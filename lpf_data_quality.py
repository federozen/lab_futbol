"""Normalización, reconciliación y controles de calidad de datos LPF.

No depende de Streamlit. La tabla anual autoritativa se reconstruye desde una
foto fija del Apertura más la tabla actual del Clausura siempre que sea posible.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

from lpf_models import AuditIssue, DataQualityReport, MatchRecord

STAT_KEYS = ("pts", "pj", "dg", "gf", "ga")


def _i(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def canonical_row(row: Mapping[str, object] | None) -> dict[str, int]:
    row = row or {}
    gf = _i(row.get("gf"))
    ga = _i(row.get("ga"))
    dg = _i(row.get("dg"), gf - ga)
    if ("gf" in row or "ga" in row) and dg != gf - ga:
        dg = gf - ga
    return {
        "pts": _i(row.get("pts")),
        "pj": _i(row.get("pj")),
        "dg": dg,
        "gf": gf,
        "ga": ga,
    }


def flatten_zones(zones: Mapping[str, Mapping[str, Mapping[str, object]]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for base in (zones or {}).values():
        for team, row in base.items():
            out[team] = canonical_row(row)
    return out


def validate_zones(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    expected_total: int = 30,
    expected_per_zone: int = 15,
    total_rounds: int = 16,
) -> tuple[list[AuditIssue], list[str]]:
    issues: list[AuditIssue] = []
    details: list[str] = []
    if not zones:
        return [AuditIssue("zones_missing", "No hay tablas de zonas cargadas.", "blocked", "playoffs")], details
    seen: list[str] = []
    for label, base in sorted(zones.items()):
        details.append(f"Zona {label}: {len(base)} equipos")
        if len(base) != expected_per_zone:
            issues.append(AuditIssue(
                "zone_size", f"La Zona {label} tiene {len(base)} equipos; deberían ser {expected_per_zone}.",
                "blocked", "playoffs", suggestion="Revisar la tabla pegada y los aliases de clubes."
            ))
        seen.extend(base)
        for team, raw in base.items():
            row = canonical_row(raw)
            if row["pj"] < 0 or row["pj"] > total_rounds:
                issues.append(AuditIssue("zone_pj", f"{team} tiene {row['pj']} PJ en su zona.", "blocked", "playoffs", (team,)))
            if row["pts"] < 0 or row["pts"] > 3 * row["pj"]:
                issues.append(AuditIssue("zone_pts", f"{team} tiene {row['pts']} puntos en {row['pj']} PJ: valor imposible.", "blocked", "playoffs", (team,)))
            if row["dg"] != row["gf"] - row["ga"] and (row["gf"] or row["ga"]):
                issues.append(AuditIssue("zone_dg", f"La diferencia de gol de {team} no coincide con GF-GA.", "warning", "playoffs", (team,)))
    duplicates = [team for team, count in Counter(seen).items() if count > 1]
    if duplicates:
        issues.append(AuditIssue("zone_duplicates", "Hay equipos repetidos entre zonas: " + ", ".join(duplicates), "blocked", "playoffs", tuple(duplicates)))
    if len(set(seen)) != expected_total:
        issues.append(AuditIssue("zone_total", f"Hay {len(set(seen))} clubes únicos; deberían ser {expected_total}.", "blocked", "playoffs"))
    return issues, details


def fixture_records(
    fixture: Sequence[Mapping[str, object]],
    played: Iterable[tuple[str, str, int, int]] | None,
    zones: Mapping[str, Mapping[str, Mapping[str, object]]] | None = None,
) -> tuple[list[MatchRecord], list[AuditIssue]]:
    """Reconcilia fixture y resultados explícitos sin inventar qué partido se jugó.

    Los marcadores partido a partido son la fuente autoritativa. Los PJ de las
    tablas se usan únicamente como control. Si faltan resultados para explicar
    esos PJ, los encuentros tempranos compatibles quedan con estado
    ``unconfirmed`` y el dominio de datos se bloquea hasta completar la fuente.

    Este comportamiento evita el error anterior: cuando un club tenía un
    postergado, una inferencia codiciosa podía marcar como jugados los primeros
    partidos del fixture y dejar como pendiente uno posterior que sí se había
    disputado.
    """
    issues: list[AuditIssue] = []
    played_map: dict[tuple[str, str], tuple[int, int]] = {}
    for home, away, gh, ga in played or []:
        key = (home, away)
        result = (int(gh), int(ga))
        if key in played_map and played_map[key] != result:
            issues.append(AuditIssue(
                "duplicate_result",
                f"Hay dos resultados distintos para {home}–{away}.",
                "blocked",
                "data",
                (home, away),
            ))
        played_map[key] = result

    rows: list[MatchRecord] = []
    by_key: dict[tuple[str, str], int] = {}
    for idx, game in enumerate(fixture):
        home, away = str(game["l"]), str(game["v"])
        rnd = _i(game.get("f"))
        key = (home, away)
        result = played_map.get(key)
        rec = MatchRecord(
            match_id=f"F{rnd:02d}-{_slug(home)}-{_slug(away)}",
            round_number=rnd,
            original_round=rnd,
            home=home,
            away=away,
            kind=str(game.get("tipo") or "zone"),
            zone=game.get("zona") if game.get("zona") in ("A", "B") else None,
            status="played" if result is not None else "scheduled",
            home_goals=result[0] if result else None,
            away_goals=result[1] if result else None,
            source="result" if result else "fixture",
        )
        by_key[key] = idx
        rows.append(rec)

    unknown_results = [key for key in played_map if key not in by_key]
    if unknown_results:
        issues.append(AuditIssue(
            "results_not_in_fixture",
            "Hay resultados que no aparecen en el fixture: "
            + ", ".join(f"{a}–{b}" for a, b in unknown_results[:4]),
            "blocked",
            "data",
        ))

    if not zones:
        return rows, issues

    table = flatten_zones(zones)
    explicit_counts = Counter()
    explicit_rounds: list[int] = []
    for rec in rows:
        if rec.status == "played":
            explicit_counts[rec.home] += 1
            explicit_counts[rec.away] += 1
            explicit_rounds.append(rec.round_number)

    impossible = [
        team for team, row in table.items()
        if explicit_counts[team] > row["pj"]
    ]
    if impossible:
        issues.append(AuditIssue(
            "too_many_results",
            "Hay más resultados explícitos que PJ en la tabla para: " + ", ".join(impossible),
            "blocked",
            "data",
            tuple(impossible),
        ))

    missing = {
        team: max(0, row["pj"] - explicit_counts[team])
        for team, row in table.items()
    }
    unresolved_teams = [team for team, count in missing.items() if count]

    if unresolved_teams:
        # El máximo número de PJ no identifica una fecha de manera perfecta cuando
        # hay postergados. Se complementa con la última fecha que sí tiene al menos
        # un resultado explícito. Sólo los cruces tempranos cuyos dos protagonistas
        # necesitan resultados adicionales se marcan como "sin confirmar".
        round_hint = max(
            max((row["pj"] for row in table.values()), default=0),
            max(explicit_rounds, default=0),
        )
        uncertain_count = 0
        for idx, rec in enumerate(rows):
            if rec.status != "scheduled" or rec.round_number > round_hint:
                continue
            if missing.get(rec.home, 0) <= 0 or missing.get(rec.away, 0) <= 0:
                continue
            rows[idx] = MatchRecord(
                match_id=rec.match_id,
                round_number=rec.round_number,
                original_round=rec.original_round,
                home=rec.home,
                away=rec.away,
                kind=rec.kind,
                zone=rec.zone,
                status="unconfirmed",
                home_goals=None,
                away_goals=None,
                inferred=False,
                source="pj_unconfirmed",
            )
            uncertain_count += 1

        missing_detail = ", ".join(
            f"{team} ({missing[team]})" for team in unresolved_teams[:10]
        )
        message = (
            "Faltan resultados partido a partido para explicar los PJ de: "
            f"{missing_detail}. No se asignó ningún partido como jugado por descarte."
        )
        if uncertain_count:
            message += f" Hay {uncertain_count} cruce(s) con estado sin confirmar."
        issues.append(AuditIssue(
            "fixture_unconfirmed",
            message,
            "blocked",
            "data",
            tuple(unresolved_teams),
            "Actualizar los resultados desde el inicio del Clausura o cargar los marcadores faltantes.",
        ))

    return rows, issues


def pending_pairs(records: Sequence[MatchRecord]) -> list[tuple[str, str]]:
    """Devuelve sólo pendientes confirmados; excluye estados sin confirmar."""
    return [(r.home, r.away) for r in records if r.status == "scheduled"]


def unconfirmed_pairs(records: Sequence[MatchRecord]) -> list[tuple[str, str]]:
    return [(r.home, r.away) for r in records if r.status == "unconfirmed"]


def derive_opening_snapshot(
    annual: Mapping[str, Mapping[str, object]],
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    opening_rounds: int = 16,
) -> tuple[dict[str, dict[str, int]], list[AuditIssue]]:
    issues: list[AuditIssue] = []
    zone = flatten_zones(zones)
    if not annual or set(annual) != set(zone):
        return {}, [AuditIssue("annual_teams", "La Tabla Anual no contiene los mismos 30 equipos que las zonas.", "blocked", "annual")]
    opening: dict[str, dict[str, int]] = {}
    for team, zrow in zone.items():
        arow = canonical_row(annual[team])
        if arow["pj"] - zrow["pj"] != opening_rounds:
            issues.append(AuditIssue(
                "annual_pj_offset",
                f"{team}: la Anual tiene {arow['pj']} PJ y la zona {zrow['pj']}; la diferencia debería ser {opening_rounds}.",
                "blocked", "annual", (team,)
            ))
            continue
        row = {key: arow[key] - zrow[key] for key in STAT_KEYS}
        if row["pj"] != opening_rounds or row["pts"] < 0 or row["pts"] > 3 * row["pj"] or row["gf"] < 0 or row["ga"] < 0:
            issues.append(AuditIssue("opening_invalid", f"No se puede reconstruir el Apertura de {team} desde las tablas cargadas.", "blocked", "annual", (team,)))
            continue
        # La DG es aditiva y puede estar disponible aunque GF/GA no lo estén.
        opening[team] = row
    if len(opening) != len(zone):
        return {}, issues
    return opening, issues



def derive_opening_from_results(
    annual: Mapping[str, Mapping[str, object]],
    fixture: Sequence[Mapping[str, object]],
    played: Iterable[tuple[str, str, int, int]],
    *,
    opening_rounds: int = 16,
) -> tuple[dict[str, dict[str, int]], list[AuditIssue]]:
    """Reconstruye el Apertura fijo restando del acumulado los partidos del Clausura.

    Es útil cuando la Tabla Anual importada corresponde a una foto anterior del
    Clausura y las zonas ya avanzaron. Los resultados se ordenan por la jornada
    original del fixture; para cada club se restan exactamente
    ``annual_pj - opening_rounds`` encuentros.

    La función no usa la tabla actual de las zonas, por lo que una actualización
    posterior del Clausura no invalida la foto fija del Apertura.
    """
    direct = {team: canonical_row(row) for team, row in (annual or {}).items()}
    if not direct:
        return {}, [AuditIssue("opening_source_missing", "Falta una Tabla Anual de referencia para reconstruir el Apertura.", "blocked", "annual")]

    round_by_match: dict[tuple[str, str], int] = {}
    for game in fixture or []:
        home = str(game.get("l") or game.get("home") or "")
        away = str(game.get("v") or game.get("away") or "")
        if home and away:
            round_by_match[(home, away)] = _i(game.get("f", game.get("round", 999)), 999)

    contributions: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for home, away, gh, ga in played or []:
        rnd = round_by_match.get((home, away), 999)
        contributions[home].append((rnd, _i(gh), _i(ga)))
        contributions[away].append((rnd, _i(ga), _i(gh)))

    opening: dict[str, dict[str, int]] = {}
    issues: list[AuditIssue] = []
    for team, row in direct.items():
        current_games = row["pj"] - int(opening_rounds)
        if current_games < 0:
            issues.append(AuditIssue(
                "opening_negative_offset",
                f"{team}: la Tabla Anual tiene {row['pj']} PJ, menos que las {opening_rounds} fechas del Apertura.",
                "blocked", "annual", (team,),
            ))
            continue
        games = sorted(contributions.get(team, []), key=lambda value: value[0])
        if len(games) < current_games:
            issues.append(AuditIssue(
                "opening_results_missing",
                f"{team}: faltan {current_games - len(games)} resultado(s) para separar el Apertura de la Tabla Anual de referencia.",
                "blocked", "annual", (team,),
                "Cargar los resultados del Clausura incluidos en esa foto de la Tabla Anual.",
            ))
            continue
        pts, pj, gf, ga = row["pts"], row["pj"], row["gf"], row["ga"]
        for _rnd, favor, against in games[:current_games]:
            pts -= 3 if favor > against else 1 if favor == against else 0
            pj -= 1
            gf -= favor
            ga -= against
        candidate = {"pts": pts, "pj": pj, "gf": gf, "ga": ga, "dg": gf - ga}
        if (candidate["pj"] != opening_rounds or candidate["pts"] < 0 or
                candidate["pts"] > 3 * candidate["pj"] or candidate["gf"] < 0 or candidate["ga"] < 0):
            issues.append(AuditIssue(
                "opening_result_invalid",
                f"No se pudo reconstruir un Apertura válido para {team}.",
                "blocked", "annual", (team,),
            ))
            continue
        opening[team] = candidate

    if len(opening) != len(direct):
        return {}, issues
    return opening, issues

def sum_opening_and_zones(
    opening: Mapping[str, Mapping[str, object]],
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> dict[str, dict[str, int]]:
    zone = flatten_zones(zones)
    out: dict[str, dict[str, int]] = {}
    for team, zrow in zone.items():
        arow = canonical_row(opening.get(team))
        out[team] = {key: arow[key] + zrow[key] for key in STAT_KEYS}
    return out


def validate_annual(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    annual: Mapping[str, Mapping[str, object]],
    *,
    opening_rounds: int = 16,
) -> list[AuditIssue]:
    zone = flatten_zones(zones)
    issues: list[AuditIssue] = []
    if not annual:
        return [AuditIssue("annual_missing", "Falta la Tabla Anual.", "blocked", "annual")]
    if set(annual) != set(zone):
        missing = sorted(set(zone) - set(annual))
        extra = sorted(set(annual) - set(zone))
        msg = f"La Anual no coincide con las zonas. Faltan {len(missing)} y sobran {len(extra)} equipos."
        issues.append(AuditIssue("annual_members", msg, "blocked", "annual", tuple(missing + extra)))
    for team in set(zone) & set(annual):
        zrow = zone[team]
        arow = canonical_row(annual[team])
        expected_pj = opening_rounds + zrow["pj"]
        if arow["pj"] != expected_pj:
            issues.append(AuditIssue("annual_stale", f"{team}: {arow['pj']} PJ en la Anual; deberían ser {expected_pj}.", "blocked", "annual", (team,)))
        if arow["pts"] < zrow["pts"] or arow["pts"] > 3 * arow["pj"]:
            issues.append(AuditIssue("annual_points", f"{team}: los puntos de la Anual son incompatibles con su zona.", "blocked", "annual", (team,)))
        if arow["dg"] != arow["gf"] - arow["ga"] and (arow["gf"] or arow["ga"]):
            issues.append(AuditIssue("annual_dg", f"{team}: DG no coincide con GF-GA en la Anual.", "warning", "annual", (team,)))
    return issues


def _norm_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    replacements = {"jrs": "juniors", "atl": "atletico", "riv": "rivadavia", "lp": "la plata"}
    return " ".join(replacements.get(token, token) for token in value.split())


def _assign_external_names(external: Iterable[str], canonical: Iterable[str]) -> dict[str, str]:
    free = list(canonical)
    assigned: dict[str, str] = {}
    for key in external:
        nk = _norm_name(key)
        exact = [team for team in free if _norm_name(team) == nk]
        if len(exact) == 1:
            assigned[key] = exact[0]; free.remove(exact[0])
    for key in external:
        if key in assigned:
            continue
        nk = _norm_name(key)
        candidates = [team for team in free if nk in _norm_name(team) or _norm_name(team) in nk]
        if len(candidates) == 1:
            assigned[key] = candidates[0]; free.remove(candidates[0])
    return assigned


def validate_promedios(
    annual: Mapping[str, Mapping[str, object]],
    previous: Mapping[str, object] | None,
) -> list[AuditIssue]:
    if not previous:
        return [AuditIssue("prom_missing", "Faltan los antecedentes de promedios.", "blocked", "promedios")]
    issues: list[AuditIssue] = []
    assigned = _assign_external_names(previous.keys(), annual.keys())
    inverse = {team: key for key, team in assigned.items()}
    missing = sorted(set(annual) - set(inverse))
    promoted_current_only = {"Estudiantes de Río Cuarto", "Gimnasia de Mendoza"}
    allowed_missing = [team for team in missing if team in promoted_current_only]
    real_missing = [team for team in missing if team not in promoted_current_only]
    if allowed_missing:
        issues.append(AuditIssue(
            "prom_promoted", "Los recién ascendidos computan sólo la temporada actual: " + ", ".join(allowed_missing) + ".",
            "warning", "promedios", tuple(allowed_missing),
            "Se los toma con 0 puntos y 0 PJ previos, según la regla de promedios."
        ))
    if real_missing:
        issues.append(AuditIssue(
            "prom_members", f"Faltan antecedentes de promedios para {len(real_missing)} equipos: {', '.join(real_missing[:6])}.",
            "blocked", "promedios", tuple(real_missing),
            "Revisar aliases o pegar la tabla completa de promedios."
        ))
    for team, external_key in inverse.items():
        value = previous[external_key]
        if isinstance(value, Mapping):
            pts = _i(value.get("pts", value.get("tp", 0)))
            pj = _i(value.get("pj", value.get("tj", 0)))
        elif isinstance(value, (tuple, list)) and len(value) >= 2:
            pts, pj = _i(value[0]), _i(value[1])
        else:
            issues.append(AuditIssue("prom_format", f"No se reconoce el antecedente de promedios de {external_key}.", "blocked", "promedios", (team,)))
            continue
        if pts < 0 or pj < 0 or (pj and pts > 3 * pj):
            issues.append(AuditIssue("prom_invalid", f"Antecedente imposible para {team}: {pts} puntos en {pj} PJ.", "blocked", "promedios", (team,)))
    unmatched = sorted(set(previous) - set(assigned))
    if unmatched:
        issues.append(AuditIssue(
            "prom_unmatched", "No se pudieron asociar estos nombres de promedios: " + ", ".join(unmatched[:6]),
            "warning", "promedios", suggestion="Agregar o corregir aliases de clubes."
        ))
    return issues


def build_quality_report(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    annual_direct: Mapping[str, Mapping[str, object]] | None,
    previous: Mapping[str, object] | None,
    fixture: Sequence[Mapping[str, object]],
    played: Iterable[tuple[str, str, int, int]] | None,
    opening_snapshot: Mapping[str, Mapping[str, object]] | None = None,
) -> DataQualityReport:
    issues, details = validate_zones(zones)
    records, fixture_issues = fixture_records(fixture, played, zones)
    issues.extend(fixture_issues)

    opening = {team: canonical_row(row) for team, row in (opening_snapshot or {}).items()}
    authoritative: dict[str, dict[str, int]] = {}
    if opening and set(opening) == set(flatten_zones(zones)):
        authoritative = sum_opening_and_zones(opening, zones)
        issues.extend(validate_annual(zones, authoritative))
        details.append("Tabla Anual: recalculada desde Apertura fijo + zonas actuales")
    else:
        direct = {team: canonical_row(row) for team, row in (annual_direct or {}).items()}
        annual_issues = validate_annual(zones, direct)
        if not any(i.level == "blocked" for i in annual_issues):
            authoritative = direct
            opening, derive_issues = derive_opening_snapshot(direct, zones)
            issues.extend(derive_issues)
            details.append("Tabla Anual: validada y usada para reconstruir el Apertura fijo")
        else:
            issues.extend(annual_issues)
    if authoritative:
        issues.extend(validate_promedios(authoritative, previous))
    else:
        issues.append(AuditIssue("annual_blocked", "No hay una Tabla Anual autoritativa; se bloquean copas y descenso.", "blocked", "annual"))

    level = "blocked" if any(i.level == "blocked" for i in issues) else "warning" if issues else "ok"
    details.append(
        "Fixture: "
        f"{sum(r.status == 'played' for r in records)} jugados · "
        f"{sum(r.status == 'scheduled' for r in records)} pendientes · "
        f"{sum(r.status == 'unconfirmed' for r in records)} sin confirmar"
    )
    return DataQualityReport(level, issues, details, authoritative, opening, records)
