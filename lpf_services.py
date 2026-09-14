"""Fachada pura y JSON-safe para exponer cálculos LPF.

Este módulo no es una API HTTP. Es la frontera de aplicación que una API futura
puede invocar sin importar Streamlit, requests ni detalles de proveedores. Recibe
diccionarios/listas compatibles con JSON, valida lo mínimo necesario y delega toda
la matemática en los motores existentes.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass

from lpf_competitive_context import competition_context
from lpf_data_provider import (
    DATA_PROVIDER_CONTRACT_VERSION,
    SUPPORTED_DATA_PROVIDER_CONTRACT_VERSIONS,
)
from lpf_editorial_definition import definition_snapshot
from lpf_form import estimate_team_strength
from lpf_pisos import VENTANA_EXACTA, piso_no_descenso, piso_por_corte
from lpf_preview import team_preview_text
from lpf_relegation import current_relegation_picture
from lpf_scenarios import point_ladder, scenario_rank_bounds
from lpf_schedule import build_schedule_map, current_round, match_round, resolve_scope_games
from lpf_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    SNAPSHOT_TRACEABILITY_VERSION,
    SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS,
    build_competition_snapshot,
    normalize_objective,
    snapshot_average_totals,
    snapshot_objective_scope,
    snapshot_scope,
    snapshot_traceability_summary,
)
from lpf_standings import DEFAULT_CRITERIOS, _orden
from lpf_version import __version__

CONTRACT_VERSION = "1"
SUPPORTED_QUERY_TYPES = ("objective_points", "objective_status", "point_ladder", "rank_window", "definition", "descent_points")
PUBLIC_SERVICE_VERSION = "1"
PUBLIC_OPERATIONS = (
    "standings",
    "preview",
    "objective_points",
    "objective_chances",
    "definition",
    "relegation",
    "competition_batch",
)


class ContractError(ValueError):
    """Error de entrada estable para que una interfaz pueda mapearlo a su protocolo."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = str(code)
        self.field = field

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.field:
            out["field"] = self.field
        return out


def _envelope(calculation: str, result: object) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "calculation_version": __version__,
        "calculation": calculation,
        "result": _json_safe(result),
    }


def _json_safe(value: object) -> object:
    """Convierte dataclasses/tuplas/set en estructuras serializables por ``json``."""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _mapping(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ContractError("invalid_payload", "El payload debe ser un objeto JSON.")
    return payload


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = str(payload.get(field, "") or "").strip()
    if not value:
        raise ContractError("missing_field", f"Falta el campo obligatorio '{field}'.", field=field)
    return value


def _required_int(payload: Mapping[str, object], field: str) -> int:
    if field not in payload:
        raise ContractError("missing_field", f"Falta el campo obligatorio '{field}'.", field=field)
    try:
        return int(payload[field])
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_integer", f"'{field}' debe ser un entero.", field=field) from exc


def _teams(payload: Mapping[str, object]) -> list[str]:
    raw = payload.get("teams")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ContractError("invalid_teams", "'teams' debe ser una lista de equipos.", field="teams")
    teams = [str(team).strip() for team in raw]
    if not teams or any(not team for team in teams):
        raise ContractError("invalid_teams", "'teams' no puede estar vacío ni contener nombres vacíos.", field="teams")
    if len(set(teams)) != len(teams):
        raise ContractError("duplicate_team", "'teams' contiene equipos repetidos.", field="teams")
    return teams


def _played_matches(raw: object) -> list[tuple[str, str, int, int]]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ContractError("invalid_matches", "'matches' debe ser una lista.", field="matches")
    out: list[tuple[str, str, int, int]] = []
    for index, row in enumerate(raw):
        try:
            if isinstance(row, Mapping):
                home = str(row["home"]).strip()
                away = str(row["away"]).strip()
                hg = int(row["home_goals"])
                ag = int(row["away_goals"])
            else:
                home, away, hg, ag = row  # type: ignore[misc]
                home, away, hg, ag = str(home).strip(), str(away).strip(), int(hg), int(ag)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(
                "invalid_match",
                f"Partido inválido en matches[{index}].",
                field="matches",
            ) from exc
        if not home or not away or home == away or hg < 0 or ag < 0:
            raise ContractError(
                "invalid_match",
                f"Partido inválido en matches[{index}].",
                field="matches",
            )
        out.append((home, away, hg, ag))
    return out


def _fixture_pairs(raw: object) -> list[tuple[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ContractError("invalid_matches", "'matches' debe ser una lista.", field="matches")
    out: list[tuple[str, str]] = []
    for index, row in enumerate(raw):
        try:
            if isinstance(row, Mapping):
                home = str(row["home"]).strip()
                away = str(row["away"]).strip()
            else:
                home, away = row  # type: ignore[misc]
                home, away = str(home).strip(), str(away).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(
                "invalid_match",
                f"Partido inválido en matches[{index}].",
                field="matches",
            ) from exc
        if not home or not away or home == away:
            raise ContractError(
                "invalid_match",
                f"Partido inválido en matches[{index}].",
                field="matches",
            )
        out.append((home, away))
    return out


def _fixed_results(raw: object) -> dict[tuple[str, str], str]:
    if raw is None:
        return {}
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ContractError("invalid_fixed", "'fixed' debe ser una lista.", field="fixed")
    out: dict[tuple[str, str], str] = {}
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ContractError("invalid_fixed", f"Resultado inválido en fixed[{index}].", field="fixed")
        home = str(row.get("home", "")).strip()
        away = str(row.get("away", "")).strip()
        result = str(row.get("result", "")).upper().strip()
        if not home or not away or home == away or result not in {"L", "E", "V"}:
            raise ContractError("invalid_fixed", f"Resultado inválido en fixed[{index}].", field="fixed")
        out[(home, away)] = result
    return out


def calculate_standings(payload: Mapping[str, object]) -> dict[str, object]:
    """Calcula posiciones y tabla desde un payload JSON-compatible."""
    payload = _mapping(payload)
    teams = _teams(payload)
    matches = _played_matches(payload.get("matches"))
    unknown = sorted({team for row in matches for team in row[:2]} - set(teams))
    if unknown:
        raise ContractError(
            "unknown_team",
            f"Hay equipos de partidos que no figuran en 'teams': {', '.join(unknown)}.",
            field="matches",
        )

    criteria_raw = payload.get("tiebreakers")
    if criteria_raw is None:
        criteria = DEFAULT_CRITERIOS
    elif isinstance(criteria_raw, Sequence) and not isinstance(criteria_raw, (str, bytes)):
        criteria = tuple(str(item) for item in criteria_raw)
    else:
        raise ContractError("invalid_tiebreakers", "'tiebreakers' debe ser una lista.", field="tiebreakers")

    fair_play = payload.get("fair_play")
    ranking = payload.get("ranking")
    if fair_play is not None and not isinstance(fair_play, Mapping):
        raise ContractError("invalid_fair_play", "'fair_play' debe ser un objeto.", field="fair_play")
    if ranking is not None and not isinstance(ranking, Mapping):
        raise ContractError("invalid_ranking", "'ranking' debe ser un objeto.", field="ranking")

    order, stats = _orden(
        teams,
        matches,
        fair_play=fair_play,
        ranking=ranking,
        criterios=criteria,
    )
    table = [
        {
            "position": position,
            "team": team,
            "played": int(stats[team]["pj"]),
            "points": int(stats[team]["pts"]),
            "goals_for": int(stats[team]["gf"]),
            "goals_against": int(stats[team]["ga"]),
            "goal_difference": int(stats[team]["dg"]),
        }
        for position, team in enumerate(order, 1)
    ]
    return _envelope(
        "standings",
        {
            "positions": {team: position for position, team in enumerate(order, 1)},
            "table": table,
            "tiebreakers": list(criteria),
        },
    )


def calculate_point_ladder(payload: Mapping[str, object]) -> dict[str, object]:
    """Expone la escalera exacta de puntos sin filtrar objetos de dominio."""
    payload = _mapping(payload)
    base = payload.get("base")
    if not isinstance(base, Mapping) or not base:
        raise ContractError("invalid_base", "'base' debe ser un objeto no vacío.", field="base")
    team = _required_text(payload, "team")
    if team not in base:
        raise ContractError("unknown_team", f"'{team}' no está en 'base'.", field="team")
    cutoff = _required_int(payload, "cutoff")
    matches = _fixture_pairs(payload.get("matches"))
    result = point_ladder(base, matches, team, cutoff)
    return _envelope("point_ladder", result)


def calculate_rank_window(payload: Mapping[str, object]) -> dict[str, object]:
    """Expone el rango exacto de puesto para una ventana y resultados fijados."""
    payload = _mapping(payload)
    base = payload.get("base")
    if not isinstance(base, Mapping) or not base:
        raise ContractError("invalid_base", "'base' debe ser un objeto no vacío.", field="base")
    team = _required_text(payload, "team")
    if team not in base:
        raise ContractError("unknown_team", f"'{team}' no está en 'base'.", field="team")
    matches = _fixture_pairs(payload.get("matches"))
    fixed = _fixed_results(payload.get("fixed"))
    result = scenario_rank_bounds(base, matches, team, fixed)
    return _envelope("rank_window", result)



def _floor_exact_guarantee(floor: object) -> int | None:
    """Tolera objetos PisoObjetivo de contratos internos anteriores a 3.8.8."""
    try:
        return getattr(floor, "garantia_exacta")
    except AttributeError:
        if bool(getattr(floor, "exacto", False)):
            return getattr(floor, "piso_exacto", None)
        return None


def _floor_conservative_reference(floor: object) -> int | None:
    """Tolera objetos PisoObjetivo de contratos internos anteriores a 3.8.8."""
    try:
        return getattr(floor, "referencia_conservadora")
    except AttributeError:
        if bool(getattr(floor, "exacto", False)):
            return None
        value = getattr(floor, "piso_conservador", None)
        return value if value is not None else getattr(floor, "piso_exacto", None)

def calculate_objective_floor(payload: Mapping[str, object]) -> dict[str, object]:
    """Expone los puntos necesarios para quedar dentro de un corte de tabla."""
    payload = _mapping(payload)
    base = payload.get("base")
    rest = payload.get("remaining")
    if not isinstance(base, Mapping) or not base:
        raise ContractError("invalid_base", "'base' debe ser un objeto no vacío.", field="base")
    if not isinstance(rest, Mapping):
        raise ContractError("invalid_remaining", "'remaining' debe ser un objeto.", field="remaining")
    team = _required_text(payload, "team")
    cutoff = _required_int(payload, "cutoff")
    key = str(payload.get("objective_key", "objective") or "objective")
    name = str(payload.get("objective_name", "el objetivo") or "el objetivo")
    matches = _fixture_pairs(payload.get("matches"))

    floor = piso_por_corte(base, rest, matches, team, cutoff, clave=key, nombre=name)
    result = asdict(floor)
    result["minimum_possible"] = floor.minimo_posible
    result["minimum_guarantee"] = _floor_exact_guarantee(floor)
    result["safe_total"] = floor.piso
    # Alias técnicos del contrato v1: se conservan para no romper consumidores.
    result["exact_guarantee"] = result["minimum_guarantee"]
    result["conservative_reference"] = _floor_conservative_reference(floor)
    result["safe_value"] = result["safe_total"]
    result["floor"] = floor.piso  # alias legado del contrato v1
    result["reading"] = floor.lectura()
    return _envelope("objective_floor", result)



def _definition_selected_teams(payload: Mapping[str, object], base: Mapping[str, object]) -> list[str] | None:
    raw_selected = payload.get("selected_teams")
    if raw_selected is None:
        return None
    if not isinstance(raw_selected, Sequence) or isinstance(raw_selected, (str, bytes)):
        raise ContractError("invalid_teams", "'selected_teams' debe ser una lista.", field="selected_teams")
    selected = [str(value).strip() for value in raw_selected]
    if any(not value for value in selected):
        raise ContractError("invalid_teams", "'selected_teams' contiene nombres vacíos.", field="selected_teams")
    unknown = [value for value in selected if value not in base]
    if unknown:
        raise ContractError(
            "unknown_team", "Hay equipos fuera del alcance del objetivo: " + ", ".join(unknown), field="selected_teams"
        )
    return selected


def _definition_key_team(payload: Mapping[str, object], base: Mapping[str, object]) -> str | None:
    key_team = str(payload.get("key_team", "") or "").strip() or None
    if key_team is not None and key_team not in base:
        raise ContractError("unknown_team", f"'{key_team}' no está en el alcance del objetivo.", field="key_team")
    return key_team


def calculate_definition(payload: Mapping[str, object]) -> dict[str, object]:
    """Expone el paquete exacto de definición sin depender de Streamlit.

    Hay dos modos compatibles:
    - legacy: el cliente envía ``base`` + ``cutoff`` + partidos;
    - snapshot schema 2: envía ``snapshot`` + ``team`` + ``objective`` (+ ``zone``
      para Playoffs) y opcionalmente ``round``/``fecha``. La base, el corte, los
      pendientes y la fecha salen de la foto canónica.
    """
    payload = _mapping(payload)
    if payload.get("snapshot") is not None:
        snapshot = _unwrap_snapshot(payload.get("snapshot"))
        _validate_snapshot(snapshot, require_canonical=False)
        return _envelope("definition", _definition_from_snapshot(snapshot, payload))

    base = payload.get("base")
    rest = payload.get("remaining")
    if not isinstance(base, Mapping) or not base:
        raise ContractError("invalid_base", "'base' debe ser un objeto no vacío.", field="base")
    if not isinstance(rest, Mapping):
        raise ContractError("invalid_remaining", "'remaining' debe ser un objeto.", field="remaining")
    team = _required_text(payload, "team")
    if team not in base:
        raise ContractError("unknown_team", f"'{team}' no está en 'base'.", field="team")
    cutoff = _required_int(payload, "cutoff")
    round_matches = _fixture_pairs(payload.get("round_matches"))
    if not round_matches:
        raise ContractError(
            "missing_round_matches", "'round_matches' debe contener la fecha a analizar.", field="round_matches"
        )
    pending = _fixture_pairs(payload.get("pending_matches")) if payload.get("pending_matches") is not None else list(round_matches)
    fixture = _fixture_payload(payload.get("fixture"))
    selected = _definition_selected_teams(payload, base)
    key_team = _definition_key_team(payload, base)

    result = definition_snapshot(
        base, rest, round_matches, team, cutoff, selected_teams=selected,
        all_pending=pending, fixture=fixture, key_team=key_team,
        exact_window=int(payload.get("exact_window", VENTANA_EXACTA) or VENTANA_EXACTA),
    )
    return _envelope("definition", result)


def service_capabilities() -> dict[str, object]:
    """Describe el contrato disponible sin depender de Streamlit ni de HTTP."""
    return _envelope(
        "capabilities",
        {
            "public_service_version": PUBLIC_SERVICE_VERSION,
            "public_operations": list(PUBLIC_OPERATIONS),
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "supported_snapshot_schema_versions": list(SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS),
            "data_provider_contract_version": DATA_PROVIDER_CONTRACT_VERSION,
            "supported_data_provider_contract_versions": list(SUPPORTED_DATA_PROVIDER_CONTRACT_VERSIONS),
            "data_provider_reference_implementations": ["current", "csv"],
            "snapshot_traceability_version": SNAPSHOT_TRACEABILITY_VERSION,
            "snapshot_objectives": ["playoffs", "libertadores", "sudamericana"],
            "batch_query_types": list(SUPPORTED_QUERY_TYPES),
            "operations": [
                "standings",
                "point_ladder",
                "rank_window",
                "objective_floor",
                "definition",
                "competition_snapshot",
                "validate_snapshot",
                "competition_batch",
            ],
            "exact_window_remaining_matches": VENTANA_EXACTA,
        },
    )


def _unwrap_snapshot(raw: object) -> Mapping[str, object]:
    """Acepta una foto cruda o el sobre completo devuelto por el servicio."""
    if not isinstance(raw, Mapping):
        raise ContractError("invalid_snapshot", "'snapshot' debe ser un objeto.", field="snapshot")
    if {"contract_version", "calculation", "result"}.issubset(raw):
        if str(raw.get("calculation", "")) != "competition_snapshot":
            raise ContractError(
                "invalid_snapshot_envelope",
                "El sobre informado no corresponde a 'competition_snapshot'.",
                field="snapshot.calculation",
            )
        result = raw.get("result")
        if not isinstance(result, Mapping):
            raise ContractError(
                "invalid_snapshot_envelope",
                "El resultado del snapshot debe ser un objeto.",
                field="snapshot.result",
            )
        return result
    return raw


def _snapshot_int_mapping(raw: object, field: str) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise ContractError("invalid_snapshot", f"'{field}' debe ser un objeto.", field=field)
    out: dict[str, int] = {}
    for team, value in raw.items():
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "invalid_snapshot", f"'{field}.{team}' debe ser un entero.", field=f"{field}.{team}"
            ) from exc
        if number < 0:
            raise ContractError(
                "invalid_snapshot", f"'{field}.{team}' no puede ser negativo.", field=f"{field}.{team}"
            )
        out[str(team)] = number
    return out


def _validate_snapshot(snapshot: Mapping[str, object], *, require_canonical: bool) -> dict[str, object]:
    """Valida forma e invariantes simples; no ejecuta matemática de competencia."""
    schema = snapshot.get("snapshot_schema_version")
    if schema is not None and str(schema) not in SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS:
        supported = ", ".join(SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS)
        raise ContractError(
            "unsupported_snapshot_schema",
            f"Snapshot schema no soportado: '{schema}'. Versiones admitidas: {supported}.",
            field="snapshot.snapshot_schema_version",
        )

    teams_raw = snapshot.get("teams")
    if require_canonical and teams_raw is None:
        raise ContractError(
            "invalid_snapshot", "Falta 'teams' en la foto canónica.", field="snapshot.teams"
        )
    teams: list[str] = []
    if teams_raw is not None:
        if not isinstance(teams_raw, Sequence) or isinstance(teams_raw, (str, bytes)):
            raise ContractError("invalid_snapshot", "'snapshot.teams' debe ser una lista.", field="snapshot.teams")
        teams = [str(team).strip() for team in teams_raw]
        if not teams or any(not team for team in teams) or len(set(teams)) != len(teams):
            raise ContractError(
                "invalid_snapshot",
                "'snapshot.teams' debe contener equipos únicos y no vacíos.",
                field="snapshot.teams",
            )

    zones = snapshot.get("zones")
    if require_canonical and (not isinstance(zones, Mapping) or not zones):
        raise ContractError("invalid_snapshot", "Falta 'zones' en la foto canónica.", field="snapshot.zones")
    zone_teams: set[str] = set()
    if zones is not None:
        if not isinstance(zones, Mapping):
            raise ContractError("invalid_snapshot", "'snapshot.zones' debe ser un objeto.", field="snapshot.zones")
        for label, base in zones.items():
            if not isinstance(base, Mapping):
                raise ContractError(
                    "invalid_snapshot", f"La zona '{label}' debe ser un objeto.", field=f"snapshot.zones.{label}"
                )
            for team, row in base.items():
                if not isinstance(row, Mapping):
                    raise ContractError(
                        "invalid_snapshot",
                        f"La fila de '{team}' en la zona '{label}' debe ser un objeto.",
                        field=f"snapshot.zones.{label}.{team}",
                    )
                if str(team) in zone_teams:
                    raise ContractError(
                        "invalid_snapshot",
                        f"'{team}' aparece en más de una zona.",
                        field="snapshot.zones",
                    )
                zone_teams.add(str(team))

    if teams and zone_teams and set(teams) != zone_teams:
        missing = sorted(set(teams) - zone_teams)
        extra = sorted(zone_teams - set(teams))
        detail = []
        if missing:
            detail.append("sin zona: " + ", ".join(missing))
        if extra:
            detail.append("fuera de teams: " + ", ".join(extra))
        raise ContractError(
            "inconsistent_snapshot",
            "La nómina de equipos y las zonas no coinciden (" + "; ".join(detail) + ").",
            field="snapshot.zones",
        )

    remaining = _snapshot_int_mapping(snapshot.get("remaining"), "snapshot.remaining")
    if teams and set(remaining) != set(teams):
        raise ContractError(
            "inconsistent_snapshot",
            "'snapshot.remaining' debe contener exactamente los equipos de 'snapshot.teams'.",
            field="snapshot.remaining",
        )

    pending_raw = snapshot.get("pending")
    if not isinstance(pending_raw, Sequence) or isinstance(pending_raw, (str, bytes)):
        raise ContractError("invalid_snapshot", "'snapshot.pending' debe ser una lista.", field="snapshot.pending")
    pending_counts = {team: 0 for team in teams}
    pending_count = 0
    known = set(teams) if teams else (set(remaining) | zone_teams)
    for index, row in enumerate(pending_raw):
        if not isinstance(row, Mapping):
            raise ContractError(
                "invalid_snapshot", f"Partido inválido en pending[{index}].", field=f"snapshot.pending[{index}]"
            )
        home = str(row.get("home", "") or "").strip()
        away = str(row.get("away", "") or "").strip()
        if not home or not away or home == away:
            raise ContractError(
                "invalid_snapshot", f"Partido inválido en pending[{index}].", field=f"snapshot.pending[{index}]"
            )
        if known and (home not in known or away not in known):
            raise ContractError(
                "inconsistent_snapshot",
                f"pending[{index}] contiene un equipo fuera de la foto.",
                field=f"snapshot.pending[{index}]",
            )
        if teams:
            pending_counts[home] += 1
            pending_counts[away] += 1
        pending_count += 1

    if teams and pending_counts != remaining:
        different = [team for team in teams if pending_counts.get(team, 0) != remaining.get(team, 0)]
        sample = ", ".join(different[:5])
        suffix = "…" if len(different) > 5 else ""
        raise ContractError(
            "inconsistent_snapshot",
            "Los partidos pendientes no coinciden con 'remaining' para: " + sample + suffix + ".",
            field="snapshot.remaining",
        )

    rules = snapshot.get("rules")
    if rules is not None:
        if not isinstance(rules, Mapping):
            raise ContractError("invalid_snapshot", "'snapshot.rules' debe ser un objeto.", field="snapshot.rules")
        for key in ("annual_relegations", "average_relegations"):
            if key in rules:
                try:
                    value = int(rules[key])
                except (TypeError, ValueError) as exc:
                    raise ContractError(
                        "invalid_snapshot", f"'snapshot.rules.{key}' debe ser entero.", field=f"snapshot.rules.{key}"
                    ) from exc
                if value < 0:
                    raise ContractError(
                        "invalid_snapshot", f"'snapshot.rules.{key}' no puede ser negativo.", field=f"snapshot.rules.{key}"
                    )

    format_rules = snapshot.get("format")
    if format_rules is not None:
        if not isinstance(format_rules, Mapping):
            raise ContractError("invalid_snapshot", "'snapshot.format' debe ser un objeto.", field="snapshot.format")
        for key in ("opening_rounds", "playoff_cutoff", "sudamericana_slots"):
            if key not in format_rules:
                continue
            try:
                value = int(format_rules[key])
            except (TypeError, ValueError) as exc:
                raise ContractError(
                    "invalid_snapshot", f"'snapshot.format.{key}' debe ser entero.", field=f"snapshot.format.{key}"
                ) from exc
            if value < 0 or (key == "opening_rounds" and value == 0):
                raise ContractError(
                    "invalid_snapshot", f"'snapshot.format.{key}' tiene un valor fuera de rango.", field=f"snapshot.format.{key}"
                )

    qualification = snapshot.get("qualification")
    if str(schema or "") in {"2", "3"} and require_canonical and not isinstance(qualification, Mapping):
        raise ContractError(
            "invalid_snapshot", "Falta el contexto de clasificación del snapshot schema 2+.", field="snapshot.qualification"
        )
    if qualification is not None:
        if not isinstance(qualification, Mapping):
            raise ContractError("invalid_snapshot", "'snapshot.qualification' debe ser un objeto.", field="snapshot.qualification")
        for objective in ("playoffs", "libertadores", "sudamericana"):
            context = qualification.get(objective)
            if not isinstance(context, Mapping):
                raise ContractError(
                    "invalid_snapshot", f"Falta el contexto de '{objective}'.", field=f"snapshot.qualification.{objective}"
                )
            if objective == "playoffs":
                zctx = context.get("zones")
                if not isinstance(zctx, Mapping):
                    raise ContractError(
                        "invalid_snapshot", "El contexto de playoffs debe declarar zonas.", field="snapshot.qualification.playoffs.zones"
                    )
                if isinstance(zones, Mapping) and set(map(str, zctx)) != set(map(str, zones)):
                    raise ContractError(
                        "inconsistent_snapshot",
                        "Las zonas del contexto de playoffs no coinciden con 'snapshot.zones'.",
                        field="snapshot.qualification.playoffs.zones",
                    )
                continue
            eligible = context.get("eligible_teams")
            direct = context.get("direct_qualifiers")
            if not isinstance(eligible, Sequence) or isinstance(eligible, (str, bytes)):
                raise ContractError(
                    "invalid_snapshot", f"'{objective}.eligible_teams' debe ser una lista.",
                    field=f"snapshot.qualification.{objective}.eligible_teams",
                )
            if not isinstance(direct, Sequence) or isinstance(direct, (str, bytes)):
                raise ContractError(
                    "invalid_snapshot", f"'{objective}.direct_qualifiers' debe ser una lista.",
                    field=f"snapshot.qualification.{objective}.direct_qualifiers",
                )
            eligible_names = [str(value) for value in eligible]
            direct_names = [str(value) for value in direct]
            if set(eligible_names) & set(direct_names):
                raise ContractError(
                    "inconsistent_snapshot",
                    f"'{objective}' mezcla equipos elegibles con clasificados directos.",
                    field=f"snapshot.qualification.{objective}",
                )
            annual = snapshot.get("annual")
            annual_names = set(map(str, annual)) if isinstance(annual, Mapping) else set()
            if annual_names and not (set(eligible_names) | set(direct_names)).issubset(annual_names):
                raise ContractError(
                    "inconsistent_snapshot",
                    f"'{objective}' contiene equipos fuera de la Tabla Anual.",
                    field=f"snapshot.qualification.{objective}",
                )
            try:
                cutoff = int(context.get("cutoff", 0) or 0)
            except (TypeError, ValueError) as exc:
                raise ContractError(
                    "invalid_snapshot", f"El corte de '{objective}' debe ser entero.",
                    field=f"snapshot.qualification.{objective}.cutoff",
                ) from exc
            if cutoff < 0 or cutoff > len(eligible_names):
                raise ContractError(
                    "inconsistent_snapshot", f"El corte de '{objective}' excede su universo elegible.",
                    field=f"snapshot.qualification.{objective}.cutoff",
                )

    traceability = snapshot.get("traceability")
    if str(schema or "") == "3" and require_canonical and not isinstance(traceability, Mapping):
        raise ContractError(
            "invalid_snapshot",
            "Falta 'traceability' en el snapshot schema 3.",
            field="snapshot.traceability",
        )
    if traceability is not None:
        if not isinstance(traceability, Mapping):
            raise ContractError(
                "invalid_snapshot", "'snapshot.traceability' debe ser un objeto.", field="snapshot.traceability"
            )
        if str(traceability.get("traceability_version") or "") != SNAPSHOT_TRACEABILITY_VERSION:
            raise ContractError(
                "invalid_snapshot",
                "Versión de trazabilidad no soportada.",
                field="snapshot.traceability.traceability_version",
            )
        if not str(traceability.get("snapshot_id") or "").strip():
            raise ContractError(
                "invalid_snapshot", "Falta snapshot_id de trazabilidad.", field="snapshot.traceability.snapshot_id"
            )
        if not isinstance(traceability.get("provider"), Mapping):
            raise ContractError(
                "invalid_snapshot", "Falta proveedor de trazabilidad.", field="snapshot.traceability.provider"
            )
        if not isinstance(traceability.get("source"), Mapping):
            raise ContractError(
                "invalid_snapshot", "Falta fuente de trazabilidad.", field="snapshot.traceability.source"
            )
        if not isinstance(traceability.get("coverage"), Mapping):
            raise ContractError(
                "invalid_snapshot", "Falta cobertura de trazabilidad.", field="snapshot.traceability.coverage"
            )
        if not isinstance(traceability.get("quality"), Mapping):
            raise ContractError(
                "invalid_snapshot", "Falta calidad de trazabilidad.", field="snapshot.traceability.quality"
            )

    trace_summary = snapshot_traceability_summary(snapshot)
    return {
        "snapshot_schema_version": str(schema or SNAPSHOT_SCHEMA_VERSION),
        "canonical": bool(teams and zone_teams),
        "team_count": len(teams) if teams else len(known),
        "zone_count": len(zones) if isinstance(zones, Mapping) else 0,
        "pending_match_count": pending_count,
        "has_annual": isinstance(snapshot.get("annual"), Mapping) and bool(snapshot.get("annual")),
        "has_average_history": isinstance(snapshot.get("previous_averages"), Mapping) and bool(snapshot.get("previous_averages")),
        "has_qualification_context": isinstance(snapshot.get("qualification"), Mapping) and bool(snapshot.get("qualification")),
        "has_traceability": bool(trace_summary.get("available")),
        "snapshot_id": trace_summary.get("snapshot_id"),
        "source_age_hours": trace_summary.get("age_hours"),
    }


def validate_competition_snapshot(payload: Mapping[str, object]) -> dict[str, object]:
    """Valida una foto canónica antes de enviarla a cálculos batch."""
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    summary = _validate_snapshot(snapshot, require_canonical=True)
    return _envelope("validate_snapshot", summary)


def _optional_mapping(payload: Mapping[str, object], field: str) -> Mapping[str, object] | None:
    raw = payload.get(field)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ContractError("invalid_mapping", f"'{field}' debe ser un objeto.", field=field)
    return raw


def _zones_mapping(payload: Mapping[str, object]) -> Mapping[str, Mapping[str, Mapping[str, object]]]:
    raw = payload.get("zones")
    if not isinstance(raw, Mapping) or not raw:
        raise ContractError("invalid_zones", "'zones' debe ser un objeto no vacío.", field="zones")
    for label, base in raw.items():
        if not isinstance(base, Mapping):
            raise ContractError("invalid_zone", f"La zona '{label}' debe ser un objeto.", field="zones")
        for team, row in base.items():
            if not isinstance(row, Mapping):
                raise ContractError(
                    "invalid_zone_row",
                    f"La fila de '{team}' en la zona '{label}' debe ser un objeto.",
                    field="zones",
                )
    return raw  # type: ignore[return-value]


def _fixture_payload(raw: object) -> list[Mapping[str, object]]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ContractError("invalid_fixture", "'fixture' debe ser una lista.", field="fixture")
    out: list[Mapping[str, object]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ContractError(
                "invalid_fixture",
                f"Partido inválido en fixture[{index}].",
                field="fixture",
            )
        if not str(row.get("l", "")).strip() or not str(row.get("v", "")).strip():
            raise ContractError(
                "invalid_fixture",
                f"Partido inválido en fixture[{index}].",
                field="fixture",
            )
        out.append(row)
    return out


def _qualification_inputs(payload: Mapping[str, object]) -> tuple[tuple[str, str, str], tuple[str, str], str]:
    raw = payload.get("qualification") or {}
    if not isinstance(raw, Mapping):
        raise ContractError("invalid_qualification", "'qualification' debe ser un objeto.", field="qualification")
    champions = raw.get("champions") or {}
    international = raw.get("international_champions") or {}
    if not isinstance(champions, Mapping):
        raise ContractError(
            "invalid_qualification", "'qualification.champions' debe ser un objeto.", field="qualification.champions"
        )
    if not isinstance(international, Mapping):
        raise ContractError(
            "invalid_qualification",
            "'qualification.international_champions' debe ser un objeto.",
            field="qualification.international_champions",
        )
    camps = (
        str(champions.get("apertura", "") or "").strip(),
        str(champions.get("clausura", "") or "").strip(),
        str(champions.get("copa_argentina", "") or "").strip(),
    )
    extras = (
        str(international.get("libertadores", "") or "").strip(),
        str(international.get("sudamericana", "") or "").strip(),
    )
    replacement = str(raw.get("copa_argentina_replacement", "") or "").strip()
    return camps, extras, replacement


def prepare_competition_snapshot(payload: Mapping[str, object]) -> dict[str, object]:
    """Construye una foto completa y JSON-safe usando el estado canónico de la app."""
    payload = _mapping(payload)
    zones = _zones_mapping(payload)
    played = _played_matches(payload.get("played"))
    annual = _optional_mapping(payload, "annual")
    opening = _optional_mapping(payload, "opening")
    previous = _optional_mapping(payload, "previous_averages")
    fixture = _fixture_payload(payload.get("fixture"))
    camps, extras, copa_replacement = _qualification_inputs(payload)
    rules = payload.get("rules") or {}
    if not isinstance(rules, Mapping):
        raise ContractError("invalid_rules", "'rules' debe ser un objeto.", field="rules")
    try:
        annual_relegations = int(rules.get("annual_relegations", 1))
        average_relegations = int(rules.get("average_relegations", 1))
        opening_rounds = int(rules.get("opening_rounds", 16))
        playoff_cutoff = int(rules.get("playoff_cutoff", 8))
        sudamericana_slots = int(rules.get("sudamericana_slots", 6))
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_rules", "Las reglas numéricas deben ser enteras.", field="rules") from exc
    if min(annual_relegations, average_relegations, playoff_cutoff, sudamericana_slots) < 0 or opening_rounds <= 0:
        raise ContractError("invalid_rules", "Las reglas numéricas tienen valores fuera de rango.", field="rules")

    provider_name = str(payload.get("data_provider") or "direct").strip() or "direct"
    provider_contract_version = str(payload.get("data_provider_contract_version") or "").strip() or None
    if provider_contract_version and provider_contract_version not in SUPPORTED_DATA_PROVIDER_CONTRACT_VERSIONS:
        raise ContractError(
            "unsupported_data_provider_contract",
            f"DataProvider contract no soportado: '{provider_contract_version}'.",
            field="data_provider_contract_version",
        )
    provenance = payload.get("provenance") or {}
    if not isinstance(provenance, Mapping):
        raise ContractError("invalid_provenance", "'provenance' debe ser un objeto.", field="provenance")

    snapshot, report = build_competition_snapshot(
        zones,
        played=played,
        annual=annual,  # type: ignore[arg-type]
        opening=opening,  # type: ignore[arg-type]
        previous_averages=previous,
        fixture=fixture,
        camps=camps,
        extras=extras,
        copa_replacement=copa_replacement,
        annual_relegations=annual_relegations,
        average_relegations=average_relegations,
        opening_rounds=opening_rounds,
        playoff_cutoff=playoff_cutoff,
        sudamericana_slots=sudamericana_slots,
        provider_name=provider_name,
        provider_contract_version=provider_contract_version,
        provenance=provenance,
    )
    snapshot["audit"] = report
    return _envelope("competition_snapshot", snapshot)


def _snapshot_query_scope(
    snapshot: Mapping[str, object],
    query: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, int], list[tuple[str, str]]]:
    scope = str(query.get("scope", "zone") or "zone").strip().lower()
    zone = str(query.get("zone", "") or "").strip() or None
    try:
        return snapshot_scope(snapshot, scope, zone=zone)
    except ValueError as exc:
        field = "zone" if scope == "zone" else "scope"
        raise ContractError("invalid_scope", str(exc), field=field) from exc


def _snapshot_objective_context(snapshot: Mapping[str, object], objective: object) -> tuple[str, Mapping[str, object]]:
    try:
        key = normalize_objective(objective)
    except ValueError as exc:
        raise ContractError("invalid_objective", str(exc), field="objective") from exc
    qualification = snapshot.get("qualification")
    if not isinstance(qualification, Mapping):
        raise ContractError(
            "missing_qualification_context",
            "El snapshot no contiene contexto de clasificación; generá una foto schema 2 para consultar objetivos directamente.",
            field="snapshot.qualification",
        )
    context = qualification.get(key)
    if not isinstance(context, Mapping):
        raise ContractError("invalid_snapshot", f"Falta el contexto de '{key}'.", field=f"snapshot.qualification.{key}")
    return key, context


def _direct_objective_resolution(
    snapshot: Mapping[str, object], objective: object, team: str
) -> dict[str, object] | None:
    key, context = _snapshot_objective_context(snapshot, objective)
    direct = context.get("direct_qualifiers")
    if key == "playoffs" or not isinstance(direct, Sequence) or isinstance(direct, (str, bytes)):
        return None
    direct_names = [str(value) for value in direct]
    if team not in direct_names:
        return None
    reasons = context.get("direct_reasons") or {}
    reason = str(reasons.get(team, "") or "") if isinstance(reasons, Mapping) else ""
    return {
        "objective": key,
        "label": str(context.get("label") or key),
        "status": "already_qualified_direct" if key == "libertadores" else "already_qualified_higher_competition",
        "resolved": True,
        "team": team,
        "via": reason or "vía directa ya resuelta",
        "message": (
            f"{team} ya tiene resuelto el objetivo por una vía directa y no compite por este corte de la Tabla Anual."
            if key == "libertadores"
            else f"{team} ya tiene una plaza superior (Libertadores), por lo que el objetivo de al menos Sudamericana ya está cumplido."
        ),
    }


def _snapshot_objective_query_scope(
    snapshot: Mapping[str, object],
    query: Mapping[str, object],
) -> tuple[str, Mapping[str, object], Mapping[str, int], list[tuple[str, str]], int, Mapping[str, object]]:
    objective = query.get("objective")
    key, _context = _snapshot_objective_context(snapshot, objective)
    zone = str(query.get("zone", "") or "").strip() or None
    try:
        base, remaining, matches, cutoff, context = snapshot_objective_scope(snapshot, objective, zone=zone)
    except ValueError as exc:
        field = "zone" if key == "playoffs" and not zone else "objective"
        raise ContractError("invalid_objective_scope", str(exc), field=field) from exc
    return key, base, remaining, matches, cutoff, context

def _definition_round_from_snapshot(
    snapshot: Mapping[str, object],
    objective_matches: Sequence[tuple[str, str]],
    query: Mapping[str, object],
) -> tuple[int, list[tuple[str, str]], list[Mapping[str, object]]]:
    """Resuelve una fecha pendiente usando un único fixture canónico.

    ``round`` es el nombre estable del contrato; ``fecha`` queda como alias editorial.
    Si no se informa ninguno, toma la jornada operativa vigente del snapshot.
    """
    fixture = _fixture_payload(snapshot.get("fixture"))
    if not fixture:
        raise ContractError(
            "missing_fixture",
            "El snapshot no contiene fixture oficial para resolver la fecha de definición.",
            field="snapshot.fixture",
        )
    all_pending = _fixture_pairs(snapshot.get("pending"))
    if not all_pending:
        raise ContractError("no_pending_matches", "El snapshot no tiene partidos pendientes.", field="snapshot.pending")

    raw_round = query.get("round") if query.get("round") is not None else query.get("fecha")
    requested: int | None = None
    if raw_round is not None and str(raw_round).strip() != "":
        try:
            requested = int(raw_round)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid_integer", "'round'/'fecha' debe ser un entero.", field="round") from exc

    round_no, official_all, _postponed = current_round(all_pending, fixture, forzar=requested)
    if requested is not None:
        fmap = {(str(game.get("l", "")), str(game.get("v", ""))): game.get("f") for game in fixture}
        requested_pending = [match for match in all_pending if fmap.get(match) == requested]
        if not requested_pending:
            raise ContractError(
                "round_not_pending",
                f"La Fecha {requested} no tiene partidos pendientes en el snapshot.",
                field="round",
            )
        round_no = requested
        official_all = requested_pending

    if round_no is None or not official_all:
        raise ContractError(
            "no_definition_round",
            "No hay una fecha oficial pendiente que pueda usarse para definición.",
            field="snapshot.pending",
        )

    allowed = set(objective_matches)
    selected = [match for match in official_all if match in allowed]
    return int(round_no), selected, fixture


def _definition_from_snapshot(
    snapshot: Mapping[str, object],
    query: Mapping[str, object],
) -> dict[str, object]:
    """Construye definición por objetivo sin pedir base/corte al consumidor."""
    team = _required_text(query, "team")
    if query.get("objective") is None:
        raise ContractError(
            "missing_field",
            "La definición desde snapshot requiere el campo 'objective'.",
            field="objective",
        )

    direct = _direct_objective_resolution(snapshot, query.get("objective"), team)
    if direct is not None:
        return {
            "available": True,
            "definition_needed": False,
            **direct,
        }

    objective_key, base, remaining, objective_matches, cutoff, context = _snapshot_objective_query_scope(
        snapshot, query
    )
    if team not in base:
        raise ContractError(
            "unknown_team",
            f"'{team}' no está en el alcance del objetivo elegido.",
            field="team",
        )

    round_no, round_matches, fixture = _definition_round_from_snapshot(snapshot, objective_matches, query)
    selected = _definition_selected_teams(query, base)
    key_team = _definition_key_team(query, base)
    result = definition_snapshot(
        base, remaining, round_matches, team, cutoff,
        selected_teams=selected, all_pending=objective_matches, fixture=fixture, key_team=key_team,
        exact_window=int(query.get("exact_window", VENTANA_EXACTA) or VENTANA_EXACTA),
    )
    result.update({
        "objective": objective_key,
        "label": str(context.get("label") or _objective_display_name(objective_key)),
        "scope": str(context.get("kind") or ""),
        "zone": str(query.get("zone", "") or "") or None,
        "round": int(round_no),
        "round_label": f"Fecha {int(round_no)}",
        "resolved": False,
        "definition_needed": True,
    })
    return result

def _objective_result(floor: object) -> dict[str, object]:
    result = asdict(floor)  # type: ignore[arg-type]
    result["minimum_possible"] = floor.minimo_posible  # type: ignore[attr-defined]
    result["minimum_guarantee"] = _floor_exact_guarantee(floor)  # type: ignore[attr-defined]
    result["safe_total"] = floor.piso  # type: ignore[attr-defined]
    # Alias técnicos del contrato v1: se conservan para no romper consumidores.
    result["exact_guarantee"] = result["minimum_guarantee"]
    result["conservative_reference"] = _floor_conservative_reference(floor)  # type: ignore[attr-defined]
    result["safe_value"] = result["safe_total"]
    result["reading"] = floor.lectura()  # type: ignore[attr-defined]
    return result


def _objective_display_name(key: str) -> str:
    return {
        "playoffs": "los playoffs",
        "libertadores": "la Libertadores",
        "sudamericana": "al menos la Sudamericana",
    }.get(key, "el objetivo")


def calculate_competition_batch(payload: Mapping[str, object]) -> dict[str, object]:
    """Ejecuta varias consultas sobre una misma foto canónica sin recalcular la carga.

    Desde snapshot schema 2, ``objective`` permite pedir Playoffs, Libertadores o
    Sudamericana sin enviar una ``base`` reducida ni un ``cutoff`` duplicado.
    """
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    _validate_snapshot(snapshot, require_canonical=False)
    queries = payload.get("queries")
    if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)) or not queries:
        raise ContractError("invalid_queries", "'queries' debe ser una lista no vacía.", field="queries")

    outputs: list[dict[str, object]] = []
    for index, raw_query in enumerate(queries):
        if not isinstance(raw_query, Mapping):
            raise ContractError("invalid_query", f"Consulta inválida en queries[{index}].", field="queries")
        qtype = str(raw_query.get("type", "") or "").strip().lower()
        query_id = str(raw_query.get("id", index))
        team = str(raw_query.get("team", "") or "").strip()
        objective_supplied = raw_query.get("objective") is not None
        objective_key: str | None = None
        objective_context: Mapping[str, object] | None = None
        cutoff: int | None = None

        if qtype == "definition":
            result = _definition_from_snapshot(snapshot, raw_query)
            outputs.append({"id": query_id, "type": qtype, "result": result})
            continue

        objective_aware = {"objective_points", "objective_status", "point_ladder", "rank_window"}
        if qtype in objective_aware:
            if not team:
                raise ContractError("missing_field", "Falta el campo obligatorio 'team'.", field="team")

            if objective_supplied:
                direct = _direct_objective_resolution(snapshot, raw_query.get("objective"), team)
                if direct is not None:
                    outputs.append({"id": query_id, "type": qtype, "result": direct})
                    continue
                objective_key, base, remaining, matches, cutoff, objective_context = _snapshot_objective_query_scope(
                    snapshot, raw_query
                )
            else:
                if qtype == "objective_status":
                    raise ContractError(
                        "missing_field", "'objective_status' requiere el campo 'objective'.", field="objective"
                    )
                base, remaining, matches = _snapshot_query_scope(snapshot, raw_query)

            if team not in base:
                raise ContractError("unknown_team", f"'{team}' no está en el alcance elegido.", field="team")

        if qtype in {"objective_points", "objective_status"}:
            if cutoff is None:
                cutoff = _required_int(raw_query, "cutoff")
            key = objective_key or str(raw_query.get("objective_key", "objective") or "objective")
            name = _objective_display_name(objective_key) if objective_key else str(
                raw_query.get("objective_name", "el objetivo") or "el objetivo"
            )
            floor = piso_por_corte(base, remaining, matches, team, cutoff, clave=key, nombre=name)
            result = _objective_result(floor)
            if objective_key:
                result.update({
                    "objective": objective_key,
                    "label": str((objective_context or {}).get("label") or name),
                    "status": "open",
                    "resolved": False,
                    "cutoff": int(cutoff),
                    "scope": str((objective_context or {}).get("kind") or ""),
                    "zone": str(raw_query.get("zone", "") or "") or None,
                })

        elif qtype == "point_ladder":
            if cutoff is None:
                cutoff = _required_int(raw_query, "cutoff")
            result = point_ladder(base, matches, team, cutoff)
            if objective_key and isinstance(result, dict):
                result.update({"objective": objective_key, "cutoff": int(cutoff)})

        elif qtype == "rank_window":
            fixed = _fixed_results(raw_query.get("fixed"))
            result = scenario_rank_bounds(base, matches, team, fixed)
            if objective_key and isinstance(result, dict):
                result.update({"objective": objective_key, "cutoff": int(cutoff or 0)})

        elif qtype == "descent_points":
            annual = snapshot.get("annual")
            remaining = snapshot.get("remaining")
            pending = snapshot.get("pending")
            rules = snapshot.get("rules") or {}
            if not isinstance(annual, Mapping) or not isinstance(remaining, Mapping) or not isinstance(pending, Sequence):
                raise ContractError("invalid_snapshot", "El snapshot no tiene datos completos de descenso.", field="snapshot")
            if not team:
                raise ContractError("missing_field", "Falta el campo obligatorio 'team'.", field="team")
            if team not in annual:
                raise ContractError("unknown_team", f"'{team}' no está en la Tabla Anual.", field="team")
            matches = _fixture_pairs(pending)
            prom_totals = snapshot_average_totals(snapshot)
            annual_relegations = int(rules.get("annual_relegations", 1)) if isinstance(rules, Mapping) else 1
            average_relegations = int(rules.get("average_relegations", 1)) if isinstance(rules, Mapping) else 1
            floor = piso_no_descenso(
                annual,
                remaining,
                matches,
                team,
                n_anual=annual_relegations,
                prom_totales=prom_totals,
                n_prom=average_relegations,
            )
            result = _objective_result(floor)

        else:
            raise ContractError(
                "unknown_query",
                f"Tipo de consulta no soportado: '{qtype}'.",
                field="type",
            )

        outputs.append({"id": query_id, "type": qtype, "result": result})

    return _envelope(
        "competition_batch",
        {
            "snapshot_schema_version": str(snapshot.get("snapshot_schema_version") or SNAPSHOT_SCHEMA_VERSION),
            "query_count": len(outputs),
            "queries": outputs,
        },
    )


def _snapshot_table_base(
    snapshot: Mapping[str, object], payload: Mapping[str, object]
) -> tuple[Mapping[str, object], dict[str, object]]:
    """Resuelve la tabla pública desde una foto canónica sin recalcular resultados."""
    objective = payload.get("objective")
    if objective is not None:
        key, _base, _remaining, _matches, cutoff, context = _snapshot_objective_query_scope(snapshot, payload)
        return _base, {
            "objective": key,
            "cutoff": int(cutoff),
            "scope": str(context.get("kind") or ""),
            "zone": str(payload.get("zone", "") or "") or None,
            "label": str(context.get("label") or _objective_display_name(key)),
        }

    scope = str(payload.get("scope", "zone") or "zone").strip().lower()
    base, _remaining, _matches = _snapshot_query_scope(snapshot, payload)
    return base, {
        "objective": None,
        "cutoff": None,
        "scope": scope,
        "zone": str(payload.get("zone", "") or "") or None,
        "label": "Tabla Anual" if scope == "annual" else f"Zona {str(payload.get('zone', '') or '').strip()}",
    }


def _table_rows_from_base(base: Mapping[str, object]) -> list[dict[str, object]]:
    source_order = {str(team): index for index, team in enumerate(base)}

    def row(team: str) -> Mapping[str, object]:
        value = base.get(team)
        return value if isinstance(value, Mapping) else {}

    order = sorted(
        (str(team) for team in base),
        key=lambda team: (
            -int(row(team).get("pts", 0) or 0),
            -int(row(team).get("dg", 0) or 0),
            -int(row(team).get("gf", 0) or 0),
            int(row(team).get("source_pos", 10_000 + source_order[team]) or (10_000 + source_order[team])),
            source_order[team],
        ),
    )
    return [
        {
            "position": position,
            "team": team,
            "played": int(row(team).get("pj", 0) or 0),
            "points": int(row(team).get("pts", 0) or 0),
            "goals_for": int(row(team).get("gf", 0) or 0),
            "goals_against": int(row(team).get("ga", 0) or 0),
            "goal_difference": int(row(team).get("dg", 0) or 0),
        }
        for position, team in enumerate(order, 1)
    ]


def calculate_snapshot_standings(payload: Mapping[str, object]) -> dict[str, object]:
    """Tabla pública preferida: consume snapshot y devuelve filas JSON estables."""
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    _validate_snapshot(snapshot, require_canonical=False)
    base, meta = _snapshot_table_base(snapshot, payload)
    rows = _table_rows_from_base(base)
    result = {
        **meta,
        "table": rows,
        "positions": {row["team"]: row["position"] for row in rows},
        "snapshot_schema_version": str(snapshot.get("snapshot_schema_version") or SNAPSHOT_SCHEMA_VERSION),
    }
    return _envelope("standings", result)


def _preview_objective_label(value: object) -> str:
    key = str(value or "playoffs").strip().lower().replace("á", "a")
    aliases = {
        "playoffs": "Playoffs",
        "playoff": "Playoffs",
        "libertadores": "Libertadores",
        "sudamericana": "Al menos Sudamericana",
        "al_menos_sudamericana": "Al menos Sudamericana",
        "descenso": "Descenso",
    }
    if key not in aliases:
        raise ContractError("invalid_objective", f"Objetivo no soportado para previa: '{value}'.", field="objective")
    return aliases[key]


def _preview_scenario_games(
    window: Mapping[str, object],
    pending: Sequence[tuple[str, str]],
    fixture: Sequence[Mapping[str, object]],
    scope: str,
) -> list[tuple[str, str]]:
    """Expande el próximo partido a su fecha oficial, igual que la UI, sin estado global."""
    games = [tuple(match) for match in (window.get("games") or [])]
    own_raw = window.get("own_match")
    own = tuple(own_raw) if isinstance(own_raw, (tuple, list)) and len(own_raw) == 2 else None
    if scope == "next_team_match" and own:
        own_meta = window.get("own_meta") or {}
        round_no = own_meta.get("round") if isinstance(own_meta, Mapping) else None
        if round_no is None:
            round_no = match_round(own, fixture)
        if round_no is not None:
            games = [match for match in pending if match_round(match, fixture) == round_no] + games + [own]
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in games:
        pair = (str(match[0]), str(match[1]))
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def calculate_preview(payload: Mapping[str, object]) -> dict[str, object]:
    """Previa pública por snapshot; devuelve texto y escenarios sin filtrar DataFrames."""
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    _validate_snapshot(snapshot, require_canonical=False)
    team = _required_text(payload, "team")
    zones = snapshot.get("zones")
    annual = snapshot.get("annual")
    if not isinstance(zones, Mapping) or not any(team in base for base in zones.values() if isinstance(base, Mapping)):
        raise ContractError("unknown_team", f"'{team}' no figura en las zonas del snapshot.", field="team")
    if annual is not None and not isinstance(annual, Mapping):
        raise ContractError("invalid_snapshot", "'snapshot.annual' debe ser un objeto.", field="snapshot.annual")

    pending = _fixture_pairs(snapshot.get("pending"))
    fixture = _fixture_payload(snapshot.get("fixture"))
    if not fixture:
        raise ContractError("missing_fixture", "El snapshot no contiene fixture oficial para la previa.", field="snapshot.fixture")
    scope = str(payload.get("scope", "next_team_match") or "next_team_match").strip().lower()
    allowed_scopes = {"next_team_match", "next_team_day", "official_round", "postponed_only", "extended_window"}
    if scope not in allowed_scopes:
        raise ContractError("invalid_scope", f"Alcance de previa no soportado: '{scope}'.", field="scope")
    raw_round = payload.get("round") if payload.get("round") is not None else payload.get("fecha")
    requested_round = None
    if raw_round is not None and str(raw_round).strip() != "":
        try:
            requested_round = int(raw_round)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid_integer", "'round'/'fecha' debe ser un entero.", field="round") from exc
        requested_pending = [match for match in pending if match_round(match, fixture) == requested_round]
        if not requested_pending:
            raise ContractError(
                "round_not_pending",
                f"La Fecha {requested_round} no tiene partidos pendientes en el snapshot.",
                field="round",
            )

    schedule_raw = payload.get("schedule")
    if schedule_raw is not None and not isinstance(schedule_raw, Mapping):
        raise ContractError("invalid_schedule", "'schedule' debe ser un objeto.", field="schedule")
    schedule = build_schedule_map(primary_schedule=schedule_raw if isinstance(schedule_raw, Mapping) else None)
    window = resolve_scope_games(team, pending, fixture, schedule, scope=scope, fecha=requested_round)
    window = dict(window)
    window["scope"] = scope
    scenario_games = _preview_scenario_games(window, pending, fixture, scope)
    if not scenario_games and window.get("games"):
        scenario_games = [tuple(match) for match in window.get("games") or []]

    objective_label = _preview_objective_label(payload.get("objective"))
    qualification = snapshot.get("qualification") or {}
    lib_ctx = qualification.get("libertadores") if isinstance(qualification, Mapping) else None
    cup_allocation: dict[str, object] = {}
    fixed_routes: dict[str, str] = {}
    eligible: list[str] = []
    if isinstance(lib_ctx, Mapping):
        cup_allocation["n_tabla_lib"] = int(lib_ctx.get("table_slots", 0) or 0)
        direct_reasons = lib_ctx.get("direct_reasons")
        if isinstance(direct_reasons, Mapping):
            fixed_routes = {str(name): str(reason) for name, reason in direct_reasons.items()}
        eligible_raw = lib_ctx.get("eligible_teams")
        if isinstance(eligible_raw, Sequence) and not isinstance(eligible_raw, (str, bytes)):
            eligible = [str(name) for name in eligible_raw]

    rules = snapshot.get("rules") or {}
    n_annual = int(rules.get("annual_relegations", 1) or 1) if isinstance(rules, Mapping) else 1
    current_round_no, _official, _postponed = current_round(pending, fixture, forzar=requested_round)
    text, frame = team_preview_text(
        team,
        zones,
        pending,
        annual if isinstance(annual, Mapping) else None,
        window=window,
        scenario_games=scenario_games,
        objective=objective_label,
        current_round=current_round_no,
        n_annual=n_annual,
        cup_allocation=cup_allocation,
        fixed_routes=fixed_routes,
        eligible_teams=eligible,
        top_eight=int((snapshot.get("format") or {}).get("playoff_cutoff", 8))
        if isinstance(snapshot.get("format"), Mapping)
        else 8,
    )
    if text is None:
        raise ContractError("preview_unavailable", "No se pudo construir la previa para el equipo.", field="team")
    records = frame.to_dict(orient="records") if frame is not None else []
    reusable_line = str(frame.attrs.get("reusable_line", "") or "") if frame is not None else ""
    return _envelope(
        "preview",
        {
            "team": team,
            "objective": str(payload.get("objective", "playoffs") or "playoffs").strip().lower(),
            "scope": scope,
            "round": window.get("round"),
            "label": window.get("label"),
            "own_match": list(window.get("own_match")) if window.get("own_match") else None,
            "markdown": text,
            "reusable_line": reusable_line,
            "scenarios": records,
        },
    )


def calculate_objective_points(payload: Mapping[str, object]) -> dict[str, object]:
    """Operación pública estable para puntos por objetivo."""
    payload = _mapping(payload)
    if payload.get("snapshot") is not None:
        if payload.get("objective") is None:
            raise ContractError("missing_field", "Falta el campo obligatorio 'objective'.", field="objective")
        query = {
            "type": "objective_points",
            "team": payload.get("team"),
            "objective": payload.get("objective"),
            "zone": payload.get("zone"),
        }
        response = calculate_competition_batch({"snapshot": payload.get("snapshot"), "queries": [query]})
        result = response["result"]["queries"][0]["result"]  # type: ignore[index]
        return _envelope("objective_points", result)
    legacy = calculate_objective_floor(payload)
    return _envelope("objective_points", legacy.get("result"))


def _canonical_strength_from_snapshot(snapshot: Mapping[str, object]) -> dict[str, float]:
    zones = snapshot.get("zones") or {}
    if not isinstance(zones, Mapping):
        return {}
    current: dict[str, Mapping[str, object]] = {}
    for base in zones.values():
        if not isinstance(base, Mapping):
            continue
        for team, value in base.items():
            if isinstance(value, Mapping):
                current[str(team)] = value
    played = _played_matches(snapshot.get("played"))
    opening = snapshot.get("opening") if isinstance(snapshot.get("opening"), Mapping) else None
    return estimate_team_strength(current, played=played, opening=opening)


def calculate_objective_chances(payload: Mapping[str, object]) -> dict[str, object]:
    """Probabilidad estimada de un objetivo, separada del paquete exacto de definición."""
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    _validate_snapshot(snapshot, require_canonical=False)
    team = _required_text(payload, "team")
    if payload.get("objective") is None:
        raise ContractError("missing_field", "Falta el campo obligatorio 'objective'.", field="objective")

    direct = _direct_objective_resolution(snapshot, payload.get("objective"), team)
    if direct is not None:
        return _envelope(
            "objective_chances",
            {
                **direct,
                "estimated": False,
                "simulations": 0,
                "qualification_probability": 1.0,
                "qualification_percentage": 100.0,
            },
        )

    key, base, _remaining, matches, cutoff, context = _snapshot_objective_query_scope(snapshot, payload)
    if team not in base:
        raise ContractError("unknown_team", f"'{team}' no está en el alcance del objetivo elegido.", field="team")
    try:
        simulations = int(payload.get("simulations", 6000) or 6000)
        seed = int(payload.get("seed", 20260804) or 20260804)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_integer", "'simulations' y 'seed' deben ser enteros.") from exc
    if simulations < 1000 or simulations > 100_000:
        raise ContractError(
            "invalid_simulations",
            "'simulations' debe estar entre 1000 y 100000; el valor editorial por defecto es 6000.",
            field="simulations",
        )
    strength = _canonical_strength_from_snapshot(snapshot)
    analysis = competition_context(
        base,
        matches,
        team,
        cutoff,
        strength=strength or None,
        simulations=simulations,
        seed=seed,
    )
    projection = analysis.get("projection") if isinstance(analysis, Mapping) else None
    if not isinstance(projection, Mapping):
        raise ContractError("simulation_failed", "La simulación no devolvió una proyección utilizable.")
    probability = float(projection.get("qualification_probability", 0.0) or 0.0)
    return _envelope(
        "objective_chances",
        {
            "team": team,
            "objective": key,
            "label": str(context.get("label") or _objective_display_name(key)),
            "scope": str(context.get("kind") or ""),
            "zone": str(payload.get("zone", "") or "") or None,
            "cutoff": int(cutoff),
            "estimated": True,
            "simulations": simulations,
            "seed": seed,
            "qualification_probability": probability,
            "qualification_percentage": round(100.0 * probability, 1),
            "current_rank": analysis.get("current_rank"),
            "current_points": analysis.get("current_points"),
            "games_left": analysis.get("games_left"),
            "ceiling": analysis.get("ceiling"),
            "projection": projection,
        },
    )


def calculate_relegation(payload: Mapping[str, object]) -> dict[str, object]:
    """Foto pública de descenso y, opcionalmente, piso exacto/conservador de un equipo."""
    payload = _mapping(payload)
    snapshot = _unwrap_snapshot(payload.get("snapshot"))
    _validate_snapshot(snapshot, require_canonical=False)
    annual = snapshot.get("annual")
    remaining = snapshot.get("remaining")
    pending = snapshot.get("pending")
    if not isinstance(annual, Mapping) or not isinstance(remaining, Mapping) or not isinstance(pending, Sequence):
        raise ContractError("invalid_snapshot", "El snapshot no tiene datos completos de descenso.", field="snapshot")
    rules = snapshot.get("rules") or {}
    annual_relegations = int(rules.get("annual_relegations", 1) or 1) if isinstance(rules, Mapping) else 1
    average_relegations = int(rules.get("average_relegations", 1) or 1) if isinstance(rules, Mapping) else 1
    average_totals = snapshot_average_totals(snapshot) or {}
    average_rows = [
        {"Equipo": team, "Pts": int(values[0]), "PJ": int(values[1])}
        for team, values in average_totals.items()
    ]
    picture = current_relegation_picture(
        annual,
        average_rows,
        annual_relegations=annual_relegations,
        average_relegations=average_relegations,
    )
    result: dict[str, object] = {
        "annual_relegations": annual_relegations,
        "average_relegations": average_relegations,
        "average_data_available": bool(average_totals),
        "complete": bool(average_totals) or average_relegations == 0,
        "current_picture": picture,
        "team": None,
    }
    if average_relegations and not average_totals:
        result["warning"] = (
            "Faltan antecedentes de promedios: la foto anual es utilizable, pero no corresponde "
            "presentar el descenso combinado como completo."
        )
    team = str(payload.get("team", "") or "").strip()
    if team:
        if team not in annual:
            raise ContractError("unknown_team", f"'{team}' no está en la Tabla Anual.", field="team")
        floor = piso_no_descenso(
            annual,
            remaining,
            _fixture_pairs(pending),
            team,
            n_anual=annual_relegations,
            prom_totales=average_totals or None,
            n_prom=average_relegations,
        )
        result["team"] = {"name": team, **_objective_result(floor)}
    return _envelope("relegation", result)


def calculate(operation: str, payload: Mapping[str, object]) -> dict[str, object]:
    """Dispatcher público mínimo, framework-agnostic y JSON-safe.

    Las siete operaciones de ``PUBLIC_OPERATIONS`` son la frontera que debería usar
    una futura API HTTP. Los helpers históricos permanecen disponibles, pero no
    forman parte de esta superficie pública estable.
    """
    payload = _mapping(payload)
    op = str(operation or "").strip().lower()
    if op not in PUBLIC_OPERATIONS:
        raise ContractError(
            "unknown_operation",
            f"Operación pública no soportada: '{operation}'.",
            field="operation",
        )
    if op == "standings":
        return calculate_snapshot_standings(payload) if payload.get("snapshot") is not None else calculate_standings(payload)
    if op == "preview":
        return calculate_preview(payload)
    if op == "objective_points":
        return calculate_objective_points(payload)
    if op == "objective_chances":
        return calculate_objective_chances(payload)
    if op == "definition":
        return calculate_definition(payload)
    if op == "relegation":
        return calculate_relegation(payload)
    return calculate_competition_batch(payload)
