"""
Módulo de Internacionalización (i18n) para el Simulador Electoral D'Hondt.
Permite alternar dinámicamente entre Español (es) e Inglés (en) en la misma URL y sesión,
manteniendo todas las variables de cálculo y simulaciones activas.
"""

from typing import Dict, Any, Optional
import streamlit as st

SUPPORTED_LANGUAGES = {
    "es": "🇪🇸 Español",
    "en": "🇬🇧 English",
}

DEFAULT_LANGUAGE = "es"


def get_current_lang() -> str:
    """Devuelve el código del idioma activo ('es' o 'en')."""
    if "app_language" in st.session_state and st.session_state["app_language"] in SUPPORTED_LANGUAGES:
        return st.session_state["app_language"]
    
    # Comprobar query params de la URL (?lang=en o ?lang=es)
    try:
        if hasattr(st, "query_params") and "lang" in st.query_params:
            qp_lang = st.query_params["lang"].lower()
            if qp_lang in SUPPORTED_LANGUAGES:
                st.session_state["app_language"] = qp_lang
                return qp_lang
    except Exception:
        pass
        
    return DEFAULT_LANGUAGE


def set_lang(lang: str) -> None:
    """Fija el idioma activo en session_state y query_params."""
    if lang in SUPPORTED_LANGUAGES:
        st.session_state["app_language"] = lang
        try:
            if hasattr(st, "query_params"):
                st.query_params["lang"] = lang
        except Exception:
            pass


MESSAGES: Dict[str, Dict[str, str]] = {
    "es": {
        # App general
        "app_title": "🗳️ Simulador Electoral D'Hondt y Laboratorio de Coaliciones",
        "app_page_title": "Simulador Electoral D'Hondt - Laboratorio Político",
        "app_subtitle": "**Plataforma de modelado y simulación electoral para el Congreso de los Diputados de España (350 escaños).**  \nExamina el impacto de la concentración o división del voto bajo la Ley D'Hondt, analiza la fuga de votos partido a partido y calcula el número de votos necesarios para igualar el escenario más favorable.",
        "lang_selector_label": "🌐 Idioma / Language",
        
        # Pestañas principales
        "tab1_name": "1️⃣ Simulación Nacional Simple",
        "tab2_name": "2️⃣ Simulación de Circunscripción",
        "tab3_name": "3️⃣ Simulación Nacional Compleja (Control Total)",
        "tab4_name": "4️⃣ Auditoría, Metodología e Importación Excel",

        # Tab 1: Simulación Simple
        "tab1_header": "🏛️ 1. Simulación Nacional Simple",
        "tab1_desc": "Proyección macroestatal basada en encuestas o resultados oficiales, comparación directa de la **Lista Única de Izquierdas frente a Candidaturas Separadas** y visualización de la **gráfica escalonada D'Hondt** para cualquier provincia.",
        "config_box_title": "🎛️ Configuración de la Simulación Nacional Simple",
        "poll_select_label": "Sondeo o resultado base:",
        "pub_date": "Publicación:",
        "source": "Fuente:",
        "sample": "Muestra:",
        "coalition_members_label": "Partidos que van en coalición:",
        "coalition_members_help": "Selecciona qué fuerzas políticas se unen en lista única nacional para comparar frente al escenario de concurrir por separado.",
        "coalition_name_label": "Nombre de la coalición:",
        "coalition_name_help": "Denominación de la candidatura conjunta.",
        "turnout_label": "Participación estimada (%):",
        "turnout_help": "Porcentaje de participación estimado sobre el censo electoral nacional. Inicializado con el dato de la encuesta/resultado elegido y totalmente modificable.",
        "retention_label": "Tasa de retención de la coalición (%):",
        "retention_help": "100% = suma exacta de votos; valores inferiores simulan desafección o desmovilización electoral.",
        "threshold_label": "Umbral legal (% votos válidos):",
        "blank_label": "Voto en blanco (% estimado):",
        "poll_candidates_expander": "📋 Lista de candidaturas tomadas en este sondeo ({poll}) — Total: {count} partidos",
        "poll_candidates_intro": "Relación de todas las fuerzas políticas computadas a nivel nacional en **{poll}** y su porcentaje estimado:",
        "col_candidacy": "Candidatura",
        "col_vote_intent": "Intención de Voto Nacional (%)",
        "col_in_coalition": "En Coalición",
        "col_territory": "Ámbito Territorial Estimado",
        "yes_coalition": "🤝 Sí",
        "no_coalition": "No",
        "adjust_poll_expander": "✏️ Ver / Ajustar porcentajes nacionales del sondeo seleccionado",
        "adjust_poll_caption": "Puedes ajustar manualmente los porcentajes de **{poll}** para simular escenarios alternativos:",
        "reset_adjustments": "🔄 Restablecer a valores originales",
        "total_pct_note": "Suma total de votos de candidaturas: **{total:.2f}%**",
        "run_simulation_btn": "🚀 Ejecutar Simulación",
        "executing_sim": "Calculando reparto electoral provincia a provincia según la Ley D'Hondt...",
        "results_header": "📊 Resultados de la Simulación Nacional",
        "summary_seats_coalition": "Escaños con Lista Única",
        "summary_seats_separated": "Escaños por Separado",
        "summary_diff": "Diferencia Neta de Escaños",
        "majority_status": "Mayoría Absoluta (176 dip.)",
        "majority_achieved": "✅ Mayoría alcanzada ({seats} escaños)",
        "majority_not_achieved": "⚠️ Sin mayoría absoluta ({seats}/176)",
        "coalition_gain": "+{gain} escaños con lista unitaria",
        "coalition_loss": "{loss} escaños con lista unitaria",
        "coalition_equal": "Mismo resultado en escaños",
        "provincial_dhondt_header": "📈 Gráfica Escalonada D'Hondt por Circunscripción",
        "select_province_dhondt": "Selecciona la provincia para examinar:",
        "map_section_header": "🗺️ Mapa Electoral de España",

        # Tab 2: Simulación de Circunscripción
        "tab2_header": "🔍 2. Simulación Detallada de Circunscripción",
        "tab2_desc": "Análisis microelectoral para una única provincia: simulación del reparto de escaños mediante el algoritmo de cocientes D'Hondt, variación de votos de partidos y umbrales de exclusión.",
        "select_province_label": "Selecciona la circunscripción a analizar:",
        "prov_seats_info": "Diputados asignados: **{seats}** | Censo: **{census:,}**",
        "prov_table_header": "Tabla de Cocientes y Asignación de Escaños D'Hondt",
        
        # Tab 3: Optimizador de Gobernabilidad
        "tab3_header": "🎯 3. Optimizador de Gobernabilidad y Mayorías de Investidura",
        "tab3_desc": "Calcula el número mínimo exacto de votos adicionales necesarios para que la coalición progresista alcance la investidura (176 escaños o meta personalizada) con sus socios de gobierno.",
        "gov_section_title": "### 🏛️ Hoja de Ruta de Gobernabilidad: Votos Mínimos para la Mayoría de Investidura ({target} Escaños)",
        "gov_section_desc": "Calcula con rigor matemático cuántos votos adicionales necesitarían las candidaturas de izquierda (en confluencia o por separado) y en qué circunscripciones estratégicas y de qué caladeros (abstención o partidos donantes) para alcanzar la mayoría de investidura ({target} escaños) junto a sus socios de gobierno.",
        "gov_pact_partners_title": "##### 🤝 Socios del Pacto de Gobierno / Investidura:",
        "gov_target_title": "##### 🎯 Objetivo Parlamentario:",
        "opt_config_title": "⚙️ Parámetros de la Optimización de Investidura",
        "target_seats_label": "Objetivo de escaños para la mayoría:",
        "partners_label": "Socios parlamentarios de investidura:",
        "optimizable_partners_label": "Socios adicionales autorizados a sumar escaños:",
        "shield_partners_label": "🛡️ Blindaje estricto de socios (evitar que pierdan escaños)",
        "max_turnout_inc_label": "Incremento máximo de participación (puntos %):",
        "opt_criterion_label": "Criterio de optimización y asignación:",
        "opt_crit_abs": "Mínimo de votos brutos absolutos (ΔV)",
        "opt_crit_prov": "Mínimo salto en puntos % del censo provincial (Δ% prov)",
        "opt_crit_growth": "Mínimo porcentaje de crecimiento del propio partido (Δ% partido)",
        "opt_crit_hybrid": "Criterio Híbrido Ponderado (Cobb-Douglas)",
        "run_optimizer_btn": "🎯 Calcular Hoja de Ruta Óptima",
        "opt_results_header": "🗺️ Hoja de Ruta Óptima de Campaña",
        "total_votes_needed_label": "Votos adicionales necesarios a nivel nacional:",
        "seats_gained_label": "Escaños adicionales ganados:",
        "recalibration_notice": "💡 Recalibración provincial aplicada: reparto simultáneo de cierre D'Hondt garantizado sin pérdidas para el bloque.",

        # Tab 4: Auditoría y Excel
        "tab4_header": "📋 4. Auditoría, Metodología e Importación Excel",
        "tab4_desc": "Bases de datos consolidadas del modelo electoral (LOREG, INE y RD 806/2026), descarga en Excel (.xlsx) y carga de encuestas externas.",
        "download_excel_btn": "📥 Descargar Modelo Electoral Completo en Excel (.xlsx)",
        "upload_poll_label": "📤 Cargar encuesta personalizada desde archivo Excel (.xlsx):",
        "audit_censo_tab": "Censo y Escaños 2026",
        "audit_pct_tab": "Porcentajes 23J",
        "audit_seats_tab": "Escaños 23J",
        "audit_polls_tab": "Catálogo de Sondeos",

        # Términos comunes
        "votes": "Votos",
        "seats": "Escaños",
        "turnout": "Participación",
        "census": "Censo",
        "valid_votes": "Votos válidos",
        "blank_votes": "Votos en blanco",
        "abstention": "Abstención",
        "majority": "Mayoría",
        "diff": "Diferencia",
        "cost": "Coste",
        "rival": "Rival",
        "province": "Provincia",
        "party": "Partido",
        "source_transfers": "Trasvases",
        "source_abstention": "Abstención",
    },
    "en": {
        # App general
        "app_title": "🗳️ D'Hondt Electoral Simulator & Coalition Lab",
        "app_page_title": "D'Hondt Electoral Simulator - Political Lab",
        "app_subtitle": "**Electoral modeling and simulation platform for Spain's Congress of Deputies (350 seats).**  \nExamine the impact of vote concentration or division under the D'Hondt Law, analyze seat leaks across parties, and compute the exact minimum votes required to secure target majorities.",
        "lang_selector_label": "🌐 Language / Idioma",

        # Main tabs
        "tab1_name": "1️⃣ Simple National Simulation",
        "tab2_name": "2️⃣ Single Constituency Simulation",
        "tab3_name": "3️⃣ Complex National Simulation (Full Control)",
        "tab4_name": "4️⃣ Audit, Methodology & Excel Import",

        # Tab 1: Simple Simulation
        "tab1_header": "🏛️ 1. Simple National Simulation",
        "tab1_desc": "National projection based on benchmark polls or official results, direct comparison of the **Left Single List vs. Separate Candidacies**, and visualization of the **D'Hondt stepped quotient chart** for any province.",
        "config_box_title": "🎛️ Simple National Simulation Settings",
        "poll_select_label": "Benchmark poll or baseline election:",
        "pub_date": "Published:",
        "source": "Source:",
        "sample": "Sample size:",
        "coalition_members_label": "Parties running in coalition:",
        "coalition_members_help": "Select which political forces unite in a single national joint ticket to compare against running separately.",
        "coalition_name_label": "Coalition name:",
        "coalition_name_help": "Name of the joint electoral list.",
        "turnout_label": "Estimated turnout (%):",
        "turnout_help": "Estimated voter turnout over the national electoral census. Initialized with the benchmark poll/election figure and fully customizable.",
        "retention_label": "Coalition vote retention rate (%):",
        "retention_help": "100% = exact sum of member votes; lower values simulate electoral fatigue or demobilization.",
        "threshold_label": "Legal threshold (% valid votes):",
        "blank_label": "Blank votes (% estimated):",
        "poll_candidates_expander": "📋 Parties included in this poll ({poll}) — Total: {count} parties",
        "poll_candidates_intro": "List of all political forces computed nationally in **{poll}** and their estimated vote share:",
        "col_candidacy": "Candidacy",
        "col_vote_intent": "National Vote Intent (%)",
        "col_in_coalition": "In Coalition",
        "col_territory": "Estimated Territorial Scope",
        "yes_coalition": "🤝 Yes",
        "no_coalition": "No",
        "adjust_poll_expander": "✏️ View / Adjust national percentages for selected poll",
        "adjust_poll_caption": "You can manually adjust percentages of **{poll}** to simulate alternative scenarios:",
        "reset_adjustments": "🔄 Reset to original poll values",
        "total_pct_note": "Total vote share of candidacies: **{total:.2f}%**",
        "run_simulation_btn": "🚀 Run Simulation",
        "executing_sim": "Computing constituency-by-constituency allocation under D'Hondt Law...",
        "results_header": "📊 National Simulation Results",
        "summary_seats_coalition": "Seats with Single List",
        "summary_seats_separated": "Seats Running Separately",
        "summary_diff": "Net Seat Difference",
        "majority_status": "Absolute Majority (176 seats)",
        "majority_achieved": "✅ Majority achieved ({seats} seats)",
        "majority_not_achieved": "⚠️ No absolute majority ({seats}/176)",
        "coalition_gain": "+{gain} seats with joint ticket",
        "coalition_loss": "{loss} seats with joint ticket",
        "coalition_equal": "Identical seat distribution",
        "provincial_dhondt_header": "📈 Provincial D'Hondt Stepped Quotient Chart",
        "select_province_dhondt": "Select province to inspect:",
        "map_section_header": "🗺️ Spain Electoral Map",

        # Tab 2: Single Constituency
        "tab2_header": "🔍 2. Detailed Single Constituency Simulation",
        "tab2_desc": "Micro-electoral analysis for a single province: seat distribution simulation using D'Hondt quotient table, party vote variation, and threshold filtering.",
        "select_province_label": "Select constituency to analyze:",
        "prov_seats_info": "Allocated seats: **{seats}** | Census: **{census:,}**",
        "prov_table_header": "D'Hondt Quotients and Seat Allocation Table",

        # Tab 3: Government Optimizer
        "tab3_header": "🎯 3. Government Formation & Majority Optimizer",
        "tab3_desc": "Calculates the exact minimum additional votes needed for the governing bloc to reach an investiture majority (176 seats or custom target) alongside parliamentary partners.",
        "gov_section_title": "### 🏛️ Government Formation Roadmap: Minimum Votes for Investiture Majority ({target} Seats)",
        "gov_section_desc": "Calculates with mathematical precision how many additional votes progressive forces would need (jointly or separately), identifying strategic constituencies and vote sources (turnout mobilization or rival transfers) to secure an investiture majority ({target} seats) alongside coalition allies.",
        "gov_pact_partners_title": "##### 🤝 Investiture / Government Coalition Partners:",
        "gov_target_title": "##### 🎯 Parliamentary Seat Target:",
        "opt_config_title": "⚙️ Investiture Optimization Settings",
        "target_seats_label": "Seat target for majority:",
        "partners_label": "Investiture parliamentary partners:",
        "optimizable_partners_label": "Additional partners authorized to gain seats:",
        "shield_partners_label": "🛡️ Strict partner shield (prevent allies from losing baseline seats)",
        "max_turnout_inc_label": "Maximum turnout increase (percentage points):",
        "opt_criterion_label": "Optimization and efficiency criterion:",
        "opt_crit_abs": "Minimum absolute votes (ΔV)",
        "opt_crit_prov": "Minimum shift in provincial census points (Δ% prov)",
        "opt_crit_growth": "Minimum party growth rate (Δ% party)",
        "opt_crit_hybrid": "Weighted Hybrid Criterion (Cobb-Douglas)",
        "run_optimizer_btn": "🎯 Calculate Optimal Campaign Roadmap",
        "opt_results_header": "🗺️ Optimal Campaign Roadmap",
        "total_votes_needed_label": "Total additional votes needed nationally:",
        "seats_gained_label": "Additional seats gained:",
        "recalibration_notice": "💡 Provincial closure recalibration applied: simultaneous D'Hondt allocation certified with zero bloc seat erosion.",

        # Tab 4: Audit & Excel
        "tab4_header": "📋 4. Audit, Methodology & Excel Import",
        "tab4_desc": "Consolidated electoral databases (LOREG, INE, and Royal Decree 806/2026), Excel (.xlsx) export, and external poll file upload.",
        "download_excel_btn": "📥 Download Complete Electoral Model in Excel (.xlsx)",
        "upload_poll_label": "📤 Upload custom poll from Excel file (.xlsx):",
        "audit_censo_tab": "Census & Seats 2026",
        "audit_pct_tab": "23J Vote Percentages",
        "audit_seats_tab": "23J Seats Won",
        "audit_polls_tab": "Integrated Polls Catalog",

        # Common terms
        "votes": "Votes",
        "seats": "Seats",
        "turnout": "Turnout",
        "census": "Census",
        "valid_votes": "Valid votes",
        "blank_votes": "Blank votes",
        "abstention": "Abstention",
        "majority": "Majority",
        "diff": "Difference",
        "cost": "Cost",
        "rival": "Rival",
        "province": "Province",
        "party": "Party",
        "source_transfers": "Transfers",
        "source_abstention": "Abstention",
    }
}


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """
    Traduce una clave al idioma activo con soporte de formateo de variables.
    Si la clave no existe en el idioma activo, recurre al español o al valor por defecto.
    """
    lang = get_current_lang()
    lang_dict = MESSAGES.get(lang, MESSAGES[DEFAULT_LANGUAGE])
    text = lang_dict.get(key)
    
    if text is None:
        text = MESSAGES[DEFAULT_LANGUAGE].get(key, default if default is not None else key)
        
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
            
    return text
