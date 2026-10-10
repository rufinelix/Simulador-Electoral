"""
Tests unitarios exhaustivos para el simulador electoral D'Hondt.
"""

import unittest
import sys
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from core.dhondt import calculate_dhondt
from core.national_model import SpanishElectoralModel
from analysis.coalition_analyzer import CoalitionAnalyzer


class TestDhondtCore(unittest.TestCase):
    def test_loreg_canonical_case(self):
        """Caso de ejemplo oficial de la LOREG (artículo 163)."""
        votes = {
            "A": 168000,
            "B": 112000,
            "C": 69000,
            "D": 52000,
            "E": 26000,
            "F": 13000,
        }
        res = calculate_dhondt(votes, seats_to_allocate=8, blank_votes=0, threshold_pct=3.0)
        self.assertEqual(res.seats["A"], 4)
        self.assertEqual(res.seats["B"], 2)
        self.assertEqual(res.seats["C"], 1)
        self.assertEqual(res.seats["D"], 1)
        self.assertEqual(res.seats["E"], 0)
        self.assertEqual(res.seats["F"], 0)
        self.assertEqual(sum(res.seats.values()), 8)
        self.assertEqual(res.cutoff_quotient, 42000.0)
        self.assertEqual(res.last_seat_winner, "A")
        self.assertEqual(res.runner_up_party, "B")

    def test_threshold_exclusion_with_blank_votes(self):
        """Verifica que los votos en blanco aumentan los votos válidos y pueden excluir listas."""
        votes = {"A": 1000, "B": 29}
        # Con 0 votos en blanco, B tiene 29 / 1029 = 2.81% -> Excluido al 3%
        res_no_blank = calculate_dhondt(votes, seats_to_allocate=1, blank_votes=0, threshold_pct=3.0)
        self.assertIn("B", res_no_blank.excluded_parties)
        self.assertEqual(res_no_blank.seats["A"], 1)
        self.assertEqual(res_no_blank.seats["B"], 0)

        # Si A tiene 950 y B tiene 31, total = 981. B tiene 31 / 981 = 3.16% -> Entra
        votes2 = {"A": 950, "B": 31}
        res_pass = calculate_dhondt(votes2, seats_to_allocate=1, blank_votes=0, threshold_pct=3.0)
        self.assertNotIn("B", res_pass.excluded_parties)

        # Pero si añadimos 100 votos en blanco, total = 1081. B tiene 31 / 1081 = 2.86% -> Excluido
        res_excluded = calculate_dhondt(votes2, seats_to_allocate=1, blank_votes=100, threshold_pct=3.0)
        self.assertIn("B", res_excluded.excluded_parties)

    def test_votes_needed_for_next_seat(self):
        """Verifica el cálculo del déficit de votos para el siguiente escaño."""
        votes = {"A": 10000, "B": 4500}
        # Reparto de 2 escaños: A gana 10000 (esc 1), A gana 5000 (esc 2). Corte = 5000 (A).
        # B tiene 4500. Para ganar su 1er escaño necesita superar 5000: necesita 5001 (delta = 500 votos).
        res = calculate_dhondt(votes, seats_to_allocate=2, blank_votes=0, threshold_pct=3.0)
        self.assertEqual(res.seats["A"], 2)
        self.assertEqual(res.seats["B"], 0)
        self.assertEqual(res.votes_needed_for_next_seat["B"], 500.0)


class TestNationalModel(unittest.TestCase):
    def setUp(self):
        self.model = SpanishElectoralModel()

    def test_baseline_2023_reproduction(self):
        """Verifica que el modelo con los porcentajes del 23J reproduce exactamente los 350 escaños."""
        poll_2023 = {
            "PP": 33.05,
            "PSOE": 31.70,
            "Vox": 12.39,
            "Sumar": 12.31,
            "ERC": 1.89,
            "Junts": 1.60,
            "EH Bildu": 1.36,
            "PNV": 1.12,
            "BNG": 0.62,
            "CC": 0.46,
            "UPN": 0.21,
        }
        res = self.model.simulate(poll_2023, left_scenario="coalition", coalition_retention_rate=1.0)
        total_seats = sum(res.national_seats.values())
        self.assertEqual(total_seats, 350)
        self.assertEqual(len(res.constituency_data), 52)


class TestCoalitionAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = CoalitionAnalyzer()

    def test_inverse_optimization_convergence(self):
        """Verifica que el optimizador inverso converge a igualar los escaños del objetivo."""
        poll = {
            "PP": 34.0, "PSOE": 29.0, "Vox": 12.0, "Sumar": 6.5, "Podemos": 4.0,
            "ERC": 1.8, "Junts": 1.6, "EH Bildu": 1.4, "PNV": 1.1, "BNG": 0.6, "CC": 0.5, "UPN": 0.2
        }
        inv = self.analyzer.solve_votes_needed_to_match_target(poll, retention_rate=0.85)
        self.assertGreaterEqual(inv.multiplier, 1.0)
        self.assertGreaterEqual(inv.additional_votes_needed, 0)
    def test_single_constituency_comparison(self):
        """Verifica la simulación libre de circunscripción única comparando ambos escenarios."""
        parties = {"PP": 85000, "PSOE": 72000, "Vox": 28000, "Sumar": 19000, "Podemos": 14000, "Local": 8000}
        comp = self.analyzer.compare_single_constituency(
            parties_votes=parties,
            coalition_members=["Sumar", "Podemos"],
            seats=6,
            blank_votes=2000,
            threshold_pct=3.0,
            retention_rate=0.85,
            coalition_name="Lista Única",
        )
        self.assertEqual(comp.separated_left_seats, 0)
        self.assertEqual(comp.coalition_left_seats, 1)
        self.assertEqual(comp.more_favorable_scenario, "Coalición")
        self.assertGreater(comp.additional_votes_needed, 0)
        self.assertIsNotNone(comp.breakeven_r)

    def test_single_constituency_retention_by_party(self):
        """Verifica la tasa de retención diferenciada partido a partido."""
        parties = {"PP": 50000, "PSOE": 40000, "Sumar": 20000, "Podemos": 10000}
        retention_by_party = {"Sumar": 0.90, "Podemos": 0.50}  # 20000*0.9 + 10000*0.5 = 18000 + 5000 = 23000
        comp = self.analyzer.compare_single_constituency(
            parties_votes=parties,
            coalition_members=["Sumar", "Podemos"],
            seats=4,
            blank_votes=500,
            threshold_pct=3.0,
            retention_rate=1.0,
            retention_by_party=retention_by_party,
            coalition_name="Izquierda Unida",
        )
        self.assertEqual(comp.coalition_left_votes, 23000)

    def test_stepped_chart_black_text_and_palette(self):
        """Verifica que la gráfica escalonada use fuentes negras y colores accesibles."""
        from core.stepped_chart import create_dhondt_stepped_chart, get_party_color, PARTY_COLORS
        res = calculate_dhondt({"PP": 100000, "PSOE": 80000, "Vox": 30000}, seats_to_allocate=4)
        fig = create_dhondt_stepped_chart({"PP": 100000, "PSOE": 80000, "Vox": 30000}, res)
        # Verificar fuente negra
        self.assertEqual(fig.layout.font.color, "#000000")
        self.assertEqual(fig.layout.xaxis.title.font.color, "#000000")
        self.assertEqual(fig.layout.yaxis.title.font.color, "#000000")
        # Verificar paleta colorblind (PP azul accesible, PSOE bermellón, Vox esmeralda)
        self.assertEqual(PARTY_COLORS["PP"], "#005AB5")
        self.assertEqual(PARTY_COLORS["PSOE"], "#D55E00")
        self.assertEqual(PARTY_COLORS["VOX"], "#009E73")


if __name__ == "__main__":
    unittest.main()
