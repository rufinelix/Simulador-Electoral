"""
Módulo de Optimización de Gobernabilidad y Mayorías de Investidura.
Calcula el número mínimo de votos adicionales necesarios para que las fuerzas de
la coalición (en formato Lista Única o Por Separado) alcancen la mayoría absoluta
(176 escaños) o un objetivo personalizado junto a sus socios de investidura.

Permite:
- Modelar de qué caladeros proceden los votos:
  * Movilización de la abstención (con tope de participación y cota física del censo).
  * Trasvases desde partidos donantes seleccionados (con tasa máxima de porosidad).
  * Blindaje estricto de socios de gobierno (evita canibalización del bloque).
- Optimización global (52 circunscripciones) o restringida a provincias diana.
- Hoja de ruta de campaña detallada: orden de prioridad, provincia, votos, rival que pierde el escaño y nueva participación.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import Counter
import copy
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

try:
    from core.dhondt import calculate_dhondt, ConstituencyResult
    from core.national_model import NationalSimulationResult, SpanishElectoralModel
    from core.toponyms import (
        normalize_province_name,
        get_province_display_name,
        are_same_province,
        CCAA_PROVINCES,
    )
    from core.stepped_chart import get_party_color
except ImportError:
    from ..core.dhondt import calculate_dhondt, ConstituencyResult
    from ..core.national_model import NationalSimulationResult, SpanishElectoralModel
    from ..core.toponyms import (
        normalize_province_name,
        get_province_display_name,
        are_same_province,
        CCAA_PROVINCES,
    )
    try:
        from ..core.stepped_chart import get_party_color
    except ImportError:
        def get_party_color(name: str) -> str:
            return "#475569"

try:
    from core.i18n import t, get_current_lang
except ImportError:
    try:
        from ..core.i18n import t, get_current_lang
    except ImportError:
        def t(key: str, default: Optional[str] = None, **kwargs) -> str:
            return default if default is not None else key
        def get_current_lang() -> str:
            return "es"


DEFAULT_GOVERNMENT_PARTNERS = ["PSOE", "ERC", "EH Bildu", "PNV", "BNG"]


@dataclass
class GovernmentOptimizationConfig:
    target_seats: int = 176
    coalition_members: List[str] = field(default_factory=lambda: ["Sumar", "Podemos"])
    coalition_name: str = "Lista Única"
    government_partners: List[str] = field(default_factory=lambda: list(DEFAULT_GOVERNMENT_PARTNERS))
    target_provinces: Optional[List[str]] = None  # None o [] = Todas las 52 provincias
    
    # Restricciones de abstención
    allow_abstention: bool = True
    max_turnout_increase_pct: float = 4.0  # Máximo incremento de participación en puntos %
    
    # Restricciones de trasvase por partido (% máximo de cesión sobre sus votos en cada provincia)
    donor_parties_max_transfer_pct: Dict[str, float] = field(default_factory=lambda: {
        "Otros": 0.30,
        "PP": 0.04,
        "SALF": 0.05,
        "Vox": 0.0,
    })
    
    # Blindaje de socios
    shield_partners: bool = True
    threshold_pct: float = 3.0

    # Desacople: socios adicionales autorizados a recibir votos en campaña (por defecto vacio = congelados)
    optimizable_partners: List[str] = field(default_factory=list)

    # Modulador de swing previo opcional por partido (puntos %): ej {"PSOE": 1.0}
    prior_swing_pct: Dict[str, float] = field(default_factory=dict)

    # Proporción de procedencia del swing previo (de 0.0 a 1.0): 1.0 = 100% abstención, 0.0 = 100% trasvases
    prior_swing_abstention_share: float = 0.50

    # Porosidad específica partido a partido: Dict[beneficiario, Dict[donante, max_transfer_pct]]
    # Permite fijar de qué partidos concretos capta votos cada candidatura (ej. PSOE capta de Sumar, Sumar capta de Podemos o PP).
    # Independencia estricta entre escenarios:
    # - La clave de 'coalition_name' (Lista Única) solo aplica al escenario con Lista Única.
    # - Las claves de integrantes separados ('Sumar', 'Podemos') solo aplican al escenario Por Separado.
    # - Las claves de socios comunes ('PSOE') aplican a su candidatura en ambos escenarios.
    # Modificar los caladeros de un escenario no afecta ni contamina al otro.
    party_porosity: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Tope de crecimiento máximo en votos por circunscripción (% sobre sus votos base en esa provincia)
    # ej: {"Podemos": 50.0} impide que Podemos sume más del 50% de sus votos base en una provincia (evita duplicar o triplicar irrealistamente)
    max_party_growth_pct: Dict[str, float] = field(default_factory=dict)
    default_max_party_growth_pct: float = 80.0

    # Criterio de eficiencia y optimización de campaña
    # "absolute_votes": Mínimo de votos brutos absolutos (ΔV)
    # "provincial_pct": Mínimo salto en puntos porcentuales del electorado provincial (Δ% prov)
    # "party_growth_pct": Mínimo porcentaje de crecimiento de la propia candidatura (Δ% partido)
    # "hybrid": Media geométrica ponderada entre Δ% prov y Δ% partido con parámetro alpha
    optimization_criterion: str = "absolute_votes"
    hybrid_alpha: float = 0.50


@dataclass
class ProvinceOptimizationStep:
    province: str
    display_name: str
    community: str
    seats_in_province: int
    seat_order: int
    votes_needed: float
    beneficiary_party: str
    seat_taken_from: Optional[str]
    initial_seats_bloc: int
    final_seats_bloc: int
    votes_source_breakdown: Dict[str, float]
    initial_turnout_pct: float
    final_turnout_pct: float
    initial_bloc_pct: float
    final_bloc_pct: float
    beneficiary_growth_pct: float = 0.0
    beneficiary_initial_votes: float = 0.0
    beneficiary_final_votes: float = 0.0
    provincial_vote_shift_pct: float = 0.0
    marginal_cost: float = 0.0
    beneficiary_cumulative_growth_pct: float = 0.0


@dataclass
class GovernmentScenarioResult:
    scenario_type: str  # "coalition" o "separated"
    scenario_label: str  # "🟣 Con Lista Única" o "🔵 Por Separado"
    target_seats: int
    initial_bloc_seats: int
    final_bloc_seats: int
    seats_gained: int
    target_achieved: bool
    total_votes_needed: float
    national_pct_increase: float
    steps: List[ProvinceOptimizationStep]
    provinces_involved: List[str]
    is_impossible: bool = False
    impossibility_reason: Optional[str] = None
    initial_national_seats: Dict[str, int] = field(default_factory=dict)
    final_national_seats: Dict[str, int] = field(default_factory=dict)
    initial_national_votes: Dict[str, float] = field(default_factory=dict)
    final_national_votes: Dict[str, float] = field(default_factory=dict)
    initial_national_pct: Dict[str, float] = field(default_factory=dict)
    final_national_pct: Dict[str, float] = field(default_factory=dict)
    final_constituency_data: List[Dict[str, Any]] = field(default_factory=list)
    initial_pact_votes: float = 0.0
    final_pact_votes: float = 0.0
    initial_pact_pct: float = 0.0
    final_pact_pct: float = 0.0
    optimization_criterion: str = "absolute_votes"
    hybrid_alpha: float = 0.50

    @property
    def national_seats_taken(self) -> Dict[str, int]:
        """Conteo nacional de escaños arrebatados desglosado por partido rival."""
        counts: Dict[str, int] = {}
        for s in self.steps:
            r = s.seat_taken_from or "Rival"
            counts[r] = counts.get(r, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    @property
    def national_sources_breakdown(self) -> Dict[str, float]:
        """Desglose nacional agregado de la procedencia de los votos (abstención y partidos donantes)."""
        sources: Dict[str, float] = {}
        for s in self.steps:
            for k, v in s.votes_source_breakdown.items():
                sources[k] = sources.get(k, 0.0) + v
        return dict(sorted(sources.items(), key=lambda x: -x[1]))

    def pact_external_sources(self, pact_parties: Set[str]) -> Dict[str, float]:
        """
        Procedencia neta EXTERNA de los votos captados por el Pacto de Gobierno.
        Filtra y excluye los votos transferidos entre los propios socios del pacto,
        contabilizando únicamente la Abstención y los donantes externos a la coalición.
        """
        sources: Dict[str, float] = {}
        for s in self.steps:
            for k, v in s.votes_source_breakdown.items():
                if v <= 0:
                    continue
                if k == "Abstención" or k not in pact_parties:
                    sources[k] = sources.get(k, 0.0) + v
        return dict(sorted(sources.items(), key=lambda x: -x[1]))

    def pact_internal_transfers(self, pact_parties: Set[str]) -> Dict[str, float]:
        """
        Transferencias internas entre miembros del Pacto de Gobierno (ej. PSOE -> Lista Única).
        Consolida flujos netos para garantizar que ningún par aparezca de forma redundante o circular.
        """
        raw_transfers: Dict[Tuple[str, str], float] = {}
        for s in self.steps:
            for k, v in s.votes_source_breakdown.items():
                if v <= 0:
                    continue
                if k != "Abstención" and k in pact_parties:
                    raw_transfers[(k, s.beneficiary_party)] = (
                        raw_transfers.get((k, s.beneficiary_party), 0.0) + v
                    )

        net_transfers: Dict[str, float] = {}
        processed_pairs = set()
        for (src, dst), v_ab in raw_transfers.items():
            pair_key = tuple(sorted([src, dst]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)
            v_ba = raw_transfers.get((dst, src), 0.0)
            if v_ab > v_ba:
                net_transfers[f"{src} ➔ {dst}"] = v_ab - v_ba
            elif v_ba > v_ab:
                net_transfers[f"{dst} ➔ {src}"] = v_ba - v_ab

        return dict(sorted(net_transfers.items(), key=lambda x: -x[1]))

    def party_sources(self, party: str) -> Dict[str, float]:
        """Procedencia de los votos sumados por un partido específico a nivel nacional con consolidación neta."""
        rec_from: Dict[str, float] = {}
        don_to: Dict[str, float] = {}
        for s in self.steps:
            if s.beneficiary_party == party:
                for k, v in s.votes_source_breakdown.items():
                    if v > 0:
                        rec_from[k] = rec_from.get(k, 0.0) + v
            elif party in s.votes_source_breakdown and s.votes_source_breakdown[party] > 0:
                don_to[s.beneficiary_party] = (
                    don_to.get(s.beneficiary_party, 0.0) + s.votes_source_breakdown[party]
                )

        sources: Dict[str, float] = {}
        for k, v in rec_from.items():
            if k == "Abstención":
                sources[k] = v
            else:
                donated_back = don_to.get(k, 0.0)
                net_v = v - donated_back
                if net_v > 0:
                    sources[k] = net_v
        return dict(sorted(sources.items(), key=lambda x: -x[1]))

    def party_donations(self, party: str) -> Dict[str, float]:
        """Votos cedidos por un partido hacia otros beneficiarios a nivel nacional con consolidación neta."""
        don_to: Dict[str, float] = {}
        rec_from: Dict[str, float] = {}
        for s in self.steps:
            if party in s.votes_source_breakdown and s.votes_source_breakdown[party] > 0:
                don_to[s.beneficiary_party] = (
                    don_to.get(s.beneficiary_party, 0.0) + s.votes_source_breakdown[party]
                )
            elif s.beneficiary_party == party:
                for k, v in s.votes_source_breakdown.items():
                    if v > 0:
                        rec_from[k] = rec_from.get(k, 0.0) + v

        donations: Dict[str, float] = {}
        for dst, v in don_to.items():
            received_back = rec_from.get(dst, 0.0)
            net_v = v - received_back
            if net_v > 0:
                donations[dst] = net_v
        return dict(sorted(donations.items(), key=lambda x: -x[1]))


@dataclass
class GovernmentFormationOptimizationResult:
    config: GovernmentOptimizationConfig
    initial_coalition_seats: int
    initial_partners_seats: Dict[str, int]
    initial_bloc_seats: int
    coalition_result: GovernmentScenarioResult
    separated_result: GovernmentScenarioResult
    more_efficient_scenario: str  # "Lista Única" o "Por Separado"
    votes_savings_with_coalition: float


class GovernmentOptimizer:
    """
    Motor de optimización para la formación de mayorías de investidura.
    """
    def __init__(self, model: Optional[SpanishElectoralModel] = None):
        self.model = model or SpanishElectoralModel()

    def _apply_prior_swing(
        self,
        sim_result: NationalSimulationResult,
        cfg: GovernmentOptimizationConfig,
    ) -> NationalSimulationResult:
        """
        Aplica un swing previo por partido garantizando que la suma de porcentajes
        sea estrictamente el 100.0% en cada circunscripción y a nivel nacional,
        modulando la proporción entre abstención (voto nuevo) y trasvases de donantes.
        """
        active_swings = {
            p: float(v) for p, v in cfg.prior_swing_pct.items()
            if abs(float(v)) >= 0.01
        }
        if not active_swings:
            return sim_result

        abst_ratio = max(0.0, min(1.0, cfg.prior_swing_abstention_share))
        new_constituency_data = []
        new_constituency_results = {}
        new_national_votes: Dict[str, float] = {}

        # Calcular ratios nacionales para el Proportional Ratio Swing
        national_ratios = {}
        for p, swing_val in active_swings.items():
            base_nat_pct = sim_result.national_pct_est.get(p, 0.0)
            if base_nat_pct > 0:
                national_ratios[p] = max(0.01, (base_nat_pct + swing_val) / base_nat_pct)
            else:
                national_ratios[p] = 1.0

        for c_info in sim_result.constituency_data:
            c_dict = copy.deepcopy(c_info)
            c_name = c_dict["name"]
            census = float(c_dict.get("census", 0.0))
            valid_v = float(c_dict.get("valid_votes", 0.0))
            votes_map = dict(c_dict.get("parties_votes") or c_dict.get("raw_parties_votes") or {})
            blank_v = float(c_dict.get("blank_votes", 0.0))
            seats_total = int(c_dict.get("seats", 0))

            if valid_v <= 0:
                valid_v = sum(votes_map.values()) if votes_map else 1.0
            if census <= 0:
                census = round(valid_v / 0.69)

            # Calcular delta de votos deseado por partido con ratio swing
            delta_votes_by_party = {}
            for p, ratio in national_ratios.items():
                if p in votes_map and votes_map[p] > 0:
                    v_orig = votes_map[p]
                    v_target = v_orig * ratio
                    delta_votes_by_party[p] = v_target - v_orig

            total_delta_pos = sum(d for d in delta_votes_by_party.values() if d > 0)
            total_delta_neg = sum(abs(d) for d in delta_votes_by_party.values() if d < 0)

            # Capacidad de donantes autorizados en la provincia
            available_donors = {}
            for d_p, rate in cfg.donor_parties_max_transfer_pct.items():
                if cfg.shield_partners and d_p in cfg.government_partners:
                    continue
                if d_p in active_swings:
                    continue
                if d_p in votes_map and votes_map[d_p] > 0 and rate > 0:
                    available_donors[d_p] = votes_map[d_p] * rate

            total_donor_cap = sum(available_donors.values())

            # Aplicar crecimiento neto modulado entre abstención y donantes
            net_delta = total_delta_pos - total_delta_neg
            if net_delta > 0:
                votes_from_abst = min(
                    net_delta * abst_ratio,
                    max(0.0, census - valid_v) if census > 0 else net_delta * abst_ratio
                )
                votes_from_donors = net_delta - votes_from_abst

                if total_donor_cap > 0 and votes_from_donors > 0:
                    for d_p, cap_val in available_donors.items():
                        deduction = min(cap_val, votes_from_donors * (cap_val / total_donor_cap))
                        votes_map[d_p] = max(0.0, votes_map.get(d_p, 0.0) - deduction)
            else:
                votes_from_abst = net_delta * abst_ratio
                votes_from_donors = 0.0

            # Aplicar deltas a los partidos con swing
            for p, d_val in delta_votes_by_party.items():
                votes_map[p] = max(0.0, votes_map.get(p, 0.0) + d_val)

            new_valid_v = max(1.0, valid_v + votes_from_abst)
            c_dict["valid_votes"] = round(new_valid_v, 0)
            c_dict["parties_votes"] = votes_map
            init_turnout = float(c_dict.get("turnout_pct", round((valid_v / census) * 100, 2) if census > 0 else 66.59))
            added_turnout = (votes_from_abst / census * 100.0) if census > 0 else 0.0
            c_dict["turnout_pct"] = round(min(100.0, max(0.0, init_turnout + added_turnout)), 2)

            # Recalcular porcentajes locales sumando estrictamente 100%
            c_dict["parties_pct"] = {
                p: round((v / new_valid_v) * 100.0, 2)
                for p, v in votes_map.items()
            }

            # Recalcular D'Hondt con los votos ajustados
            c_res = calculate_dhondt(votes_map, seats_total, blank_v, cfg.threshold_pct)
            new_constituency_results[c_name] = c_res
            new_constituency_results[normalize_province_name(c_name)] = c_res
            c_dict["parties_seats"] = dict(c_res.seats)
            new_constituency_data.append(c_dict)

            for p, v in votes_map.items():
                new_national_votes[p] = new_national_votes.get(p, 0.0) + v

        # Consolidar resultados nacionales sin duplicidades
        new_national_seats: Dict[str, int] = {}
        for c_info in new_constituency_data:
            c_res = new_constituency_results[c_info["name"]]
            for p, s in c_res.seats.items():
                new_national_seats[p] = new_national_seats.get(p, 0) + s

        tot_nat_v = max(1.0, sum(new_national_votes.values()))
        new_national_pct = {
            p: (v / tot_nat_v) * 100.0
            for p, v in new_national_votes.items()
        }

        return NationalSimulationResult(
            scenario_name=f"{sim_result.scenario_name} (con Swing previo)",
            national_seats=new_national_seats,
            national_votes_est=new_national_votes,
            national_pct_est=new_national_pct,
            constituency_results=new_constituency_results,
            constituency_data=new_constituency_data,
            total_seats=sim_result.total_seats,
        )

    def optimize(
        self,
        sim_sep: NationalSimulationResult,
        sim_coal: NationalSimulationResult,
        config: Optional[GovernmentOptimizationConfig] = None,
    ) -> GovernmentFormationOptimizationResult:
        """
        Ejecuta la optimización comparativa para ambos escenarios (Lista Única vs Separados).
        """
        cfg = config or GovernmentOptimizationConfig()

        # Aplicar swing previo si está configurado (con conservación estricta al 100%)
        active_sim_coal = self._apply_prior_swing(sim_coal, cfg) if cfg.prior_swing_pct else sim_coal
        active_sim_sep = self._apply_prior_swing(sim_sep, cfg) if cfg.prior_swing_pct else sim_sep

        # Calcular escaños iniciales de socios
        partners = set(cfg.government_partners)
        initial_partners_seats = {
            p: active_sim_coal.national_seats.get(p, 0) for p in cfg.government_partners
        }
        
        # Escaños iniciales de la coalición
        coal_members = set(cfg.coalition_members)
        init_coal_s = active_sim_coal.national_seats.get(cfg.coalition_name, 0)
        init_sep_s = sum(active_sim_sep.national_seats.get(m, 0) for m in coal_members)

        # Beneficiarios en Coalición: Lista Única + socios autorizados para optimizar
        coal_beneficiaries = [cfg.coalition_name]
        for p in cfg.optimizable_partners:
            if p in cfg.government_partners and p != cfg.coalition_name and p not in coal_beneficiaries:
                coal_beneficiaries.append(p)

        # Resolver escenario Coalición
        res_coal = self._optimize_scenario(
            sim_result=active_sim_coal,
            scenario_type="coalition",
            scenario_label=f"🟣 Con Lista Única ({cfg.coalition_name})",
            cfg=cfg,
            beneficiary_parties=coal_beneficiaries,
        )

        # Beneficiarios en Separados: integrantes de coalición + socios autorizados para optimizar
        sep_beneficiaries = list(cfg.coalition_members)
        for p in cfg.optimizable_partners:
            if p in cfg.government_partners and p not in sep_beneficiaries:
                sep_beneficiaries.append(p)

        # Resolver escenario Separado
        sep_mems_desc = f" ({', '.join(cfg.coalition_members)})" if cfg.coalition_members else ""
        res_sep = self._optimize_scenario(
            sim_result=active_sim_sep,
            scenario_type="separated",
            scenario_label=f"🔵 Con Candidaturas por Separado{sep_mems_desc}",
            cfg=cfg,
            beneficiary_parties=sep_beneficiaries,
        )

        # Determinar cuál es más eficiente
        v_coal = res_coal.total_votes_needed if res_coal.target_achieved else float("inf")
        v_sep = res_sep.total_votes_needed if res_sep.target_achieved else float("inf")

        if v_coal <= v_sep:
            more_eff = "Lista Única"
            savings = max(0.0, v_sep - v_coal) if v_sep != float("inf") else 0.0
        else:
            more_eff = "Por Separado"
            savings = max(0.0, v_coal - v_sep) if v_coal != float("inf") else 0.0

        init_bloc = init_coal_s + sum(initial_partners_seats.values())

        return GovernmentFormationOptimizationResult(
            config=cfg,
            initial_coalition_seats=init_coal_s,
            initial_partners_seats=initial_partners_seats,
            initial_bloc_seats=init_bloc,
            coalition_result=res_coal,
            separated_result=res_sep,
            more_efficient_scenario=more_eff,
            votes_savings_with_coalition=savings,
        )

    def _optimize_scenario(
        self,
        sim_result: NationalSimulationResult,
        scenario_type: str,
        scenario_label: str,
        cfg: GovernmentOptimizationConfig,
        beneficiary_parties: List[str],
    ) -> GovernmentScenarioResult:
        """
        Resuelve el mínimo de votos para que el bloque de investidura alcance target_seats en un escenario.
        """
        partners = set(cfg.government_partners)
        target_s = cfg.target_seats

        # Filtro territorial de provincias elegibles
        allowed_provinces: Optional[Set[str]] = None
        if cfg.target_provinces and len(cfg.target_provinces) > 0:
            allowed_provinces = {normalize_province_name(p) for p in cfg.target_provinces}

        # Estado mutable por circunscripción
        prov_states: Dict[str, Dict[str, Any]] = {}
        initial_total_bloc_seats = 0

        for c_info in sim_result.constituency_data:
            c_name = c_info["name"]
            canon = normalize_province_name(c_name)
            
            c_res = sim_result.constituency_results.get(c_name)
            seats_map = dict(c_res.seats) if c_res else {}
            votes_map = dict(c_info.get("parties_votes") or c_info.get("raw_parties_votes") or (getattr(c_res, "votes", None) or {}))
            
            census = float(c_info.get("census", 0.0))
            valid_v = float(c_info.get("valid_votes", sum(votes_map.values()) if votes_map else 1.0))
            blank_v = float(c_info.get("blank_votes", 0.0))
            turnout_p = float(c_info.get("turnout_pct", round((valid_v / census) * 100, 2) if census > 0 else 66.59))
            seats_total = int(c_info.get("seats", 0))

            # Escaños iniciales del bloque en esta provincia
            prov_bloc_s = sum(seats_map.get(p, 0) for p in (set(beneficiary_parties) | partners))
            initial_total_bloc_seats += prov_bloc_s

            # Capacidad de donantes por partido
            donor_caps = {}
            for p_donor, transfer_rate in cfg.donor_parties_max_transfer_pct.items():
                if cfg.shield_partners and p_donor in partners:
                    continue
                if transfer_rate > 0 and p_donor in votes_map:
                    donor_caps[p_donor] = votes_map[p_donor] * transfer_rate

            # Capacidad máxima de abstención
            abst_cap = 0.0
            if cfg.allow_abstention and census > 0:
                max_add_pct = cfg.max_turnout_increase_pct
                avail_pct = min(max_add_pct, max(0.0, 100.0 - turnout_p))
                abst_cap = (avail_pct / 100.0) * census

            prov_states[canon] = {
                "name": c_name,
                "display_name": get_province_display_name(c_name),
                "community": c_info.get("community", ""),
                "seats": seats_total,
                "census": census,
                "valid_votes": valid_v,
                "blank_votes": blank_v,
                "turnout_pct": turnout_p,
                "initial_turnout_pct": turnout_p,
                "votes": votes_map,
                "initial_votes": dict(votes_map),
                "seats_map": dict(seats_map),
                "initial_seats_map": dict(seats_map),
                "bloc_seats": prov_bloc_s,
                "initial_bloc_seats": prov_bloc_s,
                "abst_capacity": abst_cap,
                "donor_capacities": donor_caps,
                "accumulated_abstention": 0.0,
                "accumulated_transfers": {p: 0.0 for p in donor_caps},
                "accumulated_beneficiary_gains": {p: 0.0 for p in beneficiary_parties},
                "pairwise_transfers": {},
                "party_sources": {},
                "party_donations": {},
                "is_eligible": (allowed_provinces is None or canon in allowed_provinces),
            }

        all_pact_parties = set(beneficiary_parties) | partners

        # Comprobar si ya se alcanza el objetivo sin votos adicionales
        if initial_total_bloc_seats >= target_s:
            summary = self._build_scenario_summary(prov_states, all_pact_parties)
            return GovernmentScenarioResult(
                scenario_type=scenario_type,
                scenario_label=scenario_label,
                target_seats=target_s,
                initial_bloc_seats=initial_total_bloc_seats,
                final_bloc_seats=initial_total_bloc_seats,
                seats_gained=0,
                target_achieved=True,
                total_votes_needed=0.0,
                national_pct_increase=0.0,
                steps=[],
                provinces_involved=[],
                optimization_criterion=cfg.optimization_criterion,
                hybrid_alpha=cfg.hybrid_alpha,
                **summary,
            )

        current_bloc_seats = initial_total_bloc_seats
        seats_needed = target_s - current_bloc_seats
        steps: List[ProvinceOptimizationStep] = []
        total_votes_accum = 0.0

        # Iterar escaño a escaño seleccionando la provincia con menor coste marginal
        for seat_idx in range(1, seats_needed + 1):
            best_prov_canon = None
            best_cost = float("inf")
            best_v_needed = float("inf")
            best_details = None

            for canon, state in prov_states.items():
                if not state["is_eligible"]:
                    continue

                eval_res = self._find_cheapest_seat_in_province(
                    state=state,
                    beneficiary_parties=beneficiary_parties,
                    partners=partners,
                    threshold_pct=cfg.threshold_pct,
                    cfg=cfg,
                )

                if eval_res is not None:
                    m_cost = eval_res["marginal_cost"]
                    v_need = eval_res["votes_needed"]
                    is_better = False
                    if m_cost < best_cost:
                        is_better = True
                    elif abs(m_cost - best_cost) < 1e-9 and v_need < best_v_needed:
                        is_better = True

                    if is_better:
                        best_cost = m_cost
                        best_v_needed = v_need
                        best_prov_canon = canon
                        best_details = eval_res

            # Si ninguna provincia puede aportar otro escaño dentro de sus límites
            if best_prov_canon is None or best_details is None:
                impossibility_msg = (
                    f"Con las restricciones y provincias seleccionadas solo ha sido posible sumar "
                    f"{len(steps)} escaños (total {current_bloc_seats} dip.). "
                    f"Faltan {target_s - current_bloc_seats} escaños para alcanzar la mayoría de {target_s}."
                )
                if steps:
                    total_votes_accum = self._recalibrate_provinces_post_pass(
                        prov_states, steps, beneficiary_parties, partners, cfg
                    )
                total_national_votes = sum(c["valid_votes"] for c in sim_result.constituency_data)
                nat_pct_inc = (total_votes_accum / total_national_votes * 100.0) if total_national_votes > 0 else 0.0
                summary = self._build_scenario_summary(prov_states, all_pact_parties)
                return GovernmentScenarioResult(
                    scenario_type=scenario_type,
                    scenario_label=scenario_label,
                    target_seats=target_s,
                    initial_bloc_seats=initial_total_bloc_seats,
                    final_bloc_seats=current_bloc_seats,
                    seats_gained=len(steps),
                    target_achieved=False,
                    total_votes_needed=round(total_votes_accum, 0),
                    national_pct_increase=round(nat_pct_inc, 2),
                    steps=steps,
                    provinces_involved=list({s.province for s in steps}),
                    is_impossible=True,
                    impossibility_reason=impossibility_msg,
                    optimization_criterion=cfg.optimization_criterion,
                    hybrid_alpha=cfg.hybrid_alpha,
                    **summary,
                )

            # Aplicar el escaño ganado al estado provincial
            target_st = prov_states[best_prov_canon]
            target_st["votes"] = best_details["new_votes"]
            target_st["seats_map"] = best_details["new_seats_map"]
            target_st["valid_votes"] += best_details["votes_from_abstention"]
            target_st["accumulated_abstention"] += best_details["votes_from_abstention"]
            benef = best_details["beneficiary"]
            target_st["accumulated_beneficiary_gains"][benef] = (
                target_st["accumulated_beneficiary_gains"].get(benef, 0.0) + best_details["votes_needed"]
            )
            
            # Registrar procedencia de votos para el beneficiario y donaciones para los donantes
            if benef not in target_st["party_sources"]:
                target_st["party_sources"][benef] = {}
            if best_details["votes_from_abstention"] > 0:
                target_st["party_sources"][benef]["Abstención"] = (
                    target_st["party_sources"][benef].get("Abstención", 0.0) + best_details["votes_from_abstention"]
                )

            for p_don, v_don in best_details["votes_from_donors"].items():
                if v_don > 0:
                    target_st["accumulated_transfers"][p_don] = target_st["accumulated_transfers"].get(p_don, 0.0) + v_don
                    if "pairwise_transfers" not in target_st:
                        target_st["pairwise_transfers"] = {}
                    target_st["pairwise_transfers"][(p_don, benef)] = (
                        target_st["pairwise_transfers"].get((p_don, benef), 0.0) + v_don
                    )
                    target_st["party_sources"][benef][p_don] = (
                        target_st["party_sources"][benef].get(p_don, 0.0) + v_don
                    )
                    if p_don not in target_st["party_donations"]:
                        target_st["party_donations"][p_don] = {}
                    target_st["party_donations"][p_don][benef] = (
                        target_st["party_donations"][p_don].get(benef, 0.0) + v_don
                    )

            target_st["bloc_seats"] = best_details["new_bloc_seats"]
            current_bloc_seats += 1
            total_votes_accum += best_details["votes_needed"]

            # Registrar el paso
            added_turnout_pct = (
                (target_st["accumulated_abstention"] / target_st["census"] * 100.0)
                if target_st["census"] > 0
                else 0.0
            )
            new_turnout = round(min(100.0, target_st["initial_turnout_pct"] + added_turnout_pct), 2)
            target_st["turnout_pct"] = new_turnout

            init_b_pct = (sum(target_st["initial_votes"].get(p, 0.0) for p in (set(beneficiary_parties) | partners)) / max(1.0, sum(target_st["initial_votes"].values()))) * 100.0
            fin_b_pct = (sum(target_st["votes"].get(p, 0.0) for p in (set(beneficiary_parties) | partners)) / max(1.0, sum(target_st["votes"].values()))) * 100.0

            source_dict = {}
            if best_details["votes_from_abstention"] > 0:
                source_dict["Abstención"] = round(best_details["votes_from_abstention"], 0)
            for p_don, v_don in best_details["votes_from_donors"].items():
                if v_don > 0:
                    source_dict[p_don] = round(v_don, 0)

            benef_init_v = target_st["initial_votes"].get(benef, 0.0)
            benef_fin_v = target_st["votes"].get(benef, 0.0)
            step_growth = (best_details["votes_needed"] / benef_init_v * 100.0) if benef_init_v > 0 else 0.0
            cumul_growth = ((benef_fin_v - benef_init_v) / benef_init_v * 100.0) if benef_init_v > 0 else 0.0
            prov_shift = (best_details["votes_needed"] / max(1.0, target_st["valid_votes"])) * 100.0

            steps.append(ProvinceOptimizationStep(
                province=target_st["name"],
                display_name=target_st["display_name"],
                community=target_st["community"],
                seats_in_province=target_st["seats"],
                seat_order=seat_idx,
                votes_needed=round(best_details["votes_needed"], 0),
                beneficiary_party=benef,
                seat_taken_from=best_details["seat_taken_from"],
                initial_seats_bloc=target_st["initial_bloc_seats"],
                final_seats_bloc=target_st["bloc_seats"],
                votes_source_breakdown=source_dict,
                initial_turnout_pct=round(target_st["initial_turnout_pct"], 2),
                final_turnout_pct=round(new_turnout, 2),
                initial_bloc_pct=round(init_b_pct, 2),
                final_bloc_pct=round(fin_b_pct, 2),
                beneficiary_growth_pct=round(step_growth, 2),
                beneficiary_initial_votes=round(benef_init_v, 0),
                beneficiary_final_votes=round(benef_fin_v, 0),
                provincial_vote_shift_pct=round(prov_shift, 2),
                marginal_cost=round(best_details.get("marginal_cost", best_details["votes_needed"]), 3),
                beneficiary_cumulative_growth_pct=round(cumul_growth, 2),
            ))

        if steps:
            total_votes_accum = self._recalibrate_provinces_post_pass(
                prov_states, steps, beneficiary_parties, partners, cfg
            )
        total_national_votes = sum(c["valid_votes"] for c in sim_result.constituency_data)
        nat_pct_inc = (total_votes_accum / total_national_votes * 100.0) if total_national_votes > 0 else 0.0
        summary = self._build_scenario_summary(prov_states, all_pact_parties)

        return GovernmentScenarioResult(
            scenario_type=scenario_type,
            scenario_label=scenario_label,
            target_seats=target_s,
            initial_bloc_seats=initial_total_bloc_seats,
            final_bloc_seats=current_bloc_seats,
            seats_gained=len(steps),
            target_achieved=True,
            total_votes_needed=round(total_votes_accum, 0),
            national_pct_increase=round(nat_pct_inc, 2),
            steps=steps,
            provinces_involved=list({s.province for s in steps}),
            optimization_criterion=cfg.optimization_criterion,
            hybrid_alpha=cfg.hybrid_alpha,
            **summary,
        )

    def _build_scenario_summary(
        self,
        prov_states: Dict[str, Dict[str, Any]],
        pact_parties: Set[str],
    ) -> Dict[str, Any]:
        """
        Calcula los agregados nacionales de escaños y votos (antes y después)
        y la estructura detallada de cada circunscripción post-optimización.
        """
        init_nat_seats: Dict[str, int] = {}
        fin_nat_seats: Dict[str, int] = {}
        init_nat_votes: Dict[str, float] = {}
        fin_nat_votes: Dict[str, float] = {}
        final_constituency_data: List[Dict[str, Any]] = []

        total_init_valid = 0.0
        total_fin_valid = 0.0

        for canon, st in prov_states.items():
            for p, s in st["initial_seats_map"].items():
                init_nat_seats[p] = init_nat_seats.get(p, 0) + s
            for p, s in st["seats_map"].items():
                fin_nat_seats[p] = fin_nat_seats.get(p, 0) + s

            for p, v in st["initial_votes"].items():
                init_nat_votes[p] = init_nat_votes.get(p, 0.0) + v
            for p, v in st["votes"].items():
                fin_nat_votes[p] = fin_nat_votes.get(p, 0.0) + v

            total_init_valid += sum(st["initial_votes"].values()) + st.get("blank_votes", 0.0)
            total_fin_valid += sum(st["votes"].values()) + st.get("blank_votes", 0.0)

            final_constituency_data.append({
                "province": st["name"],
                "display_name": st["display_name"],
                "community": st["community"],
                "seats": st["seats"],
                "census": st["census"],
                "initial_turnout_pct": st["initial_turnout_pct"],
                "final_turnout_pct": st["turnout_pct"],
                "initial_seats": dict(st["initial_seats_map"]),
                "final_seats": dict(st["seats_map"]),
                "initial_votes": dict(st["initial_votes"]),
                "final_votes": dict(st["votes"]),
                "blank_votes": st.get("blank_votes", 0.0),
                "party_sources": copy.deepcopy(st.get("party_sources", {})),
                "party_donations": copy.deepcopy(st.get("party_donations", {})),
            })

        init_nat_pct: Dict[str, float] = {}
        fin_nat_pct: Dict[str, float] = {}
        for p, v in init_nat_votes.items():
            init_nat_pct[p] = round((v / total_init_valid * 100.0) if total_init_valid > 0 else 0.0, 2)
        for p, v in fin_nat_votes.items():
            fin_nat_pct[p] = round((v / total_fin_valid * 100.0) if total_fin_valid > 0 else 0.0, 2)

        init_pact_v = sum(init_nat_votes.get(p, 0.0) for p in pact_parties)
        fin_pact_v = sum(fin_nat_votes.get(p, 0.0) for p in pact_parties)
        init_pact_p = round((init_pact_v / total_init_valid * 100.0) if total_init_valid > 0 else 0.0, 2)
        fin_pact_p = round((fin_pact_v / total_fin_valid * 100.0) if total_fin_valid > 0 else 0.0, 2)

        return {
            "initial_national_seats": init_nat_seats,
            "final_national_seats": fin_nat_seats,
            "initial_national_votes": init_nat_votes,
            "final_national_votes": fin_nat_votes,
            "initial_national_pct": init_nat_pct,
            "final_national_pct": fin_nat_pct,
            "final_constituency_data": final_constituency_data,
            "initial_pact_votes": init_pact_v,
            "final_pact_votes": fin_pact_v,
            "initial_pact_pct": init_pact_p,
            "final_pact_pct": fin_pact_p,
        }

    def _recalibrate_provinces_post_pass(
        self,
        prov_states: Dict[str, Dict[str, Any]],
        steps: List[ProvinceOptimizationStep],
        beneficiary_parties: List[str],
        partners: Set[str],
        cfg: Optional[GovernmentOptimizationConfig],
    ) -> float:
        """
        Recalibración de Cierre Provincial (Post-Optimization Pass).
        
        En el sistema electoral español (LOREG), cada circunscripción resuelve un único reparto
        simultáneo de escaños por D'Hondt la noche electoral. El algoritmo voraz secuencial
        optimiza escaño a escaño (+1 cada vez), lo que en provincias donde se ganan múltiples
        escaños puede acumular holgura ('slack') o desajustes entre pasos secuenciales.
        
        Este pase posterior toma como punto de partida el vector inicial de votos (V_0),
        y para cada provincia donde se sumaron escaños recalcula el vector conjunto simultáneo
        mínimo (Δ_1*, ..., Δ_m*) necesario para certificar todos los escaños ganados por el bloque,
        eliminando cualquier holgura y garantizando estrictamente que ningún socio del bloque
        pierde escaños y que las ganancias provienen exclusivamente de adversarios externos.
        """
        if not steps:
            return 0.0

        all_bloc_parties = set(partners) | set(beneficiary_parties)

        # 1. Agrupar pasos de optimización por circunscripción canónica
        prov_steps_map: Dict[str, List[ProvinceOptimizationStep]] = {}
        for s in steps:
            canon = normalize_province_name(s.province)
            prov_steps_map.setdefault(canon, []).append(s)

        for canon, p_steps in prov_steps_map.items():
            if not p_steps or canon not in prov_states:
                continue

            st = prov_states[canon]
            init_votes = dict(st["initial_votes"])
            init_seats_map = dict(st["initial_seats_map"])
            target_seats_map = dict(st["seats_map"])
            target_bloc_seats = st["bloc_seats"]
            seats_to_allocate = st["seats"]
            blank_v = float(st.get("blank_votes", 0.0))
            threshold_pct = float(st.get("threshold_pct", 3.0))

            prov_beneficiaries = list(dict.fromkeys(s.beneficiary_party for s in p_steps))
            greedy_deltas = {
                b: int(round(sum(s.votes_needed for s in p_steps if s.beneficiary_party == b)))
                for b in prov_beneficiaries
            }
            total_greedy_votes = sum(greedy_deltas.values())
            if total_greedy_votes <= 0:
                continue

            # Capacidad de abstención disponible en la provincia desde V_0
            abst_cap = float(st.get("abst_capacity", 0.0))

            # Donantes autorizados: exclusivamente rivales externos (fuera del bloque)
            donor_specs: Dict[str, float] = {}
            if cfg and cfg.party_porosity:
                for b in prov_beneficiaries:
                    b_donors = cfg.party_porosity.get(b, {})
                    for p_don, rate in b_donors.items():
                        if p_don not in all_bloc_parties and rate > 0:
                            donor_specs[p_don] = max(donor_specs.get(p_don, 0.0), rate)
            elif cfg:
                for p_don, rate in cfg.donor_parties_max_transfer_pct.items():
                    if p_don not in all_bloc_parties and rate > 0:
                        donor_specs[p_don] = rate

            donor_caps: Dict[str, float] = {}
            for p_don, rate in donor_specs.items():
                if p_don in init_votes and init_votes[p_don] > 0 and rate > 0:
                    donor_caps[p_don] = init_votes[p_don] * rate

            # Función para calcular la distribución de votos con un vector de deltas
            def _eval_deltas_vector(deltas: Dict[str, int]):
                tot_delta = sum(deltas.values())
                if tot_delta <= 0:
                    return dict(init_votes), 0.0, {}, {b: 0.0 for b in prov_beneficiaries}, {b: {} for b in prov_beneficiaries}

                tot_cap = abst_cap + sum(donor_caps.values())
                test_v = dict(init_votes)

                if tot_cap <= 0:
                    for b, d in deltas.items():
                        test_v[b] = test_v.get(b, 0.0) + d
                    return test_v, 0.0, {}, {b: 0.0 for b in prov_beneficiaries}, {b: {} for b in prov_beneficiaries}

                tot_abst = min(abst_cap, tot_delta * (abst_cap / tot_cap))
                tot_don_extract = tot_delta - tot_abst
                donor_total = sum(donor_caps.values())

                donor_shares = {}
                if donor_total > 0 and tot_don_extract > 0:
                    for p_don, cap_don in donor_caps.items():
                        p_share = min(cap_don, tot_don_extract * (cap_don / donor_total))
                        donor_shares[p_don] = p_share
                        test_v[p_don] = max(0.0, test_v.get(p_don, 0.0) - p_share)

                for b, d in deltas.items():
                    test_v[b] = test_v.get(b, 0.0) + d

                # Asignación proporcional por beneficiario
                b_abst_dict = {}
                b_don_dict = {}
                for b, d in deltas.items():
                    frac = (d / tot_delta) if tot_delta > 0 else 0.0
                    b_abst_dict[b] = tot_abst * frac
                    b_don_dict[b] = {p_don: val * frac for p_don, val in donor_shares.items()}

                return test_v, tot_abst, donor_shares, b_abst_dict, b_don_dict

            # Función de verificación de validez bajo D'Hondt simultáneo
            def _is_vector_valid(deltas: Dict[str, int]):
                test_v, tot_abst, don_shares, b_abst_dict, b_don_dict = _eval_deltas_vector(deltas)
                dh = calculate_dhondt(test_v, seats_to_allocate, blank_v, threshold_pct)

                # 1. Cada beneficiario en expansión alcanza sus escaños objetivo
                if any(dh.seats.get(b, 0) < target_seats_map.get(b, 0) for b in prov_beneficiaries):
                    return False, None, None, None, None, None, None

                # 2. El bloque gubernamental suma el total de escaños objetivo
                bloc_seats_now = sum(dh.seats.get(p, 0) for p in all_bloc_parties)
                if bloc_seats_now < target_bloc_seats:
                    return False, None, None, None, None, None, None

                # 3. Invariante estricto de preservación: ningún socio del bloque pierde escaños base
                if any(dh.seats.get(p, 0) < init_seats_map.get(p, 0) for p in all_bloc_parties):
                    return False, None, None, None, None, None, None

                # 4. Los escaños ganados provienen estrictamente de adversarios ajenos al bloque
                rival_seats_lost = sum(
                    max(0, init_seats_map.get(p, 0) - dh.seats.get(p, 0))
                    for p in init_seats_map
                    if p not in all_bloc_parties
                )
                if rival_seats_lost < len(p_steps):
                    return False, None, None, None, None, None, None

                return True, dh, test_v, tot_abst, don_shares, b_abst_dict, b_don_dict

            # 2. Búsqueda del vector mínimo exacto
            best_deltas = dict(greedy_deltas)
            best_sol = None

            # Verificar primero el vector greedy como cota superior factible
            is_valid, dh, tv, tot_a, don_s, b_a, b_d = _is_vector_valid(best_deltas)
            if is_valid:
                best_sol = (dh, tv, tot_a, don_s, b_a, b_d)

            if len(prov_beneficiaries) == 1:
                b = prov_beneficiaries[0]
                low_v = 1
                high_v = best_deltas[b]
                while low_v <= high_v:
                    mid_v = (low_v + high_v) // 2
                    is_valid, dh, tv, tot_a, don_s, b_a, b_d = _is_vector_valid({b: mid_v})
                    if is_valid:
                        best_deltas[b] = mid_v
                        best_sol = (dh, tv, tot_a, don_s, b_a, b_d)
                        high_v = mid_v - 1
                    else:
                        low_v = mid_v + 1
            else:
                # Si hay múltiples beneficiarios distintos en la misma provincia: coordinate descent
                for _pass in range(2):
                    for b in prov_beneficiaries:
                        low_v = 1
                        high_v = best_deltas[b]
                        curr_best = best_deltas[b]
                        while low_v <= high_v:
                            mid_v = (low_v + high_v) // 2
                            cand_deltas = dict(best_deltas)
                            cand_deltas[b] = mid_v
                            is_valid, dh, tv, tot_a, don_s, b_a, b_d = _is_vector_valid(cand_deltas)
                            if is_valid:
                                curr_best = mid_v
                                best_sol = (dh, tv, tot_a, don_s, b_a, b_d)
                                high_v = mid_v - 1
                            else:
                                low_v = mid_v + 1
                        best_deltas[b] = curr_best

            # Si encontramos una solución válida con votos <= greedy, aplicar recalibración
            if best_sol is not None and sum(best_deltas.values()) <= total_greedy_votes:
                dh_res, final_prov_votes, recal_abst_tot, recal_don_tot, b_abst_dict, b_don_dict = best_sol

                # Actualizar estado provincial
                st["votes"] = final_prov_votes
                st["seats_map"] = dh_res.seats
                st["valid_votes"] = sum(final_prov_votes.values()) + blank_v
                st["accumulated_abstention"] = recal_abst_tot
                st["accumulated_transfers"] = dict(recal_don_tot)
                for b in prov_beneficiaries:
                    st["accumulated_beneficiary_gains"][b] = best_deltas[b]

                added_turnout_pct = (
                    (recal_abst_tot / st["census"] * 100.0)
                    if st["census"] > 0
                    else 0.0
                )
                st["turnout_pct"] = round(min(100.0, st["initial_turnout_pct"] + added_turnout_pct), 2)

                # Reconstruir procedencia y donaciones de votos
                st["party_sources"] = {}
                st["party_donations"] = {}
                for b in prov_beneficiaries:
                    st["party_sources"][b] = {}
                    if b_abst_dict.get(b, 0.0) > 0:
                        st["party_sources"][b]["Abstención"] = round(b_abst_dict[b], 0)
                    for p_don, val in b_don_dict.get(b, {}).items():
                        if val > 0:
                            st["party_sources"][b][p_don] = round(val, 0)
                            if p_don not in st["party_donations"]:
                                st["party_donations"][p_don] = {}
                            st["party_donations"][p_don][b] = round(val, 0)

                # 3. Actualizar los pasos de optimización de esta provincia
                for b in prov_beneficiaries:
                    b_steps = [s for s in p_steps if s.beneficiary_party == b]
                    orig_b_votes = sum(s.votes_needed for s in b_steps)
                    b_recal_total = best_deltas[b]

                    accum_distributed = 0
                    accum_b_votes = 0
                    benef_init_v = st["initial_votes"].get(b, 0.0)
                    for idx_step, s in enumerate(b_steps):
                        if idx_step == len(b_steps) - 1:
                            step_votes = max(1, b_recal_total - accum_distributed)
                        else:
                            ratio = (s.votes_needed / orig_b_votes) if orig_b_votes > 0 else (1.0 / len(b_steps))
                            step_votes = int(round(b_recal_total * ratio))
                            accum_distributed += step_votes

                        step_frac = (step_votes / b_recal_total) if b_recal_total > 0 else 1.0

                        # Reconstruir desglose de fuentes para este paso
                        step_sources = {}
                        if b_abst_dict.get(b, 0.0) > 0:
                            step_sources["Abstención"] = round(b_abst_dict[b] * step_frac, 0)
                        for p_don, val in b_don_dict.get(b, {}).items():
                            if val > 0:
                                step_sources[p_don] = round(val * step_frac, 0)

                        s.votes_needed = step_votes
                        s.votes_source_breakdown = step_sources
                        s.final_turnout_pct = st["turnout_pct"]
                        s.final_bloc_pct = round(
                            (sum(st["votes"].get(p, 0.0) for p in all_bloc_parties) / max(1.0, sum(st["votes"].values()))) * 100.0,
                            2,
                        )
                        accum_b_votes += step_votes
                        s.beneficiary_initial_votes = round(benef_init_v, 0)
                        s.beneficiary_final_votes = round(benef_init_v + accum_b_votes, 0)
                        s.beneficiary_growth_pct = round(
                            (s.votes_needed / benef_init_v * 100.0) if benef_init_v > 0 else 0.0,
                            2,
                        )
                        s.beneficiary_cumulative_growth_pct = round(
                            (accum_b_votes / benef_init_v * 100.0) if benef_init_v > 0 else 0.0,
                            2,
                        )
                        s.provincial_vote_shift_pct = round(
                            (s.votes_needed / max(1.0, st["valid_votes"])) * 100.0,
                            2,
                        )

                        crit = cfg.optimization_criterion if cfg else "absolute_votes"
                        valid_v = max(1.0, float(st.get("valid_votes", 1.0)))
                        benef_init_val = max(1.0, float(benef_init_v))
                        prov_pct_cost = (step_votes / valid_v) * 100.0
                        party_growth_cost = (step_votes / benef_init_val) * 100.0
                        if crit == "provincial_pct":
                            step_marginal_cost = prov_pct_cost
                        elif crit == "party_growth_pct":
                            step_marginal_cost = party_growth_cost
                        elif crit == "hybrid":
                            alpha = float(getattr(cfg, "hybrid_alpha", 0.50))
                            p_c = max(1e-7, prov_pct_cost)
                            g_c = max(1e-7, party_growth_cost)
                            if alpha <= 0.0:
                                step_marginal_cost = prov_pct_cost
                            elif alpha >= 1.0:
                                step_marginal_cost = party_growth_cost
                            else:
                                step_marginal_cost = (p_c ** (1.0 - alpha)) * (g_c ** alpha)
                        else:
                            step_marginal_cost = float(step_votes)
                        s.marginal_cost = round(step_marginal_cost, 3)

        return float(sum(s.votes_needed for s in steps))

    def _find_cheapest_seat_in_province(
        self,
        state: Dict[str, Any],
        beneficiary_parties: List[str],
        partners: Set[str],
        threshold_pct: float,
        cfg: Optional[GovernmentOptimizationConfig] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Calcula el coste mínimo exacto en votos para que el bloque sume +1 escaño en esta circunscripción,
        respetando la porosidad específica de cada partido y el tope máximo de crecimiento por provincia.
        """
        curr_votes = dict(state["votes"])
        curr_seats_map = dict(state["seats_map"])
        curr_bloc_s = state["bloc_seats"]
        seats_to_allocate = state["seats"]
        blank_v = state["blank_votes"]

        rem_abst = max(0.0, state["abst_capacity"] - state["accumulated_abstention"])

        # Evaluar qué partido beneficiario es más eficiente según el criterio configurado
        best_cand_res = None
        min_marginal_cost = float("inf")
        min_v_needed = float("inf")

        for benef in beneficiary_parties:
            # Si el partido no compite en esta circunscripción o tiene 0 votos, se descarta
            if benef not in curr_votes or curr_votes[benef] <= 0:
                continue

            # Incompatibilidad Local de Rol: un partido que ya ha actuado como donante en esta circunscripción
            # no puede convertirse en beneficiario de nuevos escaños en la misma provincia (evita desvestir para volver a vestir).
            if state.get("accumulated_transfers", {}).get(benef, 0.0) > 0:
                continue

            # 1. Porosidad específica partido a partido (Point 2)
            if cfg and cfg.party_porosity and benef in cfg.party_porosity:
                donor_specs = cfg.party_porosity[benef]
            elif cfg:
                donor_specs = cfg.donor_parties_max_transfer_pct
            else:
                donor_specs = {}

            all_bloc_parties = set(partners) | set(beneficiary_parties)

            rem_donors = {}
            for p_don, rate in donor_specs.items():
                # Blindaje general de socios y co-beneficiarios del bloque
                if cfg and cfg.shield_partners and p_don in all_bloc_parties:
                    continue
                if p_don == benef:
                    continue

                # Axioma 1: Unidireccionalidad estricta y no-circularidad pairwise
                # Si 'benef' ya le cedió votos a 'p_don' en esta circunscripción, 'p_don' no puede donar a 'benef'
                if state.get("pairwise_transfers", {}).get((benef, p_don), 0.0) > 0:
                    continue

                # Axioma 2: Incompatibilidad de rol (donante vs. beneficiario en expansión)
                # Si 'p_don' ya ha recibido votos o ganado un escaño optimizado en esta circunscripción,
                # queda excluido automáticamente como donante en esta provincia.
                if state.get("accumulated_beneficiary_gains", {}).get(p_don, 0.0) > 0:
                    continue

                # Axioma 3: Blindaje mutuo entre co-beneficiarios en la misma circunscripción
                # Dos candidaturas del bloque que aspiran a sumar escaños no pueden transferirse votos entre sí
                # en la misma provincia; sus votos de expansión deben provenir de abstención o partidos rivales.
                if p_don in beneficiary_parties:
                    continue

                if rate > 0 and curr_votes.get(p_don, 0.0) > 0:
                    init_v = state["initial_votes"].get(p_don, curr_votes.get(p_don, 0.0))
                    cap_don = init_v * rate
                    already_transferred = state["accumulated_transfers"].get(p_don, 0.0)
                    rem_d = max(0.0, cap_don - already_transferred)
                    if rem_d > 0:
                        rem_donors[p_don] = min(rem_d, curr_votes[p_don])

            benef_rem_cap = rem_abst + sum(rem_donors.values())
            if benef_rem_cap <= 10.0:
                continue

            # 2. Tope de crecimiento máximo en la circunscripción (Point 6)
            benef_init_v = state["initial_votes"].get(benef, curr_votes.get(benef, 0.0))
            growth_cap_pct = (
                cfg.max_party_growth_pct.get(benef, cfg.default_max_party_growth_pct)
                if cfg
                else 80.0
            )
            if growth_cap_pct > 0 and benef_init_v > 0:
                max_gain = benef_init_v * (growth_cap_pct / 100.0)
                already_gained = state.get("accumulated_beneficiary_gains", {}).get(benef, 0.0)
                headroom = max(0.0, max_gain - already_gained)
            else:
                headroom = benef_rem_cap

            effective_high_v = min(int(benef_rem_cap), int(headroom))
            if effective_high_v < 1:
                continue

            # Búsqueda binaria del mínimo incremento de votos
            low_v = 1
            high_v = effective_high_v
            found_v = None
            found_test_res = None
            found_taken_from = None
            found_new_votes = None
            found_abst_share = 0.0
            found_donor_shares = {}

            # Comprobar primero cota superior
            test_v_high, abst_h, don_h = self._apply_vote_sources(curr_votes, benef, high_v, rem_abst, rem_donors)
            res_h = calculate_dhondt(test_v_high, seats_to_allocate, blank_v, threshold_pct)
            new_bloc_h = sum(res_h.seats.get(p, 0) for p in all_bloc_parties)

            if new_bloc_h <= curr_bloc_s:
                continue

            # Búsqueda binaria exacta
            while low_v <= high_v:
                mid_v = (low_v + high_v) // 2
                test_v_mid, abst_m, don_m = self._apply_vote_sources(curr_votes, benef, mid_v, rem_abst, rem_donors)
                res_m = calculate_dhondt(test_v_mid, seats_to_allocate, blank_v, threshold_pct)
                new_bloc_m = sum(res_m.seats.get(p, 0) for p in all_bloc_parties)

                # Comprobar que NINGÚN partido del bloque pierde escaños respecto a su asignación actual
                bloc_lost_seat = any(res_m.seats.get(p, 0) < curr_seats_map.get(p, 0) for p in all_bloc_parties)

                # Averiguar a quién se le arrebata el escaño (debe ser estrictamente un rival de fuera del pacto)
                taken = None
                for p_cand, s_old in curr_seats_map.items():
                    if res_m.seats.get(p_cand, 0) < s_old and p_cand not in all_bloc_parties:
                        taken = p_cand
                        break

                if new_bloc_m > curr_bloc_s and not bloc_lost_seat and taken is not None:
                    found_v = mid_v
                    found_test_res = res_m
                    found_new_votes = test_v_mid
                    found_abst_share = abst_m
                    found_donor_shares = don_m
                    found_taken_from = taken

                    high_v = mid_v - 1
                else:
                    low_v = mid_v + 1

            if found_v is not None:
                valid_v = max(1.0, float(state.get("valid_votes", 1.0)))
                benef_init_val = max(1.0, float(benef_init_v))
                prov_pct_cost = (found_v / valid_v) * 100.0
                party_growth_cost = (found_v / benef_init_val) * 100.0

                crit = cfg.optimization_criterion if cfg else "absolute_votes"
                if crit == "provincial_pct":
                    cand_marginal_cost = prov_pct_cost
                elif crit == "party_growth_pct":
                    cand_marginal_cost = party_growth_cost
                elif crit == "hybrid":
                    alpha = float(getattr(cfg, "hybrid_alpha", 0.50))
                    # Media geométrica ponderada Cobb-Douglas: (prov_pct_cost ** (1 - alpha)) * (party_growth_cost ** alpha)
                    p_c = max(1e-7, prov_pct_cost)
                    g_c = max(1e-7, party_growth_cost)
                    if alpha <= 0.0:
                        cand_marginal_cost = prov_pct_cost
                    elif alpha >= 1.0:
                        cand_marginal_cost = party_growth_cost
                    else:
                        cand_marginal_cost = (p_c ** (1.0 - alpha)) * (g_c ** alpha)
                else:
                    cand_marginal_cost = float(found_v)

                is_better = False
                if cand_marginal_cost < min_marginal_cost:
                    is_better = True
                elif abs(cand_marginal_cost - min_marginal_cost) < 1e-9 and found_v < min_v_needed:
                    is_better = True

                if is_better:
                    min_marginal_cost = cand_marginal_cost
                    min_v_needed = found_v
                    best_cand_res = {
                        "votes_needed": found_v,
                        "marginal_cost": cand_marginal_cost,
                        "prov_pct_cost": prov_pct_cost,
                        "party_growth_cost": party_growth_cost,
                        "beneficiary": benef,
                        "seat_taken_from": found_taken_from,
                        "new_votes": found_new_votes,
                        "new_seats_map": found_test_res.seats,
                        "new_bloc_seats": curr_bloc_s + 1,
                        "votes_from_abstention": found_abst_share,
                        "votes_from_donors": found_donor_shares,
                    }

        return best_cand_res

    def _apply_vote_sources(
        self,
        base_votes: Dict[str, float],
        beneficiary: str,
        delta: int,
        rem_abst: float,
        rem_donors: Dict[str, float],
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Distribuye delta votos entre la abstención y los partidos donantes de forma proporcional.
        """
        new_votes = dict(base_votes)
        total_cap = rem_abst + sum(rem_donors.values())
        if total_cap <= 0:
            new_votes[beneficiary] = new_votes.get(beneficiary, 0.0) + delta
            return new_votes, 0.0, {}

        # Reparto proporcional ponderado
        abst_share = min(rem_abst, delta * (rem_abst / total_cap))
        donor_shares = {}
        remaining_to_extract = delta - abst_share

        donor_total = sum(rem_donors.values())
        if donor_total > 0 and remaining_to_extract > 0:
            for p_don, cap_don in rem_donors.items():
                p_share = min(cap_don, remaining_to_extract * (cap_don / donor_total))
                donor_shares[p_don] = p_share
                new_votes[p_don] = max(0.0, new_votes.get(p_don, 0.0) - p_share)

        new_votes[beneficiary] = new_votes.get(beneficiary, 0.0) + delta
        return new_votes, abst_share, donor_shares


def create_government_roadmap_chart(result: GovernmentScenarioResult) -> Optional[go.Figure]:
    """
    Genera un gráfico horizontal con la hoja de ruta de votos necesarios por provincia.
    Asegura texto en color negro (#000000) de máxima legibilidad, paleta accesible (Cividis),
    soporte multilínea (votos, rival y fuentes de procedencia) adaptando la posición del texto
    (dentro de la barra si es amplia, o fuera si es estrecha) y redimensionando márgenes y altura
    para evitar cualquier tipo de superposición o corte en la imagen.
    Diferencia explícitamente circunscripciones con dos o más escaños a optimizar para evitar
    el colapso de categorías categóricas en el eje Y de Plotly y la consiguiente superposición de texto.
    """
    if not result.steps:
        return None

    from collections import Counter
    prov_counts = Counter(s.display_name for s in result.steps)
    prov_seen: Dict[str, int] = {}
    is_en = (get_current_lang() == "en")

    step_data = []
    for s in result.steps:
        # Formateo detallado y compacto de la procedencia del voto
        sources_list = [
            f"{'Abst.' if k == 'Abstención' else k}: +{int(v):,}"
            for k, v in s.votes_source_breakdown.items()
            if v > 0
        ]
        sources_str = " • ".join(sources_list) if sources_list else ("No transfers" if is_en else "Sin trasvase")
        rival = s.seat_taken_from or "Rival"
        beneficiary = s.beneficiary_party
        
        growth_txt = f"+{s.beneficiary_growth_pct:.1f}% part." if s.beneficiary_growth_pct > 0 else ""
        shift_txt = f"+{s.provincial_vote_shift_pct:.2f}% prov." if s.provincial_vote_shift_pct > 0 else ""
        pct_tags = " • ".join(filter(bool, [shift_txt, growth_txt]))
        pct_suffix = f" [{pct_tags}]" if pct_tags else ""

        action_verb = "takes from" if is_en else "quita a"
        for_prep = "for" if is_en else "para"
        # Etiqueta multilínea: línea 1 con votos, beneficiario y rival, línea 2 con fuentes entre paréntesis
        bar_label = f"<b>+{int(s.votes_needed):,} v.{pct_suffix} {for_prep} {beneficiary}</b> ➔ {action_verb} {rival}<br><i>({sources_str})</i>"

        # Etiqueta de circunscripción única por paso para evitar que Plotly agrupe múltiples escaños en la misma coordenada Y
        if prov_counts[s.display_name] > 1:
            prov_seen[s.display_name] = prov_seen.get(s.display_name, 0) + 1
            idx_seat = prov_seen[s.display_name]
            if is_en:
                ord_seat = "1st seat" if idx_seat == 1 else ("2nd seat" if idx_seat == 2 else ("3rd seat" if idx_seat == 3 else f"{idx_seat}th seat"))
            else:
                ord_seat = "1er escaño" if idx_seat == 1 else ("3er escaño" if idx_seat == 3 else f"{idx_seat}º escaño")
            circ_label = f"{s.display_name} ({ord_seat})"
        else:
            circ_label = s.display_name

        step_data.append({
            "Circunscripción": circ_label,
            "Nombre Original": s.display_name,
            "Votos Necesarios": s.votes_needed,
            "Escaño arrebatado a": rival,
            "Beneficiario": beneficiary,
            "Orden": s.seat_order,
            "Procedencia": sources_str,
            "Bar Label": bar_label,
            "Turnout Delta": f"{s.initial_turnout_pct:.1f}% ➔ {s.final_turnout_pct:.1f}%",
            "Bloc Pct Delta": f"{s.initial_bloc_pct:.1f}% ➔ {s.final_bloc_pct:.1f}%",
            "Desplazamiento Prov": f"+{s.provincial_vote_shift_pct:.2f}%",
            "Crecimiento Part": (
                f"+{s.beneficiary_growth_pct:.1f}% (+{getattr(s, 'beneficiary_cumulative_growth_pct', 0.0):.1f}% acum.)"
                if prov_counts[s.display_name] > 1 and getattr(s, "beneficiary_cumulative_growth_pct", 0.0) > s.beneficiary_growth_pct
                else f"+{s.beneficiary_growth_pct:.1f}%"
            ),
        })

    df_steps = pd.DataFrame(step_data)
    # Invertir para que el escaño de máxima prioridad (#1) aparezca en la parte superior
    df_steps = df_steps.iloc[::-1]

    max_v = float(df_steps["Votos Necesarios"].max()) if not df_steps.empty else 1000.0

    # Determinar posición adaptativa del texto: dentro si la barra es amplia (>= 50% del máximo), fuera si es más estrecha
    text_positions = [
        "inside" if v >= 0.50 * max_v else "outside"
        for v in df_steps["Votos Necesarios"]
    ]

    bar_colors = [get_party_color(b) for b in df_steps["Beneficiario"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=df_steps["Circunscripción"],
            x=df_steps["Votos Necesarios"],
            orientation="h",
            marker=dict(
                color=bar_colors,
                line=dict(color="#0F172A", width=1),
            ),
            text=df_steps["Bar Label"],
            textposition=text_positions,
            insidetextanchor="middle",
            cliponaxis=False,
            textfont=dict(color="#000000", size=11, family="sans-serif"),
            insidetextfont=dict(color="#000000", size=11, family="sans-serif"),
            outsidetextfont=dict(color="#000000", size=11, family="sans-serif"),
            hovertemplate=(
                "<b>%{y} (Escaño #%{customdata[0]})</b><br>"
                "<b>Beneficiario del escaño:</b> %{customdata[2]}<br>"
                "<b>Escaño arrebatado a:</b> %{customdata[3]}<br>"
                "<b>Votos adicionales necesarios:</b> +%{x:,.0f}<br>"
                "<b>Desplazamiento provincial:</b> %{customdata[6]}<br>"
                "<b>Crecimiento candidatura:</b> %{customdata[7]}<br>"
                "<b>Procedencia:</b> %{customdata[1]}<br>"
                "<b>Participación estimada:</b> %{customdata[4]}<br>"
                "<b>% Voto Bloque:</b> %{customdata[5]}<extra></extra>"
            ),
            customdata=list(zip(
                df_steps["Orden"],
                df_steps["Procedencia"],
                df_steps["Beneficiario"],
                df_steps["Escaño arrebatado a"],
                df_steps["Turnout Delta"],
                df_steps["Bloc Pct Delta"],
                df_steps["Desplazamiento Prov"],
                df_steps["Crecimiento Part"],
            )),
        )
    )

    # Dimensionamiento dinámico para acomodar 2 líneas por barra sin colisiones verticales ni horizontales
    fig_height = max(380, len(result.steps) * 65)

    # Margen izquierdo dinámico para acomodar nombres de provincia con ordinales sin cortes
    max_label_len = max(len(str(lbl)) for lbl in df_steps["Circunscripción"]) if not df_steps.empty else 10
    left_margin = max(135, min(250, int(max_label_len * 6.5) + 20))

    chart_title = (
        f"<b>Roadmap: Vote Effort and Beneficiary by Constituency ({result.scenario_label})</b>"
        if is_en
        else f"<b>Hoja de Ruta: Esfuerzo de Votos y Beneficiario por Circunscripción ({result.scenario_label})</b>"
    )
    xaxis_title = "<b>Additional Votes Required</b>" if is_en else "<b>Votos Adicionales Requeridos</b>"

    fig.update_layout(
        title=dict(
            text=chart_title,
            font=dict(color="#000000", size=14),
        ),
        xaxis=dict(
            title=dict(text=xaxis_title, font=dict(color="#000000", size=12)),
            tickfont=dict(color="#000000", size=11),
            gridcolor="#E2E8F0",
            range=[0, max_v * 1.45 if max_v > 0 else 10000],
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=11, color="#000000"),
        ),
        bargap=0.35,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        height=fig_height,
        margin=dict(l=left_margin, r=80, t=55, b=45),
    )
    return fig


def create_government_national_scenario_chart(result: GovernmentScenarioResult) -> Optional[go.Figure]:
    """
    Gráfico de barras de escaños del Congreso post-optimización para un escenario específico,
    coloreado según los colores oficiales de cada fuerza política y con línea de mayoría absoluta (176).
    """
    if not result.final_national_seats:
        return None

    parties_seats = [
        (p, s) for p, s in result.final_national_seats.items() if s > 0
    ]
    parties_seats.sort(key=lambda x: -x[1])
    if not parties_seats:
        return None

    parties = [p for p, s in parties_seats]
    seats = [s for p, s in parties_seats]
    colors = [get_party_color(p) for p in parties]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=parties,
        y=seats,
        marker=dict(color=colors, line=dict(color="#0F172A", width=1)),
        text=seats,
        textposition="outside",
        textfont=dict(color="#000000", size=12, family="sans-serif"),
        hovertemplate="<b>%{x}</b>: %{y} diputados<extra></extra>",
    ))
    fig.add_hline(
        y=176,
        line_dash="dash",
        line_color="#000000",
        line_width=1.8,
        annotation_text="<b>Mayoría Absoluta (176)</b>",
        annotation_position="top left",
        annotation_font=dict(color="#000000", size=11, family="sans-serif"),
        annotation_bgcolor="#FFFFFF",
        annotation_bordercolor="#000000",
        annotation_borderwidth=1.2,
    )
    fig.update_layout(
        font=dict(color="#000000", family="sans-serif", size=12),
        title=dict(
            text=f"<b>Composición del Congreso Post-Optimización ({result.scenario_label}) - 350 escaños</b>",
            font=dict(color="#000000", size=14, family="sans-serif"),
        ),
        xaxis=dict(
            title=dict(text="<b>Fuerza Política</b>", font=dict(color="#000000", size=12, family="sans-serif")),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
        ),
        yaxis=dict(
            title=dict(text="<b>Diputados Obtenidos</b>", font=dict(color="#000000", size=12, family="sans-serif")),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
            gridcolor="#E2E8F0",
        ),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        showlegend=False,
        margin=dict(l=50, r=30, t=70, b=60),
    )
    return fig


def create_government_national_comparison_chart(
    res_c: GovernmentScenarioResult,
    res_s: GovernmentScenarioResult,
) -> Optional[go.Figure]:
    """
    Gráfico comparativo de composición del Congreso post-optimización (350 escaños)
    comparando Lista Única vs. Por Separado con línea de mayoría absoluta (176).
    """
    if not res_c.final_national_seats and not res_s.final_national_seats:
        return None

    all_parties = []
    std_order = [
        "PP", "PSOE", "VOX", "Vox", "Lista Única Izquierdas", "Lista Única", "Coalición Izquierda",
        "SUMAR", "Sumar", "PODEMOS", "Podemos", "SALF",
        "ERC", "JUNTS", "Junts", "EH BILDU", "EH Bildu", "EAJ-PNV", "PNV", "BNG", "CC", "UPN"
    ]
    seen = set()
    for p in std_order:
        if (res_c.final_national_seats.get(p, 0) > 0 or res_s.final_national_seats.get(p, 0) > 0) and p not in seen:
            all_parties.append(p)
            seen.add(p)
    for p in list(res_c.final_national_seats.keys()) + list(res_s.final_national_seats.keys()):
        if (res_c.final_national_seats.get(p, 0) > 0 or res_s.final_national_seats.get(p, 0) > 0) and p not in seen:
            all_parties.append(p)
            seen.add(p)

    all_parties.sort(key=lambda p: max(res_c.final_national_seats.get(p, 0), res_s.final_national_seats.get(p, 0)), reverse=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=all_parties,
        y=[res_c.final_national_seats.get(p, 0) for p in all_parties],
        name=res_c.scenario_label,
        marker=dict(color="#8B5CF6", line=dict(color="#4C1D95", width=1)),
        text=[res_c.final_national_seats.get(p, 0) if res_c.final_national_seats.get(p, 0) > 0 else "" for p in all_parties],
        textposition="outside",
        textfont=dict(color="#000000", size=11, family="sans-serif"),
    ))
    fig.add_trace(go.Bar(
        x=all_parties,
        y=[res_s.final_national_seats.get(p, 0) for p in all_parties],
        name=res_s.scenario_label,
        marker=dict(color="#2563EB", line=dict(color="#1E3A8A", width=1)),
        text=[res_s.final_national_seats.get(p, 0) if res_s.final_national_seats.get(p, 0) > 0 else "" for p in all_parties],
        textposition="outside",
        textfont=dict(color="#000000", size=11, family="sans-serif"),
    ))

    fig.add_hline(
        y=176,
        line_dash="dash",
        line_color="#000000",
        line_width=1.8,
        annotation_text="<b>Mayoría Absoluta (176)</b>",
        annotation_position="top left",
        annotation_font=dict(color="#000000", size=11, family="sans-serif"),
        annotation_bgcolor="#FFFFFF",
        annotation_bordercolor="#000000",
        annotation_borderwidth=1.2,
    )

    fig.update_layout(
        barmode="group",
        font=dict(color="#000000", family="sans-serif", size=12),
        title=dict(
            text="<b>Composición del Congreso Post-Optimización (350 escaños)</b><br><sup>Comparativa frente a frente: Lista Única vs. Candidaturas por Separado</sup>",
            font=dict(color="#000000", size=14, family="sans-serif"),
        ),
        xaxis=dict(
            title=dict(text="<b>Fuerza Política</b>", font=dict(color="#000000", size=12, family="sans-serif")),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
        ),
        yaxis=dict(
            title=dict(text="<b>Diputados Obtenidos</b>", font=dict(color="#000000", size=12, family="sans-serif")),
            tickfont=dict(color="#000000", size=11, family="sans-serif"),
            gridcolor="#E2E8F0",
        ),
        legend=dict(
            font=dict(color="#000000", size=11),
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        margin=dict(l=50, r=30, t=80, b=60),
    )
    return fig


def render_government_formation_section(
    model: SpanishElectoralModel,
    sim_sep: NationalSimulationResult,
    sim_coal: NationalSimulationResult,
    section_key: str,
    coalition_name: str = "Lista Única",
    coalition_members: Optional[List[str]] = None,
    default_target: int = 176,
    focus_province: Optional[str] = None,
):
    """
    Renderiza la sección interactiva de optimización de gobernabilidad y mayoría absoluta (176 escaños)
    al final de cualquier pestaña de la aplicación.
    """
    members = list(coalition_members or ["Sumar", "Podemos"])

    # Obtener dinámicamente todas las fuerzas políticas activas en la simulación o modelo
    all_sim_parties_set = set()
    for sim in (sim_sep, sim_coal):
        if sim is not None:
            if hasattr(sim, "national_votes_est") and sim.national_votes_est:
                all_sim_parties_set.update(sim.national_votes_est.keys())
            if hasattr(sim, "national_seats") and sim.national_seats:
                all_sim_parties_set.update(sim.national_seats.keys())
    if model is not None and hasattr(model, "parties") and model.parties:
        all_sim_parties_set.update(model.parties)

    # Excluir votos no computables como candidaturas
    excluded_names = {"Votos Blancos", "Nulos", "Censo", "Participación"}
    all_sim_parties = sorted([p for p in all_sim_parties_set if p and p not in excluded_names])

    # Socios externos disponibles: cualquier partido de la simulación excluyendo a los que ya integran la coalición
    available_external_partners = sorted([
        p for p in all_sim_parties
        if p not in (set(members) | {coalition_name, "Otros"})
    ])

    # Socios por defecto: PSOE, ERC, EH Bildu, BNG (siempre que no estén ya en la propia candidatura única)
    default_pact_partners = [
        p for p in ["PSOE", "ERC", "EH Bildu", "BNG"]
        if p in available_external_partners
    ]

    # Sincronización reactiva con la simulación previa:
    # Cuando cambian los integrantes o denominación de la lista única definidos arriba en la simulación,
    # el optimizador detecta la nueva firma y sincroniza automáticamente todas sus opciones y selecciones.
    current_coal_sig = (tuple(sorted(members)), coalition_name)
    sig_key = f"{section_key}_active_coal_sig"
    if st.session_state.get(sig_key) != current_coal_sig:
        st.session_state[sig_key] = current_coal_sig

        # 1. Limpiar o sincronizar socios del pacto externos
        if f"{section_key}_gov_partners" in st.session_state:
            curr_sel_pact = st.session_state[f"{section_key}_gov_partners"]
            st.session_state[f"{section_key}_gov_partners"] = [
                p for p in curr_sel_pact if p in available_external_partners
            ]
        else:
            st.session_state[f"{section_key}_gov_partners"] = default_pact_partners

        # 2. Limpiar socios optimizables externos
        if f"{section_key}_gov_optimizable_partners" in st.session_state:
            st.session_state[f"{section_key}_gov_optimizable_partners"] = [
                p for p in st.session_state[f"{section_key}_gov_optimizable_partners"]
                if p in available_external_partners
            ]

        # 3. Heredar automáticamente topes de crecimiento provincial para los nuevos integrantes de la lista única
        st.session_state[f"{section_key}_gov_cap_parties_selected"] = sorted(list(set([coalition_name] + members)))

        # 4. Heredar automáticamente caladeros específicos para los nuevos integrantes de la lista única
        st.session_state[f"{section_key}_gov_por_parties_selected"] = sorted(list(set([coalition_name] + members)))

    # Asegurar que st.session_state[f"{section_key}_gov_partners"] esté saneado en cada ciclo de render
    if f"{section_key}_gov_partners" in st.session_state:
        st.session_state[f"{section_key}_gov_partners"] = [
            p for p in st.session_state[f"{section_key}_gov_partners"]
            if p in available_external_partners
        ]

    with st.container(border=True):
        st.markdown(t("gov_section_title", target=default_target))
        st.markdown(t("gov_section_desc", target=default_target))

        c_pact, c_target_col = st.columns([3, 2])
        with c_pact:
            st.markdown(t("gov_pact_partners_title"))
            st.info(
                f"ℹ️ **Pacto de gobierno:** **{coalition_name}** ({', '.join(members)}) ya está incluida en el cómputo del pacto. "
                f"A continuación, selecciona el resto de socios para sumar la mayoría de investidura (los partidos ya integrados en la candidatura única no se muestran aquí para evitar duplicidades):"
            )
            selected_partners = st.multiselect(
                t("partners_label"),
                options=available_external_partners,
                default=default_pact_partners,
                help="Selecciona los demás partidos con los que se conformaría la mayoría de investidura. Cualquier nuevo partido añadido al simulador aparecerá aquí dinámicamente.",
                key=f"{section_key}_gov_partners",
            )

            # Desacople: partidos del pacto que pueden recibir votos en campaña (por defecto congelados)
            optimizable_options = [p for p in selected_partners if p in available_external_partners]
            if f"{section_key}_gov_optimizable_partners" in st.session_state:
                st.session_state[f"{section_key}_gov_optimizable_partners"] = [
                    p for p in st.session_state[f"{section_key}_gov_optimizable_partners"]
                    if p in optimizable_options
                ]
            selected_optimizable = st.multiselect(
                t("optimizable_partners_label"),
                options=optimizable_options,
                default=[],
                help="Por defecto los partidos externos están CONGELADOS: aportan sus escaños base al pacto pero no compiten por votos adicionales de campaña. Si marcas alguno (ej. BNG o PSOE), el optimizador evaluará si es más eficiente ganar el escaño para ellos en circunscripciones clave.",
                key=f"{section_key}_gov_optimizable_partners",
            )
            if not selected_optimizable and selected_partners:
                st.caption("🔒 *Todos los partidos externos permanecen congelados con sus escaños base del sondeo.*")
            elif selected_optimizable:
                st.caption(f"⚡ *Optimizando esfuerzo conjunto para: {', '.join([coalition_name] + selected_optimizable)}*")

        with c_target_col:
            st.markdown(t("gov_target_title"))
            target_seats = st.number_input(
                t("target_seats_label"),
                min_value=150,
                max_value=220,
                value=int(default_target),
                step=1,
                help="176 escaños otorga la mayoría absoluta en el Congreso de los Diputados (350 escaños).",
                key=f"{section_key}_gov_target_seats",
            )
            cur_sep_bloc = sum(sim_sep.national_seats.get(p, 0) for p in (set(members) | set(selected_partners)))
            cur_coal_bloc = sim_coal.national_seats.get(coalition_name, 0) + sum(sim_coal.national_seats.get(p, 0) for p in selected_partners)
            st.caption(f"**Escaños actuales del bloque:** 🟣 {coalition_name}: **{cur_coal_bloc} dip.** | 🔵 Por Separado ({', '.join(members)}): **{cur_sep_bloc} dip.**")

        st.markdown("##### 📍 Estrategia Territorial (Circunscripciones Objetivo):")
        scope_choice = st.radio(
            "Ámbito territorial de optimización:",
            [
                "🌍 Toda España (Búsqueda del óptimo global absoluto entre las 52 circunscripciones)",
                "🎯 Seleccionar circunscripciones específicas de campaña",
            ],
            key=f"{section_key}_gov_scope_choice",
        )

        all_prov_names = model.get_constituency_names()
        selected_provinces = None
        if "Seleccionar" in scope_choice:
            prov_key = f"{section_key}_gov_selected_provs"
            all_ccaa_names = list(CCAA_PROVINCES.keys())

            # Asegurar inicialización: por defecto todas las provincias seleccionadas
            if not isinstance(st.session_state.get(prov_key), list):
                st.session_state[prov_key] = list(all_prov_names)

            # Por defecto todas las zonas marcadas
            for c_name in all_ccaa_names:
                z_k = f"{section_key}_zone_{c_name}"
                if z_k not in st.session_state:
                    st.session_state[z_k] = True

            def _on_zone_toggle(c_name_to_toggle: str, z_k_to_check: str):
                is_on = bool(st.session_state.get(z_k_to_check, False))
                current_selected = list(st.session_state.get(prov_key, []))
                ccaa_p_list = CCAA_PROVINCES.get(c_name_to_toggle, [])
                if is_on:
                    for p in ccaa_p_list:
                        if p not in current_selected:
                            current_selected.append(p)
                else:
                    current_selected = [p for p in current_selected if p not in ccaa_p_list]
                st.session_state[prov_key] = [p for p in all_prov_names if p in current_selected]

            def _select_all_zones():
                for c_name in all_ccaa_names:
                    st.session_state[f"{section_key}_zone_{c_name}"] = True
                st.session_state[prov_key] = list(all_prov_names)

            def _deselect_all_zones():
                for c_name in all_ccaa_names:
                    st.session_state[f"{section_key}_zone_{c_name}"] = False
                st.session_state[prov_key] = []

            btn_col1, btn_col2, btn_info = st.columns([1.5, 1.5, 5])
            with btn_col1:
                st.button("✅ Marcar todas", on_click=_select_all_zones, key=f"{section_key}_btn_all_zones")
            with btn_col2:
                st.button("❌ Desmarcar todas", on_click=_deselect_all_zones, key=f"{section_key}_btn_none_zones")
            with btn_info:
                active_p_count = len(st.session_state.get(prov_key, all_prov_names))
                st.caption(f"📍 **{active_p_count} de {len(all_prov_names)} circunscripciones** activas para la optimización.")

            with st.expander("🏛️ Zonas Predefinidas: Comunidades y Ciudades Autónomas (19)", expanded=True):
                z_cols = st.columns(4)
                for idx, c_name in enumerate(all_ccaa_names):
                    col_target = z_cols[idx % 4]
                    num_p = len(CCAA_PROVINCES[c_name])
                    z_k = f"{section_key}_zone_{c_name}"
                    col_target.checkbox(
                        f"{c_name} ({num_p})",
                        key=z_k,
                        on_change=_on_zone_toggle,
                        args=(c_name, z_k),
                    )

            selected_provinces = st.multiselect(
                "Circunscripciones seleccionadas (puedes añadir o quitar provincias individuales):",
                options=all_prov_names,
                default=st.session_state.get(prov_key, all_prov_names) if prov_key not in st.session_state else None,
                format_func=get_province_display_name,
                key=prov_key,
                help="El optimizador de campaña explorará exclusivamente escaños en estas circunscripciones.",
            )

            if not selected_provinces and isinstance(st.session_state.get(prov_key), list):
                selected_provinces = st.session_state[prov_key]

            if not selected_provinces or len(selected_provinces) == 0:
                st.warning("⚠️ No has seleccionado ninguna circunscripción. Marca al menos una Comunidad Autónoma o añade provincias para optimizar.")

        st.markdown("##### 🧭 Criterio de Eficiencia y Optimización de Campaña:")
        criterion_choice = st.radio(
            "Criterio para priorizar qué escaños disputar primero:",
            [
                "📊 Puntos % Provinciales (Δ% prov) — Minimiza el desplazamiento en el electorado provincial (neutraliza el sesgo de provincias pequeñas)",
                "🏛️ Crecimiento % del Partido (Δ% partido) — Minimiza el esfuerzo orgánico y exigencia de crecimiento a la candidatura",
                "⚖️ Híbrido Ponderado (Provincia + Partido) — Media geométrica ponderada entre opinión pública y aparato de partido",
                "🔢 Votos Brutos Absolutos (ΔV) — Mínimo cuantitativo de votos en bruto (suelo teórico tradicional)",
            ],
            index=0,
            help="Define la función objetivo marginal con la que el optimizador escoge la siguiente circunscripción a disputar.",
            key=f"{section_key}_gov_criterion_choice",
        )

        hybrid_alpha_val = 0.50
        if "Híbrido Ponderado" in criterion_choice:
            col_a1, col_a2 = st.columns([3, 2])
            with col_a1:
                hybrid_alpha_val = st.slider(
                    "Ponderación del esfuerzo (α):",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.50,
                    step=0.05,
                    format="α = %.2f",
                    help="α = 0.0 equivale al criterio provincial puro (100% opinión pública); α = 1.0 equivale al criterio de partido puro (100% aparato).",
                    key=f"{section_key}_gov_hybrid_alpha",
                )
            with col_a2:
                pct_prov_weight = int(round((1.0 - hybrid_alpha_val) * 100))
                pct_party_weight = int(round(hybrid_alpha_val * 100))
                st.caption(
                    f"📐 **Media geométrica ponderada Cobb-Douglas:**  \n"
                    f"$$\\text{{Coste}} = (\\Delta \\%_{{\\text{{prov}}}})^{{1 - \\alpha}} \\times (\\Delta \\%_{{\\text{{partido}}}})^{{\\alpha}}$$  \n"
                    f"🔹 Opinión pública provincial: **{pct_prov_weight}%** | 🔹 Esfuerzo orgánico: **{pct_party_weight}%**"
                )
        elif "Puntos %" in criterion_choice:
            st.caption("ℹ️ **Criterio Provincial:** Iguala las circunscripciones grandes y pequeñas según el porcentaje de votantes provinciales a convencer.")
        elif "Partido" in criterion_choice:
            st.caption("ℹ️ **Criterio de Partido:** Prioriza escaños donde las candidaturas no tengan que multiplicar excesivamente sus votos previos.")
        else:
            st.caption("ℹ️ **Criterio de Votos Brutos:** Minimiza la suma matemática absoluta de votos en toda España.")

        if "Puntos %" in criterion_choice:
            opt_criterion = "provincial_pct"
        elif "Partido" in criterion_choice:
            opt_criterion = "party_growth_pct"
        elif "Híbrido" in criterion_choice:
            opt_criterion = "hybrid"
        else:
            opt_criterion = "absolute_votes"

        with st.expander("⚙️ Restricciones Avanzadas: Caladeros de Voto, Movilización y Porosidad Dinámica", expanded=False):
            col_abst, col_don = st.columns(2)
            with col_abst:
                st.markdown("**1. Movilización de la Abstención (Voto Nuevo):**")
                allow_abst = st.checkbox(
                    "Permitir captación de votantes abstencionistas",
                    value=True,
                    help="Si se desactiva, la participación se congela y los votos solo podrán obtenerse de trasvases entre candidaturas.",
                    key=f"{section_key}_gov_allow_abst",
                )
                max_turnout_inc = st.slider(
                    "Incremento máximo de participación admitido (puntos %):",
                    min_value=0.5,
                    max_value=10.0,
                    value=4.0,
                    step=0.5,
                    format="+%.1f%%",
                    disabled=not allow_abst,
                    help="Cota superior realista para evitar incrementos inverosímiles de la afluencia a las urnas.",
                    key=f"{section_key}_gov_max_turnout",
                )
                st.caption("🔒 Cota física: En ningún caso el número de votos emitidos superará el 100% del censo electoral provincial.")

            with col_don:
                st.markdown("**2. Trasvases desde Otras Fuerzas (Porosidad Dinámica):**")
                shield_partners = st.checkbox(
                    "🛡️ Blindar a los socios de investidura (No restar votos a PSOE, ERC, Bildu, etc.)",
                    value=True,
                    help="Evita el 'fuego amigo': no debilita a los socios para no provocar pérdidas colaterales de escaños en el propio bloque. Este blindaje tiene prioridad absoluta y NO se sobrescribe por la Sección 4.",
                    key=f"{section_key}_gov_shield_partners",
                )

                # Partidos potencialmente donantes: todos los partidos de la simulación excepto miembros de la coalición
                potential_donors = sorted([
                    p for p in all_sim_parties
                    if p not in (set(members) | {coalition_name})
                ])
                default_donors = [p for p in ["Otros", "PP", "SALF"] if p in potential_donors]

                selected_donors = st.multiselect(
                    "Seleccionar partidos de los que captar votos (partidos donantes):",
                    options=potential_donors,
                    default=default_donors,
                    help="Puedes seleccionar cualquier fuerza política existente o añadida para calibrar su porcentaje de trasvase.",
                    key=f"{section_key}_gov_selected_donors",
                )

            donor_map = {}
            if selected_donors:
                st.caption(
                    "ℹ️ **Regla general de porosidad:** Estos porcentajes aplican por defecto a todas las candidaturas "
                    "del bloque en ambos escenarios. En la **Sección 4** puedes definir caladeros específicos por candidatura "
                    "que **sobrescribirán los porcentajes de esta sección**, salvo **el blindaje de socios, que no se sobrescribe**. "
                    "Si el blindaje está activado arriba, ningún socio cederá votos; para permitir trasvases entre socios (ej. PSOE ➔ Sumar), "
                    "debes desmarcar la casilla de blindaje aquí."
                )
                st.markdown("**Calibración de trasvase por partido seleccionado:**")
                cols_d = st.columns(min(3, len(selected_donors)))
                for idx, d_party in enumerate(selected_donors):
                    with cols_d[idx % len(cols_d)]:
                        if d_party == "Otros":
                            def_val, max_val = 25.0, 50.0
                        elif d_party == "PP":
                            def_val, max_val = 4.0, 20.0
                        elif d_party == "SALF":
                            def_val, max_val = 5.0, 25.0
                        elif d_party == "Vox":
                            def_val, max_val = 0.0, 15.0
                        else:
                            def_val, max_val = 5.0, 30.0

                        p_val = st.slider(
                            f"Porosidad desde **{d_party}** (% máx):",
                            min_value=0.0,
                            max_value=float(max_val),
                            value=float(def_val),
                            step=1.0,
                            format="%.0f%%",
                            key=f"{section_key}_gov_t_{d_party}",
                        )
                        if shield_partners and d_party in selected_partners:
                            st.caption("🛡️ *Blindado por ser socio de investidura*")
                        donor_map[d_party] = p_val / 100.0

            st.markdown("---")
            st.markdown("**3. Topes de Crecimiento Máximo por Circunscripción (Realismo Electoral):**")
            st.caption("Fija el porcentaje de crecimiento adicional máximo que un partido puede experimentar sobre sus votos base en una provincia (evita duplicar o triplicar votos de forma irrealista).")

            # Partidos del pacto disponibles para configurar topes (coalición, integrantes y socios de investidura)
            all_pact_parties = sorted(list(set([coalition_name] + members + selected_partners)))
            default_cap_parties = sorted(list(set([coalition_name] + members + selected_optimizable)))
            if f"{section_key}_gov_cap_parties_selected" in st.session_state:
                st.session_state[f"{section_key}_gov_cap_parties_selected"] = [
                    p for p in st.session_state[f"{section_key}_gov_cap_parties_selected"]
                    if p in all_pact_parties
                ]
                for req_p in [coalition_name] + members:
                    if req_p in all_pact_parties and req_p not in st.session_state[f"{section_key}_gov_cap_parties_selected"]:
                        st.session_state[f"{section_key}_gov_cap_parties_selected"].append(req_p)
                st.session_state[f"{section_key}_gov_cap_parties_selected"] = sorted(st.session_state[f"{section_key}_gov_cap_parties_selected"])

            selected_cap_parties = st.multiselect(
                "Partidos del pacto para calibrar tope de crecimiento provincial:",
                options=all_pact_parties,
                default=default_cap_parties,
                help="Puedes añadir cualquier partido del pacto de gobierno (ej. PSOE, BNG, ERC, PNV...) para limitar su crecimiento máximo por circunscripción.",
                key=f"{section_key}_gov_cap_parties_selected",
            )
            cap_cols = st.columns(min(3, max(1, len(selected_cap_parties))))
            party_growth_caps = {}
            for idx, r_party in enumerate(selected_cap_parties):
                with cap_cols[idx % len(cap_cols)]:
                    cap_val = st.slider(
                        f"Crecimiento máx. de **{r_party}** en provincia (%):",
                        min_value=15.0,
                        max_value=150.0,
                        value=80.0,
                        step=5.0,
                        format="+%.0f%%",
                        help=f"Si {r_party} tiene 20.000 votos en una circunscripción, con +50% podrá captar como máximo 10.000 votos extra en ella.",
                        key=f"{section_key}_gov_cap_{r_party}",
                    )
                    party_growth_caps[r_party] = cap_val

            st.markdown("---")
            st.markdown("**4. Porosidad Específica Partido a Partido (Caladeros Diferenciados):**")
            enable_custom_porosity = st.checkbox(
                "Calibrar caladeros de trasvase específicos para cada candidatura (ej. PSOE capta de Sumar, Sumar capta de PP)",
                value=False,
                help="Permite definir qué partidos nutren a cada candidatura de forma diferenciada.",
                key=f"{section_key}_gov_custom_porosity_en",
            )
            custom_porosity_map = {}
            selected_por_parties = []
            if enable_custom_porosity:
                st.info(
                    "💡 **Independencia de Caladeros entre Escenarios y Blindaje:**  \n"
                    f"• **🟣 {coalition_name}:** El caladero que configures aquí aplica **únicamente al escenario Con {coalition_name}**.  \n"
                    f"• **🔵 Candidaturas por separado ({', '.join(members)}):** Sus caladeros aplican **únicamente al escenario Por Separado**.  \n"
                    "• **🏛️ Socios externos (ej. PSOE, BNG, etc.):** Su caladero se aplica a su candidatura en **ambos escenarios**.  \n"
                    "• **🛡️ Blindaje de socios:** Esta sección sobrescribe las tasas de la Sección 2, pero **el blindaje de socios NO se sobrescribe**. "
                    "Si el blindaje está activado en la Sección 2, ningún socio cederá votos aunque lo configures aquí; "
                    "para permitir trasvases entre socios (ej. PSOE ➔ Sumar), debes desactivar el blindaje en la Sección 2."
                )
                if f"{section_key}_gov_por_parties_selected" in st.session_state:
                    st.session_state[f"{section_key}_gov_por_parties_selected"] = [
                        p for p in st.session_state[f"{section_key}_gov_por_parties_selected"]
                        if p in all_pact_parties
                    ]
                    for req_p in [coalition_name] + members:
                        if req_p in all_pact_parties and req_p not in st.session_state[f"{section_key}_gov_por_parties_selected"]:
                            st.session_state[f"{section_key}_gov_por_parties_selected"].append(req_p)
                    st.session_state[f"{section_key}_gov_por_parties_selected"] = sorted(st.session_state[f"{section_key}_gov_por_parties_selected"])

                selected_por_parties = st.multiselect(
                    "Partidos del pacto para calibrar caladeros específicos de procedencia:",
                    options=all_pact_parties,
                    default=default_cap_parties,
                    help="Puedes añadir cualquier partido del pacto de gobierno para definir de qué fuerzas y en qué porcentaje capta votos.",
                    key=f"{section_key}_gov_por_parties_selected",
                )
                st.caption("Configura de qué partidos y hasta qué porcentaje puede nutrirse cada candidatura seleccionada:")
                for r_party in selected_por_parties:
                    if r_party == coalition_name:
                        exp_title = f"🟣 Caladero para **{r_party}** *(exclusivo para escenario Con Lista Única)*"
                    elif r_party in members:
                        exp_title = f"🔵 Caladero para **{r_party}** *(exclusivo para escenario Por Separado)*"
                    else:
                        exp_title = f"🏛️ Caladero para **{r_party}** *(aplica en ambos escenarios)*"

                    with st.expander(exp_title, expanded=False):
                        r_potential_donors = [p for p in all_sim_parties if p != r_party and p not in (set(members) if r_party == coalition_name else set())]
                        r_def_donors = [p for p in selected_donors if p in r_potential_donors]
                        r_chosen_donors = st.multiselect(
                            f"Partidos de los que **{r_party}** puede captar votos:",
                            options=r_potential_donors,
                            default=r_def_donors,
                            key=f"{section_key}_por_donors_{r_party}",
                        )
                        r_donor_rates = {}
                        if r_chosen_donors:
                            c_sub = st.columns(min(3, len(r_chosen_donors)))
                            for s_idx, d_p in enumerate(r_chosen_donors):
                                with c_sub[s_idx % len(c_sub)]:
                                    def_rate = donor_map.get(d_p, 0.05) * 100.0
                                    rate_val = st.slider(
                                        f"Trasvase {d_p} ➔ {r_party}:",
                                        min_value=0.0,
                                        max_value=40.0,
                                        value=float(def_rate),
                                        step=1.0,
                                        format="%.0f%%",
                                        key=f"{section_key}_por_rate_{r_party}_{d_p}",
                                    )
                                    if shield_partners and d_p in selected_partners:
                                        st.caption("🛡️ *Inactivo: blindaje de socios activo en Sección 2*")
                                    r_donor_rates[d_p] = rate_val / 100.0
                        custom_porosity_map[r_party] = r_donor_rates

        # Modulador de Swing Previo Opcional (Evolución de Campaña / Tracking)
        with st.expander("📈 Modulador de Swing Previo Opcional (Evolución de Campaña / Tracking)", expanded=False):
            st.info(
                "ℹ️ **Si el sondeo es reciente, deja todos los valores en 0.0%** para utilizar la encuesta de forma nativa. "
                "Usa este modulador únicamente para simular desgaste o crecimiento de partidos durante la campaña electoral. "
                "La suma total de porcentajes se estabiliza automáticamente al 100.0% combinando abstención y trasvases."
            )
            c_sw_prop, c_sw_p = st.columns([2, 3])
            with c_sw_prop:
                st.markdown("**Caladero del Swing (Composición de Procedencia):**")
                swing_abst_pct = st.slider(
                    "Proporción de Abstención (Nuevos votantes) vs. Trasvases:",
                    min_value=0,
                    max_value=100,
                    value=50,
                    step=10,
                    format="%d%% Abstención",
                    help="100% = el crecimiento procede íntegramente de nuevos votantes movilizados; 0% = procede exclusivamente de trasvases desde otros partidos.",
                    key=f"{section_key}_gov_swing_abst_pct",
                )
                st.caption(f"🔹 **{swing_abst_pct}%** procede de la Abstención (expansión de participación)  \n🔹 **{100 - swing_abst_pct}%** procede de trasvases desde partidos donantes.")

            with c_sw_p:
                st.markdown("**Partidos con variación previa estimada:**")
                sw_parties_selected = st.multiselect(
                    "Selecciona los partidos a los que aplicar swing previo:",
                    options=all_sim_parties,
                    default=[],
                    help="Solo se mostrarán controles para los partidos que decidas alterar. El resto permanecerá al 0.0%.",
                    key=f"{section_key}_gov_sw_parties_selected",
                )

            prior_swings = {}
            if sw_parties_selected:
                st.markdown("**Variación porcentual previa por partido (puntos %):**")
                sw_cols = st.columns(min(3, len(sw_parties_selected)))
                for idx, sw_p in enumerate(sw_parties_selected):
                    with sw_cols[idx % len(sw_cols)]:
                        sw_val = st.slider(
                            f"Swing para **{sw_p}** (puntos %):",
                            min_value=-5.0,
                            max_value=5.0,
                            value=0.0,
                            step=0.1,
                            format="%+.1f%%",
                            key=f"{section_key}_gov_sw_val_{sw_p}",
                        )
                        if abs(sw_val) >= 0.05:
                            prior_swings[sw_p] = sw_val

        # Un socio externo compite activamente por votos si está en selected_optimizable
        # o si se le han configurado caladeros específicos en la Sección 4
        active_custom_recipients = [
            p for p in selected_por_parties
            if p in selected_partners and p in custom_porosity_map and len(custom_porosity_map[p]) > 0
        ] if enable_custom_porosity else []
        effective_optimizable = sorted(list(set(selected_optimizable + active_custom_recipients)))

        # Configurar y ejecutar optimizador
        cfg = GovernmentOptimizationConfig(
            target_seats=int(target_seats),
            coalition_members=members,
            coalition_name=coalition_name,
            government_partners=selected_partners,
            target_provinces=selected_provinces if "Seleccionar" in scope_choice else None,
            allow_abstention=allow_abst,
            max_turnout_increase_pct=max_turnout_inc,
            donor_parties_max_transfer_pct=donor_map,
            shield_partners=shield_partners,
            optimizable_partners=effective_optimizable,
            prior_swing_pct=prior_swings,
            prior_swing_abstention_share=float(swing_abst_pct) / 100.0 if "swing_abst_pct" in locals() else 0.50,
            party_porosity=custom_porosity_map if enable_custom_porosity else {},
            max_party_growth_pct=party_growth_caps,
            optimization_criterion=opt_criterion,
            hybrid_alpha=float(hybrid_alpha_val),
        )

        optimizer = GovernmentOptimizer(model=model)
        gov_res = optimizer.optimize(sim_sep=sim_sep, sim_coal=sim_coal, config=cfg)

        st.markdown("#### ⚖️ Comparativa de Esfuerzo Electoral para Gobernar:")
        c_m_coal, c_m_sep = st.columns(2)

        res_c = gov_res.coalition_result
        res_s = gov_res.separated_result

        with c_m_coal:
            with st.container(border=True):
                st.markdown(f"##### {res_c.scenario_label}")
                if res_c.target_achieved:
                    if res_c.total_votes_needed == 0:
                        st.success(f"🎉 **¡Objetivo Cumplido!** El bloque ya cuenta con **{res_c.initial_bloc_seats} escaños** (supera los {target_seats}).")
                    else:
                        st.metric(
                            "Votos Adicionales Necesarios",
                            f"+{int(res_c.total_votes_needed):,} votos",
                            delta=f"{res_c.final_bloc_seats} / 350 escaños (+{res_c.seats_gained} dip.)",
                            delta_color="normal",
                        )
                        st.markdown(f"📊 **Movilización nacional extra:** +{int(res_c.total_votes_needed):,} votos (+{res_c.national_pct_increase:.2f}% de votos válidos)")
                        
                        # Procedencia nacional agregada
                        c_sources = ", ".join([f"{k}: +{int(v):,}" for k, v in res_c.national_sources_breakdown.items() if v > 0])
                        if c_sources:
                            st.markdown(f"📥 **Procedencia del voto:** {c_sources}")
                        
                        # Escaños extra y a quién se los quita
                        c_taken = ", ".join([f"**-{count}** a {party}" for party, count in res_c.national_seats_taken.items()])
                        if c_taken:
                            st.markdown(f"🎯 **Escaños arrebatados:** {c_taken}")
                        
                        crit_badge_c = {
                            "provincial_pct": "Puntos % Provinciales",
                            "party_growth_pct": "Crecimiento % del Partido",
                            "hybrid": f"Híbrido Ponderado (α={res_c.hybrid_alpha:.2f})",
                            "absolute_votes": "Votos Brutos Absolutos",
                        }.get(res_c.optimization_criterion, res_c.optimization_criterion)
                        st.caption(f"🧭 Criterio: **{crit_badge_c}** | 📍 Despliegue en **{len(res_c.provinces_involved)} circunscripciones** estratégicas.")
                else:
                    st.warning(f"⚠️ **Techo alcanzado:** {res_c.final_bloc_seats} / {target_seats} escaños")
                    st.caption(res_c.impossibility_reason)

        with c_m_sep:
            with st.container(border=True):
                st.markdown(f"##### {res_s.scenario_label}")
                if res_s.target_achieved:
                    if res_s.total_votes_needed == 0:
                        st.success(f"🎉 **¡Objetivo Cumplido!** El bloque ya cuenta con **{res_s.initial_bloc_seats} escaños**.")
                    else:
                        st.metric(
                            "Votos Adicionales Necesarios",
                            f"+{int(res_s.total_votes_needed):,} votos",
                            delta=f"{res_s.final_bloc_seats} / 350 escaños (+{res_s.seats_gained} dip.)",
                            delta_color="normal",
                        )
                        st.markdown(f"📊 **Movilización nacional extra:** +{int(res_s.total_votes_needed):,} votos (+{res_s.national_pct_increase:.2f}% de votos válidos)")
                        
                        # Procedencia nacional agregada
                        s_sources = ", ".join([f"{k}: +{int(v):,}" for k, v in res_s.national_sources_breakdown.items() if v > 0])
                        if s_sources:
                            st.markdown(f"📥 **Procedencia del voto:** {s_sources}")
                        
                        # Escaños extra y a quién se los quita
                        s_taken = ", ".join([f"**-{count}** a {party}" for party, count in res_s.national_seats_taken.items()])
                        if s_taken:
                            st.markdown(f"🎯 **Escaños arrebatados:** {s_taken}")
                        
                        crit_badge_s = {
                            "provincial_pct": "Puntos % Provinciales",
                            "party_growth_pct": "Crecimiento % del Partido",
                            "hybrid": f"Híbrido Ponderado (α={res_s.hybrid_alpha:.2f})",
                            "absolute_votes": "Votos Brutos Absolutos",
                        }.get(res_s.optimization_criterion, res_s.optimization_criterion)
                        st.caption(f"🧭 Criterio: **{crit_badge_s}** | 📍 Despliegue en **{len(res_s.provinces_involved)} circunscripciones** estratégicas.")
                else:
                    st.warning(f"⚠️ **Techo alcanzado:** {res_s.final_bloc_seats} / {target_seats} escaños")
                    st.caption(res_s.impossibility_reason)

        if res_c.target_achieved and res_s.target_achieved and res_c.total_votes_needed > 0 and res_s.total_votes_needed > 0:
            if gov_res.votes_savings_with_coalition > 0:
                pct_saving = (gov_res.votes_savings_with_coalition / res_s.total_votes_needed) * 100.0
                diff_provs = len(res_s.provinces_involved) - len(res_c.provinces_involved)
                prov_text = f" y **{diff_provs} provincias menos** de despliegue territorial" if diff_provs > 0 else ""
                st.success(f"💡 **Ventaja Estratégica de {coalition_name}:** Concurrir juntos requiere **{int(gov_res.votes_savings_with_coalition):,} votos MENOS (-{pct_saving:.1f}%)**{prov_text} para investir presidente.")
            elif res_c.total_votes_needed == res_s.total_votes_needed:
                st.info("⚪ **Esfuerzo similar:** Ambos escenarios requieren prácticamente la misma movilización de votos.")
            else:
                st.info(f"🔵 **Ventaja Estratégica de Separados:** Concurrir por separado requiere **{int(res_c.total_votes_needed - res_s.total_votes_needed):,} votos menos** bajo esta configuración concreta.")

        # Hoja de ruta interactiva para ambos escenarios con pestañas y claves únicas para evitar duplicados
        st.markdown("---")
        st.markdown("##### 📋 Hoja de Ruta y Despliegue Territorial por Escenario:")

        pact_partners_set = set(cfg.government_partners)
        pact_parties_coal = {coalition_name} | pact_partners_set
        pact_parties_sep = set(members) | pact_partners_set

        def _build_party_movements_df(res: GovernmentScenarioResult, pact_parties: Set[str]) -> pd.DataFrame:
            all_parties = []
            seen = set()
            for p in list(res.final_national_seats.keys()) + list(res.initial_national_seats.keys()) + list(res.final_national_votes.keys()):
                if p not in seen:
                    all_parties.append(p)
                    seen.add(p)

            all_parties.sort(
                key=lambda p: (
                    p in pact_parties,
                    res.final_national_seats.get(p, 0),
                    res.final_national_votes.get(p, 0.0),
                ),
                reverse=True,
            )

            rows = []
            for p in all_parties:
                init_s = res.initial_national_seats.get(p, 0)
                fin_s = res.final_national_seats.get(p, 0)
                init_v = res.initial_national_votes.get(p, 0.0)
                fin_v = res.final_national_votes.get(p, 0.0)
                init_p = res.initial_national_pct.get(p, 0.0)
                fin_p = res.final_national_pct.get(p, 0.0)

                diff_s = fin_s - init_s
                diff_v = fin_v - init_v
                diff_p = fin_p - init_p

                if init_s == 0 and fin_s == 0 and init_v == 0 and fin_v == 0:
                    continue

                pct_growth = (diff_v / init_v * 100.0) if init_v > 0 else 0.0
                pct_growth_str = f"{pct_growth:+.2f}%" if abs(pct_growth) >= 0.01 else "="

                rol = "🏛️ Pacto de Gobierno" if p in pact_parties else "⚔️ Oposición / Externo"
                diff_s_str = f"{diff_s:+d}" if diff_s != 0 else "="
                diff_v_str = f"{int(diff_v):+,}" if int(diff_v) != 0 else "="
                diff_p_str = f"{diff_p:+.2f}%" if abs(diff_p) >= 0.01 else "="

                # Procedencia o destino de los votos
                if diff_v > 0:
                    p_srcs = res.party_sources(p)
                    src_items = [f"{'Abst.' if k == 'Abstención' else k}: +{int(v):,}" for k, v in p_srcs.items() if v > 0]
                    proc_str = " • ".join(src_items) if src_items else f"+{int(diff_v):,} v."
                elif diff_v < 0:
                    p_dons = res.party_donations(p)
                    don_items = [f"➔ {k}: -{int(v):,}" for k, v in p_dons.items() if v > 0]
                    proc_str = " • ".join(don_items) if don_items else f"Cedidos: {int(diff_v):,}"
                else:
                    proc_str = "Sin trasvases"

                rows.append({
                    "Candidatura": p,
                    "Rol": rol,
                    "Escaños Inicial ➔ Final": f"{init_s} ➔ {fin_s}",
                    "Δ Escaños": diff_s_str,
                    "Votos Inicial ➔ Final": f"{int(init_v):,} ➔ {int(fin_v):,}",
                    "Δ Votos": diff_v_str,
                    "% Crecimiento Votos": pct_growth_str,
                    "% Voto Inicial ➔ Final": f"{init_p:.2f}% ➔ {fin_p:.2f}%",
                    "Δ % Voto": diff_p_str,
                    "Procedencia / Destino del Voto": proc_str,
                })
            return pd.DataFrame(rows)

        tab_road_c, tab_road_s = st.tabs([
            f"🟣 {res_c.scenario_label}",
            f"🔵 {res_s.scenario_label}",
        ])

        with tab_road_c:
            if res_c.steps:
                c_taken = ", ".join([f"**-{count}** a {party}" for party, count in res_c.national_seats_taken.items()])
                pact_ext_c = res_c.pact_external_sources(pact_parties_coal)
                pact_int_c = res_c.pact_internal_transfers(pact_parties_coal)
                c_sources = ", ".join([f"{k}: +{int(v):,}" for k, v in pact_ext_c.items() if v > 0]) or "Sin aportación externa"
                c_int_trans = ", ".join([f"{k}: {int(v):,} v." for k, v in pact_int_c.items() if v > 0])

                crit_desc_c = {
                    "provincial_pct": "📊 Puntos % Provinciales (Δ% prov)",
                    "party_growth_pct": "🏛️ Crecimiento % del Partido (Δ% partido)",
                    "hybrid": f"⚖️ Híbrido Ponderado (α={res_c.hybrid_alpha:.2f})",
                    "absolute_votes": "🔢 Votos Brutos Absolutos (ΔV)",
                }.get(res_c.optimization_criterion, res_c.optimization_criterion)

                st.markdown(
                    f"**Meta de investidura:** +{res_c.seats_gained} escaños ({res_c.initial_bloc_seats} ➔ {res_c.final_bloc_seats} dip.) "
                    f"requiriendo **+{int(res_c.total_votes_needed):,} votos** (+{res_c.national_pct_increase:.2f}% nacional) en **{len(res_c.provinces_involved)} circunscripciones**."
                )
                st.caption(f"🧭 **Criterio de optimización aplicado:** {crit_desc_c}")
                if c_taken:
                    st.info(f"🎯 **Balance nacional de escaños arrebatados a la oposición:** {c_taken}")
                st.caption(f"📥 **Fuentes de movilización EXTERNA captadas por el pacto:** {c_sources}")
                if c_int_trans:
                    st.caption(f"🔄 **Reorganización interna entre socios del pacto:** {c_int_trans} *(votos transferidos entre miembros sin alterar el total del pacto)*")

                prov_counts_c = Counter(s.display_name for s in res_c.steps)
                table_rows_c = []
                for s in res_c.steps:
                    sources_str = " • ".join([f"{'Abst.' if k == 'Abstención' else k}: +{int(v):,}" for k, v in s.votes_source_breakdown.items() if v > 0]) or "Sin trasvase"
                    growth_str = f"+{s.beneficiary_growth_pct:.1f}%" if s.beneficiary_growth_pct > 0 else "="
                    if prov_counts_c[s.display_name] > 1 and getattr(s, "beneficiary_cumulative_growth_pct", 0.0) > s.beneficiary_growth_pct:
                        growth_str += f" (+{s.beneficiary_cumulative_growth_pct:.1f}% acum.)"
                    shift_str = f"+{s.provincial_vote_shift_pct:.2f}%" if s.provincial_vote_shift_pct > 0 else "="
                    table_rows_c.append({
                        "Prioridad": f"#{s.seat_order}",
                        "Circunscripción": s.display_name,
                        "Comunidad": s.community,
                        "Votos Necesarios": f"+{int(s.votes_needed):,}",
                        "% Desplazamiento Prov.": shift_str,
                        "% Incremento Candidatura": growth_str,
                        "Procedencia del Voto": sources_str,
                        "Candidatura": s.beneficiary_party,
                        "Arrebatado a": s.seat_taken_from or "Rival",
                        "Participación": f"{s.initial_turnout_pct:.1f}% ➔ {s.final_turnout_pct:.1f}%",
                        "% Voto Bloque": f"{s.initial_bloc_pct:.1f}% ➔ {s.final_bloc_pct:.1f}%",
                    })
                st.dataframe(pd.DataFrame(table_rows_c), use_container_width=True, hide_index=True)

                fig_road_c = create_government_roadmap_chart(res_c)
                if fig_road_c:
                    st.plotly_chart(
                        fig_road_c,
                        use_container_width=True,
                        key=f"{section_key}_gov_roadmap_chart_coalition",
                    )

                # Métricas agregadas nacionales del Pacto de Gobierno
                st.markdown("###### 🏛️ Balance Agregado Nacional del Pacto de Gobierno:")
                pm1, pm2, pm3, pm4 = st.columns(4)
                with pm1:
                    diff_s_c = res_c.final_bloc_seats - res_c.initial_bloc_seats
                    st.metric(
                        label="Diputados Totales Pacto",
                        value=f"{res_c.final_bloc_seats} dip.",
                        delta=f"{diff_s_c:+d} dip. (desde {res_c.initial_bloc_seats})",
                        delta_color="normal",
                    )
                with pm2:
                    diff_v_c = res_c.final_pact_votes - res_c.initial_pact_votes
                    pact_growth_c = (diff_v_c / res_c.initial_pact_votes * 100.0) if res_c.initial_pact_votes > 0 else 0.0
                    st.metric(
                        label="Votos Netos Pacto",
                        value=f"{int(res_c.final_pact_votes):,}",
                        delta=f"{int(diff_v_c):+,} netos ({pact_growth_c:+.2f}%)" if diff_v_c != 0 else "0",
                        delta_color="normal",
                    )
                with pm3:
                    diff_p_c = res_c.final_pact_pct - res_c.initial_pact_pct
                    st.metric(
                        label="% Voto Nacional Pacto",
                        value=f"{res_c.final_pact_pct:.2f}%",
                        delta=f"{diff_p_c:+.2f}%" if abs(diff_p_c) >= 0.01 else "0.0%",
                        delta_color="normal",
                    )
                with pm4:
                    tot_ext_c = sum(pact_ext_c.values())
                    st.metric(
                        label="Captación Externa Neta",
                        value=f"+{int(tot_ext_c):,} votos",
                        delta=f"Abst.: +{int(pact_ext_c.get('Abstención', 0)):,} | Don. ext.: +{int(sum(v for k, v in pact_ext_c.items() if k != 'Abstención')):,}",
                        delta_color="normal",
                    )

                # Tabla de movimientos partido a partido
                st.markdown("###### 🔄 Movimientos de Escaños y Votos Partido a Partido (Antes ➔ Después):")
                df_mov_c = _build_party_movements_df(res_c, pact_parties_coal)
                st.dataframe(df_mov_c, use_container_width=True, hide_index=True)

                # Gráfico del Congreso post-optimización
                fig_cong_c = create_government_national_scenario_chart(res_c)
                if fig_cong_c:
                    st.plotly_chart(
                        fig_cong_c,
                        use_container_width=True,
                        key=f"{section_key}_gov_cong_chart_coalition",
                    )

            elif res_c.target_achieved:
                st.success(f"🎉 El bloque con **{coalition_name}** ya cuenta con **{res_c.initial_bloc_seats} escaños** (supera los {target_seats}). No se precisan escaños adicionales.")
            else:
                st.warning(f"⚠️ {res_c.impossibility_reason}")

        with tab_road_s:
            if res_s.steps:
                s_taken = ", ".join([f"**-{count}** a {party}" for party, count in res_s.national_seats_taken.items()])
                pact_ext_s = res_s.pact_external_sources(pact_parties_sep)
                pact_int_s = res_s.pact_internal_transfers(pact_parties_sep)
                s_sources = ", ".join([f"{k}: +{int(v):,}" for k, v in pact_ext_s.items() if v > 0]) or "Sin aportación externa"
                s_int_trans = ", ".join([f"{k}: {int(v):,} v." for k, v in pact_int_s.items() if v > 0])

                crit_desc_s = {
                    "provincial_pct": "📊 Puntos % Provinciales (Δ% prov)",
                    "party_growth_pct": "🏛️ Crecimiento % del Partido (Δ% partido)",
                    "hybrid": f"⚖️ Híbrido Ponderado (α={res_s.hybrid_alpha:.2f})",
                    "absolute_votes": "🔢 Votos Brutos Absolutos (ΔV)",
                }.get(res_s.optimization_criterion, res_s.optimization_criterion)

                st.markdown(
                    f"**Meta de investidura:** +{res_s.seats_gained} escaños ({res_s.initial_bloc_seats} ➔ {res_s.final_bloc_seats} dip.) "
                    f"requiriendo **+{int(res_s.total_votes_needed):,} votos** (+{res_s.national_pct_increase:.2f}% nacional) en **{len(res_s.provinces_involved)} circunscripciones**."
                )
                st.caption(f"🧭 **Criterio de optimización aplicado:** {crit_desc_s}")
                if s_taken:
                    st.info(f"🎯 **Balance nacional de escaños arrebatados a la oposición:** {s_taken}")
                st.caption(f"📥 **Fuentes de movilización EXTERNA captadas por el pacto:** {s_sources}")
                if s_int_trans:
                    st.caption(f"🔄 **Reorganización interna entre socios del pacto:** {s_int_trans} *(votos transferidos entre miembros sin alterar el total del pacto)*")

                prov_counts_s = Counter(s.display_name for s in res_s.steps)
                table_rows_s = []
                for s in res_s.steps:
                    sources_str = " • ".join([f"{'Abst.' if k == 'Abstención' else k}: +{int(v):,}" for k, v in s.votes_source_breakdown.items() if v > 0]) or "Sin trasvase"
                    growth_str = f"+{s.beneficiary_growth_pct:.1f}%" if s.beneficiary_growth_pct > 0 else "="
                    if prov_counts_s[s.display_name] > 1 and getattr(s, "beneficiary_cumulative_growth_pct", 0.0) > s.beneficiary_growth_pct:
                        growth_str += f" (+{s.beneficiary_cumulative_growth_pct:.1f}% acum.)"
                    shift_str = f"+{s.provincial_vote_shift_pct:.2f}%" if s.provincial_vote_shift_pct > 0 else "="
                    table_rows_s.append({
                        "Prioridad": f"#{s.seat_order}",
                        "Circunscripción": s.display_name,
                        "Comunidad": s.community,
                        "Votos Necesarios": f"+{int(s.votes_needed):,}",
                        "% Desplazamiento Prov.": shift_str,
                        "% Incremento Candidatura": growth_str,
                        "Procedencia del Voto": sources_str,
                        "Candidatura": s.beneficiary_party,
                        "Arrebatado a": s.seat_taken_from or "Rival",
                        "Participación": f"{s.initial_turnout_pct:.1f}% ➔ {s.final_turnout_pct:.1f}%",
                        "% Voto Bloque": f"{s.initial_bloc_pct:.1f}% ➔ {s.final_bloc_pct:.1f}%",
                    })
                st.dataframe(pd.DataFrame(table_rows_s), use_container_width=True, hide_index=True)

                fig_road_s = create_government_roadmap_chart(res_s)
                if fig_road_s:
                    st.plotly_chart(
                        fig_road_s,
                        use_container_width=True,
                        key=f"{section_key}_gov_roadmap_chart_separated",
                    )

                # Métricas agregadas nacionales del Pacto de Gobierno
                st.markdown("###### 🏛️ Balance Agregado Nacional del Pacto de Gobierno:")
                sm1, sm2, sm3, sm4 = st.columns(4)
                with sm1:
                    diff_s_s = res_s.final_bloc_seats - res_s.initial_bloc_seats
                    st.metric(
                        label="Diputados Totales Pacto",
                        value=f"{res_s.final_bloc_seats} dip.",
                        delta=f"{diff_s_s:+d} dip. (desde {res_s.initial_bloc_seats})",
                        delta_color="normal",
                    )
                with sm2:
                    diff_v_s = res_s.final_pact_votes - res_s.initial_pact_votes
                    pact_growth_s = (diff_v_s / res_s.initial_pact_votes * 100.0) if res_s.initial_pact_votes > 0 else 0.0
                    st.metric(
                        label="Votos Netos Pacto",
                        value=f"{int(res_s.final_pact_votes):,}",
                        delta=f"{int(diff_v_s):+,} netos ({pact_growth_s:+.2f}%)" if diff_v_s != 0 else "0",
                        delta_color="normal",
                    )
                with sm3:
                    diff_p_s = res_s.final_pact_pct - res_s.initial_pact_pct
                    st.metric(
                        label="% Voto Nacional Pacto",
                        value=f"{res_s.final_pact_pct:.2f}%",
                        delta=f"{diff_p_s:+.2f}%" if abs(diff_p_s) >= 0.01 else "0.0%",
                        delta_color="normal",
                    )
                with sm4:
                    tot_ext_s = sum(pact_ext_s.values())
                    st.metric(
                        label="Captación Externa Neta",
                        value=f"+{int(tot_ext_s):,} votos",
                        delta=f"Abst.: +{int(pact_ext_s.get('Abstención', 0)):,} | Don. ext.: +{int(sum(v for k, v in pact_ext_s.items() if k != 'Abstención')):,}",
                        delta_color="normal",
                    )

                # Tabla de movimientos partido a partido
                st.markdown("###### 🔄 Movimientos de Escaños y Votos Partido a Partido (Antes ➔ Después):")
                df_mov_s = _build_party_movements_df(res_s, pact_parties_sep)
                st.dataframe(pd.DataFrame(df_mov_s), use_container_width=True, hide_index=True)

                # Gráfico del Congreso post-optimización
                fig_cong_s = create_government_national_scenario_chart(res_s)
                if fig_cong_s:
                    st.plotly_chart(
                        fig_cong_s,
                        use_container_width=True,
                        key=f"{section_key}_gov_cong_chart_separated",
                    )

            elif res_s.target_achieved:
                st.success(f"🎉 El bloque por separado ya cuenta con **{res_s.initial_bloc_seats} escaños** (supera los {target_seats}). No se precisan escaños adicionales.")
            else:
                st.warning(f"⚠️ {res_s.impossibility_reason}")

        # ==============================================================================
        # REPARTO COMPARATIVO POST-OPTIMIZACIÓN: LISTA ÚNICA VS. SEPARADOS
        # ==============================================================================
        st.markdown("---")
        st.markdown("#### ⚖️ Comparativa del Reparto Post-Optimización (Lista Única vs. Por Separado)")
        st.caption(
            "Análisis directo del resultado final del Congreso (350 escaños) y de las 52 circunscripciones "
            "comparando ambos modelos tras optimizar la mayoría de gobierno."
        )

        # 1. Gráfico comparativo de composición del Congreso (350 escaños)
        fig_nat_comp = create_government_national_comparison_chart(res_c, res_s)
        if fig_nat_comp:
            st.plotly_chart(
                fig_nat_comp,
                use_container_width=True,
                key=f"{section_key}_gov_nat_comparison_chart",
            )

        # 2. Tabla comparativa de composición del Congreso (350 escaños)
        st.markdown("##### 📊 Reparto Comparativo del Congreso por Partido (Post-Optimización):")
        all_comp_parties = []
        std_order = [
            "PP", "PSOE", "VOX", "Vox", coalition_name
        ] + [m for m in members if m not in ("PP", "PSOE", "VOX", "Vox", coalition_name)] + [
            "Sumar", "SUMAR", "Podemos", "PODEMOS", "SALF",
            "ERC", "Junts", "JUNTS", "EH Bildu", "EH BILDU", "PNV", "EAJ-PNV", "BNG", "CC", "UPN"
        ]
        seen_comp = set()
        for p in std_order:
            if (res_c.final_national_seats.get(p, 0) > 0 or res_s.final_national_seats.get(p, 0) > 0) and p not in seen_comp:
                all_comp_parties.append(p)
                seen_comp.add(p)
        for p in list(res_c.final_national_seats.keys()) + list(res_s.final_national_seats.keys()):
            if (res_c.final_national_seats.get(p, 0) > 0 or res_s.final_national_seats.get(p, 0) > 0) and p not in seen_comp:
                all_comp_parties.append(p)
                seen_comp.add(p)

        all_comp_parties.sort(key=lambda p: max(res_c.final_national_seats.get(p, 0), res_s.final_national_seats.get(p, 0)), reverse=True)

        comp_nat_rows = []
        for p in all_comp_parties:
            s_c = res_c.final_national_seats.get(p, 0)
            s_s = res_s.final_national_seats.get(p, 0)
            p_c = res_c.final_national_pct.get(p, 0.0)
            p_s = res_s.final_national_pct.get(p, 0.0)

            diff_s = s_c - s_s
            diff_s_str = f"+{diff_s} dip." if diff_s > 0 else (f"{diff_s} dip." if diff_s < 0 else "=")
            rol = "🏛️ Pacto de Gobierno" if (p in pact_parties_coal or p in pact_parties_sep) else "⚔️ Oposición / Externo"

            comp_nat_rows.append({
                "Candidatura": p,
                "Rol": rol,
                "Escaños: Con Lista Única": s_c,
                "Escaños: Por Separado": s_s,
                "Diferencia (L. Única - Sep.)": diff_s_str,
                "% Voto: Con Lista Única": f"{p_c:.2f}%",
                "% Voto: Por Separado": f"{p_s:.2f}%",
            })
        st.dataframe(pd.DataFrame(comp_nat_rows), use_container_width=True, hide_index=True)

        # 3. Comparativa a nivel de circunscripciones (52 provincias)
        if res_c.final_constituency_data and res_s.final_constituency_data:
            st.markdown("---")
            st.markdown("##### 📍 Reparto Post-Optimización por Circunscripción (52 Provincias):")

            c_data_c_map = {normalize_province_name(c["province"]): c for c in res_c.final_constituency_data}
            c_data_s_map = {normalize_province_name(c["province"]): c for c in res_s.final_constituency_data}

            prov_comp_rows = []
            for c_info in res_c.final_constituency_data:
                canon = normalize_province_name(c_info["province"])
                s_info = c_data_s_map.get(canon, c_info)

                bloc_s_c = sum(c_info["final_seats"].get(p, 0) for p in pact_parties_coal)
                bloc_s_s = sum(s_info["final_seats"].get(p, 0) for p in pact_parties_sep)
                diff_bloc = bloc_s_c - bloc_s_s
                diff_bloc_str = f"+{diff_bloc}" if diff_bloc > 0 else (f"{diff_bloc}" if diff_bloc < 0 else "=")

                # Votos netos del pacto en esta provincia
                v_init_c = sum(c_info["initial_votes"].get(p, 0.0) for p in pact_parties_coal)
                v_fin_c = sum(c_info["final_votes"].get(p, 0.0) for p in pact_parties_coal)
                d_v_c = v_fin_c - v_init_c
                growth_c = (d_v_c / v_init_c * 100.0) if v_init_c > 0 else 0.0

                v_init_s = sum(s_info["initial_votes"].get(p, 0.0) for p in pact_parties_sep)
                v_fin_s = sum(s_info["final_votes"].get(p, 0.0) for p in pact_parties_sep)
                d_v_s = v_fin_s - v_init_s
                growth_s = (d_v_s / v_init_s * 100.0) if v_init_s > 0 else 0.0

                prov_comp_rows.append({
                    "Circunscripción": c_info["display_name"],
                    "Comunidad": c_info["community"],
                    "Diputados": c_info["seats"],
                    "Escaños Pacto (Lista Única)": bloc_s_c,
                    "Escaños Pacto (Separados)": bloc_s_s,
                    "Δ Escaños (L. Única - Sep.)": diff_bloc_str,
                    "Votos Netos Pacto (L. Única)": f"+{int(d_v_c):,} ({growth_c:+.1f}%)" if int(d_v_c) > 0 else "=",
                    "Votos Netos Pacto (Separados)": f"+{int(d_v_s):,} ({growth_s:+.1f}%)" if int(d_v_s) > 0 else "=",
                    "Participación (Lista Única)": f"{c_info['final_turnout_pct']:.1f}%",
                    "Participación (Separados)": f"{s_info['final_turnout_pct']:.1f}%",
                })

            st.dataframe(pd.DataFrame(prov_comp_rows), use_container_width=True, hide_index=True)

            # Selector detallado de circunscripción
            prov_names = [c["province"] for c in res_c.final_constituency_data]
            sel_detail_prov = st.selectbox(
                "🔍 Seleccionar circunscripción para ver el desglose detallado de votos y escaños:",
                options=prov_names,
                format_func=get_province_display_name,
                key=f"{section_key}_prov_detail_select",
            )
            if sel_detail_prov:
                canon_sel = normalize_province_name(sel_detail_prov)
                det_c = c_data_c_map.get(canon_sel)
                det_s = c_data_s_map.get(canon_sel)

                if det_c and det_s:
                    st.markdown(f"###### 📋 Desglose Electoral Detallado en **{get_province_display_name(sel_detail_prov)}** ({det_c['seats']} diputados):")
                    tab_p_c, tab_p_s = st.tabs([
                        f"🟣 {res_c.scenario_label}",
                        f"🔵 {res_s.scenario_label}",
                    ])

                    for tab_target, det_info, pact_set in [
                        (tab_p_c, det_c, pact_parties_coal),
                        (tab_p_s, det_s, pact_parties_sep),
                    ]:
                        with tab_target:
                            # 1. Métricas del Pacto en la Provincia
                            p_init_v = sum(det_info["initial_votes"].get(p, 0.0) for p in pact_set)
                            p_fin_v = sum(det_info["final_votes"].get(p, 0.0) for p in pact_set)
                            p_diff_v = p_fin_v - p_init_v
                            p_growth = (p_diff_v / p_init_v * 100.0) if p_init_v > 0 else 0.0

                            p_tot_init_val = sum(det_info["initial_votes"].values()) + det_info.get("blank_votes", 0.0)
                            p_tot_fin_val = sum(det_info["final_votes"].values()) + det_info.get("blank_votes", 0.0)

                            p_init_pct = (p_init_v / p_tot_init_val * 100.0) if p_tot_init_val > 0 else 0.0
                            p_fin_pct = (p_fin_v / p_tot_fin_val * 100.0) if p_tot_fin_val > 0 else 0.0
                            p_diff_pct = p_fin_pct - p_init_pct

                            p_init_s = sum(det_info["initial_seats"].get(p, 0) for p in pact_set)
                            p_fin_s = sum(det_info["final_seats"].get(p, 0) for p in pact_set)
                            p_diff_s = p_fin_s - p_init_s

                            # Procedencia EXTERNA del voto del pacto en esta provincia
                            p_ext_sources = {}
                            p_int_transfers = {}
                            prov_party_sources = det_info.get("party_sources", {})
                            for benef_p, srcs in prov_party_sources.items():
                                if benef_p in pact_set:
                                    for k, v in srcs.items():
                                        if v <= 0:
                                            continue
                                        if k == "Abstención" or k not in pact_set:
                                            p_ext_sources[k] = p_ext_sources.get(k, 0.0) + v
                                        else:
                                            key_pair = f"{k} ➔ {benef_p}"
                                            p_int_transfers[key_pair] = p_int_transfers.get(key_pair, 0.0) + v

                            ext_prov_str = ", ".join([f"{k}: +{int(v):,}" for k, v in p_ext_sources.items()]) or "Sin captación externa"
                            int_prov_str = ", ".join([f"{k}: {int(v):,} v." for k, v in p_int_transfers.items()])

                            st.markdown(f"**🏛️ Balance del Pacto de Gobierno en {get_province_display_name(sel_detail_prov)}:**")
                            col_p1, col_p2, col_p3, col_p4 = st.columns(4)
                            with col_p1:
                                st.metric(
                                    label="Diputados Pacto",
                                    value=f"{p_fin_s} dip.",
                                    delta=f"{p_diff_s:+d} dip. (desde {p_init_s})",
                                    delta_color="normal",
                                )
                            with col_p2:
                                st.metric(
                                    label="Votos Netos Pacto",
                                    value=f"{int(p_fin_v):,}",
                                    delta=f"{int(p_diff_v):+,} ({p_growth:+.2f}%)" if p_diff_v != 0 else "0",
                                    delta_color="normal",
                                )
                            with col_p3:
                                st.metric(
                                    label="% Voto Pacto",
                                    value=f"{p_fin_pct:.2f}%",
                                    delta=f"{p_diff_pct:+.2f}%" if abs(p_diff_pct) >= 0.01 else "0.0%",
                                    delta_color="normal",
                                )
                            with col_p4:
                                st.metric(
                                    label="Participación Provincial",
                                    value=f"{det_info['final_turnout_pct']:.1f}%",
                                    delta=f"{det_info['final_turnout_pct'] - det_info['initial_turnout_pct']:+.1f}%",
                                    delta_color="normal",
                                )

                            st.markdown(f"📥 **Procedencia EXTERNA del voto del pacto en la provincia:** {ext_prov_str}")
                            if int_prov_str:
                                st.caption(f"🔄 **Reorganización interna entre socios en esta provincia:** {int_prov_str} *(voto transferido internamente que no altera el balance neto del pacto)*")

                            # 2. Tabla Detallada Partido a Partido en la Provincia
                            all_det_parties = []
                            seen_p = set()
                            for p in list(det_info["final_seats"].keys()) + list(det_info["initial_seats"].keys()) + list(det_info["final_votes"].keys()):
                                if p not in seen_p:
                                    all_det_parties.append(p)
                                    seen_p.add(p)
                            all_det_parties.sort(key=lambda p: (p in pact_set, det_info["final_seats"].get(p, 0), det_info["final_votes"].get(p, 0.0)), reverse=True)

                            det_table_rows = []
                            for p in all_det_parties:
                                v_init = det_info["initial_votes"].get(p, 0.0)
                                v_fin = det_info["final_votes"].get(p, 0.0)
                                s_init = det_info["initial_seats"].get(p, 0)
                                s_fin = det_info["final_seats"].get(p, 0)
                                d_v = v_fin - v_init
                                d_s = s_fin - s_init

                                if v_init == 0 and v_fin == 0 and s_init == 0 and s_fin == 0:
                                    continue

                                p_growth_c = (d_v / v_init * 100.0) if v_init > 0 else 0.0
                                p_init_p = (v_init / p_tot_init_val * 100.0) if p_tot_init_val > 0 else 0.0
                                p_fin_p = (v_fin / p_tot_fin_val * 100.0) if p_tot_fin_val > 0 else 0.0
                                d_pct = p_fin_p - p_init_p

                                rol_p = "🏛️ Pacto" if p in pact_set else "⚔️ Oposición / Externo"

                                # Procedencia o destino del voto en esta provincia
                                if d_v > 0 and p in prov_party_sources:
                                    srcs = prov_party_sources[p]
                                    src_str = " • ".join([f"{'Abst.' if k == 'Abstención' else k}: +{int(v):,}" for k, v in srcs.items() if v > 0]) or f"+{int(d_v):,} v."
                                elif d_v < 0 and p in det_info.get("party_donations", {}):
                                    dons = det_info["party_donations"][p]
                                    src_str = " • ".join([f"➔ {k}: -{int(v):,}" for k, v in dons.items() if v > 0]) or f"Cedidos: {int(d_v):,}"
                                else:
                                    src_str = "Sin trasvases"

                                det_table_rows.append({
                                    "Candidatura": p,
                                    "Rol": rol_p,
                                    "Escaños": f"{s_init} ➔ {s_fin}",
                                    "Δ Escaños": f"{d_s:+d}" if d_s != 0 else "=",
                                    "Votos": f"{int(v_init):,} ➔ {int(v_fin):,}",
                                    "Δ Votos": f"{int(d_v):+,}" if int(d_v) != 0 else "=",
                                    "% Incremento Voto": f"{p_growth_c:+.2f}%" if abs(p_growth_c) >= 0.01 else "=",
                                    "% Voto Provincial": f"{p_init_p:.2f}% ➔ {p_fin_p:.2f}%",
                                    "Δ % Voto": f"{d_pct:+.2f}%" if abs(d_pct) >= 0.01 else "=",
                                    "Procedencia / Destino en la Provincia": src_str,
                                })

                            st.dataframe(pd.DataFrame(det_table_rows), use_container_width=True, hide_index=True)


