"""Parsers puros para tablas HTML de ligas/copa cargadas por URL.

Este modulo no hace red ni conoce Streamlit. Recibe HTML ya descargado y conserva
el comportamiento historico de ``tabla_desde_url`` y ``partidos_desde_url`` del
archivo principal.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21

import io
import re

import pandas as pd

from lpf_text import _zlow

_SCORE_RE = re.compile(r"(\d+)\s*[–—:\-]\s*(\d+)")


def parse_cross_table_html(html: str):
    """Interpreta una matriz equipo x equipo como jugados y pendientes.

    Devuelve ``(jugados, pendientes, error, nota)`` con el mismo contrato textual
    que la funcion historica usada por la UI avanzada.
    """
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception as exc:
        return [], [], f"No encontré tablas legibles ({exc}).", ""

    played, pending = [], []
    double_round = False
    found = 0
    for table in tables:
        n = len(table)
        if n < 4 or len(table.columns) != n + 1:
            continue
        names, valid = [], True
        for _, row in table.iterrows():
            name = str(row.iloc[0]).strip()
            name = re.sub(r"\s*\[[^\]]*\]", "", name)
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
            if not name or name.lower() == "nan" or _SCORE_RE.search(name):
                valid = False
                break
            names.append(name)
        if not valid or len(set(names)) != n:
            continue

        found += 1
        matrix = {}
        for i in range(n):
            for j in range(1, n + 1):
                if j - 1 == i:
                    continue
                home, away = names[i], names[j - 1]
                match = _SCORE_RE.search(str(table.iat[i, j]))
                matrix[(home, away)] = (
                    (int(match.group(1)), int(match.group(2))) if match else None
                )

        if any(
            value is not None and matrix.get((away, home)) is not None
            for (home, away), value in matrix.items()
        ):
            double_round = True

        for (home, away), value in matrix.items():
            if value is not None:
                played.append((home, away, value[0], value[1]))

        seen = set()
        for (home, away), value in matrix.items():
            if value is not None:
                continue
            if double_round:
                pending.append((home, away))
            else:
                key = frozenset((home, away))
                if key in seen:
                    continue
                seen.add(key)
                if matrix.get((away, home)) is None:
                    pending.append((home, away))

    if not found:
        return [], [], (
            "No encontré la tabla cruzada (matriz equipo × equipo) en esa página. "
            "Probá con la página de Wikipedia del torneo, o pegá el fixture a mano."
        ), ""

    note = (
        "torneo ida y vuelta"
        if double_round
        else "una sola rueda (si en realidad es ida y vuelta recién arrancado, revisá los «Restan»)"
    )
    return played, pending, None, note


def _columns(table: pd.DataFrame) -> list[str]:
    if isinstance(table.columns, pd.MultiIndex):
        return [_zlow(str(column[-1])) for column in table.columns]
    return [_zlow(str(column)) for column in table.columns]


def _find_column(columns: list[str], names: set[str]) -> int | None:
    for index, column in enumerate(columns):
        if column in names:
            return index
    return None


def _extract_standings_lines(table: pd.DataFrame) -> list[str]:
    columns = _columns(table)
    points_index = _find_column(columns, {"pts", "pts.", "puntos"})
    played_index = _find_column(columns, {"pj", "j", "jug", "jj", "part", "pj."})
    gd_index = _find_column(columns, {"dg", "dif", "dif.", "+/-", "dif. de gol", "dg.", "dif de gol"})
    team_index = _find_column(columns, {"equipo", "club", "team", "equipos"})
    if team_index is None:
        for index in range(len(columns)):
            if table.dtypes.iloc[index] == object:
                team_index = index
                break
    if points_index is None or team_index is None:
        return []

    out = []
    for _, row in table.iterrows():
        raw = str(row.iloc[team_index]).strip()
        name = re.sub(r"\s*\[[^\]]*\]", "", raw)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        if not name or name.lower() in ("nan", "equipo", "club", "equipos"):
            continue

        def number(index: int | None):
            if index is None:
                return None
            match = re.search(r"[+-]?\d+", str(row.iloc[index]))
            return int(match.group()) if match else None

        points = number(points_index)
        if points is None:
            continue
        played = number(played_index) or 0
        goal_difference = number(gd_index) or 0
        out.append(f"{name}, {points}, {played}, {goal_difference:+d}")
    return out


def parse_standings_table_html(html: str):
    """Convierte una tabla HTML de posiciones al texto pegable de la app."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception as exc:
        return "", f"No encontré tablas legibles en esa página ({exc})."

    best: list[str] = []
    for table in tables:
        try:
            lines = _extract_standings_lines(table)
        except Exception:
            lines = []
        if len(lines) > len(best):
            best = lines

    if len(best) < 4:
        return "", (
            "Leí la página pero no encontré una tabla de posiciones con filas cargadas. "
            "En algunos torneos (como la Liga Argentina por zonas) Wikipedia no trae esas tablas en el HTML: "
            "usá la tabla acumulada o de promedios, o pegá la tabla a mano."
        )
    return "\n".join(best), None
