from typing import List, Dict, Any, Optional, Tuple
import sys
import io
from pathlib import Path

app_dir = Path(__file__).parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))



import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from core.dhondt import calculate_dhondt
from core.stepped_chart import create_dhondt_stepped_chart, get_party_color
from core.national_model import SpanishElectoralModel, BASELINE_NATIONAL_2023, TOTAL_VALID_VOTES_2023
from core.toponyms import (
    normalize_province_name,
    are_same_province,
    get_province_display_name,
    is_andalusian_province,
    PROVINCES_DATA,
    CCAA_PROVINCES,
)
from core.electoral_map import (
    load_spain_geojson,
    build_constituency_electoral_summary,
    create_spain_electoral_map,
    render_electoral_map_section,
)
from analysis.coalition_analyzer import CoalitionAnalyzer
import importlib
import analysis.government_optimizer
importlib.reload(analysis.government_optimizer)
from analysis.government_optimizer import (
    GovernmentOptimizer,
    GovernmentOptimizationConfig,
    render_government_formation_section,
)
from data.poll_connector import PollConnector, BENCHMARK_POLLS
from core.i18n import t, set_lang, get_current_lang, SUPPORTED_LANGUAGES

# Configuración de página
st.set_page_config(
    page_title="Simulador Electoral D'Hondt - Laboratorio Político",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Inicializar modelos y conectores mediante st.cache_resource con versionado RD 806/2026
@st.cache_resource
def get_electoral_model(model_version: str = "rd806_2026_nov29") -> SpanishElectoralModel:
    return SpanishElectoralModel()

@st.cache_resource
def get_poll_connector() -> PollConnector:
    return PollConnector()

@st.cache_resource
def get_coalition_analyzer(model_version: str = "rd806_2026_nov29") -> CoalitionAnalyzer:
    return CoalitionAnalyzer(get_electoral_model(model_version=model_version))

model = get_electoral_model(model_version="rd806_2026_nov29")
poll_connector = get_poll_connector()
analyzer = get_coalition_analyzer(model_version="rd806_2026_nov29")

def render_mermaid(diagram_code: str, height: int = 420) -> None:
    """
    Compila y muestra visualmente un diagrama Mermaid (flowchart TD)
    dentro de Streamlit usando el motor oficial Mermaid.js en un iframe responsivo.
    """
    clean_code = diagram_code.strip()
    formatted_code = clean_code.replace("\\n", "<br/>")
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                margin: 0;
                padding: 12px;
                background-color: transparent;
                display: flex;
                justify-content: center;
                align-items: flex-start;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }}
            .mermaid-wrapper {{
                width: 100%;
                display: flex;
                justify-content: center;
            }}
            .mermaid {{
                width: 100%;
                text-align: center;
            }}
            .mermaid svg {{
                max-width: 100% !important;
                height: auto !important;
                filter: drop-shadow(0px 2px 6px rgba(0,0,0,0.06));
            }}
            #fallback {{
                display: none;
                padding: 14px;
                border: 1px dashed #cbd5e0;
                border-radius: 8px;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                font-size: 13px;
                color: #2d3748;
                background: #f7fafc;
                white-space: pre-wrap;
                text-align: left;
                width: 100%;
            }}
        </style>
    </head>
    <body>
        <div class="mermaid-wrapper">
            <div id="mermaid-graph" class="mermaid">
{formatted_code}
            </div>
            <div id="fallback">
{clean_code}
            </div>
        </div>
        <script>
            try {{
                mermaid.initialize({{
                    startOnLoad: true,
                    theme: 'neutral',
                    securityLevel: 'loose',
                    flowchart: {{
                        useMaxWidth: true,
                        htmlLabels: true,
                        curve: 'basis'
                    }}
                }});
            }} catch (err) {{
                console.error("Error al inicializar Mermaid:", err);
                document.getElementById('mermaid-graph').style.display = 'none';
                document.getElementById('fallback').style.display = 'block';
            }}
            window.addEventListener('error', function() {{
                var g = document.getElementById('mermaid-graph');
                if (g && (!g.querySelector('svg') || g.textContent.includes('Syntax error'))) {{
                    g.style.display = 'none';
                    document.getElementById('fallback').style.display = 'block';
                }}
            }});
        </script>
    </body>
    </html>
    """
    try:
        if hasattr(st, "iframe"):
            st.iframe(html_template, height=height, width="stretch")
        else:
            components.html(html_template, height=height, scrolling=True)
    except Exception:
        components.html(html_template, height=height, scrolling=True)


@st.cache_data(show_spinner=False)
def get_all_electoral_datasets(dataset_version: str = "rd806_2026_nov29") -> Dict[str, pd.DataFrame]:
    """
    Construye los 4 DataFrames canónicos del modelo electoral:
    1. Censo y Escaños de la convocatoria oficial 29N 2026 (RD 806/2026 e INE cerrado a 1 agosto 2026)
    2. Porcentajes de voto 23J por circunscripción (%)
    3. Escaños 23J obtenidos por candidatura
    4. Sondeos y encuestas integradas (intención de voto nacional)
    """
    active_model = get_electoral_model(model_version=dataset_version)
    p2c = {normalize_province_name(p): ccaa for ccaa, provs in CCAA_PROVINCES.items() for p in provs}
    total_census = sum(c["census"] for c in active_model.constituencies)
    total_seats = sum(c["seats"] for c in active_model.constituencies)
    
    # 1. Censo y Escaños
    rows_censo = []
    for c in active_model.constituencies:
        canon = normalize_province_name(c["name"])
        ccaa = p2c.get(canon, "Otras")
        disp = c.get("display_name", c["name"])
        seats = int(c["seats"])
        census = int(c["census"])
        
        rows_censo.append({
            "Circunscripción": disp,
            "Comunidad Autónoma": ccaa,
            "Diputados (Escaños)": seats,
            "% de la Cámara": round((seats / total_seats) * 100, 2),
            "Censo Electoral": census,
            "% del Censo Nacional": round((census / total_census) * 100, 2),
            "Electores por Escaño": round(census / seats),
        })
    df_censo = pd.DataFrame(rows_censo)
    
    # 2. Porcentajes 23J por circunscripción
    all_parties = sorted(list(active_model.parties))
    rows_pct = []
    for c in active_model.constituencies:
        canon = normalize_province_name(c["name"])
        row = {
            "Circunscripción": c.get("display_name", c["name"]),
            "Comunidad Autónoma": p2c.get(canon, "Otras"),
            "Diputados": c["seats"],
            "Censo": c["census"],
            "Votos Válidos": c["valid_votes"],
        }
        p_pct = c.get("parties_pct", {})
        for p in all_parties:
            row[p] = p_pct.get(p, 0.0)
        rows_pct.append(row)
    df_pct = pd.DataFrame(rows_pct).fillna(0.0)

    # 3. Escaños 23J por circunscripción
    rows_seats = []
    for c in active_model.constituencies:
        canon = normalize_province_name(c["name"])
        row = {
            "Circunscripción": c.get("display_name", c["name"]),
            "Comunidad Autónoma": p2c.get(canon, "Otras"),
            "Total Escaños": c["seats"],
        }
        p_seats = c.get("parties_seats", {})
        for p in all_parties:
            row[p] = p_seats.get(p, 0)
        rows_seats.append(row)
    df_seats = pd.DataFrame(rows_seats).fillna(0)

    # 4. Sondeos integrados
    rows_polls = []
    for name in poll_connector.get_available_poll_names():
        pdata = poll_connector.get_poll(name)
        row = {
            "Sondeo / Empresa": name,
            "Fecha Publicación": pdata.get("date", "-"),
            "Muestra": str(pdata.get("sample", "-")),
            "Participación Est. (%)": pdata.get("turnout", "-"),
        }
        poll_pcts = pdata.get("poll", {})
        for p in all_parties:
            row[p] = poll_pcts.get(p, 0.0)
        if "SALF" in poll_pcts:
            row["SALF"] = poll_pcts["SALF"]
        rows_polls.append(row)
    df_polls = pd.DataFrame(rows_polls).fillna(0.0)

    return {
        "Censo y Escaños Vigentes": df_censo,
        "Porcentajes 23J por Circunscripción": df_pct,
        "Escaños 23J por Circunscripción": df_seats,
        "Catálogo de Sondeos Integrados": df_polls,
    }


@st.cache_data
def get_consolidated_electoral_excel() -> bytes:
    """
    Genera en memoria un archivo Excel (.xlsx) con 4 hojas que agrupa todas las fuentes del modelo.
    """
    datasets = get_all_electoral_datasets()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        datasets["Censo y Escaños Vigentes"].to_excel(writer, sheet_name="Censo_y_Escaños", index=False)
        datasets["Porcentajes 23J por Circunscripción"].to_excel(writer, sheet_name="Porcentajes_23J", index=False)
        datasets["Escaños 23J por Circunscripción"].to_excel(writer, sheet_name="Escaños_23J", index=False)
        datasets["Catálogo de Sondeos Integrados"].to_excel(writer, sheet_name="Sondeos_Demoscópicos", index=False)
    return output.getvalue()


@st.cache_data
def get_electoral_situation_df() -> pd.DataFrame:
    """
    Genera el DataFrame canónico de la situación electoral de España
    (censo y escaños de las 52 circunscripciones según LOREG y RD 806/2026).
    """
    return get_all_electoral_datasets()["Censo y Escaños Vigentes"]

def safe_simulate(model_obj, *args, **kwargs):
    try:
        return model_obj.simulate(*args, **kwargs)
    except TypeError as e:
        if "is_official_23j" in str(e) or "party_multiplier" in str(e):
            clean_kwargs = {k: v for k, v in kwargs.items() if k not in ["is_official_23j", "party_multiplier"]}
            return model_obj.simulate(*args, **clean_kwargs)
        raise

# Inicializar estados en session_state
if "constituency_overrides" not in st.session_state:
    st.session_state.constituency_overrides = {}

if "global_coalition_config" not in st.session_state:
    st.session_state.global_coalition_config = {
        "name": "Lista Única Izquierdas",
        "members": ["Sumar", "Podemos"],
        "retention_by_party": {"Sumar": 1.0, "Podemos": 1.0},
    }

if "custom_excel_poll" not in st.session_state:
    st.session_state.custom_excel_poll = None

# Presets territoriales para configuración de candidaturas
TERRITORIAL_PRESETS: Dict[str, List[str]] = {
    "Nacional (52 circunscripciones)": model.get_constituency_names(),
    "Andalucía (8 provincias)": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
    "Cataluña (4 provincias)": ["Barcelona", "Girona", "Lleida", "Tarragona"],
    "País Vasco y Navarra (4 provincias)": ["Araba/Álava", "Bizkaia", "Gipuzkoa", "Navarra"],
    "Galicia (4 provincias)": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
    "C. Valenciana (3 provincias)": ["Alicante/Alacant", "Castellón/Castelló", "Valencia/València"],
    "Canarias (2 provincias)": ["Las Palmas", "Santa Cruz de Tenerife"],
    "Navarra (1 circunscripción)": ["Navarra"],
    "Asturias (1 circunscripción)": ["Asturias"],
    "Murcia (1 circunscripción)": ["Murcia"],
    "Baleares (1 circunscripción)": ["Illes Balears"],
}

DEFAULT_PARTY_TERRITORIES: Dict[str, str] = {
    "PP": "Nacional (52 circunscripciones)",
    "PSOE": "Nacional (52 circunscripciones)",
    "Vox": "Nacional (52 circunscripciones)",
    "Sumar": "Nacional (52 circunscripciones)",
    "Podemos": "Nacional (52 circunscripciones)",
    "SALF": "Nacional (52 circunscripciones)",
    "Adelante Andalucía": "Andalucía (8 provincias)",
    "ERC": "Cataluña (4 provincias)",
    "Junts": "Cataluña (4 provincias)",
    "CUP": "Cataluña (4 provincias)",
    "EH Bildu": "País Vasco y Navarra (4 provincias)",
    "PNV": "País Vasco y Navarra (4 provincias)",
    "BNG": "Galicia (4 provincias)",
    "Compromís": "C. Valenciana (3 provincias)",
    "CC": "Canarias (2 provincias)",
    "UPN": "Navarra (1 circunscripción)",
}

if "global_party_scope" not in st.session_state:
    st.session_state.global_party_scope = {
        p: list(TERRITORIAL_PRESETS.get(scope_name, model.get_constituency_names()))
        for p, scope_name in DEFAULT_PARTY_TERRITORIES.items()
    }

def get_all_poll_options() -> List[str]:
    opts = poll_connector.get_available_poll_names()
    if st.session_state.get("custom_excel_poll"):
        opts = ["Encuesta Importada desde Excel"] + opts
    return opts

def load_poll_data_by_name(poll_name: str) -> Dict[str, float]:
    if poll_name == "Encuesta Importada desde Excel" and st.session_state.get("custom_excel_poll"):
        return dict(st.session_state.custom_excel_poll)
    poll_info = poll_connector.get_poll(poll_name)
    if poll_info and "poll" in poll_info:
        return dict(poll_info["poll"])
    return dict(BASELINE_NATIONAL_2023)

def get_poll_date(poll_name: str) -> str:
    if poll_name == "Encuesta Importada desde Excel":
        return str(st.session_state.get("custom_excel_poll_date", "Fecha de archivo importado"))
    return poll_connector.get_poll_date(poll_name)

def get_poll_turnout(poll_name: str) -> float:
    if poll_name == "Encuesta Importada desde Excel":
        return float(st.session_state.get("custom_excel_poll_turnout", 68.0))
    poll_info = poll_connector.get_poll(poll_name)
    if poll_info and "turnout" in poll_info:
        try:
            return float(poll_info["turnout"])
        except (ValueError, TypeError):
            pass
    return 66.59

# Sondeo base global siempre definido
current_poll = load_poll_data_by_name("Resultados Oficiales 23J (2023)")

# Cabecera principal e internacionalización (i18n)
current_lang = get_current_lang()

with st.sidebar:
    st.markdown("### 🌐 " + ("Idioma / Language" if current_lang == "es" else "Language / Idioma"))
    sidebar_lang = st.radio(
        t("lang_selector_label"),
        options=list(SUPPORTED_LANGUAGES.keys()),
        format_func=lambda code: SUPPORTED_LANGUAGES[code],
        index=0 if current_lang == "es" else 1,
        key="sidebar_lang_radio",
        label_visibility="collapsed",
    )
    if sidebar_lang != current_lang:
        set_lang(sidebar_lang)
        st.rerun()

col_title, col_lang = st.columns([5.2, 1.4])
with col_title:
    st.title(t("app_title"))
    st.markdown(t("app_subtitle"))

with col_lang:
    header_lang = st.selectbox(
        t("lang_selector_label"),
        options=list(SUPPORTED_LANGUAGES.keys()),
        format_func=lambda code: SUPPORTED_LANGUAGES[code],
        index=0 if current_lang == "es" else 1,
        key="header_lang_select",
    )
    if header_lang != current_lang:
        set_lang(header_lang)
        st.rerun()

# Pestañas principales estructuradas según especificación
tab1, tab2, tab3, tab4 = st.tabs([
    t("tab1_name"),
    t("tab2_name"),
    t("tab3_name"),
    t("tab4_name"),
])

# ==============================================================================
# SECCIÓN 1: SIMULACIÓN NACIONAL SIMPLE
# ==============================================================================
with tab1:
    st.header(t("tab1_header"))
    st.markdown(t("tab1_desc"))

    with st.container(border=True):
        st.subheader(t("config_box_title"))

        # Fila 1: Selección de Sondeo y Partidos en Coalición
        col_poll, col_coal_m, col_coal_n = st.columns([1.2, 1.4, 1.0])

        with col_poll:
            all_poll_options = get_all_poll_options()
            simple_poll_name = st.selectbox(
                t("poll_select_label"),
                all_poll_options,
                index=1 if "Encuesta Importada desde Excel" not in all_poll_options else 0,
                key="s1_poll_select",
            )
            s1_poll_dict = load_poll_data_by_name(simple_poll_name)
            current_poll = s1_poll_dict
            s1_poll_date = get_poll_date(simple_poll_name)
            s1_poll_info = poll_connector.get_poll(simple_poll_name) or {}
            s1_source_name = s1_poll_info.get("source", "Oficial / Proyección")
            s1_sample_name = s1_poll_info.get("sample", "N/A")
            s1_poll_def_t = get_poll_turnout(simple_poll_name)
            st.caption(f"📅 **{t('pub_date')}** {s1_poll_date} • 🏢 **{t('source')}** {s1_source_name} • 👥 **{t('sample')}** {s1_sample_name}")

        # Detección de cambio de sondeo en Tab 1 para sincronizar estado de widgets
        if st.session_state.get("s1_last_poll_name") != simple_poll_name:
            st.session_state["s1_last_poll_name"] = simple_poll_name
            st.session_state["s1_macro_turnout"] = s1_poll_def_t
            if "s1_turnout_widget" in st.session_state:
                st.session_state["s1_turnout_widget"] = s1_poll_def_t
            # Limpiar cualquier clave previa de ajuste para que el nuevo sondeo cargue sus datos reales
            for k in list(st.session_state.keys()):
                if k.startswith("s1_p_"):
                    del st.session_state[k]

        available_poll_parties = list(s1_poll_dict.keys())
        default_coal_p = [p for p in ["Sumar", "Podemos"] if p in available_poll_parties]
        if not default_coal_p and len(available_poll_parties) >= 2:
            default_coal_p = available_poll_parties[:2]

        # Validar y sincronizar miembros de la coalición guardados en sesión
        if "s1_coal_members_select" in st.session_state:
            valid_mems = [m for m in st.session_state["s1_coal_members_select"] if m in available_poll_parties]
            st.session_state["s1_coal_members_select"] = valid_mems if valid_mems else default_coal_p

        with col_coal_m:
            s1_coal_members = st.multiselect(
                t("coalition_members_label"),
                options=available_poll_parties,
                default=default_coal_p,
                key="s1_coal_members_select",
                help=t("coalition_members_help"),
            )

        with col_coal_n:
            s1_coal_name = st.text_input(
                t("coalition_name_label"),
                value="Lista Única" if current_lang == "es" else "Single List",
                key="s1_coal_name_input",
                help=t("coalition_name_help"),
            )

        # Fila 2: Participación, Tasa de Retención, Umbral Legal y Votos en Blanco
        c_turnout, c2, c3, c4 = st.columns([1.1, 1.2, 0.9, 0.9])

        with c_turnout:
            if "s1_macro_turnout" not in st.session_state:
                st.session_state["s1_macro_turnout"] = s1_poll_def_t
            s1_turnout_pct = st.number_input(
                t("turnout_label"),
                min_value=15.0,
                max_value=98.0,
                value=float(st.session_state.get("s1_macro_turnout", s1_poll_def_t)),
                step=0.5,
                key="s1_turnout_widget",
                help=t("turnout_help"),
            )
            st.session_state["s1_macro_turnout"] = s1_turnout_pct

        with c2:
            s1_retention_pct = st.slider(
                t("retention_label"),
                min_value=40,
                max_value=120,
                value=100,
                step=1,
                help=t("retention_help"),
                key="s1_retention_slider",
            )
            s1_retention_rate = s1_retention_pct / 100.0

        # Guardar en sesión para sincronización entre simulaciones si Tab 3 no ha sido personalizada manualmente
        st.session_state["s1_active_coal_members"] = list(s1_coal_members)
        st.session_state["s1_active_coal_name"] = s1_coal_name
        if "s3_custom_configured" not in st.session_state and "global_coalition_config" in st.session_state and s1_coal_members:
            st.session_state.global_coalition_config["name"] = s1_coal_name
            st.session_state.global_coalition_config["members"] = list(s1_coal_members)
            st.session_state.global_coalition_config["retention_by_party"] = {p: s1_retention_rate for p in s1_coal_members}

        with c3:
            s1_threshold_pct = st.number_input(
                t("threshold_label"),
                min_value=0.0,
                max_value=10.0,
                value=3.0,
                step=0.5,
                key="s1_threshold_input",
            )

        with c4:
            s1_blank_pct = st.number_input(
                t("blank_label"),
                min_value=0.0,
                max_value=5.0,
                value=0.8,
                step=0.1,
                key="s1_blank_input",
            )

        expander_cand_title = (
            f"📋 **Lista de candidaturas tomadas en este sondeo ({simple_poll_name}) — Total: {len(s1_poll_dict)} partidos**"
            if current_lang == "es"
            else f"📋 **Parties included in this poll ({simple_poll_name}) — Total: {len(s1_poll_dict)} parties**"
        )
        with st.expander(expander_cand_title, expanded=False):
            st.markdown(
                f"Relación de todas las fuerzas políticas computadas a nivel nacional en **{simple_poll_name}** y su porcentaje estimado:"
                if current_lang == "es"
                else f"List of all political forces computed nationally in **{simple_poll_name}** and their estimated vote share:"
            )
            cands_df = pd.DataFrame([
                {
                    t("col_candidacy"): p,
                    t("col_vote_intent"): f"{val:.2f}%",
                    t("col_in_coalition"): t("yes_coalition") if p in s1_coal_members else t("no_coalition"),
                    t("col_territory"): DEFAULT_PARTY_TERRITORIES.get(p, "Nacional (52 circunscripciones)" if current_lang == "es" else "National (52 constituencies)"),
                }
                for p, val in sorted(s1_poll_dict.items(), key=lambda x: -x[1])
            ])
            st.dataframe(cands_df, use_container_width=True, hide_index=True)

        with st.expander(t("adjust_poll_expander"), expanded=False):
            st.caption(t("adjust_poll_caption", poll=simple_poll_name))
            c_rst1, c_rst2 = st.columns([3, 1])
            with c_rst2:
                if st.button(t("reset_adjustments"), key=f"s1_btn_rst_{simple_poll_name}"):
                    for k in list(st.session_state.keys()):
                        if k.startswith("s1_p_"):
                            del st.session_state[k]
                    st.rerun()

            cols_p = st.columns(4)
            s1_edited_poll = {}
            for idx, (p, val) in enumerate(s1_poll_dict.items()):
                target_col = cols_p[idx % 4]
                s1_edited_poll[p] = target_col.number_input(
                    f"% {p}:", min_value=0.0, max_value=60.0, value=float(val), step=0.1, key=f"s1_p_{simple_poll_name}_{p}"
                )
            s1_poll_dict = s1_edited_poll

    # Comparativa nacional
    if len(s1_coal_members) < 2:
        st.warning("⚠️ Selecciona al menos 2 partidos en el selector superior para comparar el escenario de lista única frente a candidaturas separadas.")
    else:
        orig_poll_data = load_poll_data_by_name(simple_poll_name)
        is_poll_modified = any(
            abs(s1_poll_dict.get(p, 0.0) - float(orig_v)) > 0.01
            for p, orig_v in orig_poll_data.items()
        )
        is_turnout_modified = abs(s1_turnout_pct - s1_poll_def_t) > 0.05
        is_23j_simple = (simple_poll_name == "Oficial 23J 2023 (Congreso de los Diputados)") and not is_poll_modified and not is_turnout_modified
        if is_23j_simple:
            st.info("ℹ️ **Datos Reales Oficiales 23J:** Computando a partir de los datos exactos circunscripción a circunscripción (diputados reales y votos oficiales proclamados con 66,59% de participación definitiva oficial BOE), sin distorsión de proyección swing nacional.")
        elif simple_poll_name == "Oficial 23J 2023 (Congreso de los Diputados)":
            reason_txt = "porcentajes" if is_poll_modified and not is_turnout_modified else ("participación" if is_turnout_modified and not is_poll_modified else "porcentajes y participación")
            st.info(f"ℹ️ **Escenario 23J Personalizado:** Has ajustado la {reason_txt} del 23J. Aplicando el Modelo de Proyección de Swing Proporcional y reescalado de participación sobre la base territorial del 23J.")

        s1_comp = analyzer.compare(
            poll=s1_poll_dict,
            retention_rate=s1_retention_rate,
            custom_coalition_name=s1_coal_name,
            default_coalition_members=s1_coal_members,
            threshold_pct=s1_threshold_pct,
            blank_pct=s1_blank_pct,
            is_official_23j=is_23j_simple,
            turnout_pct=s1_turnout_pct,
        )
        s1_inv = analyzer.solve_votes_needed_to_match_target(
            poll=s1_poll_dict,
            retention_rate=s1_retention_rate,
            custom_coalition_name=s1_coal_name,
            default_coalition_members=s1_coal_members,
            threshold_pct=s1_threshold_pct,
            blank_pct=s1_blank_pct,
            is_official_23j=is_23j_simple,
            turnout_pct=s1_turnout_pct,
        )
        s1_rates, s1_coal_curve, s1_sep_const, s1_breakeven_r = analyzer.calculate_breakeven_curve(
            poll=s1_poll_dict,
            custom_coalition_name=s1_coal_name,
            default_coalition_members=s1_coal_members,
            threshold_pct=s1_threshold_pct,
            blank_pct=s1_blank_pct,
            is_official_23j=is_23j_simple,
            turnout_pct=s1_turnout_pct,
        )

        # Tarjetas de métricas
        dip_lbl = "seats" if current_lang == "en" else "dip."
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            lbl_sep = f"{t('seats')}: {t('summary_seats_separated')} ({', '.join(s1_coal_members)})" if current_lang == "en" else f"Escaños: Separados ({', '.join(s1_coal_members)})"
            st.metric(lbl_sep, f"{s1_comp.separated_left_seats} {dip_lbl}")
            st.caption(f"{t('votes')}: **{s1_comp.separated_left_votes:,.0f}**  \n{t('cost')}: **{s1_comp.separated_votes_per_seat:,.0f}** v/seat" if current_lang == "en" else f"Votos: **{s1_comp.separated_left_votes:,.0f}**  \nCoste: **{s1_comp.separated_votes_per_seat:,.0f}** v/esc.")
        with m2:
            lbl_coal = f"{t('seats')}: {s1_coal_name} ({s1_retention_pct}%)"
            diff_str = f"{s1_comp.seat_difference:+d} {dip_lbl}" if s1_comp.seat_difference != 0 else "="
            st.metric(lbl_coal, f"{s1_comp.coalition_left_seats} {dip_lbl}", delta=diff_str)
            st.caption(f"{t('votes')}: **{s1_comp.coalition_left_votes:,.0f}**  \n{t('cost')}: **{s1_comp.coalition_votes_per_seat:,.0f}** v/seat" if current_lang == "en" else f"Votos: **{s1_comp.coalition_left_votes:,.0f}**  \nCoste: **{s1_comp.coalition_votes_per_seat:,.0f}** v/esc.")
        with m3:
            fav_label = "Favorable Scenario" if current_lang == "en" else "Escenario Favorable"
            fav_text = s1_comp.more_favorable_scenario
            if current_lang == "en":
                fav_text = fav_text.replace("Coalición", "Coalition").replace("Separados", "Separated")
            st.metric(fav_label, fav_text, delta=f"{t('diff')}: {abs(s1_comp.seat_difference)} {dip_lbl}")
            st.caption("D'Hondt electoral concentration effect." if current_lang == "en" else "Efecto de concentración electoral bajo D'Hondt.")
        with m4:
            crit_label = "Breakeven Point (R*)" if current_lang == "en" else "Punto Crítico (R*)"
            if s1_breakeven_r:
                st.metric(crit_label, f"{s1_breakeven_r * 100:.1f}%")
                st.caption(f"Tolerates up to **{(1 - s1_breakeven_r)*100:.1f}% leak**." if current_lang == "en" else f"Tolera hasta **{(1 - s1_breakeven_r)*100:.1f}% de fuga**.")
            else:
                st.metric(crit_label, "N/A")

        st.markdown("---")

        # Respuesta a la Pregunta Clave
        st.subheader("💡 " + ("Key Takeaway & Analytical Verdict:" if current_lang == "en" else "Respuesta a la Pregunta Clave:"))
        with st.container(border=True):
            if s1_comp.coalition_left_seats > s1_comp.separated_left_seats:
                if current_lang == "en":
                    st.markdown(
                        f"""
                        ### 🏆 The most favorable scenario in seats is the **COALITION ({s1_coal_name})** ({s1_comp.coalition_left_seats} seats)
                        
                        Even assuming that **{100 - s1_retention_pct}% of voters are lost** due to demobilization or friction, 
                        the concentration of votes in medium-sized provinces far outweighs this loss (+{s1_comp.seat_difference} seat advantage).
                        
                        #### 🔍 For the bloc to reach these same **{s1_inv.target_seats} seats running separately**, it would need:
                        * **Additional votes needed:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s1_inv.additional_votes_needed:,.0f} votes</span> (+{s1_inv.additional_pct_needed:.2f}% national vote).
                        * **Required national vote share:** Rise from **{s1_inv.current_pct:.1f}%** to **{s1_inv.required_pct:.1f}%** (multiply votes by **{s1_inv.multiplier:.2f}x**).
                        * **Votes needed separately:** **{s1_inv.required_votes:,.0f} votes**, compared to only **{s1_comp.coalition_left_votes:,.0f} votes** sufficient for the joint ticket.
                        * **The division penalty:** Running separately wastes hundreds of thousands of votes below the effective D'Hondt quotient in 3 to 6-seat provinces.
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""
                        ### 🏆 El escenario más favorable en escaños es la **COALICIÓN ({s1_coal_name})** ({s1_comp.coalition_left_seats} escaños)
                        
                        Incluso asumiendo que un **{100 - s1_retention_pct}% de los votantes se pierde** por rechazo mutuo o abstención, 
                        la concentración de votos en las provincias medianas supera ampliamente esa pérdida (+{s1_comp.seat_difference} escaños de ventaja).
                        
                        #### 🔍 Para que el bloque consiguiera estos mismos **{s1_inv.target_seats} escaños yendo por separado**, necesitaría:
                        * **Votos adicionales requeridos:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s1_inv.additional_votes_needed:,.0f} votos</span> (+{s1_inv.additional_pct_needed:.2f}% de voto nacional).
                        * **Intención de voto necesaria:** Pasar del **{s1_inv.current_pct:.1f}%** al **{s1_inv.required_pct:.1f}%** nacional (multiplicar sus votos por **{s1_inv.multiplier:.2f}x**).
                        * **Votos necesarios por separado:** **{s1_inv.required_votes:,.0f} votos**, frente a solo **{s1_comp.coalition_left_votes:,.0f} votos** que le bastan a la lista única.
                        * **El 'peaje' de la división:** Ir por separado 'quema' cientos de miles de papeletas por debajo de la barrera efectiva de D'Hondt en provincias de 3 a 6 escaños.
                        """,
                        unsafe_allow_html=True,
                    )
            elif s1_comp.coalition_left_seats < s1_comp.separated_left_seats:
                if current_lang == "en":
                    st.markdown(
                        f"""
                        ### 🏆 The most favorable scenario is running **SEPARATELY** ({s1_comp.separated_left_seats} seats)
                        
                        With a retention rate of only **{s1_retention_pct}%**, voter leakage (**{100 - s1_retention_pct}%**) 
                        is severe enough to destroy more representation than D'Hondt salvages (+{abs(s1_comp.seat_difference)} seats in favor of running separately).
                        
                        #### 🔍 For the Coalition to match the **{s1_inv.target_seats} seats** won separately:
                        * **Additional votes needed:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s1_inv.additional_votes_needed:,.0f} votes</span>.
                        * **Required national vote share:** Reach **{s1_inv.required_pct:.1f}%** nationally.
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""
                        ### 🏆 El escenario más favorable es ir **POR SEPARADO** ({s1_comp.separated_left_seats} escaños)
                        
                        Con una retención de solo **{s1_retention_pct}%**, la fuga de votantes desencantados (**{100 - s1_retention_pct}%**) 
                        es tan severa que destruye más representación de la que D'Hondt ayuda a salvar (+{abs(s1_comp.seat_difference)} escaños a favor de ir separados).
                        
                        #### 🔍 Para que la Coalición igualara los **{s1_inv.target_seats} escaños** de ir por separado:
                        * **Votos adicionales requeridos:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s1_inv.additional_votes_needed:,.0f} votos</span>.
                        * **Intención de voto necesaria:** Alcanzar el **{s1_inv.required_pct:.1f}%** nacional.
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info(f"Both scenarios tie at exactly **{s1_comp.separated_left_seats} seats**." if current_lang == "en" else f"Ambos escenarios empatan exactamente en **{s1_comp.separated_left_seats} escaños**.")

            if s1_inv.newly_won_provinces:
                st.markdown(
                    f"**Provinces where new seats would be gained:** {', '.join(s1_inv.newly_won_provinces)}"
                    if current_lang == "en"
                    else f"**Provincias donde entrarían los nuevos escaños:** {', '.join(s1_inv.newly_won_provinces)}"
                )

            # ==================================================================
            # SECCIÓN: A QUIÉN QUITA LOS DIPUTADOS EXTRA EL MEJOR ESCENARIO
            # ==================================================================
            st.markdown("---")
            winner_scen = s1_comp.more_favorable_scenario
            extra_seats_count = abs(s1_comp.seat_difference)

            st.subheader(f"🎯 ¿A quién quita los {extra_seats_count} diputados extra el mejor escenario ({winner_scen})?")

            if s1_comp.parties_who_lost:
                st.markdown(
                    f"Al comparar la composición del Congreso en ambos escenarios, los **+{extra_seats_count} escaños de ventaja** que consigue "
                    f"**{winner_scen}** se restan directamente a las siguientes fuerzas políticas rivales:"
                )

                # Tarjetas de pérdida de escaños por fuerza política
                lost_items = sorted(s1_comp.parties_who_lost.items(), key=lambda x: -x[1])
                cols_lost = st.columns(min(len(lost_items), 5))
                for idx, (p_lost, n_seats) in enumerate(lost_items):
                    col_target = cols_lost[idx % len(cols_lost)]
                    p_sep_tot = s1_comp.separated_result.national_seats.get(p_lost, 0)
                    p_coal_tot = s1_comp.coalition_result.national_seats.get(p_lost, 0)
                    seats_before = p_sep_tot if winner_scen == "Coalición" else p_coal_tot
                    seats_after = p_coal_tot if winner_scen == "Coalición" else p_sep_tot
                    with col_target.container(border=True):
                        st.metric(
                            label=f"Restado a {p_lost}",
                            value=f"-{n_seats} dip.",
                            delta=f"{seats_before} ➔ {seats_after} dip.",
                            delta_color="inverse",
                        )

                # Desglose circunscripción a circunscripción
                if s1_comp.seat_takeovers:
                    with st.expander(f"📍 **Ver en qué circunscripciones y a qué partidos se quita cada escaño ({len(s1_comp.seat_takeovers)} distritos)**", expanded=True):
                        st.markdown(
                            f"Detalle provincia a provincia de los escaños arrebatados por **{winner_scen}** "
                            f"al superar el cociente de corte D'Hondt frente a sus rivales:"
                        )
                        takeover_table_data = []
                        for row in s1_comp.seat_takeovers:
                            takeover_table_data.append({
                                "Circunscripción": get_province_display_name(row["province"]),
                                "Escenario Ganador": row["winner_scenario"],
                                "Escaños Arrebatados": f"+{row['seats_lost']}",
                                "Fuerza Perjudicada": row["party_lost"],
                                "Evolución Rival": f"Baja de {row['party_seats_before']} a {row['party_seats_after']} escaños",
                                "Evolución del Bloque": f"Sube de {row['block_seats_before']} a {row['block_seats_after']} escaños",
                            })
                        st.dataframe(pd.DataFrame(takeover_table_data), use_container_width=True, hide_index=True)
            else:
                st.info("No se produjeron transferencias netas de escaños con otras formaciones políticas.")

        # Gráfica de escaños obtenidos en el Congreso según esta aproximación (Nacional Simple)
        st.markdown("---")
        st.subheader("🏛️ Distribución y Comparativa de Escaños en el Congreso (350 escaños)")
        st.markdown(
            f"Representación parlamentaria proyectada a partir de **{simple_poll_name}**, comparando el escenario de "
            f"**Candidaturas Separadas** frente a la **{s1_coal_name}** con un **{s1_retention_pct}% de retención**."
        )

        all_rep_parties = []
        for p, s in s1_comp.separated_result.national_seats.items():
            if s > 0 and p not in all_rep_parties:
                all_rep_parties.append(p)
        for p, s in s1_comp.coalition_result.national_seats.items():
            if s > 0 and p not in all_rep_parties:
                all_rep_parties.append(p)

        all_rep_parties.sort(key=lambda p: -(max(s1_comp.separated_result.national_seats.get(p, 0), s1_comp.coalition_result.national_seats.get(p, 0))))

        df_seats_compare = pd.DataFrame([
            {
                "Partido": p,
                "Escaños Separados": s1_comp.separated_result.national_seats.get(p, 0),
                "Escaños Coalición": s1_comp.coalition_result.national_seats.get(p, 0),
                "Color": get_party_color(p),
            }
            for p in all_rep_parties
        ])

        fig_s1_seats = go.Figure()
        fig_s1_seats.add_trace(go.Bar(
            name="Candidaturas Separadas",
            x=df_seats_compare["Partido"],
            y=df_seats_compare["Escaños Separados"],
            text=df_seats_compare["Escaños Separados"],
            textposition="outside",
            marker_color=[get_party_color(p) for p in df_seats_compare["Partido"]],
            opacity=0.75,
            textfont=dict(color="#000000", size=11, family="sans-serif"),
        ))
        fig_s1_seats.add_trace(go.Bar(
            name=f"Con {s1_coal_name} ({s1_retention_pct}%)",
            x=df_seats_compare["Partido"],
            y=df_seats_compare["Escaños Coalición"],
            text=df_seats_compare["Escaños Coalición"],
            textposition="outside",
            marker_color=[get_party_color(p) if p != s1_coal_name else "#4A148C" for p in df_seats_compare["Partido"]],
            textfont=dict(color="#000000", size=11, family="sans-serif"),
        ))

        fig_s1_seats.add_hline(
            y=176,
            line_dash="dash",
            line_color="#000000",
            line_width=1.8,
            annotation_text="<b>Mayoría Absoluta (176)</b>",
            annotation_position="top left",
            annotation_font=dict(color="#000000", size=12, family="sans-serif"),
            annotation_bgcolor="#FFFFFF",
            annotation_bordercolor="#000000",
            annotation_borderwidth=1.2,
        )

        fig_s1_seats.update_layout(
            barmode="group",
            font=dict(color="#000000", family="sans-serif", size=12),
            title=dict(
                text=f"<b>Composición del Congreso según Escenario - 350 escaños</b><br><sup>Procedencia de datos: {simple_poll_name} • Fecha de publicación: {s1_poll_date}</sup>",
                font=dict(color="#000000", size=16),
            ),
            xaxis=dict(
                title=dict(text="<b>Fuerza Política</b>", font=dict(color="#000000", size=13)),
                tickfont=dict(color="#000000", size=11),
            ),
            yaxis=dict(
                title=dict(text="<b>Diputados Obtenidos</b>", font=dict(color="#000000", size=13)),
                tickfont=dict(color="#000000", size=11),
                gridcolor="#E2E8F0",
            ),
            legend=dict(font=dict(color="#000000", size=11)),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            margin=dict(l=60, r=40, t=65, b=80),
        )
        fig_s1_seats.add_annotation(
            xref="paper", yref="paper",
            x=0.0, y=-0.22,
            text=f"Procedencia de datos: {simple_poll_name} | Fecha de publicación: {s1_poll_date} | Total cámara: 350 escaños",
            showarrow=False,
            font=dict(color="#000000", size=11, family="sans-serif"),
        )
        st.plotly_chart(fig_s1_seats, use_container_width=True)

        with st.expander("📉 **Curva de Sensibilidad y Rentabilidad según Tasa de Retención (R*)**", expanded=False):
            df_curve = pd.DataFrame({
                "Retención (%)": [r * 100 for r in s1_rates],
                "Escaños Coalición": s1_coal_curve,
                "Escaños Separados": [s1_sep_const] * len(s1_rates),
            })
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(
                x=df_curve["Retención (%)"],
                y=df_curve["Escaños Coalición"],
                mode="lines+markers",
                name=f"{s1_coal_name} ({', '.join(s1_coal_members)})",
                line=dict(color="#4A148C", width=2.8),
                marker=dict(size=6, color="#4A148C"),
            ))
            fig_curve.add_trace(go.Scatter(
                x=df_curve["Retención (%)"],
                y=df_curve["Escaños Separados"],
                mode="lines",
                name=f"Separados ({', '.join(s1_coal_members)})",
                line=dict(color="#D55E00", width=2.5, dash="dash"),
            ))
            if s1_breakeven_r:
                fig_curve.add_vline(
                    x=s1_breakeven_r * 100,
                    line_dash="dot",
                    line_color="#000000",
                    line_width=1.8,
                    annotation_text=f"<b>Punto Crítico R*: {s1_breakeven_r*100:.1f}%</b>",
                    annotation_font=dict(color="#000000", size=11, family="sans-serif"),
                    annotation_bgcolor="#FFFFFF",
                )
            fig_curve.update_layout(
                font=dict(color="#000000", family="sans-serif", size=12),
                title=dict(
                    text=f"<b>Evolución de Escaños de la Coalición según Tasa de Retención / Fuga</b><br><sup>Procedencia de datos: {simple_poll_name} • Fecha de publicación: {s1_poll_date}</sup>",
                    font=dict(color="#000000", size=15),
                ),
                xaxis=dict(
                    title=dict(text="<b>Tasa de Retención de la Coalición (%)</b>", font=dict(color="#000000", size=12)),
                    tickfont=dict(color="#000000", size=11),
                    gridcolor="#E2E8F0",
                ),
                yaxis=dict(
                    title=dict(text="<b>Diputados Obtenidos</b>", font=dict(color="#000000", size=12)),
                    tickfont=dict(color="#000000", size=11),
                    gridcolor="#E2E8F0",
                ),
                plot_bgcolor="#FFFFFF",
                paper_bgcolor="#FFFFFF",
                legend=dict(font=dict(color="#000000", size=11)),
                margin=dict(l=60, r=40, t=65, b=70),
            )
            fig_curve.add_annotation(
                xref="paper", yref="paper",
                x=0.0, y=-0.18,
                text=f"Procedencia de datos: {simple_poll_name} | Fecha de publicación: {s1_poll_date}",
                showarrow=False,
                font=dict(color="#000000", size=11, family="sans-serif"),
            )
            st.plotly_chart(fig_curve, use_container_width=True)

        # ==============================================================================
        # MAPA ELECTORAL INTERACTIVO DE ESPAÑA (52 CIRCUNSCRIPCIONES)
        # ==============================================================================
        st.markdown("---")
        render_electoral_map_section(
            sim_result=s1_comp.coalition_result,
            comparison_result=s1_comp.separated_result,
            section_key="s1",
            coalition_name=s1_coal_name,
            coalition_members=s1_coal_members,
            poll_name=simple_poll_name,
            poll_date=s1_poll_date,
            allow_coalition_mode=True,
        )

        # Gráfica escalonada descendente D'Hondt
        st.markdown("---")
        st.subheader("📈 La Carrera por los Escaños: Gráfica Escalonada Descendente")
        st.markdown(
            """
            * En el **eje Y (vertical)** se ubican los **votos / cocientes** tomados para el reparto ($V / 1, V / 2, V / 3 \dots$).  
            * En el **eje X (horizontal)** se ubican los **escaños conseguidos**.  
            * La **línea horizontal discontinua roja** marca el cociente de corte (último escaño repartido).
            """
        )

        sc_col1, sc_col2 = st.columns([1, 1])
        with sc_col1:
            s1_prov = st.selectbox(
                "Seleccionar Circunscripción para ver la gráfica:",
                model.get_constituency_names(),
                index=model.get_constituency_names().index("Madrid") if "Madrid" in model.get_constituency_names() else 0,
                format_func=get_province_display_name,
                key="s1_stepped_prov_select",
            )
        with sc_col2:
            s1_scenario_view = st.radio(
                "Escenario a visualizar en la gráfica:",
                [f"{s1_coal_name} (Coalición)", f"Separados ({', '.join(s1_coal_members)})"],
                horizontal=True,
                key="s1_stepped_scenario_radio",
            )

        sim_for_s1_chart = s1_comp.coalition_result if "Coalición" in s1_scenario_view else s1_comp.separated_result

        s1_p_data = next((c for c in sim_for_s1_chart.constituency_data if are_same_province(c["name"], s1_prov)), sim_for_s1_chart.constituency_data[0])
        s1_res = sim_for_s1_chart.constituency_results.get(s1_prov) or s1_p_data["result"]

        ds_s1_stepped = (
            f"Resultados Oficiales 23J (Votos y diputados exactos por circunscripción) — {s1_scenario_view}"
            if is_23j_simple
            else f"Sondeo / Proyección: {simple_poll_name} ({s1_scenario_view})"
        )
        fig_s1_stepped = create_dhondt_stepped_chart(
            votes=s1_p_data["parties_votes"],
            result=s1_res,
            title=f"Circunscripción de {get_province_display_name(s1_prov)} ({s1_p_data['seats']} escaños)",
            data_source=ds_s1_stepped,
            poll_date=s1_poll_date,
        )
        st.plotly_chart(fig_s1_stepped, use_container_width=True, key=f"s1_stepped_chart_{s1_prov}")

        # Desglose de candidaturas en la circunscripción (Admitidas vs. Excluidas por barrera legal)
        st.markdown(f"#### 📋 Relación de Candidaturas en la Circunscripción de {s1_prov} ({s1_scenario_view}):")
        st.caption(
            f"En virtud del artículo 163 de la LOREG, el umbral legal para participar en el reparto de escaños en {s1_prov} es del **{s1_threshold_pct:.1f}% de los votos válidos** "
            f"({s1_res.threshold_votes:,.0f} votos sobre un total proyectado de {s1_res.valid_votes:,.0f} votos válidos). "
            f"Las candidaturas que no superan este umbral quedan legalmente excluidas y no generan peldaño en la gráfica escalonada."
        )

        s1_admitted_rows = []
        s1_excluded_rows = []
        s1_non_running = []

        for p, v in sorted(s1_p_data["parties_votes"].items(), key=lambda x: -x[1]):
            v_pct = (v / s1_res.valid_votes * 100.0) if s1_res.valid_votes > 0 else 0.0
            seats_won = s1_res.seats.get(p, 0)
            if v <= 0:
                s1_non_running.append(p)
            elif p in s1_res.excluded_parties:
                gap = max(0.0, s1_res.threshold_votes - v)
                s1_excluded_rows.append({
                    "Candidatura": p,
                    "Votos Estimados": f"{v:,.0f}",
                    "% Voto Válido": f"{v_pct:.2f}%",
                    "Escaños": 0,
                    "Votos Faltantes para Umbral": f"+{gap:,.0f} votos",
                    "Estado en Gráfica": "❌ Excluida (< 3% legal)",
                })
            else:
                s1_admitted_rows.append({
                    "Candidatura": p,
                    "Votos Estimados": f"{v:,.0f}",
                    "% Voto Válido": f"{v_pct:.2f}%",
                    "Escaños Obtenidos": seats_won,
                    "Cociente Último Escaño": f"{v / max(1, seats_won):,.0f}" if seats_won > 0 else f"{v:,.0f}",
                    "Estado en Gráfica": "✅ En el reparto (Visible)",
                })

        col_adm, col_exc = st.columns(2)
        with col_adm:
            st.markdown(f"**Candidaturas que superan el umbral legal ({len(s1_admitted_rows)}):**")
            if s1_admitted_rows:
                st.dataframe(pd.DataFrame(s1_admitted_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Ninguna candidatura ha superado el umbral legal en esta simulación.")

        with col_exc:
            st.markdown(f"**Candidaturas por debajo del umbral del {s1_threshold_pct:.1f}% ({len(s1_excluded_rows)}):**")
            if s1_excluded_rows:
                st.dataframe(pd.DataFrame(s1_excluded_rows), use_container_width=True, hide_index=True)
            else:
                st.success("Todas las candidaturas con votos superaron la barrera legal.")

        if s1_non_running:
            with st.expander(f"Candidaturas del sondeo no concurrentes en {s1_prov} ({len(s1_non_running)})", expanded=False):
                st.caption(f"Fuerzas de ámbito autonómico o sin presencia en esta circunscripción: {', '.join(s1_non_running)}")

        # ==============================================================================
        # SECCIÓN DE GOBERNABILIDAD Y MAYORÍA DE INVESTIDURA (176 ESCAÑOS)
        # ==============================================================================
        st.markdown("---")
        render_government_formation_section(
            model=model,
            sim_sep=s1_comp.separated_result,
            sim_coal=s1_comp.coalition_result,
            section_key="s1",
            coalition_name=s1_coal_name,
            coalition_members=s1_coal_members,
            default_target=176,
        )

# ==============================================================================
# SECCIÓN 2: SIMULACIÓN COMPLEJA DE UNA SOLA CIRCUNSCRIPCIÓN
# ==============================================================================
with tab2:
    st.header(t("tab2_header"))
    st.markdown(t("tab2_desc"))

    with st.container(border=True):
        st.subheader("📥 Cargar Base o Diseñar Circunscripción")
        base_source_choice = st.radio(
            "Punto de partida de los datos:",
            ["Cargar desde datos oficiales 23J / Sondeo de una provincia real", "Diseño libre desde plantilla"],
            horizontal=True,
            key="s2_base_choice",
        )

        init_prov_name = "Sevilla"
        init_census = 1_540_000
        init_turnout = 69.5
        init_null = 1.1
        init_blank = 0.9
        init_seats = 12
        init_threshold = 3.0
        init_parties = {"PP": 380000, "PSOE": 340000, "Vox": 140000, "Sumar": 125000, "Podemos": 50000, "Adelante Andalucía": 32000}

        if base_source_choice == "Cargar desde datos oficiales 23J / Sondeo de una provincia real":
            s2_c_col1, s2_c_col2 = st.columns([1.2, 1.2])
            with s2_c_col1:
                s2_loaded_prov = st.selectbox(
                    "Seleccionar provincia base:",
                    model.get_constituency_names(),
                    index=model.get_constituency_names().index("Sevilla"),
                    format_func=get_province_display_name,
                    key="s2_loaded_prov",
                )
            with s2_c_col2:
                s2_base_type = st.radio(
                    "Tipo de datos de partida para la provincia:",
                    ["Resultados Oficiales 23J (Reales, no simulados)", "Proyectar según Sondeo"],
                    horizontal=True,
                    key="s2_base_type"
                )

            prov_obj = model.get_constituency(s2_loaded_prov)
            init_prov_name = s2_loaded_prov
            init_seats = int(prov_obj["seats"])
            init_census = int(prov_obj.get("census", round(prov_obj["valid_votes"] / 0.69)))
            init_turnout = float(prov_obj.get("turnout_pct", 66.59))
            init_null = float(prov_obj.get("null_votes_pct", 1.0))
            init_blank = float(prov_obj.get("blank_votes_pct", 0.8))

            if s2_base_type == "Resultados Oficiales 23J (Reales, no simulados)":
                s2_source_id = f"prov_{s2_loaded_prov}_oficial23j"
                init_parties = {
                    p: round((pct / 100.0) * prov_obj["valid_votes"])
                    for p, pct in prov_obj.get("parties_pct", {}).items()
                    if pct > 0
                }
            else:
                s2_poll_opts = get_all_poll_options()
                s2_chosen_poll = st.selectbox("Seleccionar sondeo a proyectar:", s2_poll_opts, key="s2_chosen_poll_prov")
                s2_source_id = f"prov_{s2_loaded_prov}_{s2_chosen_poll}"
                s2_poll_dict = load_poll_data_by_name(s2_chosen_poll)
                s2_poll_date = get_poll_date(s2_chosen_poll)
                s2_poll_info = poll_connector.get_poll(s2_chosen_poll) or {}
                poll_turnout_s2 = get_poll_turnout(s2_chosen_poll)
                st.caption(f"📅 **Publicación:** {s2_poll_date} • 🏢 **Fuente:** {s2_poll_info.get('source', 'Sondeo')} • 👥 **Muestra:** {s2_poll_info.get('sample', 'N/A')} • 📊 **Participación Sondeo:** {poll_turnout_s2:.1f}%")
                is_23j_s2 = (s2_chosen_poll == "Oficial 23J 2023 (Congreso de los Diputados)")
                baseline_sim = safe_simulate(
                    model,
                    s2_poll_dict,
                    left_scenario="separated",
                    party_constituencies=st.session_state.get("global_party_scope"),
                    is_official_23j=is_23j_s2,
                    turnout_pct=poll_turnout_s2,
                )
                c_entry = next(c for c in baseline_sim.constituency_data if are_same_province(c["name"], s2_loaded_prov))
                init_turnout = float(c_entry.get("turnout_pct", poll_turnout_s2))
                init_parties = {p: round(v) for p, v in c_entry["raw_parties_votes"].items() if v > 0}

            # Asegurar presencia de cualquier partido que obtuviera al menos el 3% en el 23J en esta circunscripción
            if prov_obj and "parties_pct" in prov_obj:
                tot_v_ref = float(prov_obj.get("valid_votes", 500000))
                for p_23j, pct_23j in prov_obj["parties_pct"].items():
                    if pct_23j >= 3.0 and p_23j not in init_parties:
                        init_parties[p_23j] = round((pct_23j / 100.0) * tot_v_ref)

            # En circunscripciones de Andalucía, asegurar presencia de Adelante Andalucía si compitió
            if is_andalusian_province(s2_loaded_prov) or (prov_obj and prov_obj.get("community") == "AND"):
                if "Adelante Andalucía" not in init_parties:
                    init_parties["Adelante Andalucía"] = round(prov_obj["valid_votes"] * 0.025)
        else:
            s2_template = st.selectbox("Seleccionar plantilla libre:", ["Provincia Mediana (6 escaños)", "Provincia Pequeña (3 escaños)", "Provincia Grande (12 escaños)"], key="s2_free_template")
            s2_source_id = f"free_{s2_template}"
            if s2_template == "Provincia Pequeña (3 escaños)":
                init_seats, init_census, init_parties = 3, 160_000, {"PP": 45000, "PSOE": 38000, "Vox": 18000, "Sumar": 8500, "Podemos": 4200}
            elif s2_template == "Provincia Grande (12 escaños)":
                init_seats, init_census, init_parties = 12, 1_400_000, {"PP": 380000, "PSOE": 340000, "Vox": 140000, "Sumar": 115000, "Podemos": 55000, "Compromís": 45000}
            else:
                init_seats, init_census, init_parties = 6, 420_000, {"PP": 115000, "PSOE": 98000, "Vox": 38000, "Sumar": 22000, "Podemos": 14000, "Candidatura Local": 9000}

        # Sincronización del origen en sesión: si cambia la provincia, tipo de datos o sondeo, se restablece el estado
        if st.session_state.get("s2_active_source_id") != s2_source_id:
            st.session_state.s2_active_source_id = s2_source_id
            st.session_state.s2_party_dict = dict(init_parties)
            st.session_state.s2_last_prov = init_prov_name
            # Limpiar claves de widgets de parámetros electorales y votos para que adopten los valores de la nueva selección
            for k in list(st.session_state.keys()):
                if k.startswith("s2_p_pct_") or k.startswith("s2_p_v_") or k in [
                    "s2_seats_in", "s2_thresh_in", "s2_census_in", "s2_turnout_in", "s2_blank_in", "s2_null_in"
                ]:
                    del st.session_state[k]

        st.markdown("---")
        st.subheader("⚖️ Parámetros Electorales de la Circunscripción")
        pe1, pe2, pe3, pe4 = st.columns(4)
        with pe1:
            s2_seats = st.number_input("Escaños a repartir (S):", min_value=1, max_value=60, value=init_seats, key="s2_seats_in")
            s2_threshold = st.number_input("Umbral legal (%):", min_value=0.0, max_value=20.0, value=init_threshold, step=0.5, key="s2_thresh_in")
        with pe2:
            s2_census = st.number_input("Número de Electores (Censo):", min_value=1000, value=int(init_census), step=5000, key="s2_census_in")
            s2_turnout_pct = st.number_input("Participación (%):", min_value=10.0, max_value=100.0, value=float(init_turnout), step=0.5, key="s2_turnout_in")
        with pe3:
            s2_blank_pct = st.number_input("Votos en blanco (%):", min_value=0.0, max_value=10.0, value=float(init_blank), step=0.1, key="s2_blank_in")
            s2_null_pct = st.number_input("Votos nulos / no válidos (%):", min_value=0.0, max_value=10.0, value=float(init_null), step=0.1, key="s2_null_in")
        with pe4:
            # Magnitudes calculadas
            s2_voters = (s2_turnout_pct / 100.0) * s2_census
            s2_null_votes = (s2_null_pct / 100.0) * s2_voters
            s2_valid_votes = max(1.0, s2_voters - s2_null_votes)
            s2_blank_votes = (s2_blank_pct / 100.0) * s2_valid_votes
            st.metric("Votantes Estimados", f"{s2_voters:,.0f}")
            st.metric("Votos Válidos", f"{s2_valid_votes:,.0f}")
            st.caption(f"Blancos: {s2_blank_votes:,.0f} | Nulos: {s2_null_votes:,.0f}")

        st.markdown("---")
        st.subheader("📋 Candidaturas en la Circunscripción")
        c_mode1, c_mode2 = st.columns([3, 1])
        with c_mode1:
            s2_input_mode = st.radio("Modo de edición de candidaturas:", ["Votos Absolutos", "Porcentajes (%)"], horizontal=True, key="s2_input_mode")
        with c_mode2:
            if st.button("🔄 Restaurar candidaturas", key=f"s2_btn_rst_{s2_source_id}"):
                st.session_state.s2_party_dict = dict(init_parties)
                for k in list(st.session_state.keys()):
                    if k.startswith("s2_p_pct_") or k.startswith("s2_p_v_"):
                        del st.session_state[k]
                st.rerun()

        # Botón para añadir candidatura
        with st.expander("➕ Añadir candidatura", expanded=False):
            ac1, ac2, ac3 = st.columns([2, 1, 1])
            new_cand_name = ac1.text_input("Nombre de la candidatura:", placeholder="ej. Adelante Andalucía, CUP, PACMA, Nueva Lista...", key="s2_new_cand_name")
            new_cand_val = ac2.number_input("Valor inicial (votos o %):", min_value=0.0, value=5000.0 if s2_input_mode == "Votos Absolutos" else 3.5, key="s2_new_cand_val")
            if ac3.button("Añadir a la lista", key="s2_btn_add_cand"):
                if new_cand_name.strip():
                    if s2_input_mode == "Porcentajes (%)":
                        st.session_state.s2_party_dict[new_cand_name.strip()] = round((new_cand_val / 100.0) * s2_valid_votes)
                    else:
                        st.session_state.s2_party_dict[new_cand_name.strip()] = round(new_cand_val)
                    st.success(f"Candidatura '{new_cand_name.strip()}' añadida.")
                    st.rerun()

        # Renderizar campos de cada candidatura
        cols_cands = st.columns(3)
        s2_current_votes = {}
        parties_to_delete = []

        for idx, (p_name, v_votes) in enumerate(st.session_state.s2_party_dict.items()):
            col_target = cols_cands[idx % 3]
            with col_target.container(border=True):
                c_head1, c_head2 = st.columns([3, 1])
                c_head1.markdown(f"**{p_name}**")
                if c_head2.button("🗑️", key=f"del_{p_name}", help=f"Eliminar {p_name}"):
                    parties_to_delete.append(p_name)

                if s2_input_mode == "Porcentajes (%)":
                    p_pct_init = (v_votes / s2_valid_votes) * 100.0 if s2_valid_votes > 0 else 0.0
                    p_pct_val = st.number_input(f"% de {p_name}:", min_value=0.0, max_value=80.0, value=round(p_pct_init, 2), step=0.2, key=f"s2_p_pct_{p_name}")
                    p_votes_calc = (p_pct_val / 100.0) * s2_valid_votes
                    s2_current_votes[p_name] = p_votes_calc
                    st.caption(f"Votos: **{p_votes_calc:,.0f}**")
                else:
                    p_v_val = st.number_input(f"Votos {p_name}:", min_value=0, value=int(v_votes), step=500, key=f"s2_p_v_{p_name}")
                    s2_current_votes[p_name] = float(p_v_val)
                    p_pct_calc = (p_v_val / s2_valid_votes) * 100.0 if s2_valid_votes > 0 else 0.0
                    st.caption(f"Porcentaje: **{p_pct_calc:.2f}%**")

        if parties_to_delete:
            for p_del in parties_to_delete:
                del st.session_state.s2_party_dict[p_del]
            st.rerun()

        # Guardar cambios en el diccionario
        st.session_state.s2_party_dict = {p: v for p, v in s2_current_votes.items()}

        st.markdown("---")
        st.subheader("🤝 Configuración de la Coalición y Fuga de Votos Partido a Partido")
        
        c_coal_c1, c_coal_c2 = st.columns([1, 2])
        with c_coal_c1:
            s2_coal_name = st.text_input("Nombre de la lista única:", value="Lista Única", key="s2_coal_name_in")
            available_cand_names = list(s2_current_votes.keys())
            def_coal_candidates = [p for p in ["Sumar", "Podemos", "Compromís"] if p in available_cand_names]
            if len(def_coal_candidates) < 2 and len(available_cand_names) >= 2:
                def_coal_candidates = available_cand_names[-2:]

            if "s2_coal_members_select" in st.session_state:
                valid_s2_mems = [m for m in st.session_state["s2_coal_members_select"] if m in available_cand_names]
                st.session_state["s2_coal_members_select"] = valid_s2_mems if valid_s2_mems else def_coal_candidates

            s2_coal_members = st.multiselect(
                "Seleccionar integrantes de la coalición:",
                options=available_cand_names,
                default=def_coal_candidates,
                key="s2_coal_members_select",
            )

        with c_coal_c2:
            st.markdown("**Fuga de votos partido a partido (Tasa de retención individual):**")
            st.caption("Define qué porcentaje de sus votos aporta cada fuerza a la lista única al unirse:")
            s2_ret_by_party = {}
            if s2_coal_members:
                ret_cols = st.columns(len(s2_coal_members))
                for idx, m in enumerate(s2_coal_members):
                    ret_cols[idx].markdown(f"**{m}**")
                    r_val = ret_cols[idx].slider(f"Retención % ({m}):", min_value=40, max_value=120, value=100, step=1, key=f"s2_ret_{m}")
                    s2_ret_by_party[m] = r_val / 100.0

    if len(s2_coal_members) < 2:
        st.warning("⚠️ Selecciona al menos 2 partidos para comparar el escenario de coalición frente a candidaturas separadas.")
    else:
        # Ejecutar análisis dual para esta circunscripción
        s2_comp = analyzer.compare_single_constituency(
            parties_votes=s2_current_votes,
            coalition_members=s2_coal_members,
            seats=int(s2_seats),
            blank_votes=float(s2_blank_votes),
            threshold_pct=float(s2_threshold),
            retention_rate=1.0,
            retention_by_party=s2_ret_by_party,
            coalition_name=s2_coal_name,
            census=s2_census,
            turnout_pct=s2_turnout_pct,
            null_votes=s2_null_votes,
        )

        st.markdown("### 📊 Resultados Comparativos en la Circunscripción:")
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.metric("Escaños: Separados", f"{s2_comp.separated_left_seats} esc.")
            st.caption(f"Votos: **{s2_comp.separated_left_votes:,.0f}**  \nCoste: **{s2_comp.separated_votes_per_seat:,.0f}** v/esc.")
        with r2:
            st.metric(
                f"Escaños: {s2_coal_name}",
                f"{s2_comp.coalition_left_seats} esc.",
                delta=f"{s2_comp.seat_difference:+d} esc.",
                delta_color="normal" if s2_comp.seat_difference >= 0 else "inverse",
            )
            st.caption(f"Votos: **{s2_comp.coalition_left_votes:,.0f}**  \nCoste: **{s2_comp.coalition_votes_per_seat:,.0f}** v/esc.")
        with r3:
            st.metric("Escenario Favorable", s2_comp.more_favorable_scenario)
            st.caption("En este distrito electoral.")
        with r4:
            if s2_comp.breakeven_r:
                st.metric("Umbral de Fuga (R*)", f"{s2_comp.breakeven_r * 100:.1f}%")
                st.caption(f"Tolera hasta **{(1 - s2_comp.breakeven_r)*100:.1f}% de fuga**.")
            else:
                st.metric("Umbral de Fuga", "Sin variación")
                st.caption("No cambia de escaño en el rango evaluado.")

        # Respuesta a la pregunta clave local
        st.markdown("### 💡 Respuesta a la Pregunta Clave en esta Circunscripción:")
        with st.container(border=True):
            if s2_comp.coalition_left_seats > s2_comp.separated_left_seats:
                st.markdown(
                    f"""
                    #### 🏆 La **COALICIÓN ({s2_coal_name})** obtiene **{s2_comp.coalition_left_seats} escaño(s)** frente a **{s2_comp.separated_left_seats}** por separado.
                    
                    A pesar de la fuga de votos definida partido a partido, unir fuerzas permite superar el cociente de corte de la circunscripción.
                    
                    **¿Cuántos votos adicionales necesitaría el bloque yendo por separado para conseguir ese mismo resultado ({s2_comp.target_seats} escaño/s)?**
                    * **Votos adicionales requeridos:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s2_comp.additional_votes_needed:,.0f} votos</span> (+{s2_comp.additional_pct_needed:.2f}% de los votos válidos).
                    * **Votos necesarios por separado:** **{s2_comp.required_votes:,.0f} votos**, frente a los **{s2_comp.coalition_left_votes:,.0f} votos** que le bastan a la lista única.
                    * **Candidatura más cercana al escaño:** **{s2_comp.beneficiary_party}**.
                    * **Multiplicador de votos:** Deberían multiplicar sus votos por **{s2_comp.multiplier:.2f}x**.
                    """,
                    unsafe_allow_html=True,
                )
            elif s2_comp.separated_left_seats > s2_comp.coalition_left_seats:
                st.markdown(
                    f"""
                    #### 🏆 Ir **POR SEPARADO** obtiene **{s2_comp.separated_left_seats} escaño(s)** frente a **{s2_comp.coalition_left_seats}** de la lista única.
                    
                    La fuga individual de votantes es demasiado severa y destruye representación en esta circunscripción.
                    
                    **¿Cuántos votos necesitaría la lista única para no perder ese escaño?**
                    * **Votos adicionales requeridos:** <span style="font-size: 20px; font-weight: bold; color: #D32F2F;">+{s2_comp.additional_votes_needed:,.0f} votos</span>.
                    * **Votos necesarios para la coalición:** **{s2_comp.required_votes:,.0f} votos**.
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"#### ⚖️ Ambos escenarios empatan en **{s2_comp.separated_left_seats} escaño(s)**.")

        # Gráficas escalonadas comparadas lado a lado
        st.markdown("### 📈 Comparativa Visual: Gráficas Escalonadas Descendentes")

        # Procedencia y fecha de datos para las gráficas de Tab 2
        if base_source_choice == "Cargar desde datos oficiales 23J / Sondeo de una provincia real":
            if s2_base_type == "Resultados Oficiales 23J (Reales, no simulados)":
                s2_chart_source = f"Oficial 23J (Ministerio del Interior) — {init_prov_name}"
                s2_chart_date = "23 de julio de 2023"
            else:
                s2_chart_source = f"Sondeo: {s2_chosen_poll} proyectado a {init_prov_name}"
                s2_chart_date = get_poll_date(s2_chosen_poll)
        else:
            s2_chart_source = f"Plantilla Libre ({s2_template}) — {init_prov_name}"
            s2_chart_date = "Configuración libre / manual"

        cg1, cg2 = st.columns(2)
        with cg1:
            st.markdown("##### 🔴 Escenario A: Candidaturas Separadas")
            fig_sep = create_dhondt_stepped_chart(
                votes=s2_current_votes,
                result=s2_comp.result_separated,
                title="Escenario Separados (Peldaños Divididos)",
                data_source=s2_chart_source,
                poll_date=s2_chart_date,
            )
            st.plotly_chart(fig_sep, use_container_width=True)

        with cg2:
            st.markdown(f"##### 🟣 Escenario B: {s2_coal_name} (Peldaño Unificado)")
            coal_plot_votes = {p: v for p, v in s2_current_votes.items() if p not in s2_coal_members}
            coal_plot_votes[s2_coal_name] = s2_comp.coalition_left_votes
            fig_coal = create_dhondt_stepped_chart(
                votes=coal_plot_votes,
                result=s2_comp.result_coalition,
                title=f"Escenario {s2_coal_name}",
                data_source=s2_chart_source,
                poll_date=s2_chart_date,
            )
            st.plotly_chart(fig_coal, use_container_width=True)

        # ==============================================================================
        # MAPA ELECTORAL DE CONTEXTO TERRITORIAL (CIRCUNSCRIPCIÓN EN ESPAÑA)
        # ==============================================================================
        st.markdown("---")
        if "baseline_sim" in locals() and baseline_sim is not None:
            s2_map_baseline = baseline_sim
        else:
            s2_map_baseline = safe_simulate(
                model,
                BASELINE_NATIONAL_2023,
                left_scenario="separated",
                is_official_23j=True,
            )
        render_electoral_map_section(
            sim_result=s2_map_baseline,
            section_key="s2",
            highlight_province=init_prov_name,
            is_single_province_mode=True,
        )


# ==============================================================================
# SECCIÓN 3: SIMULACIÓN NACIONAL COMPLEJA (CONTROL TOTAL Y AGREGADOR)
# ==============================================================================
with tab3:
    st.header(t("tab3_header"))
    st.markdown(t("tab3_desc"))

    # 0. Base Electoral Nacional de Partida (Encuestas o Resultados Anteriores)
    with st.container(border=True):
        st.subheader("📊 Base Electoral Nacional de Partida (Encuesta o Resultados Anteriores)")
        st.markdown("Selecciona los datos macroelectorales de partida para alimentar la proyección circunscripción a circunscripción:")
        s3_poll_opts = get_all_poll_options()
        s3_b_col1, s3_b_col2, s3_b_col3 = st.columns([1.4, 0.9, 1.2])
        with s3_b_col1:
            s3_selected_poll_name = st.selectbox(
                "Sondeo o resultado electoral de base:",
                s3_poll_opts,
                index=1 if "Encuesta Importada desde Excel" not in s3_poll_opts else 0,
                key="s3_poll_selector",
                help="Puedes elegir 'Resultados Oficiales 23J (2023)' como base real externa no simulada, o sondeos demoscópicos recientes (CIS, 40dB, GAD3, ElectoPanel...)."
            )
            s3_active_poll = load_poll_data_by_name(s3_selected_poll_name)
            is_23j_s3 = (s3_selected_poll_name == "Oficial 23J 2023 (Congreso de los Diputados)")
            s3_poll_def_t = get_poll_turnout(s3_selected_poll_name)

            # Detección de cambio de sondeo en Tab 3 para sincronizar proyección provincial y participación
            if st.session_state.get("s3_last_poll_name") != s3_selected_poll_name:
                st.session_state["s3_last_poll_name"] = s3_selected_poll_name
                st.session_state["s3_macro_turnout"] = s3_poll_def_t
                if "s3_macro_turnout_widget" in st.session_state:
                    st.session_state["s3_macro_turnout_widget"] = s3_poll_def_t
                for k in list(st.session_state.keys()):
                    if k.startswith("s3_inp_"):
                        del st.session_state[k]

        with s3_b_col2:
            if "s3_macro_turnout" not in st.session_state:
                st.session_state["s3_macro_turnout"] = s3_poll_def_t
            s3_macro_turnout = st.number_input(
                "Participación proyectada (%):",
                min_value=15.0,
                max_value=98.0,
                value=float(st.session_state.get("s3_macro_turnout", s3_poll_def_t)),
                step=0.5,
                key="s3_macro_turnout_widget",
                help="Porcentaje de participación estimado sobre el censo electoral nacional. Inicializado con el dato del sondeo o resultado seleccionado y totalmente modificable.",
            )
            st.session_state["s3_macro_turnout"] = s3_macro_turnout

        with s3_b_col3:
            s3_poll_date = get_poll_date(s3_selected_poll_name)
            s3_poll_info = poll_connector.get_poll(s3_selected_poll_name) or {}
            s3_source_str = s3_poll_info.get("source", "Oficial / Proyección")
            s3_sample_str = s3_poll_info.get("sample", "N/A")
            is_s3_t_custom = abs(s3_macro_turnout - s3_poll_def_t) > 0.05
            t_badge = f"📊 Participación sondeo: **{s3_poll_def_t:.1f}%**" + (f" ➡️ **Ajustada: {s3_macro_turnout:.1f}%**" if is_s3_t_custom else "")
            if is_23j_s3:
                st.info(f"Base activa: **{s3_selected_poll_name}**  \n📅 **Publicación:** {s3_poll_date} • 👥 {s3_sample_str}  \n{t_badge}")
            else:
                st.info(f"Base de proyección activa: **{s3_selected_poll_name}**  \n📅 **Publicación:** {s3_poll_date} • 🏢 {s3_source_str}  \n{t_badge}")

    # 1. Preconfiguración General de Candidaturas, Ámbito Territorial y Coalición
    with st.expander("🛠️ **1. Preconfiguración General de Candidaturas, Ámbito Territorial y Coalición**", expanded=True):
        st.markdown(
            f"""
            Configura los parámetros por defecto de cada fuerza política antes de realizar ajustes particulares en la Sección 2:  
            * **Ámbito territorial de concurrencia:** Selecciona en qué circunscripciones presenta lista cada partido (nacional, autonómico o distritos a medida).  
            * **Coalición general y retención:** Define qué fuerzas concurren unidas en una lista común y qué porcentaje de voto aportan (retención individual vs. abstención/fuga).  
            * **Regla de prioridad:** Estos valores se aplican a todas las provincias. Si modificas una circunscripción en la Sección 2, **el ajuste provincial siempre tendrá prioridad**.
            """
        )

        st.markdown("##### 🤝 Definición de la Lista Unitaria General")
        cg_col1, cg_col2 = st.columns([1.5, 2])
        with cg_col1:
            global_coal_name = st.text_input(
                "Nombre general de la coalición:",
                value=st.session_state.global_coalition_config.get("name", "Lista Única Izquierdas"),
                key="s3_global_coal_name"
            )
        with cg_col2:
            st.caption(
                "Marca abajo las fuerzas que integran esta lista unitaria a nivel estatal. "
                "En el recuento nacional 'Con coaliciones', sus papeletas se sumarán aplicando la tasa de retención de cada formación."
            )

        st.markdown("---")
        st.markdown(f"##### 📋 Configuración por Partido (Sondeo Activo: {s3_selected_poll_name})")

        # Configuración por partido en cuadrícula de 3 columnas
        parties_in_active_poll = list(s3_active_poll.keys())
        p_cols = st.columns(3)
        temp_party_scope = {}
        temp_coal_members = []
        temp_ret_by_party = {}

        preset_names = list(TERRITORIAL_PRESETS.keys()) + ["Personalizado..."]

        for idx, p_name in enumerate(parties_in_active_poll):
            p_val_nat = s3_active_poll.get(p_name, 0.0)
            target_col = p_cols[idx % 3]

            with target_col.container(border=True):
                st.markdown(f"**{p_name}** ({p_val_nat:.2f}%)")

                # Obtener ámbito territorial actual
                current_scope = st.session_state.global_party_scope.get(
                    p_name,
                    TERRITORIAL_PRESETS.get(DEFAULT_PARTY_TERRITORIES.get(p_name, "Nacional (52 circunscripciones)"), model.get_constituency_names())
                )

                # Identificar preset coincidente
                matched_preset = "Personalizado..."
                for pr_name, pr_provs in TERRITORIAL_PRESETS.items():
                    if sorted([normalize_province_name(p) for p in pr_provs]) == sorted([normalize_province_name(p) for p in current_scope]):
                        matched_preset = pr_name
                        break

                pr_idx = preset_names.index(matched_preset) if matched_preset in preset_names else len(preset_names) - 1

                sel_preset = st.selectbox(
                    f"Territorio ({p_name}):",
                    preset_names,
                    index=pr_idx,
                    key=f"s3_sel_preset_{p_name}",
                    help=f"Define en qué circunscripciones computa votos {p_name}.",
                )

                if sel_preset == "Personalizado...":
                    custom_provs = st.multiselect(
                        f"Provincias donde compite {p_name}:",
                        options=model.get_constituency_names(),
                        default=[c for c in current_scope if c in model.get_constituency_names()],
                        format_func=get_province_display_name,
                        key=f"s3_custom_provs_{p_name}",
                    )
                    temp_party_scope[p_name] = custom_provs
                    st.caption(f"Concurre en **{len(custom_provs)}** circunscripciones.")
                else:
                    assigned_provs = list(TERRITORIAL_PRESETS[sel_preset])
                    temp_party_scope[p_name] = assigned_provs
                    st.caption(f"Concurre en **{len(assigned_provs)}** circunscripciones.")

                # Integración en coalición general
                is_mem_cur = p_name in st.session_state.global_coalition_config.get("members", ["Sumar", "Podemos"])
                join_coal = st.checkbox(
                    f"¿Se une a '{global_coal_name}'?",
                    value=is_mem_cur,
                    key=f"s3_join_coal_{p_name}",
                )

                if join_coal:
                    temp_coal_members.append(p_name)
                    cur_r = st.session_state.global_coalition_config.get("retention_by_party", {}).get(p_name, 1.0)
                    ret_pct = st.slider(
                        f"Retención {p_name} (%):",
                        min_value=40,
                        max_value=120,
                        value=int(cur_r * 100),
                        step=1,
                        key=f"s3_ret_sl_{p_name}",
                        help=f"Porcentaje de votantes de {p_name} que retiene la lista única al unirse.",
                    )
                    temp_ret_by_party[p_name] = ret_pct / 100.0
                    st.caption(f"Aporta el **{ret_pct}%** de su caudal electoral.")
                else:
                    temp_ret_by_party[p_name] = 1.0

        # Sincronización reactiva inmediata en tiempo real para que el recuento nacional y el optimizador
        # hereden automáticamente la lista única configurada en la simulación sin obligar a pulsar el botón
        active_tab3_members = list(temp_coal_members) if temp_coal_members else list(st.session_state.global_coalition_config.get("members", ["Sumar", "Podemos"]))
        st.session_state.global_coalition_config["name"] = global_coal_name
        st.session_state.global_coalition_config["members"] = active_tab3_members
        st.session_state.global_coalition_config["retention_by_party"] = dict(temp_ret_by_party)
        st.session_state.global_party_scope = dict(temp_party_scope)

        st.markdown("---")
        btn_c1, btn_c2, btn_c3 = st.columns([1.5, 1.5, 2])
        with btn_c1:
            if st.button("💾 Guardar y Aplicar Preconfiguración General", key="s3_btn_save_preconfig"):
                st.session_state.global_party_scope = temp_party_scope
                st.session_state.global_coalition_config = {
                    "name": global_coal_name,
                    "members": active_tab3_members,
                    "retention_by_party": temp_ret_by_party,
                }
                st.session_state["s3_custom_configured"] = True
                st.success("¡Preconfiguración general guardada y propagada a todas las circunscripciones!")
                st.rerun()

        with btn_c2:
            if st.button("🔄 Restablecer a Configuración Estándar", key="s3_btn_reset_preconfig"):
                st.session_state.global_party_scope = {
                    p: list(TERRITORIAL_PRESETS.get(scope_name, model.get_constituency_names()))
                    for p, scope_name in DEFAULT_PARTY_TERRITORIES.items()
                }
                st.session_state.global_coalition_config = {
                    "name": "Lista Única Izquierdas",
                    "members": ["Sumar", "Podemos"],
                    "retention_by_party": {"Sumar": 1.0, "Podemos": 1.0},
                }
                if "s3_custom_configured" in st.session_state:
                    del st.session_state["s3_custom_configured"]
                for k in list(st.session_state.keys()):
                    if k.startswith("s3_join_coal_") or k.startswith("s3_ret_sl_") or k.startswith("s3_sel_preset_"):
                        del st.session_state[k]
                st.success("Configuración restablecida a los valores estándar de referencia.")
                st.rerun()

        with btn_c3:
            st.info(f"Coalición general activa: **{st.session_state.global_coalition_config.get('name')}** con **{len(st.session_state.global_coalition_config.get('members', []))}** fuerzas ({', '.join(st.session_state.global_coalition_config.get('members', []))}).")

    # 2. Panel de Control y Modificación por Circunscripción
    st.markdown("---")
    st.subheader("📍 2. Control y Modificación Circunscripción a Circunscripción")

    c_sel_col, c_info_col = st.columns([1, 2])
    with c_sel_col:
        s3_selected_prov = st.selectbox(
            "Seleccionar Circunscripción a Inspeccionar / Modificar:",
            model.get_constituency_names(),
            index=model.get_constituency_names().index("Madrid"),
            format_func=get_province_display_name,
            key="s3_prov_selector"
        )
        prov_data_obj = model.get_constituency(s3_selected_prov)
        is_customized = any(are_same_province(k, s3_selected_prov) for k in st.session_state.constituency_overrides)
        if is_customized:
            st.warning("⚠️ Esta circunscripción tiene ajustes manuales activos.")
            if st.button(f"Restablecer {s3_selected_prov} a valores de encuesta", key="s3_reset_this_prov"):
                keys_to_del = [k for k in st.session_state.constituency_overrides if are_same_province(k, s3_selected_prov)]
                for k in keys_to_del:
                    del st.session_state.constituency_overrides[k]
                st.success(f"{s3_selected_prov} restablecida.")
                st.rerun()
        else:
            st.info("ℹ️ Utiliza la proyección estándar de la encuesta y la preconfiguración global.")

    with c_info_col:
        # Obtener valores actuales de la circunscripción
        prov_override = {}
        for k, v in st.session_state.constituency_overrides.items():
            if are_same_province(k, s3_selected_prov):
                prov_override = v
                break

        prov_base_t = float(prov_data_obj.get("turnout_pct", 66.59))
        scaled_t = round(min(98.0, max(10.0, prov_base_t * (s3_macro_turnout / 66.59))), 2)

        if is_23j_s3 and not is_customized:
            cur_census = int(prov_data_obj.get("census", round(prov_data_obj.get("valid_votes", 100000) / 0.6659)))
            cur_turnout = scaled_t if abs(s3_macro_turnout - 66.59) > 0.05 else prov_base_t
            cur_null = float(prov_data_obj.get("null_votes_pct", 1.0))
            cur_blank = float(prov_data_obj.get("blank_votes_pct", 0.8))
            cur_seats = int(prov_data_obj["seats"])
        else:
            cur_census = int(prov_override.get("census", prov_data_obj.get("census", round(prov_data_obj["valid_votes"]/0.69))))
            cur_turnout = float(prov_override.get("turnout_pct", scaled_t))
            cur_null = float(prov_override.get("null_pct", prov_data_obj.get("null_votes_pct", 1.0)))
            cur_blank = float(prov_override.get("blank_pct", prov_data_obj.get("blank_votes_pct", 0.8)))
            cur_seats = int(prov_override.get("seats", prov_data_obj["seats"]))

        st.markdown(f"**Parámetros Electorales en {get_province_display_name(s3_selected_prov)} ({cur_seats} escaños):**")
        st_e1, st_e2, st_e3, st_e4 = st.columns(4)
        ed_census = st_e1.number_input("Censo (Electores):", min_value=1000, value=cur_census, step=5000, key=f"s3_c_{s3_selected_prov}")
        ed_turnout = st_e2.number_input("Participación (%):", min_value=10.0, max_value=100.0, value=cur_turnout, step=0.5, key=f"s3_t_{s3_selected_prov}")
        ed_blank = st_e3.number_input("Voto en blanco (%):", min_value=0.0, max_value=10.0, value=cur_blank, step=0.1, key=f"s3_b_{s3_selected_prov}")
        ed_null = st_e4.number_input("Voto nulo (%):", min_value=0.0, max_value=10.0, value=cur_null, step=0.1, key=f"s3_n_{s3_selected_prov}")

    # Formulario de edición detallada de la circunscripción
    with st.expander(f"✏️ **Editar Candidaturas y Coalición Específica de {get_province_display_name(s3_selected_prov)}**", expanded=True):
        st.markdown(f"Configura qué listas se presentan y si van o no en coalición en **{get_province_display_name(s3_selected_prov)}**:")
        
        # Obtener candidaturas base
        if is_23j_s3 and not is_customized:
            tot_validos_23j = float(prov_data_obj["valid_votes"])
            parties_data_source = {
                p: round((pct / 100.0) * tot_validos_23j)
                for p, pct in prov_data_obj.get("parties_pct", {}).items()
                if pct > 0
            }
        else:
            baseline_prov_sim = safe_simulate(
                model,
                s3_active_poll,
                left_scenario="separated",
                party_constituencies=st.session_state.get("global_party_scope"),
                is_official_23j=is_23j_s3,
                turnout_pct=s3_macro_turnout,
            )
            base_c_item = next((c for c in baseline_prov_sim.constituency_data if are_same_province(c["name"], s3_selected_prov)), None)
            if base_c_item is None:
                base_c_item = baseline_prov_sim.constituency_data[0]
            
            parties_data_source = dict(base_c_item["raw_parties_votes"])
            if is_customized and "parties" in prov_override:
                parties_data_source = dict(prov_override["parties"])
        
        # Asegurar presencia de cualquier partido que obtuviera al menos el 3% en el 23J en esta circunscripción
        if prov_data_obj and "parties_pct" in prov_data_obj:
            tot_v_ref = float(prov_data_obj.get("valid_votes", 500000))
            for p_23j, pct_23j in prov_data_obj["parties_pct"].items():
                if pct_23j >= 3.0 and p_23j not in parties_data_source:
                    parties_data_source[p_23j] = round((pct_23j / 100.0) * tot_v_ref)

        # En Andalucía, asegurar presencia de Adelante Andalucía si compitió
        if is_andalusian_province(s3_selected_prov) or (prov_data_obj and prov_data_obj.get("community") == "AND"):
            if "Adelante Andalucía" not in parties_data_source:
                parties_data_source["Adelante Andalucía"] = 9000 if are_same_province(s3_selected_prov, "Cádiz") else 0

        ed_input_mode = st.radio("Modo de introducción de datos:", ["Porcentajes (%)", "Votos Absolutos"], horizontal=True, key=f"s3_mode_{s3_selected_prov}")

        # Coalición en esta provincia
        c_coal_box1, c_coal_box2 = st.columns([1, 2])
        cur_coal_info = prov_override.get("coalition", {})
        with c_coal_box1:
            prov_coal_enabled = st.checkbox("¿Activar coalición en esta provincia?", value=cur_coal_info.get("enabled", True), key=f"s3_coal_en_{s3_selected_prov}")
            prov_coal_name = st.text_input("Nombre de la lista unitaria en esta provincia:", value=cur_coal_info.get("name", st.session_state.global_coalition_config.get("name", "Lista Única")), key=f"s3_cn_{s3_selected_prov}")
            
            avail_cand_prov = list(parties_data_source.keys())
            def_prov_members = cur_coal_info.get("members", [p for p in st.session_state.global_coalition_config.get("members", ["Sumar", "Podemos"]) if p in avail_cand_prov])
            prov_coal_members = st.multiselect("Partidos que forman la coalición aquí:", options=avail_cand_prov, default=def_prov_members, key=f"s3_cm_{s3_selected_prov}")

        with c_coal_box2:
            st.markdown("**Fuga de votos de cada integrante en esta provincia (Retención %):**")
            prov_ret_map = {}
            if prov_coal_enabled and prov_coal_members:
                rc_cols = st.columns(len(prov_coal_members))
                for idx, m in enumerate(prov_coal_members):
                    def_r = cur_coal_info.get("retention_by_party", {}).get(m, st.session_state.global_coalition_config.get("retention_by_party", {}).get(m, 1.0))
                    val_r = rc_cols[idx].slider(f"Retención {m}:", min_value=40, max_value=120, value=int(def_r * 100), step=1, key=f"s3_ret_{s3_selected_prov}_{m}")
                    prov_ret_map[m] = val_r / 100.0

        st.markdown("---")
        if is_23j_s3 and not is_customized:
            st.caption(f"📌 **Datos Oficiales 23J para {get_province_display_name(s3_selected_prov)}:** {prov_data_obj.get('valid_votes', 0):,.0f} votos válidos, {cur_seats} diputados oficiales.")
        st.markdown("**Datos por Candidatura:**")
        c_cols = st.columns(4)
        edited_parties_dict = {}

        # Calcular votos válidos estimados para conversiones
        tot_votantes = (ed_turnout / 100.0) * ed_census
        tot_validos = max(1.0, tot_votantes - (ed_null / 100.0) * tot_votantes)

        for idx, (p, val) in enumerate(parties_data_source.items()):
            col_target = c_cols[idx % 4]
            with col_target.container(border=True):
                st.markdown(f"**{p}**")
                if ed_input_mode == "Porcentajes (%)":
                    if is_23j_s3 and not is_customized and p in prov_data_obj.get("parties_pct", {}):
                        init_pct = float(prov_data_obj["parties_pct"][p])
                    else:
                        init_pct = (val / tot_validos) * 100.0 if tot_validos > 0 else 0.0
                    val_pct = st.number_input(f"% {p}:", min_value=0.0, max_value=75.0, value=round(init_pct, 2), step=0.2, key=f"s3_inp_{s3_selected_poll_name}_{s3_selected_prov}_{p}")
                    edited_parties_dict[p] = (val_pct / 100.0) * tot_validos
                    st.caption(f"Votos: **{edited_parties_dict[p]:,.0f}**")
                else:
                    val_v = st.number_input(f"Votos {p}:", min_value=0, value=int(val), step=500, key=f"s3_inp_{s3_selected_poll_name}_{s3_selected_prov}_{p}")
                    edited_parties_dict[p] = float(val_v)
                    pct_derived = (val_v / tot_validos) * 100.0 if tot_validos > 0 else 0.0
                    st.caption(f"Porcentaje: **{pct_derived:.2f}%**")

        st.markdown("**Añadir candidatura:**")
        anc1, anc2, anc3 = st.columns([2, 1, 1])
        new_c_name = anc1.text_input("Nombre de la candidatura:", placeholder="ej. Partido Nacional / Regional / Local...", key=f"s3_new_p_{s3_selected_prov}")
        new_c_val = anc2.number_input("Votos o %:", min_value=0.0, value=5000.0 if ed_input_mode == "Votos Absolutos" else 3.0, key=f"s3_new_v_{s3_selected_prov}")
        if anc3.button("Añadir a esta provincia", key=f"s3_btn_add_{s3_selected_prov}"):
            if new_c_name.strip():
                if ed_input_mode == "Porcentajes (%)":
                    edited_parties_dict[new_c_name.strip()] = (new_c_val / 100.0) * tot_validos
                else:
                    edited_parties_dict[new_c_name.strip()] = new_c_val
                st.session_state.constituency_overrides[s3_selected_prov] = {
                    "census": ed_census,
                    "turnout_pct": ed_turnout,
                    "blank_pct": ed_blank,
                    "null_pct": ed_null,
                    "parties": edited_parties_dict,
                    "input_mode": "votes" if ed_input_mode == "Votos Absolutos" else "pct",
                    "coalition": {
                        "enabled": prov_coal_enabled,
                        "name": prov_coal_name,
                        "members": prov_coal_members,
                        "retention_by_party": prov_ret_map,
                    }
                }
                st.success(f"Candidatura '{new_c_name.strip()}' añadida.")
                st.rerun()

        if st.button(f"💾 Guardar todos los cambios de {s3_selected_prov}", key=f"s3_save_btn_{s3_selected_prov}"):
            st.session_state.constituency_overrides[s3_selected_prov] = {
                "census": ed_census,
                "turnout_pct": ed_turnout,
                "blank_pct": ed_blank,
                "null_pct": ed_null,
                "parties": edited_parties_dict,
                "input_mode": "votes" if ed_input_mode == "Votos Absolutos" else "pct",
                "coalition": {
                    "enabled": prov_coal_enabled,
                    "name": prov_coal_name,
                    "members": prov_coal_members,
                    "retention_by_party": prov_ret_map,
                }
            }
            st.success(f"¡Ajustes de {s3_selected_prov} guardados con éxito!")
            st.rerun()

    # Gráfica escalonada descendente D'Hondt para la circunscripción seleccionada en Nacional Compleja
    st.markdown("---")
    st.markdown(f"#### 📈 Escalera D'Hondt en {get_province_display_name(s3_selected_prov)} ({cur_seats} escaños)")
    st.caption(
        f"Visualización de la carrera de cocientes electorales bajo la Ley D'Hondt para **{get_province_display_name(s3_selected_prov)}** "
        f"según los datos configurados actualmente en esta circunscripción."
    )

    s3_sc_col1, s3_sc_col2 = st.columns([1.2, 1.2])
    with s3_sc_col1:
        s3_prov_view_scen = st.radio(
            f"Escenario a visualizar en la escalera de {s3_selected_prov}:",
            [f"Con Coalición ({prov_coal_name})" if prov_coal_enabled else "Con Coalición (Desactivada aquí)", "Candidaturas Separadas"],
            horizontal=True,
            key=f"s3_prov_view_scen_{s3_selected_prov}",
        )

    # Calcular votos para D'Hondt según escenario elegido
    chart_votes_s3 = dict(edited_parties_dict)
    if "Con Coalición" in s3_prov_view_scen and prov_coal_enabled and prov_coal_members:
        non_c_v = {p: v for p, v in edited_parties_dict.items() if p not in prov_coal_members}
        u_votes = sum(edited_parties_dict.get(m, 0.0) * prov_ret_map.get(m, 1.0) for m in prov_coal_members)
        if u_votes > 0:
            non_c_v[prov_coal_name] = u_votes
        chart_votes_s3 = non_c_v

    c_v_blank = (ed_blank / 100.0) * tot_validos
    dhondt_prov_s3 = calculate_dhondt(
        votes=chart_votes_s3,
        seats_to_allocate=cur_seats,
        blank_votes=c_v_blank,
        threshold_pct=3.0,
    )
    if is_23j_s3 and not is_customized and "Separadas" in s3_prov_view_scen and prov_data_obj.get("parties_seats") and cur_seats == prov_data_obj["seats"]:
        dhondt_prov_s3.seats = dict(prov_data_obj["parties_seats"])

    ds_s3_chart = (
        f"Resultados Oficiales 23J ({s3_prov_view_scen})"
        if (is_23j_s3 and not is_customized)
        else f"Configuración Provincial Sección 3 ({s3_prov_view_scen})"
    )
    fig_s3_stepped = create_dhondt_stepped_chart(
        votes=chart_votes_s3,
        result=dhondt_prov_s3,
        title=f"Circunscripción de {get_province_display_name(s3_selected_prov)} ({cur_seats} escaños)",
        data_source=ds_s3_chart,
        poll_date=s3_poll_date,
    )
    st.plotly_chart(fig_s3_stepped, use_container_width=True)

    # Relación de candidaturas (Admitidas vs Excluidas)
    with st.expander(f"📋 **Relación de Candidaturas en {get_province_display_name(s3_selected_prov)}**", expanded=False):
        st.caption(
            f"Umbral legal (3% LOREG): **{dhondt_prov_s3.threshold_votes:,.0f} votos** sobre {dhondt_prov_s3.valid_votes:,.0f} votos válidos."
        )
        s3_adm_rows = []
        s3_exc_rows = []
        for p, v in sorted(chart_votes_s3.items(), key=lambda x: -x[1]):
            v_pct = (v / dhondt_prov_s3.valid_votes * 100.0) if dhondt_prov_s3.valid_votes > 0 else 0.0
            seats_won = dhondt_prov_s3.seats.get(p, 0)
            if v <= 0:
                continue
            elif p in dhondt_prov_s3.excluded_parties:
                gap = max(0.0, dhondt_prov_s3.threshold_votes - v)
                s3_exc_rows.append({
                    "Candidatura": p,
                    "Votos": f"{v:,.0f}",
                    "% Válido": f"{v_pct:.2f}%",
                    "Escaños": 0,
                    "Faltan para Umbral": f"+{gap:,.0f} votos",
                    "Estado": "❌ Excluida (< 3%)",
                })
            else:
                s3_adm_rows.append({
                    "Candidatura": p,
                    "Votos": f"{v:,.0f}",
                    "% Válido": f"{v_pct:.2f}%",
                    "Escaños": seats_won,
                    "Faltan para Umbral": "Superado",
                    "Estado": "✅ En reparto",
                })
        if s3_adm_rows:
            st.dataframe(pd.DataFrame(s3_adm_rows), use_container_width=True, hide_index=True)
        if s3_exc_rows:
            st.dataframe(pd.DataFrame(s3_exc_rows), use_container_width=True, hide_index=True)

    # 3. Recuento Nacional Agregado
    st.markdown("---")
    st.subheader("🏛️ 3. Recuento Nacional Agregado del Congreso (350 Escaños)")
    
    s3_recount_choice = st.radio(
        "Opción de recuento nacional:",
        ["🔵 Todos los partidos por separado", "🟣 Con las coaliciones y ajustes definidos circunscripción a circunscripción"],
        horizontal=True,
        key="s3_recount_choice"
    )

    sim_mode_s3 = "separated" if s3_recount_choice == "🔵 Todos los partidos por separado" else "coalitions"

    s3_coal_name = st.session_state.global_coalition_config.get("name", "Lista Única")
    s3_coal_members = st.session_state.global_coalition_config.get("members", ["Sumar", "Podemos"])
    s3_ret_map = st.session_state.global_coalition_config.get("retention_by_party", {p: 1.0 for p in s3_coal_members})

    # Integrantes efectivos que concurren en lista unitaria (incorporando excepciones locales si existieran)
    all_s3_mems = list(s3_coal_members)
    for over in st.session_state.constituency_overrides.values():
        c_info = over.get("coalition", {})
        if c_info.get("enabled", True):
            for m in c_info.get("members", []):
                if m not in all_s3_mems:
                    all_s3_mems.append(m)
    s3_effective_coal_members = all_s3_mems

    # Ejecutar simulación para ambos escenarios (separados vs coalición) para permitir comparación completa
    sim_complex_sep = safe_simulate(
        model,
        national_poll=s3_active_poll,
        left_scenario="separated",
        constituency_overrides=st.session_state.constituency_overrides,
        party_constituencies=st.session_state.get("global_party_scope"),
        is_official_23j=is_23j_s3,
        turnout_pct=s3_macro_turnout,
    )

    sim_complex_coal = safe_simulate(
        model,
        national_poll=s3_active_poll,
        left_scenario="coalitions",
        constituency_overrides=st.session_state.constituency_overrides,
        default_coalition_members=s3_coal_members,
        default_retention_by_party=s3_ret_map,
        custom_coalition_name=s3_coal_name,
        party_constituencies=st.session_state.get("global_party_scope"),
        is_official_23j=is_23j_s3,
        turnout_pct=s3_macro_turnout,
    )

    # Resultado activo según la opción seleccionada por el usuario
    sim_complex_res = sim_complex_sep if sim_mode_s3 == "separated" else sim_complex_coal

    # Gráfico de barras de escaños con paleta accesible y texto negro
    df_s3_seats = pd.DataFrame([
        {"Partido": p, "Escaños": s, "Color": get_party_color(p)}
        for p, s in sorted(sim_complex_res.national_seats.items(), key=lambda x: -x[1])
        if s > 0
    ])

    fig_s3_bar = px.bar(
        df_s3_seats,
        x="Partido",
        y="Escaños",
        color="Partido",
        color_discrete_map={row["Partido"]: row["Color"] for _, row in df_s3_seats.iterrows()},
        text="Escaños",
        title=f"<b>Composición del Congreso ({s3_recount_choice}) - 350 escaños</b><br><sup>Procedencia de datos: {s3_selected_poll_name} • Fecha de publicación: {s3_poll_date}</sup>",
    )
    fig_s3_bar.add_hline(
        y=176,
        line_dash="dash",
        line_color="#000000",
        line_width=1.8,
        annotation_text="<b>Mayoría Absoluta (176)</b>",
        annotation_position="top left",
        annotation_font=dict(color="#000000", size=12, family="sans-serif"),
        annotation_bgcolor="#FFFFFF",
        annotation_bordercolor="#000000",
        annotation_borderwidth=1.2,
    )
    fig_s3_bar.update_layout(
        font=dict(color="#000000", family="sans-serif", size=12),
        title=dict(font=dict(color="#000000", size=16, family="sans-serif")),
        xaxis=dict(
            title=dict(text="<b>Fuerza Política</b>", font=dict(color="#000000", size=13, family="sans-serif")),
            tickfont=dict(color="#000000", size=12, family="sans-serif"),
        ),
        yaxis=dict(
            title=dict(text="<b>Diputados Obtenidos</b>", font=dict(color="#000000", size=13, family="sans-serif")),
            tickfont=dict(color="#000000", size=12, family="sans-serif"),
            gridcolor="#E2E8F0",
        ),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        showlegend=False,
        margin=dict(l=60, r=40, t=65, b=80),
    )
    fig_s3_bar.add_annotation(
        xref="paper", yref="paper",
        x=0.0, y=-0.22,
        text=f"Procedencia de datos: {s3_selected_poll_name} | Fecha de publicación: {s3_poll_date} (con ajustes y coaliciones territoriales aplicadas)",
        showarrow=False,
        font=dict(color="#000000", size=11, family="sans-serif"),
    )
    fig_s3_bar.update_traces(
        textfont=dict(color="#000000", size=12, family="sans-serif"),
        textposition="outside",
    )
    st.plotly_chart(fig_s3_bar, use_container_width=True)

    # ==============================================================================
    # TABLA COMPARATIVA Y TRANSFERENCIA DE ESCAÑOS (SEPARADOS VS. COALICIÓN)
    # ==============================================================================
    st.markdown("---")
    st.subheader("⚖️ Tabla Comparativa de Escaños y Transferencias (Separados vs. En Coalición)")
    st.caption(
        f"Contraste directo entre concurrir por separado o en coalición ({s3_coal_name}) incorporando "
        f"todos los ajustes territoriales, ámbitos de concurrencia y configuraciones provinciales activas."
    )

    # Cómputo del bloque de la izquierda alternativa
    s3_sep_block_seats = sum(sim_complex_sep.national_seats.get(m, 0) for m in s3_coal_members)
    s3_coal_block_seats = sim_complex_coal.national_seats.get(s3_coal_name, 0) + sum(sim_complex_coal.national_seats.get(m, 0) for m in s3_coal_members)
    s3_block_diff = s3_coal_block_seats - s3_sep_block_seats
    s3_winner_scenario = "Coalición" if s3_block_diff > 0 else ("Separados" if s3_block_diff < 0 else "Empate")

    # Métricas clave del bloque
    cb_col1, cb_col2, cb_col3, cb_col4 = st.columns(4)
    with cb_col1:
        st.metric(
            label="Diputados: Por Separado",
            value=f"{s3_sep_block_seats} esc.",
            help=f"Suma de escaños de los integrantes ({', '.join(s3_coal_members)}) si compiten por separado."
        )
    with cb_col2:
        st.metric(
            label=f"Diputados: {s3_coal_name}",
            value=f"{s3_coal_block_seats} esc.",
            delta=f"{s3_block_diff:+d} esc." if s3_block_diff != 0 else "0 esc.",
            delta_color="normal" if s3_block_diff >= 0 else "inverse",
            help="Escaños obtenidos concurriendo en coalición con las retenciones asignadas."
        )
    with cb_col3:
        st.metric(
            label="Escenario más favorable",
            value=f"🟣 {s3_winner_scenario}" if s3_winner_scenario == "Coalición" else (f"🔵 {s3_winner_scenario}" if s3_winner_scenario == "Separados" else "⚖️ Empate"),
            help="Estrategia electoral que maximiza la representación parlamentaria del bloque."
        )
    with cb_col4:
        st.metric(
            label="Ventaja neta",
            value=f"{abs(s3_block_diff)} escaños",
            delta=f"A favor de {s3_winner_scenario}" if s3_winner_scenario != "Empate" else "Mismo balance",
            delta_color="off",
        )

    # 1. Tabla de composición comparativa completa de la cámara (350 escaños)
    std_party_order = [
        "PP", "PSOE", "Vox", s3_coal_name
    ] + [m for m in s3_effective_coal_members if m not in ("PP", "PSOE", "Vox", s3_coal_name)] + [
        "Sumar", "Podemos", "SALF",
        "ERC", "Junts", "EH Bildu", "PNV", "BNG", "CC", "UPN", "Adelante Andalucía"
    ]
    all_known_parties = list(std_party_order)
    for p in list(sim_complex_sep.national_seats.keys()) + list(sim_complex_coal.national_seats.keys()):
        if p not in all_known_parties:
            all_known_parties.append(p)

    comp_rows_s3 = []
    for p in all_known_parties:
        s_sep = sim_complex_sep.national_seats.get(p, 0)
        s_coal = sim_complex_coal.national_seats.get(p, 0)
        if s_sep == 0 and s_coal == 0:
            continue
        diff = s_coal - s_sep
        if diff > 0:
            diff_str = f"+{diff} esc."
        elif diff < 0:
            diff_str = f"{diff} esc."
        else:
            diff_str = "="
        
        rol = "🤝 Integrante coalición" if p in s3_effective_coal_members else ("🏛️ Candidatura conjunta" if p == s3_coal_name else "⚔️ Fuerza rival")
        comp_rows_s3.append({
            "Candidatura": p,
            "Rol": rol,
            "Escaños: Por Separado": s_sep,
            "Escaños: En Coalición": s_coal,
            "Diferencia Neta (Coalición - Separados)": diff_str,
        })

    df_comp_national = pd.DataFrame(comp_rows_s3)
    st.markdown("##### 📊 Reparto Comparativo del Congreso por Partido:")
    st.dataframe(df_comp_national, use_container_width=True, hide_index=True)

    # 2. Análisis de transferencias: ¿A quién quita o cede los diputados el escenario ganador?
    st.markdown("---")
    st.markdown(f"#### 🎯 ¿A quién quita o cede diputados el escenario más favorable ({s3_winner_scenario})?")

    # Balance agregado de escaños frente a rivales
    rival_losses: Dict[str, int] = {}
    rival_gains: Dict[str, int] = {}
    for p, s_sep in sim_complex_sep.national_seats.items():
        if p in s3_coal_members or p == s3_coal_name:
            continue
        s_coal = sim_complex_coal.national_seats.get(p, 0)
        if s_coal < s_sep:
            rival_losses[p] = s_sep - s_coal
        elif s_coal > s_sep:
            rival_gains[p] = s_coal - s_sep

    if s3_winner_scenario == "Coalición" and rival_losses:
        st.markdown(
            f"Al concurrir en lista única, la ganancia de **+{s3_block_diff} diputados** del bloque "
            f"se consigue arrebatándole escaños a las siguientes formaciones rivales:"
        )
        c_cards = st.columns(min(len(rival_losses), 5))
        for idx, (p_lost, n_seats) in enumerate(sorted(rival_losses.items(), key=lambda x: -x[1])):
            target_c = c_cards[idx % len(c_cards)]
            s_bef = sim_complex_sep.national_seats.get(p_lost, 0)
            s_aft = sim_complex_coal.national_seats.get(p_lost, 0)
            with target_c.container(border=True):
                st.metric(
                    label=f"Restado a {p_lost}",
                    value=f"-{n_seats} dip.",
                    delta=f"{s_bef} ➔ {s_aft} dip.",
                    delta_color="inverse",
                )
    elif s3_winner_scenario == "Separados" and rival_gains:
        st.markdown(
            f"Concurrir por separado evita la fuga de votos y preserva **+{abs(s3_block_diff)} diputados**, "
            f"impidiendo que las siguientes formaciones rivales obtengan esos escaños:"
        )
        c_cards = st.columns(min(len(rival_gains), 5))
        for idx, (p_gain, n_seats) in enumerate(sorted(rival_gains.items(), key=lambda x: -x[1])):
            target_c = c_cards[idx % len(c_cards)]
            s_bef = sim_complex_sep.national_seats.get(p_gain, 0)
            s_aft = sim_complex_coal.national_seats.get(p_gain, 0)
            with target_c.container(border=True):
                st.metric(
                    label=f"Escaños no cedidos a {p_gain}",
                    value=f"+{n_seats} dip.",
                    delta=f"{s_aft} (con coalición) vs {s_bef} (por separado)",
                    delta_color="normal",
                )
    else:
        st.info("No se producen transferencias netas de escaños con otras fuerzas políticas a nivel global.")

    # 3. Desglose detallado circunscripción a circunscripción de las transferencias de escaños
    prov_takeovers_s3 = []
    for c_data in sim_complex_sep.constituency_data:
        c_name = c_data["name"]
        c_sep_res = sim_complex_sep.constituency_results[c_name]
        c_coal_res = sim_complex_coal.constituency_results[c_name]

        c_blk_sep = sum(c_sep_res.seats.get(m, 0) for m in s3_coal_members)
        c_blk_coal = c_coal_res.seats.get(s3_coal_name, 0) + sum(c_coal_res.seats.get(m, 0) for m in s3_coal_members)
        c_diff = c_blk_coal - c_blk_sep

        if c_diff != 0:
            all_c_p = set(c_sep_res.seats.keys()).union(c_coal_res.seats.keys())
            for p in all_c_p:
                if p in s3_coal_members or p == s3_coal_name:
                    continue
                p_s = c_sep_res.seats.get(p, 0)
                p_c = c_coal_res.seats.get(p, 0)
                if c_diff > 0 and p_c < p_s:
                    prov_takeovers_s3.append({
                        "Circunscripción": get_province_display_name(c_name),
                        "Comunidad": c_data["community"],
                        "Escenario Ganador en la Provincia": "🟣 Coalición",
                        "Escaños Transferidos": f"+{p_s - p_c}",
                        "Fuerza Afectada": p,
                        "Evolución Rival": f"Baja de {p_s} a {p_c} escaños",
                        "Evolución Bloque": f"Sube de {c_blk_sep} a {c_blk_coal} escaños",
                        "Impacto D'Hondt": "Concentración de restos superó el cociente de corte",
                    })
                elif c_diff < 0 and p_c > p_s:
                    prov_takeovers_s3.append({
                        "Circunscripción": get_province_display_name(c_name),
                        "Comunidad": c_data["community"],
                        "Escenario Ganador en la Provincia": "🔵 Separados",
                        "Escaños Transferidos": f"+{p_c - p_s}",
                        "Fuerza Afectada": p,
                        "Evolución Rival": f"Sube de {p_s} a {p_c} escaños",
                        "Evolución Bloque": f"Baja de {c_blk_sep} a {c_blk_coal} escaños",
                        "Impacto D'Hondt": "Fuga de votos de la coalición permitió al rival ganar el escaño",
                    })

    if prov_takeovers_s3:
        with st.expander(f"📍 **Detalle de Transferencias Circunscripción a Circunscripción ({len(prov_takeovers_s3)} transferencias identificadas)**", expanded=True):
            st.markdown(
                "Relación pormenorizada distrito a distrito donde la confluencia o división del voto altera el último escaño repartido:"
            )
            st.dataframe(pd.DataFrame(prov_takeovers_s3), use_container_width=True, hide_index=True)
    else:
        st.info("Ninguna circunscripción experimentó traspaso de escaños con las tasas de retención actuales.")

    # ==============================================================================
    # MAPA ELECTORAL INTERACTIVO DE ESPAÑA (CONTROL COMPLEJO)
    # ==============================================================================
    st.markdown("---")
    render_electoral_map_section(
        sim_result=sim_complex_coal,
        comparison_result=sim_complex_sep,
        section_key="s3",
        coalition_name=s3_coal_name,
        coalition_members=s3_coal_members,
        poll_name=s3_selected_poll_name,
        poll_date=s3_poll_date,
        allow_coalition_mode=True,
        default_scenario="separated" if sim_mode_s3 == "separated" else "coalition",
    )

    # Tabla resumen de las 52 circunscripciones
    st.markdown("---")
    st.markdown(f"#### 🗺️ Reparto de Escaños Circunscripción a Circunscripción ({s3_recount_choice}):")
    tbl_rows = []
    for c_item in sim_complex_res.constituency_data:
        c_nm = c_item["name"]
        row = {
            "Circunscripción": get_province_display_name(c_nm),
            "Comunidad": c_item["community"],
            "Escaños": c_item["seats"],
            "Censo": f"{c_item['census']:,.0f}",
            "Participación": f"{c_item['turnout_pct']:.1f}%",
            "Ajuste Manual": "✅ Sí" if any(are_same_province(k, c_nm) for k in st.session_state.constituency_overrides) else "No",
        }
        for p, s in c_item["result"].seats.items():
            if s > 0:
                row[p] = s
        tbl_rows.append(row)

    df_tbl = pd.DataFrame(tbl_rows).fillna(0)
    for col in df_tbl.columns:
        if col not in ["Circunscripción", "Comunidad", "Ajuste Manual", "Censo", "Participación"]:
            df_tbl[col] = df_tbl[col].astype(int)

    st.dataframe(df_tbl, use_container_width=True)

    # ==============================================================================
    # ESCALERA D'HONDT EN EL RECUENTO NACIONAL AGREGADO
    # ==============================================================================
    st.markdown("---")
    st.subheader("📈 La Carrera por los Escaños: Escalera D'Hondt en el Recuento Nacional")
    st.caption(
        "Inspecciona la carrera de cocientes de la Ley D'Hondt para **cualquiera de las 52 circunscripciones** "
        f"tras procesar todo el recuento nacional ({s3_recount_choice})."
    )

    s3_rn_col1, s3_rn_col2 = st.columns([1.2, 1.2])
    with s3_rn_col1:
        s3_rn_prov = st.selectbox(
            "Seleccionar Circunscripción para ver su escalera D'Hondt:",
            model.get_constituency_names(),
            index=model.get_constituency_names().index("Madrid") if "Madrid" in model.get_constituency_names() else 0,
            format_func=get_province_display_name,
            key="s3_national_recount_stepped_prov_select",
        )
    with s3_rn_col2:
        s3_rn_scen = st.radio(
            "Escenario a visualizar en la gráfica:",
            [f"Con Coalición ({s3_coal_name})", "Candidaturas Separadas"],
            horizontal=True,
            key=f"s3_national_recount_stepped_scen_radio_{s3_rn_prov}",
        )

    s3_rn_sim = sim_complex_coal if "Coalición" in s3_rn_scen else sim_complex_sep
    s3_rn_c_data = next((c for c in s3_rn_sim.constituency_data if are_same_province(c["name"], s3_rn_prov)), s3_rn_sim.constituency_data[0])
    s3_rn_res = s3_rn_sim.constituency_results.get(s3_rn_prov) or s3_rn_c_data["result"]

    fig_s3_rn_stepped = create_dhondt_stepped_chart(
        votes=s3_rn_c_data["parties_votes"],
        result=s3_rn_res,
        title=f"Circunscripción de {get_province_display_name(s3_rn_prov)} ({s3_rn_c_data['seats']} escaños)",
        data_source=f"Recuento Nacional Complejo ({s3_rn_scen}) — {s3_selected_poll_name}",
        poll_date=s3_poll_date,
    )
    st.plotly_chart(fig_s3_rn_stepped, use_container_width=True, key=f"s3_rn_chart_{s3_rn_prov}")

    # ==============================================================================
    # SECCIÓN DE GOBERNABILIDAD Y MAYORÍA DE INVESTIDURA (176 ESCAÑOS)
    # ==============================================================================
    st.markdown("---")
    render_government_formation_section(
        model=model,
        sim_sep=sim_complex_sep,
        sim_coal=sim_complex_coal,
        section_key="s3",
        coalition_name=s3_coal_name,
        coalition_members=s3_effective_coal_members,
        default_target=176,
    )

# ==============================================================================
# SECCIÓN 4: AUDITORÍA, METODOLOGÍA E IMPORTACIÓN EXCEL
# ==============================================================================
with tab4:
    st.header(t("tab4_header"))
    st.markdown(t("tab4_desc"))

    # 1. Ingesta de Datos por Excel
    st.subheader("📥 Importar Encuesta Externa en Excel")
    st.markdown(
        """
        Si dispones de un sondeo propio o una encuesta publicada en medios que no figure en nuestro catálogo, 
        puedes cargarla directamente en formato **Excel (`.xlsx`)** o **CSV**.
        """
    )

    with st.expander("ℹ️ **Especificación del Formato Excel Requerido**", expanded=True):
        st.markdown(
            """
            El archivo Excel debe tener una hoja con las siguientes columnas mínimas:
            
            | Columna | Tipo | Descripción | Ejemplo |
            | :--- | :--- | :--- | :--- |
            | **Partido** | Texto | Nombre de la candidatura o fuerza política | `PP`, `PSOE`, `Vox`, `Sumar`, `Podemos`... |
            | **Porcentaje** | Número | Intención de voto estimada en porcentaje nacional (%) | `33.5`, `29.2`, `12.1`, `6.8`... |
            
            *Opcionalmente*, si deseas incluir datos desglosados por circunscripción, puedes utilizar columnas: `Circunscripcion` (o `Provincia`), `Partido`, `Porcentaje` (o `Votos`).
            
            > **ℹ️ Flexibilidad toponímica total:** Puedes indicar las circunscripciones en **castellano** (`Gerona`, `Lérida`, `Vizcaya`, `Guipúzcoa`, `Álava`, `La Coruña`, `Orense`, `Baleares`...), en su **lengua cooficial** (`Girona`, `Lleida`, `Bizkaia`, `Gipuzkoa`, `Araba`, `A Coruña`, `Ourense`, `Illes Balears`...) o en **denominación oficial compuesta** (`Alicante/Alacant`, `Castellón/Castelló`, `Valencia/València`, `Araba/Álava`). El motor toponímico mapea automáticamente cualquier variante sin pérdida de datos.
            """
        )

        # Generador de plantilla descargable en memoria
        sample_df = pd.DataFrame({
            "Partido": ["PP", "PSOE", "Vox", "Sumar", "Podemos", "SALF", "ERC", "Junts", "EH Bildu", "PNV", "BNG", "CC", "UPN"],
            "Porcentaje": [34.0, 29.5, 12.0, 6.5, 3.8, 3.2, 1.8, 1.5, 1.4, 1.1, 0.7, 0.5, 0.2],
        })
        excel_buffer = io.BytesIO()
        sample_df.to_excel(excel_buffer, index=False, engine="openpyxl")
        st.download_button(
            label="📥 Descargar Plantilla Excel de Ejemplo (.xlsx)",
            data=excel_buffer.getvalue(),
            file_name="plantilla_encuesta_electoral.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # Cargador de archivo
    uploaded_file = st.file_uploader("Subir archivo Excel o CSV con la encuesta:", type=["xlsx", "xls", "csv"], key="excel_uploader")
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".csv"):
                df_uploaded = pd.read_csv(uploaded_file)
            else:
                df_uploaded = pd.read_excel(uploaded_file)

            st.write("Vista previa del archivo cargado:")
            st.dataframe(df_uploaded.head(15), use_container_width=True)

            # Normalizar columnas
            cols_lower = {str(c).lower().strip(): c for c in df_uploaded.columns}
            col_partido = cols_lower.get("partido") or cols_lower.get("party") or cols_lower.get("candidatura")
            col_pct = cols_lower.get("porcentaje") or cols_lower.get("pct") or cols_lower.get("percentage") or cols_lower.get("voto") or cols_lower.get("votos")
            col_circ = cols_lower.get("circunscripcion") or cols_lower.get("provincia") or cols_lower.get("distrito")

            if col_partido and col_pct:
                if col_circ:
                    # Ingesta por circunscripción con normalización toponímica
                    prov_overrides = {}
                    col_pct_str = str(col_pct).lower()
                    is_votes_col = any(k in col_pct_str for k in ["voto", "votos", "votes", "papeleta", "papeletas"])
                    for _, row in df_uploaded.iterrows():
                        raw_prov = str(row[col_circ]).strip()
                        c_canon = normalize_province_name(raw_prov)
                        p_name = str(row[col_partido]).strip()
                        try:
                            val_num = float(str(row[col_pct]).replace(",", ".").replace("%", ""))
                        except (ValueError, TypeError):
                            continue
                        
                        # Si los números superan 100 o la columna es de votos, se toman como votos reales directos
                        row_mode = "votes" if (is_votes_col or val_num > 100) else "pct"
                        if c_canon not in prov_overrides:
                            prov_overrides[c_canon] = {"parties": {}, "input_mode": row_mode}
                        elif row_mode == "votes":
                            prov_overrides[c_canon]["input_mode"] = "votes"
                        prov_overrides[c_canon]["parties"][p_name] = val_num

                    if prov_overrides:
                        detected_mode_str = "Votos Reales Directos" if any(v.get("input_mode") == "votes" for v in prov_overrides.values()) else "Porcentajes Provinciales"
                        st.success(f"¡Datos provinciales validados ({detected_mode_str})! {len(prov_overrides)} circunscripciones identificadas con toponimia normalizada.")
                        if st.button("🚀 Cargar datos en el Control Circunscripción a Circunscripción (Sección 3)"):
                            for c_k, c_v in prov_overrides.items():
                                if c_k in st.session_state.constituency_overrides:
                                    st.session_state.constituency_overrides[c_k]["parties"] = c_v["parties"]
                                    st.session_state.constituency_overrides[c_k]["input_mode"] = c_v["input_mode"]
                                else:
                                    st.session_state.constituency_overrides[c_k] = c_v
                            st.success("Datos provinciales transferidos a la Sección 3.")
                            st.rerun()
                else:
                    # Ingesta nacional
                    custom_excel_date = st.text_input(
                        "Fecha de publicación o realización del sondeo:",
                        value="Octubre 2026",
                        key="custom_excel_date_input",
                        help="Fecha que aparecerá en los títulos y pies de las gráficas al utilizar esta encuesta.",
                    )
                    custom_excel_turnout = st.number_input(
                        "Participación estimada para esta encuesta (%):",
                        min_value=15.0,
                        max_value=98.0,
                        value=68.0,
                        step=0.5,
                        key="custom_excel_turnout_input",
                        help="Porcentaje de participación estimado sobre el censo electoral nacional.",
                    )
                    parsed_poll = {}
                    for _, row in df_uploaded.iterrows():
                        p_name = str(row[col_partido]).strip()
                        try:
                            p_val = float(str(row[col_pct]).replace(",", ".").replace("%", ""))
                            parsed_poll[p_name] = p_val
                        except (ValueError, TypeError):
                            pass

                    if parsed_poll:
                        st.success(f"¡Encuesta validada correctamente! {len(parsed_poll)} candidaturas detectadas.")
                        if st.button("🚀 Activar esta encuesta para todas las simulaciones"):
                            st.session_state.custom_excel_poll = parsed_poll
                            st.session_state.custom_excel_poll_date = custom_excel_date
                            st.session_state.custom_excel_poll_turnout = custom_excel_turnout
                            st.success("Encuesta activada. Ahora está disponible en la Sección 1 y Sección 3.")
                            st.rerun()
            else:
                st.error("El archivo debe contener al menos una columna de 'Partido' y una de 'Porcentaje'.")
        except Exception as e:
            st.error(f"Error al leer el archivo Excel: {e}")

    st.markdown("---")

    # 2. Auditoría de Fuentes Oficiales
    st.subheader("🏛️ Auditoría de Procedencia de Datos y Fechas de Publicación")
    st.markdown(
        """
        Para garantizar el rigor empírico y evitar datos artificiales o simulados no calibrados, este simulador se nutre de fuentes primarias fechadas:
        
        1. **Reparto Oficial de Escaños por Circunscripción:**
           - **Fuente:** [Boletín Oficial del Estado (BOE)](https://www.boe.es) - Real Decreto 806/2026, de 5 de octubre (BOE-A-2026-20742) y Real Decreto 400/2023.
           - Fija los **350 diputados** distribuidos en las 50 provincias y las 2 ciudades autónomas (Ceuta y Melilla), con Madrid (38) y Cádiz (8).
        
        2. **Resultados Electorales Históricos y Censo Oficial:**
           - **Fuente:** Ministerio del Interior de España (Infoelectoral) e Instituto Nacional de Estadística (INE).
           - **Fecha:** Elecciones Generales del **23 de julio de 2023** (37.466.432 electores, 24.7M votos, participación oficial definitiva JEC / BOE del 66,59%).
        
        3. **Sondeos Electorales Integrados (Catálogo con Fechas de Publicación Más Recientes):**
           - **40dB / El País - Cadena SER:** Publicado el **5 de octubre de 2026** (2.000 entrevistas online).
           - **ElectoPanel / Electomanía:** Publicado el **4 de octubre de 2026** (Panel continuo, 2.500 respuestas).
           - **Sigma Dos / El Mundo:** Publicado el **2 de octubre de 2026** (2.400 entrevistas).
           - **SocioMétrica / El Español:** Publicado el **28 de septiembre de 2026** (1.800 entrevistas).
           - **CIS (Barómetro de Intención de Voto):** Publicado el **14 de septiembre de 2026** (4.000 entrevistas, Estudio 3577).
           - **GAD3 / ABC:** Publicado el **4 de septiembre de 2026** (1.000 entrevistas telefónicas).
        """
    )

    st.markdown("---")

    # 3. Situación Electoral Oficial de España y Libros Excel Base
    st.subheader("🗺️ 3. Situación Electoral de España y Libros de Datos Base (Excel / Fuentes)")
    st.markdown(
        """
        El Congreso de los Diputados cuenta con un total constitucional de **350 escaños**, distribuidos entre las **52 circunscripciones electorales** 
        (las 50 provincias españolas más las dos ciudades autónomas de Ceuta y Melilla).
        
        De acuerdo con el **artículo 162 de la Ley Orgánica del Régimen Electoral General (LOREG)** y las disposiciones demográficas vigentes 
        (**Real Decreto 806/2026 y RD 400/2023**), la distribución de los escaños combina un suelo fijo de equidad territorial con un reparto proporcional a la población:
        - **102 escaños fijos iniciales:** Cada provincia tiene asignado por ley un mínimo de partida de **2 diputados** (100 en total), mientras que **Ceuta y Melilla eligen 1 diputado cada una** (2 en total).
        - **248 escaños poblacionales proporcionales:** Se distribuyen entre las 50 provincias en proporción directa a su población de derecho (censo oficial del INE), mediante el método del resto mayor (cuota Hare).
        - **Actualización demográfica oficial vigente (RD 806/2026):** Debido a la evolución de la población, **Madrid cuenta con 38 diputados (+1)** y **Cádiz con 8 diputados (-1)**.

        > **📑 Transparencia y Exploración de Datos:**  
        > A continuación puedes consultar e interactuar con cualquiera de las **4 hojas del libro de datos oficial** que alimentan los algoritmos de simulación, proyección demoscópica y optimización de escaños.
        """
    )

    datasets_dict = get_all_electoral_datasets()
    df_electoral = datasets_dict["Censo y Escaños Vigentes"]
    df_pct_23j = datasets_dict["Porcentajes 23J por Circunscripción"]
    df_seats_23j = datasets_dict["Escaños 23J por Circunscripción"]
    df_polls = datasets_dict["Catálogo de Sondeos Integrados"]

    # Botón maestro de descarga del libro completo consolidado
    col_master_btn, _ = st.columns([4, 4])
    with col_master_btn:
        full_excel_bytes = get_consolidated_electoral_excel()
        st.download_button(
            label="📦 Descargar Libro Excel Completo Consolidado (4 Hojas .xlsx)",
            data=full_excel_bytes,
            file_name="Libro_Electoral_Espana_Oficial_2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descarga un único archivo Excel con todas las hojas: Censo_y_Escaños, Porcentajes_23J, Escaños_23J y Sondeos_Demoscópicos.",
            key="btn_full_electoral_excel",
        )

    tab_hoja1, tab_hoja2, tab_hoja3, tab_hoja4 = st.tabs([
        "🏛️ Hoja 1: Censo y Escaños 2026 (RD 806/2026 - Convocatoria 29N)",
        "📊 Hoja 2: Resultados 23J en Porcentaje Provincial (%)",
        "⚖️ Hoja 3: Escaños 23J Adjudicados por Circunscripción",
        "📈 Hoja 4: Matriz de Sondeos Electorales Integrados",
    ])

    with tab_hoja1:
        st.markdown("##### 🏛️ Distribución Territorial de Escaños, Censo Oficial y Representatividad (Elecciones Generales 29N 2026)")
        st.caption(
            "Convocatoria oficial para el **29 de noviembre de 2026** regulada por el **Real Decreto 806/2026, de 5 de octubre** "
            "(BOE núm. 248) y censo electoral oficial cerrado a 1 de agosto de 2026 según el Instituto Nacional de Estadística (INE). "
            "El Anexo del Real Decreto asigna 38 diputados a Madrid (+1 respecto a 2023) y 8 diputados a Cádiz (-1 respecto a 2023)."
        )

        # Métricas clave a nivel nacional
        mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
        with mcol1:
            st.metric("🏛️ Total Escaños", "350", help="Escaños totales del Congreso fijados en el Anexo del RD 806/2026")
        with mcol2:
            st.metric(
                "👥 Censo Oficial 2026",
                f"{int(df_electoral['Censo Electoral'].sum()):,}".replace(",", "."),
                help="Censo electoral total oficial cerrado a 1 de agosto de 2026 (INE)",
            )
        with mcol3:
            st.metric("📍 Circunscripciones", "52", delta="50 Prov. + 2 Ciudades Aut.", delta_color="off")
        with mcol4:
            st.metric("⚖️ Escaños Fijos", "102", delta="100 prov. + 2 C.Aut.", delta_color="off")
        with mcol5:
            st.metric("📈 Escaños Proporcionales", "248", delta="Cuota Hare (población)", delta_color="off")

        # Controles de filtro, ordenación y búsqueda
        f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
        with f_col1:
            ccaa_list = ["Todas las Comunidades (52 circunscripciones)"] + sorted(list(CCAA_PROVINCES.keys()))
            selected_audit_ccaa = st.selectbox(
                "Filtrar por Comunidad Autónoma:",
                ccaa_list,
                key="audit_filter_ccaa_h1",
            )
        with f_col2:
            sort_options = [
                "Mayor número de escaños (Diputados)",
                "Mayor censo electoral",
                "Nombre alfabético de circunscripción",
                "Mayor ratio Electores / Diputado",
                "Menor ratio Electores / Diputado (Mayor sobrerrepresentación)",
            ]
            selected_sort = st.selectbox(
                "Criterio de ordenación:",
                sort_options,
                key="audit_filter_sort_h1",
            )
        with f_col3:
            search_audit = st.text_input(
                "Buscar circunscripción:",
                value="",
                placeholder="Ej: Madrid, Sevilla, Barcelona, Coruña...",
                key="audit_search_text_h1",
            )

        # Filtrar DataFrame
        filtered_df = df_electoral.copy()
        if selected_audit_ccaa != "Todas las Comunidades (52 circunscripciones)":
            filtered_df = filtered_df[filtered_df["Comunidad Autónoma"] == selected_audit_ccaa]

        if search_audit.strip():
            sterm = search_audit.strip().lower()
            filtered_df = filtered_df[
                filtered_df["Circunscripción"].str.lower().str.contains(sterm)
                | filtered_df["Comunidad Autónoma"].str.lower().str.contains(sterm)
            ]

        # Ordenar DataFrame
        if selected_sort == "Mayor número de escaños (Diputados)":
            filtered_df = filtered_df.sort_values(
                by=["Diputados (Escaños)", "Censo Electoral"], ascending=[False, False]
            )
        elif selected_sort == "Mayor censo electoral":
            filtered_df = filtered_df.sort_values(by="Censo Electoral", ascending=False)
        elif selected_sort == "Nombre alfabético de circunscripción":
            filtered_df = filtered_df.sort_values(by="Circunscripción", ascending=True)
        elif selected_sort == "Mayor ratio Electores / Diputado":
            filtered_df = filtered_df.sort_values(by="Electores por Escaño", ascending=False)
        elif selected_sort == "Menor ratio Electores / Diputado (Mayor sobrerrepresentación)":
            filtered_df = filtered_df.sort_values(by="Electores por Escaño", ascending=True)

        # Subtotal dinámico si hay filtro activo
        if selected_audit_ccaa != "Todas las Comunidades (52 circunscripciones)" or search_audit.strip():
            sub_seats = int(filtered_df["Diputados (Escaños)"].sum())
            sub_census = int(filtered_df["Censo Electoral"].sum())
            sub_pct_s = (sub_seats / 350) * 100
            sub_pct_c = (sub_census / int(df_electoral["Censo Electoral"].sum())) * 100
            st.info(
                f"📊 **Subtotal selección:** {len(filtered_df)} circunscripciones | "
                f"**{sub_seats} diputados** ({sub_pct_s:.2f}% de la Cámara) | "
                f"**{sub_census:,.0f}".replace(",", ".") + f" electores** ({sub_pct_c:.2f}% del censo nacional)."
            )

        # Renderizado interactivo de la tabla con configuración de columnas
        st.dataframe(
            filtered_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Circunscripción": st.column_config.TextColumn("Circunscripción", width="medium"),
                "Comunidad Autónoma": st.column_config.TextColumn("Comunidad Autónoma", width="medium"),
                "Diputados (Escaños)": st.column_config.NumberColumn("Diputados", format="%d dip."),
                "% de la Cámara": st.column_config.NumberColumn("% de la Cámara", format="%.2f%%"),
                "Censo Electoral": st.column_config.NumberColumn("Censo Electoral", format="%d"),
                "% del Censo Nacional": st.column_config.NumberColumn("% Censo Nac.", format="%.2f%%"),
                "Electores por Escaño": st.column_config.NumberColumn("Electores / Escaño", format="%d"),
            },
        )

        # Botones de exportación a CSV y Excel
        exp_col1, exp_col2, _ = st.columns([2, 2, 4])
        with exp_col1:
            csv_bytes = filtered_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Descargar Hoja 1 (CSV)",
                data=csv_bytes,
                file_name="hoja1_censo_y_escanos_espana.csv",
                mime="text/csv",
                key="btn_csv_situacion_electoral",
            )
        with exp_col2:
            x_buf = io.BytesIO()
            with pd.ExcelWriter(x_buf, engine="openpyxl") as x_writer:
                filtered_df.to_excel(x_writer, index=False, sheet_name="Censo_y_Escaños")
            st.download_button(
                label="📥 Descargar Hoja 1 (Excel)",
                data=x_buf.getvalue(),
                file_name="hoja1_censo_y_escanos_espana.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_excel_situacion_electoral",
            )

    with tab_hoja2:
        st.markdown("##### 📊 Resultados Electorales Oficiales 23J: Intención de Voto (%) por Circunscripción")
        st.caption(
            "Microdatos de intención de voto del 23J por circunscripción utilizados como cociente base en el modelo "
            "de Ratio Swing Proporcional para proyectar encuestas estatales hacia los 52 distritos."
        )

        f2_col1, f2_col2 = st.columns([3, 3])
        with f2_col1:
            sel_ccaa_h2 = st.selectbox(
                "Filtrar por Comunidad Autónoma:",
                ["Todas las Comunidades (52 circunscripciones)"] + sorted(list(CCAA_PROVINCES.keys())),
                key="audit_filter_ccaa_h2",
            )
        with f2_col2:
            search_h2 = st.text_input(
                "Buscar circunscripción:",
                value="",
                placeholder="Ej: Madrid, Bizkaia, A Coruña...",
                key="audit_search_text_h2",
            )

        filtered_pct = df_pct_23j.copy()
        if sel_ccaa_h2 != "Todas las Comunidades (52 circunscripciones)":
            filtered_pct = filtered_pct[filtered_pct["Comunidad Autónoma"] == sel_ccaa_h2]
        if search_h2.strip():
            sterm2 = search_h2.strip().lower()
            filtered_pct = filtered_pct[
                filtered_pct["Circunscripción"].str.lower().str.contains(sterm2)
                | filtered_pct["Comunidad Autónoma"].str.lower().str.contains(sterm2)
            ]

        col_cfg_pct = {
            "Circunscripción": st.column_config.TextColumn("Circunscripción", width="medium"),
            "Comunidad Autónoma": st.column_config.TextColumn("Comunidad Autónoma", width="medium"),
            "Diputados": st.column_config.NumberColumn("Diputados", format="%d"),
            "Censo": st.column_config.NumberColumn("Censo", format="%d"),
            "Votos Válidos": st.column_config.NumberColumn("Votos Válidos", format="%d"),
        }
        for party_col in model.parties:
            if party_col in filtered_pct.columns:
                col_cfg_pct[party_col] = st.column_config.NumberColumn(party_col, format="%.2f%%")

        st.dataframe(
            filtered_pct,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg_pct,
        )

        exp2_col1, exp2_col2, _ = st.columns([2, 2, 4])
        with exp2_col1:
            csv_pct_bytes = filtered_pct.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Descargar Hoja 2 (CSV)",
                data=csv_pct_bytes,
                file_name="hoja2_porcentajes_23j_provincial.csv",
                mime="text/csv",
                key="btn_csv_pct_23j",
            )
        with exp2_col2:
            x_buf2 = io.BytesIO()
            with pd.ExcelWriter(x_buf2, engine="openpyxl") as x_writer2:
                filtered_pct.to_excel(x_writer2, index=False, sheet_name="Porcentajes_23J")
            st.download_button(
                label="📥 Descargar Hoja 2 (Excel)",
                data=x_buf2.getvalue(),
                file_name="hoja2_porcentajes_23j_provincial.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_excel_pct_23j",
            )

    with tab_hoja3:
        st.markdown("##### ⚖️ Resultados Electorales Oficiales 23J: Escaños Adjudicados por Circunscripción")
        st.caption(
            "Reparto de los 350 escaños adjudicados el 23 de julio de 2023 por circunscripción, que sirven como punto de partida histórico "
            "para calcular ganancias y pérdidas netas de escaños en todos los escenarios."
        )

        f3_col1, f3_col2 = st.columns([3, 3])
        with f3_col1:
            sel_ccaa_h3 = st.selectbox(
                "Filtrar por Comunidad Autónoma:",
                ["Todas las Comunidades (52 circunscripciones)"] + sorted(list(CCAA_PROVINCES.keys())),
                key="audit_filter_ccaa_h3",
            )
        with f3_col2:
            search_h3 = st.text_input(
                "Buscar circunscripción:",
                value="",
                placeholder="Ej: Madrid, Barcelona, Valencia...",
                key="audit_search_text_h3",
            )

        filtered_seats = df_seats_23j.copy()
        if sel_ccaa_h3 != "Todas las Comunidades (52 circunscripciones)":
            filtered_seats = filtered_seats[filtered_seats["Comunidad Autónoma"] == sel_ccaa_h3]
        if search_h3.strip():
            sterm3 = search_h3.strip().lower()
            filtered_seats = filtered_seats[
                filtered_seats["Circunscripción"].str.lower().str.contains(sterm3)
                | filtered_seats["Comunidad Autónoma"].str.lower().str.contains(sterm3)
            ]

        col_cfg_seats = {
            "Circunscripción": st.column_config.TextColumn("Circunscripción", width="medium"),
            "Comunidad Autónoma": st.column_config.TextColumn("Comunidad Autónoma", width="medium"),
            "Total Escaños": st.column_config.NumberColumn("Total Escaños", format="%d"),
        }
        for party_col in model.parties:
            if party_col in filtered_seats.columns:
                col_cfg_seats[party_col] = st.column_config.NumberColumn(party_col, format="%d")

        st.dataframe(
            filtered_seats,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg_seats,
        )

        exp3_col1, exp3_col2, _ = st.columns([2, 2, 4])
        with exp3_col1:
            csv_seats_bytes = filtered_seats.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Descargar Hoja 3 (CSV)",
                data=csv_seats_bytes,
                file_name="hoja3_escanos_23j_provincial.csv",
                mime="text/csv",
                key="btn_csv_seats_23j",
            )
        with exp3_col2:
            x_buf3 = io.BytesIO()
            with pd.ExcelWriter(x_buf3, engine="openpyxl") as x_writer3:
                filtered_seats.to_excel(x_writer3, index=False, sheet_name="Escaños_23J")
            st.download_button(
                label="📥 Descargar Hoja 3 (Excel)",
                data=x_buf3.getvalue(),
                file_name="hoja3_escanos_23j_provincial.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_excel_seats_23j",
            )

    with tab_hoja4:
        st.markdown("##### 📈 Matriz Comparativa de Sondeos Electorales Integrados")
        st.caption(
            "Catálogo de encuestas y barómetros demoscópicos incorporados al sistema, con sus fechas oficiales de publicación, "
            "tamaño muestral de campo y porcentajes estimados de voto."
        )

        col_cfg_polls = {
            "Sondeo / Empresa": st.column_config.TextColumn("Sondeo / Empresa", width="large"),
            "Fecha Publicación": st.column_config.TextColumn("Fecha", width="medium"),
            "Muestra": st.column_config.TextColumn("Muestra", width="medium"),
            "Participación Est. (%)": st.column_config.TextColumn("Participación Est."),
        }
        for col in df_polls.columns:
            if col not in ["Sondeo / Empresa", "Fecha Publicación", "Muestra", "Participación Est. (%)"]:
                col_cfg_polls[col] = st.column_config.NumberColumn(col, format="%.1f%%")

        st.dataframe(
            df_polls,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg_polls,
        )

        exp4_col1, exp4_col2, _ = st.columns([2, 2, 4])
        with exp4_col1:
            csv_polls_bytes = df_polls.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Descargar Hoja 4 (CSV)",
                data=csv_polls_bytes,
                file_name="hoja4_sondeos_integrados.csv",
                mime="text/csv",
                key="btn_csv_polls_mat",
            )
        with exp4_col2:
            x_buf4 = io.BytesIO()
            with pd.ExcelWriter(x_buf4, engine="openpyxl") as x_writer4:
                df_polls.to_excel(x_writer4, index=False, sheet_name="Sondeos_Demoscópicos")
            st.download_button(
                label="📥 Descargar Hoja 4 (Excel)",
                data=x_buf4.getvalue(),
                file_name="hoja4_sondeos_integrados.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_excel_polls_mat",
            )

    st.markdown("---")

    # 4. Metodología Exhaustiva del Estudio y Fundamentos Matemáticos
    st.subheader("📚 4. Metodología Exhaustiva del Estudio, Fundamentos Matemáticos y Opciones")
    st.markdown(
        """
        Esta sección documenta formalmente la arquitectura algorítmica, los fundamentos sociopolíticos y las fórmulas matemáticas 
        empleadas en cada uno de los motores del simulador, así como las **razones y motivos** que justifican cada opción disponible.
        """
    )
    with st.expander("🔄 **Diagramas de Flujo y Arquitectura por Pestaña (Pipelines de Datos y Conexión con el Optimizador)**", expanded=True):
        st.markdown(
            """
            ### ¿Cómo viajan los datos dentro del simulador?
            Para comprender con precisión cómo se procesan las opciones seleccionadas y cómo se alimenta el motor de optimización, 
            a continuación se detalla la arquitectura de flujo de cada una de las pestañas del sistema mediante diagramas interactivos compilados.
            
            ---
            
            #### 🌐 Esquema General de Propagación de Datos hacia el Optimizador
            El Optimizador de Gobernabilidad e Investidura **nunca opera de forma aislada o con datos desconectados**: 
            toma como punto de partida exacto los dos objetos de simulación (`sim_sep` y `sim_coal`) resultantes de todas las modificaciones previas.
            """
        )

        diag_general = """flowchart TD
    A["1. Sondeo Base o 23J Oficial"] --> B["2. Tus Modificaciones Previas<br/>(Porcentajes, Retenciones, Ámbitos territoriales, Overrides Provinciales)"]
    B --> C["3. Motor de Simulación Nacional<br/>(sim_sep y sim_coal calculados con D'Hondt)"]
    C --> D["4. Recuento Nacional y Gráficos del Congreso (350 esc.)"]
    C --> E["5. Optimizador de Gobernabilidad (176 Escaños)"]
    E --> F["6. Hoja de Ruta y Gráfica de Escaños a Conquistar"]"""
        render_mermaid(diag_general, height=440)
        with st.expander("📝 Ver especificación Mermaid (Esquema General)", expanded=False):
            st.code(diag_general, language="mermaid")

        st.markdown(
            """
            ---
            
            #### 1️⃣ Pestaña 1: Simulación Nacional Simple (Flujo Macro Lineal)
            - **Arquitectura:** Flujo macroestatal directo de arriba a abajo.
            - **Tratamiento territorial:** Aplica una regla homogénea a toda España. Todos los distritos siguen la misma lista única y la misma tasa de retención global $R$.
            """
        )

        diag_tab1 = """flowchart TD
    P1["1. Sondeo Base o 23J"] --> P2["2. Ajuste Opcional de % Nacionales"]
    P2 --> P3["3. Configuración de Coalición<br/>(Integrantes, Nombre, Retención Global R, Umbral 3%)"]
    P3 --> P4["4. Proyección Swing Proporcional (52 provincias)"]
    P4 --> P5["5. Repartos D'Hondt Nacionales<br/>(Separados vs. Coalición)"]
    P5 --> P6["6. Recuento del Congreso (350 esc.) y Gráfica Escalonada"]
    P5 --> P7["7. Optimizador de Gobernabilidad (176 Escaños)"]
    P7 --> P8["8. Hoja de Ruta de Campaña Hacia la Investidura"]"""
        render_mermaid(diag_tab1, height=520)
        with st.expander("📝 Ver especificación Mermaid (Pestaña 1)", expanded=False):
            st.code(diag_tab1, language="mermaid")

        st.markdown(
            """
            ---
            
            #### 🧪 2️⃣ Pestaña 2: Simulación Compleja de una Sola Circunscripción (Laboratorio Micro Local Aislado)
            - **Arquitectura:** **Laboratorio microelectoral puro** enfocado exclusivamente en un único distrito electoral.
            - **Diferencia fundamental con las pestañas nacionales:** **No incluye optimizador nacional de 176 escaños ni proyección macroestatal**. Se centra en responder a la *Pregunta Clave Local* con búsqueda binaria de votos adicionales y gráficas escalonadas descendentes cara a cara.
            """
        )

        diag_tab2 = """flowchart TD
    L1["1. Carga de 1 Provincia<br/>(23J Oficial, Sondeo Proyectado o Plantilla Libre)"] --> L2["2. Parámetros Electorales Locales<br/>(Censo, Participación, Nulos, Blancos, Barrera 3%)"]
    L2 --> L3["3. Fuga de Votos Partido a Partido<br/>(Retención Individual Rp)"]
    L3 --> L4["4. Doble Reparto D'Hondt Provincial<br/>(Escenario Separados vs. Escenario Coalición)"]
    L4 --> L5["5. Algoritmo de Búsqueda Binaria Local (m*)<br/>(Votos adicionales, Candidatura Beneficiaria, Umbral local R*)"]
    L4 --> L6["6. Gráficas Escalonadas Descendentes Cara a Cara<br/>(Peldaños divididos vs. Peldaño unificado)"]
    L4 --> L7["7. Mapa de Contexto Geográfico Territorial"]"""
        render_mermaid(diag_tab2, height=480)
        with st.expander("📝 Ver especificación Mermaid (Pestaña 2)", expanded=False):
            st.code(diag_tab2, language="mermaid")

        st.markdown(
            """
            ---
            
            #### ⚙️ 3️⃣ Pestaña 3: Simulación Nacional Compleja (Control Total, Overrides y Agregador)
            - **Arquitectura:** Jerarquía multicapa con **Matriz de Overrides Provinciales** y **Ámbitos de Concurrencia Territorial**.
            - **Diferencia con la Pestaña 1:** Mientras la Pestaña 1 aplica reglas homogéneas, la Pestaña 3 permite diseñar escenarios heterogéneos y asimétricos (ej. coalición en Madrid y Cataluña pero separados en Andalucía; o fijar votos directos en distritos clave). El recuento compila aplicando la **Regla de Prioridad**: el ajuste provincial (`constituency_overrides`) siempre prevalece sobre la preconfiguración general, y esta sobre el sondeo base.
            - **Conexión con el Optimizador:** El optimizador de la Pestaña 3 hereda todos los microajustes provinciales y territoriales para calcular el camino hacia los 176 escaños.
            """
        )

        diag_tab3 = """flowchart TD
    N1["1. Sondeo Base o 23J"] --> N2["2. Capa A: Preconfiguración General<br/>(Ámbitos Territoriales de cada lista + Retenciones Individuales Rp)"]
    N2 --> N3["3. Capa B: Control Circunscripción a Circunscripción<br/>(Overrides de censo, participación, votos/porcentajes y coalición local)"]
    N3 --> N4["4. Capa C: Compilación con Regla de Prioridad<br/>(Overrides Provinciales > Preconfiguración > Sondeo Base)"]
    N4 --> N5["5. Generación de sim_complex_sep y sim_complex_coal<br/>(52 repartos D'Hondt con datos consolidados)"]
    N5 --> N6["6. Recuento Nacional 350 Diputados<br/>(Balance de transferencias, mapa electoral nacional)"]
    N5 --> N7["7. Optimizador de Gobernabilidad (176 Escaños)<br/>(Hereda todos los overrides provinciales y territoriales)"]
    N7 --> N8["8. Hoja de Ruta Estratégica Hacia la Investidura"]"""
        render_mermaid(diag_tab3, height=540)
        with st.expander("📝 Ver especificación Mermaid (Pestaña 3)", expanded=False):
            st.code(diag_tab3, language="mermaid")
            
        st.markdown(
            """
            ---
            
            #### 📋 Cuadro Comparativo de Arquitectura y Capacidades entre Pestañas
            
            | Característica / Capacidad | 1️⃣ Pestaña 1 (Simple) | 🧪 2️⃣ Pestaña 2 (Micro Local) | ⚙️ 3️⃣ Pestaña 3 (Compleja Total) |
            | :--- | :---: | :---: | :---: |
            | **Ámbito territorial de análisis** | Nacional (52 circunscripciones) | 1 Circunscripción aislada | Nacional (52 circunscripciones) |
            | **Modificación de % nacionales del sondeo** | ✅ Sí (Expander interactivo) | ❌ No aplicable | ❌ No (Utiliza sondeo base) |
            | **Ámbito territorial de cada candidatura** | Automático / Estándar | ❌ No aplicable | ✅ Sí (52 provincias, autonómico o a medida) |
            | **Tasa de retención de la coalición** | Homogénea (1 valor $R$ para todas) | Específica por partido ($R_p$) | Específica por partido ($R_p$) |
            | **Ajustes manuales provincia a provincia (Overrides)** | ❌ No | ✅ Sí (En la provincia activa) | ✅ Sí (En cualquiera de las 52 provincias) |
            | **Coaliciones locales asimétricas (por provincia)** | ❌ No | ✅ Sí | ✅ Sí |
            | **Recuento del Congreso (350 diputados)** | ✅ Sí | ❌ No | ✅ Sí |
            | **Laboratorio D'Hondt micro y Pregunta Clave local** | ❌ No | ✅ Sí (Búsqueda binaria local) | ❌ No |
            | **Optimizador de Gobernabilidad hacia 176 escaños** | ✅ Sí (Hereda la simulación simple) | ❌ No | ✅ Sí (Hereda todos los overrides y ámbitos) |
            """
        )

        st.markdown(
            """
            ### El Congreso de los Diputados (350 Escaños y 52 Circunscripciones)
            A diferencia de sistemas de circunscripción única nacional (como Países Bajos o Israel), en España las elecciones generales 
            son en realidad **52 elecciones provinciales independientes y simultáneas**.
            
            De acuerdo con el **artículo 162 de la LOREG**:
            1. **Asignación inicial fija:** Cada una de las 50 provincias tiene asignado un mínimo de partida de **2 diputados** (100 en total), mientras que las ciudades autónomas de **Ceuta y Melilla eligen 1 diputado cada una** (2 en total). Esto suma **102 escaños fijos**.
            2. **Reparto proporcional a la población:** Los **248 escaños restantes** se distribuyen entre las 50 provincias en proporción directa a su población de derecho (censo oficial del INE), mediante el método del resto mayor (cuota Hare).
            3. **Actualización demográfica oficial vigente (Real Decreto 806/2026 y RD 400/2023):**
               - **Comunidad de Madrid:** Debido a su crecimiento demográfico relativo, pasa de 37 a **38 diputados** (+1).
               - **Cádiz:** Debido a la evolución relativa de su censo, pasa de 9 a **8 diputados** (-1).
               - El total nacional se mantiene exactamente en **350 escaños**.
            
            > **Motivo y Razón de la Opción:**  
            > El simulador calcula todos los repartos sobre el marco demográfico oficial vigente (Madrid 38, Cádiz 8), garantizando que las proyecciones de encuestas y escenarios de coalición reflejen con total exactitud la composición del Congreso que saldría de las urnas en la próxima convocatoria electoral.
            >  
            > 📊 **Tabla Interactiva de Situación Electoral:**  
            > Puedes consultar, filtrar por Comunidad Autónoma y descargar la tabla completa de las 52 circunscripciones con sus censos, escaños, porcentajes y ratios de electores por diputado en el apartado **3. Situación Electoral de España** situado más arriba en esta misma pestaña.
            """
        )

    with st.expander("⚖️ 2. Ley D'Hondt, Barrera Legal del 3% y Umbral Efectivo de Lijphart", expanded=False):
        st.markdown(
            r"""
            ### Algoritmo de la Ley D'Hondt (art. 163 LOREG)
            En cada circunscripción, el reparto de los $S$ escaños en liza se efectúa mediante cocientes sucesivos:
            $$\text{Cociente}_{p, k} = \frac{V_p}{k}, \quad \text{donde } k \in \{1, 2, \dots, S\}$$
            Los escaños se adjudican de forma descendente a los $S$ mayores cocientes de la circunscripción.
            
            ### Barrera Legal (3% de los Votos Válidos)
            No se tienen en cuenta aquellas candidaturas que no alcancen, al menos, el **3% de los votos válidos** emitidos en la circunscripción (suma de votos a candidaturas + votos en blanco).
            
            ### Umbral Efectivo de Lijphart vs. Umbral Legal
            Aunque la ley fija un 3%, en la práctica parlamentaria española ese umbral solo es relevante en las grandes urbes (Madrid y Barcelona). En el resto de España, la magnitud de la provincia impone un **umbral efectivo real** infinitamente más estricto, formalizado por el politólogo Arend Lijphart:
            $$T_{\text{efectivo}} \approx \frac{75\%}{S + 1}$$
            
            | Tipo de Circunscripción | Magnitud ($S$) | Umbral Efectivo Real | Efecto Político sobre Fuerzas Divididas |
            | :--- | :--- | :--- | :--- |
            | **Pequeña** (ej. Soria, Teruel, Segovia, Ávila) | 2 a 3 escaños | **18% al 25%** | Bipartidismo férreo. Cualquier fuerza por debajo del 18% queda a 0 escaños. |
            | **Mediana** (ej. Ciudad Real, Córdoba, Navarra, Girona) | 5 a 6 escaños | **10% al 13%** | Terceras y cuartas fuerzas disputan el último escaño; la división penaliza con pérdida total de escaño. |
            | **Grande** (ej. Madrid, Barcelona, Valencia, Sevilla) | 12 a 38 escaños | **2.5% al 5%** | Alta proporcionalidad; la barrera legal del 3% cobra operatividad real. |
            
            ### Gráficas Escalonadas Descendentes (Stepped Charts)
            Visualizan los cocientes ordenados de mayor a menor como peldaños descendentes. La línea roja horizontal marca el **cociente de corte** (el valor del último escaño asignado). Cualquier peldaño que quede por debajo de esa línea representa votos que no obtienen representación.
            """
        )

    with st.expander("📈 3. Proyección Territorial de Encuestas: Proportional Ratio Swing Model", expanded=False):
        st.markdown(
            r"""
            ### ¿Cómo se traslada un sondeo nacional a las 52 provincias?
            Una encuesta nacional únicamente publica porcentajes agregados de voto para toda España (ej. PP 33%, PSOE 29%, Vox 12%, Sumar 7%...). Sin embargo, los escaños se deciden provincia a provincia.
            
            Para proyectar dicha intención de voto sin inventar datos locales artificiales, el simulador utiliza el **Proportional Ratio Swing Model**, estándar internacional en ciencia política:
            $$V_{p, c}^{\text{proyectado}} = V_{p, c}^{\text{23J}} \times \left( \frac{\%_{\text{Sondeo}, p}^{\text{nacional}}}{\%_{\text{23J}, p}^{\text{nacional}}} \right)$$
            
            Seguidamente, los votos proyectados se ajustan mediante un algoritmo de convergencia iterativa para que la participación y los votos válidos respeten el censo electoral oficial de cada circunscripción:
            $$\sum_{p} V_{p, c} + \text{Blancos}_c = \text{Votos Válidos}_c$$
            
            ### ¿Por qué Ratio Swing Proporcional en lugar de Uniform Swing Aditivo?
            - **Uniform Swing ($\Delta\%$ aditivo):** Suma o resta una diferencia idéntica en todas las provincias (ej. si el PSOE sube +2% nacional, suma +2% en todas partes).  
              *Problema grave:* Genera aberraciones demoscópicas, como porcentajes negativos en provincias donde un partido es minoritario, o distorsiones en bastiones autonómicos.
            - **Ratio Swing (Proporcional):** Multiplica por la tasa de cambio relativo.  
              *Ventaja crucial:* **Preserva los bastiones socioterritoriales**. Si un partido crece un 10% relativo a nivel estatal, crece proporcionalmente más donde ya tiene mucho voto y menos donde es testimonial, respetando la estructura identitaria de Cataluña, País Vasco, Galicia, Andalucía o Madrid.
            
            ### Tratamiento de Nuevas Fuerzas y Partidos Regionales
            - **Nuevas candidaturas estatales (ej. Se Acabó La Fiesta / SALF):** Al no contar con resultado en el 23J, su penetración se calibra correlacionando el voto de derechas y desafección por provincia, asegurando que no aparezcan con distribución plana irreal.
            - **Partidos territoriales (Adelante Andalucía, BNG, CC, UPN, PNV, Bildu, ERC, Junts):** Su voto se restringe estrictamente a sus circunscripciones de concurrencia legal, blindando que no reciban votos en provincias donde no presentan candidatura.
            """
        )

    with st.expander("🤝 4. Comparativa Dual: Listas Separadas vs. Coalición Unitaria y Retención", expanded=False):
        st.markdown(
            r"""
            ### La Paradoja de la Unidad Electoral
            Unir dos o más fuerzas políticas bajo una candidatura unitaria (ej. Sumar + Podemos) produce dos efectos contrapuestos:
            1. **Efecto Palanca D'Hondt (+):** Agrupa papeletas dispersas para superar el umbral efectivo en provincias medianas, conquistando escaños que por separado se perderían.
            2. **Efecto Fuga / Desafección (-):** En la práctica electoral, $1 + 1$ casi nunca suma $2$. Parte de los electores de cada fuerza pueden desmovilizarse, abstenerse o votar a otra opción si rechazan el pacto de coalición.
            
            ### Tasa de Retención Individual Partido a Partido ($R_p \in [40\%, 120\%]$)
            El simulador permite calibrar qué porcentaje de sus votos aporta cada partido a la lista única al unirse:
            $$V_{\text{Coalición}, c} = \sum_{m \in \text{socios}} V_{m, c} \times R_m$$
            - **$R_m = 100\%$:** Retención perfecta (suma pura aritmética).
            - **$R_m < 100\%$:** Desafección y fuga hacia la abstención u otros partidos (ej. $R_{\text{Sumar}} = 95\%$, $R_{\text{Podemos}} = 85\%$).
            - **$R_m > 100\%$:** Efecto ilusión / entusiasmo donde la unidad moviliza a votantes que antes se abstenían (ej. $110\%$).
            
            ### Umbral de Rentabilidad Electoral ($R^*$)
            Calcula mediante barrido paramétrico el **punto de indiferencia** exacto:
            $$R^* = \min \left\{ R \in [0.4, 1.2] \mid \text{Escaños}_{\text{Coalición}}(R) \ge \text{Escaños}_{\text{Separados}} \right\}$$
            > **Razón y Utilidad Estratégica:**  
            > Responde cuantitativamente a la pregunta clave: *"¿Cuánta fuga interna de votantes puede permitirse la coalición antes de que fuera mejor competir por separado?"*. Si $R^* = 85\%$, la lista conjunta puede perder hasta un $15\%$ de su electorado y aun así rentabilizar mejor los escaños que yendo divididos.
            """
        )

    with st.expander("🎯 5. Optimizador de Gobernabilidad e Investidura (Hacia los 176 Escaños)", expanded=False):
        st.markdown(
            r"""
            ### Propósito y Algoritmo de Búsqueda Binaria Monótona
            En el sistema parlamentario español, gobernar exige alcanzar la mayoría absoluta de **176 escaños** (o una mayoría suficiente de investidura).  
            El optimizador resuelve de forma exacta el **camino marginalmente más eficiente** (menor esfuerzo) para que el bloque de gobierno (Lista Única o Separados junto a sus socios de investidura: PSOE, ERC, Bildu, PNV, BNG...) alcance la meta.
            
            En cada paso, el algoritmo evalúa las 52 circunscripciones, ejecuta una **búsqueda binaria exacta de 30 iteraciones** para hallar el mínimo de votos que produce $+1$ escaño neto para el bloque, y selecciona la provincia de menor coste según el criterio configurado.
            
            ---
            
            ### Los 4 Criterios de Optimización: Razones, Motivos y Fórmulas
            
            #### 1. 📊 Puntos % Provinciales ($\Delta\%_{\text{prov}}$) — *[Recomendado]*
            - **Fórmula de coste:**
              $$\text{Coste} = \frac{\Delta V_c}{\text{Votos Válidos}_c} \times 100$$
            - **Motivo y Razón de Ser:**  
              Neutraliza el sesgo de las provincias pequeñas. Mover un $1\%$ del electorado en Madrid exige ~27.000 votos, mientras que en Soria exige ~500 votos; sin embargo, en términos de opinión pública, convencer al $1\%$ de los ciudadanos locales representa un esfuerzo de persuasión sociológica equivalente. Este criterio prioriza escaños donde el electorado local debe desplazarse lo mínimo hacia el bloque.
            
            #### 2. 🏛️ Crecimiento % del Partido ($\Delta\%_{\text{partido}}$)
            - **Fórmula de coste:**
              $$\text{Coste} = \frac{\Delta V_c}{V_{\text{partido}, c}^{\text{inicial}}} \times 100$$
            - **Motivo y Razón de Ser:**  
              Mide la exigencia orgánica impuesta a la candidatura. En muchas provincias pequeñas, ganar un escaño requiere que una fuerza pase de 4.000 a 20.000 votos (un crecimiento del $+400\%$), algo inviable para la estructura de campaña de un partido minoritario. Este criterio prioriza provincias donde el partido ya cuenta con masa crítica previa e implantación sólida, exigiendo crecimientos orgánicos moderados (ej. $+8\%$ o $+12\%$).
            
            #### 3. ⚖️ Híbrido Ponderado (Media Geométrica Cobb-Douglas con $\alpha \in [0, 1]$)
            - **Fórmula de coste:**
              $$\text{Coste} = \left(\Delta\%_{\text{prov}}\right)^{1 - \alpha} \times \left(\Delta\%_{\text{partido}}\right)^{\alpha}$$
            - **Motivo y Razón de Ser:**  
              Ninguna campaña electoral opera en un vacío puramente sociológico ni puramente de aparato. El criterio híbrido interpola ambas dimensiones mediante una media geométrica multiplicativa:
              - Si $\alpha = 0.0$: Equivale exactamente al criterio provincial puro (opinión pública).
              - Si $\alpha = 1.0$: Equivale exactamente al criterio de partido puro (aparato orgánico).
              - Si $\alpha = 0.50$: Pondera al $50\%$ la facilidad sociológica de convencer al votante provincial y al $50\%$ el esfuerzo de movilización exigido al partido.
            
            #### 4. 🔢 Votos Brutos Absolutos ($\Delta V$)
            - **Fórmula de coste:**
              $$\text{Coste} = \Delta V_c$$
            - **Motivo y Razón de Ser:**  
              Representa el mínimo cuantitativo tradicional en bruto.  
              *Sesgo importante a tener en cuenta:* Al buscar el menor número de papeletas absolutas, tiende a concentrar artificialmente los escaños en provincias despobladas (donde un diputado cuesta 25.000 votos en lugar de los 80.000 de Madrid), aunque en la práctica requiera incrementos desproporcionados en el porcentaje de voto local.
            
            ---
            
            ### Restricciones Avanzadas y Modelado de Caladeros de Voto
            
            1. **Movilización de la Abstención (Voto Nuevo) y Cota Física:**
               - Permite captar votos de electores que no acudieron a las urnas.
               - Fija un **tope máximo de incremento de participación** (ej. $+4.0\%$ puntos porcentuales) para impedir escenarios mágicos de hiperafluencia a las urnas.
               - **Cota física infranqueable:** En ningún caso el número total de votos emitidos puede rebasar el **100% del censo electoral provincial**.
            
            2. **Porosidad Dinámica y Partidos Donantes:**
               - Modela la transferencia de votos desde fuerzas rivales (PP, Vox, SALF, Otros...). Cada partido donante tiene una tasa máxima de trasvase (porosidad) sobre sus votos iniciales.
            
            3. **Blindaje Estricto de Socios de Investidura:**
               - **Evita el "fuego amigo":** Bloquea totalmente la captación de votos provenientes del PSOE, ERC, Bildu, PNV o BNG cuando el blindaje está activado.
               - *Motivo:* Captar votos de un socio para engordar a la lista única podría provocar que el socio pierda un escaño en esa misma provincia, destruyendo la mayoría del bloque en lugar de sumarla.
            
            4. **Caladeros Específicos por Candidatura (Sección 4 del Optimizador):**
               - Permite definir caladeros de porosidad asimétricos y exclusivos para cada fuerza política o para la lista única.
               - *Coherencia del modelo:* La configuración específica sobrescribe las tasas generales de la Sección 2, pero **el blindaje de socios nunca se sobrescribe**.
            
            5. **Tope de Crecimiento Máximo por Circunscripción:**
               - Impide que una candidatura multiplique sus votos por encima de un umbral realista fijado (ej. máximo $+80\%$ en una provincia), evitando concentraciones extremas.
            
            6. **Modulador de Swing Previo de Campaña (Tracking):**
               - Permite simular dinámicas de última hora (desgaste de gobierno, auge de oposición) ajustando automáticamente la suma total al $100\%$ mediante reequilibrio con abstención y trasvases.
            """
        )

    with st.expander("📥 6. Ingesta e Importación de Sondeos Propios (Excel / CSV)", expanded=False):
        st.markdown(
            """
            ### Flexibilidad en la Carga de Encuestas
            El cargador integrado admite archivos `.xlsx`, `.xls` y `.csv` tanto para sondeos nacionales como para microdatos provinciales:
            - **Modo Nacional:** Requiere columnas `Partido` y `Porcentaje`. El motor valida la suma y proyecta los datos a toda España mediante el Ratio Swing Proporcional.
            - **Modo Provincial:** Si se incluye una columna de `Circunscripción` (o `Provincia`), el simulador aplica los valores como *overrides* específicos de cada territorio.
            - **Normalización Toponímica Automática:** El analizador resuelve cualquier denominación toponímica en castellano (`Vizcaya`, `Gerona`), cooficial (`Bizkaia`, `Girona`), oficial compuesta (`Alicante/Alacant`) o formatos INE (`Rioja, La`), garantizando una ingesta limpia y sin fallos de coincidencia.
            """
        )
