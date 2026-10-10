"""
Test unitario y de integración para el módulo GovernmentOptimizer.
Valida el cálculo de mayorías de investidura, restricciones de abstención y trasvases,
selección de provincias y comparativa Lista Única vs. Separados.
"""

import unittest
import sys
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from core.national_model import SpanishElectoralModel, BASELINE_NATIONAL_2023
from analysis.government_optimizer import (
    GovernmentOptimizer,
    GovernmentOptimizationConfig,
    create_government_roadmap_chart,
    render_government_formation_section,
)
from unittest.mock import MagicMock, patch


class TestGovernmentOptimizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = SpanishElectoralModel()
        cls.optimizer = GovernmentOptimizer(cls.model)
        cls.sim_sep = cls.model.simulate(BASELINE_NATIONAL_2023, left_scenario="separated")
        cls.sim_coal = cls.model.simulate(
            BASELINE_NATIONAL_2023,
            left_scenario="coalitions",
            custom_coalition_name="Lista Única",
            coalition_retention_rate=1.0,
        )

    def test_global_optimization_towards_176(self):
        """Prueba que el optimizador global alcanza 176 escaños para el bloque con el mínimo de votos."""
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            allow_abstention=True,
            max_turnout_increase_pct=4.0,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        self.assertGreaterEqual(res.initial_bloc_seats, 150)
        self.assertTrue(res.coalition_result.target_achieved)
        self.assertGreaterEqual(res.coalition_result.final_bloc_seats, 176)
        self.assertGreater(res.coalition_result.total_votes_needed, 0.0)
        self.assertGreater(len(res.coalition_result.steps), 0)

        # Verificar que el gráfico se genera correctamente
        fig = create_government_roadmap_chart(res.coalition_result)
        self.assertIsNotNone(fig)
        self.assertEqual(len(fig.data), 1)

    def test_restricted_provinces_optimization(self):
        """Prueba la optimización restringida a un subconjunto de circunscripciones seleccionadas."""
        andalusian_provinces = ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"]
        cfg = GovernmentOptimizationConfig(
            target_seats=174,  # Meta cercana para asegurar factibilidad dentro de Andalucía
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            target_provinces=andalusian_provinces,
            allow_abstention=True,
            max_turnout_increase_pct=5.0,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        # Todas las provincias en los pasos deben pertenecer a Andalucía
        for step in res.coalition_result.steps:
            self.assertIn(step.province, andalusian_provinces)

    def test_impossible_target_handling(self):
        """Prueba que cuando las restricciones hacen imposible alcanzar la meta, se reporta con elegancia."""
        # Restringir a Soria (2 escaños) con meta de 180 escaños
        cfg = GovernmentOptimizationConfig(
            target_seats=180,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            target_provinces=["Soria"],
            allow_abstention=False,  # Sin abstención y sin donantes
            donor_parties_max_transfer_pct={},
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        self.assertFalse(res.coalition_result.target_achieved)
        self.assertTrue(res.coalition_result.is_impossible)
        self.assertIsNotNone(res.coalition_result.impossibility_reason)
        self.assertIn("Faltan", res.coalition_result.impossibility_reason)

    def test_target_already_achieved(self):
        """Prueba que si el bloque ya cuenta con la mayoría, se requieren 0 votos adicionales."""
        # Incluir al PP como socio teórico para superar ampliamente 176
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "PP"],
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        self.assertTrue(res.coalition_result.target_achieved)
        self.assertEqual(res.coalition_result.total_votes_needed, 0.0)
        self.assertEqual(len(res.coalition_result.steps), 0)

    def test_no_abstention_pure_transfers(self):
        """Prueba que cuando la abstención está deshabilitada, los votos provienen solo de donantes."""
        cfg = GovernmentOptimizationConfig(
            target_seats=174,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            allow_abstention=False,
            donor_parties_max_transfer_pct={"PP": 0.05, "Otros": 0.30},
            shield_partners=True,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        for step in res.coalition_result.steps:
            self.assertNotIn("Abstención", step.votes_source_breakdown)

    def test_national_aggregated_metrics(self):
        """Verifica que las propiedades de métricas agregadas nacionales calculen correctamente los escaños arrebatados y fuentes."""
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            allow_abstention=True,
            max_turnout_increase_pct=4.0,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        c_res = res.coalition_result
        if c_res.steps:
            seats_taken = c_res.national_seats_taken
            sources = c_res.national_sources_breakdown
            self.assertIsInstance(seats_taken, dict)
            self.assertIsInstance(sources, dict)
            self.assertEqual(sum(seats_taken.values()), len(c_res.steps))
            self.assertAlmostEqual(sum(sources.values()), c_res.total_votes_needed, delta=1.0)

    def test_prior_swing_conservation(self):
        """Verifica que el swing previo híbrido mantenga la suma de porcentajes al 100% y respete los límites de censo."""
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            prior_swing_pct={"PP": -1.5, "PSOE": 2.0, "VOX": -0.8},
            prior_swing_abstention_share=0.40,
        )
        # Probamos _apply_prior_swing directamente
        new_sim_sep = self.optimizer._apply_prior_swing(self.sim_sep, cfg)
        self.assertIsNotNone(new_sim_sep)
        # Verificar conservación estricta al 100% a nivel nacional
        tot_nat_pct = sum(new_sim_sep.national_pct_est.values())
        self.assertAlmostEqual(tot_nat_pct, 100.0, places=2, msg="La suma nacional de % no es 100%")

        # Verificar en todas las provincias que no se supera el censo y los % son coherentes con la línea base
        for i, pdata in enumerate(new_sim_sep.constituency_data):
            prov = pdata.get("name")
            tot_pct = sum(pdata["parties_pct"].values())
            orig_tot = sum(self.sim_sep.constituency_data[i]["parties_pct"].values())
            self.assertAlmostEqual(tot_pct, orig_tot, delta=3.0, msg=f"Desviación anómala del % en {prov}")
            self.assertLessEqual(tot_pct, 100.01, msg=f"Suma de % supera 100 en {prov}")
            self.assertLessEqual(pdata["valid_votes"], pdata["census"])

    def test_optimizable_partners_assignment(self):
        """Verifica que socios optimizables puedan recibir escaños tácticamente si son la vía más eficiente."""
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            optimizable_partners=["PSOE"],
            allow_abstention=True,
            max_turnout_increase_pct=5.0,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        self.assertTrue(res.coalition_result.target_achieved)
        # Comprobar que en coalition_result los pasos pueden beneficiar tanto a Lista Única como a PSOE
        beneficiaries = {s.beneficiary_party for s in res.coalition_result.steps}
        self.assertTrue(beneficiaries.issubset({"Lista Única", "PSOE"}))

    def test_party_porosity_specific(self):
        """Verifica que la porosidad específica partido a partido limite los donantes de cada fuerza."""
        cfg = GovernmentOptimizationConfig(
            target_seats=175,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            allow_abstention=False,
            party_porosity={
                "Lista Única": {"PP": 0.05},  # Solo puede recibir de PP
            },
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        for step in res.coalition_result.steps:
            if step.beneficiary_party == "Lista Única":
                donors = [k for k in step.votes_source_breakdown if k != "Abstención"]
                for d in donors:
                    self.assertEqual(d, "PP")

    def test_max_party_growth_cap(self):
        """Verifica que el tope de crecimiento impida que una fuerza supere el % de crecimiento fijado en la provincia."""
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            max_party_growth_pct={"Lista Única": 25.0},  # Máximo +25% de crecimiento en cualquier provincia
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        # Verificar que en cada paso de Lista Única, los votos requeridos no superen el 25% del voto base
        for step in res.coalition_result.steps:
            if step.beneficiary_party == "Lista Única":
                c_data = next(c for c in self.sim_coal.constituency_data if c["name"] == step.province)
                base_v = c_data["parties_votes"].get("Lista Única", 0.0)
                if base_v > 0:
                    self.assertLessEqual(step.votes_needed, base_v * 0.25 + 1.0)

    def test_national_simulation_result_aliases(self):
        """Verifica que las propiedades alias national_votes, national_pct y model.parties funcionan."""
        self.assertIsInstance(self.sim_sep.national_votes, dict)
        self.assertIsInstance(self.sim_sep.national_pct, dict)
        self.assertGreater(len(self.sim_sep.national_votes), 0)
        self.assertGreater(len(self.model.parties), 5)
        self.assertIn("PSOE", self.model.parties)
        self.assertIn("PP", self.model.parties)

    @patch("analysis.government_optimizer.st", create=True)
    def test_render_government_formation_section_execution(self, mock_st):
        """Verifica la ejecución completa de la sección de Streamlit sin errores de atributos ni claves duplicadas."""
        mock_container = MagicMock()
        mock_st.container.return_value.__enter__.return_value = mock_container
        mock_st.expander.return_value.__enter__.return_value = MagicMock()
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.tabs.side_effect = lambda tabs: [MagicMock() for _ in tabs]
        mock_st.radio.return_value = "🌍 Toda España (Búsqueda del óptimo global absoluto entre las 52 circunscripciones)"
        mock_st.multiselect.side_effect = lambda label, options, **kwargs: kwargs.get("default", options[:2] if options else [])
        mock_st.number_input.return_value = 176
        mock_st.checkbox.return_value = True
        mock_st.slider.side_effect = lambda label, *args, **kwargs: 80.0 if "Crecimiento" in label else kwargs.get("value", 4.0)

        # Ejecutar con ERC dentro de la coalición para validar exclusión de dobles cuentas
        render_government_formation_section(
            model=self.model,
            sim_sep=self.sim_sep,
            sim_coal=self.sim_coal,
            section_key="test_section",
            coalition_name="Lista Progresista",
            coalition_members=["Sumar", "Podemos", "ERC"],
            default_target=176,
        )

        # Validar que plotly_chart se llamó y con claves únicas
        plotly_calls = mock_st.plotly_chart.call_args_list
        self.assertGreaterEqual(len(plotly_calls), 1)
        used_keys = [call.kwargs.get("key") for call in plotly_calls]
        self.assertEqual(len(used_keys), len(set(used_keys)))  # Sin claves duplicadas
        for k in used_keys:
            self.assertTrue(k.startswith("test_section_gov_"))

    @patch("analysis.government_optimizer.st", create=True)
    def test_render_government_formation_section_with_selected_provinces_and_ccaa(self, mock_st):
        """Verifica la ejecución del selector territorial con 19 CCAA por defecto y sincronización reactiva."""
        mock_container = MagicMock()
        mock_st.container.return_value.__enter__.return_value = mock_container
        mock_st.expander.return_value.__enter__.return_value = MagicMock()
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.tabs.side_effect = lambda tabs: [MagicMock() for _ in tabs]
        
        # Simular sesión de Streamlit
        session_dict = {}
        mock_st.session_state = session_dict

        mock_st.radio.side_effect = lambda label, *args, **kwargs: (
            "🎯 Seleccionar circunscripciones específicas de campaña"
            if "Ámbito territorial" in label
            else "📊 Puntos % Provinciales (Δ% prov) — Minimiza el desplazamiento en el electorado provincial (neutraliza el sesgo de provincias pequeñas)"
        )
        mock_st.multiselect.side_effect = lambda label, options, **kwargs: kwargs.get("default", options if options else [])
        mock_st.number_input.return_value = 176
        mock_st.checkbox.return_value = True
        mock_st.slider.side_effect = lambda label, *args, **kwargs: 80.0 if "Crecimiento" in label else kwargs.get("value", 4.0)

        render_government_formation_section(
            model=self.model,
            sim_sep=self.sim_sep,
            sim_coal=self.sim_coal,
            section_key="test_territorial_section",
            coalition_name="Lista Unitaria",
            coalition_members=["Sumar", "Podemos"],
            default_target=176,
        )

        # Verificar que el multiselector provincial fue poblado por defecto con las 52 provincias
        prov_key = "test_territorial_section_gov_selected_provs"
        self.assertIn(prov_key, session_dict)
        self.assertEqual(len(session_dict[prov_key]), 52)

        # Verificar que las 19 CCAA fueron inicializadas como True
        from core.toponyms import CCAA_PROVINCES
        self.assertEqual(len(CCAA_PROVINCES), 19)
        for c_name in CCAA_PROVINCES.keys():
            self.assertTrue(session_dict.get(f"test_territorial_section_zone_{c_name}", False))

        plotly_calls = mock_st.plotly_chart.call_args_list
        self.assertGreaterEqual(len(plotly_calls), 1)

    def test_post_optimization_summary_and_charts(self):
        """Verifica que los datos y gráficos post-optimización a nivel nacional y provincial se generen correctamente."""
        from analysis.government_optimizer import (
            create_government_national_scenario_chart,
            create_government_national_comparison_chart,
        )
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            allow_abstention=True,
            max_turnout_increase_pct=4.0,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        # Verificar datos agregados nacionales y provinciales
        c_res = res.coalition_result
        self.assertGreater(len(c_res.final_national_seats), 0)
        self.assertEqual(sum(c_res.final_national_seats.values()), 350)
        self.assertEqual(sum(c_res.initial_national_seats.values()), 350)
        self.assertEqual(len(c_res.final_constituency_data), 52)
        self.assertGreater(c_res.initial_pact_votes, 0)
        self.assertGreater(c_res.final_pact_votes, 0)
        self.assertGreaterEqual(c_res.final_pact_votes, c_res.initial_pact_votes)

        # Verificar gráficos del Congreso
        fig_scen = create_government_national_scenario_chart(c_res)
        self.assertIsNotNone(fig_scen)
        self.assertGreaterEqual(len(fig_scen.data), 1)

        fig_comp = create_government_national_comparison_chart(res.coalition_result, res.separated_result)
        self.assertIsNotNone(fig_comp)
        self.assertEqual(len(fig_comp.data), 2)  # Una traza para Lista Única y otra para Separados

        # Verificar que el gráfico de ruta tiene colores por beneficiario
        fig_road = create_government_roadmap_chart(c_res)
        self.assertIsNotNone(fig_road)
        # La propiedad marker.color debe ser una lista de colores correspondientes a los beneficiarios
        bar_colors = fig_road.data[0].marker.color
        self.assertEqual(len(bar_colors), len(c_res.steps))

    def test_turnout_strictly_non_decreasing(self):
        """Verifica que la participación nunca disminuya en ningún paso de la optimización (con o sin abstención)."""
        # Caso 1: Con abstención permitida
        cfg_abst = GovernmentOptimizationConfig(
            target_seats=176,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            allow_abstention=True,
            max_turnout_increase_pct=4.0,
        )
        res_abst = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg_abst)
        for step in res_abst.coalition_result.steps:
            self.assertGreaterEqual(
                step.final_turnout_pct,
                step.initial_turnout_pct,
                msg=f"La participación bajó en {step.province}: {step.initial_turnout_pct} -> {step.final_turnout_pct}"
            )

        # Caso 2: Sin abstención (solo trasvases de otros partidos, participación estrictamente idéntica)
        cfg_no_abst = GovernmentOptimizationConfig(
            target_seats=174,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            allow_abstention=False,
            donor_parties_max_transfer_pct={"PP": 0.05, "Otros": 0.30},
        )
        res_no_abst = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg_no_abst)
        for step in res_no_abst.coalition_result.steps:
            self.assertAlmostEqual(
                step.final_turnout_pct,
                step.initial_turnout_pct,
                places=2,
                msg=f"La participación varió sin abstención en {step.province}: {step.initial_turnout_pct} vs {step.final_turnout_pct}"
            )

    def test_impossible_ceiling_and_pact_external_sources(self):
        """Valida que si se alcanza el techo de optimización, national_pct_increase sea > 0 y los socios se aíslen."""
        cfg_ceiling = GovernmentOptimizationConfig(
            target_seats=180,
            target_provinces=["Madrid"],
            optimizable_partners=["PSOE"],
            donor_parties_max_transfer_pct={"PP": 0.05, "Vox": 0.02},
            max_party_growth_pct={"PSOE": 5.0},
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg_ceiling)
        for label, scenario_res in [("Coalición", res.coalition_result), ("Separados", res.separated_result)]:
            self.assertFalse(scenario_res.target_achieved, f"{label} no debió alcanzar 180 escaños solo en Madrid")
            self.assertTrue(scenario_res.is_impossible, f"{label} debió marcarse como imposible")
            self.assertGreater(scenario_res.seats_gained, 0, f"{label} debió sumar al menos 1 escaño antes del techo")
            self.assertGreater(scenario_res.total_votes_needed, 0.0, f"{label} debe requerir votos acumulados")
            self.assertGreater(scenario_res.national_pct_increase, 0.0, f"{label} national_pct_increase no puede ser 0.00%")
            
            # Verificar aislamiento estricto de socios del pacto en fuentes externas
            all_pact = set(cfg_ceiling.government_partners) | set(cfg_ceiling.coalition_members) | {cfg_ceiling.coalition_name}
            pact_ext = scenario_res.pact_external_sources(all_pact)
            for partner in all_pact:
                self.assertNotIn(partner, pact_ext, f"El socio {partner} no puede figurar como fuente externa del pacto")

            # Verificar que los steps registren crecimiento y votos
            for step in scenario_res.steps:
                self.assertGreaterEqual(step.beneficiary_growth_pct, 0.0)
                self.assertGreater(step.beneficiary_final_votes, 0.0)

    def test_multi_criteria_and_geometric_hybrid_optimization(self):
        """Valida que los 4 criterios de optimización (incluyendo híbrido Cobb-Douglas) funcionen correctamente."""
        for crit in ["absolute_votes", "provincial_pct", "party_growth_pct", "hybrid"]:
            cfg = GovernmentOptimizationConfig(
                target_seats=178,
                optimizable_partners=["PSOE"],
                optimization_criterion=crit,
                hybrid_alpha=0.50,
            )
            res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
            
            for scen_label, s_res in [("Coalición", res.coalition_result), ("Separados", res.separated_result)]:
                self.assertEqual(s_res.optimization_criterion, crit)
                self.assertEqual(s_res.hybrid_alpha, 0.50)
                self.assertGreater(len(s_res.steps), 0, f"{scen_label} debe generar pasos para alcanzar 178 escaños")
                
                for step in s_res.steps:
                    self.assertGreater(step.votes_needed, 0)
                    self.assertGreater(step.provincial_vote_shift_pct, 0.0)
                    self.assertGreater(step.marginal_cost, 0.0)

        # Validar extremos del híbrido (alpha=0.0 equivalente a provincial, alpha=1.0 equivalente a partido)
        cfg_alpha0 = GovernmentOptimizationConfig(target_seats=178, optimizable_partners=["PSOE"], optimization_criterion="hybrid", hybrid_alpha=0.0)
        res_alpha0 = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg_alpha0)
        cfg_prov = GovernmentOptimizationConfig(target_seats=178, optimizable_partners=["PSOE"], optimization_criterion="provincial_pct")
        res_prov = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg_prov)

        # La secuencia de provincias con alpha=0 debe coincidir con el criterio provincial puro
        steps_alpha0 = [s.province for s in res_alpha0.coalition_result.steps]
        steps_prov = [s.province for s in res_prov.coalition_result.steps]
        self.assertEqual(steps_alpha0, steps_prov)

    @patch("analysis.government_optimizer.st", create=True)
    def test_dynamic_inheritance_of_custom_coalition_members(self, mock_st):
        """Verifica que el optimizador herede dinámicamente cualquier lista única sin prefijar Sumar y Podemos."""
        mock_container = MagicMock()
        mock_st.container.return_value.__enter__.return_value = mock_container
        mock_st.expander.return_value.__enter__.return_value = MagicMock()
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.tabs.side_effect = lambda tabs: [MagicMock() for _ in tabs]
        
        session_dict = {
            "test_dyn_gov_partners": ["PSOE", "ERC", "EH Bildu", "BNG"],
            "test_dyn_gov_cap_parties_selected": ["Lista Única", "Sumar", "Podemos"],
            "test_dyn_gov_por_parties_selected": ["Lista Única", "Sumar", "Podemos"],
        }
        mock_st.session_state = session_dict

        mock_st.radio.return_value = "🌍 Toda España (Búsqueda del óptimo global absoluto entre las 52 circunscripciones)"
        mock_st.multiselect.side_effect = lambda label, options, **kwargs: kwargs.get("default", options)
        mock_st.number_input.return_value = 176
        mock_st.checkbox.return_value = True
        mock_st.slider.return_value = 80.0

        # Simular una coalición personalizada distinta de Sumar+Podemos: PSOE + BNG
        custom_members = ["PSOE", "BNG"]
        custom_name = "Frente Democrático"

        render_government_formation_section(
            model=self.model,
            sim_sep=self.sim_sep,
            sim_coal=self.sim_coal,
            section_key="test_dyn",
            coalition_name=custom_name,
            coalition_members=custom_members,
            default_target=176,
        )

        # 1. Verificar que los socios externos NO contengan a los nuevos integrantes de la coalición (PSOE ni BNG)
        external_partners = session_dict.get("test_dyn_gov_partners", [])
        self.assertNotIn("PSOE", external_partners)
        self.assertNotIn("BNG", external_partners)

        # 2. Verificar que los partidos con tope y caladeros hereden los nuevos integrantes
        caps_selected = session_dict.get("test_dyn_gov_cap_parties_selected", [])
        self.assertIn("Frente Democrático", caps_selected)
        self.assertIn("PSOE", caps_selected)
        self.assertIn("BNG", caps_selected)

        # 3. Verificar que GovernmentOptimizer soporte la configuración personalizada
        cfg = GovernmentOptimizationConfig(
            target_seats=176,
            coalition_members=custom_members,
            coalition_name=custom_name,
            government_partners=["ERC", "EH Bildu"],
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        self.assertIn("Frente Democrático", res.coalition_result.scenario_label)
        self.assertIn("PSOE", res.separated_result.scenario_label)
    def test_acyclic_and_non_cannibalistic_transfers(self):
        """
        Valida que el optimizador impida transferencias circulares o canibalización mutua:
        - Si dos candidaturas del bloque suman escaños en la misma provincia, no se quitan votos entre sí.
        - Ningún partido que reciba votos/escaños en una provincia actúa como donante en esa provincia.
        - No existen pares circulares A ➔ B y B ➔ A en las transferencias internas netas.
        """
        cfg = GovernmentOptimizationConfig(
            target_seats=178,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            optimizable_partners=["PSOE"],
            shield_partners=False,  # Desactivar blindaje para forzar que las reglas anti-circularidad operen
            allow_abstention=True,
            party_porosity={
                "Lista Única": {"PSOE": 0.10, "PP": 0.04},
                "PSOE": {"Lista Única": 0.10, "PP": 0.04},
            },
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
        c_res = res.coalition_result

        # 1. Comprobar que en ninguna provincia existe transferencia circular A -> B y B -> A
        prov_pairwise: dict = {}
        for step in c_res.steps:
            p = step.province
            benef = step.beneficiary_party
            for don, v in step.votes_source_breakdown.items():
                if v > 0 and don != "Abstención":
                    if p not in prov_pairwise:
                        prov_pairwise[p] = set()
                    # Si A -> B ya ocurrió en la provincia p, B -> A está prohibido
                    self.assertNotIn((benef, don), prov_pairwise[p], f"Transferencia circular detectada en {p}: {don} -> {benef} tras haber ocurrido {benef} -> {don}")
                    prov_pairwise[p].add((don, benef))

        # 2. Comprobar que en provincias donde ambos suman escaños, no se canibalizan entre sí
        prov_beneficiaries: dict = {}
        for step in c_res.steps:
            prov_beneficiaries.setdefault(step.province, set()).add(step.beneficiary_party)

        multi_benef_provs = {p: b_set for p, b_set in prov_beneficiaries.items() if len(b_set) > 1}
        for cdata in c_res.final_constituency_data:
            prov = cdata["province"]
            if prov in multi_benef_provs:
                p_sources = cdata.get("party_sources", {})
                # Si tanto Lista Única como PSOE ganan escaño en esta provincia, no deben nutrirse el uno del otro
                if "Lista Única" in p_sources and "PSOE" in p_sources:
                    self.assertEqual(p_sources["Lista Única"].get("PSOE", 0.0), 0.0, f"Lista Única tomó votos de PSOE en {prov} pese a que ambos sumaban escaños")
                    self.assertEqual(p_sources["PSOE"].get("Lista Única", 0.0), 0.0, f"PSOE tomó votos de Lista Única en {prov} pese a que ambos sumaban escaños")

        # 3. Validar consolidación neta en pact_internal_transfers
        pact_parties = {"Lista Única", "PSOE", "ERC", "EH Bildu", "PNV", "BNG"}
        internal_transfers = c_res.pact_internal_transfers(pact_parties)
        for key in internal_transfers:
            src, dst = [x.strip() for x in key.split("➔")]
            rev_key = f"{dst} ➔ {src}"
            self.assertNotIn(rev_key, internal_transfers, f"Par circular detectado en reporte de transferencias internas: {key} y {rev_key}")

    def test_strict_no_seat_loss_in_bloc(self):
        """
        Verifica formalmente el principio fundamental:
        - Ningún integrante del bloque de investidura (PSOE, Lista Única, Sumar, Podemos, socios)
          puede perder un solo escaño en ninguna circunscripción como efecto secundario de la optimización.
        - Todos los escaños arrebatados provienen estrictamente de la oposición externa (PP, Vox, etc.).
        - Ningún escaño marginal optimizado es erosionado en iteraciones posteriores.
        """
        for opt_p in [[], ["PSOE"]]:
            cfg = GovernmentOptimizationConfig(
                target_seats=178,
                government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
                coalition_name="Lista Única",
                optimizable_partners=opt_p,
                shield_partners=False,
                party_porosity={
                    "Lista Única": {"PP": 0.05, "Otros": 0.20, "PSOE": 0.10},
                    "PSOE": {"PP": 0.05, "Otros": 0.20, "Lista Única": 0.10},
                },
            )
            res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)
            for sc_name, sc_res in [("Coalición", res.coalition_result), ("Separados", res.separated_result)]:
                all_bloc = set(cfg.government_partners) | set(sc_res.steps[0].beneficiary_party if sc_res.steps else set())
                all_bloc.update(cfg.coalition_members)
                all_bloc.add(cfg.coalition_name)

                # Verificar que cada paso arrebató el escaño a un rival externo
                for s in sc_res.steps:
                    self.assertNotIn(
                        s.seat_taken_from,
                        all_bloc,
                        f"En {s.province}, el escaño ganado por {s.beneficiary_party} se arrebató al aliado {s.seat_taken_from}"
                    )

                # Verificar en cada circunscripción que ningún socio perdió escaños respecto al punto de partida
                for cdata in sc_res.final_constituency_data:
                    prov = cdata["province"]
                    for p in all_bloc:
                        init_s = cdata["initial_seats"].get(p, 0)
                        fin_s = cdata["final_seats"].get(p, 0)
                        self.assertGreaterEqual(
                            fin_s,
                            init_s,
                            f"En {prov}, el socio/candidatura {p} perdió escaños: tenía {init_s} y terminó con {fin_s}"
                        )

    def test_post_optimization_provincial_recalibration(self):
        """
        Verifica la recalibración de cierre provincial (post-optimization pass):
        - En provincias con múltiples escaños ganados (ej. Madrid), el vector simultáneo
          certifica conjuntamente todos los escaños en D'Hondt desde V_0.
        - La suma de los votos de los pasos coincide exactamente con sc_res.total_votes_needed.
        - Los desgloses de fuentes de votos y donaciones son consistentes con la asignación final.
        - Se preservan estrictamente los escaños de todos los socios del bloque.
        """
        cfg = GovernmentOptimizationConfig(
            target_seats=178,
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            coalition_name="Lista Única",
            optimizable_partners=["PSOE"],
            shield_partners=True,
        )
        res = self.optimizer.optimize(self.sim_sep, self.sim_coal, cfg)

        for sc_name, sc_res in [("Coalición", res.coalition_result), ("Separados", res.separated_result)]:
            if not sc_res.steps:
                continue

            # 1. Coherencia de suma total
            step_sum = sum(s.votes_needed for s in sc_res.steps)
            self.assertEqual(
                round(sc_res.total_votes_needed, 0),
                round(step_sum, 0),
                f"En {sc_name}, total_votes_needed ({sc_res.total_votes_needed}) no coincide con suma de pasos ({step_sum})"
            )

            # 2. Agrupar pasos por provincia
            prov_steps = {}
            for s in sc_res.steps:
                prov_steps.setdefault(s.province, []).append(s)

            all_bloc = set(cfg.government_partners) | {cfg.coalition_name} | set(cfg.coalition_members)

            for prov_name, p_steps in prov_steps.items():
                cdata = next((c for c in sc_res.final_constituency_data if c["province"] == prov_name), None)
                self.assertIsNotNone(cdata, f"Provincia {prov_name} no encontrada en final_constituency_data")

                # Comprobar que ningún socio del bloque perdió escaños respecto al punto de partida
                for p in all_bloc:
                    init_s = cdata["initial_seats"].get(p, 0)
                    fin_s = cdata["final_seats"].get(p, 0)
                    self.assertGreaterEqual(
                        fin_s,
                        init_s,
                        f"En {prov_name}, {p} perdió escaños tras la recalibración: {init_s} -> {fin_s}"
                    )

                # Comprobar que los beneficiarios alcanzaron al menos los escaños previstos
                for s in p_steps:
                    self.assertGreater(s.votes_needed, 0, f"Paso en {prov_name} tiene votos needed <= 0")
                    # Fuentes no vacías si votes_needed > 0
                    self.assertTrue(len(s.votes_source_breakdown) > 0, f"Paso en {prov_name} sin desglose de fuentes")
                    sources_sum = sum(s.votes_source_breakdown.values())
                    self.assertAlmostEqual(
                        sources_sum,
                        s.votes_needed,
                        delta=2.0,
                        msg=f"En {prov_name}, la suma de fuentes ({sources_sum}) no coincide con votes_needed ({s.votes_needed})"
                    )

    def test_multi_seat_province_chart_differentiation(self):
        """Verifica que si una provincia tiene dos o más escaños en la optimización, cada uno tenga su propia categoría en Y sin superposición."""
        from analysis.government_optimizer import ProvinceOptimizationStep, GovernmentScenarioResult

        # Crear escenario simulado con 3 escaños en Madrid y 1 en Toledo
        steps = [
            ProvinceOptimizationStep(
                province="Madrid",
                display_name="Madrid",
                community="Comunidad de Madrid",
                seats_in_province=37,
                seat_order=1,
                votes_needed=15000.0,
                beneficiary_party="PSOE",
                seat_taken_from="PP",
                initial_seats_bloc=10,
                final_seats_bloc=11,
                votes_source_breakdown={"Abstención": 15000.0},
                initial_turnout_pct=70.0,
                final_turnout_pct=70.5,
                initial_bloc_pct=35.0,
                final_bloc_pct=35.5,
            ),
            ProvinceOptimizationStep(
                province="Toledo",
                display_name="Toledo",
                community="Castilla-La Mancha",
                seats_in_province=6,
                seat_order=2,
                votes_needed=8000.0,
                beneficiary_party="PSOE",
                seat_taken_from="Vox",
                initial_seats_bloc=2,
                final_seats_bloc=3,
                votes_source_breakdown={"Abstención": 8000.0},
                initial_turnout_pct=72.0,
                final_turnout_pct=72.8,
                initial_bloc_pct=33.0,
                final_bloc_pct=34.2,
            ),
            ProvinceOptimizationStep(
                province="Madrid",
                display_name="Madrid",
                community="Comunidad de Madrid",
                seats_in_province=37,
                seat_order=3,
                votes_needed=35000.0,
                beneficiary_party="Lista Única",
                seat_taken_from="PP",
                initial_seats_bloc=11,
                final_seats_bloc=12,
                votes_source_breakdown={"Abstención": 20000.0, "PP": 15000.0},
                initial_turnout_pct=70.5,
                final_turnout_pct=71.2,
                initial_bloc_pct=35.5,
                final_bloc_pct=36.2,
            ),
            ProvinceOptimizationStep(
                province="Madrid",
                display_name="Madrid",
                community="Comunidad de Madrid",
                seats_in_province=37,
                seat_order=4,
                votes_needed=42000.0,
                beneficiary_party="PSOE",
                seat_taken_from="Vox",
                initial_seats_bloc=12,
                final_seats_bloc=13,
                votes_source_breakdown={"Abstención": 42000.0},
                initial_turnout_pct=71.2,
                final_turnout_pct=72.0,
                initial_bloc_pct=36.2,
                final_bloc_pct=37.0,
            ),
        ]

        scenario_res = GovernmentScenarioResult(
            scenario_type="coalition",
            scenario_label="🟣 Con Lista Única",
            target_seats=176,
            initial_bloc_seats=172,
            final_bloc_seats=176,
            seats_gained=4,
            target_achieved=True,
            total_votes_needed=100000.0,
            national_pct_increase=0.45,
            steps=steps,
            provinces_involved=["Madrid", "Toledo"],
        )

        fig = create_government_roadmap_chart(scenario_res)
        self.assertIsNotNone(fig)
        self.assertEqual(len(fig.data), 1)

        y_vals = list(fig.data[0].y)
        # Todos los valores en Y deben ser estrictamente únicos para evitar solapamiento en Plotly
        self.assertEqual(len(y_vals), len(set(y_vals)), "Los valores del eje Y deben ser únicos para evitar solapamientos")
        self.assertEqual(len(y_vals), len(steps), "Debe haber una barra por cada paso de optimización")

        # Comprobar ordinales en Madrid y nombre limpio en Toledo
        self.assertTrue(any("Madrid (1er escaño)" in y for y in y_vals))
        self.assertTrue(any("Madrid (2º escaño)" in y for y in y_vals))
        self.assertTrue(any("Madrid (3er escaño)" in y for y in y_vals))
        self.assertTrue("Toledo" in y_vals)

    def test_step_beneficiary_growth_pct_consistency(self):
        """Valida que beneficiary_growth_pct en cada paso corresponda al incremento marginal de ese escaño y no al acumulado."""
        from data.poll_connector import BENCHMARK_POLLS
        poll_data = BENCHMARK_POLLS["ElectoPanel / Electomanía"]["poll"]
        sim_sep = self.model.simulate(poll_data, left_scenario="separated")
        sim_coal = self.model.simulate(poll_data, left_scenario="coalitions", custom_coalition_name="Lista Única", coalition_retention_rate=1.0)
        
        cfg = GovernmentOptimizationConfig(
            target_seats=180,
            coalition_name="Lista Única",
            government_partners=["PSOE", "ERC", "EH Bildu", "PNV", "BNG"],
            target_provinces=["Madrid"],
        )
        res = self.optimizer.optimize(sim_sep, sim_coal, cfg)
        madrid_steps = [s for s in res.coalition_result.steps if s.province == "Madrid"]
        self.assertGreaterEqual(len(madrid_steps), 2, "Debe haber múltiples escaños optimizados en Madrid")

        for s in madrid_steps:
            # 1. beneficiary_growth_pct debe basarse en los votos de ESE paso concreto
            expected_step_growth = round((s.votes_needed / s.beneficiary_initial_votes) * 100.0, 2)
            self.assertAlmostEqual(s.beneficiary_growth_pct, expected_step_growth, places=2)

            # 2. La relación (provincial_shift / beneficiary_growth) debe coincidir con el % inicial de votos del partido
            # (prov_shift / party_growth) = (step_votes / valid_votes) / (step_votes / party_init_votes) = party_init_votes / valid_votes
            if s.beneficiary_growth_pct > 0:
                implied_party_share = (s.provincial_vote_shift_pct / s.beneficiary_growth_pct) * 100.0
                # En Madrid con ElectoPanel, Lista Única tiene ~12% de los votos
                self.assertGreater(implied_party_share, 10.0, "El porcentaje inicial deducido no debe colapsar a ~0.4%")
                self.assertLess(implied_party_share, 15.0)

            # 3. beneficiary_cumulative_growth_pct debe ser mayor o igual que beneficiary_growth_pct
            self.assertGreaterEqual(s.beneficiary_cumulative_growth_pct, s.beneficiary_growth_pct)

        # 4. El último paso debe tener un crecimiento acumulado estrictamente mayor que el primer paso
        self.assertGreater(madrid_steps[-1].beneficiary_cumulative_growth_pct, madrid_steps[0].beneficiary_growth_pct)


if __name__ == "__main__":
    unittest.main()


