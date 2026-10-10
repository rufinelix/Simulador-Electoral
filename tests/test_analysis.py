"""
Test unitario del analizador de coalición y optimizador inverso.
"""

import unittest
import sys
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from analysis.coalition_analyzer import CoalitionAnalyzer


class TestAnalysisSuite(unittest.TestCase):
    def setUp(self):
        self.analyzer = CoalitionAnalyzer()
        self.poll = {
            "PP": 34.0,
            "PSOE": 29.0,
            "Vox": 12.0,
            "Sumar": 6.5,
            "Podemos": 4.0,
            "ERC": 1.8,
            "Junts": 1.6,
            "EH Bildu": 1.4,
            "PNV": 1.1,
            "BNG": 0.6,
            "CC": 0.5,
            "UPN": 0.2,
        }

    def test_coalition_vs_separated_comparison(self):
        comp = self.analyzer.compare(self.poll, retention_rate=0.85)
        self.assertGreater(comp.coalition_left_seats, 0)
        self.assertGreater(comp.separated_left_seats, 0)
        self.assertIn(comp.more_favorable_scenario, ["Coalición", "Separados", "Empate"])
        self.assertIsInstance(comp.flipped_provinces, list)

    def test_inverse_optimization(self):
        inv = self.analyzer.solve_votes_needed_to_match_target(self.poll, retention_rate=0.85)
        self.assertGreaterEqual(inv.target_seats, 0)
        self.assertGreaterEqual(inv.multiplier, 1.0)
        self.assertGreaterEqual(inv.additional_votes_needed, 0.0)

    def test_breakeven_curve(self):
        rates, coal_s, sep_s, breakeven_r = self.analyzer.calculate_breakeven_curve(self.poll)
        self.assertEqual(len(rates), len(coal_s))
        self.assertGreaterEqual(sep_s, 0)
        if breakeven_r is not None:
            self.assertGreater(breakeven_r, 0.0)
            self.assertLess(breakeven_r, 1.5)


if __name__ == "__main__":
    unittest.main()
