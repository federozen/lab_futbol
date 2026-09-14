"""Derivación e inferencia de datos.

Reconstruye la foto del Apertura desde la tabla anual y las zonas actuales, e infiere
resultados de partidos faltantes a partir de las diferencias entre tablas y el fixture
conocido. Lógica pura (datos -> datos), parte de la garantía de que la calculadora
"toma bien los datos" antes de contar.
"""
from __future__ import annotations

from lpf_text import _zlow
from lpf_clubs import canon_club
from lpf_data_2026 import LPF_FIXTURE
from lpf_reconcile import _lpf_result_stats, _lpf_results_fit_zones, _merge_lpf_results


def _asignar_nombres(claves, equipos):
    """Empareja nombres externos con los equipos cargados sin confundir casos como
    «Estudiantes» vs «Estudiantes RC» o «Gimnasia» vs «Gimnasia (M)».
    1) primero los exactos, 2) después los parciales solo si son únicos y el equipo sigue libre."""
    libres = list(equipos); out = {}
    for k in list(claves):
        for e in list(libres):
            if _zlow(k) == _zlow(e):
                out[k] = e; libres.remove(e); break
    for k in [x for x in claves if x not in out]:
        kn = _zlow(k)
        cands = [e for e in libres if kn in _zlow(e) or _zlow(e) in kn]
        if len(cands) == 1:
            out[k] = cands[0]; libres.remove(cands[0])
    return out


def derivar_apertura(anual, Z):
    """Apertura = Anual − lo que ya se jugó del Clausura, para que la anual siga viva
    a medida que avanzan las fechas (y no quede congelada en la foto pegada)."""
    clausura = {}
    for lab, b in (Z or {}).items():
        clausura.update(b)
    asign = _asignar_nombres(list(anual.keys()), list(clausura.keys()))
    out, avisos = {}, []
    for nombre, d in anual.items():
        e = asign.get(nombre)
        c = clausura.get(e, {}) if e else {}
        ap = {k: d.get(k, 0) - c.get(k, 0) for k in ("pts", "pj", "dg", "gf", "ga")}
        if ap["pts"] < 0 or ap["pj"] < 0:
            avisos.append(f"{nombre}: la anual pegada tiene menos que el Clausura cargado; revisá que sean de la misma fecha.")
            ap = {k: max(0, v) for k, v in ap.items()}
        out[e or nombre] = ap
    pjs = sorted({d["pj"] for d in out.values()})
    if len(pjs) > 1:
        avisos.append(f"⚠️ El Apertura derivado da distinta cantidad de partidos según el equipo ({pjs}). "
                      "Casi seguro pegaste la **anual y el Clausura de fechas distintas**: tienen que ser del mismo momento.")
    elif pjs and pjs[0] != 16:
        avisos.append(f"⚠️ El Apertura derivado da {pjs[0]} partidos y la fase de zonas del Apertura fueron 16 fechas. "
                      "Revisá que la anual y las tablas del Clausura sean de la misma fecha.")
    return out, avisos


def _lpf_infer_missing_results_milp(deltas, edges, *, missing_matches, first_round, last_round):
    """Resuelve una conciliación grande como MILP y exige unicidad exacta.

    Variables por partido: jugado, goles local/visitante y resultado L/E/V. Los
    acumulados de cada club fijan PJ, puntos, GF y GC. Una segunda resolución agrega
    una restricción *no-good*: si existe cualquier solución con un partido o marcador
    distinto, la reconstrucción se considera ambigua y no se publica.
    """
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
    except Exception:
        return [], "La conciliación grande requiere scipy.optimize.milp y no está disponible."

    m = len(edges)
    if not m or missing_matches <= 0:
        return [], ""
    # y, gh, ga, local-win, draw, away-win
    n = 6 * m
    Y, GH, GA, HW, DR, AW = (0, m, 2 * m, 3 * m, 4 * m, 5 * m)
    lower = np.zeros(n, dtype=float)
    upper = np.ones(n, dtype=float)
    for j, (_rnd, home, away) in enumerate(edges):
        upper[GH + j] = max(0, min(int(deltas[home]["gf"]), int(deltas[away]["ga"])))
        upper[GA + j] = max(0, min(int(deltas[home]["ga"]), int(deltas[away]["gf"])))

    rows = []
    lbs = []
    ubs = []

    def add(coeffs, lb=-np.inf, ub=np.inf):
        row = np.zeros(n, dtype=float)
        for idx, value in coeffs.items():
            row[int(idx)] = float(value)
        rows.append(row); lbs.append(float(lb)); ubs.append(float(ub))

    for j in range(m):
        # Si el partido se juega, exactamente uno de L/E/V.
        add({HW + j: 1, DR + j: 1, AW + j: 1, Y + j: -1}, 0, 0)
        add({GH + j: 1, Y + j: -upper[GH + j]}, ub=0)
        add({GA + j: 1, Y + j: -upper[GA + j]}, ub=0)
        big = max(float(upper[GH + j]), float(upper[GA + j])) + 1.0
        # Local gana => gh >= ga + 1.
        add({GH + j: -1, GA + j: 1, HW + j: big}, ub=big - 1)
        # Visitante gana => ga >= gh + 1.
        add({GH + j: 1, GA + j: -1, AW + j: big}, ub=big - 1)
        # Empate => gh == ga.
        add({GH + j: 1, GA + j: -1, DR + j: big}, ub=big)
        add({GH + j: -1, GA + j: 1, DR + j: big}, ub=big)

    by_team = {team: [] for team, delta in deltas.items() if int(delta["pj"]) > 0}
    for j, (_rnd, home, away) in enumerate(edges):
        if home in by_team:
            by_team[home].append((j, True))
        if away in by_team:
            by_team[away].append((j, False))

    for team, incident in by_team.items():
        delta = deltas[team]
        # PJ
        add({Y + j: 1 for j, _is_home in incident}, delta["pj"], delta["pj"])
        # Puntos
        coeff = {}
        for j, is_home in incident:
            coeff[(HW if is_home else AW) + j] = 3
            coeff[DR + j] = 1
        add(coeff, delta["pts"], delta["pts"])
        # GF / GC
        gf = {}; ga = {}
        for j, is_home in incident:
            gf[(GH if is_home else GA) + j] = 1
            ga[(GA if is_home else GH) + j] = 1
        add(gf, delta["gf"], delta["gf"])
        add(ga, delta["ga"], delta["ga"])

    A = np.vstack(rows)
    constraint = LinearConstraint(A, np.asarray(lbs), np.asarray(ubs))
    result = milp(
        c=np.zeros(n),
        integrality=np.ones(n, dtype=int),
        bounds=Bounds(lower, upper),
        constraints=constraint,
        options={"time_limit": 4.0},
    )
    if not bool(getattr(result, "success", False)) or result.x is None:
        return [], (
            f"Fechas {first_round}-{last_round}: los acumulados no permitieron resolver "
            "una combinación completa de marcadores mediante el solver exacto."
        )

    solution = np.rint(result.x).astype(int)
    core = list(range(0, 3 * m))  # partido jugado + ambos marcadores

    # Segunda factibilidad: obliga a que al menos una variable esencial difiera.
    n2 = n + 2 * len(core)
    A2 = np.pad(A, ((0, 0), (0, n2 - n)))
    lb2 = list(lbs); ub2 = list(ubs)
    extra_rows = []
    extra_lb = []; extra_ub = []
    for k, idx in enumerate(core):
        dpos = n + 2 * k
        dneg = dpos + 1
        svalue = int(solution[idx])
        max_value = int(round(upper[idx]))
        big = float(max_value + 1)

        row = np.zeros(n2); row[idx] = -1; row[dpos] = big
        extra_rows.append(row); extra_lb.append(-np.inf); extra_ub.append(big - svalue - 1)
        row = np.zeros(n2); row[idx] = 1; row[dneg] = big
        extra_rows.append(row); extra_lb.append(-np.inf); extra_ub.append(svalue - 1 + big)
        row = np.zeros(n2); row[dpos] = 1; row[dneg] = 1
        extra_rows.append(row); extra_lb.append(-np.inf); extra_ub.append(1)

    row = np.zeros(n2)
    row[n:] = 1
    extra_rows.append(row); extra_lb.append(1); extra_ub.append(np.inf)
    A2 = np.vstack([A2, *extra_rows])
    lb2.extend(extra_lb); ub2.extend(extra_ub)
    lower2 = np.concatenate([lower, np.zeros(n2 - n)])
    upper2 = np.concatenate([upper, np.ones(n2 - n)])
    second = milp(
        c=np.zeros(n2),
        integrality=np.ones(n2, dtype=int),
        bounds=Bounds(lower2, upper2),
        constraints=LinearConstraint(A2, np.asarray(lb2), np.asarray(ub2)),
        options={"time_limit": 4.0},
    )
    # status=2 es infeasible en HiGHS/SciPy: no existe otra solución.
    if bool(getattr(second, "success", False)):
        return [], (
            f"Fechas {first_round}-{last_round}: hay más de una combinación de resultados "
            "compatible con PJ, puntos, GF, GC y DG; no se infieren marcadores."
        )
    if int(getattr(second, "status", -1)) != 2:
        return [], (
            f"Fechas {first_round}-{last_round}: el solver encontró una reconstrucción, "
            "pero no pudo demostrar que fuera única dentro del tiempo de seguridad."
        )

    inferred = []
    for j, (_rnd, home, away) in enumerate(edges):
        if int(solution[Y + j]) != 1:
            continue
        inferred.append((home, away, int(solution[GH + j]), int(solution[GA + j])))
    if len(inferred) != int(missing_matches):
        return [], "La conciliación exacta produjo una cantidad inesperada de partidos; se descartó."

    stats = _lpf_result_stats(inferred)
    for team, delta in deltas.items():
        got = stats.get(team, {"pj": 0, "pts": 0, "gf": 0, "ga": 0})
        if any(int(got.get(key, 0)) != int(delta[key]) for key in ("pj", "pts", "gf", "ga")):
            return [], "La conciliación exacta no reprodujo los acumulados; se descartó."

    return inferred, (
        f"Fechas {first_round}-{last_round}: conciliación determinística por tabla reconstruyó "
        f"{len(inferred)} resultado{'s' if len(inferred) != 1 else ''} y el solver demostró "
        "que no existe una segunda combinación compatible."
    )

def _lpf_infer_missing_results(zones, baseline, fixture=None):
    """Reconstruye partidos faltantes sólo cuando la tabla fija una solución única.

    Es un respaldo determinístico para el caso en que el standings se actualiza antes
    que los feeds de marcadores. Compara la última foto validada contra la tabla nueva
    y busca, dentro del fixture oficial, una única combinación de partidos y marcadores
    que explique exactamente PJ, puntos, GF, GC y DG de *todos* los clubes.

    La búsqueda es deliberadamente conservadora, pero no usa un tope fijo de
    partidos faltantes: la complejidad real depende de cuántos cruces del fixture
    siguen siendo candidatos y de cuántas ramas sobreviven a los acumulados.

    - para saltos de hasta 2 PJ usa backtracking podado; para 3-4 PJ usa MILP;
    - sólo considera la ventana de fechas consecutivas que empieza en la primera fecha
      todavía incompleta de la base;
    - la búsqueda tiene un presupuesto determinístico de estados para evitar bloquear
      una carga si la tabla deja demasiadas combinaciones abiertas;
    - si existen dos soluciones compatibles, no infiere nada.

    Esto permite conciliar, por ejemplo, el cierre de una fecha más un único partido de
    la siguiente sin convertir los PJ de la tabla en una fuente especulativa.
    """
    fixture = fixture or LPF_FIXTURE
    baseline = _merge_lpf_results(baseline)
    if not zones or not baseline or _lpf_results_fit_zones(zones, baseline):
        return [], ""

    expected = {}
    for base in (zones or {}).values():
        for team, row in (base or {}).items():
            expected[canon_club(team)] = {
                key: int((row or {}).get(key, 0))
                for key in ("pj", "pts", "gf", "ga", "dg")
            }

    actual = _lpf_result_stats(baseline)
    deltas = {}
    for team, wanted in expected.items():
        got = actual.get(team, {"pj": 0, "pts": 0, "gf": 0, "ga": 0, "dg": 0})
        delta = {key: int(wanted[key]) - int(got.get(key, 0)) for key in wanted}
        if any(delta[key] < 0 for key in ("pj", "pts", "gf", "ga")):
            return [], ""
        if delta["dg"] != delta["gf"] - delta["ga"]:
            return [], ""
        if delta["pts"] > 3 * delta["pj"]:
            return [], ""
        # Si no sumó PJ, ningún otro acumulado puede haber cambiado.
        if delta["pj"] == 0 and any(
            delta[key] != 0 for key in ("pts", "gf", "ga", "dg")
        ):
            return [], ""
        deltas[team] = delta

    total_team_games = sum(delta["pj"] for delta in deltas.values())
    if total_team_games <= 0 or total_team_games % 2:
        return [], ""
    missing_matches = total_team_games // 2
    max_delta_pj = max((delta["pj"] for delta in deltas.values()), default=0)
    if max_delta_pj <= 0:
        return [], ""
    if max_delta_pj > 4:
        return [], (
            f"La tabla avanzó hasta {max_delta_pj} PJ por club respecto de la base validada; "
            "la conciliación automática no reconstruye más de cuatro fechas sin marcadores explícitos."
        )

    advanced = {team for team, delta in deltas.items() if delta["pj"] > 0}
    played_pairs = {(canon_club(l), canon_club(v)) for l, v, _gl, _gv in baseline}

    pending_edges = []
    for row in fixture or []:
        home = canon_club(row.get("l") or row.get("home") or "")
        away = canon_club(row.get("v") or row.get("away") or "")
        if not home or not away or (home, away) in played_pairs:
            continue
        if home not in advanced or away not in advanced:
            continue
        round_number = int(row.get("f") or row.get("round") or 0)
        if round_number > 0:
            pending_edges.append((round_number, home, away))

    if not pending_edges:
        return [], ""

    # No salta fechas enteras para fabricar una solución. Si un postergado rompe esta
    # continuidad y no hay un feed de resultados que lo identifique, se prefiere no inferir.
    first_pending_round = min(edge[0] for edge in pending_edges)
    last_candidate_round = first_pending_round + max_delta_pj - 1
    edges = [
        edge for edge in pending_edges
        if first_pending_round <= edge[0] <= last_candidate_round
    ]

    by_team = {team: [] for team in advanced}
    for idx, (_round, home, away) in enumerate(edges):
        by_team[home].append(idx)
        by_team[away].append(idx)
    if any(len(by_team.get(team, [])) < deltas[team]["pj"] for team in advanced):
        return [], ""
    if missing_matches > len(edges):
        return [], ""

    if max_delta_pj > 2:
        return _lpf_infer_missing_results_milp(
            deltas,
            edges,
            missing_matches=missing_matches,
            first_round=first_pending_round,
            last_round=last_candidate_round,
        )

    # Para una o dos fechas se conserva el backtracking histórico, que permite
    # cortar muy rápido cuando encuentra una segunda solución.
    # En vez de cortar por una cantidad fija de partidos faltantes, el backtracking
    # usa un presupuesto de estados. Esto permite saltos reales como 49 -> 67
    # cuando los acumulados fijan rápidamente una solución, y abandona de forma
    # segura si la tabla deja un espacio combinatorio demasiado amplio.
    max_search_states = 250_000

    state = {
        team: {
            key: int(delta[key])
            for key in ("pj", "pts", "gf", "ga")
        }
        for team, delta in deltas.items()
    }
    used_edges = set()
    solutions = []
    search_states = 0
    search_aborted = False

    def team_state_is_possible(row):
        if any(int(row[key]) < 0 for key in ("pj", "pts", "gf", "ga")):
            return False
        if int(row["pts"]) > 3 * int(row["pj"]):
            return False
        if int(row["pj"]) == 0 and any(
            int(row[key]) != 0 for key in ("pts", "gf", "ga")
        ):
            return False
        return True

    def backtrack(current, chosen):
        nonlocal search_states, search_aborted
        if search_aborted or len(solutions) > 1:
            return
        search_states += 1
        if search_states > max_search_states:
            search_aborted = True
            return
        active = [team for team, row in current.items() if int(row["pj"]) > 0]
        if not active:
            if all(
                int(row["pts"]) == int(row["gf"]) == int(row["ga"]) == 0
                for row in current.values()
            ):
                solutions.append(list(chosen))
            return

        available_by_team = {}
        for team in active:
            available = [
                idx for idx in by_team.get(team, [])
                if idx not in used_edges
                and current[edges[idx][1]]["pj"] > 0
                and current[edges[idx][2]]["pj"] > 0
            ]
            if len(available) < int(current[team]["pj"]):
                return
            available_by_team[team] = available

        team = min(
            active,
            key=lambda value: (
                len(available_by_team[value]),
                int(current[value]["pj"]),
                value,
            ),
        )

        for edge_idx in available_by_team[team]:
            round_number, home, away = edges[edge_idx]
            if current[home]["pj"] <= 0 or current[away]["pj"] <= 0:
                continue

            max_home_goals = min(current[home]["gf"], current[away]["ga"])
            max_away_goals = min(current[home]["ga"], current[away]["gf"])
            for home_goals in range(int(max_home_goals) + 1):
                for away_goals in range(int(max_away_goals) + 1):
                    if home_goals > away_goals:
                        home_points, away_points = 3, 0
                    elif away_goals > home_goals:
                        home_points, away_points = 0, 3
                    else:
                        home_points = away_points = 1
                    if home_points > current[home]["pts"]:
                        continue
                    if away_points > current[away]["pts"]:
                        continue

                    nxt = {name: dict(row) for name, row in current.items()}
                    nxt[home]["pj"] -= 1
                    nxt[away]["pj"] -= 1
                    nxt[home]["pts"] -= home_points
                    nxt[away]["pts"] -= away_points
                    nxt[home]["gf"] -= home_goals
                    nxt[home]["ga"] -= away_goals
                    nxt[away]["gf"] -= away_goals
                    nxt[away]["ga"] -= home_goals
                    if not team_state_is_possible(nxt[home]) or not team_state_is_possible(nxt[away]):
                        continue
                    # Todos los goles de la tanda aparecen una vez como GF y una como GC.
                    if sum(row["gf"] for row in nxt.values()) != sum(
                        row["ga"] for row in nxt.values()
                    ):
                        continue

                    used_edges.add(edge_idx)
                    chosen.append(
                        (round_number, home, away, int(home_goals), int(away_goals))
                    )
                    backtrack(nxt, chosen)
                    chosen.pop()
                    used_edges.remove(edge_idx)
                    if len(solutions) > 1:
                        return

    backtrack(state, [])
    if search_aborted:
        return [], (
            "La conciliación determinística no se aplicó: la tabla deja demasiadas "
            "combinaciones de fixture/marcadores abiertas para resolverlas dentro del "
            "presupuesto seguro de búsqueda."
        )
    if len(solutions) != 1:
        if len(solutions) > 1:
            return [], (
                "La conciliación determinística no se aplicó: hay más de una "
                "combinación de resultados compatible con PJ, puntos, GF, GC y DG."
            )
        return [], ""

    solution_edges = solutions[0]
    inferred = sorted(
        [(home, away, gh, ga) for _rnd, home, away, gh, ga in solution_edges],
        key=lambda row: (row[0], row[1]),
    )
    candidate = _merge_lpf_results(baseline, inferred)
    if not _lpf_results_fit_zones(zones, candidate):
        return [], ""

    rounds = sorted({int(row[0]) for row in solution_edges})
    if len(rounds) == 1:
        round_label = f"Fecha {rounds[0]}"
    else:
        round_label = "Fechas " + "-".join(str(value) for value in (rounds[0], rounds[-1]))
    details = "; ".join(f"{h} {gh}-{ga} {a}" for h, a, gh, ga in inferred)
    note = (
        f"Conciliación por tabla ({round_label}): {details}. "
        f"Los {len(inferred)} marcador(es) surgen de una única combinación del fixture "
        "y reproducen exactamente PJ, puntos, GF, GC y DG."
    )
    return inferred, note

