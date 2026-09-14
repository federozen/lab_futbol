"""Presentacion editorial de nombres y tablas de la LPF.

Los calculos conservan los nombres canonicos completos. Este modulo solo cambia
la forma en que se muestran en pantalla para usar las denominaciones habituales
en el futbol argentino y evitar que una abreviatura altere cruces, fixtures o
comparaciones internas.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


EDITORIAL_TEAM_NAMES: dict[str, str] = {
    "Argentinos Juniors": "Argentinos",
    "Barracas Central": "Barracas",
    "Boca Juniors": "Boca",
    "Defensa y Justicia": "Defensa",
    "Deportivo Riestra": "Riestra",
    "Estudiantes de La Plata": "Estudiantes",
    "Estudiantes de Río Cuarto": "Estudiantes (RC)",
    "Gimnasia La Plata": "Gimnasia",
    "Gimnasia de Mendoza": "Gimnasia (M)",
    "Newell's Old Boys": "Newell's",
    "River Plate": "River",
    "Vélez Sarsfield": "Vélez",
}


def display_team(value: Any) -> str:
    """Devuelve el nombre editorial sin modificar la clave canonica interna."""
    text = str(value or "")
    return EDITORIAL_TEAM_NAMES.get(text, text)


def editorialize_text(value: Any) -> Any:
    """Reemplaza nombres canonicos dentro de un texto visible."""
    if not isinstance(value, str):
        return value
    text = value
    for canonical in sorted(EDITORIAL_TEAM_NAMES, key=len, reverse=True):
        text = text.replace(canonical, EDITORIAL_TEAM_NAMES[canonical])
    return text


def editorialize_frame(value: Any) -> Any:
    """Crea una copia de un DataFrame/Series con nombres editoriales visibles."""
    try:
        import pandas as pd
    except ImportError:
        return value

    if isinstance(value, pd.DataFrame):
        frame = value.copy()
        frame.columns = [editorialize_text(column) if isinstance(column, str) else column for column in frame.columns]
        if frame.index.dtype == "object":
            frame.index = [editorialize_text(item) if isinstance(item, str) else item for item in frame.index]
        for column in frame.columns:
            if frame[column].dtype == "object":
                frame[column] = frame[column].map(
                    lambda item: editorialize_text(item) if isinstance(item, str) else item
                )
        return frame

    if isinstance(value, pd.Series):
        series = value.copy()
        if series.dtype == "object":
            series = series.map(lambda item: editorialize_text(item) if isinstance(item, str) else item)
        return series

    return value


def editorialize_spec(spec: Any) -> Any:
    """Copia una especificacion de placa/tabla y editorializa sus textos."""
    if not isinstance(spec, dict):
        return spec
    out = dict(spec)
    for key in ("titulo", "corner", "footer"):
        if key in out:
            out[key] = editorialize_text(out[key])
    for key in ("col_headers", "row_headers"):
        if isinstance(out.get(key), list):
            out[key] = [editorialize_text(item) for item in out[key]]
    if isinstance(out.get("leyenda"), list):
        legend = []
        for item in out["leyenda"]:
            if isinstance(item, tuple) and len(item) == 2:
                color, label = item
                legend.append((color, editorialize_text(label)))
            else:
                legend.append(item)
        out["leyenda"] = legend
    if isinstance(out.get("cells"), list):
        new_rows = []
        for row in out["cells"]:
            new_row = []
            for cell in row:
                if isinstance(cell, tuple) and len(cell) == 2:
                    new_row.append((editorialize_text(cell[0]), cell[1]))
                else:
                    new_row.append(cell)
            new_rows.append(new_row)
        out["cells"] = new_rows
    return out


_PROBABILITY_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (183, 28, 28)),
    (25.0, (239, 108, 0)),
    (50.0, (249, 168, 37)),
    (75.0, (122, 165, 61)),
    (100.0, (27, 94, 32)),
)


def probability_scale_color(value: Any) -> str:
    """Escala continua rojo -> amarillo -> verde para probabilidades estimadas.

    El color es únicamente una ayuda visual del bloque ESTIMADO. No expresa un
    estado matemático exacto ni reemplaza el porcentaje impreso en la celda.
    """
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return "#e5e7eb"
    for index in range(len(_PROBABILITY_STOPS) - 1):
        low_x, low_rgb = _PROBABILITY_STOPS[index]
        high_x, high_rgb = _PROBABILITY_STOPS[index + 1]
        if low_x <= pct <= high_x:
            ratio = 0.0 if high_x == low_x else (pct - low_x) / (high_x - low_x)
            rgb = tuple(round(a + (b - a) * ratio) for a, b in zip(low_rgb, high_rgb))
            return "#%02x%02x%02x" % rgb
    return "#1b5e20"


def cup_probability_heatmap_spec(
    rows: Sequence[Mapping[str, Any]],
    *,
    active_objective: str,
    focus_team: str | None = None,
    simulations: int = 6000,
) -> dict[str, Any]:
    """Mapa visual de chances de Copas a partir de una tabla Monte Carlo ya calculada."""
    objective = str(active_objective or "").lower()
    fields = [
        ("Libertadores", "Libertadores %"),
        ("Sudamericana", "Sudamericana %"),
        ("Al menos una copa", "Al menos Sudamericana %"),
    ]
    if "sudamericana" in objective and "libertadores" not in objective:
        fields = [fields[2], fields[0], fields[1]]

    row_headers: list[str] = []
    cells: list[list[tuple[str, str]]] = []
    for row in rows or []:
        team = str(row.get("Equipo") or "")
        annual = str(row.get("Anual") or "—")
        prefix = "★ " if focus_team and team == focus_team else ""
        row_headers.append(f"{prefix}{team} · Anual {annual}")
        visual_row: list[tuple[str, str]] = []
        for _label, field in fields:
            try:
                pct = float(row.get(field, 0) or 0)
                text = f"{pct:.0f}%"
            except (TypeError, ValueError):
                pct = 0.0
                text = "—"
            visual_row.append((text, probability_scale_color(pct)))
        cells.append(visual_row)

    return {
        "titulo": "Mapa de probabilidades de Copas · ESTIMADO",
        "col_headers": [label for label, _field in fields],
        "row_headers": row_headers,
        "cells": cells,
        "corner": "Equipo ↓ / chance estimada →",
        "leyenda": [
            (probability_scale_color(5), "chance baja"),
            (probability_scale_color(50), "zona intermedia"),
            (probability_scale_color(95), "chance alta"),
        ],
        "footer": (
            f"ESTIMADO · {int(simulations):,} simulaciones. Rojo→amarillo→verde representa menor→mayor chance del modelo; "
            "el porcentaje escrito manda. Sudamericana = terminar específicamente en Sudamericana; "
            "Al menos una copa = Libertadores o Sudamericana. No es garantía matemática."
        ),
    }


def cup_current_slots_spec(
    annual: Mapping[str, Mapping[str, Any]],
    annual_order: Sequence[str],
    reduced_order: Sequence[str],
    *,
    libertadores_slots: int,
    sudamericana_slots: int = 6,
    focus_team: str | None = None,
    max_rows: int = 16,
) -> dict[str, Any]:
    """Foto exacta de cómo se repartirían hoy los cupos por Tabla Anual.

    No pronostica el cierre: clasifica visualmente la foto actual y distingue a
    quienes ya tienen Libertadores por otra vía de quienes ocupan cupo por Anual.
    """
    annual_order = [str(team) for team in annual_order if team in annual]
    reduced_order = [str(team) for team in reduced_order if team in annual]
    direct = set(annual_order) - set(reduced_order)
    reduced_pos = {team: index + 1 for index, team in enumerate(reduced_order)}
    annual_pos = {team: index + 1 for index, team in enumerate(annual_order)}

    visible = annual_order[: max(1, int(max_rows))]
    if focus_team in annual_pos and focus_team not in visible:
        pos = annual_pos[focus_team]
        around = annual_order[max(0, pos - 3): min(len(annual_order), pos + 2)]
        visible = list(dict.fromkeys(visible + ["…"] + around))

    row_headers: list[str] = []
    cells: list[list[tuple[str, str]]] = []
    for team in visible:
        if team == "…":
            row_headers.append("…")
            cells.append([("…", "#f8fafc")] * 4)
            continue
        data = annual.get(team) or {}
        prefix = "★ " if focus_team and team == focus_team else ""
        row_headers.append(prefix + team)
        pts = int(data.get("pts", 0) or 0)
        pj = int(data.get("pj", 0) or 0)
        pos = annual_pos.get(team)
        if team in direct:
            status, color = "LIBERTADORES · VÍA DIRECTA", "#0f766e"
        else:
            rpos = reduced_pos.get(team, 999)
            if rpos <= int(libertadores_slots):
                status, color = "LIBERTADORES · TABLA ANUAL", "#1b5e20"
            elif rpos <= int(libertadores_slots) + int(sudamericana_slots):
                status, color = "SUDAMERICANA · TABLA ANUAL", "#00838f"
            else:
                status, color = "FUERA DE COPAS HOY", "#e5e7eb"
        cells.append([
            (f"{pos}º" if pos else "—", "#eef1e8"),
            (str(pts), "#eef1e8"),
            (str(pj), "#eef1e8"),
            (status, color),
        ])

    return {
        "titulo": "Mapa de cupos si la temporada terminara hoy · EXACTO",
        "col_headers": ["Pos. Anual", "PTS", "PJ", "Cupo hoy"],
        "row_headers": row_headers,
        "cells": cells,
        "corner": "Equipo ↓ / foto actual →",
        "leyenda": [
            ("#0f766e", "Libertadores por vía directa"),
            ("#1b5e20", "Libertadores por Tabla Anual"),
            ("#00838f", "Sudamericana por Tabla Anual"),
            ("#e5e7eb", "fuera de cupos hoy"),
        ],
        "footer": (
            "EXACTO para la tabla de hoy: muestra cómo se asignarían los cupos si terminara ahora. "
            "No es una proyección del cierre ni significa que un equipo esté matemáticamente clasificado o eliminado."
        ),
    }
