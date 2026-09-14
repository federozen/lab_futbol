"""Narrativas editoriales puras para las competencias LPF 2026.

El modulo no consulta fuentes ni usa Streamlit. Recibe datos ya validados por el
motor y devuelve Markdown. De este modo el chat, los informes y las pantallas
pueden reutilizar exactamente el mismo relato.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from lpf_scenarios import exact_result_scenarios, scenario_rank_bounds
from lpf_display import editorialize_text
from lpf_pisos import VENTANA_EXACTA
from lpf_relegation import current_relegation_picture


def _num(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _signed(value: object) -> str:
    return f"{_num(value):+d}"


def _decimal_es(value: object, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return ("0," + "0" * digits) if digits else "0"


def ordered_rows(base: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    # Si PTS, DG y GF coinciden, se conserva el puesto publicado por la fuente.
    # La inserción queda como último respaldo para cargas manuales sin metadata.
    source_order = {team: index for index, team in enumerate(base)}
    ordered = sorted(
        base.items(),
        key=lambda item: (
            -_num(item[1].get("pts")),
            -_num(item[1].get("dg")),
            -_num(item[1].get("gf")),
            _num(item[1].get("source_pos"), 10_000 + source_order[item[0]]),
            source_order[item[0]],
        ),
    )
    return [
        {
            "pos": index,
            "team": team,
            "pts": _num(data.get("pts")),
            "pj": _num(data.get("pj")),
            "dg": _num(data.get("dg")),
            "gf": _num(data.get("gf")),
            "gf_known": "gf" in data and data.get("gf") is not None,
            "ga": _num(data.get("ga")),
        }
        for index, (team, data) in enumerate(ordered, 1)
    ]


def _renumber_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Renombra 1..N para la lógica de cupos sin perder el puesto real de la Anual."""
    return [
        {**dict(row), "annual_pos": _num(row.get("pos")), "pos": index}
        for index, row in enumerate(rows, 1)
    ]


def _gf(row: Mapping[str, object]) -> str:
    return str(_num(row.get("gf"))) if bool(row.get("gf_known")) else "s/d"


def _pts(value: object) -> str:
    number = _num(value)
    return f"{number} punto" if number == 1 else f"{number} puntos"


def _team_list(items: Sequence[str]) -> str:
    if not items:
        return "—"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _direct_qualifier_note_above(
    all_rows: Sequence[Mapping[str, object]],
    raw_pos: int,
    fixed_qualified: Sequence[str],
) -> str:
    """Nota breve: no crea una segunda numeración, sólo avisa si arriba hay un clasificado directo."""
    fixed = set(fixed_qualified)
    above = [
        str(row.get("team"))
        for row in all_rows
        if _num(row.get("pos")) < int(raw_pos) and str(row.get("team")) in fixed
    ]
    if not above:
        return ""
    bold = [f"**{team}**" for team in above]
    if len(bold) == 1:
        return f" (Entre los equipos que tiene arriba, {bold[0]} ya tiene una plaza directa de Libertadores.)"
    return f" (Entre los equipos que tiene arriba, {_team_list(bold)} ya tienen una plaza directa de Libertadores.)"


def _rank_label(best: int | None, worst: int | None) -> str:
    if best is None or worst is None:
        return "sin rango disponible"
    if best == worst:
        return f"{best}º"
    return f"entre {best}º y {worst}º"


def _short_rank_window(best: int, worst: int, max_positions: int = 5) -> bool:
    """Mantiene el rango completo sólo cuando sigue siendo editorialmente legible."""
    return max(0, int(worst) - int(best) + 1) <= max_positions


def _round_team_snapshot(
    team: str,
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    cutoff: int,
) -> dict[str, object] | None:
    for label, base in zones.items():
        if team not in base:
            continue
        rows = ordered_rows(base)
        row = next((item for item in rows if item["team"] == team), None)
        if row is None:
            return None
        cut_index = min(max(1, cutoff), len(rows)) - 1
        cut = rows[cut_index]
        gap = _num(cut["pts"]) - _num(row["pts"])
        if _num(row["pos"]) == 1:
            situation = "lidera"
        elif _num(row["pos"]) == cutoff:
            situation = "ocupa el último puesto de clasificación"
        elif _num(row["pos"]) < cutoff:
            situation = "está dentro de los puestos de playoffs"
        elif gap == 0:
            situation = "está afuera por desempate"
        elif gap == 1:
            situation = "está a un punto del corte"
        else:
            situation = f"está a {gap} puntos del corte"
        return {
            "zone": str(label),
            "base": base,
            "row": row,
            "cut": cut,
            "situation": situation,
        }
    return None


def _round_zone_sentence(
    label: str,
    base: Mapping[str, Mapping[str, object]],
    *,
    cutoff: int,
) -> str:
    rows = ordered_rows(base)
    if not rows:
        return f"**Zona {label}:** sin datos."
    cut_index = min(max(1, cutoff), len(rows)) - 1
    leader = rows[0]
    cut = rows[cut_index]
    first_out = rows[cut_index + 1] if cut_index + 1 < len(rows) else None
    text = (
        f"**Zona {label}.** {leader['team']} lidera con {_pts(leader['pts'])} en {leader['pj']} PJ "
        f"y DG {_signed(leader['dg'])}. {cut['team']} ocupa el {cutoff}º y último puesto de clasificación "
        f"con {_pts(cut['pts'])} en {cut['pj']} PJ y DG {_signed(cut['dg'])}"
    )
    if first_out:
        text += (
            f"; {first_out['team']} es el primero afuera con {_pts(first_out['pts'])} en "
            f"{first_out['pj']} PJ y DG {_signed(first_out['dg'])}."
        )
        if cut["pts"] == first_out["pts"]:
            text += " Hoy la frontera se define por los criterios de desempate."
    else:
        text += "."
    return text

def _round_match_hook(local: dict[str, object], visitor: dict[str, object], *, cutoff: int) -> str:
    lp = _num(local["row"]["pos"])  # type: ignore[index]
    vp = _num(visitor["row"]["pos"])  # type: ignore[index]
    lr = local["row"]  # type: ignore[assignment]
    vr = visitor["row"]  # type: ignore[assignment]
    same_zone = local["zone"] == visitor["zone"]
    if not same_zone:
        return (
            f"{lr['team']} {local['situation']} y {vr['team']} {visitor['situation']}. "
            "Al ser un interzonal, el resultado mueve simultáneamente las dos zonas."
        )
    if abs(lp - cutoff) <= 2 and abs(vp - cutoff) <= 2:
        if _num(lr["pts"]) == _num(vr["pts"]):
            return (
                f"La frontera pasa por este partido: los dos tienen {_pts(lr['pts'])}, pero "
                f"{lr['team']} está {lp}º y {vr['team']} {vp}º por los criterios de desempate."
            )
        return "Es un cruce directo alrededor del último puesto de clasificación."
    if lp == 1 or vp == 1:
        leader = lr["team"] if lp == 1 else vr["team"]
        return f"{leader} defiende la punta."
    if lp <= cutoff and vp <= cutoff:
        return "Es un duelo entre dos equipos que comienzan la ventana dentro de los puestos de playoffs."
    if (lp <= cutoff) != (vp <= cutoff):
        inside = lr["team"] if lp <= cutoff else vr["team"]
        outside = vr["team"] if lp <= cutoff else lr["team"]
        return f"{inside} defiende un lugar de playoffs y {outside} busca entrar entre los ocho primeros."
    if _num(lr["pts"]) == 0 or _num(vr["pts"]) == 0:
        zero = lr["team"] if _num(lr["pts"]) == 0 else vr["team"]
        other = vr["team"] if zero == lr["team"] else lr["team"]
        return (
            f"{other} busca acercarse a los puestos de playoffs y {zero} necesita sumar sus primeros puntos "
            "para empezar a reducir la distancia."
        )
    return "Los dos necesitan sumar para acercarse a los puestos de playoffs."

def _round_probability_sentence(
    local: str,
    visitor: str,
    probability: Sequence[float] | None,
) -> str:
    if not probability or len(probability) < 3:
        return ""
    pl, pe, pv = (float(probability[0]), float(probability[1]), float(probability[2]))
    values = [(pl, local), (pv, visitor)]
    values.sort(reverse=True)
    favorite = values[0]
    if favorite[0] < 0.40 or abs(pl - pv) < 0.08:
        lead = "La estimación no marca un favorito fuerte"
    else:
        lead = f"La estimación da una leve ventaja a {favorite[1]}"
    return (
        f"{lead} ({round(100 * pl)}% triunfo local, {round(100 * pe)}% empate y "
        f"{round(100 * pv)}% triunfo visitante). Es una frecuencia del modelo, no una cuota ni un pronóstico exacto."
    )

def _window_rank_sentence(
    team: str,
    snapshot: Mapping[str, object],
    games: Sequence[tuple[str, str]],
    *,
    cutoff: int,
    appearances: int,
    bounds_cache: dict[tuple[str, str], dict[str, object]],
) -> str:
    base = snapshot["base"]  # type: ignore[assignment]
    zone = str(snapshot["zone"])
    key = (zone, team)
    if key not in bounds_cache:
        zone_games = [match for match in games if match[0] in base or match[1] in base]
        bounds_cache[key] = scenario_rank_bounds(base, zone_games, team)
    bounds = bounds_cache[key]
    if not bounds.get("available"):
        return ""
    best = int(bounds["best_rank"])
    worst = int(bounds["worst_rank"])
    current = _num(snapshot["row"]["pos"])  # type: ignore[index]
    games_text = (
        f"disputa {appearances} partidos en la ventana" if appearances > 1
        else "disputa un partido en la ventana"
    )
    if best > cutoff:
        return (
            f"{team} {games_text} y no puede entrar entre los ocho primeros: su mejor puesto posible por puntos "
            f"es el {best}º."
        )
    short_window = _short_rank_window(best, worst)
    if current <= cutoff and worst <= cutoff:
        if best == 1:
            lead = "puede conservar la punta" if current == 1 else "puede alcanzar la punta por puntos"
            if short_window:
                return (
                    f"{team} ya tiene asegurado cerrar esta ventana entre los ocho primeros; {lead} "
                    f"y su peor ubicación posible es el {worst}º puesto."
                )
            return f"{team} ya tiene asegurado cerrar esta ventana entre los ocho primeros y {lead}."
        if short_window:
            return (
                f"{team} ya tiene asegurado cerrar esta ventana entre los ocho primeros; su rango posible por puntos es "
                f"{_rank_label(best, worst)}."
            )
        return (
            f"{team} ya tiene asegurado cerrar esta ventana entre los ocho primeros. "
            f"Puede subir hasta el {best}º puesto por puntos."
        )
    if current <= cutoff:
        if short_window:
            return (
                f"{team} comienza dentro de los puestos de playoffs y puede cerrar la ventana "
                f"{_rank_label(best, worst)} por puntos. Tiene escenarios en los que conserva la clasificación y otros "
                "en los que queda afuera."
            )
        lead = "puede alcanzar la punta por puntos" if best == 1 else f"puede subir hasta el {best}º lugar por puntos"
        return (
            f"{team} comienza dentro de los puestos de playoffs. {lead[:1].upper() + lead[1:]}, "
            "pero también tiene escenarios en los que termina la fecha fuera de los ocho."
        )
    if short_window:
        return (
            f"{team} parte fuera de los puestos de playoffs y puede cerrar la ventana "
            f"{_rank_label(best, worst)} por puntos. Tiene escenarios para entrar entre los ocho y otros en los que "
            "continúa afuera."
        )
    lead = "puede alcanzar la punta por puntos" if best == 1 else f"puede subir hasta el {best}º puesto por puntos"
    return (
        f"{team} parte fuera de los playoffs. {lead[:1].upper() + lead[1:]} y tiene escenarios para entrar entre "
        "los ocho. También puede terminar la fecha todavía afuera."
    )


def _round_result_branch(
    team: str,
    base: Mapping[str, Mapping[str, object]],
    games: Sequence[tuple[str, str]],
    own_match: tuple[str, str],
    *,
    cutoff: int,
) -> str:
    relevant_games = [match for match in games if match[0] in base or match[1] in base]
    rows = exact_result_scenarios(base, relevant_games, team, own_match, cutoff)
    if not rows or any(row.get("best_rank") is None or row.get("worst_rank") is None for row in rows):
        return ""
    labels = []
    for row in rows:
        labels.append(
            f"si {str(row['result']).lower()}, {_rank_label(int(row['best_rank']), int(row['worst_rank']))}"
        )
    return f"**{team}:** " + "; ".join(labels) + "."


def _objective_state(
    team: str,
    base: Mapping[str, Mapping[str, object]],
    remaining: Mapping[str, int],
    cutoff: int,
) -> str:
    """Estado matemático simple: adentro, afuera o en pelea.

    Replica la cuenta exacta usada por la aplicación: compara el puntaje actual
    con los techos de todos los rivales. No usa probabilidades ni proyecta DG.
    """
    if team not in base or cutoff <= 0:
        return "out"
    points = {name: _num(data.get("pts")) for name, data in base.items()}
    ceilings = {
        name: points[name] + 3 * max(0, _num(remaining.get(name, 0)))
        for name in base
    }
    can_finish_above = sum(
        1 for rival in base if rival != team and ceilings[rival] > points[team]
    )
    already_unreachable = sum(
        1 for rival in base if rival != team and points[rival] > ceilings[team]
    )
    if can_finish_above < cutoff:
        return "in"
    if already_unreachable >= cutoff:
        return "out"
    return "pelea"


def _result_rank_summary(
    team: str,
    base: Mapping[str, Mapping[str, object]],
    games: Sequence[tuple[str, str]],
    own_match: tuple[str, str],
    *,
    cutoff: int,
    target_label: str,
) -> str:
    if team not in base or cutoff <= 0:
        return ""
    relevant_games = [match for match in games if match[0] in base or match[1] in base]
    rows = exact_result_scenarios(base, relevant_games, team, own_match, cutoff)
    if not rows:
        return ""
    parts = []
    for row in rows:
        best, worst = row.get("best_rank"), row.get("worst_rank")
        if best is None or worst is None:
            continue
        rank = _rank_label(int(best), int(worst))
        if bool(row.get("can_enter")) and not bool(row.get("can_fail")):
            verdict = f"queda dentro de {target_label}"
        elif not bool(row.get("can_enter")):
            verdict = f"no alcanza {target_label} en esta ventana"
        else:
            verdict = f"puede quedar dentro o fuera de {target_label}"
        parts.append(f"si {str(row.get('result', '')).lower()}, {rank} ({verdict})")
    return "; ".join(parts)


def _cup_result_rank_summary(
    team: str,
    base: Mapping[str, Mapping[str, object]],
    games: Sequence[tuple[str, str]],
    own_match: tuple[str, str],
    *,
    lib_cut: int,
    sud_cut: int,
    target: str,
    rank_base: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    """Ramas de copa: el veredicto usa la lógica de cupos, el puesto visible siempre es el de la Anual."""
    if team not in base or sud_cut <= 0:
        return ""
    relevant_games = [match for match in games if match[0] in base or match[1] in base]
    cup_rows = exact_result_scenarios(base, relevant_games, team, own_match, sud_cut)
    rank_source = rank_base or base
    rank_games = [match for match in games if match[0] in rank_source or match[1] in rank_source]
    rank_rows = exact_result_scenarios(rank_source, rank_games, team, own_match, len(rank_source))
    ranks_by_result = {str(row.get("result", "")).lower(): row for row in rank_rows}
    parts: list[str] = []
    for row in cup_rows:
        best, worst = row.get("best_rank"), row.get("worst_rank")
        if best is None or worst is None:
            continue
        best_i, worst_i = int(best), int(worst)
        rank_row = ranks_by_result.get(str(row.get("result", "")).lower(), row)
        rank_best, rank_worst = rank_row.get("best_rank"), rank_row.get("worst_rank")
        if rank_best is None or rank_worst is None:
            continue
        rank = _rank_label(int(rank_best), int(rank_worst))
        if target == "Libertadores":
            if worst_i <= lib_cut:
                verdict = "queda en zona de Libertadores"
            elif best_i <= lib_cut:
                verdict = "puede quedar dentro o fuera de Libertadores"
            else:
                verdict = "no llega a zona de Libertadores en esta ventana"
        else:
            if lib_cut > 0 and worst_i <= lib_cut:
                verdict = "queda en zona de Libertadores"
            elif best_i <= lib_cut and worst_i <= sud_cut:
                verdict = "queda en puestos de copas y puede subir a Libertadores"
            elif best_i > lib_cut and worst_i <= sud_cut:
                verdict = "queda en zona de Sudamericana"
            elif best_i <= sud_cut:
                verdict = "puede quedar dentro o fuera de los puestos de copas"
            else:
                verdict = "queda fuera de los puestos de copas en esta ventana"
        parts.append(
            f"si {str(row.get('result', '')).lower()}, en la Tabla Anual puede quedar {rank} ({verdict})"
        )
    return "; ".join(parts)


def _cup_stake_for_team(
    team: str,
    annual: Mapping[str, Mapping[str, object]],
    games: Sequence[tuple[str, str]],
    own_match: tuple[str, str],
    *,
    remaining: Mapping[str, int],
    fixed_qualified: Sequence[str],
    table_slots_lib: int,
    detailed: bool,
) -> str:
    if not annual or team not in annual or team in set(fixed_qualified):
        return ""
    all_rows = ordered_rows(annual)
    raw_row = next((row for row in all_rows if row["team"] == team), None)
    effective = _renumber_rows(
        [row for row in all_rows if row["team"] not in set(fixed_qualified)]
    )
    effective_base = {
        str(row["team"]): annual[str(row["team"])]
        for row in effective
        if str(row["team"]) in annual
    }
    row = next((item for item in effective if item["team"] == team), None)
    if row is None or raw_row is None:
        return ""

    lib_cut = max(0, int(table_slots_lib))
    sud_cut = min(len(effective), lib_cut + 6)
    pos = _num(row["pos"])  # sólo para decidir cupos; nunca se muestra como una segunda posición.
    lib_state = _objective_state(team, effective_base, remaining, lib_cut) if lib_cut else "out"
    sud_state = _objective_state(team, effective_base, remaining, sud_cut) if sud_cut else "out"

    lib_boundary = effective[lib_cut - 1] if 0 < lib_cut <= len(effective) else None
    sud_boundary = effective[sud_cut - 1] if 0 < sud_cut <= len(effective) else None
    lib_gap = max(0, _num(lib_boundary["pts"]) - _num(row["pts"])) if lib_boundary else 999
    sud_gap = max(0, _num(sud_boundary["pts"]) - _num(row["pts"])) if sud_boundary else 999
    late_stage = max(0, _num(remaining.get(team, 0))) <= VENTANA_EXACTA
    near_lib = lib_cut > 0 and lib_state != "out" and (
        pos <= lib_cut or lib_gap <= 3 or (late_stage and lib_gap <= 6)
    )
    near_sud = sud_cut > 0 and sud_state != "out" and (
        pos <= sud_cut or sud_gap <= 3 or (late_stage and sud_gap <= 6)
    )
    if not near_lib and not near_sud:
        return ""

    if lib_cut and pos <= lib_cut:
        target = "Libertadores"
        status = "hoy ocupa un cupo de Libertadores por la Tabla Anual"
    elif near_lib:
        target = "Libertadores"
        status = (
            "ya aseguró terminar en zona de Libertadores por la Anual"
            if lib_state == "in"
            else (
                "sigue en carrera por la Libertadores; está igualado en puntos con el último cupo y hoy queda afuera por desempate"
                if lib_gap == 0
                else f"sigue en carrera por la Libertadores; está a {lib_gap} punto{'s' if lib_gap != 1 else ''} del último cupo"
            )
        )
    elif pos <= sud_cut:
        target = "Sudamericana"
        status = "hoy ocupa un cupo de Sudamericana por la Tabla Anual"
    else:
        target = "Sudamericana"
        status = (
            "ya aseguró terminar en zona de Sudamericana por la Anual"
            if sud_state == "in"
            else (
                "sigue en carrera por la Sudamericana; está igualado en puntos con el último cupo y hoy queda afuera por desempate"
                if sud_gap == 0
                else f"sigue en carrera por la Sudamericana; está a {sud_gap} punto{'s' if sud_gap != 1 else ''} del último cupo"
            )
        )

    text = (
        f"**Copas — {team}:** está {raw_row['pos']}º en la Tabla Anual con {_pts(raw_row['pts'])} en "
        f"{raw_row['pj']} PJ; {status}."
    )
    text += _direct_qualifier_note_above(all_rows, _num(raw_row["pos"]), fixed_qualified)

    annual_games = [m for m in games if m[0] in annual or m[1] in annual]
    annual_bounds = scenario_rank_bounds(annual, annual_games, team)
    cup_bounds = scenario_rank_bounds(
        effective_base,
        [m for m in games if m[0] in effective_base or m[1] in effective_base],
        team,
    )
    if annual_bounds.get("available"):
        best_a, worst_a = int(annual_bounds["best_rank"]), int(annual_bounds["worst_rank"])
        text += (
            f" En esta ventana, su **mejor posición posible en la Tabla Anual es {best_a}º** "
            f"y la **peor {worst_a}º**."
        )
    if cup_bounds.get("available"):
        best_c, worst_c = int(cup_bounds["best_rank"]), int(cup_bounds["worst_rank"])
        if pos <= sud_cut:
            if worst_c > sud_cut:
                text += " También tiene escenarios en los que termina la ventana fuera de los puestos de clasificación internacional."
            elif lib_cut and worst_c <= lib_cut:
                text += " Tiene asegurado cerrar la ventana en zona de Libertadores."
            elif lib_cut and best_c <= lib_cut:
                text += " Tiene asegurado seguir en puestos de copas y puede terminar la ventana en zona de Libertadores."
            else:
                text += " Tiene asegurado cerrar la ventana dentro de los puestos de clasificación internacional."
        elif best_c <= sud_cut:
            if lib_cut and best_c <= lib_cut:
                text += " Tiene escenarios para entrar a puestos de copas e incluso alcanzar la zona de Libertadores."
            else:
                text += " Tiene escenarios para terminar la ventana dentro de los puestos de clasificación internacional."
        else:
            text += " Aun en su mejor escenario de la ventana, sigue fuera de los puestos de clasificación internacional."

    if detailed:
        branch = _cup_result_rank_summary(
            team,
            effective_base,
            games,
            own_match,
            lib_cut=lib_cut,
            sud_cut=sud_cut,
            target=target,
            rank_base=annual,
        )
        if branch:
            text += " " + branch[:1].upper() + branch[1:] + "."
    return text


def _sorted_average_rows(averages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in sorted(
            averages,
            key=lambda item: float(item.get("PROMEDIO", 0) or 0),
            reverse=True,
        )
    ]


def _relegation_stake_for_team(
    team: str,
    annual: Mapping[str, Mapping[str, object]],
    averages: Sequence[Mapping[str, object]],
    games: Sequence[tuple[str, str]],
    own_match: tuple[str, str],
    *,
    annual_relegations: int,
    average_relegations: int,
    detailed: bool,
) -> str:
    notes: list[str] = []
    annual_rows = ordered_rows(annual) if annual else []
    annual_row = next((row for row in annual_rows if row["team"] == team), None)
    annual_count = max(0, int(annual_relegations))
    annual_window = max(5, annual_count + 4)
    annual_drop_now = bool(
        annual_row and annual_count and _num(annual_row["pos"]) > len(annual_rows) - annual_count
    )
    if annual_row and annual_count and _num(annual_row["pos"]) > max(0, len(annual_rows) - annual_window):
        safe_pos = max(1, len(annual_rows) - annual_count)
        first_drop_pos = min(len(annual_rows), safe_pos + 1)
        safe_row = annual_rows[safe_pos - 1]
        drop_row = annual_rows[first_drop_pos - 1]
        pos = _num(annual_row["pos"])
        if pos > safe_pos:
            gap = max(0, _num(safe_row["pts"]) - _num(annual_row["pts"]))
            situation = (
                "está en zona de descenso anual por desempate"
                if gap == 0 else
                f"está en zona de descenso anual, a {gap} punto{'s' if gap != 1 else ''} del último puesto de salvación"
            )
        else:
            cushion = max(0, _num(annual_row["pts"]) - _num(drop_row["pts"]))
            situation = (
                "está fuera del descenso anual sólo por desempate"
                if cushion == 0 else
                f"está {cushion} punto{'s' if cushion != 1 else ''} por encima de la zona de descenso anual"
            )
        text = f"**Anual — {team}:** está {pos}º con {_pts(annual_row['pts'])} en {annual_row['pj']} PJ y {situation}."
        bounds = scenario_rank_bounds(annual, games, team)
        if bounds.get("available"):
            best, worst = int(bounds["best_rank"]), int(bounds["worst_rank"])
            text += f" Puede cerrar la ventana {_rank_label(best, worst)} por puntos."
        if detailed:
            branch = _result_rank_summary(
                team, annual, games, own_match, cutoff=safe_pos,
                target_label="la zona de permanencia anual",
            )
            if branch:
                text += " " + branch[:1].upper() + branch[1:] + "."
        notes.append(text)

    avg_rows = _sorted_average_rows(averages)
    avg_count = max(0, int(average_relegations))
    avg_window = max(5, avg_count + 4)
    avg_index = next((index for index, row in enumerate(avg_rows) if row.get("Equipo") == team), None)
    avg_drop_now = bool(
        avg_index is not None and avg_count and avg_index + 1 > len(avg_rows) - avg_count
    )
    if avg_index is not None and avg_count and avg_index + 1 > max(0, len(avg_rows) - avg_window):
        row = avg_rows[avg_index]
        pos = avg_index + 1
        avg = float(row.get("PROMEDIO", 0) or 0)
        if pos > len(avg_rows) - avg_count:
            situation = "hoy ocupa un puesto de descenso por promedios"
        else:
            situation = "hoy está fuera del puesto de descenso por promedios"
        pts = _num(row.get("Pts"))
        played = _num(row.get("PJ"))
        text = f"**Promedios — {team}:** está {pos}º con {_decimal_es(avg)}; {situation}."
        if played >= 0:
            after = {
                "gana": (pts + 3) / (played + 1) if played + 1 else 0.0,
                "empata": (pts + 1) / (played + 1) if played + 1 else 0.0,
                "pierde": pts / (played + 1) if played + 1 else 0.0,
            }
            text += (
                f" Tras este partido quedaría en {_decimal_es(after['gana'])} si gana, "
                f"{_decimal_es(after['empata'])} si empata y {_decimal_es(after['pierde'])} si pierde."
            )
            if sum(team in match for match in games) > 1:
                text += " Esos valores son antes de su otro partido pendiente en la misma ventana."
        notes.append(text)

    if annual_drop_now and avg_drop_now:
        notes.insert(
            0,
            f"**Doble riesgo — {team}:** hoy está en zona de descenso en las dos tablas; "
            "si terminara así, bajaría por promedios y el descenso por Tabla Anual pasaría al siguiente equipo "
            "peor ubicado que no hubiera descendido ya por esa vía.",
        )

    return " ".join(notes)


def round_preview_story(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]],
    games: Sequence[tuple[str, str]],
    *,
    round_label: str,
    cutoff: int = 8,
    match_types: Mapping[tuple[str, str], tuple[str, str | None]] | None = None,
    probabilities: Mapping[tuple[str, str], Sequence[float]] | None = None,
    postponed_rounds: Mapping[tuple[str, str], int] | None = None,
    selected_match: tuple[str, str] | None = None,
    detailed: bool = False,
    annual: Mapping[str, Mapping[str, object]] | None = None,
    remaining: Mapping[str, int] | None = None,
    fixed_qualified: Sequence[str] = (),
    table_slots_lib: int = 0,
    averages: Sequence[Mapping[str, object]] = (),
    annual_relegations: int = 1,
    average_relegations: int = 1,
    include_cups: bool = False,
    include_relegation: bool = False,
) -> str:
    """Narrativa de una ventana completa o de un partido puntual.

    Los rangos de puesto consideran todos los partidos de la ventana, incluso
    cuando un club juega dos veces. Son exactos por puntos y no inventan una
    diferencia de gol futura.
    """
    if not games:
        return "No hay partidos pendientes en la fecha seleccionada."
    match_types = dict(match_types or {})
    probabilities = dict(probabilities or {})
    postponed_rounds = dict(postponed_rounds or {})
    annual = dict(annual or {})
    remaining = dict(remaining or {})
    all_teams = {team for base in zones.values() for team in base}
    appearances = {team: sum(team in match for match in games) for team in all_teams}
    multiple = sorted(team for team, count in appearances.items() if count > 1)

    def match_order(match: tuple[str, str]) -> tuple[object, ...]:
        kind, zone = match_types.get(match, ("zona", None))
        return (1 if match in postponed_rounds else 0, 0 if kind == "zona" else 1, zone or "Z", match[0])

    ordered_games = sorted(games, key=match_order)
    if selected_match is not None:
        ordered_games = [selected_match] if selected_match in games else []
        if not ordered_games:
            return "El partido elegido no pertenece a la fecha seleccionada."

    blocks: list[str] = []
    if selected_match is None:
        blocks.append(f"## {round_label}")
        intro = (
            f"La ventana reúne **{len(games)} partidos**. Cada encuentro modifica la zona de sus protagonistas "
            "y suma para la Tabla Anual, por lo que también puede mover la clasificación a las copas y la pelea "
            "por el descenso."
        )
        if multiple:
            verb = "juega" if len(multiple) == 1 else "juegan"
            intro += (
                f" **{_team_list(multiple)}** {verb} dos veces; sus rangos contemplan ambos encuentros."
            )
        blocks.append(intro)
        for label in sorted(zones):
            blocks.append(_round_zone_sentence(str(label), zones[label], cutoff=cutoff))
        blocks.append("### Partido por partido")
    else:
        blocks.append(f"## {round_label} — partido elegido")

    bounds_cache: dict[tuple[str, str], dict[str, object]] = {}
    seen_teams: set[str] = set()

    for local, visitor in ordered_games:
        local_snapshot = _round_team_snapshot(local, zones, cutoff=cutoff)
        visitor_snapshot = _round_team_snapshot(visitor, zones, cutoff=cutoff)
        if local_snapshot is None or visitor_snapshot is None:
            blocks.append(f"**{local} – {visitor}.** No hay datos suficientes para narrar este encuentro.")
            continue
        kind, zone = match_types.get((local, visitor), ("zona", None))
        type_label = f"Zona {zone}" if kind == "zona" and zone else "Interzonal"
        postponed = postponed_rounds.get((local, visitor))
        timing = f" · pendiente de la Fecha {postponed}" if postponed is not None else ""
        lr = local_snapshot["row"]
        vr = visitor_snapshot["row"]
        paragraph = [f"**{local}–{visitor} ({type_label}{timing}).**"]
        paragraph.append(
            f"{local} llega {lr['pos']}º de la Zona {local_snapshot['zone']}, con {_pts(lr['pts'])} en "
            f"{lr['pj']} PJ y DG {_signed(lr['dg'])}. {visitor} está {vr['pos']}º de la Zona "
            f"{visitor_snapshot['zone']}, con {_pts(vr['pts'])} en {vr['pj']} PJ y DG {_signed(vr['dg'])}."
        )
        paragraph.append(_round_match_hook(local_snapshot, visitor_snapshot, cutoff=cutoff))

        already_seen = set(seen_teams)
        for team, snapshot in ((local, local_snapshot), (visitor, visitor_snapshot)):
            count = appearances.get(team, 1)
            if count > 1 and team in seen_teams and selected_match is None:
                extra = (
                    " y el impacto acumulado en las otras tablas"
                    if include_cups or include_relegation else ""
                )
                paragraph.append(
                    f"{team} disputa acá su segundo partido de la ventana. Su primera aparición ya contempla el "
                    f"rango global{extra} de los dos encuentros."
                )
            else:
                sentence = _window_rank_sentence(
                    team, snapshot, games, cutoff=cutoff, appearances=count, bounds_cache=bounds_cache,
                )
                if sentence:
                    paragraph.append(sentence)
            seen_teams.add(team)

        if selected_match is not None or detailed:
            prob_sentence = _round_probability_sentence(local, visitor, probabilities.get((local, visitor)))
            if prob_sentence:
                paragraph.append(prob_sentence)
        blocks.append(" ".join(part for part in paragraph if part))

        stakes: list[str] = []
        for team in (local, visitor):
            if selected_match is None and appearances.get(team, 1) > 1 and team in already_seen:
                continue
            if include_cups:
                cup = _cup_stake_for_team(
                    team,
                    annual,
                    games,
                    (local, visitor),
                    remaining=remaining,
                    fixed_qualified=fixed_qualified,
                    table_slots_lib=table_slots_lib,
                    detailed=detailed,
                )
                if cup:
                    stakes.append(cup)
            if include_relegation:
                relegation = _relegation_stake_for_team(
                    team,
                    annual,
                    averages,
                    games,
                    (local, visitor),
                    annual_relegations=annual_relegations,
                    average_relegations=average_relegations,
                    detailed=detailed,
                )
                if relegation:
                    stakes.append(relegation)
        if stakes:
            blocks.append("**Impacto en otras tablas**\n" + "\n".join(f"- {stake}" for stake in stakes))

        if detailed:
            local_branch = _round_result_branch(
                local, local_snapshot["base"], games, (local, visitor), cutoff=cutoff
            )
            visitor_branch = _round_result_branch(
                visitor, visitor_snapshot["base"], games, (local, visitor), cutoff=cutoff
            )
            if local_branch:
                blocks.append(local_branch)
            if visitor_branch:
                blocks.append(visitor_branch)

    if selected_match is None:
        blocks.append(
            "_Los rangos consideran todos los partidos de la ventana, incluidos los equipos que juegan dos veces. "
            "Son exactos por puntos. Cuando puede haber igualdad, contemplan un desempate favorable o adverso sin "
            "inventar una diferencia de gol futura. Las probabilidades, cuando aparecen, son una estimación separada "
            "y no modifican esas cuentas._"
        )
    elif detailed:
        blocks.append(
            "_Las ramas gana/empata/pierde son exactas por puntos. Si hay igualdad, el rango contempla un desempate "
            "favorable o adverso sin inventar una diferencia de gol futura._"
        )
    if (include_cups or include_relegation) and annual:
        blocks.append(
            "_Todos los puestos que se muestran corresponden a la **Tabla Anual real**. Un equipo ya clasificado "
            "por otra vía conserva su posición en esa tabla, aunque no consuma otro cupo internacional. Los campeones "
            "pendientes todavía pueden mover la línea de clasificación. En los promedios se informa el efecto exacto "
            "de cada resultado sobre el coeficiente propio, pero no se asegura una posición futura._"
        )
    return editorialize_text("\n\n".join(blocks))

def _tiebreak_between(above: Mapping[str, object], below: Mapping[str, object]) -> str:
    if _num(above.get("pts")) != _num(below.get("pts")):
        return "puntos"
    if _num(above.get("dg")) != _num(below.get("dg")):
        return "diferencia de gol"
    if bool(above.get("gf_known")) and bool(below.get("gf_known")) and _num(above.get("gf")) != _num(below.get("gf")):
        return "goles a favor"
    return "criterios posteriores no incluidos en esta foto"


def zone_story(
    label: str,
    base: Mapping[str, Mapping[str, object]],
    rest: Mapping[str, int],
    *,
    top_n: int = 8,
    total_rounds: int = 16,
    qualified: Iterable[str] = (),
    eliminated: Iterable[str] = (),
) -> str:
    rows = ordered_rows(base)
    if not rows:
        return f"No hay datos cargados para la Zona {label}."

    cut_index = min(max(1, top_n), len(rows)) - 1
    leader = rows[0]
    cutoff = rows[cut_index]
    first_out = rows[cut_index + 1] if cut_index + 1 < len(rows) else None
    max_played = max((_num(row["pj"]) for row in rows), default=0)
    min_remaining = min((int(rest.get(str(row["team"]), 0)) for row in rows), default=0)
    max_remaining = max((int(rest.get(str(row["team"]), 0)) for row in rows), default=0)

    lines = [f"## Zona {label} — cómo está la carrera por los playoffs"]
    lines.append(
        f"**{leader['team']} lidera** con **{_pts(leader['pts'])}** en {leader['pj']} PJ, "
        f"diferencia de gol **{_signed(leader['dg'])}** y **{_gf(leader)} GF**."
    )

    if first_out:
        lines.append(
            f"El corte está en el **{top_n}º puesto**: **{cutoff['team']}** está adentro con "
            f"**{_pts(cutoff['pts'])}** en **{cutoff['pj']} PJ**, DG **{_signed(cutoff['dg'])}** y {_gf(cutoff)} GF. "
            f"El primero afuera es **{first_out['team']}**, con **{_pts(first_out['pts'])}** en **{first_out['pj']} PJ**, "
            f"DG **{_signed(first_out['dg'])}** y {_gf(first_out)} GF."
        )
    else:
        lines.append(
            f"El último puesto de clasificación es de **{cutoff['team']}**, con {_pts(cutoff['pts'])} en {cutoff['pj']} PJ."
        )

    tied = [row for row in rows if row["pts"] == cutoff["pts"]]
    if len(tied) > 1:
        lines.append(
            "### Equipos igualados en los puntos del corte"
        )
        tied_table = [
            "| Pos. | Equipo | PTS | PJ | DG | GF |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        for row in tied:
            tied_table.append(
                f"| {row['pos']}º | {row['team']} | {row['pts']} | {row['pj']} | "
                f"{_signed(row['dg'])} | {_gf(row)} |"
            )
        lines.append("\n".join(tied_table))
        lines.append(
            "El reglamento ordena primero por diferencia de gol y después por goles a favor. Si la igualdad "
            "continúa, se aplican los criterios posteriores."
        )

        same_after_gf: dict[tuple[int, int, int], list[str]] = {}
        for row in tied:
            if not bool(row.get("gf_known")):
                continue
            key = (_num(row["pts"]), _num(row["dg"]), _num(row["gf"]))
            same_after_gf.setdefault(key, []).append(str(row["team"]))
        unresolved = [teams for teams in same_after_gf.values() if len(teams) > 1]
        if unresolved:
            groups = "; ".join(_team_list(group) for group in unresolved)
            lines.append(
                f"También siguen igualados después de PTS, DG y GF: **{groups}**. Su orden actual depende de "
                "los criterios posteriores del reglamento."
            )
        if first_out:
            deciding = _tiebreak_between(cutoff, first_out)
            if deciding == "criterios posteriores no incluidos en esta foto":
                lines.append(
                    f"Entre **{cutoff['team']}** y **{first_out['team']}** también coinciden PTS, DG y GF. "
                    "La tabla cargada conserva un orden, pero esta narrativa no lo atribuye a un desempate que no fue cargado."
                )
            else:
                if deciding == "goles a favor":
                    lines.append(
                        f"**{cutoff['team']}** ocupa hoy el último puesto de clasificación porque tiene "
                        f"**{_gf(cutoff)} goles a favor**, contra **{_gf(first_out)}** de {first_out['team']}."
                    )
                elif deciding == "diferencia de gol":
                    lines.append(
                        f"**{cutoff['team']}** está hoy adentro porque tiene diferencia de gol "
                        f"**{_signed(cutoff['dg'])}**, mientras {first_out['team']} registra "
                        f"**{_signed(first_out['dg'])}**."
                    )
                else:
                    lines.append(
                        f"La frontera entre **{cutoff['team']}** y **{first_out['team']}** se decide hoy por "
                        f"**{deciding}**."
                    )

    leader_gap = _num(leader["pts"]) - _num(cutoff["pts"])
    bottom = rows[-1]
    bottom_gap = _num(cutoff["pts"]) - _num(bottom["pts"])
    around_cut = [
        str(row["team"])
        for row in rows
        if abs(_num(row["pts"]) - _num(cutoff["pts"])) <= 3
    ]
    lines.append(
        f"Del líder al corte hay **{leader_gap} punto{'s' if leader_gap != 1 else ''}**; "
        f"del corte al último hay **{bottom_gap} punto{'s' if bottom_gap != 1 else ''}**. La zona está muy "
        f"comprimida: **{len(around_cut)} de los "
        f"{len(rows)} equipos** están a no más de tres puntos del {top_n}º puesto: {_team_list(around_cut)}."
    )

    qualified_list = list(qualified)
    eliminated_list = list(eliminated)
    if qualified_list:
        lines.append(f"**Clasificados matemáticamente:** {_team_list(qualified_list)}.")
    if eliminated_list:
        lines.append(f"**Sin chances matemáticas:** {_team_list(eliminated_list)}.")
    if not qualified_list and not eliminated_list:
        lines.append("Todavía no hay clasificados ni eliminados matemáticamente.")

    if min_remaining == max_remaining:
        lines.append(
            f"A cada equipo le quedan **{max_remaining} partidos** y hasta **{3 * max_remaining} puntos**. "
            f"La tabla corresponde a {max_played} partidos jugados como máximo sobre {total_rounds} jornadas oficiales."
        )
    else:
        lines.append(
            "Como todavía hay partidos pendientes, no todos disputaron la misma cantidad de encuentros. Les quedan "
            f"entre **{min_remaining} y {max_remaining} partidos**, por lo que la posición actual debe leerse junto "
            "con los PJ y el fixture restante, no sólo por el lugar en la tabla."
        )

    lines.append("### Foto del corte")
    cut_table = [
        "| Referencia | Equipo | PTS | PJ | DG | GF |",
        "|---|---|---:|---:|---:|---:|",
        f"| Líder | {leader['team']} | {leader['pts']} | {leader['pj']} | {_signed(leader['dg'])} | {_gf(leader)} |"
    ]
    cut_table.append(
        f"| Último clasificado | {cutoff['team']} | {cutoff['pts']} | {cutoff['pj']} | {_signed(cutoff['dg'])} | {_gf(cutoff)} |"
    )
    if first_out:
        cut_table.append(
            f"| Primero afuera | {first_out['team']} | {first_out['pts']} | {first_out['pj']} | {_signed(first_out['dg'])} | {_gf(first_out)} |"
        )
    lines.append("\n".join(cut_table))
    lines.append(
        "_Es una fotografía exacta de la tabla actual. No proyecta dónde terminará el corte ni asigna resultados futuros._"
    )
    return editorialize_text("\n\n".join(lines))


def _effective_order(
    annual: Mapping[str, Mapping[str, object]],
    fixed_qualified: Iterable[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows = ordered_rows(annual)
    fixed = {team for team in fixed_qualified if team}
    effective = _renumber_rows([row for row in rows if row["team"] not in fixed])
    return rows, effective


def libertadores_story(
    annual: Mapping[str, Mapping[str, object]],
    *,
    fixed_qualified: Sequence[str],
    table_slots: int,
    aperture_champion: str = "",
    clausura_champion: str = "",
    copa_argentina_champion: str = "",
    clausura_candidates: Iterable[str] = (),
    copa_argentina_alive: Iterable[str] = (),
    copa_snapshot: str = "",
) -> str:
    rows, effective = _effective_order(annual, fixed_qualified)
    if not effective:
        return "No hay una Tabla Anual válida para narrar la clasificación a la Libertadores."

    table_slots = max(0, int(table_slots))
    qualifiers = effective[:table_slots]
    waiting = effective[table_slots] if len(effective) > table_slots else None
    alive = set(copa_argentina_alive)
    clausura_possible = set(clausura_candidates)

    lines = ["## Copa Libertadores 2027 — cómo está la clasificación"]
    fixed_text = _team_list([team for team in fixed_qualified if team])
    lines.append(
        f"La Libertadores tiene plazas para los campeones y **{table_slots} lugares que se definen por la Tabla Anual**. "
        f"Ya tienen plaza directa por otra vía: **{fixed_text}**."
    )

    if qualifiers:
        q_text = " · ".join(
            f"{row['team']} ({row.get('annual_pos', row['pos'])}º Anual, {row['pts']} pts, {row['pj']} PJ, DG {_signed(row['dg'])})" for row in qualifiers
        )
        lines.append(f"**Hoy entrarían por la Anual:** {q_text}.")
    if waiting:
        lines.append(
            f"El primero que espera es **{waiting['team']}**, **{waiting.get('annual_pos', waiting['pos'])}º en la Tabla Anual**, con **{waiting['pts']} puntos en {waiting['pj']} PJ**, "
            f"DG **{_signed(waiting['dg'])}** y {_gf(waiting)} GF."
        )

    if qualifiers and waiting:
        cutoff = qualifiers[-1]
        if cutoff["pts"] == waiting["pts"]:
            deciding = _tiebreak_between(cutoff, waiting)
            if deciding == "criterios posteriores no incluidos en esta foto":
                lines.append(
                    f"El último cupo está igualado: **{cutoff['team']}** y **{waiting['team']}** coinciden en PTS, DG y GF. "
                    "El orden exacto requiere los criterios posteriores de la Tabla General."
                )
            else:
                lines.append(
                    f"El último cupo está igualado en puntos: **{cutoff['team']}** se mantiene arriba de "
                    f"**{waiting['team']}** por **{deciding}**."
                )
        else:
            gap = _num(cutoff["pts"]) - _num(waiting["pts"])
            lines.append(
                f"La diferencia entre el último que entra y el primero que espera es de **{gap} punto"
                f"{'s' if gap != 1 else ''}**."
            )

    current_names = [str(row["team"]) for row in qualifiers]
    via_clausura = [team for team in current_names if team in clausura_possible]
    via_copa = [team for team in current_names if team in alive]
    if waiting:
        conditions = []
        if via_clausura:
            conditions.append(
                "uno de los actuales clasificados por tabla gana el Clausura "
                f"({_team_list(via_clausura)})"
            )
        if via_copa:
            conditions.append(
                "uno de ellos gana la Copa Argentina "
                f"({_team_list(via_copa)})"
            )
        if aperture_champion and not clausura_champion:
            conditions.append(
                f"**{aperture_champion}** también gana el Clausura, porque la plaza duplicada corre a la Anual"
            )
        if conditions:
            lines.append(
                f"**Cómo puede entrar el siguiente:** {waiting['team']} tomaría un lugar de Libertadores si "
                + "; o si ".join(conditions)
                + "."
            )

    lines.append("### Cómo se mueve la línea")
    lines.append(
        "- Si un equipo que hoy ocupa uno de los cupos por tabla gana el **Clausura** o la **Copa Argentina**, "
        "su clasificación deja de depender de la Anual y el siguiente equipo pasa a ocupar ese cupo."
    )
    lines.append(
        "- Si el campeón del Apertura también gana el Clausura, se habilita **un lugar adicional por la Tabla General** "
        "(art. 27.7)."
    )
    lines.append(
        "- Si el campeón de la Copa Argentina también fue campeón del Apertura o del Clausura, la plaza de Copa Argentina "
        "**no corre automáticamente a la Anual**: pasa al mejor equipo de Primera de esa Copa (arts. 27.8 y 27.8.1)."
    )

    if alive:
        alive_top = [str(row["team"]) for row in rows if row["team"] in alive]
        lines.append(
            f"**Copa Argentina todavía abierta:** {_team_list(alive_top)} siguen con esa vía entre los clubes de Primera cargados."
        )
        if copa_snapshot:
            lines.append(f"_Estado de Copa Argentina: {copa_snapshot}._")

    lines.append(
        "_La tabla de hoy es una foto provisional: los campeones futuros no agregan siempre un cupo nuevo, pero pueden "
        "cambiar qué equipos ocupan los lugares que otorga la Tabla Anual._"
    )
    return editorialize_text("\n\n".join(lines))


def sudamericana_story(
    annual: Mapping[str, Mapping[str, object]],
    *,
    fixed_qualified: Sequence[str],
    table_slots_lib: int,
    aperture_champion: str = "",
    clausura_champion: str = "",
    clausura_candidates: Iterable[str] = (),
    copa_argentina_alive: Iterable[str] = (),
    copa_snapshot: str = "",
) -> str:
    rows, effective = _effective_order(annual, fixed_qualified)
    start = max(0, int(table_slots_lib))
    sud = effective[start : start + 6]
    waiting = effective[start + 6] if len(effective) > start + 6 else None
    alive = set(copa_argentina_alive)
    clausura_possible = set(clausura_candidates)

    lines = ["## Copa Sudamericana 2027 — cómo está la clasificación"]
    lines.append(
        "La Sudamericana recibe a los **seis mejores de la Tabla Anual que no tengan plaza en la Libertadores**. "
        "Por eso su corte depende tanto de los puntos como de quiénes terminen siendo campeones."
    )
    if sud:
        lines.append(
            "**Hoy ocuparían los seis lugares:** "
            + " · ".join(f"{row['team']} ({row.get('annual_pos', row['pos'])}º Anual, {row['pts']} pts, {row['pj']} PJ, DG {_signed(row['dg'])})" for row in sud)
            + "."
        )
    if waiting:
        last = sud[-1]
        lines.append(
            f"El último cupo es de **{last['team']}**, **{last.get('annual_pos', last['pos'])}º en la Tabla Anual**, con **{last['pts']} puntos en {last['pj']} PJ**, DG **{_signed(last['dg'])}**. "
            f"El primero que espera es **{waiting['team']}**, **{waiting.get('annual_pos', waiting['pos'])}º en la Tabla Anual**, con **{waiting['pts']} en {waiting['pj']} PJ**, DG **{_signed(waiting['dg'])}**."
        )
        if last["pts"] == waiting["pts"]:
            deciding = _tiebreak_between(last, waiting)
            if deciding == "criterios posteriores no incluidos en esta foto":
                lines.append(
                    "La frontera coincide en PTS, DG y GF. El orden exacto requiere los criterios posteriores de la Tabla General."
                )
            else:
                lines.append(f"La frontera está igualada en puntos y hoy se decide por **{deciding}**.")

        ahead = [str(row["team"]) for row in effective[: start + 6]]
        potential_clausura = [team for team in ahead if team in clausura_possible]
        potential_copa = [team for team in ahead if team in alive and team != aperture_champion]
        shifts = []
        if potential_clausura:
            shifts.append(f"un club ubicado arriba gana el Clausura ({_team_list(potential_clausura)})")
        if potential_copa:
            shifts.append(f"un club ubicado arriba gana la Copa Argentina ({_team_list(potential_copa)})")
        if aperture_champion and not clausura_champion:
            shifts.append(f"{aperture_champion} repite el título en el Clausura")
        if shifts:
            lines.append(
                f"**Cómo puede bajar la línea:** {waiting['team']} puede entrar si " + "; o si ".join(shifts) + "."
            )

    lines.append("### Qué significa que un campeón ‘libere’ lugar")
    lines.append(
        "Cuando un equipo que está en esta franja consigue una plaza de Libertadores como campeón, deja de ocupar un "
        "lugar de Sudamericana y el siguiente de la Anual avanza. El número total de seis cupos no cambia: cambia la identidad "
        "de los equipos excluidos por estar en Libertadores."
    )
    lines.append(
        "La excepción importante es la duplicación de la Copa Argentina con Apertura o Clausura: esa plaza se hereda dentro "
        "de la Copa Argentina y no se entrega de manera automática al siguiente de la Anual."
    )
    if copa_snapshot:
        lines.append(f"_Estado de Copa Argentina considerado: {copa_snapshot}._")
    return editorialize_text("\n\n".join(lines))


def relegation_story(
    annual: Mapping[str, Mapping[str, object]],
    averages: Sequence[Mapping[str, object]],
    *,
    annual_relegations: int = 1,
    average_relegations: int = 1,
) -> str:
    annual_rows = ordered_rows(annual)
    if not annual_rows:
        return "No hay una Tabla Anual válida para narrar el descenso."
    avg_rows = list(averages)
    picture = current_relegation_picture(
        annual, avg_rows, annual_relegations=annual_relegations, average_relegations=average_relegations
    )
    lines = ["## Descenso 2026 — cómo está la pelea"]
    lines.append(
        f"Hay **{average_relegations} descenso por promedios** y **{annual_relegations} por la Tabla General**. "
        "Un equipo debe quedar fuera de la última posición en ambas carreras para estar completamente a salvo."
    )

    bottom_annual = annual_rows[-max(5, annual_relegations + 3) :]
    min_annual = min(_num(row["pts"]) for row in annual_rows)
    tied_annual = [row for row in annual_rows if _num(row["pts"]) == min_annual]
    if len(tied_annual) > 1:
        lines.append(
            "**Tabla General:** hay empate en el fondo entre **"
            + _team_list([str(row["team"]) for row in tied_annual])
            + f"**, todos con **{int(min_annual)} puntos**. Si esa igualdad define el descenso, corresponde partido desempate; la DG no elige al que baja."
        )
    else:
        last_annual = tied_annual[0]
        previous_annual = annual_rows[-2] if len(annual_rows) > 1 else None
        lines.append(
            f"**Tabla General:** hoy el último es **{last_annual['team']}**, con **{last_annual['pts']} puntos** en "
            f"{last_annual['pj']} PJ, DG **{_signed(last_annual['dg'])}** y {_gf(last_annual)} GF."
        )
        if previous_annual:
            gap = _num(previous_annual["pts"]) - _num(last_annual["pts"])
            lines.append(
                f"Está a **{gap} punto{'s' if gap != 1 else ''}** de **{previous_annual['team']}**, que tiene "
                f"{previous_annual['pts']} puntos en {previous_annual['pj']} PJ. La DG se muestra como contexto, pero una igualdad en una posición de descenso "
                "se define mediante partido desempate, no por diferencia de gol."
            )

    if avg_rows:
        if picture["average_playoff"]:
            lines.append(
                "**Promedios:** la posición de descenso está empatada entre **"
                + _team_list(picture["average_playoff"])
                + "**. Si terminara así, esa plaza se resuelve por desempate y no corresponde señalar un descendido único."
            )
        else:
            last_avg = avg_rows[-1]
            prev_avg = avg_rows[-2] if len(avg_rows) > 1 else None
            lines.append(
                f"**Promedios:** el último es **{last_avg.get('Equipo')}** con **{_decimal_es(last_avg.get('PROMEDIO', 0))}**, "
                f"producto de {last_avg.get('Pts', 0)} puntos en {last_avg.get('PJ', 0)} partidos."
            )
            if prev_avg:
                diff = float(prev_avg.get("PROMEDIO", 0)) - float(last_avg.get("PROMEDIO", 0))
                lines.append(
                    f"La diferencia con **{prev_avg.get('Equipo')}** es de **{_decimal_es(diff)}** en el coeficiente actual. "
                    "En esta tabla cada resultado cambia también el denominador, especialmente para los recién ascendidos."
                )
    else:
        lines.append("**Promedios:** faltan antecedentes válidos; esta vía debe quedar bloqueada hasta completar la fuente.")

    if picture["average_playoff"]:
        lines.append(
            "**Si terminara hoy, el descenso por promedios se definiría en un desempate entre:** "
            + _team_list(picture["average_playoff"]) + "."
        )
    elif picture["average_confirmed"]:
        lines.append(f"**Si terminara hoy, bajaría por promedios:** {_team_list(picture['average_confirmed'])}.")

    if picture["annual_depends_on_average_playoff"]:
        lines.append(
            "**Tabla General:** su descenso queda condicionado por quién pierda el desempate de promedios. "
            "Los candidatos que aparecen en los escenarios actuales son: " + _team_list(picture["annual_candidates"]) + "."
        )
    elif picture["annual_scenarios"]:
        scenario = picture["annual_scenarios"][0]
        if scenario["annual_playoff"]:
            lines.append(
                "**Por la Tabla General hay desempate en la posición de descenso entre:** "
                + _team_list(scenario["annual_playoff"]) + "."
            )
        elif scenario["annual_confirmed"]:
            lines.append(f"**Y por la Tabla General:** {_team_list(scenario['annual_confirmed'])}.")

    lines.append("### Los que están hoy en la zona de riesgo")
    lines.append("| Tabla General | PTS | PJ | DG | GF |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in bottom_annual:
        lines.append(
            f"| {row['team']} | {row['pts']} | {row['pj']} | {_signed(row['dg'])} | {_gf(row)} |"
        )
    if avg_rows:
        lines.append("\n| Promedios | Promedio | Pts | PJ | Mínimo final | Máximo final |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in avg_rows[-5:]:
            lines.append(
                f"| {row.get('Equipo')} | {_decimal_es(row.get('PROMEDIO', 0))} | {row.get('Pts', 0)} | "
                f"{row.get('PJ', 0)} | {_decimal_es(row.get('Mínimo final', row.get('Piso', 0)))} | {_decimal_es(row.get('Máximo final', row.get('Techo', 0)))} |"
            )
    lines.append(
        "_Es una foto exacta de las tablas cargadas. En una igualdad que defina descenso, la DG no rompe el empate: "
        "corresponde partido desempate. Los rangos de promedio son matemáticos, no una predicción._"
    )
    return editorialize_text("\n\n".join(lines))

