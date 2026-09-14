"""Aplicación pura de resultados y cambios de posiciones.

Recibe estructuras ya normalizadas, actualiza una copia de las zonas y devuelve
los marcadores efectivamente aplicados. No conoce Streamlit, red ni persistencia.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from lpf_standings import liga_tabla_df

LPF_RUNTIME_API = 21


def _update_stats(stats: dict[str, Any], gf: int, ga: int) -> None:
    """Aplica un partido terminado sobre una fila estadística mutable."""
    stats["pj"] = int(stats.get("pj", 0)) + 1
    stats["gf"] = int(stats.get("gf", 0)) + int(gf)
    stats["ga"] = int(stats.get("ga", 0)) + int(ga)
    stats["dg"] = stats["gf"] - stats["ga"]
    stats["pts"] = int(stats.get("pts", 0)) + (3 if gf > ga else 1 if gf == ga else 0)


def apply_completed_results(
    zones: Mapping[str, Mapping[str, Mapping[str, Any]]],
    played: Sequence[tuple[str, str, int, int]] | None,
    pending: Sequence[tuple[str, str]] | None,
    results: Sequence[tuple[str, str, int, int]],
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[tuple[str, str, int, int]], list[tuple[str, str, int, int]]]:
    """Aplica sólo resultados pendientes y no duplicados sobre una copia de zonas.

    Devuelve ``(zonas_actualizadas, jugados_actualizados, aplicados)``. El orden y
    la política de aceptación reproducen la carga manual histórica de la app.
    """
    updated_zones = copy.deepcopy(zones or {})
    updated_played = list(played or [])
    pending_pairs = set(pending or [])
    known = {(local, visitor) for local, visitor, _gl, _gv in updated_played}
    applied: list[tuple[str, str, int, int]] = []

    for local, visitor, gl, gv in results:
        if (local, visitor) not in pending_pairs or (local, visitor) in known:
            continue
        for team, gf, ga in ((local, gl, gv), (visitor, gv, gl)):
            for base in updated_zones.values():
                if team in base:
                    _update_stats(base[team], gf, ga)
                    break
        record = (local, visitor, int(gl), int(gv))
        updated_played.append(record)
        known.add((local, visitor))
        applied.append(record)

    return updated_zones, updated_played, applied


def table_position_changes(
    before_zones: Mapping[str, Mapping[str, Mapping[str, Any]]],
    before_annual: Mapping[str, Mapping[str, Any]] | None,
    after_zones: Mapping[str, Mapping[str, Mapping[str, Any]]],
    after_annual: Mapping[str, Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Devuelve las filas de equipos cuyo puesto cambió en zonas o Tabla Anual."""
    changes: list[dict[str, Any]] = []

    for label, before_base in (before_zones or {}).items():
        after_base = (after_zones or {}).get(label) or {}
        old_df = liga_tabla_df(before_base)
        old = {row["Equipo"]: int(row["Pos"]) for _, row in old_df.iterrows()}
        new_df = liga_tabla_df(after_base)
        for _, row in new_df.iterrows():
            team = row["Equipo"]
            position = int(row["Pos"])
            if old.get(team) != position:
                changes.append({
                    "Tabla": f"Zona {label}",
                    "Equipo": team,
                    "Antes": old.get(team),
                    "Ahora": position,
                    "Cambio": int(old.get(team, position)) - position,
                })

    if before_annual and after_annual:
        old_df = liga_tabla_df(before_annual)
        old = {row["Equipo"]: int(row["Pos"]) for _, row in old_df.iterrows()}
        for _, row in liga_tabla_df(after_annual).iterrows():
            team = row["Equipo"]
            position = int(row["Pos"])
            if old.get(team) != position:
                changes.append({
                    "Tabla": "Anual",
                    "Equipo": team,
                    "Antes": old.get(team),
                    "Ahora": position,
                    "Cambio": int(old.get(team, position)) - position,
                })

    return changes
