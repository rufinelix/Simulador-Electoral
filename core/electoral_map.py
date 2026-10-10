"""
Módulo de visualización cartográfica interactiva de España para el simulador electoral.
Genera mapas coropléticos de las 52 circunscripciones (50 provincias + Ceuta y Melilla)
con soporte para inserción cartográfica de Canarias (inset), paleta accesible colorblind-friendly,
textos informativos enriquecidos (hover tooltips), comparativa entre lista única y candidaturas
por separado, e inspección detallada distrito a distrito.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import functools

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

try:
    import streamlit as st
except ImportError:
    st = None

try:
    from core.toponyms import (
        normalize_province_name,
        get_province_display_name,
        are_same_province,
        PROVINCES_DATA,
    )
    from core.stepped_chart import get_party_color, PARTY_COLORS
    from core.national_model import NationalSimulationResult
except ImportError:
    from .toponyms import (
        normalize_province_name,
        get_province_display_name,
        are_same_province,
        PROVINCES_DATA,
    )
    from .stepped_chart import get_party_color, PARTY_COLORS
    from .national_model import NationalSimulationResult

DATA_DIR = Path(__file__).parent.parent / "data"
GEOJSON_INSET_PATH = DATA_DIR / "spain_provinces_inset.geojson"
GEOJSON_ORIG_PATH = DATA_DIR / "spain_provinces.geojson"


@functools.lru_cache(maxsize=2)
def load_spain_geojson(use_inset: bool = True) -> Dict[str, Any]:
    """
    Carga el GeoJSON con las 52 circunscripciones electorales de España.
    Si use_inset=True, carga la cartografía con las Islas Canarias reubicadas
    en el recuadro inferior izquierdo (estándar oficial INE / RTVE).
    """
    path = GEOJSON_INSET_PATH if use_inset else GEOJSON_ORIG_PATH
    if not path.exists():
        path = GEOJSON_ORIG_PATH if path == GEOJSON_INSET_PATH else GEOJSON_INSET_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_constituency_electoral_summary(
    sim_result: NationalSimulationResult,
    comparison_result: Optional[NationalSimulationResult] = None,
    coalition_name: str = "Lista Única",
    coalition_members: Optional[List[str]] = None,
    is_active_separated: bool = False,
) -> pd.DataFrame:
    """
    Construye un DataFrame estructurado con todos los detalles electorales
    de las 52 circunscripciones a partir de una simulación nacional.
    Permite alternar si el escenario activo es la coalición o ir por separado.
    """
    members = list(coalition_members or ["Sumar", "Podemos"])
    rows = []

    comp_info_by_name = {}
    if comparison_result and hasattr(comparison_result, "constituency_data") and comparison_result.constituency_data:
        comp_info_by_name = {ci.get("name"): ci for ci in comparison_result.constituency_data}

    for c_info in sim_result.constituency_data:
        c_name = c_info["name"]
        canonical = normalize_province_name(c_name)
        display_name = get_province_display_name(c_name)
        community = c_info.get("community", "")
        seats = int(c_info.get("seats", 0))
        census = int(c_info.get("census", 0))
        turnout_pct = float(c_info.get("turnout_pct", 0.0))

        c_res = sim_result.constituency_results.get(c_name)
        seats_map: Dict[str, int] = dict(c_res.seats) if c_res else {}
        # Obtener votos y porcentajes directos de la simulación
        votes_map: Dict[str, float] = dict(c_info.get("parties_votes") or c_info.get("raw_parties_votes") or (getattr(c_res, "votes", None) or {}))
        pct_map: Dict[str, float] = dict(c_info.get("parties_pct") or {})

        # Determinar partido ganador en la simulación activa (más escaños; en empate, más votos)
        if seats_map and max(seats_map.values(), default=0) > 0:
            winner = max(seats_map.keys(), key=lambda p: (seats_map.get(p, 0), votes_map.get(p, 0.0)))
            winner_seats = seats_map.get(winner, 0)
        elif votes_map:
            winner = max(votes_map.keys(), key=lambda p: votes_map.get(p, 0.0))
            winner_seats = seats_map.get(winner, 0)
        else:
            winner = "Otros"
            winner_seats = 0

        # Porcentaje de voto real del ganador en la circunscripción
        total_valid = float(c_info.get("valid_votes") or getattr(c_res, "valid_votes", 0.0) or (sum(votes_map.values()) if votes_map else 1.0))
        winner_votes = votes_map.get(winner, 0.0)
        if total_valid > 0 and winner_votes > 0:
            winner_pct = (winner_votes / total_valid * 100.0)
        elif winner in pct_map:
            winner_pct = float(pct_map[winner])
        else:
            winner_pct = 0.0

        # Datos del último escaño y más cercano
        last_seat_winner = getattr(c_res, "last_seat_winner", None)
        runner_up = getattr(c_res, "runner_up_party", None)
        runner_deficit = getattr(c_res, "votes_needed_for_next_seat", {}).get(runner_up, 0.0) if runner_up else 0.0

        # Formatear reparto de escaños como texto (usando punto medio Unicode en vez de entidades HTML)
        sorted_seats = sorted([(p, s) for p, s in seats_map.items() if s > 0], key=lambda x: -x[1])
        seats_text_list = [f"<b>{p}</b>: {s}" for p, s in sorted_seats]
        seats_breakdown_str = " • ".join(seats_text_list) if seats_text_list else "Sin asignación"

        # Comparativa con el otro escenario (si se provee)
        coalition_diff = 0
        transfer_text = "Sin comparativa"
        transfer_category = "neutral"
        comp_seats_map: Dict[str, int] = {}
        comp_votes_map: Dict[str, float] = {}

        if comparison_result:
            comp_c_res = comparison_result.constituency_results.get(c_name)
            comp_c_info = comp_info_by_name.get(c_name)
            if comp_c_res:
                comp_seats_map = dict(comp_c_res.seats)
            if comp_c_info:
                comp_votes_map = dict(comp_c_info.get("parties_votes") or comp_c_info.get("raw_parties_votes") or (getattr(comp_c_res, "votes", None) or {}))
            elif comp_c_res:
                comp_votes_map = dict(getattr(comp_c_res, "votes", {}))

            # Definir escaños con coalición y por separado
            if is_active_separated:
                # El activo es SEPARADO y el de comparación es COALICIÓN
                seats_sep = sum(seats_map.get(m, 0) for m in members) + seats_map.get(coalition_name, 0)
                seats_coal = sum(comp_seats_map.get(m, 0) for m in members) + comp_seats_map.get(coalition_name, 0)
                diff_coal_vs_sep = seats_coal - seats_sep
            else:
                # El activo es COALICIÓN y el de comparación es SEPARADO
                seats_coal = sum(seats_map.get(m, 0) for m in members) + seats_map.get(coalition_name, 0)
                seats_sep = sum(comp_seats_map.get(m, 0) for m in members) + comp_seats_map.get(coalition_name, 0)
                diff_coal_vs_sep = seats_coal - seats_sep

                coalition_diff = diff_coal_vs_sep

                if diff_coal_vs_sep > 0:
                    transfer_category = "gain"
                    # Buscar qué rival pierde
                    lost_rivals = []
                    sep_dict = seats_map if is_active_separated else comp_seats_map
                    coal_dict = comp_seats_map if is_active_separated else seats_map
                    for p, s_sep_val in sep_dict.items():
                        if p not in members and p != coalition_name:
                            s_coal_val = coal_dict.get(p, 0)
                            if s_coal_val < s_sep_val:
                                lost_rivals.append(f"{p} (-{s_sep_val - s_coal_val})")
                    rival_str = f"arrebatado a {', '.join(lost_rivals)}" if lost_rivals else ""
                    transfer_text = f"🟣 +{diff_coal_vs_sep} escaño con Coalición ({rival_str})"
                elif diff_coal_vs_sep < 0:
                    transfer_category = "loss"
                    gain_rivals = []
                    sep_dict = seats_map if is_active_separated else comp_seats_map
                    coal_dict = comp_seats_map if is_active_separated else seats_map
                    for p, s_sep_val in sep_dict.items():
                        if p not in members and p != coalition_name:
                            s_coal_val = coal_dict.get(p, 0)
                            if s_coal_val > s_sep_val:
                                gain_rivals.append(f"{p} (+{s_coal_val - s_sep_val})")
                    rival_str = f"cedido a {', '.join(gain_rivals)}" if gain_rivals else ""
                    transfer_text = f"🟠 {diff_coal_vs_sep} escaño por fuga ({rival_str})"
                else:
                    transfer_category = "neutral"
                    transfer_text = "⚪ Sin traspaso de escaños (0)"

        # Construir tooltip interactivo enriquecido en HTML limpio
        scen_label = "Candidaturas Separadas" if is_active_separated else f"Coalición ({coalition_name})"
        tooltip_lines = [
            f"<b style='font-size: 15px; color: #111;'>{display_name}</b> ({community})",
            f"<b>Modo proyectado:</b> {scen_label}",
            f"<b>Diputados en juego:</b> {seats} escaños",
            f"<b>1ª Fuerza:</b> <span style='color: {get_party_color(winner)}; font-weight: bold;'>{winner}</span> ({winner_seats} dip., {winner_pct:.1f}%)",
            f"<b>Reparto:</b> {seats_breakdown_str}",
            f"<b>Censo:</b> {census:,.0f} | <b>Participación:</b> {turnout_pct:.1f}%",
        ]
        if last_seat_winner:
            tooltip_lines.append(f"<b>Último escaño:</b> {last_seat_winner}")
            if runner_up and runner_deficit > 0:
                tooltip_lines.append(f"<b>A las puertas:</b> {runner_up} (le faltaron ~{runner_deficit:,.0f} votos)")

        if comparison_result:
            tooltip_lines.append(f"<b>Comparativa Coalición:</b> {transfer_text}")

        tooltip_html = "<br>".join(tooltip_lines)

        rows.append({
            "province": canonical,
            "display_name": display_name,
            "community": community,
            "seats": seats,
            "census": census,
            "turnout_pct": turnout_pct,
            "winner": winner,
            "winner_seats": winner_seats,
            "winner_pct": winner_pct,
            "winner_color": get_party_color(winner),
            "seats_map": seats_map,
            "votes_map": votes_map,
            "comp_seats_map": comp_seats_map,
            "comp_votes_map": comp_votes_map,
            "valid_votes": total_valid,
            "last_seat_winner": last_seat_winner,
            "runner_up": runner_up,
            "runner_deficit": runner_deficit,
            "coalition_diff": coalition_diff,
            "transfer_category": transfer_category,
            "transfer_text": transfer_text,
            "hover_text": tooltip_html,
        })

    return pd.DataFrame(rows)


def create_spain_electoral_map(
    df_data: pd.DataFrame,
    view_mode: str = "winner",
    selected_party: Optional[str] = None,
    highlight_province: Optional[str] = None,
    use_inset: bool = True,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> go.Figure:
    """
    Genera la figura interactiva de Plotly con el mapa coroplético de España.

    Modos disponibles (view_mode):
    - 'winner': Colorea por partido ganador (PP, PSOE, Vox, Sumar, Bildu, etc.).
    - 'coalition_impact': Colorea según ganancia (+), neutral (=) o pérdida (-) de escaños de la coalición.
    - 'party_pct': Intensidad de voto (%) del partido especificado en selected_party.
    - 'party_seats': Número de escaños del partido especificado en selected_party.
    - 'seats_total': Número total de escaños que reparte la circunscripción (1 a 38).
    - 'single_province': Resalta una única circunscripción (para Pestaña 2) y deja el resto en gris suave.
    """
    geojson = load_spain_geojson(use_inset=use_inset)
    fig = go.Figure()

    if view_mode == "single_province" or highlight_province:
        target_norm = normalize_province_name(highlight_province or df_data.iloc[0]["province"])
        df_target = df_data[df_data["province"] == target_norm]
        df_others = df_data[df_data["province"] != target_norm]

        if not df_others.empty:
            fig.add_trace(go.Choropleth(
                geojson=geojson,
                locations=df_others["province"],
                z=[0] * len(df_others),
                colorscale=[[0, "#E2E8F0"], [1, "#E2E8F0"]],
                showscale=False,
                featureidkey="id",
                marker_line_color="#94A3B8",
                marker_line_width=0.8,
                hoverinfo="text",
                text=df_others["hover_text"],
                name="Otras provincias",
            ))

        if not df_target.empty:
            target_winner = df_target.iloc[0]["winner"]
            target_color = get_party_color(target_winner)
            fig.add_trace(go.Choropleth(
                geojson=geojson,
                locations=df_target["province"],
                z=[1] * len(df_target),
                colorscale=[[0, target_color], [1, target_color]],
                showscale=False,
                featureidkey="id",
                marker_line_color="#000000",
                marker_line_width=3.0,
                hoverinfo="text",
                text=df_target["hover_text"],
                name=f"{df_target.iloc[0]['display_name']} (Seleccionada)",
            ))

    elif view_mode == "winner":
        unique_winners = [p for p in df_data["winner"].value_counts().index if p in df_data["winner"].unique()]
        n_winners = len(unique_winners)
        if n_winners == 0:
            unique_winners = ["Otros"]
            n_winners = 1

        cscale = []
        for i, party in enumerate(unique_winners):
            c = get_party_color(party)
            cscale.extend([[i / n_winners, c], [(i + 1) / n_winners, c]])

        z_indices = [unique_winners.index(w) + 0.5 for w in df_data["winner"]]

        fig.add_trace(go.Choropleth(
            geojson=geojson,
            locations=df_data["province"],
            z=z_indices,
            zmin=0,
            zmax=n_winners,
            colorscale=cscale,
            showscale=False,
            featureidkey="id",
            marker_line_color="#FFFFFF",
            marker_line_width=1.2,
            hoverinfo="text",
            text=df_data["hover_text"],
            showlegend=False,
            name="Provincias",
        ))

        for party in unique_winners:
            n_provs = int((df_data["winner"] == party).sum())
            color = get_party_color(party)
            fig.add_trace(go.Scattergeo(
                lon=[None],
                lat=[None],
                mode="markers",
                marker=dict(size=10, color=color, symbol="square"),
                name=f"{party} ({n_provs} prov.)",
                showlegend=True,
            ))

    elif view_mode == "coalition_impact":
        categories = [
            ("gain", "🟣 Suma escaño con Coalición (+)", "#7B1FA2"),
            ("neutral", "⚪ Sin cambios en el reparto (0)", "#CBD5E1"),
            ("loss", "🟠 Pierde escaño por fuga (-)", "#E65100"),
        ]
        cat_map = {k: idx for idx, (k, _, _) in enumerate(categories)}
        cscale = []
        for idx, (_, _, color) in enumerate(categories):
            cscale.extend([[idx / 3.0, color], [(idx + 1) / 3.0, color]])

        z_cats = [cat_map.get(cat, 1) + 0.5 for cat in df_data["transfer_category"]]

        fig.add_trace(go.Choropleth(
            geojson=geojson,
            locations=df_data["province"],
            z=z_cats,
            zmin=0,
            zmax=3,
            colorscale=cscale,
            showscale=False,
            featureidkey="id",
            marker_line_color="#94A3B8",
            marker_line_width=1.0,
            hoverinfo="text",
            text=df_data["hover_text"],
            showlegend=False,
            name="Transferencias",
        ))

        for cat_key, cat_label, cat_color in categories:
            n_count = int((df_data["transfer_category"] == cat_key).sum())
            if n_count > 0:
                fig.add_trace(go.Scattergeo(
                    lon=[None],
                    lat=[None],
                    mode="markers",
                    marker=dict(size=10, color=cat_color, symbol="square"),
                    name=f"{cat_label} ({n_count})",
                    showlegend=True,
                ))

    elif view_mode == "party_pct" and selected_party:
        party_pcts = []
        for _, row in df_data.iterrows():
            v_map = row["votes_map"]
            tot = sum(v_map.values()) if v_map else 0
            p_v = v_map.get(selected_party, 0)
            pct = (p_v / tot * 100.0) if tot > 0 else 0.0
            party_pcts.append(pct)

        df_copy = df_data.copy()
        df_copy["party_pct_val"] = party_pcts

        base_color = get_party_color(selected_party)
        fig.add_trace(go.Choropleth(
            geojson=geojson,
            locations=df_copy["province"],
            z=df_copy["party_pct_val"],
            colorscale=[[0.0, "#F8FAFC"], [1.0, base_color]],
            showscale=True,
            featureidkey="id",
            marker_line_color="#64748B",
            marker_line_width=0.8,
            colorbar=dict(
                title=dict(text=f"<b>% {selected_party}</b>", font=dict(color="#000000", size=12)),
                tickfont=dict(color="#000000", size=10),
                thickness=14,
                len=0.7,
                x=0.98,
            ),
            hoverinfo="text",
            text=[
                f"{h}<br><b>Porcentaje {selected_party}:</b> {val:.2f}%"
                for h, val in zip(df_copy["hover_text"], party_pcts)
            ],
            name=f"% {selected_party}",
        ))

    elif view_mode == "party_seats" and selected_party:
        party_s_list = [row["seats_map"].get(selected_party, 0) for _, row in df_data.iterrows()]
        df_copy = df_data.copy()
        df_copy["party_s_val"] = party_s_list
        base_color = get_party_color(selected_party)

        fig.add_trace(go.Choropleth(
            geojson=geojson,
            locations=df_copy["province"],
            z=df_copy["party_s_val"],
            colorscale=[[0.0, "#F8FAFC"], [1.0, base_color]],
            showscale=True,
            featureidkey="id",
            marker_line_color="#64748B",
            marker_line_width=0.8,
            colorbar=dict(
                title=dict(text=f"<b>Dip. {selected_party}</b>", font=dict(color="#000000", size=12)),
                tickfont=dict(color="#000000", size=10),
                thickness=14,
                len=0.7,
                x=0.98,
            ),
            hoverinfo="text",
            text=[
                f"{h}<br><b>Diputados {selected_party}:</b> {val} escaños"
                for h, val in zip(df_copy["hover_text"], party_s_list)
            ],
            name=f"Escaños {selected_party}",
        ))

    elif view_mode == "seats_total":
        fig.add_trace(go.Choropleth(
            geojson=geojson,
            locations=df_data["province"],
            z=df_data["seats"],
            colorscale="Purples",
            showscale=True,
            featureidkey="id",
            marker_line_color="#475569",
            marker_line_width=0.8,
            colorbar=dict(
                title=dict(text="<b>Escaños</b>", font=dict(color="#000000", size=12)),
                tickfont=dict(color="#000000", size=10),
                thickness=14,
                len=0.7,
                x=0.98,
            ),
            hoverinfo="text",
            text=df_data["hover_text"],
            name="Escaños asignados",
        ))

    # Ajuste del mapa y proyección geográfica
    fig.update_geos(
        fitbounds="locations",
        visible=False,
        projection_type="mercator",
        showcountries=False,
        showcoastlines=False,
        showland=False,
        bgcolor="#FFFFFF",
    )

    map_title = title or "<b>Mapa Electoral de España — 52 Circunscripciones</b>"
    map_subtitle = subtitle or "Haz clic o pasa el cursor sobre cualquier provincia para ver sus detalles"

    fig.update_layout(
        title=dict(
            text=f"{map_title}<br><sup>{map_subtitle}</sup>",
            font=dict(color="#000000", size=15, family="sans-serif"),
            x=0.02,
            y=0.97,
        ),
        font=dict(color="#000000", family="sans-serif", size=11),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        margin=dict(l=10, r=10, t=65, b=25),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.08,
            xanchor="center",
            x=0.5,
            font=dict(color="#000000", size=11),
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="#E2E8F0",
            borderwidth=1,
        ),
    )

    # Recuadro oficial para Canarias trazado directamente en coordenadas geográficas
    if use_inset:
        # En la cartografía inset, el archipiélago canario está ubicado en lon [-13.60, -8.77], lat [33.82, 35.60]
        # El marco geográfico delimita con exactitud las islas canarias en el mapa
        box_lons = [-13.95, -8.45, -8.45, -13.95, -13.95]
        box_lats = [33.50, 33.50, 35.95, 35.95, 33.50]
        fig.add_trace(go.Scattergeo(
            lon=box_lons,
            lat=box_lats,
            mode="lines",
            line=dict(color="#64748B", width=1.5, dash="dot"),
            hoverinfo="none",
            showlegend=False,
            name="Recuadro Canarias",
        ))
        fig.add_trace(go.Scattergeo(
            lon=[-11.20],
            lat=[35.75],
            mode="text",
            text=["<b>Canarias (recuadro)</b>"],
            textfont=dict(color="#475569", size=10, family="sans-serif"),
            hoverinfo="none",
            showlegend=False,
            name="Etiqueta Canarias",
        ))

    return fig


def render_electoral_map_section(
    sim_result: NationalSimulationResult,
    comparison_result: Optional[NationalSimulationResult] = None,
    section_key: str = "s1",
    coalition_name: str = "Lista Única",
    coalition_members: Optional[List[str]] = None,
    poll_name: str = "",
    poll_date: str = "",
    allow_coalition_mode: bool = True,
    highlight_province: Optional[str] = None,
    is_single_province_mode: bool = False,
    default_scenario: str = "coalition",
):
    """
    Componente visual interactivo para Streamlit que renderiza el mapa electoral de España
    con controles de visualización, conmutador entre lista única y candidaturas por separado,
    tarjetas de balance territorial y ficha de auditoría local.
    """
    if st is None:
        return

    members = list(coalition_members or ["Sumar", "Podemos"])

    # Modo circunscripción individual (Pestaña 2)
    if is_single_province_mode:
        df_map = build_constituency_electoral_summary(
            sim_result=sim_result,
            comparison_result=comparison_result,
            coalition_name=coalition_name,
            coalition_members=members,
            is_active_separated=False,
        )
        target_name = highlight_province or df_map.iloc[0]["province"]
        target_row = df_map[df_map["province"] == normalize_province_name(target_name)]
        if target_row.empty:
            target_row = df_map.iloc[0]
        else:
            target_row = target_row.iloc[0]

        st.subheader("🗺️ Ubicación Territorial de la Circunscripción en España")
        st.caption(
            f"La circunscripción de **{target_row['display_name']}** reparte **{target_row['seats']} escaños** "
            f"({target_row['seats']/350*100:.1f}% de la cámara). Pasa el cursor sobre el mapa para explorar el resto de distritos."
        )

        fig_mini = create_spain_electoral_map(
            df_data=df_map,
            view_mode="single_province",
            highlight_province=target_name,
            title=f"<b>{target_row['display_name']} en el Mapa de España</b> ({target_row['seats']} escaños)",
            subtitle=f"1ª Fuerza proyectada: {target_row['winner']} ({target_row['winner_seats']} dip.)",
            use_inset=True,
        )
        st.plotly_chart(fig_mini, use_container_width=True)
        return

    # Modo Nacional (Pestañas 1 y 3)
    st.subheader("🗺️ Mapa Electoral Interactivo de España (52 Circunscripciones)")
    st.markdown(
        """
        Explora la geografía política del Congreso: identifica la **fuerza ganadora en cada provincia**, 
        compara el resultado con **candidaturas por separado frente a la lista única**, analiza las 
        **transferencias de escaños** provincia a provincia y consulta la implantación de cualquier partido.
        """
    )

    # 1. Selector principal de escenario (Separados vs Coalición)
    is_active_separated = False
    active_sim = sim_result
    other_sim = comparison_result

    if comparison_result is not None and allow_coalition_mode:
        st.markdown("##### 🔀 Escenario de Candidaturas en el Mapa:")
        sc_col1, sc_col2 = st.columns([1.6, 1.4])
        with sc_col1:
            radio_opts = [
                f"🟣 Con {coalition_name} (Lista Única)",
                f"🔵 Con Candidaturas por Separado ({', '.join(members)})",
            ]
            default_idx = 1 if default_scenario == "separated" else 0
            selected_scenario = st.radio(
                "Seleccionar escenario a proyectar en las provincias:",
                radio_opts,
                index=default_idx,
                horizontal=True,
                key=f"{section_key}_map_scenario_choice",
                help="Alterna el mapa para ver qué partidos ganan cada provincia con lista única frente a acudir divididos.",
            )
            is_active_separated = ("Separado" in selected_scenario)

        with sc_col2:
            st.info(
                f"**Escenario activo en el mapa:** {'🔵 Partidos por separado' if is_active_separated else f'🟣 {coalition_name}'}."
                f" {'Los integrantes compiten por libre.' if is_active_separated else 'Los votos se concentran bajo la lista común.'}"
            )

        if is_active_separated:
            active_sim = comparison_result
            other_sim = sim_result
        else:
            active_sim = sim_result
            other_sim = comparison_result

    df_map = build_constituency_electoral_summary(
        sim_result=active_sim,
        comparison_result=other_sim,
        coalition_name=coalition_name,
        coalition_members=members,
        is_active_separated=is_active_separated,
    )

    # 2. Controles de capa de visualización
    mode_options = ["🏆 Fuerza Ganadora por Circunscripción"]
    if comparison_result is not None and allow_coalition_mode:
        mode_options.append("⚖️ Impacto Territorial y Transferencias (Separados vs. Coalición)")
    mode_options.extend([
        "📊 Porcentaje de Voto (%) por Partido",
        "🏛️ Escaños Obtenidos por Partido",
        "📏 Magnitud de Distrito (Escaños en juego)",
    ])

    c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.4, 1.2, 1.1])
    with c_ctrl1:
        selected_mode_label = st.selectbox(
            "Capa de visualización del mapa:",
            mode_options,
            key=f"{section_key}_map_mode_select",
        )

    # Identificar partidos con presencia en el escenario activo
    all_parties = set()
    for row_seats in df_map["seats_map"]:
        all_parties.update(k for k, v in row_seats.items() if v > 0)
    for row_votes in df_map["votes_map"]:
        all_parties.update(k for k, v in row_votes.items() if v > 0)

    std_party_prio = ["PP", "PSOE", "Vox", coalition_name] + members + ["SALF", "ERC", "Junts", "EH Bildu", "PNV", "BNG", "CC", "UPN", "Adelante Andalucía"]
    party_choices = [p for p in std_party_prio if p in all_parties]
    for p in sorted(all_parties):
        if p not in party_choices:
            party_choices.append(p)

    selected_party = None
    with c_ctrl2:
        if "Partido" in selected_mode_label:
            selected_party = st.selectbox(
                "Seleccionar formación política:",
                party_choices,
                index=0,
                key=f"{section_key}_map_party_select",
            )
        else:
            st.empty()

    with c_ctrl3:
        use_inset = st.checkbox(
            "Recuadro oficial Canarias",
            value=True,
            help="Enmarca a las Islas Canarias en un recuadro oficial situado en la esquina inferior izquierda (estándar RTVE/INE).",
            key=f"{section_key}_map_inset_chk",
        )

    # Mapeo de modo de visualización
    if "Fuerza Ganadora" in selected_mode_label:
        v_mode = "winner"
        mode_title = f"Fuerza Ganadora por Circunscripción ({'Separados' if is_active_separated else coalition_name})"
    elif "Transferencias" in selected_mode_label:
        v_mode = "coalition_impact"
        mode_title = f"Impacto Territorial de la Coalición ({coalition_name})"
    elif "Porcentaje" in selected_mode_label:
        v_mode = "party_pct"
        mode_title = f"Porcentaje de Voto de {selected_party} (%)"
    elif "Escaños Obtenidos" in selected_mode_label:
        v_mode = "party_seats"
        mode_title = f"Escaños Obtenidos por {selected_party}"
    else:
        v_mode = "seats_total"
        mode_title = "Magnitud de Distrito (Escaños Asignados)"

    # Tarjetas métricas de balance territorial
    if v_mode == "winner":
        winner_counts = df_map["winner"].value_counts()
        scen_tag = "por separado" if is_active_separated else f"con {coalition_name}"
        st.markdown(f"##### 🏛️ Provincias Vencedoras ({scen_tag}):")
        cols_w = st.columns(min(len(winner_counts), 6))
        for idx, (p_win, count_prov) in enumerate(winner_counts.items()):
            c_target = cols_w[idx % len(cols_w)]
            tot_s = sum(r["seats_map"].get(p_win, 0) for _, r in df_map.iterrows())
            with c_target.container(border=True):
                st.metric(
                    label=p_win,
                    value=f"{count_prov} prov.",
                    delta=f"{tot_s} dip. totales",
                    delta_color="off",
                )
    elif v_mode == "coalition_impact":
        n_gain = len(df_map[df_map["transfer_category"] == "gain"])
        n_neutral = len(df_map[df_map["transfer_category"] == "neutral"])
        n_loss = len(df_map[df_map["transfer_category"] == "loss"])
        g_provs = ", ".join(df_map[df_map["transfer_category"] == "gain"]["display_name"].tolist())
        l_provs = ", ".join(df_map[df_map["transfer_category"] == "loss"]["display_name"].tolist())

        st.markdown("##### ⚖️ Balance Territorial de la Confluencia frente a la División:")
        cm1, cm2, cm3 = st.columns(3)
        with cm1:
            st.metric(
                label="🟣 Provincias donde Gana escaño (+)",
                value=f"{n_gain} provincias",
                delta=f"+{n_gain} escaños" if n_gain > 0 else "0",
                help=f"Distritos donde la concentración de restos superó el corte D'Hondt: {g_provs or 'Ninguna'}"
            )
        with cm2:
            st.metric(
                label="⚪ Provincias Sin Variación (0)",
                value=f"{n_neutral} provincias",
                help="Distritos donde el reparto de escaños no se altera."
            )
        with cm3:
            st.metric(
                label="🟠 Provincias donde Cede escaño (-)",
                value=f"{n_loss} provincias",
                delta=f"-{n_loss} escaños" if n_loss > 0 else "0",
                delta_color="inverse",
                help=f"Distritos donde la desmovilización/fuga provocó pérdida de escaño: {l_provs or 'Ninguna'}"
            )

    # Generación y renderizado del mapa
    sub_text = f"Procedencia de datos: {poll_name} • Fecha de publicación: {poll_date}" if poll_name else "Pasa el cursor sobre cualquier provincia para ver su desglose completo"
    fig_map = create_spain_electoral_map(
        df_data=df_map,
        view_mode=v_mode,
        selected_party=selected_party,
        use_inset=use_inset,
        title=f"<b>España: {mode_title}</b>",
        subtitle=sub_text,
    )
    st.plotly_chart(fig_map, use_container_width=True)

    # Inspector interactivo de circunscripción
    with st.expander("🔍 **Auditoría y Ficha Electoral Detallada por Circunscripción**", expanded=False):
        st.markdown("Selecciona cualquier provincia para auditar su censo, participación, reparto D'Hondt y último escaño asignado:")
        insp_prov = st.selectbox(
            "Seleccionar circunscripción para auditar:",
            df_map["province"].tolist(),
            format_func=get_province_display_name,
            key=f"{section_key}_map_inspect_select",
        )
        row_insp = df_map[df_map["province"] == insp_prov].iloc[0]

        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        with fc1:
            st.metric("Diputados en juego", f"{row_insp['seats']} escaños")
        with fc2:
            st.metric("Censo Electoral", f"{row_insp['census']:,.0f}")
        with fc3:
            st.metric("Participación", f"{row_insp['turnout_pct']:.1f}%")
        with fc4:
            st.metric(f"1ª Fuerza ({'Separados' if is_active_separated else 'Coalición'})", f"{row_insp['winner']} ({row_insp['winner_seats']} dip.)")
        with fc5:
            st.metric("Efecto de la Coalición", f"{row_insp['coalition_diff']:+d} dip." if row_insp['coalition_diff'] != 0 else "= 0 dip.")

        # Comparativa directa lado a lado en la provincia
        if comparison_result is not None:
            st.markdown(f"##### 📊 Comparativa de Escaños en {row_insp['display_name']} (Separados vs. En Coalición):")
            # Unir todas las formaciones con presencia en esta provincia
            all_local_p = list(row_insp["seats_map"].keys())
            for p in row_insp["comp_seats_map"].keys():
                if p not in all_local_p:
                    all_local_p.append(p)

            comp_table_rows = []
            for p in all_local_p:
                if is_active_separated:
                    s_sep = row_insp["seats_map"].get(p, 0)
                    v_sep = row_insp["votes_map"].get(p, 0.0)
                    s_coal = row_insp["comp_seats_map"].get(p, 0)
                    v_coal = row_insp["comp_votes_map"].get(p, 0.0)
                else:
                    s_coal = row_insp["seats_map"].get(p, 0)
                    v_coal = row_insp["votes_map"].get(p, 0.0)
                    s_sep = row_insp["comp_seats_map"].get(p, 0)
                    v_sep = row_insp["comp_votes_map"].get(p, 0.0)

                if s_sep == 0 and s_coal == 0 and v_sep == 0 and v_coal == 0:
                    continue

                tot_v = row_insp["valid_votes"]
                pct_active = ((v_sep if is_active_separated else v_coal) / tot_v * 100.0) if tot_v > 0 else 0.0
                diff_val = s_coal - s_sep
                diff_str = f"+{diff_val}" if diff_val > 0 else (f"{diff_val}" if diff_val < 0 else "=")

                comp_table_rows.append({
                    "Candidatura": p,
                    "Escaños: Por Separado": s_sep,
                    "Escaños: Con Coalición": s_coal,
                    "Diferencia (Coalición - Separados)": diff_str,
                    "% Voto Estimado": f"{pct_active:.2f}%",
                    "Supera Umbral 3%": "✅ Sí" if pct_active >= 3.0 else "❌ Excluido (<3%)",
                })

            comp_table_rows.sort(key=lambda x: -(max(x["Escaños: Por Separado"], x["Escaños: Con Coalición"])))
            st.dataframe(pd.DataFrame(comp_table_rows), use_container_width=True, hide_index=True)
        else:
            # Tabla pormenorizada simple si no hay comparación
            p_data = []
            for p, s in sorted(row_insp["seats_map"].items(), key=lambda x: -x[1]):
                v = row_insp["votes_map"].get(p, 0.0)
                tot_v = row_insp["valid_votes"]
                pct = (v / tot_v * 100.0) if tot_v > 0 else 0.0
                p_data.append({
                    "Candidatura": p,
                    "Votos Estimados": f"{v:,.0f}",
                    "% Voto Provincial": f"{pct:.2f}%",
                    "Escaños Asignados": s,
                    "Supera Umbral 3%": "✅ Sí" if pct >= 3.0 else "❌ Excluido (<3%)",
                })
            st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)

        if row_insp["last_seat_winner"]:
            corte_info = f"🎯 **Último escaño repartido en {row_insp['display_name']}:** Adjudicado a **{row_insp['last_seat_winner']}**."
            if row_insp["runner_up"] and row_insp["runner_deficit"] > 0:
                corte_info += f" La siguiente candidatura más cercana fue **{row_insp['runner_up']}**, que se quedó a **{row_insp['runner_deficit']:,.0f} votos** de arrebatarlo."
            st.info(corte_info)
