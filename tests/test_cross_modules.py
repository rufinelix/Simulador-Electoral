"""
Test exhaustivo de integración cruzada entre módulos (Cross-Module End-to-End Test).
Valida que todos los métodos, estructuras de datos, retornos y pipelines utilizados
en cada pestaña de app.py se ejecuten sin excepción con datos reales y extremos.
"""

import unittest
import sys
import io
import pandas as pd
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from core.dhondt import calculate_dhondt, ConstituencyResult
from core.stepped_chart import create_dhondt_stepped_chart, get_party_color, PARTY_COLORS
from core.national_model import SpanishElectoralModel, BASELINE_NATIONAL_2023
from analysis.coalition_analyzer import CoalitionAnalyzer
from data.poll_connector import PollConnector


class TestCrossModulesE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = SpanishElectoralModel()
        cls.poll_conn = PollConnector()
        cls.analyzer = CoalitionAnalyzer(cls.model)

    def test_pipeline_tab1_national_simple(self):
        """Prueba todo el pipeline de cómputo y visualización de la Pestaña 1."""
        for poll_name in self.poll_conn.get_available_poll_names():
            poll_info = self.poll_conn.get_poll(poll_name)
            poll_dict = dict(poll_info["poll"])

            # 1. Comparativa nacional
            comp = self.analyzer.compare(poll_dict, retention_rate=0.85)
            self.assertGreater(comp.coalition_left_seats + comp.separated_left_seats, 0)
            self.assertIsNotNone(comp.more_favorable_scenario)

            # 2. Optimizador inverso
            inv = self.analyzer.solve_votes_needed_to_match_target(poll_dict, retention_rate=0.85)
            self.assertGreaterEqual(inv.additional_votes_needed, 0.0)

            # 3. Curva de sensibilidad
            rates, coal_s, sep_s, breakeven_r = self.analyzer.calculate_breakeven_curve(poll_dict)
            self.assertEqual(len(rates), len(coal_s))

            # 4. Gráfica escalonada para una provincia grande, mediana y pequeña
            for sample_prov in ["Madrid", "Sevilla", "Teruel"]:
                sim_res = self.model.simulate(poll_dict, left_scenario="coalition", coalition_retention_rate=0.85)
                c_res = sim_res.constituency_results[sample_prov]
                c_data = next(c for c in sim_res.constituency_data if c["name"] == sample_prov)
                fig = create_dhondt_stepped_chart(
                    votes=c_data["parties_votes"],
                    result=c_res,
                    title=f"Test {sample_prov}",
                )
                self.assertEqual(fig.layout.font.color, "#000000")

    def test_pipeline_tab2_single_constituency_extremes(self):
        """Prueba el pipeline de la Pestaña 2 (Simulación Compleja de una Circunscripción)."""
        # Caso 1: Provincia real cargada (Sevilla) con Adelante Andalucía
        sevilla = self.model.get_constituency("Sevilla")
        self.assertIn("Adelante Andalucía", sevilla["parties_pct"])

        parties_sevilla = {
            p: round((pct / 100.0) * sevilla["valid_votes"])
            for p, pct in sevilla["parties_pct"].items()
            if pct > 0
        }
        if "Adelante Andalucía" not in parties_sevilla:
            parties_sevilla["Adelante Andalucía"] = 30000

        ret_by_party = {"Sumar": 0.90, "Podemos": 0.75, "Adelante Andalucía": 0.60}
        comp = self.analyzer.compare_single_constituency(
            parties_votes=parties_sevilla,
            coalition_members=["Sumar", "Podemos", "Adelante Andalucía"],
            seats=sevilla["seats"],
            blank_votes=round(sevilla["valid_votes"] * 0.008),
            threshold_pct=3.0,
            retention_rate=0.85,
            retention_by_party=ret_by_party,
            coalition_name="Izquierda Andaluza Unida",
        )
        self.assertGreaterEqual(comp.coalition_left_seats, 0)
        self.assertGreaterEqual(comp.separated_left_seats, 0)
        self.assertGreaterEqual(comp.additional_votes_needed, 0.0)

        # Gráfica para ambos escenarios
        fig_sep = create_dhondt_stepped_chart(parties_sevilla, comp.result_separated)
        self.assertEqual(fig_sep.layout.font.color, "#000000")

        coal_v = {p: v for p, v in parties_sevilla.items() if p not in ["Sumar", "Podemos", "Adelante Andalucía"]}
        coal_v["Izquierda Andaluza Unida"] = comp.coalition_left_votes
        fig_coal = create_dhondt_stepped_chart(coal_v, comp.result_coalition)
        self.assertEqual(fig_coal.layout.font.color, "#000000")

    def test_pipeline_tab3_complex_national_overrides(self):
        """Prueba la Pestaña 3 (Control Provincia a Provincia y Recuento Nacional Agregado)."""
        poll = dict(BASELINE_NATIONAL_2023)
        global_cfg = {
            "name": "Frente Popular Progresista",
            "members": ["Sumar", "Podemos"],
            "retention_by_party": {"Sumar": 0.85, "Podemos": 0.80},
        }

        # Aplicar excepciones en Madrid, Barcelona y Sevilla
        overrides = {
            "Madrid": {
                "census": 5_200_000,
                "turnout_pct": 74.0,
                "blank_pct": 0.9,
                "null_pct": 0.8,
                "input_mode": "pct",
                "parties": {"PP": 40.0, "PSOE": 28.0, "Vox": 10.0, "Sumar": 11.0, "Podemos": 6.0, "Nuevo Partido": 3.5},
                "coalition": {
                    "enabled": True,
                    "name": "Madrid En Común",
                    "members": ["Sumar", "Podemos"],
                    "retention_by_party": {"Sumar": 0.90, "Podemos": 0.90},
                }
            },
            "Barcelona": {
                "census": 4_100_000,
                "turnout_pct": 68.0,
                "blank_pct": 0.7,
                "null_pct": 0.9,
                "input_mode": "votes",
                "parties": {"PSC": 750000, "ERC": 420000, "Junts": 400000, "PP": 380000, "Sumar": 320000, "Podemos": 110000, "Vox": 190000},
                "coalition": {
                    "enabled": True,
                    "name": "En Comú Podem",
                    "members": ["Sumar", "Podemos"],
                    "retention_by_party": {"Sumar": 0.88, "Podemos": 0.85},
                }
            },
            "Cádiz": {
                "coalition": {
                    "enabled": False,  # Se desactiva la coalición en Cádiz
                }
            }
        }

        # Simular modo 'separated'
        res_sep = self.model.simulate(
            national_poll=poll,
            left_scenario="separated",
            constituency_overrides=overrides,
            default_coalition_members=global_cfg["members"],
            default_retention_by_party=global_cfg["retention_by_party"],
        )
        self.assertEqual(sum(res_sep.national_seats.values()), 350)

        # Simular modo 'coalitions'
        res_coal = self.model.simulate(
            national_poll=poll,
            left_scenario="coalitions",
            constituency_overrides=overrides,
            default_coalition_members=global_cfg["members"],
            default_retention_by_party=global_cfg["retention_by_party"],
            custom_coalition_name=global_cfg["name"],
        )
        self.assertEqual(sum(res_coal.national_seats.values()), 350)
        # Verificar que en Cádiz compitieron separados
        cadiz_res = res_coal.constituency_results["Cádiz"]
        self.assertNotIn(global_cfg["name"], cadiz_res.seats)

    def test_pipeline_tab4_excel_template_and_ingestion(self):
        """Prueba la generación e ingesta de plantillas Excel en memoria."""
        # 1. Crear plantilla en memoria
        df = pd.DataFrame([
            {"Partido": "PP", "Porcentaje": 33.5},
            {"Partido": "PSOE", "Porcentaje": 29.8},
            {"Partido": "Vox", "Porcentaje": 11.9},
            {"Partido": "Sumar", "Porcentaje": 7.5},
            {"Partido": "Podemos", "Porcentaje": 4.2},
        ])
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Encuesta_Nacional")
        excel_bytes = excel_buffer.getvalue()

        # 2. Releer como si fuera el archivo cargado por el usuario
        read_df = pd.read_excel(io.BytesIO(excel_bytes))
        self.assertEqual(len(read_df), 5)
        parsed_poll = {str(row["Partido"]): float(row["Porcentaje"]) for _, row in read_df.iterrows()}

        # 3. Simular con la encuesta importada
        sim = self.model.simulate(parsed_poll, left_scenario="separated")
        self.assertEqual(sum(sim.national_seats.values()), 350)

    def test_party_constituencies_scoping_and_data_provenance(self):
        """Prueba la asignación territorial por partido, Adelante Andalucía y procedencia de datos."""
        # Verificar que todos los sondeos tienen Adelante Andalucía
        for name in self.poll_conn.get_available_poll_names():
            data = self.poll_conn.get_poll(name)
            self.assertIn("Adelante Andalucía", data["poll"], f"Falta Adelante Andalucía en {name}")

        scopes = {
            "Adelante Andalucía": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
            "ERC": ["Barcelona", "Girona", "Lleida", "Tarragona"],
        }
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]
        sim = self.model.simulate(cis_data, left_scenario="separated", party_constituencies=scopes)

        sev = next(c for c in sim.constituency_data if c["name"] == "Sevilla")
        mad = next(c for c in sim.constituency_data if c["name"] == "Madrid")
        bar = next(c for c in sim.constituency_data if c["name"] == "Barcelona")

        self.assertIn("Adelante Andalucía", sev["parties_votes"])
        self.assertNotIn("Adelante Andalucía", mad["parties_votes"])
        self.assertIn("ERC", bar["parties_votes"])
        self.assertNotIn("ERC", mad["parties_votes"])

        # Probar creación de gráfica con data_source y poll_date
        cis_date = self.poll_conn.get_poll_date("CIS (Barómetro de Intención de Voto)")
        self.assertIn("septiembre", cis_date.lower())
        fig = create_dhondt_stepped_chart(
            votes=sev["parties_votes"],
            result=sev["result"],
            title="Sevilla Test",
            data_source="Sondeo CIS Proyectado",
            poll_date=cis_date,
        )
        self.assertIn("Sondeo CIS Proyectado", fig.layout.title.text)
        self.assertIn(cis_date, fig.layout.title.text)

    def test_toponym_bidirectional_resolution_cis_erc(self):
        """
        Valida que ERC, Junts, Bildu, PNV, BNG y Adelante Andalucía concurran
        correctamente en sus circunscripciones con datos del CIS tanto si se consultan
        o configuran en castellano como en su toponimia cooficial o formato BOE.
        """
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]

        # Configuración territorial usando nombres de provincias en catalán, euskera y gallego
        coofficial_scopes = {
            "ERC": ["Barcelona", "Girona", "Lleida", "Tarragona"],
            "Junts": ["Barcelona", "Girona", "Lleida", "Tarragona"],
            "EH Bildu": ["Araba/Álava", "Bizkaia", "Gipuzkoa", "Navarra"],
            "PNV": ["Araba/Álava", "Bizkaia", "Gipuzkoa", "Navarra"],
            "BNG": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
        }
        sim_co = self.model.simulate(cis_data, left_scenario="separated", party_constituencies=coofficial_scopes)

        # 1. Girona / Gerona: ERC y Junts deben tener votos y escaños
        girona_c = next(c for c in sim_co.constituency_data if c["name"] == "Girona")
        self.assertIn("ERC", girona_c["parties_votes"], "ERC debe existir en Girona")
        self.assertGreater(girona_c["parties_votes"]["ERC"], 10000, "ERC debe tener votos representativos en Girona")
        self.assertIn("Junts", girona_c["parties_votes"], "Junts debe existir en Girona")
        self.assertGreater(girona_c["parties_votes"]["Junts"], 10000, "Junts debe tener votos representativos en Girona")

        # Acceso idéntico a través de toponimia castellana ("Gerona") y catalana ("Girona")
        self.assertEqual(sim_co.constituency_results["Gerona"].seats, sim_co.constituency_results["Girona"].seats)
        self.assertGreater(sim_co.constituency_results["Gerona"].seats.get("ERC", 0), 0, "ERC debe obtener representación en Gerona con CIS")
        self.assertGreater(sim_co.constituency_results["Gerona"].seats.get("Junts", 0), 0, "Junts debe obtener representación en Gerona con CIS")

        # 2. Lleida / Lérida: Acceso bidireccional
        self.assertEqual(sim_co.constituency_results["Lérida"].seats, sim_co.constituency_results["Lleida"].seats)
        self.assertIn("ERC", sim_co.constituency_results["Lérida"].seats)
        self.assertIn("Junts", sim_co.constituency_results["Lérida"].seats)

        # 3. Bizkaia / Vizcaya: PNV y Bildu deben obtener representación
        self.assertEqual(sim_co.constituency_results["Vizcaya"].seats, sim_co.constituency_results["Bizkaia"].seats)
        self.assertGreater(sim_co.constituency_results["Vizcaya"].seats.get("PNV", 0), 0)
        self.assertGreater(sim_co.constituency_results["Vizcaya"].seats.get("EH Bildu", 0), 0)

        # 4. Gipuzkoa / Guipúzcoa
        self.assertEqual(sim_co.constituency_results["Guipúzcoa"].seats, sim_co.constituency_results["Gipuzkoa"].seats)
        self.assertIn("EH Bildu", sim_co.constituency_results["Guipúzcoa"].seats)

        # 5. Araba/Álava / Álava
        self.assertEqual(sim_co.constituency_results["Álava"].seats, sim_co.constituency_results["Araba/Álava"].seats)
        self.assertIn("EH Bildu", sim_co.constituency_results["Álava"].seats)

        # 6. A Coruña / La Coruña / Coruña, La
        self.assertEqual(sim_co.constituency_results["La Coruña"].seats, sim_co.constituency_results["A Coruña"].seats)
        self.assertEqual(sim_co.constituency_results["Coruña, La"].seats, sim_co.constituency_results["A Coruña"].seats)
        self.assertGreater(sim_co.constituency_results["La Coruña"].seats.get("BNG", 0), 0)

        # 7. Ourense / Orense
        self.assertEqual(sim_co.constituency_results["Orense"].seats, sim_co.constituency_results["Ourense"].seats)

        # 8. Illes Balears / Baleares / Islas Baleares / Baleares, Islas
        self.assertEqual(sim_co.constituency_results["Baleares"].seats, sim_co.constituency_results["Illes Balears"].seats)
        self.assertEqual(sim_co.constituency_results["Islas Baleares"].seats, sim_co.constituency_results["Illes Balears"].seats)
        self.assertEqual(sim_co.constituency_results["Baleares, Islas"].seats, sim_co.constituency_results["Illes Balears"].seats)

        # 9. Las Palmas / Palmas, Las
        self.assertEqual(sim_co.constituency_results["Palmas, Las"].seats, sim_co.constituency_results["Las Palmas"].seats)

        # 10. La Rioja / Rioja, La
        self.assertEqual(sim_co.constituency_results["Rioja, La"].seats, sim_co.constituency_results["La Rioja"].seats)

        # 11. Valencia / València
        self.assertEqual(sim_co.constituency_results["Valencia"].seats, sim_co.constituency_results["Valencia/València"].seats)
        self.assertEqual(sim_co.constituency_results["València"].seats, sim_co.constituency_results["Valencia/València"].seats)

        # 12. get_constituency en modelo electoral
        self.assertIsNotNone(self.model.get_constituency("Gerona"))
        self.assertIsNotNone(self.model.get_constituency("Girona"))
        self.assertEqual(self.model.get_constituency("Gerona")["name"], self.model.get_constituency("Girona")["name"])
        self.assertIsNotNone(self.model.get_constituency("Vizcaya"))
        self.assertIsNotNone(self.model.get_constituency("Bizkaia"))
        self.assertEqual(self.model.get_constituency("Vizcaya")["name"], self.model.get_constituency("Bizkaia")["name"])

    def test_toponym_overrides_tolerance(self):
        """Valida que los overrides manuales especificados en castellano se apliquen sin fallo a provincias canónicas."""
        poll = dict(BASELINE_NATIONAL_2023)
        overrides = {
            "Gerona": {
                "parties": {"ERC": 85000, "Junts": 80000, "PSC": 75000, "PP": 30000},
                "input_mode": "votes",
            },
            "Vizcaya": {
                "parties": {"PNV": 220000, "EH Bildu": 180000, "PSE-EE": 120000, "PP": 55000},
                "input_mode": "votes",
            },
        }
        res = self.model.simulate(poll, left_scenario="separated", constituency_overrides=overrides)
        girona_res = res.constituency_results["Girona"]
        self.assertIn("ERC", girona_res.seats)
        self.assertIn("Junts", girona_res.seats)

        bizkaia_res = res.constituency_results["Bizkaia"]
        self.assertIn("PNV", bizkaia_res.seats)
        self.assertIn("EH Bildu", bizkaia_res.seats)

    def test_exact_23j_constituency_data(self):
        """Valida que la simulación con datos oficiales 23J tome los votos y diputados reales exactos sin distorsión swing."""
        poll_23j = dict(BASELINE_NATIONAL_2023)
        res = self.model.simulate(poll_23j, left_scenario="separated", is_official_23j=True)

        # 1. Total nacional 350 escaños exactos (con Madrid 38 y Cádiz 8 según Real Decreto 806/2026)
        self.assertEqual(sum(res.national_seats.values()), 350)
        self.assertEqual(res.national_seats["PP"], 136)
        self.assertEqual(res.national_seats["PSOE"], 122)
        self.assertEqual(res.national_seats["Vox"], 33)
        self.assertEqual(res.national_seats["Sumar"], 31)
        self.assertEqual(res.national_seats["BNG"], 1)

        # 2. Comprobación exhaustiva en Madrid (38 escaños)
        madrid_data = next(c for c in res.constituency_data if c["name"] == "Madrid")
        madrid_obj = self.model.get_constituency("Madrid")
        self.assertEqual(madrid_data["valid_votes"], float(madrid_obj["valid_votes"]))
        self.assertEqual(madrid_data["parties_pct"]["PP"], 40.55)
        self.assertEqual(madrid_data["parties_pct"]["PSOE"], 27.84)
        self.assertEqual(madrid_data["parties_pct"]["Vox"], 14.03)
        self.assertEqual(madrid_data["parties_pct"]["Sumar"], 15.46)
        self.assertEqual(res.constituency_results["Madrid"].seats["PP"], 16)
        self.assertEqual(res.constituency_results["Madrid"].seats["PSOE"], 11)
        self.assertEqual(res.constituency_results["Madrid"].seats["Vox"], 5)
        self.assertEqual(res.constituency_results["Madrid"].seats["Sumar"], 6)

        # 3. Comprobación exhaustiva en A Coruña (BNG)
        coruna_data = next(c for c in res.constituency_data if c["name"] == "A Coruña")
        coruna_obj = self.model.get_constituency("A Coruña")
        self.assertEqual(coruna_data["valid_votes"], float(coruna_obj["valid_votes"]))
        self.assertEqual(coruna_data["parties_pct"]["BNG"], 9.98)
        self.assertEqual(res.constituency_results["A Coruña"].seats["BNG"], 1)

    def test_compare_exact_23j_consistency(self):
        """Valida que el analizador compare() respete los escaños oficiales del 23J y evalúe la coalición con precisión."""
        poll_23j = dict(BASELINE_NATIONAL_2023)
        comp = self.analyzer.compare(poll_23j, retention_rate=1.0, is_official_23j=True)
        self.assertEqual(comp.separated_left_seats, 31)
        self.assertEqual(comp.separated_result.national_seats["PP"], 136)
        self.assertEqual(comp.separated_result.national_seats["PSOE"], 122)
        self.assertEqual(comp.separated_result.national_seats["Vox"], 33)
        self.assertEqual(comp.separated_result.national_seats["BNG"], 1)

    def test_safe_simulate_with_legacy_model(self):
        """Valida que _safe_simulate capture TypeError de modelos obsoletos sin romper la ejecución."""
        class LegacyModel:
            def simulate(self, national_poll, left_scenario="separated", **kwargs):
                if "is_official_23j" in kwargs or "party_multiplier" in kwargs:
                    raise TypeError("simulate() got an unexpected keyword argument 'is_official_23j'")
                return self_model.simulate(national_poll, left_scenario=left_scenario)

        self_model = self.model
        legacy = LegacyModel()
        legacy_analyzer = CoalitionAnalyzer(legacy)
        poll_23j = dict(BASELINE_NATIONAL_2023)
        # Debe ejecutar sin lanzar TypeError gracias al fallback seguro
        comp = legacy_analyzer.compare(poll_23j, retention_rate=1.0, is_official_23j=True)
        self.assertIsNotNone(comp)
        self.assertGreater(comp.coalition_left_seats, 0)

    def test_adelante_andalucia_exclusion_from_defaults(self):
        """Valida que Adelante Andalucía no esté preseleccionada por defecto en ninguna coalición."""
        # Verificar que en sondeos de referencia Adelante Andalucía esté disponible pero no en defaults de coalición
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]
        self.assertIn("Adelante Andalucía", cis_data)

        # Simular lógica por defecto de app.py Tab 1
        available_parties = list(cis_data.keys())
        default_tab1_coal = [p for p in ["Sumar", "Podemos"] if p in available_parties]
        self.assertNotIn("Adelante Andalucía", default_tab1_coal)
        self.assertEqual(default_tab1_coal, ["Sumar", "Podemos"])

        # Simular lógica por defecto de app.py Tab 2
        cand_names = ["PP", "PSOE", "Vox", "Sumar", "Podemos", "Adelante Andalucía"]
        default_tab2_coal = [p for p in ["Sumar", "Podemos", "Compromís"] if p in cand_names]
        self.assertNotIn("Adelante Andalucía", default_tab2_coal)
        self.assertEqual(default_tab2_coal, ["Sumar", "Podemos"])

    def test_seat_takeovers_accounting(self):
        """Valida la coherencia contable de las transferencias de escaños a favor de la coalición."""
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]
        comp = self.analyzer.compare(cis_data, retention_rate=1.0)
        if comp.seat_difference > 0:
            total_seats_taken = sum(comp.parties_who_lost.values())
            self.assertEqual(total_seats_taken, comp.seat_difference)
            self.assertEqual(len(comp.seat_takeovers), comp.seat_difference)

    def test_national_complex_dual_simulation_and_transfers(self):
        """Valida la simulación dual y cálculo de transferencias en el modelo complejo de la Sección 3."""
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]
        coal_members = ["Sumar", "Podemos"]
        coal_name = "Lista Única"

        sim_sep = self.model.simulate(cis_data, left_scenario="separated")
        sim_coal = self.model.simulate(
            cis_data,
            left_scenario="coalitions",
            default_coalition_members=coal_members,
            default_retention_by_party={"Sumar": 1.0, "Podemos": 1.0},
            custom_coalition_name=coal_name,
        )

        self.assertEqual(sum(sim_sep.national_seats.values()), 350)
        self.assertEqual(sum(sim_coal.national_seats.values()), 350)

        s_sep_blk = sum(sim_sep.national_seats.get(m, 0) for m in coal_members)
        s_coal_blk = sim_coal.national_seats.get(coal_name, 0) + sum(sim_coal.national_seats.get(m, 0) for m in coal_members)
        diff_blk = s_coal_blk - s_sep_blk

        rival_losses = {}
        for p, s_sep in sim_sep.national_seats.items():
            if p in coal_members or p == coal_name:
                continue
            s_coal = sim_coal.national_seats.get(p, 0)
            if s_coal < s_sep:
                rival_losses[p] = s_sep - s_coal

        if diff_blk > 0:
            self.assertEqual(sum(rival_losses.values()), diff_blk)

    def test_dataset_provincial_override_vs_swing(self):
        """Valida que si se cargan datos circunscripción a circunscripción se tomen los votos reales exactos sin proyección swing."""
        cis_data = self.poll_conn.get_poll("CIS (Barómetro de Intención de Voto)")["poll"]
        # Override manual en Madrid con votos reales directos
        real_votes_madrid = {
            "PP": 1_600_000,
            "PSOE": 1_100_000,
            "Vox": 450_000,
            "Sumar": 400_000,
            "Podemos": 180_000,
        }
        overrides = {
            "Madrid": {
                "parties": real_votes_madrid,
                "input_mode": "votes",
            }
        }
        sim = self.model.simulate(cis_data, left_scenario="separated", constituency_overrides=overrides)
        madrid_data = next(c for c in sim.constituency_data if c["name"] == "Madrid")
        
        # Debe tomar exactamente los votos dados en el override sin alteración por swing
        self.assertEqual(madrid_data["raw_parties_votes"]["PP"], 1_600_000)
        self.assertEqual(madrid_data["raw_parties_votes"]["PSOE"], 1_100_000)
        self.assertEqual(madrid_data["raw_parties_votes"]["Sumar"], 400_000)

    def test_government_formation_cross_module(self):
        """Valida la integración cruzada completa del GovernmentOptimizer con encuestas reales."""
        from analysis.government_optimizer import GovernmentOptimizer, GovernmentOptimizationConfig
        optimizer = GovernmentOptimizer(self.model)

        for p_name in ["CIS (Barómetro de Intención de Voto)", "40dB / El País - Cadena SER"]:
            poll = self.poll_conn.get_poll(p_name)["poll"]
            sim_sep = self.model.simulate(poll, left_scenario="separated")
            sim_coal = self.model.simulate(poll, left_scenario="coalitions", custom_coalition_name="Lista Única", coalition_retention_rate=1.0)

            cfg = GovernmentOptimizationConfig(
                target_seats=176,
                government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
                coalition_name="Lista Única",
                allow_abstention=True,
                max_turnout_increase_pct=5.0,
            )
            res = optimizer.optimize(sim_sep, sim_coal, cfg)
            self.assertIsNotNone(res)
            self.assertGreaterEqual(res.initial_bloc_seats, 100)
            if res.coalition_result.target_achieved:
                self.assertGreaterEqual(res.coalition_result.final_bloc_seats, 176)

    def test_parties_with_at_least_3_pct_preserved_across_provinces(self):
        """Valida que cualquier partido con >= 3% en el 23J (ej. BNG en Galicia, CC en Las Palmas) se preserve y proyecte."""
        for p_name in ["CIS (Barómetro de Intención de Voto)", "40dB / El País - Cadena SER"]:
            poll = self.poll_conn.get_poll(p_name)["poll"]
            sim = self.model.simulate(poll, left_scenario="separated")
            
            # Verificar BNG en las 4 provincias gallegas
            for prov in ["A Coruña", "Lugo", "Ourense", "Pontevedra"]:
                c_data = next(c for c in sim.constituency_data if c["name"] == prov)
                self.assertIn("BNG", c_data["raw_parties_votes"], f"BNG falta en {prov}")
                self.assertGreater(c_data["raw_parties_votes"]["BNG"], 10_000, f"Votos BNG insuficientes en {prov}")
                # El porcentaje proyectado debe ser superior al umbral legal del 3%
                bng_pct = (c_data["raw_parties_votes"]["BNG"] / c_data["valid_votes"]) * 100.0
                self.assertGreater(bng_pct, 3.0, f"BNG por debajo del 3% en {prov}")

            # Verificar CC en Las Palmas (6.34% en 23J, 0 escaños)
            lp_data = next(c for c in sim.constituency_data if c["name"] == "Las Palmas")
            self.assertIn("CC", lp_data["raw_parties_votes"], "CC falta en Las Palmas")
            self.assertGreater(lp_data["raw_parties_votes"]["CC"], 10_000)

            # Verificar UPN en Navarra (15.27% en 23J)
            nav_data = next(c for c in sim.constituency_data if c["name"] == "Navarra")
            self.assertIn("UPN", nav_data["raw_parties_votes"], "UPN falta en Navarra")
            self.assertGreater(nav_data["raw_parties_votes"]["UPN"], 20_000)

    def test_electoral_situation_table_dataset(self):
        """Valida la tabla de situación electoral de España (censo y escaños de las 52 circunscripciones)."""
        from app import get_electoral_situation_df
        df = get_electoral_situation_df()
        
        # 1. Dimensiones y completitud
        self.assertEqual(len(df), 52, "Deben existir exactamente 52 circunscripciones")
        self.assertEqual(df["Diputados (Escaños)"].sum(), 350, "La suma de escaños debe ser exactamente 350")
        self.assertGreater(df["Censo Electoral"].sum(), 30_000_000, "El censo total debe superar los 30M")
        
        # 2. Asignaciones demográficas clave (RD 806/2026)
        madrid_row = df[df["Circunscripción"].str.contains("Madrid")].iloc[0]
        self.assertEqual(madrid_row["Diputados (Escaños)"], 38, "Madrid debe tener 38 escaños")
        
        cadiz_row = df[df["Circunscripción"].str.contains("Cádiz")].iloc[0]
        self.assertEqual(cadiz_row["Diputados (Escaños)"], 8, "Cádiz debe tener 8 escaños")
        
        barcelona_row = df[df["Circunscripción"].str.contains("Barcelona")].iloc[0]
        self.assertEqual(barcelona_row["Diputados (Escaños)"], 32, "Barcelona debe tener 32 escaños")
        
        ceuta_row = df[df["Circunscripción"].str.contains("Ceuta")].iloc[0]
        self.assertEqual(ceuta_row["Diputados (Escaños)"], 1, "Ceuta debe tener 1 escaño")
        
        melilla_row = df[df["Circunscripción"].str.contains("Melilla")].iloc[0]
        self.assertEqual(melilla_row["Diputados (Escaños)"], 1, "Melilla debe tener 1 escaño")
        
        # 3. Columnas requeridas y ausencia de nulos (sin las dos columnas de 23J retiradas)
        expected_cols = [
            "Circunscripción", "Comunidad Autónoma", "Diputados (Escaños)",
            "% de la Cámara", "Censo Electoral", "% del Censo Nacional",
            "Electores por Escaño"
        ]
        for col in expected_cols:
            self.assertIn(col, df.columns)
            self.assertEqual(df[col].isnull().sum(), 0)

        # Verificar que las columnas relativas a 23J y participación no figuren en la Hoja 1
        self.assertNotIn("Votos Válidos (23J)", df.columns)
        self.assertNotIn("Participación (%)", df.columns)

        # 4. Verificar variación real y no uniforme de Electores por Escaño
        self.assertGreater(df["Electores por Escaño"].nunique(), 20, "El ratio no puede ser constante para todas las circunscripciones")
        madrid_ratio = df[df["Circunscripción"].str.contains("Madrid")].iloc[0]["Electores por Escaño"]
        soria_ratio = df[df["Circunscripción"].str.contains("Soria")].iloc[0]["Electores por Escaño"]
        teruel_ratio = df[df["Circunscripción"].str.contains("Teruel")].iloc[0]["Electores por Escaño"]
        self.assertGreater(madrid_ratio, 130_000, "Madrid debe superar los 130.000 electores por diputado")
        self.assertLess(soria_ratio, 45_000, "Soria debe situarse por debajo de 45.000 electores por diputado")
        self.assertLess(teruel_ratio, 40_000, "Teruel debe situarse en torno a ~35.000 electores por diputado")

    def test_all_electoral_datasets_and_excel(self):
        """Valida la generación de las 4 hojas Excel base y el libro consolidado multihoja."""
        from app import get_all_electoral_datasets, get_consolidated_electoral_excel
        datasets = get_all_electoral_datasets()
        self.assertEqual(len(datasets), 4)
        self.assertIn("Censo y Escaños Vigentes", datasets)
        self.assertIn("Porcentajes 23J por Circunscripción", datasets)
        self.assertIn("Escaños 23J por Circunscripción", datasets)
        self.assertIn("Catálogo de Sondeos Integrados", datasets)
        
        # Hoja 2 (Porcentajes 23J)
        df_pct = datasets["Porcentajes 23J por Circunscripción"]
        self.assertEqual(len(df_pct), 52)
        self.assertIn("PP", df_pct.columns)
        self.assertIn("PSOE", df_pct.columns)
        self.assertIn("Vox", df_pct.columns)
        self.assertIn("Sumar", df_pct.columns)
        
        # Hoja 3 (Escaños 23J)
        df_seats = datasets["Escaños 23J por Circunscripción"]
        self.assertEqual(len(df_seats), 52)
        self.assertEqual(df_seats["Total Escaños"].sum(), 350)
        
        # Hoja 4 (Sondeos)
        df_polls = datasets["Catálogo de Sondeos Integrados"]
        self.assertGreaterEqual(len(df_polls), 6)
        
        # Libro Excel consolidado
        excel_bytes = get_consolidated_electoral_excel()
        self.assertIsInstance(excel_bytes, bytes)
        self.assertGreater(len(excel_bytes), 5000, "El libro Excel debe tener contenido binario")


    def test_dynamic_turnout_simulation(self):
        """Valida que la modificación interactiva del porcentaje de participación reescale coherentemente los votos."""
        from app import get_poll_turnout

        # 1. Verificar extracción de participación por sondeo
        t_23j = get_poll_turnout("Oficial 23J 2023 (Congreso de los Diputados)")
        t_cis = get_poll_turnout("CIS (Barómetro de Intención de Voto)")
        t_40db = get_poll_turnout("40dB / El País - Cadena SER")
        self.assertAlmostEqual(t_23j, 66.59, places=2)
        self.assertAlmostEqual(t_cis, 68.5, places=1)
        self.assertAlmostEqual(t_40db, self.poll_conn.get_poll("40dB / El País - Cadena SER")["turnout"], places=1)

        poll_info = self.poll_conn.get_poll("Sigma Dos / El Mundo")
        poll_dict = dict(poll_info["poll"])

        # 2. Simulación con participación alta vs baja
        res_high = self.model.simulate(poll_dict, turnout_pct=78.0)
        res_low = self.model.simulate(poll_dict, turnout_pct=58.0)

        tot_valid_high = sum(c["valid_votes"] for c in res_high.constituency_data)
        tot_valid_low = sum(c["valid_votes"] for c in res_low.constituency_data)

        self.assertGreater(tot_valid_high, tot_valid_low, "Mayor participación debe resultar en más votos válidos")
        self.assertAlmostEqual(tot_valid_high / tot_valid_low, 78.0 / 58.0, delta=0.08)

        # 3. Propagación en CoalitionAnalyzer
        comp_high = self.analyzer.compare(poll_dict, turnout_pct=76.0)
        comp_low = self.analyzer.compare(poll_dict, turnout_pct=60.0)

        self.assertGreater(comp_high.separated_left_votes, comp_low.separated_left_votes)
        self.assertGreater(comp_high.coalition_left_votes, comp_low.coalition_left_votes)


if __name__ == "__main__":
    unittest.main()




