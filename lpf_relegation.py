"""Foto actual de los descensos respetando desempates obligatorios.

La diferencia de gol no decide una igualdad en una posición de descenso. Este
módulo separa equipos que bajarían sin desempate de los que deberían jugarlo y
resuelve además la regla de que el descenso por Tabla Anual excluye al equipo que
ya descendió por promedios.
"""
from __future__ import annotations

from fractions import Fraction
from itertools import combinations
from collections.abc import Mapping, Sequence

LPF_RUNTIME_API = 21


def _bottom_resolution(items, score, slots: int):
    slots = max(0, int(slots))
    groups = {}
    for item in items:
        groups.setdefault(score(item), []).append(item)
    confirmed = []
    playoff = []
    playoff_slots = 0
    remaining = slots
    for value in sorted(groups):
        if remaining <= 0:
            break
        group = groups[value]
        if len(group) <= remaining:
            confirmed.extend(group)
            remaining -= len(group)
        else:
            playoff = list(group)
            playoff_slots = remaining
            remaining = 0
    return confirmed, playoff, playoff_slots


def _avg_score(row):
    pts = int(row.get("Pts", row.get("points", row.get("pts", 0))) or 0)
    played = int(row.get("PJ", row.get("played", row.get("pj", 0))) or 0)
    return Fraction(pts, played) if played else Fraction(0, 1)


def current_relegation_picture(
    annual: Mapping[str, Mapping[str, object]],
    averages: Sequence[Mapping[str, object]] | None,
    *,
    annual_relegations: int = 1,
    average_relegations: int = 1,
) -> dict[str, object]:
    annual_items = [
        {"team": str(team), "pts": int((row or {}).get("pts", 0))}
        for team, row in (annual or {}).items()
    ]
    avg_items = [dict(row) for row in (averages or [])]
    for row in avg_items:
        row["team"] = str(row.get("Equipo", row.get("team", "")))

    avg_confirmed, avg_playoff, avg_playoff_slots = _bottom_resolution(
        avg_items, _avg_score, int(average_relegations)
    ) if avg_items and average_relegations else ([], [], 0)
    confirmed_names = [row["team"] for row in avg_confirmed]
    playoff_names = [row["team"] for row in avg_playoff]

    if avg_playoff:
        choices = [
            tuple(choice)
            for choice in combinations(playoff_names, avg_playoff_slots)
        ]
    else:
        choices = [tuple()]

    annual_scenarios = []
    for choice in choices:
        relegated_avg = set(confirmed_names) | set(choice)
        pool = [row for row in annual_items if row["team"] not in relegated_avg]
        confirmed, playoff, playoff_slots = _bottom_resolution(
            pool, lambda row: int(row["pts"]), int(annual_relegations)
        ) if annual_relegations else ([], [], 0)
        annual_scenarios.append({
            "average_relegated": sorted(relegated_avg),
            "annual_confirmed": [row["team"] for row in confirmed],
            "annual_playoff": [row["team"] for row in playoff],
            "annual_playoff_slots": playoff_slots,
        })

    annual_candidate_sets = [
        set(scenario["annual_confirmed"]) | set(scenario["annual_playoff"])
        for scenario in annual_scenarios
    ]
    annual_candidates = sorted(set().union(*annual_candidate_sets)) if annual_candidate_sets else []
    if annual_scenarios:
        common = set(annual_scenarios[0]["annual_confirmed"])
        for scenario in annual_scenarios[1:]:
            common &= set(scenario["annual_confirmed"])
        annual_confirmed_common = sorted(common)
    else:
        annual_confirmed_common = []

    return {
        "average_confirmed": confirmed_names,
        "average_playoff": playoff_names,
        "average_playoff_slots": avg_playoff_slots,
        "annual_scenarios": annual_scenarios,
        "annual_confirmed_common": annual_confirmed_common,
        "annual_candidates": annual_candidates,
        "annual_depends_on_average_playoff": len(annual_scenarios) > 1,
    }
