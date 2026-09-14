"""Adaptadores puros de respuestas externas al dominio LPF.

Reciben HTML/JSON ya descargado y devuelven estructuras Python simples. No hacen
red, no usan Streamlit y no persisten estado. Esta es la frontera que puede sumar
un adaptador Opta en el futuro sin modificar ``lpf_loading`` ni los motores.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from collections.abc import Mapping, Sequence
from io import StringIO
from typing import Any
import re
import unicodedata

import pandas as pd

from lpf_clubs import LPF_CLUBES, canon_base, canon_club
from lpf_reconcile import _known_lpf_zone_rosters, _validate_base_rows, _validate_lpf_tables
from lpf_text import _zlow


_FUTBOLARGENTINO_ALIASES = {
    "a tucuman": "Atletico Tucuman",
    "argentinos j": "Argentinos Juniors",
    "c cordoba": "Central Cordoba",
    "defensa": "Defensa y Justicia",
    "estudiantes ba": "Estudiantes de Rio Cuarto",
    "estudiantes rc": "Estudiantes de Rio Cuarto",
    "ind rivadavia": "Independiente Rivadavia",
    "rosario": "Rosario Central",
}


def norm_table_label(value: object) -> str:
    text = str(value or "").strip().lower()
    try:
        text = "".join(
            ch for ch in unicodedata.normalize("NFD", text)
            if unicodedata.category(ch) != "Mn"
        )
    except Exception:
        pass
    text = re.sub(r"[^a-z0-9+/-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _table_int(value: object, default: int | None = None) -> int | None:
    if value is None:
        return default
    text = str(value).strip().replace("−", "-")
    match = re.search(r"[+-]?\d+", text)
    if not match:
        return default
    try:
        return int(match.group())
    except Exception:
        return default


def _flatten_table_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    cols = []
    for col in out.columns:
        if isinstance(col, tuple):
            pieces = [str(x) for x in col if str(x).lower() != "nan"]
            cols.append(" ".join(pieces).strip())
        else:
            cols.append(str(col).strip())
    out.columns = cols
    return out


def _find_table_column(columns: Sequence[object], aliases: set[str]) -> object | None:
    normalized = {col: norm_table_label(col) for col in columns}
    for col, norm in normalized.items():
        if norm in aliases:
            return col
    for col, norm in normalized.items():
        if any(
            alias and (
                norm.startswith(alias + " ")
                or norm.endswith(" " + alias)
                or (" " + alias + " ") in (" " + norm + " ")
            )
            for alias in aliases
        ):
            return col
    return None


def _source_team_name(raw_team: object, source_name: str = "") -> str:
    clean = re.sub(r"^\s*\d+[.)-]?\s*", "", str(raw_team or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""

    if source_name == "FutbolArgentino.com":
        normalized = norm_table_label(clean)
        alias = _FUTBOLARGENTINO_ALIASES.get(normalized)
        if alias:
            return canon_club(alias)

        direct = canon_club(clean)
        if direct in LPF_CLUBES:
            return direct

        compact = re.sub(r"[^a-z0-9]+", "", normalized)
        scores: dict[str, int] = {}
        source_aliases = {
            "Atlético Tucumán": ["a tucuman"],
            "Argentinos Juniors": ["argentinos j"],
            "Central Córdoba": ["central cordoba se", "c cordoba"],
            "Estudiantes de Río Cuarto": ["estudiantes rio cuarto", "estudiantes rc"],
            "Gimnasia de Mendoza": ["gimnasia mendoza", "gimnasia m"],
            "Independiente Rivadavia": ["ind rivadavia"],
            "Talleres": ["talleres de cordoba"],
            "Unión": ["union de santa fe"],
        }
        for canonical, aliases in LPF_CLUBES.items():
            variants = [canonical, *aliases, *source_aliases.get(canonical, [])]
            best = 0
            for variant in variants:
                token = re.sub(r"[^a-z0-9]+", "", norm_table_label(variant))
                if len(token) >= 4 and token in compact:
                    best = max(best, len(token))
            if best:
                scores[canonical] = best

        if scores:
            ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            best_team, best_score = ordered[0]
            second_score = ordered[1][1] if len(ordered) > 1 else -1
            if best_score > second_score:
                return best_team

    return canon_club(clean)


def parse_standings_table(df: pd.DataFrame, source_name: str = "") -> dict[str, dict[str, int]]:
    """Convierte una tabla HTML de posiciones a la estructura interna."""
    if df is None or getattr(df, "empty", True):
        return {}
    table = _flatten_table_columns(df)
    columns = list(table.columns)

    team_col = _find_table_column(
        columns, {"equipo", "equipos", "club", "team", "nombre", "institucion"}
    )
    pts_col = _find_table_column(columns, {"pts", "pt", "puntos", "punto", "points"})
    pj_col = _find_table_column(
        columns, {"pj", "j", "jug", "jugados", "partidos", "partidos jugados", "played"}
    )
    pos_col = _find_table_column(columns, {"pos", "posicion", "puesto", "rank", "#"})
    dg_col = _find_table_column(
        columns, {"dg", "dif", "diff", "diferencia", "diferencia de gol", "+/-"}
    )
    gf_col = _find_table_column(columns, {"gf", "g f", "favor", "goles a favor"})
    ga_col = _find_table_column(columns, {"gc", "ga", "g c", "contra", "goles en contra"})

    if team_col is None:
        best = None
        best_score = -1
        for col in columns:
            values = [str(v).strip() for v in table[col].tolist()]
            text_values = [v for v in values if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", v)]
            score = len(set(text_values))
            if score > best_score:
                best, best_score = col, score
        team_col = best

    if not team_col or not pts_col or not pj_col:
        return {}

    base: dict[str, dict[str, int]] = {}
    for _, row in table.iterrows():
        raw_team = str(row.get(team_col, "") or "").strip()
        if not raw_team or norm_table_label(raw_team) in {"equipo", "club", "team", "nan", "total"}:
            continue
        pts = _table_int(row.get(pts_col))
        pj = _table_int(row.get(pj_col))
        if pts is None or pj is None:
            continue
        team = _source_team_name(raw_team, source_name=source_name)
        if not team:
            continue
        gf = _table_int(row.get(gf_col), 0) if gf_col else 0
        ga = _table_int(row.get(ga_col), 0) if ga_col else 0
        dg = _table_int(row.get(dg_col), None) if dg_col else None
        if dg is None:
            dg = int(gf or 0) - int(ga or 0)
        published_pos = _table_int(row.get(pos_col), None) if pos_col else None
        if published_pos is None or published_pos <= 0:
            published_pos = len(base) + 1
        base[team] = {
            "pts": int(pts),
            "pj": int(pj),
            "dg": int(dg or 0),
            "gf": int(gf or 0),
            "ga": int(ga or 0),
            "source_pos": int(published_pos),
        }
    return canon_base(base)


def html_standings_tables(html: str, source_name: str = "") -> list[dict[str, dict[str, int]]]:
    try:
        tables = pd.read_html(StringIO(html))
    except Exception as exc:
        raise RuntimeError(f"no pude leer tablas HTML ({exc})") from exc
    parsed = []
    for table in tables:
        try:
            base = parse_standings_table(table, source_name=source_name)
        except Exception:
            base = {}
        if len(base) >= 10:
            parsed.append(base)
    if not parsed:
        raise RuntimeError("la página respondió, pero no encontré una tabla de posiciones legible")
    return parsed


def assign_two_zone_tables(candidates: Sequence[Mapping[str, Mapping[str, object]]]) -> dict[str, dict]:
    if len(candidates) < 2:
        return {}
    known = _known_lpf_zone_rosters()
    best = None
    for i, first in enumerate(candidates):
        for j, second in enumerate(candidates):
            if i == j:
                continue
            score = (
                len(set(first) & known["A"])
                + len(set(second) & known["B"])
                - len(set(first) & known["B"])
                - len(set(second) & known["A"])
            )
            if best is None or score > best[0]:
                best = (score, first, second)
    if not best:
        return {}
    return {"A": canon_base(best[1]), "B": canon_base(best[2])}


def parse_futbolargentino_zones_html(html: str) -> dict[str, dict]:
    parsed = [
        base for base in html_standings_tables(html, "FutbolArgentino.com")
        if 13 <= len(base) <= 17
    ]
    zones = assign_two_zone_tables(parsed)
    _validate_lpf_tables(zones)
    return zones


def parse_futbolargentino_annual_html(html: str) -> dict[str, dict[str, int]]:
    parsed = html_standings_tables(html, "FutbolArgentino.com")
    candidates = [base for base in parsed if len(base) >= 28]
    if not candidates:
        sizes = ", ".join(str(len(base)) for base in parsed)
        raise RuntimeError(
            "no encontré una Tabla Anual de 30 equipos "
            f"(tamaños detectados: {sizes or 'ninguno'})"
        )
    annual = max(candidates, key=len)
    _validate_base_rows(annual, expected_size=30, label="Tabla anual", max_pj=32)
    return canon_base(annual)


def _espn_stats(entry: Mapping[str, Any]) -> dict[str, int]:
    values: dict[str, int] = {}
    for stat in entry.get("stats", []) or []:
        try:
            values[str(stat.get("name"))] = int(float(stat.get("value", 0) or 0))
        except Exception:
            pass
    return values


def parse_espn_table_payload(data: Mapping[str, Any], league: str = "") -> tuple[dict, str, str | None]:
    """Adapta el payload de standings general de ESPN."""
    base: dict[str, dict[str, int]] = {}
    notes: dict[str, list[int]] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            standings = node.get("standings")
            if isinstance(standings, dict) and isinstance(standings.get("entries"), list):
                for source_pos, entry in enumerate(standings["entries"], 1):
                    name = (entry.get("team") or {}).get("displayName")
                    if not name:
                        continue
                    stats = _espn_stats(entry)
                    base[name] = {
                        "pts": stats.get("points", 0),
                        "pj": stats.get("gamesPlayed", 0),
                        "dg": stats.get("pointDifferential", 0),
                        "gf": stats.get("pointsFor", 0),
                        "ga": stats.get("pointsAgainst", 0),
                        "source_pos": source_pos,
                    }
                    note = (entry.get("note") or {}).get("description")
                    rank = stats.get("rank", 0)
                    if note and rank:
                        notes.setdefault(note, []).append(rank)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if not base:
        return {}, "", f"ESPN no devolvió tabla para «{league}». Revisá el código de liga."

    translations = {
        "relegation": "Descenso",
        "relegation playoff": "Promoción",
        "champions league": "Libertadores/Champions",
        "europa league": "Sudamericana/Europa",
        "conference league": "Conference",
        "conference league playoff round": "Playoff Conference",
        "promotion": "Ascenso",
        "playoffs": "Playoffs",
        "championship round": "Ronda campeonato",
    }

    def translate(name: str) -> str:
        return translations.get(_zlow(name).strip(), name)

    zones_text = "\n".join(
        f"{max(ranks)} {translate(name)}"
        for name, ranks in sorted(notes.items(), key=lambda item: max(item[1]))
    )
    return base, zones_text, None


def parse_espn_lpf_zones_payload(data: Mapping[str, Any], league: str = "arg.1") -> tuple[dict, str | None]:
    """Adapta los standings por grupos de ESPN a ``{'A': ..., 'B': ...}``."""
    groups: list[tuple[str, dict]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            standings = node.get("standings")
            if isinstance(standings, dict) and isinstance(standings.get("entries"), list) and standings["entries"]:
                base = {}
                for source_pos, entry in enumerate(standings["entries"], 1):
                    name = (entry.get("team") or {}).get("displayName")
                    if not name:
                        continue
                    stats = _espn_stats(entry)
                    base[name] = {
                        "pts": stats.get("points", 0),
                        "pj": stats.get("gamesPlayed", 0),
                        "dg": stats.get("pointDifferential", 0),
                        "gf": stats.get("pointsFor", 0),
                        "ga": stats.get("pointsAgainst", 0),
                        "source_pos": source_pos,
                    }
                if base:
                    groups.append((str(node.get("name") or node.get("abbreviation") or ""), base))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if not groups:
        return {}, f"ESPN no devolvió tabla para «{league}»."
    if len(groups) == 1:
        return {}, (
            "ESPN devolvió una sola tabla (sin las zonas A y B separadas). "
            "Pegá las dos tablas en el panel para el modo LPF."
        )

    zones: dict[str, dict] = {}
    for name, base in groups[:2]:
        match = re.search(r"\b([AB])\b", name.upper())
        label = match.group(1) if match else ("A" if "A" not in zones else "B")
        while label in zones:
            label = "B" if label == "A" else "A"
        zones[label] = canon_base(base)
    return zones, None


def _espn_round_number(event: Mapping[str, Any], competition: Mapping[str, Any]) -> int | None:
    candidates = [
        (competition.get("week") or {}).get("number")
        if isinstance(competition.get("week"), dict)
        else competition.get("week"),
        (event.get("week") or {}).get("number")
        if isinstance(event.get("week"), dict)
        else event.get("week"),
    ]
    for value in candidates:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_espn_scoreboard_payloads(
    payloads: Sequence[Mapping[str, Any]],
    *,
    initial_event_meta: Mapping[str, Mapping[str, object]] | None = None,
    initial_schedule: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Combina payloads de scoreboard ESPN conservando la semantica historica.

    El primer evento visto para un ``event_id`` gana, igual que en el loader previo.
    La salida incluye los mapas de fechas/metadatos para que Streamlit decida si los
    persiste; el parser no tiene efectos laterales.
    """
    seen_events: set[str] = set()
    played_by_pair: dict[tuple[str, str], tuple[str, str, int, int]] = {}
    pending_by_pair: dict[tuple[str, str], tuple[str, str]] = {}
    event_meta = dict(initial_event_meta or {})
    schedule = dict(initial_schedule or {})
    day_map: dict[tuple[str, str], str] = {}
    datetime_map: dict[tuple[str, str], str] = {}

    for payload in payloads:
        for event in payload.get("events", []) or []:
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            home = next((item for item in competitors if item.get("homeAway") == "home"), None)
            away = next((item for item in competitors if item.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            home_name = (home.get("team") or {}).get("displayName")
            away_name = (away.get("team") or {}).get("displayName")
            if not home_name or not away_name:
                continue

            canonical_pair = (canon_club(home_name), canon_club(away_name))
            iso_value = str(event.get("date") or competition.get("date") or "").strip()
            event_id = str(event.get("id") or f"{canonical_pair[0]}|{canonical_pair[1]}|{iso_value}")
            if event_id in seen_events:
                continue
            seen_events.add(event_id)

            status_type = ((competition.get("status") or {}).get("type") or {})
            state = str(status_type.get("state") or "").lower()
            completed = bool(status_type.get("completed"))
            status_name = str(status_type.get("name") or "").upper()
            round_number = _espn_round_number(event, competition)

            if iso_value:
                day_map[(home_name, away_name)] = iso_value[:10]
                day_map[canonical_pair] = iso_value[:10]
                datetime_map[(home_name, away_name)] = iso_value
                datetime_map[canonical_pair] = iso_value
                schedule[f"{canonical_pair[0]}|||{canonical_pair[1]}"] = iso_value

            event_meta[f"{canonical_pair[0]}|||{canonical_pair[1]}"] = {
                "event_id": event_id,
                "scheduled_at": iso_value,
                "state": state,
                "completed": completed,
                "status_name": status_name,
                "round": round_number,
            }

            if any(token in status_name for token in ("CANCEL", "ABANDON")):
                pending_by_pair.pop(canonical_pair, None)
                continue
            if "POSTPON" in status_name:
                continue

            if completed or state == "post":
                try:
                    result = (
                        home_name,
                        away_name,
                        int(float(home.get("score"))),
                        int(float(away.get("score"))),
                    )
                except (TypeError, ValueError):
                    continue
                played_by_pair[canonical_pair] = result
                pending_by_pair.pop(canonical_pair, None)
            elif state in ("pre", "in") and canonical_pair not in played_by_pair:
                pending_by_pair[canonical_pair] = (home_name, away_name)

    return {
        "played": list(played_by_pair.values()),
        "pending": [
            value for pair, value in pending_by_pair.items()
            if pair not in played_by_pair
        ],
        "event_meta": event_meta,
        "schedule": schedule,
        "day_map": day_map,
        "datetime_map": datetime_map,
    }
