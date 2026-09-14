"""Contrato canónico para antecedentes y totales de promedios LPF.

La aplicación conserva dos conceptos distintos que históricamente se mezclaban:

- ``previous_averages``: puntos y PJ de temporadas anteriores, sin 2026;
- ``average_totals``: puntos y PJ acumulados incluyendo la Tabla Anual 2026 viva.

Este módulo normaliza ambos formatos sin Streamlit ni red. Los consumidores que
calculan descenso deben usar ``average_totals``; la sesión y los snapshots guardan
``previous_averages`` para poder recomponer los totales con la foto actual.
"""
from __future__ import annotations

from collections.abc import Mapping

from lpf_clubs import canon_club

LPF_RUNTIME_API = 21


def _pair(raw: object) -> tuple[int, int] | None:
    """Lee un par ``(puntos, PJ)`` desde formatos legacy o JSON-safe."""
    if isinstance(raw, Mapping):
        pts = raw.get("points", raw.get("pts"))
        pj = raw.get("played", raw.get("pj"))
        if pts is None or pj is None:
            return None
    elif isinstance(raw, (tuple, list)) and len(raw) >= 2:
        pts, pj = raw[0], raw[1]
    else:
        return None
    try:
        return int(pts), int(pj)
    except (TypeError, ValueError):
        return None


def normalize_previous_averages(
    previous: Mapping[str, object] | None,
) -> dict[str, tuple[int, int]]:
    """Normaliza antecedentes a ``{equipo: (puntos_previos, pj_previos)}``.

    Canonicaliza nombres de clubes para que una carga manual (por ejemplo
    ``"River"``) se aplique al mismo equipo que la Tabla Anual (``"River Plate"``).
    No agrega la temporada actual.
    """
    out: dict[str, tuple[int, int]] = {}
    for team, raw in (previous or {}).items():
        pair = _pair(raw)
        if pair is None:
            continue
        out[canon_club(str(team))] = pair
    return out


def previous_averages_json(
    previous: Mapping[str, object] | None,
) -> dict[str, dict[str, int]]:
    """Versión JSON-safe del histórico, siempre con claves ``points/played``."""
    return {
        team: {"points": pts, "played": pj}
        for team, (pts, pj) in normalize_previous_averages(previous).items()
    }


def combine_average_totals(
    annual: Mapping[str, object],
    previous: Mapping[str, object] | None,
    *,
    zones: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, tuple[int, int]] | None:
    """Combina Tabla Anual 2026 + temporadas previas.

    La Tabla Anual es la fuente autoritativa de **puntos y PJ de 2026**. ``zones``
    queda sólo como respaldo de PJ para fotos legacy que no tengan ``pj`` en la
    Anual; nunca reemplaza un ``pj`` anual presente. Esto evita mezclar puntos de
    Apertura+Clausura con un denominador que cuente únicamente el Clausura.
    """
    if not previous or not annual:
        return None

    prev = normalize_previous_averages(previous)
    zone_played = {
        canon_club(str(team)): int((row or {}).get("pj", 0))
        for base in (zones or {}).values()
        for team, row in base.items()
        if isinstance(row, Mapping)
    }

    totals: dict[str, tuple[int, int]] = {}
    for team, raw in annual.items():
        row = raw if isinstance(raw, Mapping) else {}
        canonical = canon_club(str(team))
        current_points = int(row.get("pts", 0))
        if "pj" in row:
            current_played = int(row.get("pj", 0))
        else:
            current_played = int(zone_played.get(canonical, 0))
        previous_points, previous_played = prev.get(canonical, (0, 0))
        totals[str(team)] = (
            current_points + previous_points,
            current_played + previous_played,
        )
    return totals
