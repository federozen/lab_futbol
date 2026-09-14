"""Regresiones de las primitivas Monte Carlo extraídas del archivo Streamlit."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from lpf_simulation import objective_mask, simulate_point_additions, simulate_zone_rank_points

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "lpf_simulation.py"
MAIN = ROOT / "calculadora_futbol_argentino.py"


def test_modulo_no_depende_de_streamlit_ni_red():
    text = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "streamlit" not in imported
    assert "requests" not in imported
    assert "session_state" not in text


def test_simulacion_de_zona_es_reproducible_y_devuelve_puntos_enteros():
    base = {
        "A": {"pts": 10, "dg": 2},
        "B": {"pts": 9, "dg": 0},
        "C": {"pts": 7, "dg": -1},
        "D": {"pts": 6, "dg": 1},
    }
    remaining = {team: 2 for team in base}
    pending = [("A", "B"), ("C", "D")]
    strength = {"A": 1.2, "B": 1.05, "C": 0.95, "D": 0.85}
    first = simulate_zone_rank_points(base, remaining, pending, "A", 500, 41, strength)
    second = simulate_zone_rank_points(base, remaining, pending, "A", 500, 41, strength)
    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])
    assert first[0].shape == first[1].shape == (500,)
    assert np.issubdtype(first[1].dtype, np.integer)


def test_resultados_forzados_en_suma_de_puntos_son_deterministas():
    teams = ["A", "B", "C"]
    pending = [("A", "B"), ("B", "C")]
    strength = {team: 1.0 for team in teams}
    additions, idx = simulate_point_additions(
        teams,
        pending,
        strength,
        40,
        7,
        forced={("A", "B"): "L", ("B", "C"): "E"},
    )
    assert np.all(additions[:, idx["A"]] == 3)
    assert np.all(additions[:, idx["B"]] == 1)
    assert np.all(additions[:, idx["C"]] == 1)


def test_mascara_de_playoffs_respeta_top_ocho():
    teams = [f"T{i}" for i in range(10)]
    context = {
        "zona_de": {team: "A" for team in teams},
        "Z": {"A": {team: {} for team in teams}},
        "zpts": {team: 20 - i for i, team in enumerate(teams)},
        "zdg": {team: 0 for team in teams},
    }
    additions = np.zeros((3, len(teams)))
    idx = {team: i for i, team in enumerate(teams)}
    assert objective_mask("playoffs", "T0", additions, idx, context).tolist() == [True, True, True]
    assert objective_mask("playoffs", "T9", additions, idx, context).tolist() == [False, False, False]


def test_main_delega_primitivas_generales_al_modulo_puro():
    text = MAIN.read_text(encoding="utf-8")
    assert "simulate_point_additions as _sim_lpf_add" in text
    assert "objective_mask as _obj_bool" in text
    assert "simulate_zone_rank_points as _simulate_zone_rank_points_core" in text
    assert "def _sim_lpf_add(" not in text
    assert "def _obj_bool(" not in text


def _row(pts=0, pj=0, gf=0, ga=0):
    return {
        "pts": int(pts),
        "pj": int(pj),
        "gf": int(gf),
        "ga": int(ga),
        "dg": int(gf) - int(ga),
    }


def test_contexto_de_simulacion_recibe_anual_y_reemplazo_explicitamente():
    from lpf_simulation import build_simulation_context

    teams = ["River Plate", "Boca Juniors", "Racing", "Independiente"]
    zones = {
        "A": {
            "River Plate": _row(8, 4, 7, 3),
            "Boca Juniors": _row(7, 4, 6, 4),
        },
        "B": {
            "Racing": _row(6, 4, 5, 4),
            "Independiente": _row(5, 4, 4, 5),
        },
    }
    opening = {team: _row(20 + i, 16, 15 + i, 10) for i, team in enumerate(teams)}
    context = build_simulation_context(
        zones,
        {team: 12 for team in teams},
        opening,
        ("River Plate", "River Plate", "River Plate"),
        ("", ""),
        {team: (80 + i, 60) for i, team in enumerate(teams)},
        direct_annual={},
        opening_rounds=16,
        copa_replacement="Boca Juniors",
        n_annual=1,
        n_average=1,
    )
    assert context["equipos"] == teams
    assert context["zona_de"] == {"River Plate": "A", "Boca Juniors": "A", "Racing": "B", "Independiente": "B"}
    assert context["anual"]["River Plate"]["pts"] == 28
    assert context["n_lib"] == 4
    assert "Boca Juniors" in context["tomados"]
    assert context["previous_averages"]["River Plate"] == (80, 60)
    assert context["average_totals"]["River Plate"] == (108, 80)
    assert context["prom"]["River Plate"] == (108, 80)  # alias legacy = totales, no previas


def test_contexto_de_simulacion_puede_usar_anual_directa_sin_apertura():
    from lpf_simulation import build_simulation_context

    teams = ["River Plate", "Boca Juniors", "Racing", "Independiente"]
    zones = {
        "A": {"River Plate": _row(4, 2, 3, 2), "Boca Juniors": _row(3, 2, 2, 2)},
        "B": {"Racing": _row(2, 2, 2, 3), "Independiente": _row(1, 2, 1, 3)},
    }
    direct = {
        team: _row(25 - i, 18, 20 - i, 10)
        for i, team in enumerate(teams)
    }
    context = build_simulation_context(
        zones,
        {team: 14 for team in teams},
        {},
        ("", "", ""),
        ("", ""),
        {},
        direct_annual=direct,
        opening_rounds=16,
    )
    assert context["anual"]
    assert context["anual"]["River Plate"]["pj"] == 18
    assert context["apts"]["River Plate"] == 25


def test_main_delega_el_armado_del_contexto_al_modulo_puro():
    text = MAIN.read_text(encoding="utf-8")
    assert "build_simulation_context as _build_simulation_context_core" in text
    tree = ast.parse(text)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_lpf_ctx")
    calls = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_build_simulation_context_core" in calls
    assert "lpf_anual_base" not in calls
    assert "lpf_plazas_copas" not in calls


def test_contexto_de_descenso_suma_la_temporada_actual_a_las_previas():
    from lpf_simulation import build_simulation_context

    zones = {
        "A": {"A": _row(6, 4), "B": _row(4, 4)},
        "B": {"C": _row(3, 4), "D": _row(2, 4)},
    }
    opening = {team: _row(20, 16) for team in ("A", "B", "C", "D")}
    previous = {team: (80, 60) for team in ("A", "B", "C", "D")}
    context = build_simulation_context(
        zones,
        {team: 12 for team in ("A", "B", "C", "D")},
        opening,
        ("", "", ""),
        ("", ""),
        previous,
        direct_annual={},
        opening_rounds=16,
    )
    assert context["previous_averages"]["A"] == (80, 60)
    assert context["average_totals"]["A"] == (106, 80)
    assert context["prom"] == context["average_totals"]


def test_descenso_prefiere_totales_explicitos_y_no_el_alias_legacy():
    import numpy as np
    from lpf_simulation import objective_mask

    additions = np.zeros((3, 3), dtype=float)
    idx = {"A": 0, "B": 1, "C": 2}
    context = {
        "equipos": ["A", "B", "C"],
        "average_totals": {"A": (100, 10), "B": (10, 10), "C": (20, 10)},
        # Si el motor leyera este alias conflictivo, A aparecería último por promedio.
        "prom": {"A": (0, 10), "B": (10, 10), "C": (20, 10)},
        "rest": {"A": 0, "B": 0, "C": 0},
        "apts": {"A": 100, "B": 90, "C": 80},
        "adg": {"A": 0, "B": 0, "C": 0},
    }
    assert objective_mask("descenso", "A", additions, idx, context).tolist() == [False, False, False]
