"""Agenda real y alcance temporal de partidos LPF.

Este módulo concentra reglas puras de calendario que usa la Previa: normaliza
fechas/horas de distintas fuentes, resuelve la jornada operativa frente a
postergados y ordena partidos por programación real con el fixture oficial como
respaldo. No conoce Streamlit ni hace red.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence

from lpf_clubs import canon_club

LPF_RUNTIME_API = 21


def parse_datetime(value):
    """Convierte una fecha ISO de la fuente a hora oficial argentina."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = _dt.datetime.fromisoformat(raw)
    except Exception:
        try:
            parsed = _dt.datetime.strptime(raw[:10], "%Y-%m-%d")
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    argentina = _dt.timezone(_dt.timedelta(hours=-3))
    return parsed.astimezone(argentina)


def build_schedule_map(
    primary_schedule: Mapping | None = None,
    secondary_schedule: Mapping | None = None,
    legacy_day_schedule: Mapping | None = None,
):
    """Combina agendas por partido y devuelve datetimes en hora argentina.

    ``secondary_schedule`` pisa valores del primario, reproduciendo la prioridad
    histórica de la app. ``legacy_day_schedule`` sólo completa partidos que aún no
    tienen fecha/hora y usa las 15:00 como horario de compatibilidad.
    """
    out = {}
    for source in (primary_schedule or {}, secondary_schedule or {}):
        for raw_key, raw_value in source.items():
            if isinstance(raw_key, str) and "|||" in raw_key:
                left, right = raw_key.split("|||", 1)
                key = (canon_club(left), canon_club(right))
            elif isinstance(raw_key, (tuple, list)) and len(raw_key) == 2:
                key = (canon_club(raw_key[0]), canon_club(raw_key[1]))
            else:
                continue
            parsed = parse_datetime(raw_value)
            if parsed:
                out[key] = parsed

    for raw_key, raw_value in (legacy_day_schedule or {}).items():
        if not isinstance(raw_key, (tuple, list)) or len(raw_key) != 2:
            continue
        key = (canon_club(raw_key[0]), canon_club(raw_key[1]))
        if key not in out:
            parsed = parse_datetime(str(raw_value)[:10] + "T15:00:00-03:00")
            if parsed:
                out[key] = parsed
    return out


def pending_round_map(pending, games: Sequence[Mapping]):
    """Devuelve ``{partido: fecha oficial}`` para los pendientes conocidos."""
    fmap = {(g["l"], g["v"]): g["f"] for g in games}
    return {(l, v): fmap.get((l, v)) for (l, v) in pending}


def current_round(pending, games: Sequence[Mapping], umbral=0.5, forzar=None):
    """Distingue jornada operativa y partidos postergados.

    Una fecha con menos de ``umbral`` de sus partidos pendientes se considera casi
    completada; sus pendientes pasan a ser postergados y la jornada operativa avanza.
    """
    fmap = {(g["l"], g["v"]): g["f"] for g in games}
    total_por_fecha = {}
    for g in games:
        total_por_fecha[g["f"]] = total_por_fecha.get(g["f"], 0) + 1
    con = [((l, v), fmap[(l, v)]) for (l, v) in pending if (l, v) in fmap]
    if not con:
        return None, [], []
    pend_por_fecha = {}
    for lv, fecha in con:
        pend_por_fecha.setdefault(fecha, []).append(lv)
    fechas = sorted(pend_por_fecha)
    if forzar is not None and forzar in pend_por_fecha:
        jornada = forzar
    else:
        jornada = fechas[-1]
        for fecha in fechas:
            total = total_por_fecha.get(fecha, 0)
            if total and len(pend_por_fecha[fecha]) >= umbral * total:
                jornada = fecha
                break
    juegos = pend_por_fecha.get(jornada, [])
    atrasados = [(lv, fecha) for lv, fecha in con if fecha < jornada]
    return jornada, juegos, atrasados


def round_label(jornada, atrasados):
    """Texto para titular la jornada, aclarando postergados anteriores."""
    if jornada is None:
        return "sin partidos pendientes"
    if not atrasados:
        return f"Fecha {jornada}"
    fechas = sorted({fecha for _, fecha in atrasados})
    cantidad = len(atrasados)
    detalle = ", ".join(str(fecha) for fecha in fechas)
    return (
        f"Fecha {jornada} (más {cantidad} partido{'s' if cantidad != 1 else ''} postergado"
        f"{'s' if cantidad != 1 else ''} de la fecha {detalle})"
    )


def match_round(match, games: Sequence[Mapping]):
    """Fecha oficial de un partido según el fixture."""
    fmap = {(g["l"], g["v"]): g.get("f") for g in games}
    return fmap.get(tuple(match))


def format_datetime(value):
    """Formatea una fecha/hora en español para la interfaz."""
    dt = value if hasattr(value, "strftime") else parse_datetime(value)
    if not dt:
        return ""
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    months = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    return f"{weekdays[dt.weekday()]} {dt.day} de {months[dt.month - 1]} a las {dt:%H.%M}"


def ordered_team_matches(equipo, pending, games: Sequence[Mapping], schedule: Mapping):
    """Pendientes del equipo ordenados por agenda real y luego fecha oficial."""
    rows = []
    for raw_match in pending or []:
        match = tuple(raw_match)
        if equipo not in match:
            continue
        scheduled = schedule.get(match)
        round_no = match_round(match, games)
        key = (0, scheduled) if scheduled else (1, round_no if round_no is not None else 999)
        rows.append({"match": match, "round": round_no, "scheduled_at": scheduled, "sort_key": key})
    rows.sort(key=lambda row: (row["sort_key"], row["match"][0], row["match"][1]))
    return rows


def next_team_match(equipo, pending, games: Sequence[Mapping], schedule: Mapping):
    ordered = ordered_team_matches(equipo, pending, games, schedule)
    return ordered[0] if ordered else None


def resolve_scope_games(
    equipo,
    pending,
    games: Sequence[Mapping],
    schedule: Mapping,
    *,
    scope="next_team_match",
    fecha=None,
):
    """Resuelve la ventana de análisis sin confundir fecha oficial y calendario real."""
    prox, official, postponed = current_round(pending, games, forzar=fecha)
    ordered_all = []
    for raw_match in pending or []:
        match = tuple(raw_match)
        scheduled = schedule.get(match)
        round_no = match_round(match, games)
        key = (0, scheduled) if scheduled else (1, round_no if round_no is not None else 999)
        ordered_all.append({"match": match, "round": round_no, "scheduled_at": scheduled, "sort_key": key})
    ordered_all.sort(key=lambda row: (row["sort_key"], row["match"][0], row["match"][1]))
    own = next_team_match(equipo, pending, games, schedule)

    if scope == "next_team_match":
        selected = [own["match"]] if own else []
        label = "próximo partido real"
    elif scope == "next_team_day":
        if own and own.get("scheduled_at"):
            day = own["scheduled_at"].date()
            selected = [
                row["match"]
                for row in ordered_all
                if row.get("scheduled_at") and row["scheduled_at"].date() == day
            ]
            label = f"partidos del {format_datetime(own['scheduled_at']).split(' a las ')[0]}"
        elif own:
            selected = list(official) + [match for match, _round in postponed]
            label = round_label(prox, postponed) if prox is not None else "próxima ventana"
        else:
            selected = []
            label = "próximo día de competencia"
    elif scope == "postponed_only":
        selected = [match for match, _round in postponed]
        label = f"postergados anteriores a la Fecha {prox}" if prox is not None else "postergados"
    elif scope == "extended_window":
        selected = list(official) + [match for match, _round in postponed]
        label = round_label(prox, postponed)
    else:
        selected = list(official)
        label = f"Fecha {prox} oficial" if prox is not None else "fecha oficial"

    own_match = next((match for match in selected if equipo in match), None)
    if scope in ("next_team_match", "next_team_day") and own:
        own_match = own["match"]
    return {
        "round": prox,
        "games": selected,
        "label": label,
        "own_match": own_match,
        "own_meta": own,
        "postponed": postponed,
    }
