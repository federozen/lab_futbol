"""Motor exacto de escenarios por resultados para la LPF.

Usa ``scipy.optimize.milp`` cuando está disponible. No modela marcadores futuros:
los empates en puntos se tratan de forma favorable o desfavorable según la pregunta.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

try:
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix
    SCIPY_MILP = True
except Exception:  # pragma: no cover - fallback documentado
    SCIPY_MILP = False

from lpf_models import PointLadderRow

OUTCOMES = ("L", "E", "V")
POINTS_HOME = (3, 1, 0)
POINTS_AWAY = (0, 1, 3)


@dataclass
class SolverResult:
    feasible: bool
    objective: float | None = None
    outcomes: dict[tuple[str, str], str] | None = None
    message: str = ""


def _points(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("pts", 0))
    return int(value)


def _normalize_matches(matches: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """Normaliza y elimina duplicados exactos conservando el orden.

    La orientación local/visitante se respeta porque este módulo también puede
    usarse con torneos de ida y vuelta; la identidad oficial específica de LPF se
    resuelve antes, en la capa de aplicación.
    """
    out = []
    seen = set()
    for a, b in matches:
        match = (str(a), str(b))
        if match in seen:
            continue
        seen.add(match)
        out.append(match)
    return tuple(out)


def _matches_relevant_to_base(
    base: Mapping[str, object],
    matches: Iterable[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Conserva sólo partidos capaces de mover la tabla ``base``.

    Los cruces contra equipos externos (por ejemplo, un interzonal) sí importan
    porque suman puntos a un club de la tabla. Un partido entre dos equipos que no
    pertenecen a ``base`` no puede alterar ninguna posición y sólo agranda el MILP.
    """
    teams = set(base)
    return tuple(match for match in _normalize_matches(matches) if match[0] in teams or match[1] in teams)


def _build_model(
    base: Mapping[str, object],
    matches: Sequence[tuple[str, str]],
    team: str,
    target_final: int,
    cutoff: int,
    mode: str,
    fixed: Mapping[tuple[str, str], str] | None = None,
    optimize_rank: str | None = None,
) -> SolverResult:
    if not SCIPY_MILP:
        return SolverResult(False, message="scipy.optimize.milp no está disponible")
    if team not in base:
        return SolverResult(False, message="equipo desconocido")
    teams = list(base)
    rivals = [t for t in teams if t != team]
    matches = list(_matches_relevant_to_base(base, matches))
    fixed = dict(fixed or {})
    m, r = len(matches), len(rivals)
    nvars = 3 * m + r
    if nvars == 0:
        rank_bad = sum(_points(base[x]) >= target_final for x in rivals)
        if mode == "fail":
            return SolverResult(rank_bad >= cutoff)
        rank_strict = sum(_points(base[x]) > target_final for x in rivals)
        return SolverResult(rank_strict <= cutoff - 1)

    # Coeficientes de puntos ganados por cada equipo.
    gains = {t: np.zeros(nvars) for t in teams}
    for j, (home, away) in enumerate(matches):
        for o in range(3):
            gains.setdefault(home, np.zeros(nvars))[3*j + o] += POINTS_HOME[o]
            gains.setdefault(away, np.zeros(nvars))[3*j + o] += POINTS_AWAY[o]

    rows: list[tuple[np.ndarray, float, float]] = []
    # Un solo resultado por partido.
    for j, match in enumerate(matches):
        row = np.zeros(nvars)
        row[3*j:3*j+3] = 1
        rows.append((row, 1, 1))
        if match in fixed:
            wanted = OUTCOMES.index(fixed[match])
            for o in range(3):
                if o != wanted:
                    rfix = np.zeros(nvars); rfix[3*j+o] = 1
                    rows.append((rfix, 0, 0))

    # El equipo objetivo termina exactamente con target_final.
    need = target_final - _points(base[team])
    rows.append((gains.get(team, np.zeros(nvars)), need, need))

    max_diff = max(12, 3 * len(matches) + max((_points(v) for v in base.values()), default=0) + 5)
    y_start = 3 * m
    for i, rival in enumerate(rivals):
        y = y_start + i
        diff = gains.get(rival, np.zeros(nvars))
        diff = diff - gains.get(team, np.zeros(nvars))
        base_diff = _points(base[rival]) - _points(base[team])
        if mode in ("qualify", "best_rank"):
            # y=1 <=> rival termina estrictamente por encima.
            row1 = diff.copy(); row1[y] -= max_diff
            rows.append((row1, -np.inf, -base_diff))       # diff+base <= M*y
            row2 = -diff.copy(); row2[y] += max_diff
            rows.append((row2, -np.inf, max_diff - 1 + base_diff))
        else:
            # y=1 <=> rival termina igualado o por encima (desempate adverso).
            row1 = diff.copy(); row1[y] -= max_diff
            rows.append((row1, -np.inf, -1 - base_diff))   # y=0 => diff+base <= -1
            row2 = -diff.copy(); row2[y] += max_diff
            rows.append((row2, -np.inf, max_diff + base_diff))

    count = np.zeros(nvars); count[y_start:] = 1
    if mode == "qualify":
        rows.append((count, -np.inf, cutoff - 1))
    elif mode == "fail":
        rows.append((count, cutoff, np.inf))

    A = lil_matrix((len(rows), nvars), dtype=float)
    lb = np.empty(len(rows)); ub = np.empty(len(rows))
    for i, (row, low, high) in enumerate(rows):
        A[i, :] = row
        lb[i], ub[i] = low, high

    c = np.zeros(nvars)
    if optimize_rank == "best":
        c[y_start:] = 1
    elif optimize_rank == "worst":
        c[y_start:] = -1
    result = milp(
        c=c,
        integrality=np.ones(nvars),
        bounds=Bounds(np.zeros(nvars), np.ones(nvars)),
        constraints=LinearConstraint(A.tocsr(), lb, ub),
        options={"time_limit": 12.0, "mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        return SolverResult(False, message=str(result.message))
    outcomes: dict[tuple[str, str], str] = {}
    for j, match in enumerate(matches):
        outcomes[match] = OUTCOMES[int(np.argmax(result.x[3*j:3*j+3]))]
    objective = float(result.fun) if result.fun is not None else None
    return SolverResult(True, objective, outcomes, str(result.message))


def can_qualify_with_points(base, matches, team, cutoff, final_points, fixed=None) -> SolverResult:
    return _build_model(base, _normalize_matches(matches), team, int(final_points), int(cutoff), "qualify", fixed)


def can_fail_with_points(base, matches, team, cutoff, final_points, fixed=None) -> SolverResult:
    return _build_model(base, _normalize_matches(matches), team, int(final_points), int(cutoff), "fail", fixed)


def exact_objective_result_states(
    base: Mapping[str, object],
    rest: Mapping[str, int],
    matches: Iterable[tuple[str, str]],
    team: str,
    own_match: tuple[str, str],
    cutoff: int,
) -> dict[str, object]:
    """Estado exacto G/E/P del objetivo sin enumerar todas las otras canchas.

    La matriz editorial de próxima fecha normalmente usa enumeración completa para
    poder explicar también *qué otra cancha* pesa más. Cuando hay demasiados
    partidos ajenos, esa enumeración crece como ``3^N``. Para el semáforo G/E/P
    no hace falta enumerarlos: alcanza con resolver dos problemas MILP por rama.

    - Para probar una garantía se busca si el equipo todavía puede fallar incluso
      terminando con su **mínimo** puntaje compatible con la rama. Si ni así puede
      fallar, el objetivo queda asegurado.
    - Para probar eliminación se busca si puede clasificar llegando a su **máximo**
      puntaje compatible con la rama. Si ni así puede entrar, queda eliminado.

    El método requiere fixture completo para los equipos de ``base``. Si la
    cobertura no coincide con ``rest``, devuelve ``available=False`` antes que
    publicar un cierre matemático sobre un fixture incompleto.
    """
    if not SCIPY_MILP:
        return {"available": False, "reason": "scipy.optimize.milp no está disponible"}
    if team not in base:
        return {"available": False, "reason": "equipo desconocido"}
    if int(cutoff) <= 0:
        return {"available": False, "reason": "corte inválido"}

    matches = list(_matches_relevant_to_base(base, matches))
    own_match = (str(own_match[0]), str(own_match[1]))
    if own_match not in matches:
        return {"available": False, "reason": "el partido propio no está en el fixture pendiente"}
    if team not in own_match:
        return {"available": False, "reason": "el partido indicado no corresponde al equipo"}

    # La prueba de temporada necesita todos los partidos pendientes de cada club
    # que integra la tabla reducida. Un partido contra un equipo externo sí cuenta.
    coverage = {name: 0 for name in base}
    for home, away in matches:
        if home in coverage:
            coverage[home] += 1
        if away in coverage:
            coverage[away] += 1
    missing = [
        name for name in base
        if int(coverage.get(name, 0)) != max(0, int(rest.get(name, 0)))
    ]
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        suffix = "…" if len(missing) > 5 else ""
        return {
            "available": False,
            "reason": f"fixture pendiente incompleto para la prueba exacta ({sample}{suffix})",
        }

    current = _points(base[team])
    remaining_after_own = max(0, int(rest.get(team, 0)) - 1)
    is_home = own_match[0] == team
    branch_defs = (
        ("G", "Si gana", "L" if is_home else "V", 3),
        ("E", "Si empata", "E", 1),
        ("P", "Si pierde", "V" if is_home else "L", 0),
    )
    branches: list[dict[str, object]] = []
    for code, label, fixed_code, gain in branch_defs:
        fixed = {own_match: fixed_code}
        floor = current + gain
        ceiling = floor + 3 * remaining_after_own

        # Menor puntaje = peor camino propio. Si ni en ese escenario existe una
        # eliminación, la rama asegura.
        fail_at_floor = can_fail_with_points(base, matches, team, int(cutoff), floor, fixed)
        # Mayor puntaje = mejor camino propio. Si ni así existe clasificación, la
        # rama elimina.
        qualify_at_ceiling = can_qualify_with_points(base, matches, team, int(cutoff), ceiling, fixed)

        guaranteed = not fail_at_floor.feasible
        eliminated = not qualify_at_ceiling.feasible
        state = "in" if guaranteed else "out" if eliminated else "pelea"
        if guaranteed:
            explanation = (
                f"{label}, aun tomando el peor recorrido propio posterior ({floor} puntos finales), "
                f"el solver exacto no encuentra ningún cierre compatible que deje a {team} fuera del corte. "
                "Por eso esta rama asegura el objetivo."
            )
        elif eliminated:
            explanation = (
                f"{label}, aun tomando el mejor recorrido propio posterior ({ceiling} puntos finales), "
                f"el solver exacto no encuentra ningún cierre compatible que meta a {team} dentro del corte. "
                "Por eso esta rama deja el objetivo fuera de alcance."
            )
        else:
            explanation = (
                f"{label}, el objetivo sigue abierto: existe al menos un cierre compatible en el que {team} entra "
                "y también uno en el que queda fuera. Para esta celda el solver prueba factibilidad matemática; "
                "no asigna probabilidad a esos caminos."
            )
        branches.append({
            "result": code,
            "result_label": label,
            "final_points_after_round": current + gain,
            "points_floor": floor,
            "points_ceiling": ceiling,
            "solver_state": state,
            "solver": "scipy.optimize.milp",
            "solver_explanation": explanation,
            # Forma mínima compatible con branch_state(), sólo para presentación.
            "total_combinations": 1,
            "season_in": 1 if state == "in" else 0,
            "season_pelea": 1 if state == "pelea" else 0,
            "season_out": 1 if state == "out" else 0,
            "round_safe": 0,
            "proof": {"team_points": current + gain, "cutoff": int(cutoff)},
        })

    return {
        "available": True,
        "method": "milp-season-branches",
        "own_match": own_match,
        "branches": branches,
        "reason": "",
    }


def exact_rank_bounds_with_points(base, matches, team, final_points, fixed=None) -> tuple[int, int] | None:
    best = _build_model(base, _normalize_matches(matches), team, int(final_points), len(base), "best_rank", fixed, "best")
    worst = _build_model(base, _normalize_matches(matches), team, int(final_points), len(base), "worst_rank", fixed, "worst")
    if not best.feasible or not worst.feasible:
        return None
    best_above = int(round(best.objective or 0))
    worst_above = int(round(-(worst.objective or 0)))
    return best_above + 1, worst_above + 1


def can_finish_exact_rank_by_points(
    base: Mapping[str, object],
    matches: Iterable[tuple[str, str]],
    team: str,
    rank: int,
    final_points: int,
    fixed: Mapping[tuple[str, str], str] | None = None,
) -> SolverResult:
    """Prueba un puesto exacto sin depender de un desempate futuro.

    A diferencia de :func:`exact_rank_bounds_with_points`, esta consulta no toma
    un intervalo de puestos y asume que todos los puestos intermedios son
    publicables. Exige un escenario concreto en el que ``rank - 1`` rivales
    terminen con más puntos que ``team`` y todos los demás con menos puntos.

    Si algún rival termina igualado en puntos, ese escenario se descarta: la app
    no proyecta marcadores futuros y por lo tanto no puede afirmar qué puesto
    exacto resolvería el desempate.
    """
    if not SCIPY_MILP:
        return SolverResult(False, message="scipy.optimize.milp no está disponible")
    if team not in base:
        return SolverResult(False, message="equipo desconocido")
    rank = int(rank)
    target_final = int(final_points)
    if rank < 1 or rank > len(base):
        return SolverResult(False, message="puesto fuera de rango")

    matches = list(_normalize_matches(matches))
    fixed = dict(fixed or {})
    rivals = [rival for rival in base if rival != team]

    if not matches:
        if _points(base[team]) != target_final:
            return SolverResult(False, message="puntaje final inalcanzable")
        rival_points = [_points(base[rival]) for rival in rivals]
        if any(points == target_final for points in rival_points):
            return SolverResult(False, message="el puesto depende del desempate")
        actual_rank = 1 + sum(points > target_final for points in rival_points)
        return SolverResult(actual_rank == rank)

    m, r = len(matches), len(rivals)
    nvars = 3 * m + r
    gains = {club: np.zeros(nvars) for club in base}
    for j, (home, away) in enumerate(matches):
        for outcome in range(3):
            gains.setdefault(home, np.zeros(nvars))[3 * j + outcome] += POINTS_HOME[outcome]
            gains.setdefault(away, np.zeros(nvars))[3 * j + outcome] += POINTS_AWAY[outcome]

    rows: list[tuple[np.ndarray, float, float]] = []
    for j, match in enumerate(matches):
        row = np.zeros(nvars)
        row[3 * j:3 * j + 3] = 1
        rows.append((row, 1, 1))
        if match in fixed:
            wanted = OUTCOMES.index(fixed[match])
            for outcome in range(3):
                if outcome != wanted:
                    fixed_row = np.zeros(nvars)
                    fixed_row[3 * j + outcome] = 1
                    rows.append((fixed_row, 0, 0))

    need = target_final - _points(base[team])
    rows.append((gains.get(team, np.zeros(nvars)), need, need))

    max_base_gap = max(
        (abs(_points(base[rival]) - target_final) for rival in rivals),
        default=0,
    )
    big_m = max(12, 3 * len(matches) + max_base_gap + 5)
    y_start = 3 * m
    for i, rival in enumerate(rivals):
        y = y_start + i
        gain = gains.get(rival, np.zeros(nvars))
        base_gap = _points(base[rival]) - target_final

        # y=0 => rival termina al menos un punto abajo.
        row_low = gain.copy()
        row_low[y] -= big_m
        rows.append((row_low, -np.inf, -1 - base_gap))

        # y=1 => rival termina al menos un punto arriba.
        row_high = -gain.copy()
        row_high[y] += big_m
        rows.append((row_high, -np.inf, big_m - 1 + base_gap))

    count = np.zeros(nvars)
    count[y_start:] = 1
    rows.append((count, rank - 1, rank - 1))

    A = lil_matrix((len(rows), nvars), dtype=float)
    lb = np.empty(len(rows))
    ub = np.empty(len(rows))
    for i, (row, low, high) in enumerate(rows):
        A[i, :] = row
        lb[i], ub[i] = low, high

    result = milp(
        c=np.zeros(nvars),
        integrality=np.ones(nvars),
        bounds=Bounds(np.zeros(nvars), np.ones(nvars)),
        constraints=LinearConstraint(A.tocsr(), lb, ub),
        options={"time_limit": 12.0, "mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        return SolverResult(False, message=str(result.message))

    outcomes: dict[tuple[str, str], str] = {}
    for j, match in enumerate(matches):
        outcomes[match] = OUTCOMES[int(np.argmax(result.x[3 * j:3 * j + 3]))]
    return SolverResult(True, 0.0, outcomes, str(result.message))


def reachable_point_totals(current: int, games_left: int) -> list[int]:
    totals = set()
    for wins in range(games_left + 1):
        for draws in range(games_left - wins + 1):
            totals.add(current + 3 * wins + draws)
    return sorted(totals)


def _describe_outcomes(outcomes: Mapping[tuple[str, str], str] | None, team: str, limit: int = 5) -> list[str]:
    if not outcomes:
        return []
    descriptions = []
    for (home, away), result in outcomes.items():
        if team in (home, away):
            continue
        if result == "L":
            descriptions.append(f"gana {home} ante {away}")
        elif result == "V":
            descriptions.append(f"gana {away} ante {home}")
        else:
            descriptions.append(f"empatan {home} y {away}")
        if len(descriptions) >= limit:
            break
    return descriptions


def point_ladder(
    base: Mapping[str, object],
    matches: Iterable[tuple[str, str]],
    team: str,
    cutoff: int,
    *,
    max_rows: int = 8,
    max_matches: int = 100,
) -> dict[str, object]:
    matches = _matches_relevant_to_base(base, matches)
    current = _points(base[team])
    games_left = sum(team in match for match in matches)
    reachable = reachable_point_totals(current, games_left)
    if not SCIPY_MILP or len(matches) > max_matches:
        return {
            "available": False,
            "reason": "El motor exacto se reserva para ventanas de hasta 100 partidos; mientras no pueda resolver el mínimo exacto, no se publica un mínimo que asegura aproximado.",
            "minimum_possible": None,
            "guarantee": None,
            "rows": [],
        }
    statuses: list[PointLadderRow] = []
    minimum = None
    guarantee = None
    for pts in reachable:
        q = can_qualify_with_points(base, matches, team, cutoff, pts)
        if not q.feasible:
            continue
        minimum = pts if minimum is None else minimum
        fail = can_fail_with_points(base, matches, team, cutoff, pts)
        guaranteed = not fail.feasible
        if guaranteed and guarantee is None:
            guarantee = pts
        status = "Mínimo que asegura" if guaranteed else "Clasificación condicionada"
        statuses.append(PointLadderRow(
            final_points=pts,
            status=status,
            can_qualify=True,
            can_fail=fail.feasible,
            guaranteed=guaranteed,
            example=[] if guaranteed else _describe_outcomes(q.outcomes, team),
            note=("No depende de otros resultados ni del desempate." if guaranteed else
                  "Existe al menos un camino de clasificación y también un escenario de eliminación."),
        ))
        if guarantee is not None and pts >= guarantee + 3:
            break
    # Mantener los puntos cercanos a la frontera, no toda la temporada.
    if len(statuses) > max_rows:
        pivot = next((i for i, row in enumerate(statuses) if row.guaranteed), len(statuses) - 1)
        start = max(0, pivot - max_rows + 2)
        statuses = statuses[start:start + max_rows]
    return {
        "available": True,
        "minimum_possible": minimum,
        "guarantee": guarantee,
        "rows": statuses,
        "solver": "scipy.optimize.milp",
    }


def exact_result_scenarios(
    base: Mapping[str, object],
    games: Sequence[tuple[str, str]],
    team: str,
    own_match: tuple[str, str],
    cutoff: int,
) -> list[dict[str, object]]:
    """Gana/empata/pierde en una ventana que puede contener postergados.

    Si el equipo juega otro partido dentro de la misma ventana, ese segundo partido
    queda libre y es incorporado al rango.
    """
    games = list(_normalize_matches(games))
    own_match = (str(own_match[0]), str(own_match[1]))
    if own_match not in games:
        # Defensa final: una rama gana/empata/pierde nunca puede fijar un partido
        # que no exista en la ventana enviada al solver. Si la capa superior lo
        # omitió, se incorpora aquí en vez de producir un rango artificial.
        games.append(own_match)
    current = _points(base[team])
    is_home = own_match[0] == team
    labels = (("Gana", "L" if is_home else "V", 3), ("Empata", "E", 1), ("Pierde", "V" if is_home else "L", 0))
    rows = []
    for label, code, gain in labels:
        fixed = {own_match: code}
        # El puntaje final de la ventana también depende de un eventual segundo partido.
        other_games = sum(team in match and match != own_match for match in games)
        possible = reachable_point_totals(current + gain, other_games)
        rank_bounds = []
        can_enter = False
        can_fail = False
        for pts in possible:
            rb = exact_rank_bounds_with_points(base, games, team, pts, fixed)
            if rb:
                rank_bounds.append(rb)
            can_enter = can_enter or can_qualify_with_points(base, games, team, cutoff, pts, fixed).feasible
            can_fail = can_fail or can_fail_with_points(base, games, team, cutoff, pts, fixed).feasible
        rows.append({
            "result": label,
            "points_min": min(possible),
            "points_max": max(possible),
            "best_rank": min((r[0] for r in rank_bounds), default=None),
            "worst_rank": max((r[1] for r in rank_bounds), default=None),
            "can_enter": can_enter,
            "can_fail": can_fail,
        })
    return rows


def _fixed_gain_for_team(team: str, fixed: Mapping[tuple[str, str], str]) -> int:
    gain = 0
    for (home, away), outcome in fixed.items():
        if team == home:
            gain += 3 if outcome == "L" else 1 if outcome == "E" else 0
        elif team == away:
            gain += 3 if outcome == "V" else 1 if outcome == "E" else 0
    return gain


def scenario_rank_bounds(
    base: Mapping[str, object],
    games: Sequence[tuple[str, str]],
    team: str,
    fixed: Mapping[tuple[str, str], str] | None = None,
) -> dict[str, object]:
    """Rango exacto de puesto para una ventana parcialmente fijada.

    Los partidos sin resultado quedan abiertos. El motor no inventa marcadores:
    cuando hay igualdad en puntos, el mejor y el peor puesto contemplan un
    desempate favorable o adverso.
    """
    fixed = dict(fixed or {})
    games = _normalize_matches(games)
    current = _points(base[team])
    fixed_gain = _fixed_gain_for_team(team, fixed)
    open_team_games = sum(team in match and match not in fixed for match in games)
    totals = reachable_point_totals(current + fixed_gain, open_team_games)
    bounds: list[tuple[int, int, int]] = []
    for final_points in totals:
        rb = exact_rank_bounds_with_points(base, games, team, final_points, fixed)
        if rb is not None:
            bounds.append((final_points, rb[0], rb[1]))
    return {
        "available": bool(bounds),
        "points_min": min((row[0] for row in bounds), default=None),
        "points_max": max((row[0] for row in bounds), default=None),
        "best_rank": min((row[1] for row in bounds), default=None),
        "worst_rank": max((row[2] for row in bounds), default=None),
        "by_points": bounds,
    }


def best_worst_window_scenarios(
    base: Mapping[str, object],
    games: Sequence[tuple[str, str]],
    team: str,
    fixed: Mapping[tuple[str, str], str] | None = None,
) -> dict[str, object]:
    """Devuelve un ejemplo concreto del mejor y peor caso de una ventana.

    El resultado es exacto por puntos. Los desempates futuros no se resuelven con
    marcadores inventados: el mejor caso supone desempate favorable y el peor,
    desfavorable.
    """
    fixed = dict(fixed or {})
    games = _normalize_matches(games)
    current = _points(base[team])
    fixed_gain = _fixed_gain_for_team(team, fixed)
    open_team_games = sum(team in match and match not in fixed for match in games)
    totals = reachable_point_totals(current + fixed_gain, open_team_games)
    best_row = None
    worst_row = None
    for final_points in totals:
        best = _build_model(base, games, team, final_points, len(base), "best_rank", fixed, "best")
        if best.feasible:
            rank = int(round(best.objective or 0)) + 1
            candidate = {
                "rank": rank,
                "final_points": final_points,
                "outcomes": best.outcomes or {},
            }
            if best_row is None or (rank, -final_points) < (best_row["rank"], -best_row["final_points"]):
                best_row = candidate
        worst = _build_model(base, games, team, final_points, len(base), "worst_rank", fixed, "worst")
        if worst.feasible:
            above = int(round(-(worst.objective or 0)))
            rank = above + 1
            candidate = {
                "rank": rank,
                "final_points": final_points,
                "outcomes": worst.outcomes or {},
            }
            if worst_row is None or (rank, -final_points) > (worst_row["rank"], -worst_row["final_points"]):
                worst_row = candidate
    return {
        "available": best_row is not None and worst_row is not None,
        "best": best_row,
        "worst": worst_row,
    }
