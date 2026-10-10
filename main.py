"""
Punto de entrada principal para el Simulador Electoral D'Hondt.
Permite ejecutar en modo CLI o arrancar la aplicación interactiva de Streamlit.
"""

import sys
import argparse
from pathlib import Path

app_dir = Path(__file__).parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from core.national_model import SpanishElectoralModel
from analysis.coalition_analyzer import CoalitionAnalyzer
from data.poll_connector import PollConnector


def run_cli_analysis(poll_name: str = "CIS (Barómetro de Intención de Voto)", retention_pct: float = 85.0):
    connector = PollConnector()
    poll_data = connector.get_poll(poll_name)
    if not poll_data:
        poll_name = list(connector.cached_polls.keys())[1]
        poll_data = connector.get_poll(poll_name)

    poll = poll_data["poll"]
    retention_rate = retention_pct / 100.0

    print("=" * 70)
    print(f" SIMULADOR ELECTORAL D'HONDT - ESPAÑA (350 ESCAÑOS)")
    print(f" Encuesta: {poll_name}")
    print(f" Tasa de retención de lista única: {retention_pct:.1f}%")
    print("=" * 70)

    analyzer = CoalitionAnalyzer()
    comp = analyzer.compare(poll, retention_rate=retention_rate)

    print(f"\n[1] RESULTADOS COMPARATIVOS DEL BLOQUE DE IZQUIERDAS:")
    print(f"  * Escenario Separados (Sumar + Podemos):")
    print(f"      - Escaños: {comp.separated_left_seats}")
    print(f"      - Votos:   {comp.separated_left_votes:,.0f}")
    print(f"      - Coste:   {comp.separated_votes_per_seat:,.0f} votos/escaño")
    print(f"  * Escenario Lista Única ({retention_pct:.0f}% retención):")
    print(f"      - Escaños: {comp.coalition_left_seats}")
    print(f"      - Votos:   {comp.coalition_left_votes:,.0f}")
    print(f"      - Coste:   {comp.coalition_votes_per_seat:,.0f} votos/escaño")
    print(f"  * Diferencia: {comp.seat_difference:+d} escaños a favor de {comp.more_favorable_scenario}")

    print(f"\n[2] RESPUESTA A LA PREGUNTA CLAVE (OPTIMIZACIÓN INVERSA):")
    inv = analyzer.solve_votes_needed_to_match_target(poll, retention_rate=retention_rate)
    print(f"  Para que el escenario {inv.underperforming_scenario} consiga los {inv.target_seats} escaños")
    print(f"  del escenario {inv.favorable_scenario}, necesitaría:")
    print(f"      - Votos actuales:    {inv.current_votes:,.0f} ({inv.current_pct:.1f}% nac.)")
    print(f"      - Votos requeridos:  {inv.required_votes:,.0f} ({inv.required_pct:.1f}% nac.)")
    print(f"      - Votos ADICIONALES: +{inv.additional_votes_needed:,.0f} (+{inv.additional_pct_needed:.2f}% nac.)")
    print(f"      - Multiplicador:     {inv.multiplier:.2f}x")
    if inv.newly_won_provinces:
        print(f"  Provincias beneficiadas: {', '.join(inv.newly_won_provinces[:6])}")

    print(f"\n[3] UMBRAL CRÍTICO DE RENTABILIDAD / INDIFERENCIA (R*):")
    _, _, sep_s, breakeven_r = analyzer.calculate_breakeven_curve(poll)
    if breakeven_r:
        print(f"  Punto de corte: {breakeven_r*100:.1f}% de retención")
        print(f"  -> Con retención > {breakeven_r*100:.1f}%, la LISTA ÚNICA obtiene más escaños.")
        print(f"  -> Se requeriría una desafección > {(1-breakeven_r)*100:.1f}% para que ir separados fuera mejor.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Simulador Electoral D'Hondt")
    parser.add_argument("--cli", action="store_true", help="Ejecutar análisis en terminal")
    parser.add_argument("--retention", type=float, default=85.0, help="Tasa de retención de la coalición (por defecto: 85.0)")
    parser.add_argument("--poll", type=str, default="CIS (Barómetro de Intención de Voto)", help="Nombre de la encuesta")
    parser.add_argument("--app", action="store_true", help="Lanzar la interfaz web interactiva con Streamlit")

    args = parser.parse_args()

    if args.app or (len(sys.argv) == 1):
        import subprocess
        print("Lanzando aplicación web interactiva en Streamlit...")
        app_path = app_dir / "app.py"
        subprocess.run(["streamlit", "run", str(app_path)])
    else:
        run_cli_analysis(poll_name=args.poll, retention_pct=args.retention)


if __name__ == "__main__":
    main()
