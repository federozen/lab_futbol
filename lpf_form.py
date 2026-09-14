"""Forma reciente y fuerza regularizada para simulaciones LPF.

El módulo no conoce Streamlit ni fuentes externas. Recibe la tabla vigente,
resultados confirmados y la foto fija del Apertura por parámetro.
"""
from __future__ import annotations

import numpy as np

LPF_RUNTIME_API = 21


def result_letter(team, local, visitor, goals_local, goals_visitor):
    """Devuelve G/E/P para ``team`` en un resultado confirmado."""
    if goals_local == goals_visitor:
        return "E"
    return "G" if (local if goals_local > goals_visitor else visitor) == team else "P"


def team_form(team, played, n=5):
    """Últimos ``n`` resultados y puntos obtenidos en esa ventana."""
    letters = [
        result_letter(team, local, visitor, goals_local, goals_visitor)
        for (local, visitor, goals_local, goals_visitor) in played
        if team in (local, visitor)
    ]
    latest = letters[-n:]
    points = sum(3 if value == "G" else (1 if value == "E" else 0) for value in latest)
    return latest, points


def team_streak(team, played):
    """Descripción editorial breve de la racha reciente."""
    letters = [
        result_letter(team, local, visitor, goals_local, goals_visitor)
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
        return (
            f"{consecutive} victoria{'s' if consecutive > 1 else ''} al hilo"
            + (f" ({unbeaten} invicto)" if unbeaten > consecutive else "")
        )
    if last == "E":
        if unbeaten > consecutive:
            return f"{unbeaten} partidos invicto"
        if winless > consecutive:
            return f"{winless} sin ganar"
        return f"{consecutive} empate{'s' if consecutive > 1 else ''} seguido{'s' if consecutive > 1 else ''}"
    return (
        f"{consecutive} derrota{'s' if consecutive > 1 else ''} al hilo"
        + (f" ({winless} sin ganar)" if winless > consecutive else "")
    )


def estimate_team_strength(base, played=None, opening=None):
    """Fuerza regularizada usada por las simulaciones LPF.

    Conserva el modelo histórico: seis partidos equivalentes de antecedente del
    Apertura, peso creciente del Clausura actual y hasta 25% de forma reciente.
    La salida se normaliza por la mediana y queda limitada a [0.55, 1.75].
    """
    teams = list(base.keys())
    opening = opening or {}
    current = {}
    for team in teams:
        pj = int(base[team].get("pj", 0))
        current[team] = (float(base[team].get("pts", 0)) / pj) if pj else 1.35
    recent = {}
    for team in teams:
        latest, points = team_form(team, played or [], 5)
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
