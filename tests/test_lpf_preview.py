import ast
from pathlib import Path

from lpf_preview import preview_objective, team_preview_text


ROOT = Path(__file__).resolve().parents[1]


def _zone():
    teams = [f"T{i}" for i in range(1, 10)]
    return {
        team: {"pts": 18 - i, "pj": 8, "dg": 8 - i, "gf": 10 + i, "ga": 5 + i}
        for i, team in enumerate(teams)
    }


def _window(scope="next_team_match"):
    return {
        "round": 9,
        "games": [("T1", "T2")],
        "label": "próximo partido real",
        "own_match": ("T1", "T2"),
        "own_meta": {"match": ("T1", "T2"), "round": 9, "scheduled_at": None},
        "postponed": [],
        "scope": scope,
    }


def test_preview_objective_normalizes_visible_labels():
    assert preview_objective("Playoffs") == "playoffs"
    assert preview_objective("Libertadores") == "libertadores"
    assert preview_objective("Al menos Sudamericana") == "copas"
    assert preview_objective("Descenso") == "descenso"


def test_team_preview_playoffs_is_pure_and_returns_exportable_frame():
    zone = _zone()
    zones = {"A": zone}
    pending = [("T1", "T2"), ("T3", "T4"), ("T5", "T6"), ("T7", "T8")]
    text, frame = team_preview_text(
        "T1",
        zones,
        pending,
        {},
        window=_window(),
        scenario_games=pending,
        objective="Playoffs",
        current_round=9,
        n_annual=1,
        top_eight=8,
    )
    assert text.startswith("## Próximo partido de T1")
    assert "**Si gana**" in text
    assert "EXACTO POR PUNTOS" in text
    assert list(frame["Si T1"]) == ["gana", "empata", "pierde"]
    assert frame.attrs["export_name"] == "T1_escenarios_proximo_partido"
    assert "reusable_line" in frame.attrs


def test_team_preview_descent_uses_explicit_annual_relegation_slots():
    zone = _zone()
    zones = {"A": zone}
    pending = [("T1", "T2"), ("T3", "T4"), ("T5", "T6"), ("T7", "T8")]
    text, frame = team_preview_text(
        "T1",
        zones,
        pending,
        zone,
        window=_window(),
        scenario_games=pending,
        objective="Descenso",
        current_round=9,
        n_annual=2,
        top_eight=8,
    )
    descent_rows = frame[frame["Tabla"] == "Descenso · Tabla Anual"]
    assert len(descent_rows) == 3
    assert "Tabla Anual" in text or "EXACTO POR PUNTOS" in text
    assert all(isinstance(value, str) for value in descent_rows["Lectura"])


def test_preview_module_has_no_streamlit_or_network_dependency():
    source = (ROOT / "lpf_preview.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    from_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "streamlit" not in imports | from_imports
    assert "requests" not in imports | from_imports
    assert not any(isinstance(node, ast.Attribute) and node.attr == "session_state" for node in ast.walk(tree))


def test_main_preview_function_is_only_an_adapter():
    source = (ROOT / "calculadora_futbol_argentino.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lpf_previa_equipo_texto"
    )
    legacy = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_lpf_previa_equipo_texto_legacy"
    )
    segment = ast.get_source_segment(source, fn) or ""
    legacy_segment = ast.get_source_segment(source, legacy) or ""
    assert '_lpf_service_result(' in segment
    assert '"preview"' in segment
    assert "pd.DataFrame(" in segment
    assert "_team_preview_text_core(" not in segment
    assert "_team_preview_text_core(" in legacy_segment
    assert "exact_result_scenarios(" not in segment
    assert fn.end_lineno - fn.lineno + 1 <= 50
