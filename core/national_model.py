"""
Modelo de agregación electoral nacional para las 52 circunscripciones de España.
Soporta:
- Normalización toponímica bidireccional (castellano / lenguas cooficiales / INE).
- Proyección por Swing Proporcional (Ratio Swing) a partir de encuestas.
- Control total circunscripción a circunscripción (votos o porcentajes, censo, participación, nulos y blancos).
- Coaliciones configurables circunscripción a circunscripción con fuga/retención partido a partido.
- Preconfiguración global de coalición con integrantes y tasas de retención por partido.
- Recuento nacional conmutador: 'Todos por separado' vs 'Con coaliciones configuradas'.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

try:
    from core.dhondt import calculate_dhondt, ConstituencyResult
except ImportError:
    from .dhondt import calculate_dhondt, ConstituencyResult

try:
    from core.toponyms import (
        normalize_province_name,
        are_same_province,
        get_province_display_name,
        is_andalusian_province,
        ToponymDict,
        CANONICAL_PROVINCES,
    )
except ImportError:
    from .toponyms import (
        normalize_province_name,
        are_same_province,
        get_province_display_name,
        is_andalusian_province,
        ToponymDict,
        CANONICAL_PROVINCES,
    )


DATA_PATH = Path(__file__).parent.parent / "data" / "circunscripciones_2023.json"

BASELINE_NATIONAL_2023 = {
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
    "Adelante Andalucía": 0.04,
}

ANDALUSIAN_PROVINCES = [
    "Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"
]

ANDALUSIA_ADELANTE_WEIGHTS = {
    "Cádiz": 1.42,
    "Sevilla": 1.30,
    "Málaga": 1.10,
    "Granada": 1.05,
    "Córdoba": 1.10,
    "Huelva": 0.95,
    "Almería": 0.75,
    "Jaén": 0.80,
}

TOTAL_VALID_VOTES_2023 = 24_688_087


@dataclass
class NationalSimulationResult:
    scenario_name: str
    national_seats: Dict[str, int]
    national_votes_est: Dict[str, float]
    national_pct_est: Dict[str, float]
    constituency_results: Dict[str, ConstituencyResult]
    constituency_data: List[Dict[str, Any]]
    total_seats: int = 350

    @property
    def national_votes(self) -> Dict[str, float]:
        """Alias de compatibilidad hacia atrás para acceder a las estimaciones de voto nacional."""
        return self.national_votes_est

    @property
    def national_pct(self) -> Dict[str, float]:
        """Alias de compatibilidad hacia atrás para acceder a los porcentajes de voto nacional."""
        return self.national_pct_est


class SpanishElectoralModel:
    def __init__(self, data_file: Optional[Path] = None):
        path = data_file or DATA_PATH
        with open(path, "r", encoding="utf-8") as f:
            self.constituencies = json.load(f)

        total_assigned_seats = sum(c["seats"] for c in self.constituencies)
        for c in self.constituencies:
            # Asegurar nombre canónico y display toponímico
            c["name"] = normalize_province_name(c["name"])
            c["display_name"] = get_province_display_name(c["name"])
            if "valid_votes" not in c:
                c["valid_votes"] = round(TOTAL_VALID_VOTES_2023 * (c["seats"] / total_assigned_seats))
            if "census" not in c:
                c["census"] = round(c["valid_votes"] / 0.69)
            if "turnout_pct" not in c:
                c["turnout_pct"] = round((c["valid_votes"] / c["census"]) * 100, 2) if c.get("census") else 66.59
            if "null_votes_pct" not in c:
                c["null_votes_pct"] = 1.0
            if "blank_votes_pct" not in c:
                c["blank_votes_pct"] = 0.8

        self._by_canonical = {c["name"]: c for c in self.constituencies}

    @property
    def parties(self) -> List[str]:
        """Devuelve la lista ordenada de todas las candidaturas presentes en los datos base y circunscripciones."""
        all_p = set(BASELINE_NATIONAL_2023.keys())
        for c in self.constituencies:
            if "parties_pct" in c and isinstance(c["parties_pct"], dict):
                all_p.update(c["parties_pct"].keys())
            if "parties_seats" in c and isinstance(c["parties_seats"], dict):
                all_p.update(c["parties_seats"].keys())
        return sorted([p for p in all_p if p and p not in {"Votos Blancos", "Nulos", "Censo", "Participación"}])

    def get_constituency_names(self) -> List[str]:
        return [c["name"] for c in self.constituencies]

    def get_constituency(self, name: str) -> Optional[Dict[str, Any]]:
        """Recupera la circunscripción aceptando cualquier variante toponímica castellana o cooficial."""
        canon = normalize_province_name(name)
        if hasattr(self, "_by_canonical") and canon in self._by_canonical:
            return self._by_canonical[canon]
        for c in self.constituencies:
            if are_same_province(c["name"], name):
                return c
        return None

    def simulate(
        self,
        national_poll: Dict[str, float],
        left_scenario: str = "separated",  # "separated" o "coalition" / "coalitions"
        coalition_retention_rate: float = 1.0,  # retención general por defecto
        custom_coalition_name: str = "Lista Única Izquierdas",
        blank_pct: float = 0.8,
        threshold_pct: float = 3.0,
        constituency_overrides: Optional[Dict[str, Any]] = None,
        default_coalition_members: Optional[List[str]] = None,
        default_retention_by_party: Optional[Dict[str, float]] = None,
        party_constituencies: Optional[Dict[str, List[str]]] = None,
        is_official_23j: Optional[bool] = None,
        party_multiplier: Optional[Dict[str, float]] = None,
        turnout_pct: Optional[float] = None,
        **kwargs,
    ) -> NationalSimulationResult:
        """
        Ejecuta la simulación completa para las 52 circunscripciones con resolución toponímica integral.
        Si se utilizan los resultados oficiales del 23J (is_official_23j=True o sondeo base 23J),
        se toman directamente los datos reales exactos circunscripción a circunscripción (diputados,
        votos válidos, censo y porcentajes oficiales) evitando la distorsión del swing proporcional.
        Permite además proyectar o modificar la participación electoral nacional de forma dinámica.
        """
        if is_official_23j is None:
            is_official_23j = kwargs.get("is_official_23j", None)
        if party_multiplier is None:
            party_multiplier = kwargs.get("party_multiplier", None)
        if turnout_pct is None:
            turnout_pct = kwargs.get("turnout_pct", None)
        national_seats: Dict[str, int] = {}
        national_votes_est: Dict[str, float] = {}
        constituency_results: ToponymDict = ToponymDict()
        simulated_constituencies_data = []

        # Detección automática de sondeo oficial 23J si no se especifica explícitamente
        if is_official_23j is None:
            is_official_23j = (
                national_poll.get("_is_official_23j", False)
                or (
                    abs(national_poll.get("PP", 0.0) - BASELINE_NATIONAL_2023.get("PP", 33.05)) < 0.05
                    and abs(national_poll.get("PSOE", 0.0) - BASELINE_NATIONAL_2023.get("PSOE", 31.70)) < 0.05
                    and abs(national_poll.get("Vox", 0.0) - BASELINE_NATIONAL_2023.get("Vox", 12.39)) < 0.05
                    and abs(national_poll.get("Sumar", 0.0) - BASELINE_NATIONAL_2023.get("Sumar", 12.31)) < 0.05
                    and national_poll.get("Podemos", 0.0) == 0.0
                )
            )

        # Base de participación nacional de referencia (23J oficial definitivo JEC / BOE = 66.59%)
        ref_nat_turnout = 66.59
        sim_turnout = turnout_pct
        if sim_turnout is None and isinstance(national_poll, dict) and "turnout" in national_poll and not is_official_23j:
            try:
                sim_turnout = float(national_poll["turnout"])
            except (ValueError, TypeError):
                sim_turnout = None

        turnout_ratio = (sim_turnout / ref_nat_turnout) if (sim_turnout is not None and ref_nat_turnout > 0) else 1.0
        is_exact_23j_run = (
            is_official_23j
            and (sim_turnout is None or abs(sim_turnout - ref_nat_turnout) < 0.05)
        )

        # Integrantes por defecto de la coalición
        def_members = default_coalition_members or ["Sumar", "Podemos"]
        def_ret_by_party = default_retention_by_party or {p: coalition_retention_rate for p in def_members}

        sumar_poll = national_poll.get("Sumar", 0.0)
        podemos_poll = national_poll.get("Podemos", 0.0)
        left_total_poll = sumar_poll + podemos_poll
        if left_total_poll == 0:
            left_total_poll = national_poll.get("Sumar", 12.31)

        baseline_left = BASELINE_NATIONAL_2023.get("Sumar", 12.31)

        # Preprocesar party_constituencies para normalizar toponimia de cada lista permitida
        normalized_party_scopes: Optional[Dict[str, set]] = None
        if party_constituencies:
            normalized_party_scopes = {
                p: {normalize_province_name(prov) for prov in provs}
                for p, provs in party_constituencies.items()
            }

        # Preprocesar constituency_overrides con toponimia canónica
        normalized_overrides: Dict[str, Any] = {}
        if constituency_overrides:
            for k, v in constituency_overrides.items():
                normalized_overrides[normalize_province_name(k)] = v

        for c in self.constituencies:
            c_name = c["name"]
            c_seats = c["seats"]
            baseline_parties_pct = c.get("parties_pct", {})

            # 1. Recuperar o sobreescribir parámetros electorales de la provincia (O(1) canónico)
            override = normalized_overrides.get(c_name, {})
            has_prov_override = bool(override)

            # Censo, participación, nulos, blancos y votos válidos
            c_census = float(override.get("census", c.get("census", round(c.get("valid_votes", TOTAL_VALID_VOTES_2023 * (c_seats / 350)) / 0.69))))
            c_seats = int(override.get("seats", c_seats))
            c_null_pct = float(override.get("null_pct", c.get("null_votes_pct", 1.0)))
            c_blank_pct = float(override.get("blank_pct", c.get("blank_votes_pct", blank_pct)))

            if "turnout_pct" in override:
                c_turnout_pct = float(override["turnout_pct"])
            elif sim_turnout is not None and not is_exact_23j_run:
                local_base_t = float(c.get("turnout_pct", ref_nat_turnout))
                c_turnout_pct = round(min(98.0, max(10.0, local_base_t * turnout_ratio)), 2)
            else:
                c_turnout_pct = float(c.get("turnout_pct", ref_nat_turnout))

            if is_exact_23j_run and not has_prov_override:
                # Tomar los datos reales exactos del 23J de esta circunscripción
                c_valid_votes = float(c.get("valid_votes", 0.0))
                if c_valid_votes <= 0:
                    c_voters = (c_turnout_pct / 100.0) * c_census
                    c_null_votes = (c_null_pct / 100.0) * c_voters
                    c_valid_votes = max(1.0, c_voters - c_null_votes)
                else:
                    c_null_votes = (c_null_pct / 100.0) * (c_valid_votes / max(0.01, 1.0 - (c_null_pct / 100.0)))
                c_blank_votes = (c_blank_pct / 100.0) * c_valid_votes
            else:
                if "valid_votes" in override:
                    c_valid_votes = float(override["valid_votes"])
                    c_null_votes = (c_null_pct / 100.0) * (c_valid_votes / max(0.01, 1.0 - (c_null_pct / 100.0)))
                elif not override and sim_turnout is None and "valid_votes" in c:
                    c_valid_votes = float(c["valid_votes"])
                    c_null_votes = (c_null_pct / 100.0) * (c_valid_votes / max(0.01, 1.0 - (c_null_pct / 100.0)))
                else:
                    c_voters = (c_turnout_pct / 100.0) * c_census
                    c_null_votes = (c_null_pct / 100.0) * c_voters
                    c_valid_votes = max(1.0, c_voters - c_null_votes)
                c_blank_votes = (c_blank_pct / 100.0) * c_valid_votes

            # 2. Obtener porcentajes o votos base de los partidos
            parties_votes_base: Dict[str, float] = {}
            parties_pct_base: Dict[str, float] = {}

            # Verificar si hay override directo de datos de partidos en la circunscripción
            parties_override = None
            if isinstance(override, dict):
                if "parties" in override and isinstance(override["parties"], dict):
                    parties_override = override["parties"]
                elif not any(k in override for k in ["coalition", "census", "turnout_pct", "blank_pct", "null_pct", "seats", "input_mode"]):
                    parties_override = override

            clean_override = {}
            if parties_override and isinstance(parties_override, dict):
                clean_override = {p: float(v) for p, v in parties_override.items() if not isinstance(v, dict) and float(v) > 0}

            input_mode = override.get("input_mode", "pct") if isinstance(override, dict) else "pct"

            if clean_override:
                # El usuario especificó datos personalizados para esta provincia
                if input_mode == "votes":
                    # Entrada directa en votos absolutos
                    parties_votes_base = dict(clean_override)
                    tot_v_cand = sum(parties_votes_base.values())
                    c_valid_votes = max(1.0, tot_v_cand + c_blank_votes)
                    parties_pct_base = {p: (v / c_valid_votes) * 100.0 for p, v in parties_votes_base.items()}
                else:
                    # Entrada en porcentajes
                    parties_pct_base = dict(clean_override)
                    # Normalizar a (100 - blank_pct)
                    sum_pct = sum(parties_pct_base.values())
                    target_sum = max(1.0, 100.0 - c_blank_pct)
                    if sum_pct > 0:
                        scale = target_sum / sum_pct
                        parties_pct_base = {p: v * scale for p, v in parties_pct_base.items()}
                    parties_votes_base = {p: (pct / 100.0) * c_valid_votes for p, pct in parties_pct_base.items()}
            elif is_official_23j:
                # Tomar los datos reales exactos del 23J para esta circunscripción (sin proyección swing)
                parties_pct_base = {p: float(pct) for p, pct in baseline_parties_pct.items() if float(pct) > 0}
                parties_votes_base = {p: (pct / 100.0) * c_valid_votes for p, pct in parties_pct_base.items()}
                if party_multiplier:
                    for p_m, mult in party_multiplier.items():
                        if p_m in parties_votes_base:
                            parties_votes_base[p_m] = parties_votes_base[p_m] * mult
                            parties_pct_base[p_m] = (parties_votes_base[p_m] / c_valid_votes) * 100.0
            else:
                # Proyección por Swing Proporcional nacional estándar
                proj_pct: Dict[str, float] = {}
                for party, poll_val in national_poll.items():
                    if party in ["Sumar", "Podemos", custom_coalition_name]:
                        continue
                    base_nat = BASELINE_NATIONAL_2023.get(party)
                    base_local = baseline_parties_pct.get(party, 0.0)
                    if base_nat and base_nat > 0:
                        ratio = poll_val / base_nat
                        proj_pct[party] = base_local * ratio
                    elif base_local > 0:
                        proj_pct[party] = base_local
                    else:
                        proj_pct[party] = poll_val

                # Espacio de la izquierda alternativa (Sumar / Podemos)
                base_left_local = baseline_parties_pct.get("Sumar", 0.0)
                ratio_sumar = sumar_poll / baseline_left if baseline_left > 0 else 0.5
                ratio_podemos = podemos_poll / baseline_left if baseline_left > 0 else 0.5
                if sumar_poll > 0:
                    proj_pct["Sumar"] = base_left_local * ratio_sumar
                if podemos_poll > 0:
                    proj_pct["Podemos"] = base_left_local * ratio_podemos

                # Partidos regionales estándar y formaciones que superaron el umbral legal del 3% en el 23J
                for reg_p in ["ERC", "Junts", "EH Bildu", "PNV", "BNG", "CC", "UPN"]:
                    if reg_p in baseline_parties_pct and reg_p not in proj_pct:
                        base_nat = BASELINE_NATIONAL_2023.get(reg_p, 1.0)
                        poll_val = national_poll.get(reg_p, base_nat)
                        ratio = poll_val / base_nat if base_nat > 0 else 1.0
                        proj_pct[reg_p] = baseline_parties_pct[reg_p] * ratio

                # Garantizar presencia de cualquier candidatura con >= 3.0% en esta provincia en el 23J
                for p_23j, pct_23j in baseline_parties_pct.items():
                    if pct_23j >= 3.0 and p_23j not in proj_pct and p_23j not in ["Sumar", "Podemos", custom_coalition_name]:
                        base_nat = BASELINE_NATIONAL_2023.get(p_23j)
                        poll_val = national_poll.get(p_23j, base_nat if base_nat else pct_23j)
                        ratio = (poll_val / base_nat) if (base_nat and base_nat > 0) else 1.0
                        proj_pct[p_23j] = pct_23j * ratio

                # Adelante Andalucía (distribución específica en las 8 provincias andaluzas con toponimia normalizada)
                if "Adelante Andalucía" in national_poll and national_poll["Adelante Andalucía"] > 0:
                    if is_andalusian_province(c_name):
                        adelante_nat = national_poll["Adelante Andalucía"]
                        base_local = ANDALUSIA_ADELANTE_WEIGHTS.get(c_name, 1.10)
                        proj_pct["Adelante Andalucía"] = base_local * (adelante_nat / 0.5)
                    else:
                        proj_pct["Adelante Andalucía"] = 0.0
                elif "Adelante Andalucía" in baseline_parties_pct:
                    proj_pct["Adelante Andalucía"] = baseline_parties_pct["Adelante Andalucía"]

                # Si se define en qué circunscripciones se presenta cada candidatura (toponimia tolerante)
                if normalized_party_scopes:
                    for p_name, allowed_set in normalized_party_scopes.items():
                        if normalize_province_name(c_name) not in allowed_set and p_name in proj_pct:
                            proj_pct[p_name] = 0.0

                # Normalizar porcentajes
                sum_p = sum(proj_pct.values())
                target_s = max(1.0, 100.0 - c_blank_pct)
                if sum_p > 0:
                    scale = target_s / sum_p
                    parties_pct_base = {p: v * scale for p, v in proj_pct.items()}
                else:
                    parties_pct_base = proj_pct

                parties_votes_base = {p: (pct / 100.0) * c_valid_votes for p, pct in parties_pct_base.items()}

            # Si se configuró ámbito territorial por partido y la provincia no tiene override manual expreso de candidaturas
            has_explicit_parties_override = (
                isinstance(override, dict)
                and "parties" in override
                and isinstance(override["parties"], dict)
                and len(override["parties"]) > 0
            )
            if normalized_party_scopes and not has_explicit_parties_override:
                for p_name, allowed_set in normalized_party_scopes.items():
                    if normalize_province_name(c_name) not in allowed_set and p_name in parties_votes_base:
                        del parties_votes_base[p_name]

            # 3. Aplicar lógica de Coalición (Escenario Separados vs. Con Coaliciones)
            final_votes_for_dhondt: Dict[str, float] = {}

            if left_scenario == "separated":
                # Todos compiten de forma separada
                final_votes_for_dhondt = dict(parties_votes_base)
            else:
                # Escenario con Coaliciones configuradas
                # Revisar configuración de coalición específica para esta circunscripción
                c_coalition_info = override.get("coalition", {}) if isinstance(override, dict) else {}
                coalition_enabled = c_coalition_info.get("enabled", True)

                if coalition_enabled:
                    coal_name = c_coalition_info.get("name", custom_coalition_name)
                    coal_members = c_coalition_info.get("members", def_members)
                    coal_ret_map = c_coalition_info.get("retention_by_party", def_ret_by_party)

                    # Partidos que no entran a la coalición conservan sus votos
                    non_coal_votes = {p: v for p, v in parties_votes_base.items() if p not in coal_members}

                    # Sumar votos aportados por cada integrante aplicando su tasa de retención individual
                    unified_coal_votes = 0.0
                    for m in coal_members:
                        v_m = parties_votes_base.get(m, 0.0)
                        r_m = coal_ret_map.get(m, coalition_retention_rate)
                        unified_coal_votes += v_m * r_m

                    final_votes_for_dhondt = non_coal_votes
                    if unified_coal_votes > 0:
                        final_votes_for_dhondt[coal_name] = unified_coal_votes
                else:
                    # En esta circunscripción concreta se desactivó la coalición
                    final_votes_for_dhondt = dict(parties_votes_base)

            # 4. Cálculo D'Hondt para esta circunscripción
            dhondt_res = calculate_dhondt(
                votes=final_votes_for_dhondt,
                seats_to_allocate=c_seats,
                blank_votes=c_blank_votes,
                threshold_pct=threshold_pct,
            )

            # Salvaguarda de exactitud institucional para el resultado oficial 23J por circunscripción
            if is_official_23j and left_scenario == "separated" and not clean_override and c.get("parties_seats") and c_seats == c["seats"] and not party_multiplier:
                dhondt_res.seats = dict(c["parties_seats"])

            constituency_results[c_name] = dhondt_res

            for p, s in dhondt_res.seats.items():
                national_seats[p] = national_seats.get(p, 0) + s
                v_count = final_votes_for_dhondt.get(p, 0.0)
                national_votes_est[p] = national_votes_est.get(p, 0.0) + v_count

            simulated_constituencies_data.append({
                "name": c_name,
                "display_name": get_province_display_name(c_name),
                "community": c.get("community", ""),
                "seats": c_seats,
                "census": c_census,
                "turnout_pct": c_turnout_pct,
                "valid_votes": c_valid_votes,
                "blank_votes": c_blank_votes,
                "null_votes": c_null_votes,
                "parties_pct": parties_pct_base,
                "parties_votes": final_votes_for_dhondt,
                "raw_parties_votes": parties_votes_base,
                "result": dhondt_res,
            })

        total_v = sum(national_votes_est.values())
        national_pct_est = {
            p: (v / total_v * 100.0) if total_v > 0 else 0.0
            for p, v in national_votes_est.items()
        }

        return NationalSimulationResult(
            scenario_name="Con Coaliciones" if left_scenario != "separated" else "Todos Separados",
            national_seats=national_seats,
            national_votes_est=national_votes_est,
            national_pct_est=national_pct_est,
            constituency_results=constituency_results,
            constituency_data=simulated_constituencies_data,
        )
