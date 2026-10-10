"""
Analizador comparativo de escenarios electorales y optimizador inverso.
Responde a la pregunta clave tanto a nivel nacional (52 provincias) como en simulación libre de circunscripción única:
¿Cuántos votos necesitaría el escenario separado para conseguir el mismo resultado en escaños
que el escenario en coalición (o viceversa)?
Calcula además el punto de indiferencia / umbral de rentabilidad de la coalición frente a la desafección.
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import plotly.graph_objects as go

try:
    from core.national_model import SpanishElectoralModel, NationalSimulationResult
    from core.dhondt import calculate_dhondt, ConstituencyResult
except ImportError:
    from ..core.national_model import SpanishElectoralModel, NationalSimulationResult
    from ..core.dhondt import calculate_dhondt, ConstituencyResult


@dataclass
class ScenarioComparison:
    poll_used: Dict[str, float]
    retention_rate: float
    separated_result: NationalSimulationResult
    coalition_result: NationalSimulationResult
    separated_left_seats: int
    coalition_left_seats: int
    separated_left_votes: float
    coalition_left_votes: float
    separated_votes_per_seat: float
    coalition_votes_per_seat: float
    seat_difference: int  # coalition - separated
    more_favorable_scenario: str  # "Coalición" o "Separados"
    flipped_provinces: List[Dict[str, Any]]
    parties_who_lost: Dict[str, int] = field(default_factory=dict)
    seat_takeovers: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class InverseOptimizationResult:
    target_seats: int
    favorable_scenario: str
    underperforming_scenario: str
    current_votes: float
    current_pct: float
    required_votes: float
    required_pct: float
    additional_votes_needed: float
    additional_pct_needed: float
    multiplier: float
    seats_by_province_at_target: Dict[str, int]
    newly_won_provinces: List[str]


@dataclass
class SingleConstituencyComparison:
    seats: int
    blank_votes: float
    threshold_pct: float
    parties_votes: Dict[str, float]
    coalition_members: List[str]
    coalition_name: str
    retention_rate: float
    retention_by_party: Dict[str, float]
    result_separated: ConstituencyResult
    result_coalition: ConstituencyResult
    separated_left_seats: int
    coalition_left_seats: int
    separated_left_votes: float
    coalition_left_votes: float
    separated_votes_per_seat: float
    coalition_votes_per_seat: float
    seat_difference: int  # coalition - separated
    more_favorable_scenario: str  # "Coalición", "Separados" o "Empate"
    target_seats: int
    additional_votes_needed: float
    additional_pct_needed: float
    required_votes: float
    multiplier: float
    beneficiary_party: Optional[str]
    breakeven_r: Optional[float]
    census: float = 0.0
    turnout_pct: float = 0.0
    null_votes: float = 0.0
    valid_votes: float = 0.0


class CoalitionAnalyzer:
    def __init__(self, model: Optional[SpanishElectoralModel] = None):
        self.model = model or SpanishElectoralModel()

    def _safe_simulate(self, *args, **kwargs) -> NationalSimulationResult:
        try:
            return self.model.simulate(*args, **kwargs)
        except TypeError as e:
            if "is_official_23j" in str(e) or "party_multiplier" in str(e) or "turnout_pct" in str(e):
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ["is_official_23j", "party_multiplier", "turnout_pct"]}
                return self.model.simulate(*args, **clean_kwargs)
            raise

    def compare(
        self,
        poll: Dict[str, float],
        retention_rate: float = 1.0,
        custom_coalition_name: str = "Lista Única Izquierdas",
        constituency_overrides: Optional[Dict[str, Any]] = None,
        default_coalition_members: Optional[List[str]] = None,
        default_retention_by_party: Optional[Dict[str, float]] = None,
        threshold_pct: float = 3.0,
        blank_pct: float = 0.8,
        is_official_23j: Optional[bool] = None,
        turnout_pct: Optional[float] = None,
        **kwargs,
    ) -> ScenarioComparison:
        """
        Compara directamente el escenario de listas separadas frente a lista única a nivel nacional.
        """
        if is_official_23j is None:
            is_official_23j = kwargs.get("is_official_23j", None)
        if turnout_pct is None:
            turnout_pct = kwargs.get("turnout_pct", None)
        res_sep = self._safe_simulate(
            national_poll=poll,
            left_scenario="separated",
            custom_coalition_name=custom_coalition_name,
            constituency_overrides=constituency_overrides,
            default_coalition_members=default_coalition_members,
            threshold_pct=threshold_pct,
            blank_pct=blank_pct,
            is_official_23j=is_official_23j,
            turnout_pct=turnout_pct,
        )
        res_coal = self._safe_simulate(
            national_poll=poll,
            left_scenario="coalition",
            coalition_retention_rate=retention_rate,
            custom_coalition_name=custom_coalition_name,
            constituency_overrides=constituency_overrides,
            default_coalition_members=default_coalition_members,
            default_retention_by_party=default_retention_by_party,
            threshold_pct=threshold_pct,
            blank_pct=blank_pct,
            is_official_23j=is_official_23j,
            turnout_pct=turnout_pct,
        )

        def_members = default_coalition_members or ["Sumar", "Podemos"]
        sep_seats = sum(res_sep.national_seats.get(p, 0) for p in def_members)
        coal_seats = res_coal.national_seats.get(custom_coalition_name, 0)

        sep_votes = sum(res_sep.national_votes_est.get(p, 0.0) for p in def_members)
        coal_votes = res_coal.national_votes_est.get(custom_coalition_name, 0.0)

        sep_cost = (sep_votes / sep_seats) if sep_seats > 0 else 0.0
        coal_cost = (coal_votes / coal_seats) if coal_seats > 0 else 0.0

        diff = coal_seats - sep_seats
        more_favorable = "Coalición" if coal_seats >= sep_seats else "Separados"

        # Identificar provincias donde cambia la asignación de escaños
        flipped = []
        for c_data in res_sep.constituency_data:
            c_name = c_data["name"]
            sep_res = res_sep.constituency_results[c_name]
            coal_res = res_coal.constituency_results[c_name]

            s_sep = sum(sep_res.seats.get(p, 0) for p in def_members)
            s_coal = coal_res.seats.get(custom_coalition_name, 0)

            if s_sep != s_coal:
                parties_lost = []
                parties_gained = []
                all_p = set(sep_res.seats.keys()).union(coal_res.seats.keys())
                for p in all_p:
                    if p in def_members or p == custom_coalition_name:
                        continue
                    diff_p = coal_res.seats.get(p, 0) - sep_res.seats.get(p, 0)
                    if diff_p < 0:
                        parties_lost.append(f"{p} ({diff_p})")
                    elif diff_p > 0:
                        parties_gained.append(f"{p} (+{diff_p})")

                flipped.append({
                    "province": c_name,
                    "total_seats": c_data["seats"],
                    "separated_left_seats": s_sep,
                    "coalition_left_seats": s_coal,
                    "difference": s_coal - s_sep,
                    "impact_on_others": f"Pierde: {', '.join(parties_lost)}" if parties_lost else "Sin cambios externos",
                })

        # Balance agregado de a qué partidos quita escaños el escenario más favorable
        parties_who_lost: Dict[str, int] = {}
        seat_takeovers: List[Dict[str, Any]] = []

        if coal_seats > sep_seats:
            for p, s_sep in res_sep.national_seats.items():
                if p in def_members or p == custom_coalition_name:
                    continue
                s_coal = res_coal.national_seats.get(p, 0)
                if s_coal < s_sep:
                    parties_who_lost[p] = s_sep - s_coal

            for c_data in res_sep.constituency_data:
                c_name = c_data["name"]
                c_sep_res = res_sep.constituency_results[c_name]
                c_coal_res = res_coal.constituency_results[c_name]
                c_s_sep = sum(c_sep_res.seats.get(p, 0) for p in def_members)
                c_s_coal = c_coal_res.seats.get(custom_coalition_name, 0)

                if c_s_coal > c_s_sep:
                    all_p = set(c_sep_res.seats.keys()).union(c_coal_res.seats.keys())
                    for p in all_p:
                        if p in def_members or p == custom_coalition_name:
                            continue
                        p_sep = c_sep_res.seats.get(p, 0)
                        p_coal = c_coal_res.seats.get(p, 0)
                        if p_coal < p_sep:
                            seat_takeovers.append({
                                "province": c_name,
                                "winner_scenario": "Coalición",
                                "party_lost": p,
                                "seats_lost": p_sep - p_coal,
                                "party_seats_before": p_sep,
                                "party_seats_after": p_coal,
                                "block_seats_before": c_s_sep,
                                "block_seats_after": c_s_coal,
                            })

        elif sep_seats > coal_seats:
            for p, s_coal in res_coal.national_seats.items():
                if p in def_members or p == custom_coalition_name:
                    continue
                s_sep = res_sep.national_seats.get(p, 0)
                if s_sep < s_coal:
                    parties_who_lost[p] = s_coal - s_sep

            for c_data in res_sep.constituency_data:
                c_name = c_data["name"]
                c_sep_res = res_sep.constituency_results[c_name]
                c_coal_res = res_coal.constituency_results[c_name]
                c_s_sep = sum(c_sep_res.seats.get(p, 0) for p in def_members)
                c_s_coal = c_coal_res.seats.get(custom_coalition_name, 0)

                if c_s_sep > c_s_coal:
                    all_p = set(c_sep_res.seats.keys()).union(c_coal_res.seats.keys())
                    for p in all_p:
                        if p in def_members or p == custom_coalition_name:
                            continue
                        p_sep = c_sep_res.seats.get(p, 0)
                        p_coal = c_coal_res.seats.get(p, 0)
                        if p_sep < p_coal:
                            seat_takeovers.append({
                                "province": c_name,
                                "winner_scenario": "Separados",
                                "party_lost": p,
                                "seats_lost": p_coal - p_sep,
                                "party_seats_before": p_coal,
                                "party_seats_after": p_sep,
                                "block_seats_before": c_s_coal,
                                "block_seats_after": c_s_sep,
                            })

        return ScenarioComparison(
            poll_used=poll,
            retention_rate=retention_rate,
            separated_result=res_sep,
            coalition_result=res_coal,
            separated_left_seats=sep_seats,
            coalition_left_seats=coal_seats,
            separated_left_votes=sep_votes,
            coalition_left_votes=coal_votes,
            separated_votes_per_seat=sep_cost,
            coalition_votes_per_seat=coal_cost,
            seat_difference=diff,
            more_favorable_scenario=more_favorable,
            flipped_provinces=flipped,
            parties_who_lost=parties_who_lost,
            seat_takeovers=seat_takeovers,
        )

    def solve_votes_needed_to_match_target(
        self,
        poll: Dict[str, float],
        retention_rate: float = 1.0,
        custom_coalition_name: str = "Lista Única Izquierdas",
        constituency_overrides: Optional[Dict[str, Any]] = None,
        default_coalition_members: Optional[List[str]] = None,
        default_retention_by_party: Optional[Dict[str, float]] = None,
        threshold_pct: float = 3.0,
        blank_pct: float = 0.8,
        max_iterations: int = 25,
        is_official_23j: Optional[bool] = None,
        turnout_pct: Optional[float] = None,
        **kwargs,
    ) -> InverseOptimizationResult:
        """
        OPTIMIZADOR INVERSO NACIONAL:
        Responde a la pregunta: ¿Cuántos votos necesitaría el escenario menos favorable
        para igualar en escaños al escenario más favorable?
        """
        if is_official_23j is None:
            is_official_23j = kwargs.get("is_official_23j", None)
        if turnout_pct is None:
            turnout_pct = kwargs.get("turnout_pct", None)
        comparison = self.compare(
            poll,
            retention_rate=retention_rate,
            custom_coalition_name=custom_coalition_name,
            constituency_overrides=constituency_overrides,
            default_coalition_members=default_coalition_members,
            default_retention_by_party=default_retention_by_party,
            threshold_pct=threshold_pct,
            blank_pct=blank_pct,
            is_official_23j=is_official_23j,
            turnout_pct=turnout_pct,
        )

        def_members = default_coalition_members or ["Sumar", "Podemos"]

        if comparison.coalition_left_seats >= comparison.separated_left_seats:
            target_seats = comparison.coalition_left_seats
            favorable = "Coalición"
            underperforming = "Separados"
            current_votes = comparison.separated_left_votes
            current_pct = sum(poll.get(p, 0.0) for p in def_members)

            low_m = 1.0
            high_m = 4.0

            test_poll_high = dict(poll)
            for p in def_members:
                test_poll_high[p] = poll.get(p, 0.0) * high_m
            res_high = self._safe_simulate(
                test_poll_high,
                left_scenario="separated",
                constituency_overrides=constituency_overrides,
                threshold_pct=threshold_pct,
                blank_pct=blank_pct,
                is_official_23j=is_official_23j,
                party_multiplier={p: high_m for p in def_members},
                turnout_pct=turnout_pct,
            )
            high_seats = sum(res_high.national_seats.get(p, 0) for p in def_members)

            if high_seats < target_seats:
                high_m = 6.0

            best_m = high_m
            best_res = None

            for _ in range(max_iterations):
                mid_m = (low_m + high_m) / 2.0
                test_poll = dict(poll)
                for p in def_members:
                    test_poll[p] = poll.get(p, 0.0) * mid_m

                sim = self._safe_simulate(
                    test_poll,
                    left_scenario="separated",
                    constituency_overrides=constituency_overrides,
                    threshold_pct=threshold_pct,
                    blank_pct=blank_pct,
                    is_official_23j=is_official_23j,
                    party_multiplier={p: mid_m for p in def_members},
                    turnout_pct=turnout_pct,
                )
                s_count = sum(sim.national_seats.get(p, 0) for p in def_members)

                if s_count >= target_seats:
                    best_m = mid_m
                    best_res = sim
                    high_m = mid_m
                else:
                    low_m = mid_m

            req_votes = current_votes * best_m
            req_pct = current_pct * best_m
            add_votes = req_votes - current_votes
            add_pct = req_pct - current_pct

            new_provs = []
            seats_by_prov = {}
            for c_data in best_res.constituency_data:
                c_name = c_data["name"]
                s_orig = sum(comparison.separated_result.constituency_results[c_name].seats.get(p, 0) for p in def_members)
                s_new = sum(best_res.constituency_results[c_name].seats.get(p, 0) for p in def_members)
                seats_by_prov[c_name] = s_new
                if s_new > s_orig:
                    new_provs.append(f"{c_name} (+{s_new - s_orig})")

            return InverseOptimizationResult(
                target_seats=target_seats,
                favorable_scenario=favorable,
                underperforming_scenario=underperforming,
                current_votes=current_votes,
                current_pct=current_pct,
                required_votes=req_votes,
                required_pct=req_pct,
                additional_votes_needed=add_votes,
                additional_pct_needed=add_pct,
                multiplier=best_m,
                seats_by_province_at_target=seats_by_prov,
                newly_won_provinces=new_provs,
            )

        else:
            target_seats = comparison.separated_left_seats
            favorable = "Separados"
            underperforming = "Coalición"
            current_votes = comparison.coalition_left_votes
            current_pct = sum(poll.get(p, 0.0) for p in def_members) * retention_rate

            low_m = 1.0
            high_m = 3.0
            best_m = high_m
            best_res = None

            for _ in range(max_iterations):
                mid_m = (low_m + high_m) / 2.0
                sim = self._safe_simulate(
                    poll,
                    left_scenario="coalition",
                    coalition_retention_rate=retention_rate * mid_m,
                    custom_coalition_name=custom_coalition_name,
                    constituency_overrides=constituency_overrides,
                    default_coalition_members=default_coalition_members,
                    default_retention_by_party=default_retention_by_party,
                    threshold_pct=threshold_pct,
                    blank_pct=blank_pct,
                    is_official_23j=is_official_23j,
                    turnout_pct=turnout_pct,
                )
                s_count = sim.national_seats.get(custom_coalition_name, 0)

                if s_count >= target_seats:
                    best_m = mid_m
                    best_res = sim
                    high_m = mid_m
                else:
                    low_m = mid_m

            req_votes = current_votes * best_m
            req_pct = current_pct * best_m
            add_votes = req_votes - current_votes
            add_pct = req_pct - current_pct

            new_provs = []
            seats_by_prov = {}
            for c_data in best_res.constituency_data:
                c_name = c_data["name"]
                s_orig = comparison.coalition_result.constituency_results[c_name].seats.get(custom_coalition_name, 0)
                s_new = best_res.constituency_results[c_name].seats.get(custom_coalition_name, 0)
                seats_by_prov[c_name] = s_new
                if s_new > s_orig:
                    new_provs.append(f"{c_name} (+{s_new - s_orig})")

            return InverseOptimizationResult(
                target_seats=target_seats,
                favorable_scenario=favorable,
                underperforming_scenario=underperforming,
                current_votes=current_votes,
                current_pct=current_pct,
                required_votes=req_votes,
                required_pct=req_pct,
                additional_votes_needed=add_votes,
                additional_pct_needed=add_pct,
                multiplier=best_m,
                seats_by_province_at_target=seats_by_prov,
                newly_won_provinces=new_provs,
            )

    def calculate_breakeven_curve(
        self,
        poll: Dict[str, float],
        min_retention: float = 0.50,
        max_retention: float = 1.15,
        step: float = 0.02,
        custom_coalition_name: str = "Lista Única Izquierdas",
        constituency_overrides: Optional[Dict[str, Any]] = None,
        default_coalition_members: Optional[List[str]] = None,
        default_retention_by_party: Optional[Dict[str, float]] = None,
        threshold_pct: float = 3.0,
        blank_pct: float = 0.8,
        is_official_23j: Optional[bool] = None,
        turnout_pct: Optional[float] = None,
        **kwargs,
    ) -> Tuple[List[float], List[int], int, Optional[float]]:
        """
        Calcula la curva de rentabilidad electoral en función del factor de retención R.
        """
        if is_official_23j is None:
            is_official_23j = kwargs.get("is_official_23j", None)
        if turnout_pct is None:
            turnout_pct = kwargs.get("turnout_pct", None)
        def_members = default_coalition_members or ["Sumar", "Podemos"]
        res_sep = self._safe_simulate(
            poll,
            left_scenario="separated",
            constituency_overrides=constituency_overrides,
            default_coalition_members=default_coalition_members,
            threshold_pct=threshold_pct,
            blank_pct=blank_pct,
            is_official_23j=is_official_23j,
            turnout_pct=turnout_pct,
        )
        sep_seats = sum(res_sep.national_seats.get(p, 0) for p in def_members)

        rates = []
        coal_seats = []
        r = min_retention

        while r <= max_retention + 1e-5:
            sim = self._safe_simulate(
                poll,
                left_scenario="coalition",
                coalition_retention_rate=r,
                custom_coalition_name=custom_coalition_name,
                constituency_overrides=constituency_overrides,
                default_coalition_members=default_coalition_members,
                default_retention_by_party=default_retention_by_party,
                threshold_pct=threshold_pct,
                blank_pct=blank_pct,
                is_official_23j=is_official_23j,
                turnout_pct=turnout_pct,
            )
            s = sim.national_seats.get(custom_coalition_name, 0)
            rates.append(round(r, 4))
            coal_seats.append(s)
            r += step

        breakeven_r = None
        for i in range(len(rates) - 1):
            if (coal_seats[i] <= sep_seats and coal_seats[i + 1] >= sep_seats) or \
               (coal_seats[i] >= sep_seats and coal_seats[i + 1] <= sep_seats):
                breakeven_r = rates[i + 1]
                break

        return rates, coal_seats, sep_seats, breakeven_r

    def compare_single_constituency(
        self,
        parties_votes: Dict[str, float],
        coalition_members: List[str],
        seats: int,
        blank_votes: float = 0.0,
        threshold_pct: float = 3.0,
        retention_rate: float = 1.0,
        retention_by_party: Optional[Dict[str, float]] = None,
        coalition_name: str = "Lista Única",
        census: float = 0.0,
        turnout_pct: float = 0.0,
        null_votes: float = 0.0,
    ) -> SingleConstituencyComparison:
        """
        SIMULACIÓN COMPLEJA DE UNA SOLA CIRCUNSCRIPCIÓN DUAL:
        Compara el escenario separado frente al de coalición con fuga partido a partido,
        censo, participación, nulos y blancos, respondiendo a la pregunta de optimización inversa.
        """
        ret_map = retention_by_party or {p: retention_rate for p in coalition_members}

        # 1. Escenario Separados
        res_sep = calculate_dhondt(
            votes=parties_votes,
            seats_to_allocate=seats,
            blank_votes=blank_votes,
            threshold_pct=threshold_pct,
        )
        sep_seats = sum(res_sep.seats.get(p, 0) for p in coalition_members)
        sep_votes = sum(parties_votes.get(p, 0.0) for p in coalition_members)
        sep_cost = (sep_votes / sep_seats) if sep_seats > 0 else 0.0

        # 2. Escenario Coalición (con retención individual por partido)
        coal_votes = sum(parties_votes.get(p, 0.0) * ret_map.get(p, retention_rate) for p in coalition_members)
        coal_parties_votes = {p: v for p, v in parties_votes.items() if p not in coalition_members}
        coal_parties_votes[coalition_name] = coal_votes

        res_coal = calculate_dhondt(
            votes=coal_parties_votes,
            seats_to_allocate=seats,
            blank_votes=blank_votes,
            threshold_pct=threshold_pct,
        )
        coal_seats = res_coal.seats.get(coalition_name, 0)
        coal_cost = (coal_votes / coal_seats) if coal_seats > 0 else 0.0

        diff = coal_seats - sep_seats
        if diff > 0:
            more_favorable = "Coalición"
        elif diff < 0:
            more_favorable = "Separados"
        else:
            more_favorable = "Empate"

        total_valid_votes = sum(parties_votes.values()) + max(0.0, blank_votes)

        # 3. Optimización Inversa para la circunscripción
        beneficiary = None
        if coal_seats > sep_seats:
            target_seats = coal_seats
            low_m = 1.0
            high_m = 5.0
            best_m = high_m
            best_sep_res = None

            for _ in range(30):
                mid_m = (low_m + high_m) / 2.0
                test_v = dict(parties_votes)
                for p in coalition_members:
                    test_v[p] = parties_votes.get(p, 0.0) * mid_m
                test_r = calculate_dhondt(test_v, seats, blank_votes, threshold_pct)
                s_test = sum(test_r.seats.get(p, 0) for p in coalition_members)
                if s_test >= target_seats:
                    best_m = mid_m
                    best_sep_res = test_r
                    high_m = mid_m
                else:
                    low_m = mid_m

            req_votes = sep_votes * best_m
            add_votes = req_votes - sep_votes
            add_pct = (add_votes / total_valid_votes * 100.0) if total_valid_votes > 0 else 0.0

            if best_sep_res:
                for p in coalition_members:
                    if best_sep_res.seats.get(p, 0) > res_sep.seats.get(p, 0):
                        beneficiary = p
                        break

        elif sep_seats > coal_seats:
            target_seats = sep_seats
            low_m = 1.0
            high_m = 4.0
            best_m = high_m

            for _ in range(30):
                mid_m = (low_m + high_m) / 2.0
                test_coal_v = dict(coal_parties_votes)
                test_coal_v[coalition_name] = coal_votes * mid_m
                test_r = calculate_dhondt(test_coal_v, seats, blank_votes, threshold_pct)
                s_test = test_r.seats.get(coalition_name, 0)
                if s_test >= target_seats:
                    best_m = mid_m
                    high_m = mid_m
                else:
                    low_m = mid_m

            req_votes = coal_votes * best_m
            add_votes = req_votes - coal_votes
            add_pct = (add_votes / total_valid_votes * 100.0) if total_valid_votes > 0 else 0.0
            beneficiary = coalition_name

        else:
            target_seats = sep_seats
            best_m = 1.0
            req_votes = sep_votes
            add_votes = 0.0
            add_pct = 0.0
            beneficiary = None

        # 4. Umbral de rentabilidad R* para esta circunscripción
        breakeven_r = None
        combined_raw_votes = sum(parties_votes.get(p, 0.0) for p in coalition_members)
        if combined_raw_votes > 0:
            for step_i in range(10, 201):
                r_test = step_i / 100.0
                test_v = {p: v for p, v in parties_votes.items() if p not in coalition_members}
                test_v[coalition_name] = combined_raw_votes * r_test
                s_test = calculate_dhondt(test_v, seats, blank_votes, threshold_pct).seats.get(coalition_name, 0)
                if s_test > sep_seats:
                    breakeven_r = r_test
                    break

        return SingleConstituencyComparison(
            seats=seats,
            blank_votes=blank_votes,
            threshold_pct=threshold_pct,
            parties_votes=parties_votes,
            coalition_members=coalition_members,
            coalition_name=coalition_name,
            retention_rate=retention_rate,
            retention_by_party=ret_map,
            result_separated=res_sep,
            result_coalition=res_coal,
            separated_left_seats=sep_seats,
            coalition_left_seats=coal_seats,
            separated_left_votes=sep_votes,
            coalition_left_votes=coal_votes,
            separated_votes_per_seat=sep_cost,
            coalition_votes_per_seat=coal_cost,
            seat_difference=diff,
            more_favorable_scenario=more_favorable,
            target_seats=target_seats,
            additional_votes_needed=round(add_votes, 1),
            additional_pct_needed=round(add_pct, 2),
            required_votes=round(req_votes, 1),
            multiplier=round(best_m, 2),
            beneficiary_party=beneficiary,
            breakeven_r=breakeven_r,
            census=census,
            turnout_pct=turnout_pct,
            null_votes=null_votes,
            valid_votes=total_valid_votes,
        )

    def plot_breakeven_chart(
        self,
        rates: List[float],
        coal_seats: List[int],
        sep_seats: int,
        breakeven_r: Optional[float],
    ) -> go.Figure:
        """
        Genera la gráfica de sensibilidad y rentabilidad de la coalición frente a la desafección.
        """
        fig = go.Figure()
        pct_rates = [r * 100 for r in rates]

        fig.add_trace(
            go.Scatter(
                x=pct_rates,
                y=coal_seats,
                mode="lines+markers",
                name="Lista Única",
                line=dict(color="#9C27B0", width=3),
                marker=dict(size=6),
                hovertemplate="Retención: %{x:.1f}%<br>Escaños coalición: %{y}<extra></extra>",
            )
        )

        fig.add_hline(
            y=sep_seats,
            line_dash="dash",
            line_color="#E30613",
            line_width=2.5,
            annotation_text=f"Escenario Separados: {sep_seats} escaños",
            annotation_position="top left",
            annotation_font=dict(color="#E30613", size=12),
        )

        if breakeven_r:
            fig.add_vline(
                x=breakeven_r * 100,
                line_dash="dot",
                line_color="#2E7D32",
                line_width=2,
                annotation_text=f"Umbral de rentabilidad: {breakeven_r * 100:.1f}% retención",
                annotation_position="bottom right",
                annotation_font=dict(color="#2E7D32", size=12),
            )

        fig.update_layout(
            title="<b>Rentabilidad Electoral de la Coalición vs. Desgaste / Rechazo de Votantes</b><br><sup>¿A partir de qué nivel de fuga de voto compensa ir por separado?</sup>",
            xaxis=dict(
                title="<b>Tasa de Retención de Votos de la Coalición (%)</b><br><sup>(100% = suma total de votos; 80% = un 20% de votantes se abstiene o no vota a la lista única)</sup>",
                ticksuffix="%",
                gridcolor="#E2E8F0",
            ),
            yaxis=dict(
                title="<b>Escaños Totales del Bloque</b>",
                gridcolor="#E2E8F0",
                dtick=2,
            ),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            hovermode="x unified",
            legend=dict(x=0.02, y=0.98),
            margin=dict(l=60, r=40, t=90, b=80),
        )

        return fig
