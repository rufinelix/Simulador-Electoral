"""
Motor de cálculo de la Ley D'Hondt para reparto de escaños electorales.
Cumple con la normativa electoral española (LOREG art. 163).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math


@dataclass
class QuotientEntry:
    party: str
    seat_order: int  # 1, 2, ..., total_seats
    quotient: float
    party_seat_num: int  # 1st seat of this party, 2nd, etc.
    won: bool


@dataclass
class ConstituencyResult:
    seats_to_allocate: int
    seats: Dict[str, int]
    valid_votes: float
    blank_votes: float
    threshold_pct: float
    threshold_votes: float
    excluded_parties: List[str]
    quotients: List[QuotientEntry]
    cutoff_quotient: float
    last_seat_winner: Optional[str]
    runner_up_party: Optional[str]
    runner_up_quotient: float
    votes_needed_for_next_seat: Dict[str, float]
    votes: Dict[str, float] = field(default_factory=dict)


def calculate_dhondt(
    votes: Dict[str, float],
    seats_to_allocate: int,
    blank_votes: float = 0.0,
    threshold_pct: float = 3.0,
) -> ConstituencyResult:
    """
    Calcula el reparto de escaños de una circunscripción según la Ley D'Hondt.

    Parámetros:
    -----------
    votes : dict
        Diccionario con {nombre_partido: numero_votos_o_porcentaje}
    seats_to_allocate : int
        Número de escaños a repartir en la circunscripción
    blank_votes : float
        Número o peso de votos en blanco (cuentan para el umbral legal)
    threshold_pct : float
        Porcentaje mínimo de votos válidos para entrar al reparto (por defecto 3.0%)

    Retorna:
    --------
    ConstituencyResult
    """
    if seats_to_allocate <= 0:
        raise ValueError("seats_to_allocate debe ser mayor que 0")

    # 1. Votos válidos totales = suma votos a candidaturas + votos en blanco
    total_candidate_votes = sum(v for v in votes.values() if v > 0)
    valid_votes = total_candidate_votes + max(0.0, blank_votes)

    if valid_votes <= 0:
        return ConstituencyResult(
            seats_to_allocate=seats_to_allocate,
            seats={p: 0 for p in votes},
            valid_votes=0.0,
            blank_votes=blank_votes,
            threshold_pct=threshold_pct,
            threshold_votes=0.0,
            excluded_parties=list(votes.keys()),
            quotients=[],
            cutoff_quotient=0.0,
            last_seat_winner=None,
            runner_up_party=None,
            runner_up_quotient=0.0,
            votes_needed_for_next_seat={p: 0.0 for p in votes},
            votes=dict(votes),
        )

    # 2. Umbral de exclusión (en España, sobre los votos válidos en la circunscripción)
    threshold_votes = (threshold_pct / 100.0) * valid_votes

    eligible_parties = {}
    excluded_parties = []

    for party, v in votes.items():
        if v >= threshold_votes and v > 0:
            eligible_parties[party] = float(v)
        else:
            excluded_parties.append(party)

    # Si no hay listas que pasen el umbral
    if not eligible_parties:
        return ConstituencyResult(
            seats_to_allocate=seats_to_allocate,
            seats={p: 0 for p in votes},
            valid_votes=valid_votes,
            blank_votes=blank_votes,
            threshold_pct=threshold_pct,
            threshold_votes=threshold_votes,
            excluded_parties=list(votes.keys()),
            quotients=[],
            cutoff_quotient=0.0,
            last_seat_winner=None,
            runner_up_party=None,
            runner_up_quotient=0.0,
            votes_needed_for_next_seat={p: threshold_votes for p in votes},
            votes=dict(votes),
        )

    # 3. Matriz de cocientes: Q_{i, s} = V_i / s
    all_quotients: List[Tuple[float, float, str, int]] = []
    # Guardamos tuplas: (quotient, total_votes_party, party, party_seat_num)
    # total_votes_party se usa como criterio de desempate según LOREG art 163.1.b
    for party, v in eligible_parties.items():
        for s in range(1, seats_to_allocate + 1):
            q = v / s
            all_quotients.append((q, v, party, s))

    # 4. Ordenar de mayor a menor cociente (desempate por votos totales del partido)
    all_quotients.sort(key=lambda item: (item[0], item[1]), reverse=True)

    # 5. Asignar los S mayores cocientes
    seats_won = {p: 0 for p in votes}
    quotients_result: List[QuotientEntry] = []

    cutoff_quotient = 0.0
    last_seat_winner = None

    assigned_count = min(seats_to_allocate, len(all_quotients))

    for idx in range(assigned_count):
        q, v, party, seat_num = all_quotients[idx]
        seats_won[party] += 1
        cutoff_quotient = q
        last_seat_winner = party
        quotients_result.append(
            QuotientEntry(
                party=party,
                seat_order=idx + 1,
                quotient=q,
                party_seat_num=seat_num,
                won=True,
            )
        )

    # 6. Identificar el cociente a las puertas (runner-up: posición S)
    runner_up_party = None
    runner_up_quotient = 0.0
    if len(all_quotients) > assigned_count:
        q_next, _, party_next, seat_num_next = all_quotients[assigned_count]
        runner_up_party = party_next
        runner_up_quotient = q_next
        quotients_result.append(
            QuotientEntry(
                party=party_next,
                seat_order=assigned_count + 1,
                quotient=q_next,
                party_seat_num=seat_num_next,
                won=False,
            )
        )

    # 7. Cálculo de votos necesarios para el siguiente escaño
    # Para cualquier partido p, su siguiente escaño es (seats_won[p] + 1).
    # Necesita que su cociente (v_p + delta) / (seats_won[p] + 1) supere el corte.
    # Si p es el partido que ganó el último escaño, el "corte a batir" para ganar UNO MÁS
    # sigue siendo el corte frente a los demás (o el runner up).
    votes_needed_for_next: Dict[str, float] = {}

    for party, v in votes.items():
        if party in excluded_parties:
            # Primero debe llegar al umbral electoral
            needed_for_threshold = max(0.0, threshold_votes - v)
            votes_needed_for_next[party] = round(needed_for_threshold, 2)
        else:
            current_s = seats_won.get(party, 0)
            target_s = current_s + 1
            # Para superar el corte: (v + delta) / target_s > cutoff_quotient
            # delta = target_s * cutoff_quotient - v
            # Si delta <= 0, necesitaría superar al runner_up si party es el último ganador
            needed = target_s * cutoff_quotient - v
            if needed <= 0 and runner_up_quotient > 0:
                needed = target_s * runner_up_quotient - v
            votes_needed_for_next[party] = max(0.0, round(needed, 2))

    return ConstituencyResult(
        seats_to_allocate=seats_to_allocate,
        seats=seats_won,
        valid_votes=valid_votes,
        blank_votes=blank_votes,
        threshold_pct=threshold_pct,
        threshold_votes=threshold_votes,
        excluded_parties=excluded_parties,
        quotients=quotients_result,
        cutoff_quotient=cutoff_quotient,
        last_seat_winner=last_seat_winner,
        runner_up_party=runner_up_party,
        runner_up_quotient=runner_up_quotient,
        votes_needed_for_next_seat=votes_needed_for_next,
        votes=dict(votes),
    )
