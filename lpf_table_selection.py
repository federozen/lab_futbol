"""Política pura de selección de tablas LPF entre fuentes y respaldos.

Recibe candidatos ya descargados/parseados y decide qué zonas y Tabla Anual usar.
No hace red, no lee disco ni sesión y no persiste nada. Esa separación permite que
Streamlit, una futura API u otro proveedor (por ejemplo Opta) reutilicen exactamente
la misma prioridad de fuentes.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from lpf_clubs import canon_base
from lpf_reconcile import _validate_lpf_tables
from lpf_text import _fmt_num_es

LPF_RUNTIME_API = 21


def select_lpf_tables(
    *,
    espn_zones: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    espn_error: str | None = None,
    fa_zones: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    fa_zones_error: str | None = None,
    fa_annual: Mapping[str, Mapping[str, Any]] | None = None,
    fa_annual_error: str | None = None,
    snapshot_zones: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    snapshot_annual: Mapping[str, Mapping[str, Any]] | None = None,
    snapshot_source: str = "",
    snapshot_age_hours: float | None = None,
    snapshot_error: str | None = None,
    annual_fallbacks: Iterable[tuple[str, Mapping[str, Mapping[str, Any]]]] = (),
) -> dict[str, Any]:
    """Selecciona zonas/Anual preservando la prioridad histórica de la app.

    Prioridad de zonas: ESPN -> FutbolArgentino.com -> última foto válida.
    Con zonas frescas, la Anual prioriza FutbolArgentino.com -> Anual de la última
    foto -> candidatos locales (sesión / incluida en la app).

    Devuelve un dict JSON-friendly con la selección, advertencias, error y una
    bandera ``save_snapshot`` para que la capa de I/O decida si persiste la foto.
    """
    warnings: list[str] = []
    errors: list[str] = []

    espn_zones = dict(espn_zones or {})
    fa_zones = dict(fa_zones or {})
    fa_annual = dict(fa_annual or {})
    snapshot_zones = dict(snapshot_zones or {})
    snapshot_annual = dict(snapshot_annual or {})

    if espn_error:
        errors.append(str(espn_error))
        espn_zones = {}
    elif espn_zones:
        try:
            _validate_lpf_tables(espn_zones)
        except Exception as exc:
            errors.append(f"ESPN devolvió una tabla inválida: {exc}")
            espn_zones = {}

    if fa_zones_error:
        errors.append(f"FutbolArgentino.com (zonas): {fa_zones_error}")
    if fa_annual_error:
        errors.append(f"FutbolArgentino.com (Anual): {fa_annual_error}")

    zones = espn_zones or fa_zones
    zones_source = "ESPN" if espn_zones else ("FutbolArgentino.com" if fa_zones else "")

    if zones:
        annual = fa_annual
        annual_source = "FutbolArgentino.com" if annual else ""

        if not annual and snapshot_annual:
            try:
                _validate_lpf_tables(zones, snapshot_annual)
                annual = snapshot_annual
                annual_source = f"último respaldo ({snapshot_source})"
                warnings.append(
                    "La Tabla Anual no pudo actualizarse; uso la última válida "
                    f"de hace {_fmt_num_es(snapshot_age_hours, 1)} horas."
                )
            except Exception:
                annual = {}

        if not annual:
            for label, candidate in annual_fallbacks:
                candidate = canon_base(candidate or {})
                try:
                    _validate_lpf_tables(zones, candidate)
                except Exception:
                    continue
                annual = candidate
                annual_source = str(label)
                warnings.append(
                    f"La Tabla Anual no pudo actualizarse; uso {annual_source.lower()}."
                )
                break

        if annual:
            _validate_lpf_tables(zones, annual)
            source_name = zones_source
            if annual_source and annual_source != zones_source:
                source_name = f"{zones_source} (zonas) + {annual_source} (Anual)"
            if zones_source == "FutbolArgentino.com" and espn_error:
                warnings.append("ESPN rechazó las posiciones; se usó el respaldo automático.")
            return {
                "zones": zones,
                "annual": annual,
                "source_name": source_name,
                "warnings": warnings,
                "error": None,
                # Igual que el comportamiento previo: sólo una Anual fresca de FA
                # habilita a sobrescribir la última foto válida.
                "save_snapshot": bool(fa_annual),
            }

        warnings.append(
            "Las zonas se actualizaron, pero no hay una Tabla Anual válida; "
            "las cuentas de copas pueden quedar bloqueadas."
        )
        return {
            "zones": zones,
            "annual": {},
            "source_name": zones_source,
            "warnings": warnings,
            "error": None,
            "save_snapshot": False,
        }

    if snapshot_zones:
        warnings.append(
            "No pude consultar las fuentes ahora. Uso la última foto válida "
            f"({snapshot_source}), guardada hace {_fmt_num_es(snapshot_age_hours, 1)} horas."
        )
        return {
            "zones": snapshot_zones,
            "annual": snapshot_annual,
            "source_name": f"Último respaldo válido · {snapshot_source}",
            "warnings": warnings,
            "error": None,
            "save_snapshot": False,
        }

    if snapshot_error:
        errors.append(f"Último respaldo: {snapshot_error}")
    return {
        "zones": {},
        "annual": {},
        "source_name": "",
        "warnings": warnings,
        "error": "No pude obtener las zonas automáticamente. " + " | ".join(errors),
        "save_snapshot": False,
    }
