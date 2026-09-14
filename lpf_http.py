"""Transporte HTTP para las fuentes publicas usadas por la calculadora.

Este modulo hace solamente red: no parsea tablas, no conoce el estado LPF y no
importa Streamlit. La UI puede envolver estas funciones con su cache; una futura
API puede reutilizarlas o reemplazarlas por otro transporte sin tocar los parsers
ni los motores.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


import datetime as _dt
import time
from collections.abc import Callable
from typing import Any

import requests


def source_headers(referer: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def fetch_url_text(url: str, *, timeout: int = 30) -> str:
    """Descarga texto con el comportamiento historico de las URLs genericas.

    No valida status HTTP ni interpreta el contenido: los wrappers de UI conservan
    sus mensajes de error y delegan el parsing en un adaptador puro.
    """
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    return response.text


def fetch_html(url: str, *, referer: str = "", timeout: int = 30, retries: int = 1) -> tuple[str, str]:
    """Descarga HTML y devuelve ``(texto, url_final)`` con los errores historicos."""
    last_error: Exception | None = None
    for attempt in range(int(retries) + 1):
        try:
            response = requests.get(
                url,
                headers=source_headers(referer),
                timeout=timeout,
                allow_redirects=True,
            )
            if response.status_code == 200:
                text = response.text or ""
                if len(text.strip()) < 500:
                    raise RuntimeError(
                        f"respondió HTTP 200, pero entregó sólo {len(text)} caracteres"
                    )
                return text, response.url
            raise RuntimeError(
                f"respondió HTTP {response.status_code} en {response.url}"
            )
        except Exception as exc:
            last_error = exc
            if attempt < int(retries):
                time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(str(last_error or "no se pudo descargar la página"))


def fetch_futbolargentino_results_pages(
    source_urls: list[str] | tuple[str, ...],
    *,
    referer: str = "",
    timeout: int = 30,
    get_html: Callable[..., tuple[str, str]] | None = None,
    timestamp: int | None = None,
) -> dict[str, Any]:
    """Descarga las paginas de resultados usadas por FutbolArgentino.com.

    Replica la orquestacion historica del wrapper Streamlit: agrega un cache-buster
    distinto por URL y conserva cada fallo junto a la fuente correspondiente. No
    interpreta HTML ni decide si la cobertura de partidos es suficiente.

    ``get_html`` permite que la UI mantenga su cache (`_standings_html_get`) y que
    una futura API use :func:`fetch_html` directamente.
    """
    getter = get_html or fetch_html
    stamp = int(time.time()) if timestamp is None else int(timestamp)
    attempts: list[dict[str, Any]] = []

    for index, raw_url in enumerate(source_urls or ()):
        source_url = str(raw_url or "").strip()
        if not source_url:
            continue
        separator = "&" if "?" in source_url else "?"
        request_url = f"{source_url}{separator}_lpf_refresh={stamp + index}"
        try:
            html, final_url = getter(
                request_url,
                referer=referer,
                timeout=timeout,
            )
        except Exception as exc:
            attempts.append(
                {
                    "source_url": source_url,
                    "request_url": request_url,
                    "html": "",
                    "final_url": "",
                    "error": str(exc),
                }
            )
            continue
        attempts.append(
            {
                "source_url": source_url,
                "request_url": request_url,
                "html": html,
                "final_url": final_url,
                "error": "",
            }
        )

    return {"attempts": attempts, "timestamp": stamp}


def fetch_espn_json(url: str, *, timeout: int = 30, retries: int = 2) -> dict[str, Any]:
    """Consulta ESPN y devuelve JSON, sin cache ni efectos sobre la aplicacion."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
        "Referer": "https://www.espn.com.ar/",
        "Cache-Control": "no-cache",
    }

    retryable_statuses = {429, 500, 502, 503, 504}
    last_error: str | None = None

    for attempt in range(int(retries) + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            last_error = (
                f"Error de red al consultar ESPN en {url}: "
                f"{exc.__class__.__name__}: {exc}"
            )
        else:
            if "/standings" in url:
                kind = "tabla de posiciones"
            elif "/scoreboard" in url:
                kind = "fixture/resultados"
            else:
                kind = "datos"

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"ESPN respondió en {response.url}, pero la respuesta "
                        f"de {kind} no era JSON válido: {exc}"
                    ) from exc
                return payload

            message = (
                f"{kind}: ESPN respondió HTTP {response.status_code} "
                f"en {response.url}"
            )
            if response.status_code == 403:
                raise RuntimeError(
                    f"{message}. ESPN rechazó la solicitud automática. "
                    "Puede estar bloqueando la IP del servidor."
                )
            if response.status_code not in retryable_statuses:
                raise RuntimeError(message)
            last_error = message

        if attempt < int(retries):
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(last_error or f"No se pudo consultar ESPN en {url}")

def _scoreboard_date(value: object) -> _dt.date | None:
    """Normaliza una fecha aceptada por el wrapper historico de ESPN."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return _dt.datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def fetch_espn_scoreboard_window(
    liga: str,
    *,
    dias: int = 120,
    timeout: int = 30,
    max_req: int = 30,
    desde: object = None,
    get_json: Callable[..., dict[str, Any]] | None = None,
    today: _dt.date | None = None,
) -> dict[str, Any]:
    """Descarga la ventana de scoreboards que historicamente armaba Streamlit.

    La funcion hace solo orquestacion de transporte: no interpreta eventos ni
    persiste estado. ``get_json`` permite que Streamlit conserve su cache
    (`_espn_get`) y que una futura API use ``fetch_espn_json`` directamente.
    """
    lg = str(liga or "").strip()
    if not lg:
        raise ValueError("Indicá el código de liga.")

    getter = get_json or fetch_espn_json
    current = today or _dt.date.today()
    end_date = current + _dt.timedelta(days=max(0, int(dias)))

    start_date = _scoreboard_date(desde)
    if start_date is None:
        start_date = _dt.date(2026, 7, 1) if lg == "arg.1" else current - _dt.timedelta(days=30)
    if start_date > end_date:
        start_date = current

    head_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard"
    head_payload = getter(head_url, timeout=timeout)
    payloads = [head_payload]

    chunk_days = 21
    cursor = start_date
    requests_used = 0
    failed_chunks = 0
    request_limit = max(1, int(max_req))
    while cursor <= end_date and requests_used < request_limit:
        chunk_end = min(cursor + _dt.timedelta(days=chunk_days - 1), end_date)
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard"
            f"?dates={cursor:%Y%m%d}-{chunk_end:%Y%m%d}"
        )
        try:
            payloads.append(getter(url, timeout=timeout))
        except Exception:
            failed_chunks += 1
        requests_used += 1
        cursor = chunk_end + _dt.timedelta(days=1)

    return {
        "payloads": payloads,
        "start_date": start_date,
        "end_date": end_date,
        "requests": requests_used,
        "failed_chunks": failed_chunks,
        "limited": cursor <= end_date,
    }



def fetch_html_pages(
    source_urls: list[str] | tuple[str, ...],
    *,
    referer: str = "",
    timeout: int = 30,
    get_html: Callable[..., tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Descarga una lista acotada de páginas HTML conservando fallos por URL.

    Es transporte puro y se usa para la fuente oficial LPF: la capa superior decide
    qué links son notas de resultados y cómo parsearlas. ``get_html`` permite a la UI
    reutilizar su cache sin acoplar Streamlit a este módulo.
    """
    getter = get_html or fetch_html
    attempts: list[dict[str, Any]] = []
    for raw_url in source_urls or ():
        source_url = str(raw_url or "").strip()
        if not source_url:
            continue
        try:
            html, final_url = getter(
                source_url,
                referer=referer,
                timeout=timeout,
            )
        except Exception as exc:
            attempts.append({
                "source_url": source_url,
                "html": "",
                "final_url": "",
                "error": str(exc),
            })
            continue
        attempts.append({
            "source_url": source_url,
            "html": html,
            "final_url": final_url,
            "error": "",
        })
    return {"attempts": attempts}
