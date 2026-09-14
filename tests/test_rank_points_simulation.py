"""Regresiones de la simulación usada por Puntos y puesto final."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from lpf_simulation import simulate_zone_rank_points

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "calculadora_futbol_argentino.py"
ORIGINAL = ROOT / "_original_referencia" / "calculadora_futbol_argentino_ORIGINAL.py"


def _extract_functions(path: Path, names: set[str]):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    namespace = {
        "np": np,
        "_LPF_PDRAW": 0.26,
        "_LPF_LOCALIA": 1.22,
        "_simulate_zone_rank_points_core": simulate_zone_rank_points,
        "_fuerza_lpf": lambda base, _played: {
            team: 0.8 + (idx + 1) * 0.13 for idx, team in enumerate(base)
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def _sample_input():
    base = {
        "A": {"pts": 8, "dg": 2},
        "B": {"pts": 7, "dg": 0},
        "C": {"pts": 6, "dg": -1},
        "D": {"pts": 5, "dg": 1},
        "E": {"pts": 4, "dg": -2},
    }
    rest = {"A": 3, "B": 3, "C": 3, "D": 3, "E": 3}
    pending = [
        ("A", "B"),
        ("C", "D"),
        ("E", "A"),
        ("B", "X"),  # interzonal: sólo B pertenece a la zona
    ]
    forced = {("A", "B"): "E"}
    return base, rest, pending, forced


def test_wrapper_conserva_la_simulacion_historica_si_no_hay_interzonal_externo():
    old = _extract_functions(ORIGINAL, {"_sim_zone_pos"})["_sim_zone_pos"]
    new_ns = _extract_functions(MAIN, {"_sim_zone_rank_points", "_sim_zone_pos"})
    new = new_ns["_sim_zone_pos"]
    base, rest, pending, forced = _sample_input()
    pending = [match for match in pending if "X" not in match]

    expected = old(base, rest, pending, "A", 1200, 77, forced=forced, jugados=[])
    got = new(base, rest, pending, "A", 1200, 77, forced=forced, jugados=[])
    np.testing.assert_array_equal(got, expected)


def test_interzonal_externo_usa_al_rival_real_en_vez_de_un_rival_promedio():
    base, rest, pending, _forced = _sample_input()
    strength = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0, "X": 1.75}
    _positions, points_strong_rival = simulate_zone_rank_points(
        base, rest, pending, "B", 8000, 88, strength
    )
    strength["X"] = 0.55
    _positions, points_weak_rival = simulate_zone_rank_points(
        base, rest, pending, "B", 8000, 88, strength
    )
    assert points_weak_rival.mean() > points_strong_rival.mean()


def test_simulacion_nueva_devuelve_los_puntos_de_las_mismas_corridas():
    fn = _extract_functions(MAIN, {"_sim_zone_rank_points"})["_sim_zone_rank_points"]
    base, rest, pending, forced = _sample_input()
    positions, points = fn(base, rest, pending, "A", 900, 91, forced=forced, jugados=[])

    assert positions.shape == points.shape == (900,)
    assert np.issubdtype(points.dtype, np.integer)
    # A tiene 8 puntos y tres partidos restantes; uno queda fijado en empate.
    assert int(points.min()) >= 9
    assert int(points.max()) <= 15
