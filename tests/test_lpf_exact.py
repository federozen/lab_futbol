"""Las cotas seguras (`lpf_exact`) NUNCA deben declarar una garantía falsa.

Una cota conservadora puede pedir algún punto de más, pero si alguna vez afirma
que un puntaje garantiza el objetivo cuando en realidad todavía depende de otros
resultados, eso es un error crítico: la aplicación le estaría mintiendo al usuario.

Estas pruebas generan ligas chicas al azar, enumeran TODOS los desenlaces y
verifican dos cosas para la línea de garantía y para el piso por promedios:

1. **Seguridad (lo crítico):** terminar con el puntaje de garantía deja al equipo
   dentro del objetivo en TODOS los desenlaces (desempate adverso).
2. **Nunca por debajo del exacto:** la cota conservadora nunca pide menos que la
   garantía exacta real (si pidiera menos, sería insegura).
"""
import itertools
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_exact import safe_average_guarantee_points, safe_guarantee_line  # noqa: E402
from lpf_scenarios import point_ladder, reachable_point_totals  # noqa: E402

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
    base = {t: {"pts": rng.randint(0, 10)} for t in teams}
    pairs = list(itertools.combinations(teams, 2))
    rng.shuffle(pairs)
    return base, teams, pairs[:n_matches]


LEAGUES = [(5, 4), (5, 5), (6, 5), (6, 6), (4, 5)]


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_linea_garantia_nunca_es_falsa(n_teams, n_matches):
    """G = línea + 1 debe garantizar top-k en TODOS los desenlaces."""
    rng = random.Random(5000 + n_teams * 10 + n_matches)
    for _ in range(8):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        team = rng.choice(teams)
        rest = {}
        for a, b in matches:
            rest[a] = rest.get(a, 0) + 1
            rest[b] = rest.get(b, 0) + 1
        cutoff = rng.randint(1, n_teams - 1)

        line = safe_guarantee_line(base, rest, matches, team, cutoff)
        guarantee = line + 1
        finals = [_final_points(base, matches, c) for c in itertools.product(OUTCOMES, repeat=len(matches))]

        # SEGURIDAD: ningún desenlace con el equipo en `guarantee` puede dejar
        # que `cutoff` o más rivales lo alcancen (desempate adverso).
        for p in finals:
            if p[team] >= guarantee:
                rivals_at_or_above = sum(1 for e in base if e != team and p[e] >= p[team])
                assert rivals_at_or_above < cutoff, (
                    f"GARANTÍA FALSA: team={team} cutoff={cutoff} línea={line} "
                    f"garantía={guarantee} pero {rivals_at_or_above} rivales lo alcanzan"
                )


@pytest.mark.parametrize("n_teams,n_matches", LEAGUES)
def test_linea_garantia_nunca_por_debajo_del_exacto(n_teams, n_matches):
    """La cota conservadora nunca pide menos que la garantía exacta real."""
    rng = random.Random(6000 + n_teams * 10 + n_matches)
    for _ in range(8):
        base, teams, matches = _random_league(rng, n_teams, n_matches)
        team = rng.choice(teams)
        rest = {}
        for a, b in matches:
            rest[a] = rest.get(a, 0) + 1
            rest[b] = rest.get(b, 0) + 1
        cutoff = rng.randint(1, n_teams - 1)

        line = safe_guarantee_line(base, rest, matches, team, cutoff)
        conservador = line + 1

        # Solo tiene sentido comparar si el equipo puede terminar realmente con ese
        # puntaje. Un conservador por debajo de un total inalcanzable no es inseguro;
        # es un artefacto de que la línea razona sobre los rivales, no sobre el equipo.
        alcanzables = reachable_point_totals(base[team]["pts"], sum(team in m for m in matches))
        if conservador not in alcanzables:
            continue

        exacto = point_ladder(base, matches, team, cutoff, max_rows=8, max_matches=120)
        g_exacto = exacto.get("guarantee") if exacto.get("available") else None
        if g_exacto is not None:
            assert conservador >= g_exacto, (
                f"INSEGURA: conservador={conservador} < garantía exacta={g_exacto} "
                f"(team={team}, cutoff={cutoff})"
            )


def _final_average(totals, played, matches, combo, team):
    """Coeficiente final (num, den) por equipo tras aplicar un desenlace."""
    pts = {e: int(totals[e]) for e in totals}
    for (home, away), r in zip(matches, combo):
        if r == "L":
            pts[home] += 3
        elif r == "V":
            pts[away] += 3
        else:
            pts[home] += 1
            pts[away] += 1
    den = {}
    for e in totals:
        extra = sum(e in m for m in matches)
        den[e] = int(played[e]) + extra
    return pts, den


@pytest.mark.parametrize("n_teams,n_matches", [(4, 4), (5, 4), (5, 5), (4, 5)])
def test_promedios_garantia_nunca_es_falsa(n_teams, n_matches):
    """El piso por promedios nunca debe declarar una salvación falsa."""
    rng = random.Random(7000 + n_teams * 10 + n_matches)
    for _ in range(8):
        teams = [f"T{i:02d}" for i in range(n_teams)]
        totals = {t: rng.randint(20, 60) for t in teams}
        played = {t: rng.randint(15, 25) for t in teams}
        pairs = list(itertools.combinations(teams, 2))
        rng.shuffle(pairs)
        matches = pairs[:n_matches]
        rest = {}
        for a, b in matches:
            rest[a] = rest.get(a, 0) + 1
            rest[b] = rest.get(b, 0) + 1
        # Asegurar que el equipo analizado juega al menos una vez.
        team = next((t for t in teams if rest.get(t, 0) > 0), teams[0])
        k = rng.randint(1, max(1, n_teams - 2))

        extra = safe_average_guarantee_points(totals, played, rest, matches, team, k)
        if extra is None:
            continue
        guarantee_total = totals[team] + extra

        # SEGURIDAD: si el equipo llega a ese total de puntos, en TODOS los
        # desenlaces debe dejar por debajo (coeficiente) a >= k rivales, es decir,
        # NO puede quedar entre los k peores promedios (empate adverso).
        for combo in itertools.product(OUTCOMES, repeat=len(matches)):
            pts, den = _final_average(totals, played, matches, combo, team)
            if pts[team] < guarantee_total:
                continue
            # cociente del equipo vs cada rival, sin float (num_a/den_a vs num_b/den_b)
            worse_or_equal = 0
            for e in teams:
                if e == team:
                    continue
                # rival por encima o igual del equipo => e*den_team >= team*den_e
                if pts[e] * den[team] >= pts[team] * den[e]:
                    worse_or_equal += 1
            # worse_or_equal = rivales que empatan o superan al equipo por promedio.
            # Para NO estar entre los k peores, deben ser menos que... el equipo
            # está a salvo si menos de (n-k) rivales quedan por debajo -> más simple:
            # el equipo NO debe estar entre los k peores => al menos k rivales por debajo.
            below = (n_teams - 1) - worse_or_equal
            assert below >= k, (
                f"SALVACIÓN FALSA promedios: team={team} k={k} extra={extra} "
                f"total={guarantee_total} pero sólo {below} rivales quedan por debajo"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
