import json
import math
from pathlib import Path

import numpy as np

from lpf_data_2026 import LPF_FIXTURE, TABLA_ANUAL_LPF_2026
from lpf_data_quality import derive_opening_from_results
from lpf_form import estimate_team_strength
from lpf_parsers import parse_tabla_anual
from lpf_simulation import (
    DEFAULT_DRAW_PROBABILITY,
    DEFAULT_HOME_ADVANTAGE,
    match_outcome_probabilities,
    objective_mask,
    simulate_point_additions,
    simulate_zone_rank_points,
    summarize_rank_condition,
)
from lpf_competitive_context import competition_context


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lpf_2026_fecha4_probability_audit.json"


def _audit_snapshot():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _opening(snapshot):
    annual = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]
    first_round = [tuple(row) for row in snapshot["played"][:15]]
    opening, issues = derive_opening_from_results(
        annual, LPF_FIXTURE, first_round, opening_rounds=16
    )
    assert not [issue for issue in issues if issue.level == "blocked"]
    return opening


def _snapshot_inputs():
    snapshot = _audit_snapshot()
    zones = snapshot["zones"]
    played = [tuple(row) for row in snapshot["played"]]
    base_all = {team: row for base in zones.values() for team, row in base.items()}
    opening = _opening(snapshot)
    strength = estimate_team_strength(base_all, played, opening)
    played_pairs = {(home, away) for home, away, _gh, _ga in played}
    pending = [
        (game["l"], game["v"])
        for game in LPF_FIXTURE
        if (game["l"], game["v"]) not in played_pairs
    ]
    remaining = {team: 0 for team in base_all}
    for home, away in pending:
        if home in remaining:
            remaining[home] += 1
        if away in remaining:
            remaining[away] += 1
    return snapshot, zones, played, base_all, strength, pending, remaining


def _legacy_strength(base, names):
    prior_ppg = 1.35
    prior_games = 6.0
    raw = {}
    for team in names:
        row = base.get(team)
        if row is None:
            raw[team] = prior_ppg
            continue
        pj = max(0, int(row.get("pj", 0)))
        pts = int(row.get("pts", 0))
        raw[team] = (pts + prior_ppg * prior_games) / (pj + prior_games)
    known = [raw[team] for team in base if team in raw]
    centre = float(np.median(known)) if known else prior_ppg
    if centre <= 0:
        centre = prior_ppg
    return {team: min(1.75, max(0.55, raw[team] / centre)) for team in raw}


def _outcome_probabilities(strength, home, away, draw, local):
    return match_outcome_probabilities(strength[home], strength[away], draw, local)


def test_match_kernel_is_normalized_and_has_expected_sensitivity():
    base = match_outcome_probabilities(1.0, 1.0)
    stronger_home = match_outcome_probabilities(1.4, 1.0)
    more_home_advantage = match_outcome_probabilities(1.0, 1.0, home_advantage=1.35)
    more_draws = match_outcome_probabilities(1.0, 1.0, draw_probability=0.35)

    assert sum(base) == pytest.approx(1.0)
    assert base[0] > base[2]
    assert stronger_home[0] > base[0]
    assert more_home_advantage[0] > base[0]
    assert more_draws[1] > base[1]
    assert more_draws[0] + more_draws[2] < base[0] + base[2]


def test_competitive_context_uses_canonical_kernel_and_supplied_strength():
    base = {
        "A": {"pts": 5, "pj": 3, "dg": 1, "gf": 4},
        "B": {"pts": 4, "pj": 3, "dg": 0, "gf": 3},
        "C": {"pts": 3, "pj": 3, "dg": -1, "gf": 2},
    }
    context = competition_context(
        base,
        [("A", "B"), ("C", "A")],
        "A",
        2,
        strength={"A": 1.5, "B": 1.0, "C": 0.8},
        simulations=1200,
        seed=77,
    )
    params = context["projection"]["model_parameters"]
    assert params == {
        "draw_probability": DEFAULT_DRAW_PROBABILITY,
        "home_advantage": DEFAULT_HOME_ADVANTAGE,
        "strength_source": "provided_canonical",
    }
    assert "26%" in context["projection"]["model_note"]
    assert "1.22" in context["projection"]["model_note"]


def test_conditional_rank_summary_exposes_small_samples():
    positions = np.array([8] * 99 + [7] * 101)
    points = np.array([21] * 40 + [22] * 59 + [25] * 101)
    summary = summarize_rank_condition(positions, points, 8, min_samples=100)
    assert summary["samples"] == 99
    assert summary["probability"] == pytest.approx(99 / 200)
    assert summary["median"] == 22.0
    assert summary["stable"] is False
    assert sum(row["samples"] for row in summary["distribution"]) == 99


def test_real_fecha4_snapshot_has_59_completed_matches_and_expected_balance():
    snapshot = _audit_snapshot()
    played = snapshot["played"]
    home = sum(gh > ga for _h, _a, gh, ga in played)
    draws = sum(gh == ga for _h, _a, gh, ga in played)
    away = sum(gh < ga for _h, _a, gh, ga in played)
    assert (len(played), home, draws, away) == (59, 33, 9, 17)
    assert snapshot["zones"]["A"]["Boca Juniors"]["pts"] == 5
    assert snapshot["zones"]["B"]["River Plate"]["pts"] == 0


def test_real_fecha4_backtest_prefers_existing_canonical_model_over_legacy_context_model():
    snapshot, zones, played, base_all, _strength, _pending, _remaining = _snapshot_inputs()
    opening = _opening(snapshot)
    teams = list(base_all)
    current = {
        team: {"pts": 0, "pj": 0, "gf": 0, "ga": 0, "dg": 0}
        for team in teams
    }
    history = []
    logloss = {"canonical": 0.0, "legacy": 0.0}

    for home, away, goals_home, goals_away in played:
        canonical_strength = estimate_team_strength(current, history, opening)
        legacy_strength = _legacy_strength(current, teams)
        canonical = _outcome_probabilities(
            canonical_strength, home, away,
            DEFAULT_DRAW_PROBABILITY, DEFAULT_HOME_ADVANTAGE,
        )
        legacy = _outcome_probabilities(legacy_strength, home, away, 0.27, 1.08)
        outcome = 0 if goals_home > goals_away else 1 if goals_home == goals_away else 2
        logloss["canonical"] -= math.log(canonical[outcome])
        logloss["legacy"] -= math.log(legacy[outcome])

        for team, gf, ga in ((home, goals_home, goals_away), (away, goals_away, goals_home)):
            row = current[team]
            row["pj"] += 1
            row["gf"] += gf
            row["ga"] += ga
            row["dg"] = row["gf"] - row["ga"]
        if goals_home > goals_away:
            current[home]["pts"] += 3
        elif goals_home < goals_away:
            current[away]["pts"] += 3
        else:
            current[home]["pts"] += 1
            current[away]["pts"] += 1
        history.append((home, away, goals_home, goals_away))

    canonical_mean = logloss["canonical"] / len(played)
    legacy_mean = logloss["legacy"] / len(played)
    assert canonical_mean == pytest.approx(1.03687990706495)
    assert legacy_mean == pytest.approx(1.05672977525843)
    assert canonical_mean < legacy_mean


def test_real_fecha4_playoff_simulation_preserves_exactly_eight_slots_per_zone():
    _snapshot, zones, _played, base_all, strength, pending, _remaining = _snapshot_inputs()
    teams = list(base_all)
    additions, index = simulate_point_additions(teams, pending, strength, 1500, 290829)
    context = {
        "Z": zones,
        "zona_de": {team: zone for zone, base in zones.items() for team in base},
        "zpts": {team: row["pts"] for base in zones.values() for team, row in base.items()},
        "zdg": {team: row["dg"] for base in zones.values() for team, row in base.items()},
    }
    qualified = np.zeros(additions.shape[0], dtype=int)
    for team in teams:
        qualified += objective_mask("playoffs", team, additions, index, context).astype(int)
    assert np.all(qualified == 16)


def test_real_fecha4_rank_condition_marks_river_sample_as_fragile_but_boca_as_stable():
    _snapshot, zones, played, _base_all, strength, pending, remaining = _snapshot_inputs()
    results = {}
    for team, zone in (("Boca Juniors", "A"), ("River Plate", "B")):
        ranks, points = simulate_zone_rank_points(
            zones[zone], remaining, pending, team, 6000, 3833, strength
        )
        results[team] = summarize_rank_condition(ranks, points, 8, min_samples=100)

    boca = results["Boca Juniors"]
    river = results["River Plate"]
    assert boca["samples"] == 497
    assert boca["median"] == 22.0
    assert (boca["q25"], boca["q75"]) == (21.0, 23.0)
    assert boca["stable"] is True
    assert river["samples"] == 85
    assert river["stable"] is False


def test_real_fecha4_competitive_context_agrees_with_main_zone_simulator():
    _snapshot, zones, _played, base_all, strength, pending, remaining = _snapshot_inputs()
    for team, zone in (("Boca Juniors", "A"), ("River Plate", "B")):
        ranks, _points = simulate_zone_rank_points(
            zones[zone], remaining, pending, team, 6000, 3833, strength
        )
        context = competition_context(
            zones[zone], pending, team, 8,
            strength_base=base_all, strength=strength, simulations=6000, seed=3833,
        )
        main_probability = float((ranks <= 8).mean())
        context_probability = float(context["projection"]["qualification_probability"])
        # Los dos caminos comparten fuerza, fixture y kernel. Sólo puede quedar una
        # diferencia mínima por el tratamiento editorial del desempate futuro.
        assert abs(main_probability - context_probability) < 0.005


# pytest se importa al final para mantener arriba sólo dependencias del motor.
import pytest
