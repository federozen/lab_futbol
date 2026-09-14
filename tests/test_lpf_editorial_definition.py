from lpf_conditionals import branch_explanation, key_rival_matrix, next_round_conditionals
from lpf_editorial_definition import all_teams_matrix, branch_cell, definition_clock, fight_zone


def _base():
    return {
        "A": {"pts": 10},
        "B": {"pts": 9},
        "C": {"pts": 8},
        "D": {"pts": 7},
        "E": {"pts": 5},
    }


def test_all_teams_matrix_is_selectable_and_exact_by_branch():
    base = _base()
    rest = {team: 2 for team in base}
    games = [("A", "E"), ("B", "C"), ("D", "X")]
    rows = all_teams_matrix(base, rest, games, ["A", "B"], cutoff=2)
    assert [row["Equipo"] for row in rows] == ["A", "B"]
    assert all("Si gana" in row and "Si empata" in row and "Si pierde" in row for row in rows)
    assert all("%" not in row["Si gana"] for row in rows)


def test_key_rival_matrix_keeps_remaining_games_open():
    base = _base()
    rest = {team: 2 for team in base}
    games = [("A", "E"), ("B", "C"), ("D", "X")]
    report = key_rival_matrix(base, rest, games, "A", "B", cutoff=2)
    assert report["available"] is True
    assert report["key_match"] == ("B", "C")
    assert len(report["cells"]) == 9
    assert all(cell["total_combinations"] == 3 for cell in report["cells"])


def test_branch_explanation_proves_assurance_without_probability_language():
    base = {"A": {"pts": 10}, "B": {"pts": 7}, "C": {"pts": 5}, "D": {"pts": 4}}
    rest = {team: 1 for team in base}
    report = next_round_conditionals(base, rest, [("A", "X"), ("B", "C")], "A", cutoff=2)
    win = next(branch for branch in report["branches"] if branch["result"] == "G")
    text = branch_explanation(win, "los playoffs")
    assert "combinaciones" in text
    assert "asegurado" in text
    assert "probabilidad" not in text.lower()
    assert win["proof"]["max_threat_count"] < 2


def test_fight_zone_keeps_team_and_cutoff_visible():
    rows = fight_zone(_base(), {team: 3 for team in _base()}, "E", cutoff=2, radius=1)
    refs = {row["Equipo"]: row["Referencia"] for row in rows if row["Equipo"] != "…"}
    assert "E" in refs and "seleccionado" in refs["E"]
    assert any("corte" in value for value in refs.values())


def test_clock_only_uses_exact_milestones_and_guarantee():
    base = {"A": {"pts": 10}, "B": {"pts": 7}, "C": {"pts": 5}, "D": {"pts": 4}}
    rest = {team: 1 for team in base}
    report = next_round_conditionals(base, rest, [("A", "X"), ("B", "C")], "A", cutoff=2)
    rows = definition_clock(report, current_points=10, guarantee=13, guarantee_round_label="Fecha 12")
    assert rows[0]["when"] == "Próxima fecha"
    assert any(row["when"] == "Fecha 12" for row in rows)
    assert all("prob" not in (row["detail"] + row["status"]).lower() for row in rows)


def test_branch_cell_semantics_are_not_probabilities():
    base = {"A": {"pts": 10}, "B": {"pts": 7}, "C": {"pts": 5}, "D": {"pts": 4}}
    rest = {team: 1 for team in base}
    report = next_round_conditionals(base, rest, [("A", "X"), ("B", "C")], "A", cutoff=2)
    win = report["branches"][0]
    assert branch_cell(win).startswith("🟢")


def test_branch_explanation_explains_partial_failure_and_adverse_condition():
    base = {
        "A": {"pts": 3},
        "B": {"pts": 3},
        "C": {"pts": 3},
        "D": {"pts": 4},
    }
    rest = {team: 1 for team in base}
    report = next_round_conditionals(base, rest, [("A", "D"), ("B", "C")], "A", cutoff=2)
    draw = next(branch for branch in report["branches"] if branch["result"] == "E")
    text = branch_explanation(draw, "los playoffs")
    assert draw["season_in"] == 0
    assert 0 < draw["season_out"] < draw["total_combinations"]
    assert draw["elimination_sufficient_condition"] == "gana B"
    assert "no puede asegurar todavía" in text
    assert "gana B" in text
    assert "fuera de alcance" in text
    assert "no son probabilidades" in text


def test_branch_explanation_does_not_confuse_round_cut_with_assured_objective():
    base = {team: {"pts": 3} for team in ("A", "B", "C", "D")}
    rest = {team: 2 for team in base}
    report = next_round_conditionals(base, rest, [("A", "D"), ("B", "C")], "A", cutoff=2)
    win = next(branch for branch in report["branches"] if branch["result"] == "G")
    text = branch_explanation(win, "los playoffs")
    assert win["season_in"] == 0
    assert win["round_safe"] == win["total_combinations"]
    assert "dentro del corte por puntos" in text
    assert "no puede asegurar todavía" in text
    assert "queda asegurado el objetivo" not in text


def test_branch_explanation_explains_total_impossibility_by_ceiling_and_rivals():
    base = {team: {"pts": 0} for team in ("A", "B", "C", "D")}
    rest = {team: 1 for team in base}
    report = next_round_conditionals(base, rest, [("A", "D"), ("B", "C")], "A", cutoff=2)
    loss = next(branch for branch in report["branches"] if branch["result"] == "P")
    text = branch_explanation(loss, "los playoffs")
    assert loss["season_out"] == loss["total_combinations"]
    assert "techo final" in text
    assert "fuera de alcance el objetivo" in text
    assert "rivales" in text
    assert "probabilidad" not in text.lower()
