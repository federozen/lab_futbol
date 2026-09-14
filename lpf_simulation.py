"""Primitivas Monte Carlo puras para la LPF.

No conoce Streamlit, red ni estado global de la aplicación. Recibe fuerzas,
fixture pendiente y contexto de competencia por parámetro y devuelve arrays NumPy
que las capas superiores convierten en probabilidades o narrativas.
"""
from __future__ import annotations

import numpy as np

from lpf_averages import combine_average_totals, normalize_previous_averages
from lpf_qualification import allocate_cup_slots, annual_base

LPF_RUNTIME_API = 21

DEFAULT_DRAW_PROBABILITY = 0.26
DEFAULT_HOME_ADVANTAGE = 1.22


def match_outcome_probabilities(
    home_strength,
    away_strength,
    draw_probability=DEFAULT_DRAW_PROBABILITY,
    home_advantage=DEFAULT_HOME_ADVANTAGE,
):
    """Probabilidades canónicas (local, empate, visitante) del modelo LPF.

    La ventaja local se aplica sólo a la fuerza del local y el empate conserva
    una probabilidad fija. Esta función centraliza el kernel para que Previa,
    Monte Carlo y contexto competitivo no deriven fórmulas distintas.
    """
    draw = float(draw_probability)
    weighted_home = float(home_strength) * float(home_advantage)
    weighted_away = float(away_strength)
    decisive = 1.0 - draw
    home = decisive * weighted_home / (weighted_home + weighted_away)
    away = decisive - home
    return home, draw, away


def summarize_rank_condition(positions, final_points, target_rank, *, min_samples=100):
    """Resume puntos finales condicionado a terminar en ``target_rank``.

    Devuelve también cuántas corridas sostienen el resumen. La mediana y los
    cuantiles condicionados pueden ser muy sensibles cuando el puesto aparece
    pocas veces; ``stable`` hace visible ese tamaño de muestra a la UI.
    """
    positions = np.asarray(positions)
    final_points = np.asarray(final_points)
    if positions.shape != final_points.shape:
        raise ValueError("positions y final_points deben tener la misma forma")
    total = int(positions.size)
    mask = positions == int(target_rank)
    selected = final_points[mask]
    count = int(selected.size)
    result = {
        "target_rank": int(target_rank),
        "simulations": total,
        "samples": count,
        "probability": (float(count / total) if total else 0.0),
        "stable": count >= int(min_samples),
        "minimum_samples": int(min_samples),
        "median": None,
        "q25": None,
        "q75": None,
        "distribution": [],
    }
    if not count:
        return result
    values, counts = np.unique(selected.astype(int), return_counts=True)
    result.update({
        "median": float(np.median(selected)),
        "q25": float(np.quantile(selected, 0.25)),
        "q75": float(np.quantile(selected, 0.75)),
        "distribution": [
            {
                "final_points": int(value),
                "samples": int(n),
                "frequency": float(n / count),
            }
            for value, n in zip(values, counts)
        ],
    })
    return result


def build_simulation_context(
    zones,
    remaining,
    opening,
    camps,
    extras,
    previous_averages,
    *,
    direct_annual=None,
    opening_rounds,
    copa_replacement="",
    n_annual=1,
    n_average=1,
):
    """Arma el contexto estable compartido por las simulaciones de objetivos.

    Todas las fotos que antes podían llegar implícitamente desde la capa de UI
    entran de forma explícita. El resultado conserva la estructura histórica de
    ``_lpf_ctx`` para que los consumidores Monte Carlo no cambien.
    """
    zones = zones or {}
    annual = annual_base(
        zones,
        opening=opening or {},
        direct_annual=direct_annual or {},
        opening_rounds=opening_rounds,
    )
    allocation = allocate_cup_slots(
        annual,
        camps=camps or ("", "", ""),
        extras=extras or ("", ""),
        copa_replacement=copa_replacement or "",
    )
    previous = normalize_previous_averages(previous_averages)
    average_totals = combine_average_totals(annual, previous, zones=zones) or {}
    teams = [team for base in zones.values() for team in base]
    zone_of = {team: label for label, base in zones.items() for team in base}
    zone_points = {team: zones[zone_of[team]][team]["pts"] for team in teams}
    zone_goal_difference = {
        team: zones[zone_of[team]][team].get("dg", 0) for team in teams
    }
    annual_points = {team: annual[team]["pts"] for team in teams if team in annual}
    annual_goal_difference = {
        team: annual[team].get("dg", 0) for team in teams if team in annual
    }
    return {
        "Z": zones,
        "anual": annual,
        "reducida": allocation["reducida"],
        "n_lib": allocation["n_tabla_lib"],
        "tomados": allocation["tomados"],
        "orden": allocation["orden"],
        "equipos": teams,
        "zona_de": zone_of,
        "zpts": zone_points,
        "zdg": zone_goal_difference,
        "apts": annual_points,
        "adg": annual_goal_difference,
        "previous_averages": previous,
        "average_totals": average_totals,
        # Alias legacy: históricamente ``ctx["prom"]`` se consumía como totales.
        "prom": average_totals,
        "rest": remaining,
        "n_anual": n_annual,
        "n_prom": n_average,
    }


def simulate_zone_rank_points(
    base,
    remaining,
    pending,
    target,
    n,
    seed,
    strength,
    forced=None,
    pdraw=DEFAULT_DRAW_PROBABILITY,
    loc=DEFAULT_HOME_ADVANTAGE,
):
    """Simula posición y puntos finales de ``target`` dentro de su zona."""
    rng = np.random.default_rng(seed)
    teams = list(base.keys())
    idx = {team: i for i, team in enumerate(teams)}
    points = np.tile(np.array([base[team]["pts"] for team in teams], float), (n, 1))
    dg0 = np.array([float(base[team].get("dg", 0)) for team in teams])
    forced = dict(forced or {})
    consumed = {team: 0 for team in teams}

    for (local, visitor), outcome in forced.items():
        for team in (local, visitor):
            if team in idx:
                consumed[team] += 1
        if outcome == "L" and local in idx:
            points[:, idx[local]] += 3
        elif outcome == "V" and visitor in idx:
            points[:, idx[visitor]] += 3
        elif outcome == "E":
            if local in idx:
                points[:, idx[local]] += 1
            if visitor in idx:
                points[:, idx[visitor]] += 1

    in_fixture = {team: 0 for team in teams}
    for local, visitor in pending:
        if (local, visitor) in forced or (local not in idx and visitor not in idx):
            continue
        if local in idx:
            in_fixture[local] += 1
        if visitor in idx:
            in_fixture[visitor] += 1
        p_local, p_draw, _p_visitor = match_outcome_probabilities(
            strength.get(local, 1.0), strength.get(visitor, 1.0), pdraw, loc
        )
        sample = rng.random(n)
        local_win = sample < p_local
        visitor_win = sample >= p_local + p_draw
        if local in idx:
            points[:, idx[local]] += np.where(local_win, 3, np.where(visitor_win, 0, 1))
        if visitor in idx:
            points[:, idx[visitor]] += np.where(visitor_win, 3, np.where(local_win, 0, 1))

    for team in teams:
        extra = max(0, remaining.get(team, 0) - in_fixture[team] - consumed[team])
        if extra:
            p_team, p_draw, _p_average = match_outcome_probabilities(
                strength[team], 1.0, pdraw, 1.0
            )
            sample = rng.random((n, extra))
            points[:, idx[team]] += np.where(
                sample < p_team,
                3,
                np.where(sample < p_team + p_draw, 1, 0),
            ).sum(axis=1)

    key = points + dg0[None, :] * 1e-4 + rng.random((n, len(teams))) * 1e-7
    positions = np.argsort(np.argsort(-key, axis=1), axis=1) + 1
    return positions[:, idx[target]], points[:, idx[target]].astype(int)


def simulate_point_additions(
    teams,
    pending,
    strength,
    n,
    seed,
    forced=None,
    pdraw=DEFAULT_DRAW_PROBABILITY,
    loc=DEFAULT_HOME_ADVANTAGE,
):
    """Simula los puntos que suma cada equipo en todos los partidos pendientes."""
    rng = np.random.default_rng(seed)
    idx = {team: i for i, team in enumerate(teams)}
    add = np.zeros((n, len(teams)))
    forced = forced or {}
    for local, visitor in pending:
        if local not in idx or visitor not in idx:
            continue
        ilocal, ivisitor = idx[local], idx[visitor]
        outcome = forced.get((local, visitor))
        if outcome == "L":
            add[:, ilocal] += 3
        elif outcome == "V":
            add[:, ivisitor] += 3
        elif outcome == "E":
            add[:, ilocal] += 1
            add[:, ivisitor] += 1
        else:
            p_local, p_draw, _p_visitor = match_outcome_probabilities(
                strength[local], strength[visitor], pdraw, loc
            )
            sample = rng.random(n)
            local_win = sample < p_local
            visitor_win = sample >= p_local + p_draw
            add[:, ilocal] += np.where(local_win, 3, np.where(visitor_win, 0, 1))
            add[:, ivisitor] += np.where(visitor_win, 3, np.where(local_win, 0, 1))
    return add, idx


def objective_mask(objective, team, additions, idx, context):
    """Indica en cada corrida si ``team`` cumple el objetivo pedido."""
    n = additions.shape[0]
    if objective == "playoffs":
        zone = context["zona_de"].get(team)
        if not zone:
            return np.zeros(n, bool)
        zone_teams = list(context["Z"][zone])
        eps = np.arange(len(zone_teams), dtype=float) * 1e-8
        key = (
            np.array([context["zpts"][other] + context["zdg"][other] * 1e-4 for other in zone_teams])[None, :]
            + eps
            + additions[:, [idx[other] for other in zone_teams]]
        )
        target_index = zone_teams.index(team)
        return ((key > key[:, target_index:target_index + 1]).sum(1) + 1) <= 8

    if objective in ("libertadores", "sudamericana", "al_menos_sudamericana"):
        reduced = context["reducida"]
        if team not in reduced:
            return np.zeros(n, bool)
        eps = np.arange(len(reduced), dtype=float) * 1e-8
        key = (
            np.array([context["apts"][other] + context["adg"][other] * 1e-4 for other in reduced])[None, :]
            + eps
            + additions[:, [idx[other] for other in reduced]]
        )
        target_index = reduced.index(team)
        rank = (key > key[:, target_index:target_index + 1]).sum(1) + 1
        if objective == "libertadores":
            return rank <= context["n_lib"]
        if objective == "al_menos_sudamericana":
            return rank <= context["n_lib"] + 6
        return (rank > context["n_lib"]) & (rank <= context["n_lib"] + 6)

    if objective == "descenso":
        averages = context.get("average_totals") or context.get("prom") or {}
        remaining = context["rest"]
        average_teams = [other for other in context["equipos"] if other in averages]
        if average_teams:
            numerator = (
                np.array([averages[other][0] for other in average_teams], float)[None, :]
                + additions[:, [idx[other] for other in average_teams]]
            )
            denominator = np.array(
                [averages[other][1] + remaining.get(other, 0) for other in average_teams],
                float,
            )[None, :]
            average_value = numerator / denominator
            average_last = np.array(average_teams)[average_value.argmin(1)]
        else:
            average_last = np.array([""] * n)

        annual_teams = [other for other in context["equipos"] if other in context["apts"]]
        eps = np.arange(len(annual_teams), dtype=float) * 1e-8
        annual_key = (
            np.array([context["apts"][other] + context["adg"][other] * 1e-4 for other in annual_teams])[None, :]
            + eps
            + additions[:, [idx[other] for other in annual_teams]]
        )
        order = annual_key.argsort(1)
        annual_last = np.array(annual_teams)[order[:, 0]]
        annual_second_last = np.array(annual_teams)[order[:, 1]]
        annual_relegated = np.where(annual_last == average_last, annual_second_last, annual_last)
        return (average_last == team) | (annual_relegated == team)

    return np.zeros(n, bool)
