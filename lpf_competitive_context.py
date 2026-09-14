"""Contexto competitivo e histórico para objetivos de la LPF.

Este módulo separa tres capas que no deben confundirse:

* la foto actual de la tabla;
* la proyección estimada a partir del fixture pendiente completo;
* la referencia histórica, normalizada por partidos cuando corresponde.

No importa Streamlit y no modifica las garantías matemáticas. La simulación se usa
sólo como estimación editorial: cada partido pendiente se resuelve una sola vez, por
lo que respeta el sobreconteo que producirían los cruces entre rivales y el doble efecto
de los enfrentamientos directos del equipo consultado.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean, median
from typing import Iterable, Mapping

import numpy as np

from lpf_simulation import (
    DEFAULT_DRAW_PROBABILITY,
    DEFAULT_HOME_ADVANTAGE,
    match_outcome_probabilities,
)

LPF_RUNTIME_API = 21


# Los playoffs 2025/26 comparten formato de 16 partidos por zona. La muestra se
# guarda como cortes, no como garantías: cinco de los seis octavos sumaron 21 y uno 18.
PLAYOFF_CUTOFF_HISTORY = (
    {"season": 2025, "tournament": "Apertura", "zone": "A", "matches": 16, "points": 21},
    {"season": 2025, "tournament": "Apertura", "zone": "B", "matches": 16, "points": 18},
    {"season": 2025, "tournament": "Clausura", "zone": "A", "matches": 16, "points": 21},
    {"season": 2025, "tournament": "Clausura", "zone": "B", "matches": 16, "points": 21},
    {"season": 2026, "tournament": "Apertura", "zone": "A", "matches": 16, "points": 21},
    {"season": 2026, "tournament": "Apertura", "zone": "B", "matches": 16, "points": 21},
)

# Último clasificado efectivo por Tabla Anual. Los puntos se normalizan por PJ antes
# de compararlos con el formato de 32 partidos. Las plazas obtenidas como campeón no
# se mezclan con esta muestra.
CUP_CUTOFF_HISTORY = (
    {"season": 2022, "matches": 41, "libertadores": 65, "sudamericana": 58},
    {"season": 2023, "matches": 41, "libertadores": 63, "sudamericana": 54},
    {"season": 2024, "matches": 41, "libertadores": 67, "sudamericana": 58},
    {"season": 2025, "matches": 32, "libertadores": 57, "sudamericana": 48},
)


def _points(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("pts", 0))
    return int(value)


def _stat(value: object, key: str, default: int = 0) -> int:
    if isinstance(value, Mapping):
        return int(value.get(key, default))
    return default


def historical_reference(objective: str, *, target_matches: int | None = None) -> dict[str, object]:
    """Devuelve una referencia histórica claramente rotulada como tal.

    Para Libertadores y Sudamericana convierte cada temporada a puntos por partido y
    luego la expresa en la cantidad de encuentros del formato actual. Para playoffs
    usa sólo antecedentes del mismo formato.
    """
    key = str(objective).lower().strip()
    if key == "playoffs":
        rows = list(PLAYOFF_CUTOFF_HISTORY)
        values = [float(row["points"]) for row in rows]
        return {
            "objective": key,
            "sample_size": len(values),
            "target_matches": 16,
            "mean": mean(values),
            "median": median(values),
            "minimum": min(values),
            "maximum": max(values),
            "latest_same_format": values[-1],
            "latest_season": rows[-1]["season"],
            "normalized": False,
            "records": rows,
        }
    if key not in ("libertadores", "sudamericana"):
        raise ValueError(f"Objetivo histórico desconocido: {objective}")
    target = int(target_matches or 32)
    rows = list(CUP_CUTOFF_HISTORY)
    equivalents = [float(row[key]) / float(row["matches"]) * target for row in rows]
    same_format = [row for row in rows if int(row["matches"]) == target]
    latest_same = None
    latest_season = None
    if same_format:
        last = max(same_format, key=lambda row: int(row["season"]))
        latest_same = float(last[key])
        latest_season = int(last["season"])
    return {
        "objective": key,
        "sample_size": len(equivalents),
        "target_matches": target,
        "mean": mean(equivalents),
        "median": median(equivalents),
        "minimum": min(equivalents),
        "maximum": max(equivalents),
        "latest_same_format": latest_same,
        "latest_season": latest_season,
        "normalized": True,
        "records": [
            {
                **row,
                "equivalent": float(row[key]) / float(row["matches"]) * target,
            }
            for row in rows
        ],
    }


def _current_order(base: Mapping[str, object]) -> list[str]:
    return sorted(
        base,
        key=lambda team: (
            -_points(base[team]),
            -_stat(base[team], "dg"),
            -_stat(base[team], "gf"),
            team,
        ),
    )


def _regularized_strength(base: Mapping[str, object], names: Iterable[str]) -> dict[str, float]:
    prior_ppg = 1.35
    prior_games = 6.0
    raw: dict[str, float] = {}
    for team in names:
        row = base.get(team)
        if row is None:
            raw[team] = prior_ppg
            continue
        pj = max(0, _stat(row, "pj"))
        pts = _points(row)
        raw[team] = (pts + prior_ppg * prior_games) / (pj + prior_games)
    known = [raw[team] for team in base if team in raw]
    centre = float(np.median(known)) if known else prior_ppg
    if centre <= 0:
        centre = prior_ppg
    return {team: min(1.75, max(0.55, raw[team] / centre)) for team in raw}


def _quantile_int(values: np.ndarray, q: float) -> int:
    try:
        return int(np.quantile(values, q, method="nearest"))
    except TypeError:  # NumPy anterior
        return int(np.quantile(values, q, interpolation="nearest"))


def _simulate_fixture(
    base: Mapping[str, object],
    matches: tuple[tuple[str, str], ...],
    team: str,
    cutoff: int,
    *,
    strength_base: Mapping[str, object] | None,
    strength: Mapping[str, float] | None,
    simulations: int,
    seed: int,
    draw_probability: float,
    home_advantage: float,
) -> dict[str, object]:
    teams = list(base)
    index = {name: idx for idx, name in enumerate(teams)}
    all_names = set(teams)
    for home, away in matches:
        all_names.add(home)
        all_names.add(away)
    if strength is None:
        model_strength = _regularized_strength(strength_base or base, all_names)
        strength_source = "regularized_current_points"
    else:
        model_strength = {name: float(strength.get(name, 1.0)) for name in all_names}
        strength_source = "provided_canonical"
    rng = np.random.default_rng(int(seed))
    additions = np.zeros((int(simulations), len(teams)), dtype=np.int16)

    for home, away in matches:
        p_home, p_draw, _p_away = match_outcome_probabilities(
            model_strength.get(home, 1.0),
            model_strength.get(away, 1.0),
            draw_probability,
            home_advantage,
        )
        u = rng.random(int(simulations))
        home_win = u < p_home
        away_win = u >= p_home + p_draw
        draw = ~(home_win | away_win)
        if home in index:
            additions[:, index[home]] += np.where(home_win, 3, np.where(draw, 1, 0)).astype(np.int16)
        if away in index:
            additions[:, index[away]] += np.where(away_win, 3, np.where(draw, 1, 0)).astype(np.int16)

    current = np.array([_points(base[name]) for name in teams], dtype=np.int16)
    final_points = additions + current[None, :]
    k = max(1, min(int(cutoff), len(teams)))
    cutoff_points = -np.partition(-final_points, k - 1, axis=1)[:, k - 1]

    # El desempate futuro no se inventa. Para la estimación se usa la DG/GF actual y
    # un epsilon estable; la narrativa debe mantener este resultado como ESTIMADO.
    tie = np.array([
        _stat(base[name], "dg") * 1e-4 + _stat(base[name], "gf") * 1e-6 - idx * 1e-9
        for idx, name in enumerate(teams)
    ])
    keys = final_points.astype(float) + tie[None, :]
    target_idx = index[team]
    target_rank = (keys > keys[:, target_idx:target_idx + 1]).sum(axis=1) + 1
    qualified = target_rank <= k
    target_totals = final_points[:, target_idx]

    minimum_samples = max(25, int(simulations * 0.004))
    grouped: list[dict[str, object]] = []
    running = 0.0
    for total in sorted(int(value) for value in np.unique(target_totals)):
        mask = target_totals == total
        count = int(mask.sum())
        raw_probability = float(qualified[mask].mean()) if count else 0.0
        # El ajuste monótono evita que el ruido de Monte Carlo haga bajar la chance al
        # sumar más puntos. Se conserva el valor bruto para auditoría.
        running = max(running, raw_probability)
        grouped.append({
            "final_points": total,
            "samples": count,
            "probability": running,
            "raw_probability": raw_probability,
            "stable": count >= minimum_samples,
        })

    def threshold(probability: float) -> int | None:
        stable = [
            int(row["final_points"])
            for row in grouped
            if bool(row["stable"]) and float(row["probability"]) >= probability
        ]
        return min(stable) if stable else None

    counts = Counter(int(value) for value in cutoff_points)
    mode_cutoff = max(counts, key=lambda value: (counts[value], -value)) if counts else None
    return {
        "simulations": int(simulations),
        "seed": int(seed),
        "cutoff_median": _quantile_int(cutoff_points, 0.50),
        "cutoff_low": _quantile_int(cutoff_points, 0.25),
        "cutoff_high": _quantile_int(cutoff_points, 0.75),
        "cutoff_mode": int(mode_cutoff) if mode_cutoff is not None else None,
        "cutoff_interval_label": "50% central (percentiles 25 a 75)",
        "qualification_probability": float(qualified.mean()),
        "target_points_median": _quantile_int(target_totals, 0.50),
        "target_50": threshold(0.50),
        "target_70": threshold(0.70),
        "target_85": threshold(0.85),
        "by_final_points": grouped,
        "model_parameters": {
            "draw_probability": float(draw_probability),
            "home_advantage": float(home_advantage),
            "strength_source": strength_source,
        },
        "tiebreak_note": "La estimación usa la diferencia de gol actual como desempate de referencia.",
        "model_note": (
            ("El modelo usa la fuerza canónica y el mismo kernel probabilístico que el Monte Carlo principal "
             if strength_source == "provided_canonical" else
             "El modelo usa una fuerza regularizada de compatibilidad y el kernel probabilístico canónico ")
            + f"({100 * float(draw_probability):.0f}% de empate y factor local {float(home_advantage):.2f}); "
            + "la diferencia de gol actual queda sólo como referencia para los desempates futuros."
        ),
    }


def competition_context(
    base: Mapping[str, object],
    matches: Iterable[tuple[str, str]],
    team: str,
    cutoff: int,
    *,
    strength_base: Mapping[str, object] | None = None,
    strength: Mapping[str, float] | None = None,
    simulations: int = 6000,
    seed: int = 20260804,
    contender_margin: int = 4,
) -> dict[str, object]:
    """Analiza tabla, fixture, cruces internos y proyección del corte.

    La selección de competidores no altera la simulación: sirve únicamente para
    explicar los cruces. La proyección incluye todos los partidos pendientes que
    afectan a por lo menos un club de la tabla analizada.
    """
    if team not in base:
        raise ValueError(f"{team} no pertenece a la tabla analizada")
    order = _current_order(base)
    n = len(order)
    k = max(1, min(int(cutoff), n))
    points = {name: _points(base[name]) for name in base}
    relevant_matches = tuple(
        (str(home), str(away))
        for home, away in matches
        if home in base or away in base
    )
    remaining = {name: 0 for name in base}
    for home, away in relevant_matches:
        if home in remaining:
            remaining[home] += 1
        if away in remaining:
            remaining[away] += 1
    ceilings = {name: points[name] + 3 * remaining[name] for name in base}
    current_cutoff = points[order[k - 1]]
    target_rank = order.index(team) + 1
    target_ceiling = ceilings[team]

    # Un competidor es relevante si todavía puede alcanzar el corte actual y no está
    # ya fuera del techo del equipo consultado. Se suman los puestos cercanos a la
    # frontera para no omitir un rival con pocos partidos jugados.
    near_start = max(0, k - 1 - int(contender_margin))
    near_end = min(n, k + int(contender_margin))
    near_cut = set(order[near_start:near_end])
    contenders = {
        name for name in base
        if name != team
        and ceilings[name] >= current_cutoff
        and points[name] <= target_ceiling
    }
    contenders.update(name for name in near_cut if name != team)

    direct_counter: Counter[str] = Counter()
    internal_matches: list[tuple[str, str]] = []
    for home, away in relevant_matches:
        if team in (home, away):
            rival = away if home == team else home
            if rival in contenders:
                direct_counter[rival] += 1
        elif home in contenders and away in contenders:
            internal_matches.append((home, away))

    internal_counter: Counter[str] = Counter()
    for home, away in internal_matches:
        internal_counter[home] += 1
        internal_counter[away] += 1

    visible = sorted(
        contenders,
        key=lambda name: (
            abs((order.index(name) + 1) - k),
            -points[name],
            name,
        ),
    )[:10]
    rivals = []
    for name in visible:
        direct = int(direct_counter.get(name, 0))
        rivals.append({
            "team": name,
            "rank": order.index(name) + 1,
            "points": points[name],
            "played": _stat(base[name], "pj"),
            "games_left": remaining[name],
            "ceiling": ceilings[name],
            "direct_matches": direct,
            "ceiling_if_target_wins": ceilings[name] - 3 * direct,
            "internal_matches": int(internal_counter.get(name, 0)),
        })

    projection = _simulate_fixture(
        base,
        relevant_matches,
        team,
        k,
        strength_base=strength_base,
        strength=strength,
        simulations=max(1000, int(simulations)),
        seed=int(seed),
        draw_probability=DEFAULT_DRAW_PROBABILITY,
        home_advantage=DEFAULT_HOME_ADVANTAGE,
    )
    return {
        "team": team,
        "cutoff": k,
        "current_rank": target_rank,
        "current_points": points[team],
        "current_cutoff_points": current_cutoff,
        "games_left": remaining[team],
        "ceiling": target_ceiling,
        "contender_count": len(contenders),
        "direct_match_count": sum(direct_counter.values()),
        "direct_rivals": dict(direct_counter),
        "internal_match_count": len(internal_matches),
        "internal_matches": internal_matches,
        "independent_ceiling_overcount": 3 * len(internal_matches),
        "rivals": rivals,
        "projection": projection,
    }
