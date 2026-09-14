"""Foto canónica de competencia reutilizable por Streamlit y futuras APIs.

La foto reúne datos ya normalizados/reconciliados en una estructura simple y
serializable. Desde schema 2 también conserva el contexto competitivo necesario
para resolver Playoffs, Libertadores y Sudamericana sin que cada consumidor deba
reconstruir cortes, exclusiones por vía directa o la Tabla Anual reducida.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21
SNAPSHOT_SCHEMA_VERSION = "3"
SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS = ("1", "2", "3")
SNAPSHOT_TRACEABILITY_VERSION = "1"

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from lpf_averages import combine_average_totals, previous_averages_json
from lpf_qualification import allocate_cup_slots
from lpf_state import LPF_APERTURA_PJ, build_lpf_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snapshot_id(snapshot: Mapping[str, object]) -> str:
    """Huella estable del contenido competitivo, independiente de fuente/hora."""
    keys = (
        "competition", "teams", "zones", "annual", "opening", "played", "pending",
        "remaining", "previous_averages", "fixture", "rules", "format",
        "qualification_inputs", "qualification",
    )
    payload = {key: snapshot.get(key) for key in keys}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _coverage(snapshot: Mapping[str, object]) -> dict[str, object]:
    fixture = [row for row in (snapshot.get("fixture") or []) if isinstance(row, Mapping)]
    played = [row for row in (snapshot.get("played") or []) if isinstance(row, Mapping)]
    pending = [row for row in (snapshot.get("pending") or []) if isinstance(row, Mapping)]
    fixture_by_pair = {
        (str(row.get("l", "")), str(row.get("v", ""))): row
        for row in fixture
        if str(row.get("l", "")) and str(row.get("v", ""))
    }
    played_pairs = [
        (str(row.get("home", "")), str(row.get("away", "")))
        for row in played
        if str(row.get("home", "")) and str(row.get("away", ""))
    ]
    played_fixture = [fixture_by_pair[pair] for pair in played_pairs if pair in fixture_by_pair]
    played_rounds = [int(row.get("f", 0) or 0) for row in played_fixture if int(row.get("f", 0) or 0) > 0]
    last_round = max(played_rounds, default=None)
    frontier = []
    if last_round is not None:
        for pair in played_pairs:
            game = fixture_by_pair.get(pair)
            if game is not None and int(game.get("f", 0) or 0) == last_round:
                frontier.append({"round": last_round, "home": pair[0], "away": pair[1]})
    fixture_rounds = [int(row.get("f", 0) or 0) for row in fixture if int(row.get("f", 0) or 0) > 0]
    dated = sum(
        any(row.get(key) not in (None, "") for key in ("date", "datetime", "fecha_hora", "kickoff"))
        for row in fixture
    )
    return {
        "team_count": len(snapshot.get("teams") or []),
        "played_match_count": len(played),
        "pending_match_count": len(pending),
        "fixture_match_count": len(fixture),
        "fixture_through_round": max(fixture_rounds, default=None),
        "last_confirmed_round": last_round,
        "frontier_played_matches": frontier,
        "results_outside_fixture_count": sum(pair not in fixture_by_pair for pair in played_pairs),
        "dated_fixture_match_count": int(dated),
    }


def _quality_summary(report: object) -> dict[str, object]:
    issues = list(getattr(report, "issues", []) or [])
    level = str(getattr(report, "level", "warning") or "warning")
    blocked_domains = sorted(
        str(value) for value in (getattr(report, "blocked_domains", set()) or set())
    )
    return {
        "level": level,
        "complete": level != "blocked",
        "issue_count": len(issues),
        "warning_count": sum(str(getattr(issue, "level", "")) == "warning" for issue in issues),
        "blocked_count": sum(str(getattr(issue, "level", "")) == "blocked" for issue in issues),
        "blocked_domains": blocked_domains,
    }


def _traceability(
    snapshot: Mapping[str, object],
    report: object,
    *,
    provider_name: str,
    provider_contract_version: str | None,
    provenance: Mapping[str, object] | None,
    generated_at: str | None,
) -> dict[str, object]:
    provenance = provenance if isinstance(provenance, Mapping) else {}
    source_updated_at = provenance.get("source_updated_at")
    data_as_of = provenance.get("data_as_of") or source_updated_at
    warnings = [str(value) for value in (provenance.get("warnings") or []) if str(value).strip()]
    if not source_updated_at and not data_as_of:
        message = "El proveedor no informó un timestamp de actualización de la fuente."
        if not any("timestamp" in warning.lower() for warning in warnings):
            warnings.append(message)
    return {
        "traceability_version": SNAPSHOT_TRACEABILITY_VERSION,
        "snapshot_id": _snapshot_id(snapshot),
        "generated_at": str(generated_at or _utc_now()),
        "provider": {
            "name": str(provider_name or "direct"),
            "contract_version": str(provider_contract_version or "") or None,
        },
        "source": {
            "name": str(provenance.get("source_name") or provider_name or "direct"),
            "updated_at": source_updated_at,
            "data_as_of": data_as_of,
            "sources": [str(value) for value in (provenance.get("sources") or []) if str(value).strip()],
            "warnings": warnings,
        },
        "coverage": _coverage(snapshot),
        "quality": _quality_summary(report),
    }


def snapshot_traceability_summary(
    snapshot: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Resumen JSON-safe con edad de la fuente sin mutar el snapshot almacenado."""
    trace = snapshot.get("traceability")
    if not isinstance(trace, Mapping):
        return {
            "available": False,
            "timestamp_known": False,
            "age_hours": None,
            "warning": "El snapshot no contiene trazabilidad.",
        }
    source = trace.get("source") if isinstance(trace.get("source"), Mapping) else {}
    reference = source.get("data_as_of") or source.get("updated_at")
    age_hours: float | None = None
    if reference:
        try:
            parsed = datetime.fromisoformat(str(reference).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            age_hours = round(max(0.0, (current - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0), 2)
        except ValueError:
            age_hours = None
    return {
        "available": True,
        "snapshot_id": trace.get("snapshot_id"),
        "generated_at": trace.get("generated_at"),
        "provider": trace.get("provider"),
        "source": source,
        "coverage": trace.get("coverage"),
        "quality": trace.get("quality"),
        "timestamp_known": bool(reference),
        "reference_at": reference,
        "age_hours": age_hours,
    }


def _average_rows(previous: Mapping[str, object] | None) -> dict[str, dict[str, int]]:
    """Normaliza antecedentes al contrato JSON-safe compartido."""
    return previous_averages_json(previous)


def _clean_sequence(values: Sequence[object] | None, size: int) -> tuple[str, ...]:
    raw = [str(value or "").strip() for value in (values or ())]
    raw = (raw + [""] * size)[:size]
    return tuple(raw)


def _qualification_context(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    annual: Mapping[str, Mapping[str, object]],
    *,
    camps: Sequence[object] = ("", "", ""),
    extras: Sequence[object] = ("", ""),
    copa_replacement: object = "",
    playoff_cutoff: int = 8,
    sudamericana_slots: int = 6,
) -> dict[str, object]:
    """Deriva el universo estable de cada objetivo desde una sola foto canónica."""
    playoff_zones = {
        str(label): {
            "cutoff": min(max(0, int(playoff_cutoff)), len(base)),
            "eligible_teams": list(base),
        }
        for label, base in zones.items()
    }
    playoffs = {
        "available": bool(playoff_zones),
        "kind": "zone",
        "label": "Playoffs",
        "zones": playoff_zones,
    }

    if not annual:
        unavailable = {
            "available": False,
            "kind": "annual_reduced",
            "reason": "No hay una Tabla Anual autoritativa en el snapshot.",
            "eligible_teams": [],
            "direct_qualifiers": [],
            "direct_reasons": {},
            "cutoff": 0,
        }
        return {
            "playoffs": playoffs,
            "libertadores": {**unavailable, "label": "Libertadores por Tabla Anual"},
            "sudamericana": {**unavailable, "label": "Al menos Sudamericana por Tabla Anual"},
        }

    allocation = allocate_cup_slots(
        annual,
        camps=_clean_sequence(camps, 3),
        extras=_clean_sequence(extras, 2),
        copa_replacement=str(copa_replacement or "").strip(),
    )
    eligible = [str(team) for team in allocation.get("reducida", []) if str(team) in annual]
    eligible_set = set(eligible)
    order = [str(team) for team in allocation.get("orden", [])]
    direct = [team for team in order if team not in eligible_set]
    direct_set = set(direct)
    direct_reasons = {
        str(team): str(reason)
        for team, reason in allocation.get("lib", [])
        if str(team) in direct_set
    }
    n_lib = max(0, int(allocation.get("n_tabla_lib") or 0))
    n_sud = max(0, int(sudamericana_slots))
    common = {
        "available": bool(eligible),
        "kind": "annual_reduced",
        "eligible_teams": eligible,
        "direct_qualifiers": direct,
        "direct_reasons": direct_reasons,
        "notices": [str(value) for value in allocation.get("avisos", [])],
    }
    return {
        "playoffs": playoffs,
        "libertadores": {
            **common,
            "label": "Libertadores por Tabla Anual",
            "cutoff": min(n_lib, len(eligible)),
            "table_slots": n_lib,
        },
        "sudamericana": {
            **common,
            "label": "Al menos Sudamericana por Tabla Anual",
            "cutoff": min(n_lib + n_sud, len(eligible)),
            "libertadores_table_slots": n_lib,
            "sudamericana_slots": n_sud,
        },
    }


def build_competition_snapshot(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    played: Sequence[tuple[str, str, int, int]] | None = None,
    annual: Mapping[str, Mapping[str, object]] | None = None,
    opening: Mapping[str, Mapping[str, object]] | None = None,
    previous_averages: Mapping[str, object] | None = None,
    fixture: Sequence[Mapping[str, object]] = (),
    camps: Sequence[object] = ("", "", ""),
    extras: Sequence[object] = ("", ""),
    copa_replacement: object = "",
    annual_relegations: int = 1,
    average_relegations: int = 1,
    opening_rounds: int = LPF_APERTURA_PJ,
    playoff_cutoff: int = 8,
    sudamericana_slots: int = 6,
    provider_name: str = "direct",
    provider_contract_version: str | None = None,
    provenance: Mapping[str, object] | None = None,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], object]:
    """Construye una foto estable a partir del mismo estado que usa la app."""
    clean_camps = _clean_sequence(camps, 3)
    clean_extras = _clean_sequence(extras, 2)
    state, report = build_lpf_state(
        zones,
        played=played,
        annual_direct=annual,
        opening=opening,
        promedios=previous_averages,
        fixture=fixture,
        camps=clean_camps,
        intl=clean_extras,
        n_anual=annual_relegations,
        n_prom=average_relegations,
        copa_arg_reemplazo=str(copa_replacement or "").strip(),
        opening_rounds=int(opening_rounds),
    )
    authoritative_annual = state["anual_directo"]
    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "competition": "LPF 2026",
        "teams": list(state["equipos"]),
        "zones": state["zonas_lpf"],
        "annual": authoritative_annual,
        "opening": state["apertura"],
        "played": [
            {"home": h, "away": a, "home_goals": int(gh), "away_goals": int(ga)}
            for h, a, gh, ga in state["jugados"]
        ],
        "pending": [
            {"home": h, "away": a}
            for h, a in state["pendientes"]
        ],
        "remaining": {team: int(value) for team, value in state["rest"].items()},
        "previous_averages": _average_rows(state.get("promedios") or previous_averages),
        "fixture": [dict(game) for game in fixture],
        "rules": {
            "annual_relegations": int(state["n_anual"]),
            "average_relegations": int(state["n_prom"]),
        },
        "format": {
            "opening_rounds": int(opening_rounds),
            "playoff_cutoff": int(playoff_cutoff),
            "sudamericana_slots": int(sudamericana_slots),
        },
        "qualification_inputs": {
            "champions": {
                "apertura": clean_camps[0],
                "clausura": clean_camps[1],
                "copa_argentina": clean_camps[2],
            },
            "international_champions": {
                "libertadores": clean_extras[0],
                "sudamericana": clean_extras[1],
            },
            "copa_argentina_replacement": str(copa_replacement or "").strip(),
        },
        "qualification": _qualification_context(
            state["zonas_lpf"],
            authoritative_annual,
            camps=clean_camps,
            extras=clean_extras,
            copa_replacement=copa_replacement,
            playoff_cutoff=int(playoff_cutoff),
            sudamericana_slots=int(sudamericana_slots),
        ),
    }
    snapshot["traceability"] = _traceability(
        snapshot,
        report,
        provider_name=provider_name,
        provider_contract_version=provider_contract_version,
        provenance=provenance,
        generated_at=generated_at,
    )
    return snapshot, report


def _pending_pairs(snapshot: Mapping[str, object]) -> tuple[Mapping[str, int], list[tuple[str, str]]]:
    remaining = snapshot.get("remaining")
    pending_raw = snapshot.get("pending")
    if not isinstance(remaining, Mapping) or not isinstance(pending_raw, Sequence):
        raise ValueError("snapshot incompleto")
    pending: list[tuple[str, str]] = []
    for row in pending_raw:
        if not isinstance(row, Mapping):
            continue
        home, away = str(row.get("home", "")), str(row.get("away", ""))
        if home and away:
            pending.append((home, away))
    return remaining, pending


def snapshot_scope(
    snapshot: Mapping[str, object],
    scope: str,
    *,
    zone: str | None = None,
) -> tuple[Mapping[str, object], Mapping[str, int], list[tuple[str, str]]]:
    """Devuelve base, partidos restantes y conteos para una consulta del snapshot."""
    remaining, pending = _pending_pairs(snapshot)

    if scope == "annual":
        base = snapshot.get("annual")
        if not isinstance(base, Mapping):
            raise ValueError("snapshot sin Tabla Anual")
        return base, remaining, pending

    if scope == "zone":
        zones = snapshot.get("zones")
        if not isinstance(zones, Mapping) or zone not in zones:
            raise ValueError("zona inexistente")
        base = zones[zone]
        if not isinstance(base, Mapping):
            raise ValueError("zona inválida")
        pool = set(base)
        matches = [(h, a) for h, a in pending if h in pool or a in pool]
        return base, remaining, matches

    raise ValueError("scope inválido")


def normalize_objective(objective: object) -> str:
    """Normaliza aliases editoriales del contrato a tres objetivos matemáticos."""
    key = str(objective or "").strip().lower().replace("á", "a")
    key = key.replace(" ", "_")
    aliases = {
        "playoff": "playoffs",
        "playoffs": "playoffs",
        "libertadores": "libertadores",
        "copa_libertadores": "libertadores",
        "sudamericana": "sudamericana",
        "al_menos_sudamericana": "sudamericana",
        "copa_sudamericana": "sudamericana",
    }
    if key not in aliases:
        raise ValueError("objetivo inválido")
    return aliases[key]


def snapshot_objective_scope(
    snapshot: Mapping[str, object],
    objective: object,
    *,
    zone: str | None = None,
) -> tuple[Mapping[str, object], Mapping[str, int], list[tuple[str, str]], int, Mapping[str, object]]:
    """Resuelve base y corte de un objetivo sin parámetros duplicados del cliente."""
    key = normalize_objective(objective)
    qualification = snapshot.get("qualification")
    if not isinstance(qualification, Mapping):
        raise ValueError("snapshot sin contexto de clasificación")
    context = qualification.get(key)
    if not isinstance(context, Mapping):
        raise ValueError("snapshot sin contexto para el objetivo")
    if not bool(context.get("available")):
        raise ValueError(str(context.get("reason") or "objetivo no disponible en el snapshot"))

    remaining, pending = _pending_pairs(snapshot)
    if key == "playoffs":
        zones = snapshot.get("zones")
        by_zone = context.get("zones")
        if not isinstance(zones, Mapping) or not isinstance(by_zone, Mapping):
            raise ValueError("snapshot sin zonas de playoffs")
        selected = str(zone or "").strip()
        if not selected:
            raise ValueError("falta indicar la zona para playoffs")
        base = zones.get(selected)
        zctx = by_zone.get(selected)
        if not isinstance(base, Mapping) or not isinstance(zctx, Mapping):
            raise ValueError("zona inexistente")
        cutoff = int(zctx.get("cutoff", 0) or 0)
        pool = set(base)
        matches = [(h, a) for h, a in pending if h in pool or a in pool]
        meta = {**dict(context), "zone": selected, "cutoff": cutoff}
        return base, remaining, matches, cutoff, meta

    annual = snapshot.get("annual")
    eligible = context.get("eligible_teams")
    if not isinstance(annual, Mapping) or not isinstance(eligible, Sequence) or isinstance(eligible, (str, bytes)):
        raise ValueError("snapshot sin Tabla Anual reducida")
    base = {str(team): annual[str(team)] for team in eligible if str(team) in annual}
    cutoff = int(context.get("cutoff", 0) or 0)
    pool = set(base)
    matches = [(h, a) for h, a in pending if h in pool or a in pool]
    return base, remaining, matches, cutoff, context


def snapshot_average_totals(snapshot: Mapping[str, object]) -> dict[str, tuple[int, int]] | None:
    """Totales de promedios listos para ``piso_no_descenso``."""
    annual = snapshot.get("annual")
    zones = snapshot.get("zones")
    previous = snapshot.get("previous_averages")
    if not isinstance(annual, Mapping) or not isinstance(zones, Mapping) or not isinstance(previous, Mapping):
        return None
    return combine_average_totals(annual, previous, zones=zones)
