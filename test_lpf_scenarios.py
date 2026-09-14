"""Validación por fuerza bruta del motor exacto (`lpf_scenarios`).

Este motor es el cimiento de toda la aplicación: si sus respuestas están mal, todo
lo demás también. Estas pruebas generan ligas chicas al azar, enumeran TODOS los
desenlaces posibles y comparan, resultado por resultado, contra lo que dice el
solver de programación entera.

Convenios de desempate del motor (confirmados aquí):
- `can_qualify_with_points` y el mejor puesto usan desempate **a favor** (sólo
  cuentan los rivales estrictamente por encima).
- `can_fail_with_points` y el peor puesto usan desempate **en contra** (cuentan los
  rivales iguales o por encima).
"""
import itertools
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_scenarios import (  # noqa: E402
    can_fail_with_points,
    can_finish_exact_rank_by_points,
    can_qualify_with_points,
    exact_rank_bounds_with_points,
    point_ladder,
    reachable_point_totals,
)

OUTCOMES = ("L", "E", "V")


def _final_points(base, matches, combo):
    pts = {e: int(base[e]["pts"]) for e in base}
    for (home, away), r in zip(matches, combo):
        if r == "L":
            pts[home] += 3
        elif r == "V":
            pts[away] += 3
        else:
            pts[home] += 1
            pts[away] += 1
    return pts


def _random_league(rng, n_teams, n_matches):
    teams = [f"T{i:02d}" for i in range(n_teams)]
    base = {t: {"pts": rng.randint(0, 12)} for t in teams}
    pairs = list(itertools.combinations(teams, 2))
    rng.shuffle(pairs)
    matches = pairs[:n_matches]
    return base, teams, matches


def _all_finals(base, matches):
    """Enumera (puntos_finales) para los 3**m desenlaces posibles."""
    for combo in itertools.product(OUTCOMES, repeat=len(matches)):
        yield _final_points(base, matches, combo)


# Semillas fijas => pruebas deterministas y reproducibles.
LEAGUES = [(5, 4), (5, 5), (6, 5), (4, 6), (6, 6)]


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_can_qualify_coincide_con_fuerza_bruta(n_teams, n_matches):
    rng = random.Random(1000 + n_teams * 10 + n_matches)
    for _ in range(6):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        cutoff = rng.randint(1, n_teams - 1)
        team = rng.choice(teams)
        finals = list(_all_finals(base, matches))
        for target in reachable_point_totals(base[team]["pts"], sum(team in m for m in matches)):
            # Fuerza bruta con desempate A FAVOR (estrictamente por encima).
            brute = any(
                p[team] == target
                and (1 + sum(1 for e in base if e != team and p[e] > p[team])) <= cutoff
                for p in finals
            )
            got = can_qualify_with_points(base, matches, team, cutoff, target).feasible
            assert got == brute, (
                f"can_qualify n={n_teams} m={n_matches} team={team} cutoff={cutoff} "
                f"target={target}: motor={got} fuerza_bruta={brute}"
            )


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_can_fail_coincide_con_fuerza_bruta(n_teams, n_matches):
    rng = random.Random(2000 + n_teams * 10 + n_matches)
    for _ in range(6):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        cutoff = rng.randint(1, n_teams - 1)
        team = rng.choice(teams)
        finals = list(_all_finals(base, matches))
        for target in reachable_point_totals(base[team]["pts"], sum(team in m for m in matches)):
            # Fuerza bruta con desempate EN CONTRA (iguales o por encima).
            brute = any(
                p[team] == target
                and (1 + sum(1 for e in base if e != team and p[e] >= p[team])) > cutoff
                for p in finals
            )
            got = can_fail_with_points(base, matches, team, cutoff, target).feasible
            assert got == brute, (
                f"can_fail n={n_teams} m={n_matches} team={team} cutoff={cutoff} "
                f"target={target}: motor={got} fuerza_bruta={brute}"
            )


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_rank_bounds_coinciden_con_fuerza_bruta(n_teams, n_matches):
    rng = random.Random(3000 + n_teams * 10 + n_matches)
    for _ in range(6):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        team = rng.choice(teams)
        finals = list(_all_finals(base, matches))
        for target in reachable_point_totals(base[team]["pts"], sum(team in m for m in matches)):
            relevant = [p for p in finals if p[team] == target]
            if not relevant:
                # No alcanzable => el motor devuelve None.
                assert exact_rank_bounds_with_points(base, matches, team, target) is None
                continue
            best = min(1 + sum(1 for e in base if e != team and p[e] > p[team]) for p in relevant)
            worst = max(1 + sum(1 for e in base if e != team and p[e] >= p[team]) for p in relevant)
            got = exact_rank_bounds_with_points(base, matches, team, target)
            assert got == (best, worst), (
                f"rank_bounds team={team} target={target}: motor={got} fuerza_bruta={(best, worst)}"
            )


@pytest.mark.parametrize("n_teams,n_matches", [(4, 4), (5, 4), (5, 5)])
def test_puesto_exacto_por_puntos_coincide_con_fuerza_bruta(n_teams, n_matches):
    rng = random.Random(3500 + n_teams * 10 + n_matches)
    for _ in range(4):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        team = rng.choice(teams)
        finals = list(_all_finals(base, matches))
        for target in reachable_point_totals(base[team]["pts"], sum(team in m for m in matches)):
            rank = rng.randint(1, n_teams)
            brute = any(
                p[team] == target
                and all(p[rival] != p[team] for rival in teams if rival != team)
                and (1 + sum(1 for rival in teams if rival != team and p[rival] > p[team])) == rank
                for p in finals
            )
            got = can_finish_exact_rank_by_points(base, matches, team, rank, target).feasible
            assert got == brute, (
                f"puesto exacto team={team} rank={rank} target={target}: "
                f"motor={got} fuerza_bruta={brute}"
            )


def test_puesto_exacto_por_puntos_no_publica_un_empate_como_puesto_definido():
    base = {
        "A": {"pts": 10},
        "B": {"pts": 10},
        "C": {"pts": 6},
    }
    assert not can_finish_exact_rank_by_points(base, [], "A", 1, 10).feasible
    assert not can_finish_exact_rank_by_points(base, [], "A", 2, 10).feasible


def test_puesto_exacto_por_puntos_sin_partidos_reconoce_orden_claro():
    base = {
        "A": {"pts": 12},
        "B": {"pts": 10},
        "C": {"pts": 6},
    }
    assert can_finish_exact_rank_by_points(base, [], "B", 2, 10).feasible
    assert not can_finish_exact_rank_by_points(base, [], "B", 1, 10).feasible


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_point_ladder_minimo_y_garantia(n_teams, n_matches):
    rng = random.Random(4000 + n_teams * 10 + n_matches)
    for _ in range(5):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        cutoff = rng.randint(1, n_teams - 1)
        team = rng.choice(teams)
        finals = list(_all_finals(base, matches))
        targets = reachable_point_totals(base[team]["pts"], sum(team in m for m in matches))

        brute_min = None
        brute_guar = None
        for target in targets:
            rel = [p for p in finals if p[team] == target]
            if not rel:
                continue
            # Mínimo posible: existe un desenlace favorable.
            if brute_min is None and any(
                (1 + sum(1 for e in base if e != team and p[e] > p[team])) <= cutoff for p in rel
            ):
                brute_min = target
            # Garantía: todos los desenlaces entran con desempate adverso.
            if brute_guar is None and all(
                (1 + sum(1 for e in base if e != team and p[e] >= p[team])) <= cutoff for p in rel
            ):
                brute_guar = target

        ladder = point_ladder(base, matches, team, cutoff, max_rows=8, max_matches=120)
        assert ladder["available"]
        assert ladder.get("minimum_possible") == brute_min, (
            f"ladder mínimo team={team} cutoff={cutoff}: motor={ladder.get('minimum_possible')} bruta={brute_min}"
        )
        assert ladder.get("guarantee") == brute_guar, (
            f"ladder garantía team={team} cutoff={cutoff}: motor={ladder.get('guarantee')} bruta={brute_guar}"
        )


def test_reachable_point_totals():
    # 2 partidos: 0..6 puntos posibles => {cur, cur+1, cur+2, cur+3, cur+4, cur+6}
    assert reachable_point_totals(10, 2) == [10, 11, 12, 13, 14, 16]
    assert reachable_point_totals(0, 0) == [0]
    assert reachable_point_totals(5, 1) == [5, 6, 8]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ── exact_result_scenarios: gana / empata / pierde en una ventana ──────────────

def _brute_result_scenario(base, matches, team, own_match):
    """Fuerza bruta: para cada resultado propio, el rango de puestos y si puede
    entrar/quedar afuera del top-2, considerando el resto de la ventana libre."""
    from lpf_scenarios import _points  # noqa
    is_home = own_match[0] == team
    code_for = {"Gana": ("L" if is_home else "V"), "Empata": "E", "Pierde": ("V" if is_home else "L")}
    out = {}
    for label, own_code in code_for.items():
        idx = matches.index(own_match)
        best = 99
        worst = 0
        can_enter = False
        can_fail = False
        for combo in itertools.product(OUTCOMES, repeat=len(matches)):
            if combo[idx] != own_code:
                continue
            p = _final_points(base, matches, combo)
            strict = 1 + sum(1 for e in base if e != team and p[e] > p[team])
            adv = 1 + sum(1 for e in base if e != team and p[e] >= p[team])
            best = min(best, strict)
            worst = max(worst, adv)
            # can_enter usa desempate a favor (puede clasificar); can_fail, en contra.
            if strict <= 2:
                can_enter = True
            if adv > 2:
                can_fail = True
        out[label] = (best, worst, can_enter, can_fail)
    return out


def test_exact_result_scenarios_vs_fuerza_bruta():
    from lpf_scenarios import exact_result_scenarios
    rng = random.Random(9090)
    for _ in range(6):
        base, teams, matches = _random_league(rng, 5, 4)
        # elegir un partido que exista y tomar uno de sus equipos
        own = rng.choice(matches)
        team = own[0]
        rows = exact_result_scenarios(base, matches, team, own, cutoff=2)
        brute = _brute_result_scenario(base, matches, team, own)
        for row in rows:
            b_best, b_worst, b_enter, b_fail = brute[row["result"]]
            assert row["best_rank"] == b_best, f"{row['result']} best {row['best_rank']} != {b_best}"
            assert row["worst_rank"] == b_worst, f"{row['result']} worst {row['worst_rank']} != {b_worst}"
            assert row["can_enter"] == b_enter, f"{row['result']} can_enter {row['can_enter']} != {b_enter}"
            assert row["can_fail"] == b_fail, f"{row['result']} can_fail {row['can_fail']} != {b_fail}"


def test_point_ladder_ignora_partidos_totalmente_ajenos_a_la_tabla_para_el_limite():
    """Otra zona no debe apagar el solver exacto por inflar artificialmente el MILP."""
    base = {
        "A": {"pts": 4},
        "B": {"pts": 5},
        "C": {"pts": 3},
        "D": {"pts": 2},
    }
    relevant = [("A", "X"), ("B", "C"), ("D", "Y")]
    unrelated = [(f"U{i}", f"V{i}") for i in range(20)]

    expected = point_ladder(base, relevant, "A", 1, max_matches=3)
    got = point_ladder(base, relevant + unrelated, "A", 1, max_matches=3)

    assert expected["available"] is True
    assert got == expected


def test_point_ladder_conserva_interzonales_que_tocan_un_equipo_de_la_tabla():
    """Un rival externo se filtra sólo si ninguno de los dos equipos pertenece a la tabla."""
    base = {
        "A": {"pts": 4},
        "B": {"pts": 5},
        "C": {"pts": 3},
        "D": {"pts": 2},
    }
    with_cross_zone = point_ladder(
        base,
        [("A", "Interzonal"), ("B", "C")],
        "A",
        1,
        max_matches=2,
    )
    without_cross_zone = point_ladder(base, [("B", "C")], "A", 1, max_matches=2)

    assert with_cross_zone["minimum_possible"] == 7
    assert without_cross_zone["minimum_possible"] is None
