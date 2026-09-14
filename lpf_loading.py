"""Preparación pura de cargas de datos LPF.

Este módulo orquesta las transformaciones que ocurren *después* de obtener datos de
una fuente y *antes* de construir el estado canónico. No hace red, no conoce
Streamlit y no persiste nada: recibe estructuras Python simples y devuelve
estructuras simples aptas para una futura API.

La frontera queda así::

    proveedor -> transporte -> adaptador -> lpf_loading -> lpf_state -> motores

El transporte y los adaptadores actuales de ESPN/FutbolArgentino.com viven en
``lpf_http`` y ``lpf_provider_adapters``. Un futuro adaptador Opta sólo deberá
entregar las mismas filas normalizadas de tablas y resultados.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from collections.abc import Mapping, Sequence
from typing import Any

from lpf_clubs import canon_base, canon_club
from lpf_data_2026 import LPF_FIXTURE
from lpf_data_quality import sum_opening_and_zones
from lpf_derive import _lpf_infer_missing_results
from lpf_fixture_sources import expected_played_count
from lpf_reconcile import (
    _lpf_advance_zones_from_confirmed_results,
    _lpf_complete_results_for_zones,
    _lpf_reorder_source_positions,
    _lpf_repair_single_duplicate_in_zones,
    _lpf_results_mismatches,
    _merge_lpf_results,
)
from lpf_state import opening_is_valid

ResultRow = tuple[str, str, int, int]
ZoneTable = Mapping[str, Mapping[str, Mapping[str, object]]]


def results_text(played: Sequence[ResultRow] | None) -> str:
    """Serializa resultados al formato manual histórico de la aplicación."""
    return "\n".join(
        f"{local} {int(gl)}-{int(gv)} {visitor}"
        for local, visitor, gl, gv in (played or [])
    )


def normalize_results_for_zones(
    zones: ZoneTable,
    played: Sequence[tuple[object, object, object, object]] | None,
) -> list[ResultRow]:
    """Canonicaliza resultados y descarta clubes ajenos a las zonas publicadas.

    Esta función es el contrato mínimo que puede reutilizar cualquier proveedor:
    recibe filas ``(local, visitante, goles_local, goles_visitante)`` y devuelve
    identidad canónica LPF, enteros y una sola fila por partido.
    """
    teams = {team for base in (zones or {}).values() for team in (base or {})}
    normalized: list[ResultRow] = []
    for local, visitor, gl, gv in played or []:
        cl, cv = canon_club(local), canon_club(visitor)
        if cl in teams and cv in teams:
            normalized.append((cl, cv, int(gl), int(gv)))
    return _merge_lpf_results(normalized)


def prepare_offline_load(
    zones: ZoneTable,
    *,
    manual_played: Sequence[ResultRow] | None = None,
    previous_played: Sequence[ResultRow] | None = None,
    builtin_played: Sequence[ResultRow] | None = None,
) -> dict[str, Any]:
    """Reconcilia una carga offline sin tocar sesión ni construir el estado final."""
    forward = _merge_lpf_results(
        builtin_played or [], previous_played or [], manual_played or []
    )
    prepared_zones, duplicate_note = _lpf_repair_single_duplicate_in_zones(
        zones, forward
    )
    prepared_zones, reconcile_note = _lpf_advance_zones_from_confirmed_results(
        prepared_zones, forward
    )
    played = _lpf_complete_results_for_zones(
        prepared_zones,
        manual_played or [],
        previous_played or [],
        builtin_played or [],
    ) or _merge_lpf_results(
        previous_played or [], manual_played or [], builtin_played or []
    )
    return {
        "zones": prepared_zones,
        "played": played,
        "results_text": results_text(played),
        "duplicate_repair_note": duplicate_note,
        "standings_reconcile_note": reconcile_note,
    }


def prepare_automatic_update(
    zones: ZoneTable,
    *,
    annual: Mapping[str, Mapping[str, object]] | None = None,
    opening: Mapping[str, Mapping[str, object]] | None = None,
    manual_played: Sequence[ResultRow] | None = None,
    previous_played: Sequence[ResultRow] | None = None,
    builtin_played: Sequence[ResultRow] | None = None,
    futbolargentino_played: Sequence[ResultRow] | None = None,
    espn_played: Sequence[ResultRow] | None = None,
    official_played: Sequence[ResultRow] | None = None,
    fixture: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Prepara la actualización automática a partir de payloads ya obtenidos.

    Conserva la política histórica y agrega la LPF oficial como fuente pública
    prioritaria de marcadores. No
    realiza requests, no lee estado de UI y no guarda snapshots. El resultado puede
    pasarse luego a :func:`lpf_state.build_lpf_state` desde Streamlit o una API.
    """
    fixture = fixture or LPF_FIXTURE
    manual_played = list(manual_played or [])
    previous_played = list(previous_played or [])
    builtin_played = list(builtin_played or [])
    futbolargentino_played = list(futbolargentino_played or [])
    espn_played = list(espn_played or [])
    official_played = list(official_played or [])

    # La colección más nueva gana sólo para hacer avanzar un standings atrasado.
    # Prioridad para avanzar una tabla atrasada: manual > LPF oficial > ESPN > FA.
    # corrección explícita del mismo partido en esta etapa.
    forward_results = _merge_lpf_results(
        builtin_played,
        previous_played,
        futbolargentino_played,
        espn_played,
        official_played,
        manual_played,
    )
    prepared_zones, duplicate_repair_note = _lpf_repair_single_duplicate_in_zones(
        zones, forward_results
    )
    prepared_zones, standings_reconcile_note = _lpf_advance_zones_from_confirmed_results(
        prepared_zones, forward_results
    )
    reconcile_note = standings_reconcile_note or duplicate_repair_note

    reconciled_annual: dict[str, dict[str, int]] = {}
    if reconcile_note:
        normalized_opening = canon_base(opening or {})
        if opening_is_valid(normalized_opening, prepared_zones):
            rebuilt_annual = sum_opening_and_zones(normalized_opening, prepared_zones)
            for team, row in rebuilt_annual.items():
                previous_pos = ((annual or {}).get(team) or {}).get("source_pos")
                if previous_pos is not None:
                    row["source_pos"] = int(previous_pos)
            reconciled_annual = _lpf_reorder_source_positions(rebuilt_annual)

    # Prioridad de la foto completa: manual, LPF oficial, base anterior, incluida,
    # FutbolArgentino.com y ESPN. _lpf_complete_results_for_zones preserva el
    # primer origen cuando dos fuentes discrepan para una misma pareja.
    played = _lpf_complete_results_for_zones(
        prepared_zones,
        manual_played,
        official_played,
        previous_played,
        builtin_played,
        futbolargentino_played,
        espn_played,
    )

    inferred_played: list[ResultRow] = []
    inferred_note = ""
    if not played:
        trusted_baseline = _merge_lpf_results(
            builtin_played, previous_played, official_played, manual_played
        )
        inferred_played, inferred_note = _lpf_infer_missing_results(
            prepared_zones, trusted_baseline, fixture
        )
        if inferred_played:
            played = _lpf_complete_results_for_zones(
                prepared_zones,
                manual_played,
                official_played,
                previous_played,
                builtin_played,
                inferred_played,
                futbolargentino_played,
                espn_played,
            )

    expected_results = expected_played_count(prepared_zones)
    diagnostic_candidates = [
        (
            "base validada + LPF oficial",
            _merge_lpf_results(
                builtin_played,
                previous_played,
                official_played,
                manual_played,
            ),
        ),
        (
            "base validada + FutbolArgentino.com",
            _merge_lpf_results(
                futbolargentino_played,
                builtin_played,
                previous_played,
                manual_played,
            ),
        ),
        (
            "base validada + ESPN",
            _merge_lpf_results(
                espn_played,
                builtin_played,
                previous_played,
                manual_played,
            ),
        ),
    ]
    diagnostic_notes = []
    diagnostic_seen = set()
    for diagnostic_name, diagnostic_played in diagnostic_candidates:
        fingerprint = tuple(sorted(
            (local, visitor, int(gl), int(gv))
            for local, visitor, gl, gv in diagnostic_played
        ))
        # Si dos fuentes aportaron cero o exactamente la misma foto, no repetir
        # el mismo bloque de diferencias con dos rótulos distintos.
        if fingerprint in diagnostic_seen:
            continue
        diagnostic_seen.add(fingerprint)
        diffs = _lpf_results_mismatches(prepared_zones, diagnostic_played, limit=4)
        if diffs:
            diagnostic_notes.append(diagnostic_name + ": " + "; ".join(diffs))

    coverage_note = (
        f"La tabla implica {expected_results if expected_results is not None else '?'} partidos; "
        f"LPF oficial aportó {len(official_played)}, "
        f"FutbolArgentino.com {len(futbolargentino_played)}, "
        f"ESPN {len(espn_played)}, la base anterior {len(previous_played)}, "
        f"la base incluida {len(builtin_played)}"
        + (
            f" y la conciliación determinística {len(inferred_played)}"
            if inferred_played
            else ""
        )
        + "."
    )

    return {
        "zones": prepared_zones,
        "played": played,
        "results_text": results_text(played),
        "reconciled_annual": reconciled_annual,
        "duplicate_repair_note": duplicate_repair_note,
        "standings_reconcile_note": standings_reconcile_note,
        "reconcile_note": reconcile_note,
        "inferred_played": inferred_played,
        "inferred_note": inferred_note,
        "expected_results": expected_results,
        "diagnostic_notes": diagnostic_notes,
        "coverage_note": coverage_note,
    }
