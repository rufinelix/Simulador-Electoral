"""
Pruebas de verificación de sincronización de estado y diversidad de resultados
entre los distintos sondeos demoscópicos (CIS, 40dB, Sigma Dos, ElectoPanel, GAD3, etc.).
"""

import unittest
import sys
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from core.national_model import SpanishElectoralModel
from analysis.coalition_analyzer import CoalitionAnalyzer
from data.poll_connector import BENCHMARK_POLLS


class TestUIStateAndPollSync(unittest.TestCase):
    def setUp(self):
        self.model = SpanishElectoralModel()
        self.analyzer = CoalitionAnalyzer(self.model)

    def test_all_benchmark_polls_produce_distinct_national_seats(self):
        """Verifica que cada sondeo produce resultados parlamentarios diferenciados y no idénticos."""
        results = {}
        for poll_name, p_info in BENCHMARK_POLLS.items():
            if poll_name == "Oficial 23J 2023 (Congreso de los Diputados)":
                sim = self.model.simulate(
                    national_poll=p_info["poll"],
                    left_scenario="separated",
                    is_official_23j=True
                )
            else:
                sim = self.model.simulate(
                    national_poll=p_info["poll"],
                    left_scenario="separated",
                    is_official_23j=False
                )
            
            top_parties = (
                sim.national_seats.get("PP", 0),
                sim.national_seats.get("PSOE", 0),
                sim.national_seats.get("Vox", 0),
                sim.national_seats.get("Sumar", 0),
                sim.national_seats.get("Podemos", 0),
            )
            results[poll_name] = top_parties

        # Verificar que CIS y 40dB no dan los mismos escaños
        cis_key = "CIS (Barómetro de Intención de Voto)"
        db40_key = "40dB / El País - Cadena SER"
        self.assertIn(cis_key, results)
        self.assertIn(db40_key, results)
        self.assertNotEqual(
            results[db40_key],
            results[cis_key],
            "40dB y CIS deben arrojar resultados parlamentarios diferentes"
        )

        # En CIS el PSOE debe liderar frente al PP en escaños
        cis_seats = results[cis_key]
        self.assertGreater(cis_seats[1], cis_seats[0], "En CIS el PSOE tiene más escaños que el PP")

        # En 40dB el PP debe superar al PSOE
        db40_seats = results[db40_key]
        self.assertGreater(db40_seats[0], db40_seats[1], "En 40dB el PP supera al PSOE")

        # Sigma Dos también debe superar al PSOE ampliamente
        sigma_seats = results["Sigma Dos / El Mundo"]
        self.assertGreater(sigma_seats[0], sigma_seats[1], "En Sigma Dos el PP supera al PSOE")

    def test_analyzer_compare_varies_by_poll(self):
        """Verifica que CoalitionAnalyzer.compare() genera métricas distintas según el sondeo."""
        cis_key = "CIS (Barómetro de Intención de Voto)"
        comp_40db = self.analyzer.compare(
            poll=BENCHMARK_POLLS["40dB / El País - Cadena SER"]["poll"],
            retention_rate=1.0,
            custom_coalition_name="Lista Única",
            default_coalition_members=["Sumar", "Podemos"],
            threshold_pct=3.0,
            blank_pct=0.8,
            is_official_23j=False,
        )

        comp_cis = self.analyzer.compare(
            poll=BENCHMARK_POLLS[cis_key]["poll"],
            retention_rate=1.0,
            custom_coalition_name="Lista Única",
            default_coalition_members=["Sumar", "Podemos"],
            threshold_pct=3.0,
            blank_pct=0.8,
            is_official_23j=False,
        )

        # Los votos y escaños de izquierda deben ser diferentes entre 40dB y CIS
        self.assertNotEqual(comp_40db.separated_left_votes, comp_cis.separated_left_votes)
        self.assertNotEqual(comp_40db.separated_left_seats, comp_cis.separated_left_seats)

    def test_session_state_purging_mechanism(self):
        """
        Simula el mecanismo de purga de estado de Streamlit implementado en app.py:
        al cambiar de sondeo, las claves antiguas se eliminan para que number_input
        adopte los valores reales del nuevo sondeo.
        """
        fake_session_state = {}

        # 1. Usuario carga 40dB
        active_poll = "40dB / El País - Cadena SER"
        fake_session_state["s1_last_poll_name"] = active_poll
        poll_40db = BENCHMARK_POLLS[active_poll]["poll"]
        for p, val in poll_40db.items():
            fake_session_state[f"s1_p_{active_poll}_{p}"] = float(val)

        self.assertEqual(fake_session_state[f"s1_p_{active_poll}_PP"], poll_40db["PP"])

        # 2. Usuario cambia a CIS
        new_poll = "CIS (Barómetro de Intención de Voto)"
        if fake_session_state.get("s1_last_poll_name") != new_poll:
            fake_session_state["s1_last_poll_name"] = new_poll
            for k in list(fake_session_state.keys()):
                if k.startswith("s1_p_"):
                    del fake_session_state[k]

        self.assertEqual(fake_session_state["s1_last_poll_name"], new_poll)
        self.assertNotIn(f"s1_p_{active_poll}_PP", fake_session_state)

        # 3. Widgets de CIS se inicializan con valores de CIS
        poll_cis = BENCHMARK_POLLS[new_poll]["poll"]
        for p, val in poll_cis.items():
            fake_session_state[f"s1_p_{new_poll}_{p}"] = float(val)

        self.assertEqual(fake_session_state[f"s1_p_{new_poll}_PP"], 25.5)
        self.assertEqual(fake_session_state[f"s1_p_{new_poll}_PSOE"], 31.0)


if __name__ == "__main__":
    unittest.main()
