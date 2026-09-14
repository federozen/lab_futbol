"""Regresiones de forma, racha y fuerza regularizada LPF."""
from __future__ import annotations

import random

import numpy as np

from lpf_form import estimate_team_strength, result_letter, team_form, team_streak


def _reference_result_letter(team, local, visitor, goals_local, goals_visitor):
    if goals_local == goals_visitor:
        return "E"
    return "G" if (local if goals_local > goals_visitor else visitor) == team else "P"


def _reference_form(team, played, n=5):
    letters = [
        _reference_result_letter(team, local, visitor, goals_local, goals_visitor)
        for (local, visitor, goals_local, goals_visitor) in played
        if team in (local, visitor)
    ]
    latest = letters[-n:]
    points = sum(3 if value == "G" else (1 if value == "E" else 0) for value in latest)
    return latest, points


def _reference_streak(team, played):
    letters = [
        _reference_result_letter(team, local, visitor, goals_local, goals_visitor)
        for (local, visitor, goals_local, goals_visitor) in played
        if team in (local, visitor)
    ]
    if not letters:
        return "sin partidos"
    last = letters[-1]
    consecutive = 0
    for value in reversed(letters):
        if value == last:
            consecutive += 1
        else:
            break
    unbeaten = 0
    for value in reversed(letters):
        if value in ("G", "E"):
            unbeaten += 1
        else:
            break
    winless = 0
    for value in reversed(letters):
        if value in ("P", "E"):
            winless += 1
        else:
            break
    if last == "G":
        return f"{consecutive} victoria{'s' if consecutive > 1 else ''} al hilo" + (f" ({unbeaten} invicto)" if unbeaten > consecutive else "")
    if last == "E":
        if unbeaten > consecutive:
            return f"{unbeaten} partidos invicto"
        if winless > consecutive:
            return f"{winless} sin ganar"
        return f"{consecutive} empate{'s' if consecutive > 1 else ''} seguido{'s' if consecutive > 1 else ''}"
    return f"{consecutive} derrota{'s' if consecutive > 1 else ''} al hilo" + (f" ({winless} sin ganar)" if winless > consecutive else "")


def _reference_strength(base, played=None, opening=None):
    teams = list(base.keys())
    opening = opening or {}
    current = {}
    for team in teams:
        pj = int(base[team].get("pj", 0))
        current[team] = (float(base[team].get("pts", 0)) / pj) if pj else 1.35
    recent = {}
    for team in teams:
        latest, points = _reference_form(team, played or [], 5)
        recent[team] = (points / len(latest)) if latest else current[team]
    prior = {}
    for team in teams:
        row = opening.get(team, {})
        pj = int(row.get("pj", 0))
        prior[team] = (float(row.get("pts", 0)) / pj) if pj else 1.35
    mixed = {}
    for team in teams:
        pj = int(base[team].get("pj", 0))
        prior_weight = 6.0
        regularized = (prior[team] * prior_weight + current[team] * pj) / (prior_weight + pj)
        form_weight = min(0.25, pj / 24.0)
        mixed[team] = (1 - form_weight) * regularized + form_weight * recent[team]
    median = float(np.median(list(mixed.values()))) if mixed else 1.0
    if median <= 0:
        median = 1.0
    return {team: min(1.75, max(0.55, mixed[team] / median)) for team in teams}


def test_resultado_forma_y_racha_basicos():
    played = [
        ("A", "B", 2, 0),
        ("C", "A", 1, 1),
        ("A", "D", 0, 1),
        ("E", "A", 0, 3),
    ]
    assert result_letter("A", "A", "B", 2, 0) == "G"
    assert team_form("A", played, 3) == (["E", "P", "G"], 4)
    assert team_streak("A", played) == "1 victoria al hilo"
    assert team_streak("Z", played) == "sin partidos"


def test_forma_y_racha_equivalen_al_codigo_3825_en_500_casos():
    rng = random.Random(3825)
    teams = ["A", "B", "C", "D", "E", "F"]
    for _ in range(500):
        played = []
        for _match in range(rng.randint(0, 30)):
            local, visitor = rng.sample(teams, 2)
            played.append((local, visitor, rng.randint(0, 5), rng.randint(0, 5)))
        team = rng.choice(teams)
        n = rng.randint(1, 8)
        assert team_form(team, played, n) == _reference_form(team, played, n)
        assert team_streak(team, played) == _reference_streak(team, played)


def test_fuerza_equivale_al_codigo_3825_en_600_casos():
    rng = random.Random(4925)
    teams = [f"T{i}" for i in range(10)]
    for _ in range(600):
        selected = teams[: rng.randint(0, len(teams))]
        base = {
            team: {"pts": rng.randint(0, 30), "pj": rng.randint(0, 12)}
            for team in selected
        }
        opening = {
            team: {"pts": rng.randint(0, 45), "pj": rng.choice([0, 14, 16])}
            for team in selected
            if rng.random() < 0.85
        }
        played = []
        if len(selected) >= 2:
            for _match in range(rng.randint(0, 40)):
                local, visitor = rng.sample(selected, 2)
                played.append((local, visitor, rng.randint(0, 5), rng.randint(0, 5)))
        expected = _reference_strength(base, played, opening)
        actual = estimate_team_strength(base, played, opening)
        assert actual == expected


def test_modulo_no_depende_de_streamlit_ni_red():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "lpf_form.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "import requests" not in source
