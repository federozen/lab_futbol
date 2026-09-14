from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlparse

from football_lab.data.calculator_adapter import ExistingCalculatorProvider
from football_lab.models import Match, ProviderDataset
from football_lab.utils import parse_datetime, slug
from lpf_clubs import canon_club
from lpf_data_2026 import LPF_FIXTURE
from lpf_fixture_sources import (
    ARG_TZ,
    expected_played_count,
    official_fixture_index,
    parse_clock,
    parse_futbolargentino_results_html,
    parse_lpf_official_listing_html,
    parse_lpf_official_results_article_html,
    parse_spanish_date,
    resolve_team_token,
)
from lpf_http import fetch_html
from lpf_provider_adapters import parse_futbolargentino_zones_html
from lpf_reconcile import lpf_results_mismatches


FUTBOLARGENTINO_RESULTS_URLS = (
    "https://www.futbolargentino.com/primera-division/clausura/",
    "https://www.futbolargentino.com/primera-division/torneo/",
    "https://www.futbolargentino.com/primera-division/resultados",
    "https://www.futbolargentino.com/primera-division/clausura/resultados",
)
FUTBOLARGENTINO_ZONES_URL = (
    "https://www.futbolargentino.com/primera-division/clausura/tabla-de-posiciones"
)
FUTBOLARGENTINO_REFERER = "https://www.futbolargentino.com/primera-division/"
LPF_PRIMERA_URL = "https://www.ligaprofesional.ar/notas/primera/"
LPF_PRIMERA_PAGES = (
    LPF_PRIMERA_URL,
    f"{LPF_PRIMERA_URL}page/2/",
)


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def discover_lpf_schedule_links(html: str, *, base_url: str) -> list[str]:
    """Descubre notas de programación en la portada de Primera.

    No confía en el slug ni en IDs de WordPress: exige que el título visible sea
    una agenda/programación de fecha(s) y que el enlace pertenezca al mismo host.
    El parser del artículo vuelve a validar cada cruce contra ``LPF_FIXTURE``.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover - dependencia declarada
        raise RuntimeError(f"BeautifulSoup no está disponible: {exc}") from exc

    soup = BeautifulSoup(html or "", "lxml")
    host = urlparse(base_url).netloc.lower()
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = _clean_text(anchor.get_text(" ", strip=True))
        normalized = title.lower()
        if not title or not re.search(r"\b(?:agenda|programaci[oó]n)\b", normalized):
            continue
        has_fecha = bool(re.search(r"\bfecha(?:s)?\b", normalized))
        has_round_range = bool(re.search(r"\b\d{1,2}\s+a\s+(?:la\s+)?\d{1,2}\b", normalized))
        if not has_fecha and not has_round_range:
            continue
        if "proyecci" in normalized:
            continue
        href = urljoin(base_url, str(anchor.get("href") or "").strip())
        parsed = urlparse(href)
        if parsed.netloc.lower() != host or href in seen:
            continue
        if "proyeccion" in parsed.path.lower():
            continue
        seen.add(href)
        out.append(href)
    return out


def parse_lpf_schedule_article_html(
    html: str,
    *,
    official_fixture: Sequence[Mapping[str, object]] = LPF_FIXTURE,
    default_year: int = 2026,
    source_url: str = "",
) -> list[dict]:
    """Extrae fecha y hora desde una agenda oficial de la LPF.

    Acepta líneas del tipo ``18.00 River – Huracán (Zona B)``. Las parejas que no
    existen en el fixture canónico se descartan, de modo que una tarjeta de noticias
    relacionadas nunca entra al dataset del Clausura por accidente.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"BeautifulSoup no está disponible: {exc}") from exc

    fixture_index = official_fixture_index(official_fixture)
    expected = {team for pair in fixture_index for team in pair}
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    rows: list[dict] = []
    current_round: int | None = None
    current_day = None
    seen: set[tuple[str, str]] = set()

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = _clean_text(tag.get_text(" ", strip=True))
        if not text:
            continue
        if re.search(r"^Últimas noticias$", text, flags=re.I):
            break

        round_match = re.search(r"\bFecha\s+(\d{1,2})\b", text, flags=re.I)
        if round_match and len(text) <= 40:
            value = int(round_match.group(1))
            if 1 <= value <= 16:
                current_round = value
            continue

        parsed_day = parse_spanish_date(text, default_year=default_year)
        if parsed_day is not None and not re.search(r"\d{1,2}[.:]\d{2}", text):
            current_day = parsed_day
            continue

        match = re.match(
            r"^(?P<clock>\d{1,2}[.:]\d{2})\s+(?P<home>.+?)\s+[–—-]\s+(?P<away>.+)$",
            text,
        )
        if not match or current_day is None:
            continue
        clock = parse_clock(match.group("clock"))
        if clock is None:
            continue

        home_token = _clean_text(match.group("home"))
        away_token = _clean_text(match.group("away"))
        # Zona, TV, estadio, etc. aparecen después del visitante entre paréntesis.
        away_token = re.split(r"\s+\(", away_token, maxsplit=1)[0].strip()
        home = resolve_team_token(home_token, canon_club=canon_club, expected_teams=expected)
        away = resolve_team_token(away_token, canon_club=canon_club, expected_teams=expected)
        if not home or not away or home == away:
            continue
        key = (home, away)
        if key not in fixture_index or key in seen:
            continue
        fixture_round = int(fixture_index[key].get("round") or 0)
        if current_round is not None and fixture_round != current_round:
            continue
        seen.add(key)
        dt = datetime.combine(current_day, clock, tzinfo=ARG_TZ)
        rows.append(
            {
                "match_id": f"LPF-SCHED-F{fixture_round:02d}-{slug(home)}-{slug(away)}",
                "round": fixture_round,
                "home": home,
                "away": away,
                "scheduled_at": dt.isoformat(),
                "status": "scheduled",
                "home_score": None,
                "away_score": None,
                "source": "Liga Profesional de Fútbol",
                "source_url": source_url,
            }
        )
    return rows


def _record_from_match(match: Match) -> dict:
    return {
        "match_id": match.match_id,
        "round": match.round or 0,
        "home": match.home_team,
        "away": match.away_team,
        "scheduled_at": match.match_date.isoformat() if match.match_date else "",
        "status": "played" if match.finished else match.status,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "source": match.source or "Calculadora LPF",
    }


def _played(record: Mapping[str, object]) -> bool:
    return (
        str(record.get("status") or "") in {"played", "finished"}
        and record.get("home_score") is not None
        and record.get("away_score") is not None
    )


def _source_priority(record: Mapping[str, object]) -> int:
    source = str(record.get("source") or "").lower()
    if "liga profesional" in source:
        return 50
    if "futbolargentino" in source:
        return 40
    if "snapshot" in source:
        return 25
    if "calculadora" in source:
        return 20
    return 10


def _reconcile_records(
    base_records: Iterable[Mapping[str, object]],
    snapshot_records: Iterable[Mapping[str, object]],
    live_records: Iterable[Mapping[str, object]],
) -> tuple[list[dict], list[str]]:
    """Reconcilia por pareja sin permitir que una fuente parcial haga retroceder datos.

    Marcadores finales tienen prioridad sobre estados en vivo/programados. Entre dos
    marcadores finales, LPF oficial > FutbolArgentino > snapshot > base incluida.
    Las fechas se completan por separado para conservar, por ejemplo, un marcador
    validado localmente y la hora oficial obtenida por scraping.
    """
    fixture = official_fixture_index(LPF_FIXTURE)
    buckets: dict[tuple[str, str], list[Mapping[str, object]]] = {
        pair: [] for pair in fixture
    }
    for row in list(base_records) + list(snapshot_records) + list(live_records):
        key = (str(row.get("home") or ""), str(row.get("away") or ""))
        if key in buckets:
            buckets[key].append(row)

    out: list[dict] = []
    conflicts: list[str] = []
    for (home, away), meta in fixture.items():
        rows = buckets[(home, away)]
        finished = [row for row in rows if _played(row)]
        if finished:
            # Primero mayor confianza; a igual confianza, conservar quien trae fecha.
            finished.sort(
                key=lambda row: (
                    _source_priority(row),
                    bool(str(row.get("scheduled_at") or "")),
                ),
                reverse=True,
            )
            winner = finished[0]
            score_set = {
                (int(row["home_score"]), int(row["away_score"]))
                for row in finished
                if row.get("home_score") is not None and row.get("away_score") is not None
            }
            if len(score_set) > 1:
                conflicts.append(
                    f"Conflicto de marcador en {home}–{away}: "
                    + ", ".join(f"{a}-{b}" for a, b in sorted(score_set))
                )
        elif rows:
            status_rank = {"live": 4, "scheduled": 3, "postponed": 2, "cancelled": 1}
            winner = sorted(
                rows,
                key=lambda row: (status_rank.get(str(row.get("status") or "scheduled"), 0), _source_priority(row)),
                reverse=True,
            )[0]
        else:
            winner = {
                "match_id": f"LPF-2026-C-{int(meta.get('round') or 0):02d}-{slug(home)}-{slug(away)}",
                "status": "scheduled",
                "source": "Fixture LPF incluido",
            }

        dated = [row for row in rows if str(row.get("scheduled_at") or "").strip()]
        dated.sort(key=_source_priority, reverse=True)
        scheduled_at = str(dated[0].get("scheduled_at") or "") if dated else ""
        is_finished = _played(winner)
        status = "played" if is_finished else str(winner.get("status") or "scheduled")
        out.append(
            {
                "match_id": str(winner.get("match_id") or f"{home}|{away}"),
                "round": int(meta.get("round") or winner.get("round") or 0),
                "home": home,
                "away": away,
                "scheduled_at": scheduled_at,
                "status": status,
                "home_score": int(winner["home_score"]) if is_finished else None,
                "away_score": int(winner["away_score"]) if is_finished else None,
                "source": str(winner.get("source") or ""),
            }
        )
    return out, conflicts


class PublicScrapingProvider:
    """Proveedor operativo sin APIs pagas.

    Fuente principal: FutbolArgentino.com (HTML). Complemento/contraste: notas de
    Primera de la LPF oficial. Si la red o un sitio falla, usa una snapshot reciente
    y por último la base incluida de la Calculadora LPF. Nunca elimina un resultado
    ya conocido porque un scraping parcial devuelva menos partidos.
    """

    provider_name = "scraping_publico"

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        timeout: int = 8,
        snapshot_max_age_hours: int = 48,
        html_getter: Callable[..., tuple[str, str]] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self.timeout = int(timeout)
        self.snapshot_max_age_hours = int(snapshot_max_age_hours)
        self.html_getter = html_getter
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.snapshot_path = self.root / "data" / "live" / "lpf_web_snapshot.json"

    def _get_html(self, url: str, *, referer: str = "") -> tuple[str, str]:
        if self.html_getter is not None:
            return self.html_getter(url, referer=referer, timeout=self.timeout)
        return fetch_html(url, referer=referer, timeout=self.timeout, retries=0)

    def _load_snapshot(self) -> tuple[list[dict], float | None, str | None]:
        if not self.snapshot_path.exists():
            return [], None, None
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            saved = parse_datetime(payload.get("saved_at"))
            if saved is None:
                return [], None, "La snapshot web no tiene fecha válida."
            if saved.tzinfo is None:
                saved = saved.replace(tzinfo=timezone.utc)
            age = (self.now() - saved.astimezone(timezone.utc)).total_seconds() / 3600.0
            if age > self.snapshot_max_age_hours:
                return [], age, f"La última snapshot web tiene {age:.1f} h y se considera vencida."
            records = list(payload.get("records") or [])
            for row in records:
                source = str(row.get("source") or "web")
                if not source.startswith("Snapshot · "):
                    row["source"] = f"Snapshot · {source}"
            return records, age, None
        except Exception as exc:
            return [], None, f"No pude leer la snapshot web: {exc}"

    def _save_snapshot(self, records: list[dict], metadata: dict) -> str | None:
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": 1,
                "saved_at": self.now().isoformat(),
                "records": records,
                "metadata": metadata,
            }
            tmp = self.snapshot_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.snapshot_path)
            return None
        except Exception as exc:
            return f"No pude guardar la snapshot web: {exc}"

    def _scrape_futbolargentino(self) -> tuple[list[dict], list[str], list[str]]:
        records: list[dict] = []
        sources: list[str] = []
        errors: list[str] = []
        # Las variantes son espejos del mismo torneo. Se detiene al primer HTML que
        # realmente entrega un conjunto amplio de partidos para no castigar al sitio.
        for url in FUTBOLARGENTINO_RESULTS_URLS:
            try:
                html, final_url = self._get_html(url, referer=FUTBOLARGENTINO_REFERER)
                parsed = parse_futbolargentino_results_html(
                    html,
                    canon_club=canon_club,
                    official_fixture=LPF_FIXTURE,
                )
                records.extend(parsed)
                sources.append(final_url or url)
                if len(parsed) >= 40:
                    break
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        return records, sources, errors

    def _scrape_zones(self):
        try:
            html, final_url = self._get_html(
                FUTBOLARGENTINO_ZONES_URL,
                referer=FUTBOLARGENTINO_REFERER,
            )
            zones = parse_futbolargentino_zones_html(html)
            return zones, final_url or FUTBOLARGENTINO_ZONES_URL, None
        except Exception as exc:
            return {}, "", str(exc)

    def _scrape_lpf(self, *, need_results: bool) -> tuple[list[dict], list[str], list[str]]:
        records: list[dict] = []
        sources: list[str] = []
        errors: list[str] = []
        schedule_links: list[str] = []
        result_links: list[str] = []

        for page_url in LPF_PRIMERA_PAGES:
            try:
                html, final_url = self._get_html(page_url, referer=LPF_PRIMERA_URL)
                base_url = final_url or page_url
                sources.append(base_url)
                schedule_links.extend(discover_lpf_schedule_links(html, base_url=base_url))
                if need_results:
                    result_links.extend(
                        item["url"]
                        for item in parse_lpf_official_listing_html(html, base_url=base_url)
                        if item.get("url")
                    )
            except Exception as exc:
                errors.append(f"{page_url}: {exc}")
            if schedule_links and (result_links or not need_results):
                break

        # Las agendas de varias fechas suelen bastar con las primeras notas recientes.
        for url in list(dict.fromkeys(schedule_links))[:8]:
            try:
                html, final_url = self._get_html(url, referer=LPF_PRIMERA_URL)
                records.extend(
                    parse_lpf_schedule_article_html(
                        html,
                        official_fixture=LPF_FIXTURE,
                        source_url=final_url or url,
                    )
                )
                sources.append(final_url or url)
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        if need_results:
            for url in list(dict.fromkeys(result_links))[:12]:
                try:
                    html, final_url = self._get_html(url, referer=LPF_PRIMERA_URL)
                    records.extend(
                        parse_lpf_official_results_article_html(
                            html,
                            canon_club=canon_club,
                            official_fixture=LPF_FIXTURE,
                            source_url=final_url or url,
                        )
                    )
                    sources.append(final_url or url)
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
        return records, list(dict.fromkeys(sources)), errors

    @staticmethod
    def _records_to_dataset(records: list[dict], base: ProviderDataset, metadata: dict) -> ProviderDataset:
        matches: list[Match] = []
        for row in records:
            date = parse_datetime(row.get("scheduled_at"))
            played = _played(row)
            raw_status = str(row.get("status") or "scheduled")
            status = "finished" if played else raw_status
            matches.append(
                Match(
                    match_id=str(row.get("match_id") or f"{row['home']}|{row['away']}"),
                    competition="Liga Profesional",
                    season="Clausura 2026",
                    round=int(row.get("round") or 0),
                    match_date=date,
                    home_team=str(row["home"]),
                    away_team=str(row["away"]),
                    home_score=int(row["home_score"]) if played else None,
                    away_score=int(row["away_score"]) if played else None,
                    status=status,
                    source=str(row.get("source") or ""),
                )
            )
        return ProviderDataset(
            tuple(matches),
            events=base.events,
            players=base.players,
            team_groups=dict(base.team_groups),
            metadata=metadata,
        )

    def load(self) -> ProviderDataset:
        base = ExistingCalculatorProvider(self.root).load()
        base_records = [_record_from_match(m) for m in base.matches]
        snapshot_records, snapshot_age, snapshot_error = self._load_snapshot()

        warnings: list[str] = []
        if snapshot_error:
            warnings.append(snapshot_error)

        fa_records, fa_sources, fa_errors = self._scrape_futbolargentino()
        zones, zones_source, zones_error = self._scrape_zones()
        if zones_error:
            warnings.append(f"Tabla de posiciones de contraste no disponible: {zones_error}")

        expected = expected_played_count(zones) if zones else None
        fa_played = sum(_played(row) for row in fa_records)
        base_played = sum(_played(row) for row in base_records)
        snapshot_played = sum(_played(row) for row in snapshot_records)
        # Si el feed principal no explica la tabla actual, consultar además las notas
        # oficiales de resultados. Siempre se buscan agendas para completar fechas.
        known_before_lpf = max(base_played, snapshot_played, fa_played)
        need_official_results = expected is None or known_before_lpf < expected
        lpf_records, lpf_sources, lpf_errors = self._scrape_lpf(need_results=need_official_results)

        live_records = list(fa_records) + list(lpf_records)
        reconciled, conflicts = _reconcile_records(base_records, snapshot_records, live_records)
        warnings.extend(conflicts)

        finished = sum(_played(row) for row in reconciled)
        dated_finished = sum(_played(row) and bool(row.get("scheduled_at")) for row in reconciled)
        dated_all = sum(bool(row.get("scheduled_at")) for row in reconciled)
        live_ok = bool(fa_records or lpf_records)
        live_finished = sum(_played(row) for row in live_records)
        live_results_ok = live_finished > 0
        live_schedule_ok = any(bool(str(row.get("scheduled_at") or "")) for row in live_records)
        snapshot_used = bool(snapshot_records) and any(
            str(row.get("source") or "").startswith("Snapshot") for row in reconciled
        )

        if fa_errors and not fa_records:
            warnings.append("FutbolArgentino no respondió correctamente: " + " | ".join(fa_errors[:2]))
        if lpf_errors and not lpf_records:
            warnings.append("LPF oficial no aportó datos parseables: " + " | ".join(lpf_errors[:2]))
        if not live_ok:
            warnings.append(
                "No hubo actualización web en esta ejecución. Se mantiene la última información válida disponible."
            )
        standings_mismatches: list[str] = []
        standings_reconciled = None
        if zones and expected is not None and finished == expected:
            played_rows = [
                (str(row["home"]), str(row["away"]), int(row["home_score"]), int(row["away_score"]))
                for row in reconciled
                if _played(row)
            ]
            standings_mismatches = lpf_results_mismatches(zones, played_rows, limit=8)
            standings_reconciled = not standings_mismatches
            if standings_mismatches:
                warnings.append(
                    "Los marcadores no reconstruyen exactamente la tabla publicada: "
                    + " | ".join(standings_mismatches[:4])
                )
        if expected is not None and finished < expected:
            warnings.append(
                f"La tabla publicada implica {expected} partidos jugados y el dataset explica {finished}."
            )

        # Una agenda que respondió no debe "refrescar" artificialmente la edad de
        # resultados viejos. La snapshot sólo se renueva si hubo marcadores web y,
        # cuando existe tabla de contraste, la cobertura alcanza al menos esa foto.
        save_warning = None
        snapshot_coverage_ok = expected is None or finished >= expected
        if live_results_ok and finished >= base_played and snapshot_coverage_ok:
            save_warning = self._save_snapshot(
                reconciled,
                {
                    "finished_matches": finished,
                    "expected_played_matches": expected,
                    "sources": fa_sources + lpf_sources + ([zones_source] if zones_source else []),
                },
            )
        if save_warning:
            warnings.append(save_warning)

        if dated_finished == finished and finished:
            chronology_basis = "match_date"
        elif dated_finished:
            chronology_basis = "mixed"
        else:
            chronology_basis = "round"

        sources = list(dict.fromkeys(fa_sources + lpf_sources + ([zones_source] if zones_source else [])))
        if not sources:
            sources = list(base.metadata.get("sources") or [])

        metadata = {
            "provider": self.provider_name,
            "sources": sources,
            "opta_required": False,
            "events_available": False,
            "players_available": False,
            "xg_available": False,
            "dates_available": bool(dated_all),
            "dated_matches": dated_all,
            "dated_finished_matches": dated_finished,
            "chronology_basis": chronology_basis,
            "updated_at": self.now().isoformat(),
            "live_fetch_ok": live_ok,
            "live_results_ok": live_results_ok,
            "live_schedule_ok": live_schedule_ok,
            "snapshot_used": snapshot_used,
            "snapshot_age_hours": snapshot_age,
            "expected_played_matches": expected,
            "standings_reconciled": standings_reconciled,
            "standings_mismatches": standings_mismatches,
            "finished_matches": finished,
            "base_finished_matches": base_played,
            "web_finished_matches": live_finished,
            "warnings": warnings,
            "source_errors": fa_errors + lpf_errors + ([zones_error] if zones_error else []),
        }
        return self._records_to_dataset(reconciled, base, metadata)
