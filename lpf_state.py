"""Construcción pura del estado canónico de la LPF.

Este módulo es la frontera entre datos ya normalizados/reconciliados y los
consumidores del cálculo. No conoce Streamlit ni proveedores de red: recibe
estructuras Python simples y devuelve un estado serializable junto con su
reporte de calidad.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from collections.abc import Mapping, Sequence
from typing import Any

from lpf_clubs import canon_base
from lpf_data_quality import (
    build_quality_report,
    derive_opening_from_results,
    derive_opening_snapshot,
    flatten_zones,
    pending_pairs,
    sum_opening_and_zones,
)
from lpf_models import AuditIssue, DataQualityReport

LPF_APERTURA_PJ = 16


def opening_is_valid(
    opening: Mapping[str, Mapping[str, object]] | None,
    zones: Mapping[str, Mapping[str, Mapping[str, object]]] | None = None,
    *,
    opening_rounds: int = LPF_APERTURA_PJ,
) -> bool:
    """Valida una foto fija de Apertura contra la nómina y sus rangos básicos."""
    normalized = canon_base(opening or {})
    if not normalized:
        return False
    if zones:
        teams = {team for base in zones.values() for team in base}
        if set(normalized) != teams:
            return False
    return all(
        int(row.get("pj", -1)) == int(opening_rounds)
        and 0 <= int(row.get("pts", -1)) <= 3 * int(opening_rounds)
        and int(row.get("gf", 0)) >= 0
        and int(row.get("ga", 0)) >= 0
        for row in normalized.values()
    )


def add_source_issues(
    report: DataQualityReport,
    messages: Sequence[object] | None,
) -> DataQualityReport:
    """Agrega a la auditoría conflictos de procedencia ya detectados por la UI."""
    existing = {(issue.code, issue.message) for issue in report.issues}
    for raw_message in messages or []:
        message = str(raw_message)
        blocked = message.startswith("BLOQUEO:")
        key = ("prom_source_sync", message)
        if key in existing:
            continue
        report.issues.append(
            AuditIssue(
                "prom_source_sync",
                message,
                "blocked" if blocked else "warning",
                "promedios",
                suggestion="Pegá Tabla Anual y Promedios de la misma actualización.",
            )
        )
    report.level = (
        "blocked"
        if any(issue.level == "blocked" for issue in report.issues)
        else "warning"
        if report.issues
        else "ok"
    )
    return report



def refresh_lpf_quality_state(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    annual_imported: Mapping[str, Mapping[str, object]] | None = None,
    annual_direct: Mapping[str, Mapping[str, object]] | None = None,
    opening_candidates: Sequence[Mapping[str, Mapping[str, object]] | None] = (),
    promedios: Mapping[str, object] | None = None,
    fixture: Sequence[Mapping[str, object]] = (),
    played: Sequence[tuple[str, str, int, int]] | None = None,
    source_issues: Sequence[object] | None = None,
    opening_rounds: int = LPF_APERTURA_PJ,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]], DataQualityReport]:
    """Revalida una foto LPF existente sin leer ni escribir estado de interfaz.

    Reproduce la migración defensiva usada por Streamlit para sesiones guardadas por
    versiones anteriores: elige el primer Apertura válido, reconstruye la Anual viva
    cuando ese Apertura existe y vuelve a emitir la auditoría completa. No intenta
    derivar un Apertura nuevo; esa responsabilidad sigue en ``build_lpf_state``.
    """
    candidates = [canon_base(candidate or {}) for candidate in opening_candidates]
    selected_opening = next(
        (
            candidate
            for candidate in candidates
            if opening_is_valid(
                candidate,
                zones,
                opening_rounds=opening_rounds,
            )
        ),
        {},
    )

    if selected_opening:
        authoritative = sum_opening_and_zones(selected_opening, zones)
    else:
        authoritative = dict(annual_direct or {})

    report = build_quality_report(
        zones or {},
        annual_imported or authoritative,
        promedios or {},
        fixture,
        list(played or []),
        opening_snapshot=selected_opening,
    )
    report = add_source_issues(report, source_issues)
    return selected_opening, authoritative, report

def build_lpf_state(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    played: Sequence[tuple[str, str, int, int]] | None = None,
    annual_direct: Mapping[str, Mapping[str, object]] | None = None,
    opening: Mapping[str, Mapping[str, object]] | None = None,
    stored_opening: Mapping[str, Mapping[str, object]] | None = None,
    builtin_opening: Mapping[str, Mapping[str, object]] | None = None,
    promedios: Mapping[str, object] | None = None,
    fixture: Sequence[Mapping[str, object]] = (),
    source_issues: Sequence[object] | None = None,
    camps: Sequence[str] | None = None,
    intl: Sequence[str] | None = None,
    n_anual: int = 1,
    n_prom: int = 1,
    copa_arg_vivos: Sequence[str] | None = None,
    copa_arg_updated: str = "",
    copa_arg_source: str = "",
    copa_arg_reemplazo: str = "",
    opening_rounds: int = LPF_APERTURA_PJ,
) -> tuple[dict[str, Any], DataQualityReport]:
    """Construye una foto LPF coherente sin leer ni escribir estado de interfaz.

    Prioridad de verdad:
    1) resultados explícitos para identificar partidos jugados;
    2) Apertura fijo + zonas actuales para la Tabla Anual;
    3) Tabla Anual directa sólo si pasa todos los controles.

    Todo argumento es una estructura Python simple para que la misma función pueda
    ser consumida por Streamlit o, más adelante, por una API.
    """
    normalized_zones = {
        label: canon_base(base) for label, base in (zones or {}).items()
    }
    normalized_played = list(played or [])
    normalized_annual = canon_base(annual_direct or {})

    candidates = [
        canon_base(opening or {}),
        canon_base(stored_opening or {}),
        canon_base(builtin_opening or {}),
    ]
    selected_opening = next(
        (
            candidate
            for candidate in candidates
            if opening_is_valid(
                candidate,
                normalized_zones,
                opening_rounds=opening_rounds,
            )
        ),
        {},
    )

    # Respaldo para otras ediciones o para una foto importada por el usuario.
    if not selected_opening and normalized_annual:
        selected_opening, _opening_issues = derive_opening_snapshot(
            normalized_annual,
            normalized_zones,
            opening_rounds=opening_rounds,
        )
        if not selected_opening:
            selected_opening, _opening_issues = derive_opening_from_results(
                normalized_annual,
                fixture,
                normalized_played,
                opening_rounds=opening_rounds,
            )
        if not opening_is_valid(
            selected_opening,
            normalized_zones,
            opening_rounds=opening_rounds,
        ):
            selected_opening = {}

    report = build_quality_report(
        normalized_zones,
        normalized_annual,
        promedios or {},
        fixture,
        normalized_played,
        opening_snapshot=selected_opening,
    )
    report = add_source_issues(report, source_issues)

    authoritative = report.authoritative_annual or {}
    for team, row in authoritative.items():
        source_pos = (normalized_annual.get(team) or {}).get("source_pos")
        if source_pos is not None:
            row["source_pos"] = int(source_pos)
    if report.opening_snapshot:
        selected_opening = report.opening_snapshot

    pending = pending_pairs(report.match_records)
    rest = {team: 0 for team in flatten_zones(normalized_zones)}
    for local, visitor in pending:
        if local in rest:
            rest[local] += 1
        if visitor in rest:
            rest[visitor] += 1
    teams = [team for base in normalized_zones.values() for team in base]

    state = dict(
        modo="lpf2026",
        equipos=teams,
        zonas_lpf=normalized_zones,
        anual_directo=authoritative,
        anual_importada=normalized_annual,
        apertura=selected_opening,
        pendientes=pending,
        rest=rest,
        camps=camps or (),
        intl=intl or (),
        n_anual=int(n_anual),
        n_prom=int(n_prom),
        copa_arg_vivos=list(copa_arg_vivos or []),
        copa_arg_updated=str(copa_arg_updated or ""),
        copa_arg_source=str(copa_arg_source or ""),
        copa_arg_reemplazo=str(copa_arg_reemplazo or ""),
        promedios=dict(promedios or {}),
        base={},
        jugados=normalized_played,
        esc=None,
        mg=0,
        solo_puntos=True,
        data_quality=report,
    )
    return state, report
