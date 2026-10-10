"""
Generador de la gráfica escalonada descendente para la Ley D'Hondt con Plotly.
Eje Y: Cocientes / Votos considerados para el reparto.
Eje X: Escaños conseguidos (función escalonada descendente, X depende de Y).
"""

from typing import Dict, Optional, List
import plotly.graph_objects as go
try:
    from core.dhondt import ConstituencyResult
except ImportError:
    from .dhondt import ConstituencyResult

# Paleta de colores accesible y colorblind-friendly (Okabe-Ito, Paul Tol e IBM Design)
# Diseñada para garantizar alto contraste y legibilidad para personas con deuteranopía, protanopía y tritanopía.
PARTY_COLORS = {
    # PP: Azul cobalto intenso (diferenciable de celestes y púrpuras)
    "PP": "#005AB5",
    # PSOE: Bermellón / Rojo anaranjado de alto contraste (Okabe-Ito, no colisiona con verdes)
    "PSOE": "#D55E00",
    # VOX: Verde azulado / Esmeralda (Okabe-Ito, muy distinguible del bermellón del PSOE)
    "VOX": "#009E73",
    "Vox": "#009E73",
    # Sumar: Magenta rojizo / Rosa oscuro accesible (Okabe-Ito)
    "SUMAR": "#CC79A7",
    "Sumar": "#CC79A7",
    # Podemos: Púrpura / Violeta intenso (IBM Design, distinguible de azules y rosas)
    "PODEMOS": "#785EF0",
    "Podemos": "#785EF0",
    "IZQUIERDA_UNIDA": "#882255",
    "IU": "#882255",
    # Coalición / Lista Única: Ciruela oscuro / Mora de alto contraste
    "Lista Única Izquierdas": "#4A148C",
    "Lista Única": "#4A148C",
    "Coalición Izquierda": "#4A148C",
    # ERC: Ámbar / Naranja dorado (Okabe-Ito)
    "ERC": "#E69F00",
    # JUNTS: Turquesa / Verde marino oscuro (IBM Design)
    "JUNTS": "#009D9A",
    "Junts": "#009D9A",
    # EH BILDU: Cerceta / Verde azulado medio
    "EH BILDU": "#44AA99",
    "EH Bildu": "#44AA99",
    # PNV: Verde bosque profundo (Paul Tol)
    "EAJ-PNV": "#117733",
    "PNV": "#117733",
    # BNG: Celeste / Sky Blue (Okabe-Ito, diferenciable del azul PP)
    "BNG": "#56B4E9",
    # CC: Amarillo dorado cálido
    "CC": "#FFB000",
    # UPN: Azul marino profundo
    "UPN": "#002D9C",
    # Adelante Andalucía: Verde pino / Esmeralda profundo
    "Adelante Andalucía": "#007756",
    # Compromís: Naranja vivo
    "Compromís": "#FE6100",
    # SALF: Púrpura oscuro / Índigo
    "SALF": "#332288",
    "Otros": "#666666",
}

# Paleta alternativa colorblind-safe de respaldo (Okabe-Ito / Tol)
COLORBLIND_FALLBACK = [
    "#005AB5",  # Azul
    "#D55E00",  # Bermellón
    "#009E73",  # Verde azulado
    "#E69F00",  # Naranja ámbar
    "#785EF0",  # Púrpura
    "#56B4E9",  # Celeste
    "#CC79A7",  # Magenta rojizo
    "#117733",  # Verde profundo
    "#882255",  # Burdeos
    "#44AA99",  # Turquesa
    "#FFB000",  # Oro
    "#332288",  # Índigo
]


def get_party_color(party_name: str, fallback_idx: int = 0) -> str:
    if party_name in PARTY_COLORS:
        return PARTY_COLORS[party_name]
    return COLORBLIND_FALLBACK[fallback_idx % len(COLORBLIND_FALLBACK)]


def create_dhondt_stepped_chart(
    votes: Dict[str, float],
    result: ConstituencyResult,
    title: str = "Carrera por los Escaños (Ley D'Hondt)",
    max_seats_display: Optional[int] = None,
    data_source: str = "Datos Oficiales 23J / Proyección de Sondeo",
    poll_date: Optional[str] = None,
) -> go.Figure:
    """
    Construye la gráfica escalonada interactiva solicitada.
    
    A medida que el cociente de votos (Y) disminuye:
    - Cuando Y está por encima de V_i, X = 0 escaños.
    - Cuando Y alcanza V_i / 1, X salta a 1 escaño.
    - Se mantiene en 1 hasta que Y baja a V_i / 2, donde salta a 2.
    - Y así sucesivamente.
    
    Una línea horizontal roja marca el 'cociente de corte' (último escaño repartido).
    Todo el texto se renderiza en negro (#000000) y se emplea una paleta colorblind-friendly.
    Incluye la procedencia y fecha de publicación de los datos en el encabezado y pie del gráfico.
    """
    fig = go.Figure()

    seats_to_alloc = result.seats_to_allocate
    max_seats = max_seats_display or (max(result.seats.values()) + 2 if result.seats else seats_to_alloc)
    max_seats = max(max_seats, 3)

    source_meta = f"<b>Procedencia de los datos:</b> {data_source}"
    if poll_date:
        source_meta += f" • <b>Fecha de publicación:</b> {poll_date}"

    # Determinar el techo del eje Y (el máximo de votos entre las listas elegibles)
    eligible_votes = [v for p, v in votes.items() if p not in result.excluded_parties and v > 0]
    if not eligible_votes:
        fig.add_annotation(
            text="Ningún partido superó el umbral de exclusión electoral.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#000000", family="sans-serif")
        )
        fig.update_layout(
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            font=dict(color="#000000", family="sans-serif"),
            title=dict(
                text=f"<b>{title}</b><br><span style='font-size:11px;color:#1E293B;'>{source_meta}</span>",
                font=dict(color="#000000", size=15),
            )
        )
        return fig

    max_vote = max(eligible_votes)
    cutoff = result.cutoff_quotient
    y_min_display = max(cutoff * 0.4, 1.0) if cutoff > 0 else 1.0
    y_max_display = max_vote * 1.08

    # Para cada partido admitido al reparto:
    for idx, (party, v) in enumerate(votes.items()):
        if party in result.excluded_parties or v <= 0:
            continue

        color = get_party_color(party, idx)
        seats_won = result.seats.get(party, 0)

        # Construir los puntos de la función escalonada (X: escaños, Y: cociente)
        x_coords = [0]
        y_coords = [y_max_display]

        # Para k = 1 hasta max_seats
        for k in range(1, max_seats + 1):
            q_k = v / k
            # Punto antes del salto (X = k - 1, Y = q_k)
            x_coords.append(k - 1)
            y_coords.append(q_k)
            # Salto horizontal al nuevo escaño (X = k, Y = q_k)
            x_coords.append(k)
            y_coords.append(q_k)

        # Añadimos la traza escalonada
        fig.add_trace(
            go.Scatter(
                x=x_coords,
                y=y_coords,
                mode="lines",
                name=f"{party} ({seats_won} esc.)",
                line=dict(color=color, width=2.8),
                hoverinfo="skip",
            )
        )

        # Añadir marcadores circulares en cada cociente exacto Q_k = V / k
        won_k = []
        won_q = []
        lost_k = []
        lost_q = []

        for k in range(1, max_seats + 1):
            q_k = v / k
            if k <= seats_won:
                won_k.append(k)
                won_q.append(q_k)
            else:
                lost_k.append(k)
                lost_q.append(q_k)

        # Marcadores de escaños conseguidos (llenos, borde negro definido para alta visibilidad)
        if won_k:
            fig.add_trace(
                go.Scatter(
                    x=won_k,
                    y=won_q,
                    mode="markers+text",
                    name=f"{party} (Obtenidos)",
                    marker=dict(size=12, color=color, symbol="circle", line=dict(width=1.5, color="#000000")),
                    text=[f"{party} #{k}" for k in won_k],
                    textposition="top right",
                    textfont=dict(size=11, color="#000000", family="sans-serif"),
                    hovertemplate=(
                        f"<b>{party}</b><br>"
                        + "Escaño #: %{x}<br>"
                        + "Cociente D'Hondt: %{y:,.1f} votos<br>"
                        + "<span style='color:green;font-weight:bold;'>✔ Escaño Asignado</span><extra></extra>"
                    ),
                    showlegend=False,
                )
            )

        # Marcadores de escaños no alcanzados (huecos con borde del color del partido)
        if lost_k:
            fig.add_trace(
                go.Scatter(
                    x=lost_k,
                    y=lost_q,
                    mode="markers",
                    name=f"{party} (No alcanzados)",
                    marker=dict(size=8, color="#FFFFFF", symbol="circle", line=dict(width=2.0, color=color)),
                    hovertemplate=(
                        f"<b>{party}</b><br>"
                        + "Escaño #: %{x}<br>"
                        + "Cociente: %{y:,.1f} votos<br>"
                        + "<span style='color:#C51B24;font-weight:bold;'>✘ No Alcanzado</span><extra></extra>"
                    ),
                    showlegend=False,
                )
            )

    # Línea horizontal del Cociente de Corte (el último escaño asignado)
    if cutoff > 0:
        fig.add_hline(
            y=cutoff,
            line_dash="dash",
            line_color="#C51B24",
            line_width=2.5,
            annotation_text=f"<b>Corte del último escaño ({cutoff:,.1f} votos)</b>",
            annotation_position="bottom right",
            annotation_font=dict(color="#000000", size=12, family="sans-serif"),
            annotation_bgcolor="#FFFFFF",
            annotation_bordercolor="#C51B24",
            annotation_borderwidth=1.5,
        )

    # Pie con la procedencia y fecha de los datos
    footer_text = f"<b>Procedencia de los datos:</b> {data_source}"
    if poll_date:
        footer_text += f" | <b>Fecha de publicación:</b> {poll_date}"

    fig.add_annotation(
        text=footer_text,
        xref="paper",
        yref="paper",
        x=0.0,
        y=-0.16,
        showarrow=False,
        font=dict(color="#000000", size=10, family="sans-serif"),
        xanchor="left",
    )

    # Configuración de los ejes y diseño visual con texto 100% negro y legible
    fig.update_layout(
        font=dict(
            family="sans-serif",
            size=12,
            color="#000000",
        ),
        title=dict(
            text=f"<b>{title}</b><br><span style='font-size:12px;color:#000000;font-weight:normal;'>Total a repartir: <b>{seats_to_alloc} escaños</b> | Votos válidos: <b>{result.valid_votes:,.0f}</b></span><br><span style='font-size:11px;color:#1E293B;font-weight:normal;'>{source_meta}</span>",
            x=0.04,
            y=0.96,
            font=dict(color="#000000", size=16, family="sans-serif"),
        ),
        xaxis=dict(
            title=dict(
                text="<b>Escaños conseguidos (X)</b>",
                font=dict(color="#000000", size=13, family="sans-serif"),
            ),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
            tickmode="linear",
            tick0=0,
            dtick=1,
            range=[-0.2, max_seats + 0.8],
            gridcolor="#E2E8F0",
            zeroline=True,
            zerolinecolor="#475569",
            zerolinewidth=1.5,
        ),
        yaxis=dict(
            title=dict(
                text="<b>Votos / Cociente de reparto (Y)</b>",
                font=dict(color="#000000", size=13, family="sans-serif"),
            ),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
            range=[y_min_display, y_max_display],
            gridcolor="#E2E8F0",
            tickformat=",.0f",
            zeroline=False,
        ),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        hovermode="closest",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#000000", size=11, family="sans-serif"),
            bgcolor="rgba(255, 255, 255, 0.95)",
            bordercolor="#000000",
            borderwidth=1,
        ),
        margin=dict(l=65, r=40, t=110, b=75),
    )

    return fig
