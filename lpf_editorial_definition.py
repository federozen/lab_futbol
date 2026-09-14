"""Salidas editoriales exactas para la definición de objetivos LPF.

Este módulo no conoce Streamlit ni proveedores. Convierte los condicionales exactos
por fecha en estructuras cortas para matrices, semáforos, zona de pelea y reloj de
definición. No calcula probabilidades.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from lpf_conditionals import key_rival_matrix, next_round_conditionals
from lpf_qualification import allocate_cup_slots, annual_base
from lpf_scenarios import point_ladder
from lpf_schedule import pending_round_map
from lpf_standings import liga_tabla_df

LPF_RUNTIME_API = 21


def branch_state(branch: Mapping[str, object]) -> dict[str, str]:
    """Resume una rama G/E/P sin convertir frecuencias en probabilidades."""
    total = max(1, int(branch.get("total_combinations", 0) or 0))
    inside = int(branch.get("season_in", 0) or 0)
    open_ = int(branch.get("season_pelea", 0) or 0)
    outside = int(branch.get("season_out", 0) or 0)
    condition = str(branch.get("sufficient_condition") or "").strip()

    if inside == total:
        return {"signal": "green", "label": "Asegura", "detail": "No depende de otros resultados"}
    if outside == total:
        return {"signal": "red", "label": "Queda eliminado", "detail": "No hay otra cancha que lo salve"}
    if inside:
        detail = condition if condition and condition != "No depende de otros resultados" else "Existe una combinación exacta favorable"
        return {"signal": "yellow", "label": "Puede asegurar", "detail": detail}
    if outside and open_:
        return {"signal": "yellow", "label": "Puede quedar eliminado", "detail": "Depende de otros resultados"}
    if int(branch.get("round_safe", 0) or 0):
        detail = condition if condition and condition != "No depende de otros resultados" else "Puede terminar la fecha dentro"
        return {"signal": "yellow", "label": "Sigue abierto", "detail": detail}
    return {"signal": "yellow", "label": "Sigue dependiendo", "detail": "La fecha no resuelve el objetivo"}


def branch_cell(branch: Mapping[str, object], *, with_detail: bool = True) -> str:
    state = branch_state(branch)
    icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[state["signal"]]
    if with_detail and state["detail"]:
        return f"{icon} {state['label']} · {state['detail']}"
    return f"{icon} {state['label']}"


def all_teams_matrix(
    base: Mapping[str, Mapping[str, object]],
    rest: Mapping[str, int],
    games: Iterable[tuple[str, str]],
    teams: Sequence[str],
    cutoff: int,
    *,
    max_other_matches: int = 8,
) -> list[dict[str, object]]:
    """Una fila por equipo y tres columnas G/E/P con estado matemático exacto."""
    rows: list[dict[str, object]] = []
    for team in teams:
        if team not in base:
            continue
        report = next_round_conditionals(
            base, rest, games, team, cutoff, max_other_matches=max_other_matches
        )
        row: dict[str, object] = {
            "Equipo": team,
            "PTS": int((base[team] or {}).get("pts", 0)),
            "PJ por jugar": int(rest.get(team, 0)),
        }
        if not report.get("available"):
            row.update({"Si gana": "—", "Si empata": "—", "Si pierde": "—", "_report": report})
        else:
            by_result = {str(branch["result"]): branch for branch in report.get("branches", [])}
            row.update({
                "Si gana": branch_cell(by_result["G"]),
                "Si empata": branch_cell(by_result["E"]),
                "Si pierde": branch_cell(by_result["P"]),
                "_report": report,
            })
        rows.append(row)
    return rows


def fight_zone(
    base: Mapping[str, Mapping[str, object]],
    rest: Mapping[str, int],
    team: str,
    cutoff: int,
    *,
    radius: int = 2,
) -> list[dict[str, object]]:
    """Recorta la tabla alrededor del equipo y del corte del objetivo."""
    if team not in base or cutoff <= 0:
        return []
    frame = liga_tabla_df(base)
    order = list(frame["Equipo"])
    if team not in order:
        return []
    team_pos = order.index(team) + 1
    cutoff = min(int(cutoff), len(order))
    keep: set[int] = set()
    for center in (team_pos, cutoff):
        keep.update(range(max(1, center - radius), min(len(order), center + radius) + 1))
    rows: list[dict[str, object]] = []
    previous = None
    for pos in sorted(keep):
        if previous is not None and pos > previous + 1:
            rows.append({"Pos": "…", "Equipo": "…", "PTS": "…", "PJ por jugar": "…", "Techo": "…", "Referencia": ""})
        record = frame.iloc[pos - 1]
        name = str(record["Equipo"])
        refs = []
        if pos == cutoff:
            refs.append("corte")
        if name == team:
            refs.append("seleccionado")
        pts = int(record["PTS"])
        left = int(rest.get(name, 0))
        rows.append({
            "Pos": f"{pos}º",
            "Equipo": name,
            "PTS": pts,
            "PJ por jugar": left,
            "Techo": pts + 3 * left,
            "Referencia": " · ".join(refs),
        })
        previous = pos
    return rows


def definition_clock(
    report: Mapping[str, object] | None,
    *,
    current_points: int,
    guarantee: int | None = None,
    guarantee_round_label: str | None = None,
) -> list[dict[str, str]]:
    """Hitos exactos y breves para una línea temporal editorial.

    El primer hito sale de la próxima fecha enumerada. El segundo, si existe, sólo
    dice cuándo el equipo puede alcanzar por sus propios puntos un total que ya fue
    demostrado como garantía exacta.
    """
    milestones: list[dict[str, str]] = []
    if report and report.get("available"):
        branches = list(report.get("branches", []))
        can_in = [b for b in branches if int(b.get("season_in", 0) or 0) > 0]
        sure_in = [b for b in branches if int(b.get("season_in", 0) or 0) == max(1, int(b.get("total_combinations", 0) or 0))]
        can_out = [b for b in branches if int(b.get("season_out", 0) or 0) > 0]
        if sure_in:
            labels = ", ".join(str(b.get("result_label", "")) for b in sure_in)
            milestones.append({"when": "Próxima fecha", "status": "Puede asegurar", "detail": f"{labels}: no depende de nadie."})
        elif can_in:
            best = can_in[0]
            condition = str(best.get("sufficient_condition") or "hay una combinación favorable")
            milestones.append({"when": "Próxima fecha", "status": "Puede asegurar", "detail": f"{best.get('result_label')}: {condition}."})
        if can_out:
            labels = ", ".join(str(b.get("result_label", "")) for b in can_out)
            milestones.append({"when": "Próxima fecha", "status": "Puede quedar eliminado", "detail": labels})
        if not can_in and not can_out:
            milestones.append({"when": "Próxima fecha", "status": "No puede definirse", "detail": "El objetivo seguirá abierto pase lo que pase en esta fecha."})

    if guarantee is not None and int(guarantee) > int(current_points):
        needed = int(guarantee) - int(current_points)
        wins = (needed + 2) // 3
        label = guarantee_round_label or f"Tras {wins} partido(s) propios"
        milestones.append({
            "when": label,
            "status": "Puede llegar al total que asegura",
            "detail": f"Necesita sumar al menos {needed} puntos para alcanzar {int(guarantee)}.",
        })
    elif guarantee is not None and int(guarantee) <= int(current_points):
        milestones.append({"when": "Hoy", "status": "Ya alcanzó el total que asegura", "detail": f"Tiene {int(current_points)} puntos; la garantía exacta es {int(guarantee)}."})
    return milestones


def objective_context(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]] | None,
    *,
    objective: str,
    zone: str | None = None,
    opening: Mapping[str, Mapping[str, object]] | None = None,
    direct_annual: Mapping[str, Mapping[str, object]] | None = None,
    opening_rounds: int,
    camps: Sequence[object] = ("", "", ""),
    extras: Sequence[object] = ("", ""),
    copa_replacement: object = "",
    playoff_cutoff: int = 8,
    sudamericana_slots: int = 6,
) -> dict[str, object] | None:
    """Construye el universo exacto del objetivo sin conocer Streamlit.

    Playoffs usa una zona. Libertadores/Sudamericana usan la Tabla Anual reducida
    después de retirar únicamente las plazas directas ya resueltas. La función no
    consulta sesión ni proveedores, por lo que una API puede reutilizarla.
    """
    zones = zones or {}
    annual = annual_base(
        zones, opening=opening or {}, direct_annual=direct_annual or {}, opening_rounds=int(opening_rounds)
    )
    normalized = str(objective or "").strip()
    if normalized == "Playoffs":
        label = zone if zone in zones else (sorted(zones)[0] if zones else None)
        if label is None:
            return None
        base = zones[label]
        return {
            "base": base,
            "cutoff": min(int(playoff_cutoff), len(base)),
            "label": "Playoffs",
            "scope": f"Zona {label}",
            "zone": label,
            "direct": [],
            "annual": annual,
            "allocation": None,
        }

    if normalized not in {"Libertadores", "Al menos Sudamericana", "Sudamericana"} or not annual:
        return None
    allocation = allocate_cup_slots(
        annual, camps=camps, extras=extras, copa_replacement=copa_replacement
    )
    reduced = [team for team in allocation.get("reducida", []) if team in annual]
    base = {team: annual[team] for team in reduced}
    n_lib = int(allocation.get("n_tabla_lib") or 0)
    cutoff = n_lib if normalized == "Libertadores" else n_lib + int(sudamericana_slots)
    direct = [team for team in allocation.get("orden", []) if team not in set(reduced)]
    label = (
        "Libertadores por Tabla Anual"
        if normalized == "Libertadores"
        else "Al menos Sudamericana por Tabla Anual"
    )
    return {
        "base": base,
        "cutoff": min(cutoff, len(base)),
        "label": label,
        "scope": "Tabla Anual sin clasificados directos a Libertadores",
        "zone": None,
        "direct": direct,
        "annual": annual,
        "allocation": allocation,
    }


def definition_guarantee(
    base: Mapping[str, Mapping[str, object]],
    pending: Iterable[tuple[str, str]],
    team: str,
    cutoff: int,
    rest: Mapping[str, int],
    *,
    exact_window: int = 8,
    max_rows: int = 4,
    max_matches: int = 110,
) -> tuple[int | None, Mapping[str, object] | None]:
    """Mínimo que asegura demostrado por el solver exacto, si entra en ventana."""
    left = int(rest.get(team, 0))
    if not (0 < left <= int(exact_window)):
        return None, None
    exact = point_ladder(base, list(pending or []), team, int(cutoff), max_rows=max_rows, max_matches=max_matches)
    if not exact.get("available"):
        return None, exact
    guarantee = exact.get("guarantee")
    return (int(guarantee) if guarantee is not None else None), exact


def guarantee_round_label(
    team: str,
    pending: Iterable[tuple[str, str]],
    fixture: Sequence[Mapping[str, object]],
    current_points: int,
    guarantee: int | None,
) -> str | None:
    """Primera fecha oficial en la que puede alcanzar el total que ya asegura."""
    if guarantee is None:
        return None
    if int(guarantee) <= int(current_points):
        return "Hoy"
    games_needed = (int(guarantee) - int(current_points) + 2) // 3
    fmap = pending_round_map(list(pending or []), fixture or [])
    rounds = sorted({rnd for match, rnd in fmap.items() if rnd is not None and team in match})
    if games_needed > 0 and len(rounds) >= games_needed:
        return f"Fecha {rounds[games_needed - 1]}"
    return f"Tras {games_needed} partido(s) propios"


def definition_snapshot(
    base: Mapping[str, Mapping[str, object]],
    rest: Mapping[str, int],
    round_games: Iterable[tuple[str, str]],
    team: str,
    cutoff: int,
    *,
    selected_teams: Sequence[str] | None = None,
    all_pending: Iterable[tuple[str, str]] | None = None,
    fixture: Sequence[Mapping[str, object]] | None = None,
    key_team: str | None = None,
    fight_radius: int = 2,
    exact_window: int = 8,
    max_other_matches: int = 8,
) -> dict[str, object]:
    """Paquete JSON-safe de definición para otra interfaz o una futura API.

    ``round_games`` contiene la fecha que se quiere cruzar; ``all_pending`` se usa
    sólo para la garantía del torneo. No se incorporan probabilidades.
    """
    if team not in base:
        return {"available": False, "reason": "Equipo desconocido."}
    games = list(round_games or [])
    pending = list(all_pending or games)
    report = next_round_conditionals(
        base, rest, games, team, int(cutoff), max_other_matches=max_other_matches
    )
    chosen = [name for name in (selected_teams or [team]) if name in base]
    matrix = all_teams_matrix(
        base, rest, games, chosen, int(cutoff), max_other_matches=max_other_matches
    )
    guarantee, ladder = definition_guarantee(
        base, pending, team, int(cutoff), rest, exact_window=exact_window
    )
    current = int((base[team] or {}).get("pts", 0))
    round_label = guarantee_round_label(team, pending, fixture or [], current, guarantee)
    key = None
    if key_team:
        key = key_rival_matrix(base, rest, games, team, key_team, int(cutoff))
    return {
        "available": bool(report.get("available")),
        "team": team,
        "cutoff": int(cutoff),
        "fight_zone": fight_zone(base, rest, team, int(cutoff), radius=fight_radius),
        "matrix": matrix,
        "report": report,
        "key_rival": key,
        "guarantee": guarantee,
        "guarantee_round_label": round_label,
        "clock": definition_clock(
            report, current_points=current, guarantee=guarantee, guarantee_round_label=round_label
        ),
        "ladder": ladder,
        "probability_note": "No usa probabilidades: todos los estados provienen de cuentas exactas.",
    }
