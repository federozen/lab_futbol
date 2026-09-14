"""Fuentes, normalizacion y respaldo del fixture LPF 2026.

Este modulo no depende de Streamlit. Recibe callbacks para canonizar clubes y
permite combinar LPF oficial, ESPN, FutbolArgentino.com y una ultima foto JSON sin inferir
resultados a partir de los PJ de la tabla.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
import re
import unicodedata
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ARG_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_STATUS_MAP = {
    "jugado": "played",
    "finalizado": "played",
    "final": "played",
    "por jugar": "scheduled",
    "programado": "scheduled",
    "proximo": "scheduled",
    "próximo": "scheduled",
    "en juego": "live",
    "en vivo": "live",
    "aplazado": "postponed",
    "postergado": "postponed",
    "suspendido": "postponed",
    "cancelado": "cancelled",
    "anulado": "cancelled",
}

# Variantes visibles en FutbolArgentino.com. Las claves se comparan contra los
# nombres canonicos que llegan desde el fixture de la aplicacion.
_SOURCE_ALIASES = {
    "Argentinos Juniors": ["Argentinos J.", "Argentinos"],
    "Atletico Tucuman": ["A. Tucuman", "Atlético Tucumán"],
    "Barracas Central": ["Barracas"],
    "Boca Juniors": ["Boca"],
    "Central Cordoba": ["Central Córdoba SE", "Central Córdoba", "C. Córdoba"],
    "Defensa y Justicia": ["Defensa"],
    "Deportivo Riestra": ["Riestra"],
    "Estudiantes de La Plata": ["Estudiantes"],
    "Estudiantes de Rio Cuarto": ["Estudiantes Río Cuarto", "Estudiantes (RC)", "Estudiantes RC"],
    "Gimnasia La Plata": ["Gimnasia"],
    "Gimnasia de Mendoza": ["Gimnasia Mendoza", "Gimnasia (M)", "Gimnasia M", "Gimnasia (Mza.)", "Gimnasia Mza."],
    "Independiente Rivadavia": ["Ind. Rivadavia", "Ind Rivadavia", "Ind. Rivadavia Mza.", "Independiente Rivadavia Mza."],
    "Newell's Old Boys": ["Newell's", "Newells"],
    "Racing": ["Racing Club"],
    "River Plate": ["River"],
    "Rosario Central": ["Rosario"],
    "Talleres": ["Talleres de Córdoba", "Talleres (Córdoba)"],
    "Union": ["Unión de Santa Fe", "Unión"],
    "Velez Sarsfield": ["Vélez"],
}


def _ascii(value: object) -> str:
    text = str(value or "").strip().lower()
    text = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    text = text.replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value))


def official_fixture_index(fixture: Sequence[Mapping[str, object]]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for row in fixture or []:
        home = str(row.get("l") or row.get("home") or "").strip()
        away = str(row.get("v") or row.get("away") or "").strip()
        if not home or not away:
            continue
        out[(home, away)] = {
            "round": int(row.get("f") or row.get("round") or 0),
            "kind": str(row.get("tipo") or row.get("kind") or "zone"),
            "zone": row.get("zona") or row.get("zone"),
        }
    return out


def _canonical_aliases(expected_teams: Iterable[str]) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    for team in expected_teams:
        key = _ascii(team)
        candidates = [team]
        candidates.extend(_SOURCE_ALIASES.get(team, []))
        candidates.extend(_SOURCE_ALIASES.get(key.title(), []))
        # Coincidencias por forma sin acentos para nombres canonicos del proyecto.
        for source_key, values in _SOURCE_ALIASES.items():
            if _ascii(source_key) == key:
                candidates.extend(values)
        aliases[team] = list(dict.fromkeys(str(item) for item in candidates if item))
    return aliases


def resolve_team_token(
    token: object,
    *,
    canon_club: Callable[[str], str],
    expected_teams: Iterable[str],
) -> str | None:
    """Resuelve una celda visible, incluso si trae nombre largo + abreviatura."""
    raw = re.sub(r"^\s*\d+[.)-]?\s*", "", str(token or ""))
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None

    expected = set(expected_teams)
    direct = canon_club(raw)
    if direct in expected:
        return direct

    compact = _compact(raw)
    if not compact:
        return None
    scores: list[tuple[int, str]] = []
    for team, variants in _canonical_aliases(expected).items():
        best = 0
        for variant in variants:
            needle = _compact(variant)
            if len(needle) >= 4 and needle in compact:
                best = max(best, len(needle))
        if best:
            scores.append((best, team))
    scores.sort(reverse=True)
    if not scores:
        return None
    if len(scores) == 1 or scores[0][0] > scores[1][0]:
        return scores[0][1]
    return None


def parse_spanish_date(value: object, default_year: int = 2026) -> date | None:
    text = _ascii(value)
    text = re.sub(r"^[a-z]+,\s*", "", text)
    match = re.search(r"\b(\d{1,2})\s+(?:de\s+)?([a-z]+)(?:\s+(?:de\s+)?(\d{4}))?\b", text)
    if not match:
        return None
    month = _SPANISH_MONTHS.get(match.group(2))
    if not month:
        return None
    try:
        return date(int(match.group(3) or default_year), month, int(match.group(1)))
    except ValueError:
        return None


def parse_clock(value: object) -> time | None:
    text = str(value or "").strip().upper()
    # Las agendas oficiales de LPF usan tanto 18:00 como 18.00.
    text = re.sub(r"(?<=\d)[.](?=\d{2}(?:\s|$))", ":", text)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3)
    if ampm:
        if hour == 12:
            hour = 0
        if ampm == "PM":
            hour += 12
    try:
        return time(hour, minute)
    except ValueError:
        return None


def _status(value: object) -> str | None:
    text = _ascii(value)
    for label, status in _STATUS_MAP.items():
        if text == _ascii(label) or text.startswith(_ascii(label) + " "):
            return status
    # FutbolArgentino.com muestra el minuto (por ejemplo, 87' o 45+2')
    # en el lugar del estado mientras el partido está en juego. Conservar el
    # registro como live evita descartarlo, pero nunca lo convierte en resultado final.
    if re.fullmatch(r"\d{1,3}(?:\+\d{1,2})?['’]?", str(value or "").strip()):
        return "live"
    if text in {"entretiempo", "descanso", "medio tiempo"}:
        return "live"
    return None


def _score(value: object) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _iso_datetime(day: date | None, clock: time | None) -> str:
    if not day:
        return ""
    dt = datetime.combine(day, clock or time(17, 0), tzinfo=ARG_TZ)
    return dt.isoformat()


def _record_priority(record: Mapping[str, object]) -> tuple[int, int, str]:
    status = str(record.get("status") or "")
    base = {
        "played": 100,
        "live": 90,
        "scheduled": 70,
        "postponed": 40,
        "cancelled": 10,
    }.get(status, 0)
    scheduled = str(record.get("scheduled_at") or "")
    return base, 1 if scheduled else 0, scheduled


def merge_match_records(*collections: Iterable[Mapping[str, object]]) -> list[dict]:
    """Une fuentes por pareja. Un resultado siempre prevalece sobre programación."""
    best: dict[tuple[str, str], dict] = {}
    for collection in collections:
        for raw in collection or []:
            home = str(raw.get("home") or "").strip()
            away = str(raw.get("away") or "").strip()
            if not home or not away or home == away:
                continue
            row = {
                "match_id": str(raw.get("match_id") or raw.get("event_id") or f"{home}|{away}"),
                "round": int(raw.get("round") or raw.get("round_number") or 0),
                "home": home,
                "away": away,
                "scheduled_at": str(raw.get("scheduled_at") or ""),
                "status": str(raw.get("status") or "scheduled"),
                "home_score": raw.get("home_score"),
                "away_score": raw.get("away_score"),
                "source": str(raw.get("source") or ""),
            }
            key = (home, away)
            if key not in best or _record_priority(row) > _record_priority(best[key]):
                best[key] = row
    return sorted(best.values(), key=lambda row: (int(row.get("round") or 999), str(row.get("scheduled_at") or ""), row["home"], row["away"]))


def _jsonld_records(
    html: str,
    *,
    canon_club: Callable[[str], str],
    fixture_index: Mapping[tuple[str, str], Mapping[str, object]],
) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    expected = {team for pair in fixture_index for team in pair}
    records: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                yield from walk(item)
        elif isinstance(node, dict):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(item).lower() in {"sportsevent", "event"} for item in types if item):
                yield node
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from walk(value)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except Exception:
            continue
        for event in walk(payload):
            home_raw = event.get("homeTeam") or event.get("competitor") or {}
            away_raw = event.get("awayTeam") or {}
            if isinstance(home_raw, list) and len(home_raw) >= 2 and not away_raw:
                home_raw, away_raw = home_raw[0], home_raw[1]
            home_name = home_raw.get("name") if isinstance(home_raw, dict) else str(home_raw or "")
            away_name = away_raw.get("name") if isinstance(away_raw, dict) else str(away_raw or "")
            home = resolve_team_token(home_name, canon_club=canon_club, expected_teams=expected)
            away = resolve_team_token(away_name, canon_club=canon_club, expected_teams=expected)
            if not home or not away or (home, away) not in fixture_index:
                continue
            event_status = _ascii(event.get("eventStatus") or event.get("status") or "")
            status = "played" if "complete" in event_status or "finished" in event_status else "scheduled"
            score = event.get("score") or {}
            home_score = away_score = None
            if isinstance(score, dict):
                try:
                    home_score = int(score.get("homeScore"))
                    away_score = int(score.get("awayScore"))
                    status = "played"
                except (TypeError, ValueError):
                    pass
            meta = fixture_index[(home, away)]
            records.append({
                "match_id": str(event.get("@id") or event.get("url") or f"FA|{home}|{away}"),
                "round": int(meta.get("round") or 0),
                "home": home,
                "away": away,
                "scheduled_at": str(event.get("startDate") or ""),
                "status": status,
                "home_score": home_score,
                "away_score": away_score,
                "source": "FutbolArgentino.com",
            })
    return records


def parse_futbolargentino_results_html(
    html: str,
    *,
    canon_club: Callable[[str], str],
    official_fixture: Sequence[Mapping[str, object]],
) -> list[dict]:
    """Lee resultados y programación visible de FutbolArgentino.com.

    Usa JSON-LD cuando está disponible y luego una estrategia por texto visible.
    La salida se filtra estrictamente contra el fixture oficial de la aplicación,
    lo que descarta partidos, noticias y duplicados ajenos al Clausura.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        raise RuntimeError(f"BeautifulSoup no está disponible: {exc}") from exc

    fixture_index = official_fixture_index(official_fixture)
    expected = {team for pair in fixture_index for team in pair}
    jsonld = _jsonld_records(html, canon_club=canon_club, fixture_index=fixture_index)

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    tokens = [re.sub(r"\s+", " ", text).strip() for text in soup.stripped_strings]
    tokens = [token for token in tokens if token]

    round_number = 0
    current_day: date | None = None
    text_records: list[dict] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        round_match = re.search(r"\bFecha\s+(\d+)\b", token, flags=re.I)
        if round_match:
            round_number = int(round_match.group(1))
            i += 1
            continue
        parsed_day = parse_spanish_date(token)
        if parsed_day:
            current_day = parsed_day
            i += 1
            continue

        home = resolve_team_token(token, canon_club=canon_club, expected_teams=expected)
        if not home:
            i += 1
            continue

        # Estructura visible habitual: local, hora, marcador, visitante, estado.
        # La hora es opcional: el proveedor puede omitirla o moverla en el DOM
        # cuando actualiza un partido en vivo/final. Para reconocer un resultado
        # alcanzan marcador + rival + estado, siempre filtrados contra el fixture.
        time_idx = score_idx = away_idx = status_idx = None
        clock = None
        result = None
        away = None
        status = None
        upper = min(len(tokens), i + 14)
        for j in range(i + 1, upper):
            if re.search(r"\bFecha\s+\d+\b", tokens[j], flags=re.I) or parse_spanish_date(tokens[j]):
                break
            if time_idx is None:
                parsed_clock = parse_clock(tokens[j])
                if parsed_clock:
                    time_idx, clock = j, parsed_clock
                    continue
            if score_idx is None:
                parsed_score = _score(tokens[j])
                if parsed_score:
                    score_idx, result = j, parsed_score
                    continue
            if score_idx is not None and away_idx is None:
                candidate = resolve_team_token(tokens[j], canon_club=canon_club, expected_teams=expected)
                if candidate and candidate != home:
                    away_idx, away = j, candidate
                    continue
            if away_idx is not None:
                parsed_status = _status(tokens[j])
                if parsed_status:
                    status_idx, status = j, parsed_status
                    break

        if not all(value is not None for value in (score_idx, away_idx, status_idx)):
            i += 1
            continue
        key = (home, away)
        if key not in fixture_index:
            i += 1
            continue
        meta = fixture_index[key]
        effective_round = int(meta.get("round") or round_number or 0)
        home_score = away_score = None
        if status in {"played", "live"} and result is not None:
            home_score, away_score = result
        text_records.append({
            "match_id": f"FA-F{effective_round:02d}-{_compact(home)}-{_compact(away)}",
            "round": effective_round,
            "home": home,
            "away": away,
            "scheduled_at": _iso_datetime(current_day, clock),
            "status": status,
            "home_score": home_score,
            "away_score": away_score,
            "source": "FutbolArgentino.com",
        })
        i = status_idx + 1

    merged = merge_match_records(jsonld, text_records)
    if not merged:
        raise RuntimeError("no pude identificar partidos del Clausura en el HTML")
    return merged



_LPF_RESULT_TITLE_RE = re.compile(
    r"\b(?:venci[oó]|gan[oó]|gole[oó]|derrot[oó]|super[oó]|empataron|igualaron|"
    r"cerr[oó]|complet[oó]|triunf[oó]|victoria|cay[oó])\b",
    flags=re.I,
)

_LPF_ROUND_HUB_TITLE_RE = re.compile(
    r"^(?:agenda|programacion)(?:\s+de)?\s+la\s+fecha\s+\d+\s*$",
    flags=re.I,
)

_LPF_ROUND_HUB_PATH_RE = re.compile(
    r"/(?:agenda|programacion)-de-la-fecha-\d+(?:-\d+)?/?$",
    flags=re.I,
)


def parse_lpf_official_listing_html(html: str, *, base_url: str) -> list[dict]:
    """Extrae notas de Primera que pueden contener marcadores explícitos.

    La LPF usa las notas ``Agenda/Programación de la fecha N`` como *round hubs*:
    nacen con horarios y, a medida que se juega la jornada, el mismo URL se actualiza
    con marcadores. El título de la portada puede quedar desfasado respecto del cuerpo
    por caché/CDN, por lo que no alcanza con buscar sólo verbos de resultado.

    Se descargan dos clases acotadas de notas: títulos de cierre/resultado y hubs de
    una fecha individual. La seguridad sigue en el parser del artículo: sólo una línea
    con dos clubes + marcador explícito + pareja existente en el fixture puede volverse
    un partido jugado. Una agenda todavía no disputada aporta cero resultados.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        raise RuntimeError(f"BeautifulSoup no está disponible: {exc}") from exc

    soup = BeautifulSoup(html or "", "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    base_host = urlparse(base_url).netloc.lower()
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urljoin(base_url, str(anchor.get("href") or "").strip())
        parsed = urlparse(href)
        if not href or href in seen:
            continue
        if parsed.netloc.lower() != base_host:
            continue
        if "/notas/primera/" not in parsed.path or not re.search(r"/2026/\d{2}/\d{2}/", parsed.path):
            continue
        if title.lower() in {"leer más", "leer mas"}:
            # El mismo href suele aparecer una segunda vez con este texto; conservar
            # la primera ancla con el título real.
            continue
        ascii_title = _ascii(title)
        is_result_story = bool(_LPF_RESULT_TITLE_RE.search(ascii_title))
        is_round_hub = bool(
            _LPF_ROUND_HUB_TITLE_RE.fullmatch(ascii_title)
            or _LPF_ROUND_HUB_PATH_RE.search(_ascii(parsed.path))
        )
        if not is_result_story and not is_round_hub:
            continue
        seen.add(href)
        out.append({"title": title, "url": href})
    return out


def _official_score_line(
    text: str,
    *,
    canon_club: Callable[[str], str],
    expected: set[str],
    fixture_index: Mapping[tuple[str, str], Mapping[str, object]],
) -> tuple[str, str, int, int] | None:
    """Reconoce las dos formas de marcador que usa la web oficial.

    En sus notas aparecen tanto ``River 2 – Vélez 2`` como
    ``Racing 0 – Banfield 1``. También puede haber zona, estadio o TV después del
    marcador. La pareja resuelta siempre debe existir en el fixture de la app.
    """
    line = re.sub(r"\s+", " ", str(text or "")).strip()
    if not line or "–" not in line and "—" not in line and " - " not in line:
        return None

    patterns = (
        # local 1 – 3 visitante
        re.compile(r"^(?P<home>.+?)\s+(?P<hg>\d+)\s*[–—-]\s*(?P<ag>\d+)\s+(?P<away>.+)$"),
        # local 1 – visitante 3
        re.compile(r"^(?P<home>.+?)\s+(?P<hg>\d+)\s*[–—-]\s*(?P<away>.+?)\s+(?P<ag>\d+)(?:\s*[,;(].*)?$"),
    )
    for pattern in patterns:
        match = pattern.match(line)
        if not match:
            continue
        home = resolve_team_token(match.group("home"), canon_club=canon_club, expected_teams=expected)
        away = resolve_team_token(match.group("away"), canon_club=canon_club, expected_teams=expected)
        if not home or not away or home == away:
            continue
        key = (home, away)
        if key not in fixture_index:
            continue
        return home, away, int(match.group("hg")), int(match.group("ag"))
    return None


def _lpf_article_round(soup, source_url: str = "") -> int | None:
    """Devuelve la fecha del Clausura cuando la nota la identifica sin ambigüedad.

    Los hubs oficiales mantienen slugs como ``agenda-de-la-fecha-6`` incluso
    después de actualizar el título. Para otras notas se toma la primera mención
    estructural ``Fecha N`` del cuerpo. No se usan menciones de noticias relacionadas
    del pie para evitar adjudicar una jornada ajena.
    """
    path = _ascii(urlparse(str(source_url or "")).path)
    match = re.search(r"(?:^|/) [^/]*fecha-(\d{1,2})(?:-|/|$)", path, flags=re.X)
    if match:
        value = int(match.group(1))
        if 1 <= value <= 16:
            return value

    # Buscar sólo bloques de contenido simples, en orden de documento. La primera
    # mención "Fecha N" de las notas oficiales corresponde al artículo; las tarjetas
    # de "Últimas noticias" aparecen después.
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"], limit=80):
        value = _ascii(tag.get_text(" ", strip=True))
        match = re.search(r"\bfecha\s+(\d{1,2})\b", value)
        if not match:
            continue
        round_number = int(match.group(1))
        if 1 <= round_number <= 16:
            return round_number
    return None


def _lpf_atomic_article_candidates(soup) -> list[str]:
    """Extrae líneas de marcador sin concatenar contenedores de varios partidos.

    El sitio LPF agrupa cada día/jornada en ``div`` que pueden contener varios
    ``p``. Interpretar el texto completo de esos wrappers puede fabricar una pareja
    válida con el marcador del primer partido y el nombre del último. Se aceptan
    párrafos/listas/títulos y sólo ``div`` hoja (útiles cuando la fila está armada
    con ``span``), además de strings individuales como respaldo.
    """
    candidates: list[str] = []
    block_children = ["p", "li", "h1", "h2", "h3", "h4", "div", "section", "article"]
    for tag in soup.find_all(["p", "li", "h2", "h3", "h4", "div"]):
        if tag.name == "div" and tag.find(block_children):
            continue
        value = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
        # Un resultado oficial es una línea corta. El límite también impide que un
        # wrapper no reconocido se convierta en un candidato gigante.
        if value and len(value) <= 280:
            candidates.append(value)
    candidates.extend(
        value
        for raw in soup.stripped_strings
        if (value := re.sub(r"\s+", " ", raw).strip()) and len(value) <= 280
    )
    return candidates


def parse_lpf_official_results_article_html(
    html: str,
    *,
    canon_club: Callable[[str], str],
    official_fixture: Sequence[Mapping[str, object]],
    source_url: str = "",
) -> list[dict]:
    """Extrae marcadores explícitos de notas de Primera de ligaprofesional.ar.

    No interpreta titulares ni prosa: sólo líneas atómicas que contienen dos clubes,
    un marcador explícito y una pareja existente en el fixture oficial. Cuando la
    nota identifica una ``Fecha N``, el cruce debe pertenecer además a esa misma
    jornada. Esta doble validación evita que un contenedor HTML que concatena varios
    partidos fabrique un resultado de otra fecha del fixture.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        raise RuntimeError(f"BeautifulSoup no está disponible: {exc}") from exc

    fixture_index = official_fixture_index(official_fixture)
    expected = {team for pair in fixture_index for team in pair}
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    article_round = _lpf_article_round(soup, source_url)
    candidates = _lpf_atomic_article_candidates(soup)

    records: list[dict] = []
    seen_lines: set[str] = set()
    for text in candidates:
        if not text or text in seen_lines:
            continue
        seen_lines.add(text)
        parsed = _official_score_line(
            text, canon_club=canon_club, expected=expected, fixture_index=fixture_index
        )
        if not parsed:
            continue
        home, away, home_score, away_score = parsed
        meta = fixture_index[(home, away)]
        match_round = int(meta.get("round") or 0)
        if article_round is not None and match_round != article_round:
            continue
        records.append({
            "match_id": f"LPF-F{match_round:02d}-{_compact(home)}-{_compact(away)}",
            "round": match_round,
            "home": home,
            "away": away,
            "scheduled_at": "",
            "status": "played",
            "home_score": home_score,
            "away_score": away_score,
            "source": "Liga Profesional de Fútbol",
            "source_url": str(source_url or ""),
        })
    return merge_match_records(records)

def records_from_legacy(
    played: Iterable[tuple[str, str, int, int]],
    pending: Iterable[tuple[str, str]],
    *,
    schedule: Mapping[str, str] | None,
    event_meta: Mapping[str, Mapping[str, object]] | None,
    official_fixture: Sequence[Mapping[str, object]],
    source: str,
) -> list[dict]:
    fixture_index = official_fixture_index(official_fixture)
    schedule = schedule or {}
    event_meta = event_meta or {}
    records: list[dict] = []
    played_pairs = set()
    for home, away, gh, ga in played or []:
        key = (home, away)
        if key not in fixture_index:
            continue
        played_pairs.add(key)
        map_key = f"{home}|||{away}"
        meta = event_meta.get(map_key) or {}
        records.append({
            "match_id": str(meta.get("event_id") or f"{source}|{home}|{away}"),
            "round": int(meta.get("round") or fixture_index[key].get("round") or 0),
            "home": home,
            "away": away,
            "scheduled_at": str(meta.get("scheduled_at") or schedule.get(map_key) or ""),
            "status": "played",
            "home_score": int(gh),
            "away_score": int(ga),
            "source": source,
        })
    for home, away in pending or []:
        key = (home, away)
        if key not in fixture_index or key in played_pairs:
            continue
        map_key = f"{home}|||{away}"
        meta = event_meta.get(map_key) or {}
        records.append({
            "match_id": str(meta.get("event_id") or f"{source}|{home}|{away}"),
            "round": int(meta.get("round") or fixture_index[key].get("round") or 0),
            "home": home,
            "away": away,
            "scheduled_at": str(meta.get("scheduled_at") or schedule.get(map_key) or ""),
            "status": "scheduled",
            "home_score": None,
            "away_score": None,
            "source": source,
        })
    return merge_match_records(records)


def expected_played_count(zones: Mapping[str, Mapping[str, Mapping[str, object]]] | None) -> int | None:
    if not zones:
        return None
    total = 0
    for base in zones.values():
        for row in base.values():
            try:
                total += int((row or {}).get("pj", 0))
            except (TypeError, ValueError):
                return None
    return total // 2 if total % 2 == 0 else None


def validate_fixture_records(
    records: Sequence[Mapping[str, object]],
    *,
    official_fixture: Sequence[Mapping[str, object]],
    expected_played: int | None = None,
) -> list[dict]:
    fixture_index = official_fixture_index(official_fixture)
    clean = merge_match_records(records)
    errors: list[str] = []
    for row in clean:
        key = (str(row.get("home") or ""), str(row.get("away") or ""))
        if key not in fixture_index:
            errors.append(f"{key[0]}–{key[1]} no pertenece al fixture")
        if row.get("status") == "played":
            if row.get("home_score") is None or row.get("away_score") is None:
                errors.append(f"falta el marcador de {key[0]}–{key[1]}")
    played = [row for row in clean if row.get("status") == "played"]
    if expected_played is not None and len(played) < expected_played:
        errors.append(f"faltan {expected_played - len(played)} resultado(s) para explicar los PJ de las zonas")
    if errors:
        raise RuntimeError("; ".join(errors[:8]))
    return clean


def played_pending_from_records(records: Sequence[Mapping[str, object]]) -> tuple[list[tuple[str, str, int, int]], list[tuple[str, str]]]:
    played: list[tuple[str, str, int, int]] = []
    pending: list[tuple[str, str]] = []
    for row in records or []:
        home, away = str(row.get("home") or ""), str(row.get("away") or "")
        if row.get("status") == "played":
            played.append((home, away, int(row.get("home_score") or 0), int(row.get("away_score") or 0)))
        elif row.get("status") in {"scheduled", "live", "postponed"}:
            pending.append((home, away))
    return played, pending


def snapshot_payload(records: Sequence[Mapping[str, object]], *, source: str, updated_at: str | None = None) -> dict:
    return {
        "schema": 1,
        "competition": "LPF Clausura 2026",
        "source": str(source or "fuente automática"),
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "matches": merge_match_records(records),
    }


def write_snapshot(path: str | Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def read_snapshot(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def snapshot_age_hours(payload: Mapping[str, object]) -> float:
    raw = str(payload.get("updated_at") or "").replace("Z", "+00:00")
    updated = datetime.fromisoformat(raw)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 3600.0)
