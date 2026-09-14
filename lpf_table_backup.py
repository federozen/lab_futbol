"""Persistencia y recuperación del último respaldo válido de tablas LPF.

Esta capa conoce JSON y filesystem, pero no Streamlit ni proveedores externos. La
UI puede conservar una copia adicional en sesión y una futura API puede elegir otro
path o incluso reutilizar sólo las funciones de serialización/validación.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

from lpf_clubs import canon_base
from lpf_reconcile import _validate_lpf_tables
from lpf_text import _fmt_num_es

LPF_RUNTIME_API = 21

TABLE_BACKUP_SCHEMA = 1
DEFAULT_MAX_AGE_HOURS = 168


def table_backup_path(base_dir: str | Path | None = None) -> Path:
    """Devuelve el path del respaldo, respetando ``LPF_SNAPSHOT_PATH``."""
    override = str(os.environ.get("LPF_SNAPSHOT_PATH", "") or "").strip()
    if override:
        return Path(override)
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
    return root / "data" / "lpf_last_valid.json"


def _plain_base(base: Mapping[str, Mapping[str, Any]] | None) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for team, stats in (base or {}).items():
        row = {
            key: int((stats or {}).get(key, 0))
            for key in ("pts", "pj", "dg", "gf", "ga")
        }
        if (stats or {}).get("source_pos") is not None:
            row["source_pos"] = int((stats or {}).get("source_pos"))
        out[str(team)] = row
    return out


def build_table_backup(
    zones: Mapping[str, Mapping[str, Mapping[str, Any]]],
    annual: Mapping[str, Mapping[str, Any]],
    source_name: str,
    *,
    updated_at: str | None = None,
) -> dict[str, object]:
    """Construye el JSON del último respaldo válido y valida antes de serializar."""
    _validate_lpf_tables(zones, annual)
    return {
        "schema": TABLE_BACKUP_SCHEMA,
        "competition": "LPF Clausura 2026",
        "source": str(source_name or "fuente automática"),
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "zones": {label: _plain_base(base) for label, base in zones.items()},
        "annual": _plain_base(annual),
    }


def write_table_backup(payload: Mapping[str, object], path: str | Path | None = None) -> None:
    """Escribe el respaldo de forma atómica. No captura errores de filesystem."""
    target = Path(path) if path is not None else table_backup_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def read_table_backup(path: str | Path | None = None) -> dict[str, object]:
    """Lee un payload de respaldo desde disco."""
    target = Path(path) if path is not None else table_backup_path()
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("el respaldo no contiene un objeto JSON")
    return raw


def table_backup_candidates(
    *,
    session_payload: Mapping[str, object] | None = None,
    path: str | Path | None = None,
) -> list[tuple[str, Mapping[str, object]]]:
    """Devuelve candidatos en la misma prioridad histórica: sesión y luego disco."""
    candidates: list[tuple[str, Mapping[str, object]]] = []
    if isinstance(session_payload, Mapping):
        candidates.append(("sesión", session_payload))
    try:
        target = Path(path) if path is not None else table_backup_path()
        if target.exists():
            payload = read_table_backup(target)
            candidates.append(("disco", payload))
    except Exception:
        # Compatibilidad histórica: un JSON ilegible en disco se ignora aquí. La
        # copia de sesión puede seguir siendo válida y la carga no debe bloquearse.
        pass
    return candidates


def _norm_label(value: object) -> str:
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


def _decode_table_backup(
    payload: Mapping[str, object],
) -> tuple[dict[str, dict[str, dict[str, int]]], dict[str, dict[str, int]], str]:
    raw_zones = payload.get("zones") or payload.get("zonas") or {}
    if not raw_zones:
        raw_zones = {
            key: payload.get(key)
            for key in ("A", "B", "Zona A", "Zona B", "zone_a", "zone_b")
            if isinstance(payload.get(key), Mapping)
        }

    zones: dict[str, dict[str, dict[str, int]]] = {}
    if isinstance(raw_zones, Mapping):
        for raw_label, base in raw_zones.items():
            label_norm = _norm_label(raw_label).replace("_", " ")
            if label_norm in {"a", "zona a", "zone a"}:
                label = "A"
            elif label_norm in {"b", "zona b", "zone b"}:
                label = "B"
            else:
                continue
            if isinstance(base, Mapping):
                zones[label] = canon_base(base)

    annual_raw = (
        payload.get("annual")
        or payload.get("anual")
        or payload.get("tabla_anual")
        or payload.get("tabla general")
        or {}
    )
    annual = canon_base(annual_raw if isinstance(annual_raw, Mapping) else {})
    _validate_lpf_tables(zones, annual)
    source = str(payload.get("source") or "fuente desconocida")
    return zones, annual, source


def select_valid_table_backup(
    candidates: Iterable[tuple[str, Mapping[str, object]]],
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> tuple[
    dict[str, dict[str, dict[str, int]]],
    dict[str, dict[str, int]],
    str,
    float | None,
    str | None,
]:
    """Elige el primer respaldo válido y suficientemente reciente."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    errors: list[str] = []
    for location, payload in candidates:
        try:
            updated = datetime.fromisoformat(str(payload.get("updated_at", "")).replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_hours = max(0.0, (current - updated).total_seconds() / 3600.0)
            if age_hours > float(max_age_hours):
                errors.append(
                    f"respaldo de {location} demasiado viejo ({_fmt_num_es(age_hours / 24, 1)} días)"
                )
                continue
            zones, annual, source = _decode_table_backup(payload)
            return zones, annual, source, age_hours, None
        except Exception as exc:
            errors.append(f"respaldo de {location} inválido: {exc}")

    error = " | ".join(errors) if errors else "no existe un respaldo válido"
    return {}, {}, "", None, error


def load_table_backup(
    *,
    session_payload: Mapping[str, object] | None = None,
    path: str | Path | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
):
    """Recupera el último respaldo válido desde sesión/disco sin conocer Streamlit."""
    return select_valid_table_backup(
        table_backup_candidates(session_payload=session_payload, path=path),
        max_age_hours=max_age_hours,
        now=now,
    )
