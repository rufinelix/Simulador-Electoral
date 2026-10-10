import unittest
import os
import sys
from pathlib import Path

# Agregar raíz al sys.path
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from core.national_model import SpanishElectoralModel, BASELINE_NATIONAL_2023
from core.electoral_map import (
    load_spain_geojson,
    build_constituency_electoral_summary,
    create_spain_electoral_map,
)
from core.toponyms import PROVINCES_DATA


class TestElectoralMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = SpanishElectoralModel()
        cls.sim_sep = cls.model.simulate(
            national_poll=BASELINE_NATIONAL_2023,
            left_scenario="separated",
            is_official_23j=True,
        )
        cls.sim_coal = cls.model.simulate(
            national_poll=BASELINE_NATIONAL_2023,
            left_scenario="coalitions",
            default_coalition_members=["Sumar", "Podemos"],
            coalition_retention_rate=1.0,
            is_official_23j=True,
        )

    def test_geojson_loading_and_features(self):
        geojson = load_spain_geojson(use_inset=True)
        self.assertIn("features", geojson)
        self.assertEqual(len(geojson["features"]), 52)
        canonical_set = set(PROVINCES_DATA.keys())
        for f in geojson["features"]:
            self.assertIn(f["id"], canonical_set)

    def test_build_summary_structure_and_no_bull_entity(self):
        df = build_constituency_electoral_summary(self.sim_sep)
        self.assertEqual(len(df), 52)
        self.assertIn("province", df.columns)
        self.assertIn("winner", df.columns)
        self.assertIn("winner_seats", df.columns)
        self.assertIn("hover_text", df.columns)

        # Madrid should have 38 seats (actualizado Real Decreto 806/2026)
        madrid_row = df[df["province"] == "Madrid"].iloc[0]
        self.assertEqual(madrid_row["seats"], 38)
        self.assertGreater(madrid_row["winner_seats"], 0)
        self.assertGreater(madrid_row["winner_pct"], 0.0)
        self.assertAlmostEqual(madrid_row["winner_pct"], 40.55, delta=0.5)
        self.assertIn("Madrid", madrid_row["hover_text"])

        # Cádiz should have 8 seats
        cadiz_row = df[df["province"] == "Cádiz"].iloc[0]
        self.assertEqual(cadiz_row["seats"], 8)
        self.assertGreater(cadiz_row["winner_pct"], 0.0)
        self.assertAlmostEqual(cadiz_row["winner_pct"], 34.8, delta=0.5)

        # Verificar que NINGÚN tooltip contiene la entidad rota &bull
        for _, r in df.iterrows():
            self.assertNotIn("&bull", r["hover_text"], f"Found &bull in {r['province']}")

    def test_build_summary_with_comparison(self):
        df_comp = build_constituency_electoral_summary(
            sim_result=self.sim_coal,
            comparison_result=self.sim_sep,
            coalition_name="Lista Única",
            coalition_members=["Sumar", "Podemos"],
            is_active_separated=False,
        )
        self.assertEqual(len(df_comp), 52)
        self.assertIn("coalition_diff", df_comp.columns)
        self.assertIn("transfer_category", df_comp.columns)

        # Probar también con el escenario activo como SEPARADO
        df_comp_sep = build_constituency_electoral_summary(
            sim_result=self.sim_sep,
            comparison_result=self.sim_coal,
            coalition_name="Lista Única",
            coalition_members=["Sumar", "Podemos"],
            is_active_separated=True,
        )
        self.assertEqual(len(df_comp_sep), 52)
        for _, r in df_comp_sep.iterrows():
            self.assertNotIn("&bull", r["hover_text"])

    def test_create_map_modes_and_canary_box(self):
        df = build_constituency_electoral_summary(
            sim_result=self.sim_coal,
            comparison_result=self.sim_sep,
        )

        modes = ["winner", "coalition_impact", "party_pct", "party_seats", "seats_total", "single_province"]
        for mode in modes:
            fig = create_spain_electoral_map(
                df_data=df,
                view_mode=mode,
                selected_party="PP" if "party" in mode else None,
                highlight_province="Sevilla" if mode == "single_province" else None,
                use_inset=True,
            )
            self.assertIsNotNone(fig)
            self.assertGreater(len(fig.data), 0, f"Failed for mode {mode}")

            # Verificar que el recuadro geográfico de Canarias existe en la figura
            trace_names = [t.name for t in fig.data if hasattr(t, "name") and t.name]
            self.assertIn("Recuadro Canarias", trace_names)


if __name__ == "__main__":
    unittest.main()
