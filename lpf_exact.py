"""Núcleo exacto y auditable para las cuentas sensibles de la LPF.

No importa Streamlit ni usa azar. Las funciones de este módulo se pueden probar
por separado de la interfaz.
"""

from __future__ import annotations

LPF_RUNTIME_API = 21


from itertools import combinations
from typing import Iterable, Mapping, Sequence


def _points(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("pts", 0))
    return int(value)


def safe_guarantee_line(
    base: Mapping[str, object],
    remaining: Mapping[str, int],
    matches: Iterable[tuple[str, str]],
    team: str,
    rivals_above: int,
) -> int:
    """Línea superior segura para el puntaje del rival k-ésimo.

    Devuelve el mayor ``P`` para el que *todavía es posible* que al menos ``k``
    rivales terminen con ``P`` puntos. Por eso, terminar con ``P + 1`` garantiza
    quedar por encima de ese grupo (sin depender de desempates).

    La relajación descuenta correctamente los partidos entre los rivales elegidos:
    cada uno aparece dos veces en la suma de partidos restantes, pero reparte como
    máximo tres puntos en total. Se prueban todos los subconjuntos relevantes, no
    sólo los equipos con mayor techo. La prueba es necesaria, no suficiente; puede
    pedir algún punto de más, pero nunca declarar una garantía falsa.
    """
    rivals = [name for name in base if name != team]
    k = int(rivals_above)
    if k <= 0:
        return -1
    if len(rivals) < k:
        return -1

    pts = {name: _points(value) for name, value in base.items()}
    games_left = {name: max(0, int(remaining.get(name, 0))) for name in base}
    relevant_edges = [
        (a, b)
        for a, b in matches
        if a in base and b in base and a != team and b != team
    ]
    ceilings = {name: pts[name] + 3 * games_left[name] for name in rivals}

    def relaxed_feasible(target_points: int) -> bool:
        candidates = [name for name in rivals if ceilings[name] >= target_points]
        if len(candidates) < k:
            return False

        # Los candidatos más ajustados primero suelen descartar antes; en los casos
        # fáciles la función sale con el primer subconjunto factible.
        candidates.sort(key=lambda name: (ceilings[name], -pts[name]))
        for chosen in combinations(candidates, k):
            deficits = [max(0, target_points - pts[name]) for name in chosen]
            if any(deficit > 3 * games_left[name] for name, deficit in zip(chosen, deficits)):
                continue
            chosen_set = set(chosen)
            internal_edges = [
                (a, b) for a, b in relevant_edges if a in chosen_set and b in chosen_set
            ]
            degree = {name: 0 for name in chosen}
            for a, b in internal_edges:
                degree[a] += 1
                degree[b] += 1
            # Primero se asigna a cada club el máximo de sus partidos externos.
            # Lo que todavía necesita debe salir de los cruces internos, que
            # reparten como máximo tres puntos por partido entre ambos equipos.
            residual = []
            valid = True
            for name, deficit in zip(chosen, deficits):
                external_games = max(0, games_left[name] - degree[name])
                need_internal = max(0, deficit - 3 * external_games)
                if need_internal > 3 * degree[name]:
                    valid = False
                    break
                residual.append(need_internal)
            if valid and sum(residual) <= 3 * len(internal_edges):
                return True
        return False

    low = min(pts.values(), default=0)
    high = max(ceilings.values(), default=0)
    answer = low - 1
    while low <= high:
        middle = (low + high) // 2
        if relaxed_feasible(middle):
            answer = middle
            low = middle + 1
        else:
            high = middle - 1
    return answer


def safe_average_guarantee_points(
    totals: Mapping[str, int],
    played: Mapping[str, int],
    remaining: Mapping[str, int],
    matches: Iterable[tuple[str, str]],
    team: str,
    relegation_slots: int,
) -> int | None:
    """Puntos adicionales alcanzables que garantizan escapar de los promedios.

    La comparación se hace por cocientes finales y sin usar ``float``. Un empate
    de promedio se considera desfavorable: para estar garantizado el equipo debe
    dejar estrictamente por debajo a, como mínimo, ``relegation_slots`` rivales.

    La relajación prueba todos los subconjuntos de rivales que podrían terminar
    igual o por encima del promedio objetivo. Descuenta los cruces internos,
    porque dos clubes que se enfrentan no pueden sumar tres puntos cada uno.
    Como no fija qué partidos producen los puntos del equipo analizado, conserva
    como disponibles los puntos de sus rivales directos; por eso puede pedir algún
    punto de más, pero nunca declarar una salvación que aún dependa de resultados.
    """
    if team not in totals:
        return None
    names = [name for name in totals if name != team]
    k = max(0, int(relegation_slots))
    n = len(names) + 1
    if k <= 0:
        return 0
    if k >= n:
        return None

    total_points = {name: int(totals.get(name, 0)) for name in totals}
    games_played = {name: max(0, int(played.get(name, 0))) for name in totals}
    games_left = {name: max(0, int(remaining.get(name, 0))) for name in totals}
    final_games = {name: games_played[name] + games_left[name] for name in totals}
    if final_games.get(team, 0) <= 0:
        return None

    # Si al menos n-k rivales pueden terminar igual o por encima, el equipo
    # todavía podría quedar entre los k peores (los empates se toman adversos).
    rivals_needed = n - k
    relevant_edges = [
        (a, b)
        for a, b in matches
        if a in totals and b in totals and a != team and b != team
    ]

    def minimum_add_to_reach(name: str, target_num: int, target_den: int) -> int:
        den = final_games.get(name, 0)
        if den <= 0:
            return 10**9
        numerator = target_num * den - total_points[name] * target_den
        return max(0, -(-numerator // target_den))

    def rivals_can_keep_team_in_bottom(target_add: int) -> bool:
        target_num = total_points[team] + int(target_add)
        target_den = final_games[team]
        deficits = {
            name: minimum_add_to_reach(name, target_num, target_den)
            for name in names
        }
        candidates = [
            name for name in names
            if deficits[name] <= 3 * games_left[name]
        ]
        if len(candidates) < rivals_needed:
            return False
        candidates.sort(key=lambda name: (3 * games_left[name] - deficits[name], total_points[name]))

        for chosen in combinations(candidates, rivals_needed):
            chosen_set = set(chosen)
            internal_edges = [
                (a, b) for a, b in relevant_edges if a in chosen_set and b in chosen_set
            ]
            degree = {name: 0 for name in chosen}
            for a, b in internal_edges:
                degree[a] += 1
                degree[b] += 1
            residual = []
            valid = True
            for name in chosen:
                external_games = max(0, games_left[name] - degree[name])
                need_internal = max(0, deficits[name] - 3 * external_games)
                if need_internal > 3 * degree[name]:
                    valid = False
                    break
                residual.append(need_internal)
            if valid and sum(residual) <= 3 * len(internal_edges):
                return True
        return False

    r = games_left[team]
    reachable = sorted({3 * wins + draws for wins in range(r + 1) for draws in range(r - wins + 1)})
    for added in reachable:
        if not rivals_can_keep_team_in_bottom(added):
            return added
    return None


def next_round_rank_bounds(
    target: str,
    table: Mapping[str, Mapping[str, int]],
    games: Sequence[tuple[str, str]],
) -> tuple[int, int] | None:
    """Mejor y peor puesto posible tras una fecha, sin fingir un desempate.

    La frontera se calcula por puntos. En el mejor caso, un empate en puntos puede
    favorecer al equipo; en el peor, puede perjudicarlo. Ese intervalo incluye los
    marcadores y los criterios reglamentarios todavía desconocidos (fair play o
    sorteo). Dos rivales que se enfrentan se evalúan juntos, así que no se les
    adjudican simultáneamente tres puntos.
    """
    if target not in table:
        return None

    current = {name: int(stats.get("pts", 0)) for name, stats in table.items()}
    target_best = current[target] + 3
    target_worst = current[target]
    best_above = 0
    worst_above = 0
    seen = {target}

    for local, visitor in games:
        if target in (local, visitor):
            opponent = visitor if local == target else local
            if opponent in current:
                seen.add(opponent)
                best_above += int(current[opponent] > target_best)
                worst_above += int(current[opponent] + 3 >= target_worst)
            continue

        in_local = local in current
        in_visitor = visitor in current
        if in_local and in_visitor:
            seen.update((local, visitor))
            outcomes = ((3, 0), (1, 1), (0, 3))
            best_above += min(
                int(current[local] + dl > target_best)
                + int(current[visitor] + dv > target_best)
                for dl, dv in outcomes
            )
            worst_above += max(
                int(current[local] + dl >= target_worst)
                + int(current[visitor] + dv >= target_worst)
                for dl, dv in outcomes
            )
        elif in_local or in_visitor:
            rival = local if in_local else visitor
            seen.add(rival)
            best_above += min(int(current[rival] + add > target_best) for add in (3, 1, 0))
            worst_above += max(int(current[rival] + add >= target_worst) for add in (3, 1, 0))

    for rival in current:
        if rival not in seen:
            best_above += int(current[rival] > target_best)
            worst_above += int(current[rival] >= target_worst)

    return best_above + 1, worst_above + 1
