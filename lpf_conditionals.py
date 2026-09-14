"""Condicionales exactos de la próxima fecha para una tabla LPF.

Enumera únicamente los resultados de la próxima jornada capaces de mover la tabla
analizada. No asigna probabilidades: cada combinación cuenta una vez y las
frecuencias resultantes son combinatorias, no pronósticos.
"""
from __future__ import annotations

from itertools import product
from collections.abc import Iterable, Mapping

LPF_RUNTIME_API = 21

OUTCOMES = ("L", "E", "V")
_OWN_BRANCHES = ("G", "E", "P")


def _dedupe_relevant(base: Mapping[str, object], games: Iterable[tuple[str, str]]):
    teams = set(base)
    out = []
    seen = set()
    for raw in games or []:
        if len(raw) < 2:
            continue
        match = (str(raw[0]), str(raw[1]))
        if match in seen or not (match[0] in teams or match[1] in teams):
            continue
        seen.add(match)
        out.append(match)
    return out


def _outcome_points(code: str) -> tuple[int, int]:
    if code == "L":
        return 3, 0
    if code == "V":
        return 0, 3
    return 1, 1


def _own_code(match: tuple[str, str], team: str, branch: str) -> str:
    if branch == "E":
        return "E"
    home = match[0] == team
    if branch == "G":
        return "L" if home else "V"
    return "V" if home else "L"


def _apply(base: Mapping[str, object], games, outcomes):
    points = {team: int((row or {}).get("pts", 0)) for team, row in base.items()}
    for (home, away), code in zip(games, outcomes):
        ph, pa = _outcome_points(code)
        if home in points:
            points[home] += ph
        if away in points:
            points[away] += pa
    return points


def _rest_after_round(base: Mapping[str, object], rest: Mapping[str, int], games):
    out = {team: int(rest.get(team, 0)) for team in base}
    for home, away in games:
        if home in out:
            out[home] = max(0, out[home] - 1)
        if away in out:
            out[away] = max(0, out[away] - 1)
    return out


def _season_state(points: Mapping[str, int], rest: Mapping[str, int], team: str, cutoff: int) -> str:
    pmax = {name: int(points[name]) + 3 * int(rest.get(name, 0)) for name in points}
    above_reachable = sum(1 for name in points if name != team and pmax[name] >= int(points[team]))
    unreachable = sum(1 for name in points if name != team and int(points[name]) > pmax[team])
    if above_reachable < cutoff:
        return "in"
    if unreachable >= cutoff:
        return "out"
    return "pelea"


def _round_state(points: Mapping[str, int], team: str, cutoff: int) -> str:
    target = int(points[team])
    strictly_above = sum(1 for name, value in points.items() if name != team and int(value) > target)
    equal_or_above = sum(1 for name, value in points.items() if name != team and int(value) >= target)
    if equal_or_above < cutoff:
        return "safe"
    if strictly_above < cutoff:
        return "tiebreak"
    return "out"


def _proof_metrics(points: Mapping[str, int], rest: Mapping[str, int], team: str, cutoff: int) -> dict[str, object]:
    """Datos de auditoría para explicar por qué una rama asegura o elimina."""
    team_points = int(points[team])
    team_ceiling = team_points + 3 * int(rest.get(team, 0))
    pmax = {name: int(value) + 3 * int(rest.get(name, 0)) for name, value in points.items()}
    threats = sorted(
        ((name, int(pmax[name])) for name in points if name != team and int(pmax[name]) >= team_points),
        key=lambda item: (-item[1], item[0]),
    )
    unreachable = sorted(
        ((name, int(points[name])) for name in points if name != team and int(points[name]) > team_ceiling),
        key=lambda item: (-item[1], item[0]),
    )
    return {
        "team_points": team_points,
        "team_ceiling": team_ceiling,
        "threats": threats,
        "threat_count": len(threats),
        "unreachable": unreachable,
        "unreachable_count": len(unreachable),
        "cutoff": int(cutoff),
    }


def _outcome_label(match: tuple[str, str], code: str) -> str:
    home, away = match
    if code == "L":
        return f"gana {home}"
    if code == "V":
        return f"gana {away}"
    return f"empatan {home} y {away}"


def _candidate_events(matches):
    candidates = []
    for index, match in enumerate(matches):
        home, away = match
        candidates.extend([
            (index, frozenset({"L"}), f"gana {home}"),
            (index, frozenset({"E"}), f"empatan {home} y {away}"),
            (index, frozenset({"V"}), f"gana {away}"),
            (index, frozenset({"E", "V"}), f"{home} no gana"),
            (index, frozenset({"L", "E"}), f"{away} no gana"),
        ])
    return candidates


def _simple_conditions(rows, matches, target_key):
    if not rows or not any(row[target_key] for row in rows):
        return None, None
    if all(row[target_key] for row in rows):
        return "No depende de otros resultados", None

    candidates = _candidate_events(matches)

    def matches_event(row, event):
        idx, allowed, _label = event
        return row["other_outcomes"][idx] in allowed

    sufficient = []
    for event in candidates:
        subset = [row for row in rows if matches_event(row, event)]
        if subset and all(row[target_key] for row in subset):
            sufficient.append((1, -len(subset), event[2], (event,)))
    if not sufficient:
        for i, first in enumerate(candidates):
            for second in candidates[i + 1:]:
                if first[0] == second[0]:
                    continue
                subset = [row for row in rows if matches_event(row, first) and matches_event(row, second)]
                if subset and all(row[target_key] for row in subset):
                    label = f"{first[2]} y {second[2]}"
                    sufficient.append((2, -len(subset), label, (first, second)))
    sufficient.sort(key=lambda item: (item[0], item[1], item[2]))
    sufficient_label = sufficient[0][2] if sufficient else None

    target_rows = [row for row in rows if row[target_key]]
    necessary = []
    for event in candidates:
        if all(matches_event(row, event) for row in target_rows):
            necessary.append((len(event[1]), event[2]))
    necessary.sort(key=lambda item: (item[0], item[1]))
    necessary_label = necessary[0][1] if necessary else None
    return sufficient_label, necessary_label


def next_round_conditionals(
    base: Mapping[str, object],
    rest: Mapping[str, int],
    games: Iterable[tuple[str, str]],
    team: str,
    cutoff: int = 8,
    *,
    max_other_matches: int = 8,
) -> dict[str, object]:
    """Enumera condicionales exactos de la próxima jornada.

    ``season_state`` replica la convención del motor LPF: ``in`` significa que el
    objetivo ya queda asegurado aun con desempate adverso; ``out`` que ya es
    inalcanzable; ``pelea`` que sigue abierto. ``round_state`` describe sólo cómo
    termina la jornada por puntos y separa los empates que exigirían desempate.
    """
    if team not in base:
        return {"available": False, "reason": "Equipo desconocido."}
    relevant = _dedupe_relevant(base, games)
    own = next((match for match in relevant if team in match), None)
    if own is None:
        return {"available": False, "reason": "El equipo no tiene partido en la próxima jornada seleccionada."}
    others = [match for match in relevant if match != own]
    if len(others) > int(max_other_matches):
        return {
            "available": False,
            "reason": f"Hay {len(others)} partidos ajenos relevantes; el máximo para enumerar exactamente es {max_other_matches}.",
        }

    all_games = [own, *others]
    rest_after = _rest_after_round(base, rest, all_games)
    branches = []
    for branch in _OWN_BRANCHES:
        own_code = _own_code(own, team, branch)
        rows = []
        for other_outcomes in product(OUTCOMES, repeat=len(others)):
            points = _apply(base, all_games, (own_code, *other_outcomes))
            season = _season_state(points, rest_after, team, int(cutoff))
            round_state = _round_state(points, team, int(cutoff))
            proof_metrics = _proof_metrics(points, rest_after, team, int(cutoff))
            rows.append({
                "other_outcomes": other_outcomes,
                "season_state": season,
                "round_state": round_state,
                "season_in": season == "in",
                "season_out": season == "out",
                "season_pelea": season == "pelea",
                "round_safe": round_state == "safe",
                "proof": proof_metrics,
            })

        total = max(1, len(rows))
        counts = {
            "season_in": sum(row["season_state"] == "in" for row in rows),
            "season_pelea": sum(row["season_state"] == "pelea" for row in rows),
            "season_out": sum(row["season_state"] == "out" for row in rows),
            "round_safe": sum(row["round_state"] == "safe" for row in rows),
            "round_tiebreak": sum(row["round_state"] == "tiebreak" for row in rows),
            "round_out": sum(row["round_state"] == "out" for row in rows),
        }
        target_key = "season_in" if counts["season_in"] else "round_safe"
        sufficient, necessary = _simple_conditions(rows, others, target_key)
        elimination_sufficient, elimination_necessary = _simple_conditions(rows, others, "season_out")
        worst_threat = max(rows, key=lambda row: (int(row["proof"]["threat_count"]), tuple(row["other_outcomes"])))
        weakest_elimination = min(rows, key=lambda row: (int(row["proof"]["unreachable_count"]), tuple(row["other_outcomes"])))
        proof = {
            "verified_combinations": total,
            "team_points": int(worst_threat["proof"]["team_points"]),
            "team_ceiling": int(worst_threat["proof"]["team_ceiling"]),
            "max_threat_count": int(worst_threat["proof"]["threat_count"]),
            "worst_threats": list(worst_threat["proof"]["threats"]),
            "min_unreachable_count": int(weakest_elimination["proof"]["unreachable_count"]),
            "weakest_unreachable": list(weakest_elimination["proof"]["unreachable"]),
            "cutoff": int(cutoff),
        }

        levers = []
        for idx, match in enumerate(others):
            values = []
            for code in OUTCOMES:
                subset = [row for row in rows if row["other_outcomes"][idx] == code]
                success = sum(row[target_key] for row in subset)
                values.append({
                    "code": code,
                    "label": _outcome_label(match, code),
                    "success": success,
                    "total": len(subset),
                    "share": (100.0 * success / len(subset)) if subset else 0.0,
                })
            shares = [item["share"] for item in values]
            levers.append({
                "match": f"{match[0]} – {match[1]}",
                "target": "Asegura playoffs" if target_key == "season_in" else "Termina la fecha adentro sin desempate",
                "spread": max(shares) - min(shares) if shares else 0.0,
                "outcomes": values,
            })
        levers.sort(key=lambda item: (-item["spread"], item["match"]))

        final_points = int((base[team] or {}).get("pts", 0)) + _outcome_points(own_code)[0 if own[0] == team else 1]
        branches.append({
            "result": branch,
            "result_label": {"G": "Si gana", "E": "Si empata", "P": "Si pierde"}[branch],
            "final_points_after_round": final_points,
            "total_combinations": len(rows),
            **counts,
            "target": "season_in" if target_key == "season_in" else "round_safe",
            "sufficient_condition": sufficient,
            "necessary_condition": necessary,
            "elimination_sufficient_condition": elimination_sufficient,
            "elimination_necessary_condition": elimination_necessary,
            "levers": levers,
            "proof": proof,
        })

    return {
        "available": True,
        "team": team,
        "cutoff": int(cutoff),
        "own_match": own,
        "other_matches": others,
        "branches": branches,
        "frequency_note": "Frecuencia combinatoria: cada combinación de resultados ajenos cuenta una vez; no es una probabilidad.",
    }



def branch_explanation(branch: Mapping[str, object], objective_label: str = "el objetivo") -> str:
    """Explicación breve y auditable de una rama exacta G/E/P.

    Explica tanto por qué una rama asegura/elimina como por qué un resultado
    todavía no alcanza por sí solo. Los conteos son enumeraciones exactas, nunca
    probabilidades.
    """
    total = max(1, int(branch.get("total_combinations", 0) or 0))
    inside = int(branch.get("season_in", 0) or 0)
    outside = int(branch.get("season_out", 0) or 0)
    open_ = int(branch.get("season_pelea", 0) or 0)
    round_safe = int(branch.get("round_safe", 0) or 0)
    proof = dict(branch.get("proof") or {})
    team_points = int(proof.get("team_points", branch.get("final_points_after_round", 0)) or 0)
    cutoff = int(proof.get("cutoff", 0) or 0)
    label = str(branch.get("result_label") or "Ese resultado")

    if inside == total:
        max_threats = int(proof.get("max_threat_count", 0) or 0)
        rivals = [str(name) for name, _value in list(proof.get("worst_threats") or [])[:6]]
        suffix = f" Los que todavía podrían igualarlo o superarlo en el caso más adverso son: {', '.join(rivals)}." if rivals else ""
        return (
            f"{label}, el equipo queda con {team_points} puntos. Se comprobaron exactamente {total} combinaciones "
            f"de las otras canchas y, aun en la más adversa, como máximo {max_threats} rivales pueden terminar "
            f"con {team_points} puntos o más. Como el corte admite {cutoff} equipos, queda asegurado el objetivo: {objective_label}.{suffix}"
        )

    if outside == total:
        ceiling = int(proof.get("team_ceiling", team_points) or team_points)
        blocked = int(proof.get("min_unreachable_count", 0) or 0)
        rivals = [str(name) for name, _value in list(proof.get("weakest_unreachable") or [])[:6]]
        suffix = f" Incluso en el caso menos desfavorable ya quedan por encima: {', '.join(rivals)}." if rivals else ""
        return (
            f"{label}, su techo final pasa a ser {ceiling} puntos. En las {total} combinaciones verificadas hay al menos "
            f"{blocked} rivales que ya quedan fuera de su alcance; con un corte de {cutoff}, queda fuera de alcance el objetivo: {objective_label}.{suffix}"
        )

    favorable = str(branch.get("sufficient_condition") or "").strip()
    necessary = str(branch.get("necessary_condition") or "").strip()
    adverse = str(branch.get("elimination_sufficient_condition") or "").strip()
    adverse_necessary = str(branch.get("elimination_necessary_condition") or "").strip()
    target = str(branch.get("target") or "season_in")
    parts = [f"{label}, el equipo queda con {team_points} puntos."]

    # Primero responde a la pregunta más importante: por qué ese resultado solo no basta.
    if inside < total:
        if inside:
            parts.append(
                f"Ese resultado por sí solo no asegura {objective_label}: hay {total - inside} combinaciones exactas de las otras canchas "
                "en las que la garantía no se produce."
            )
        elif target == "round_safe" and round_safe:
            parts.append(
                f"Ese resultado no puede asegurar todavía {objective_label}: en ninguna de las {total} combinaciones queda cerrado el objetivo, "
                "aunque sí puede terminar esta fecha dentro del corte por puntos."
            )
        else:
            parts.append(
                f"Ese resultado no puede asegurar todavía {objective_label}: ninguna de las {total} combinaciones exactas cierra el objetivo a favor."
            )

    if inside:
        if favorable and favorable != "No depende de otros resultados":
            parts.append(
                f"A favor, **{favorable}** es una condición suficiente: una vez cumplida, todas las combinaciones restantes compatibles "
                f"dejan asegurado el objetivo: {objective_label}."
            )
        elif necessary:
            parts.append(
                f"En todos los caminos que sí aseguran aparece **{necessary}**, pero esa condición es necesaria y no necesariamente suficiente por sí sola."
            )
        else:
            parts.append(
                f"Sí existen {inside} combinaciones exactas que lo aseguran, pero no se reducen a una condición simple de una o dos canchas."
            )
    elif round_safe:
        if favorable and favorable != "No depende de otros resultados":
            parts.append(
                f"**{favorable}** sí alcanza para terminar la fecha dentro del corte por puntos, pero eso no equivale a haber asegurado {objective_label}."
            )
        elif necessary:
            parts.append(
                f"Para terminar la fecha dentro del corte aparece como condición necesaria **{necessary}**, sin que eso cierre todavía {objective_label}."
            )

    if outside:
        if adverse and adverse != "No depende de otros resultados":
            parts.append(
                f"En contra, **{adverse}** es una condición suficiente para dejar fuera de alcance el objetivo ({objective_label}) en esta rama."
            )
        elif adverse_necessary:
            parts.append(
                f"Todos los caminos que lo dejan matemáticamente afuera comparten **{adverse_necessary}**, aunque esa condición sola puede no bastar para eliminarlo."
            )
        else:
            parts.append(
                f"También hay {outside} combinaciones exactas que lo dejan matemáticamente afuera, sin una condición simple común de una o dos canchas."
            )
    elif open_ == total and not inside:
        parts.append(f"Tampoco puede quedar eliminado en esta fecha: el objetivo sigue abierto en las {total} combinaciones.")

    parts.append("Son condiciones matemáticas enumeradas; no son probabilidades.")
    return " ".join(parts)


def key_rival_matrix(
    base: Mapping[str, object],
    rest: Mapping[str, int],
    games: Iterable[tuple[str, str]],
    team: str,
    key_team: str,
    cutoff: int = 8,
    *,
    max_remaining_matches: int = 7,
) -> dict[str, object]:
    """Cruza G/E/P del equipo con G/E/P de un rival de la misma fecha.

    Los demás partidos quedan abiertos y se enumeran exactamente. Una celda verde o
    roja significa que todas las combinaciones restantes llevan al mismo estado.
    """
    relevant = _dedupe_relevant(base, games)
    own = next((match for match in relevant if team in match), None)
    key_match = next((match for match in relevant if key_team in match and team not in match), None)
    if own is None:
        return {"available": False, "reason": "El equipo no juega en la fecha seleccionada."}
    if key_match is None:
        return {"available": False, "reason": "El rival elegido no tiene un partido independiente en esa fecha."}
    remaining = [match for match in relevant if match not in (own, key_match)]
    if len(remaining) > int(max_remaining_matches):
        return {"available": False, "reason": f"Quedan {len(remaining)} partidos abiertos; el máximo exacto es {max_remaining_matches}."}

    all_games = [own, key_match, *remaining]
    rest_after = _rest_after_round(base, rest, all_games)

    def team_code(match, selected_team, result):
        if result == "E":
            return "E"
        home = match[0] == selected_team
        if result == "G":
            return "L" if home else "V"
        return "V" if home else "L"

    cells = []
    for own_branch in _OWN_BRANCHES:
        own_code = team_code(own, team, own_branch)
        for key_branch in _OWN_BRANCHES:
            key_code = team_code(key_match, key_team, key_branch)
            rows = []
            for other_outcomes in product(OUTCOMES, repeat=len(remaining)):
                points = _apply(base, all_games, (own_code, key_code, *other_outcomes))
                season = _season_state(points, rest_after, team, int(cutoff))
                round_state = _round_state(points, team, int(cutoff))
                rows.append({
                    "other_outcomes": other_outcomes,
                    "season_state": season,
                    "round_state": round_state,
                    "season_in": season == "in",
                    "season_out": season == "out",
                    "season_pelea": season == "pelea",
                    "round_safe": round_state == "safe",
                    "proof": _proof_metrics(points, rest_after, team, int(cutoff)),
                })
            total = max(1, len(rows))
            counts = {
                "season_in": sum(row["season_state"] == "in" for row in rows),
                "season_pelea": sum(row["season_state"] == "pelea" for row in rows),
                "season_out": sum(row["season_state"] == "out" for row in rows),
                "round_safe": sum(row["round_state"] == "safe" for row in rows),
            }
            target_key = "season_in" if counts["season_in"] else "round_safe"
            sufficient, necessary = _simple_conditions(rows, remaining, target_key)
            elimination_sufficient, elimination_necessary = _simple_conditions(rows, remaining, "season_out")
            worst = max(rows, key=lambda row: int(row["proof"]["threat_count"]))
            weak_out = min(rows, key=lambda row: int(row["proof"]["unreachable_count"]))
            cells.append({
                "own_result": own_branch,
                "key_result": key_branch,
                "own_label": {"G": "Gana", "E": "Empata", "P": "Pierde"}[own_branch],
                "key_label": {"G": f"{key_team} gana", "E": f"{key_team} empata", "P": f"{key_team} pierde"}[key_branch],
                "total_combinations": total,
                **counts,
                "sufficient_condition": sufficient,
                "necessary_condition": necessary,
                "elimination_sufficient_condition": elimination_sufficient,
                "elimination_necessary_condition": elimination_necessary,
                "target": "season_in" if target_key == "season_in" else "round_safe",
                "proof": {
                    "verified_combinations": total,
                    "team_points": int(worst["proof"]["team_points"]),
                    "team_ceiling": int(worst["proof"]["team_ceiling"]),
                    "max_threat_count": int(worst["proof"]["threat_count"]),
                    "worst_threats": list(worst["proof"]["threats"]),
                    "min_unreachable_count": int(weak_out["proof"]["unreachable_count"]),
                    "weakest_unreachable": list(weak_out["proof"]["unreachable"]),
                    "cutoff": int(cutoff),
                },
            })
    return {
        "available": True,
        "team": team,
        "key_team": key_team,
        "own_match": own,
        "key_match": key_match,
        "remaining_matches": remaining,
        "cells": cells,
        "frequency_note": "Los demás resultados se enumeran exactamente; no se asignan probabilidades.",
    }
