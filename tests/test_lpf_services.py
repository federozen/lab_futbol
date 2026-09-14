import json
from dataclasses import asdict

import pytest

from lpf_pisos import piso_por_corte
from lpf_scenarios import point_ladder, scenario_rank_bounds
from lpf_services import (
    CONTRACT_VERSION,
    ContractError,
    calculate_objective_floor,
    calculate_point_ladder,
    calculate_rank_window,
    calculate_standings,
)
from lpf_standings import DEFAULT_CRITERIOS, _orden
from lpf_version import __version__


def _assert_envelope(response, calculation):
    assert response["contract_version"] == CONTRACT_VERSION
    assert response["calculation_version"] == __version__
    assert response["calculation"] == calculation
    json.dumps(response, ensure_ascii=False)


def test_standings_service_matches_engine_exactly():
    teams = ["A", "B", "C", "D"]
    matches = [("A", "B", 2, 0), ("C", "D", 1, 1), ("A", "C", 0, 1)]
    response = calculate_standings({
        "teams": teams,
        "matches": [
            {"home": h, "away": a, "home_goals": gh, "away_goals": ga}
            for h, a, gh, ga in matches
        ],
    })
    _assert_envelope(response, "standings")
    order, stats = _orden(teams, matches, criterios=DEFAULT_CRITERIOS)
    assert response["result"]["positions"] == {team: i for i, team in enumerate(order, 1)}
    assert response["result"]["table"] == [
        {
            "position": i,
            "team": team,
            "played": stats[team]["pj"],
            "points": stats[team]["pts"],
            "goals_for": stats[team]["gf"],
            "goals_against": stats[team]["ga"],
            "goal_difference": stats[team]["dg"],
        }
        for i, team in enumerate(order, 1)
    ]


def test_standings_service_preserves_explicit_tiebreakers():
    response = calculate_standings({
        "teams": ["A", "B"],
        "matches": [{"home": "A", "away": "B", "home_goals": 0, "away_goals": 0}],
        "tiebreakers": [],
    })
    assert response["result"]["tiebreakers"] == []
    assert response["result"]["positions"] == {"A": 1, "B": 2}


def test_standings_service_rejects_unknown_team_cleanly():
    with pytest.raises(ContractError) as exc:
        calculate_standings({
            "teams": ["A", "B"],
            "matches": [{"home": "A", "away": "C", "home_goals": 1, "away_goals": 0}],
        })
    assert exc.value.code == "unknown_team"
    assert exc.value.field == "matches"
    json.dumps(exc.value.to_dict())


def test_point_ladder_service_matches_direct_engine():
    base = {"A": {"pts": 4}, "B": {"pts": 4}, "C": {"pts": 1}}
    matches = [("A", "B"), ("A", "C"), ("B", "C")]
    direct = point_ladder(base, matches, "A", 2)
    response = calculate_point_ladder({
        "base": base,
        "matches": [{"home": h, "away": a} for h, a in matches],
        "team": "A",
        "cutoff": 2,
    })
    _assert_envelope(response, "point_ladder")
    expected = dict(direct)
    expected["rows"] = [asdict(row) for row in direct["rows"]]
    assert response["result"] == expected


def test_rank_window_service_translates_json_fixed_results():
    base = {"A": 3, "B": 3, "C": 0}
    matches = [("A", "B"), ("A", "C")]
    fixed = {("A", "B"): "E"}
    direct = scenario_rank_bounds(base, matches, "A", fixed)
    response = calculate_rank_window({
        "base": base,
        "matches": [{"home": h, "away": a} for h, a in matches],
        "team": "A",
        "fixed": [{"home": "A", "away": "B", "result": "E"}],
    })
    _assert_envelope(response, "rank_window")
    expected = dict(direct)
    expected["by_points"] = [list(row) for row in direct["by_points"]]
    assert response["result"] == expected


def test_objective_floor_service_matches_direct_engine():
    base = {"A": 5, "B": 5, "C": 2, "D": 1}
    remaining = {"A": 1, "B": 1, "C": 1, "D": 1}
    matches = [("A", "B"), ("C", "D")]
    direct = piso_por_corte(base, remaining, matches, "A", 2, clave="playoffs", nombre="los playoffs")
    response = calculate_objective_floor({
        "base": base,
        "remaining": remaining,
        "matches": [{"home": h, "away": a} for h, a in matches],
        "team": "A",
        "cutoff": 2,
        "objective_key": "playoffs",
        "objective_name": "los playoffs",
    })
    _assert_envelope(response, "objective_floor")
    expected = asdict(direct)
    expected["caminos"] = [list(row) for row in expected["caminos"]]
    expected["minimum_possible"] = direct.minimo_posible
    expected["minimum_guarantee"] = direct.garantia_exacta
    expected["safe_total"] = direct.piso
    expected["exact_guarantee"] = direct.garantia_exacta
    expected["conservative_reference"] = direct.referencia_conservadora
    expected["safe_value"] = direct.piso
    expected["floor"] = direct.piso
    expected["reading"] = direct.lectura()
    assert response["result"] == expected


def test_service_modules_do_not_require_streamlit_or_http():
    import lpf_services

    source = open(lpf_services.__file__, encoding="utf-8").read()
    assert "import streamlit" not in source
    assert "import requests" not in source


def test_version_module_is_shared_with_audit_metadata():
    from lpf_models import AuditMetadata

    assert AuditMetadata().calculation_version == __version__


def _snapshot_fixture_payload():
    teams_a = ["Equipo A", "Equipo B", "Equipo C", "Equipo D"]
    teams_b = ["Equipo E", "Equipo F", "Equipo G", "Equipo H"]
    zones = {
        "A": {team: {"pts": 0, "pj": 0, "dg": 0, "gf": 0, "ga": 0} for team in teams_a},
        "B": {team: {"pts": 0, "pj": 0, "dg": 0, "gf": 0, "ga": 0} for team in teams_b},
    }
    fixture = [
        {"f": 1, "l": "Equipo A", "v": "Equipo B", "tipo": "zone", "zona": "A"},
        {"f": 1, "l": "Equipo C", "v": "Equipo D", "tipo": "zone", "zona": "A"},
        {"f": 1, "l": "Equipo E", "v": "Equipo F", "tipo": "zone", "zona": "B"},
        {"f": 1, "l": "Equipo G", "v": "Equipo H", "tipo": "zone", "zona": "B"},
    ]
    return {"zones": zones, "fixture": fixture}


def test_competition_snapshot_is_json_safe_and_keeps_pending_state():
    from lpf_services import prepare_competition_snapshot

    response = prepare_competition_snapshot(_snapshot_fixture_payload())
    _assert_envelope(response, "competition_snapshot")
    snapshot = response["result"]
    assert snapshot["remaining"] == {f"Equipo {letter}": 1 for letter in "ABCDEFGH"}
    assert snapshot["pending"][:2] == [
        {"home": "Equipo A", "away": "Equipo B"},
        {"home": "Equipo C", "away": "Equipo D"},
    ]
    assert snapshot["rules"] == {"annual_relegations": 1, "average_relegations": 1}
    assert snapshot["audit"]["level"] == "blocked"  # nómina sintética, pero la foto sigue siendo utilizable
    json.dumps(response, ensure_ascii=False)


def test_competition_batch_reuses_snapshot_for_multiple_exact_queries():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_fixture_payload())["result"]
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [
            {"id": "obj", "type": "objective_points", "scope": "zone", "zone": "A", "team": "Equipo A", "cutoff": 2},
            {"id": "ladder", "type": "point_ladder", "scope": "zone", "zone": "A", "team": "Equipo A", "cutoff": 2},
            {"id": "rank", "type": "rank_window", "scope": "zone", "zone": "A", "team": "Equipo A"},
        ],
    })
    _assert_envelope(response, "competition_batch")
    assert [row["id"] for row in response["result"]["queries"]] == ["obj", "ladder", "rank"]
    assert [row["type"] for row in response["result"]["queries"]] == [
        "objective_points", "point_ladder", "rank_window"
    ]
    json.dumps(response, ensure_ascii=False)


def test_competition_batch_objective_matches_direct_engine():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_fixture_payload())["result"]
    base = snapshot["zones"]["A"]
    remaining = snapshot["remaining"]
    matches = [(row["home"], row["away"]) for row in snapshot["pending"] if row["home"] in base or row["away"] in base]
    direct = piso_por_corte(base, remaining, matches, "Equipo A", 2, clave="playoffs", nombre="los playoffs")
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [{
            "type": "objective_points", "scope": "zone", "zone": "A", "team": "Equipo A", "cutoff": 2,
            "objective_key": "playoffs", "objective_name": "los playoffs",
        }],
    })
    result = response["result"]["queries"][0]["result"]
    assert result["minimum_possible"] == direct.minimo_posible
    assert result["minimum_guarantee"] == direct.garantia_exacta
    assert result["safe_total"] == direct.piso
    assert result["exact_guarantee"] == direct.garantia_exacta
    assert result["conservative_reference"] == direct.referencia_conservadora
    assert result["safe_value"] == direct.piso


def test_competition_batch_descent_combines_annual_and_average_history():
    from lpf_pisos import piso_no_descenso, promedio_totales
    from lpf_services import calculate_competition_batch

    annual = {team: {"pts": pts, "pj": 2} for team, pts in {"A": 2, "B": 3, "C": 4, "D": 5}.items()}
    zones = {"A": {team: {"pts": 0, "pj": 2} for team in annual}}
    previous = {team: {"points": pts, "played": 10} for team, pts in {"A": 10, "B": 13, "C": 16, "D": 19}.items()}
    snapshot = {
        "annual": annual,
        "zones": zones,
        "remaining": {team: 1 for team in annual},
        "pending": [{"home": "A", "away": "B"}, {"home": "C", "away": "D"}],
        "previous_averages": previous,
        "rules": {"annual_relegations": 1, "average_relegations": 1},
    }
    prom_totals = promedio_totales(annual, zones, previous)
    direct = piso_no_descenso(
        annual, snapshot["remaining"], [("A", "B"), ("C", "D")], "A",
        n_anual=1, prom_totales=prom_totals, n_prom=1,
    )
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [{"type": "descent_points", "team": "A"}],
    })
    result = response["result"]["queries"][0]["result"]
    assert result["safe_value"] == direct.piso
    assert result["minimum_guarantee"] == direct.garantia_exacta
    assert result["safe_total"] == direct.piso
    assert result["exact_guarantee"] == direct.garantia_exacta
    assert result["conservative_reference"] == direct.referencia_conservadora


def test_snapshot_and_service_layers_do_not_import_streamlit_or_http():
    import lpf_snapshot

    source = open(lpf_snapshot.__file__, encoding="utf-8").read()
    assert "import streamlit" not in source
    assert "import requests" not in source


def test_competition_snapshot_real_fixture_keeps_30_teams_and_remaining_counts():
    from lpf_clubs import canon_base
    from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026
    from lpf_parsers import parse_tabla_anual
    from lpf_reconcile import _lpf_result_stats
    from lpf_services import prepare_competition_snapshot

    rosters = {
        "A": canon_base(parse_tabla_anual(ZONA_A_LPF_2026)[0]),
        "B": canon_base(parse_tabla_anual(ZONA_B_LPF_2026)[0]),
    }
    played = [
        (row["l"], row["v"], 1, 0)
        for row in LPF_FIXTURE
        if int(row["f"]) <= 2
    ]
    stats = _lpf_result_stats(played)
    zones = {
        label: {
            team: {**stats[team], "source_pos": pos}
            for pos, team in enumerate(roster, 1)
        }
        for label, roster in rosters.items()
    }
    response = prepare_competition_snapshot({
        "zones": zones,
        "played": [
            {"home": h, "away": a, "home_goals": gh, "away_goals": ga}
            for h, a, gh, ga in played
        ],
        "fixture": LPF_FIXTURE,
    })
    snapshot = response["result"]
    assert len(snapshot["teams"]) == 30
    assert set(snapshot["remaining"].values()) == {14}
    assert len(snapshot["pending"]) == 210
    json.dumps(response, ensure_ascii=False)


def test_service_floor_accessors_accept_legacy_piso_objetivo():
    from lpf_services import _floor_conservative_reference, _floor_exact_guarantee

    class LegacyFloor:
        def __init__(self, *, exacto, piso_exacto=None, piso_conservador=None):
            self.exacto = exacto
            self.piso_exacto = piso_exacto
            self.piso_conservador = piso_conservador

    exact = LegacyFloor(exacto=True, piso_exacto=25, piso_conservador=27)
    conservative = LegacyFloor(exacto=False, piso_exacto=None, piso_conservador=27)

    assert _floor_exact_guarantee(exact) == 25
    assert _floor_conservative_reference(exact) is None
    assert _floor_exact_guarantee(conservative) is None
    assert _floor_conservative_reference(conservative) == 27


def test_service_capabilities_exposes_stable_contract_and_exact_window():
    from lpf_pisos import VENTANA_EXACTA
    from lpf_services import service_capabilities
    from lpf_snapshot import SNAPSHOT_SCHEMA_VERSION

    response = service_capabilities()
    _assert_envelope(response, "capabilities")
    result = response["result"]
    assert result["snapshot_schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert result["exact_window_remaining_matches"] == VENTANA_EXACTA == 8
    assert result["batch_query_types"] == [
        "objective_points", "objective_status", "point_ladder", "rank_window", "definition", "descent_points"
    ]
    assert result["supported_snapshot_schema_versions"] == ["1", "2", "3"]
    assert result["snapshot_objectives"] == ["playoffs", "libertadores", "sudamericana"]
    assert "competition_batch" in result["operations"]
    assert "definition" in result["operations"]
    json.dumps(response, ensure_ascii=False)


def test_snapshot_declares_schema_version_and_can_be_validated():
    from lpf_services import prepare_competition_snapshot, validate_competition_snapshot
    from lpf_snapshot import SNAPSHOT_SCHEMA_VERSION

    prepared = prepare_competition_snapshot(_snapshot_fixture_payload())
    snapshot = prepared["result"]
    assert snapshot["snapshot_schema_version"] == SNAPSHOT_SCHEMA_VERSION

    validated = validate_competition_snapshot({"snapshot": snapshot})
    _assert_envelope(validated, "validate_snapshot")
    assert validated["result"] == {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "canonical": True,
        "team_count": 8,
        "zone_count": 2,
        "pending_match_count": 4,
        "has_annual": False,
        "has_average_history": False,
        "has_qualification_context": True,
        "has_traceability": True,
        "snapshot_id": snapshot["traceability"]["snapshot_id"],
        "source_age_hours": None,
    }


def test_batch_accepts_full_snapshot_service_envelope():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    prepared = prepare_competition_snapshot(_snapshot_fixture_payload())
    response = calculate_competition_batch({
        "snapshot": prepared,
        "queries": [
            {"id": "rango", "type": "rank_window", "scope": "zone", "zone": "A", "team": "Equipo A"}
        ],
    })
    _assert_envelope(response, "competition_batch")
    assert response["result"]["query_count"] == 1
    assert response["result"]["snapshot_schema_version"] == prepared["result"]["snapshot_schema_version"]
    assert response["result"]["queries"][0]["id"] == "rango"


def test_batch_rejects_unsupported_snapshot_schema():
    from lpf_services import ContractError, calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_fixture_payload())["result"]
    snapshot["snapshot_schema_version"] = "999"
    try:
        calculate_competition_batch({
            "snapshot": snapshot,
            "queries": [{"type": "rank_window", "scope": "zone", "zone": "A", "team": "Equipo A"}],
        })
    except ContractError as exc:
        assert exc.code == "unsupported_snapshot_schema"
        assert exc.field == "snapshot.snapshot_schema_version"
    else:
        raise AssertionError("debía rechazar un snapshot schema no soportado")


def test_canonical_snapshot_detects_remaining_pending_mismatch_before_calculating():
    from lpf_services import ContractError, calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_fixture_payload())["result"]
    snapshot["remaining"]["Equipo A"] = 0
    try:
        calculate_competition_batch({
            "snapshot": snapshot,
            "queries": [{"type": "rank_window", "scope": "zone", "zone": "A", "team": "Equipo A"}],
        })
    except ContractError as exc:
        assert exc.code == "inconsistent_snapshot"
        assert exc.field == "snapshot.remaining"
        assert "Equipo A" in str(exc)
    else:
        raise AssertionError("debía detectar la incoherencia entre pending y remaining")


def test_real_fixture_snapshot_passes_strict_validation():
    from lpf_clubs import canon_base
    from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026
    from lpf_parsers import parse_tabla_anual
    from lpf_reconcile import _lpf_result_stats
    from lpf_services import prepare_competition_snapshot, validate_competition_snapshot

    rosters = {
        "A": canon_base(parse_tabla_anual(ZONA_A_LPF_2026)[0]),
        "B": canon_base(parse_tabla_anual(ZONA_B_LPF_2026)[0]),
    }
    played = [(row["l"], row["v"], 1, 0) for row in LPF_FIXTURE if int(row["f"]) <= 2]
    stats = _lpf_result_stats(played)
    zones = {
        label: {
            team: {**stats[team], "source_pos": pos}
            for pos, team in enumerate(roster, 1)
        }
        for label, roster in rosters.items()
    }
    prepared = prepare_competition_snapshot({
        "zones": zones,
        "played": [
            {"home": h, "away": a, "home_goals": gh, "away_goals": ga}
            for h, a, gh, ga in played
        ],
        "fixture": LPF_FIXTURE,
    })
    result = validate_competition_snapshot({"snapshot": prepared})["result"]
    assert result["team_count"] == 30
    assert result["zone_count"] == 2
    assert result["pending_match_count"] == 210
    assert result["canonical"] is True



def _snapshot_with_qualification_payload():
    payload = _snapshot_fixture_payload()
    names = [f"Equipo {letter}" for letter in "ABCDEFGH"]
    payload["opening"] = {
        team: {"pts": points, "pj": 2, "gf": points, "ga": 0, "dg": points}
        for team, points in zip(names, [6, 5, 4, 3, 2, 1, 0, 0])
    }
    payload["rules"] = {
        "opening_rounds": 2,
        "playoff_cutoff": 2,
        "sudamericana_slots": 2,
    }
    payload["qualification"] = {
        "champions": {"apertura": "Equipo A"},
        "international_champions": {},
    }
    return payload


def test_snapshot_schema_2_embeds_playoffs_and_cup_context():
    from lpf_services import prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    assert snapshot["snapshot_schema_version"] == "3"
    assert snapshot["format"] == {
        "opening_rounds": 2,
        "playoff_cutoff": 2,
        "sudamericana_slots": 2,
    }
    assert snapshot["qualification"]["playoffs"]["zones"]["A"]["cutoff"] == 2
    lib = snapshot["qualification"]["libertadores"]
    sud = snapshot["qualification"]["sudamericana"]
    assert lib["cutoff"] == 3
    assert sud["cutoff"] == 5
    assert lib["direct_qualifiers"] == ["Equipo A"]
    assert "Equipo A" not in lib["eligible_teams"]
    assert "Campeón del Apertura" in lib["direct_reasons"]["Equipo A"]


def test_batch_resolves_playoffs_and_cups_without_client_cutoff_or_reduced_table():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [
            {"id": "p", "type": "objective_status", "objective": "playoffs", "zone": "A", "team": "Equipo B"},
            {"id": "l", "type": "objective_status", "objective": "libertadores", "team": "Equipo B"},
            {"id": "s", "type": "objective_status", "objective": "sudamericana", "team": "Equipo B"},
        ],
    })
    rows = {row["id"]: row["result"] for row in response["result"]["queries"]}
    assert rows["p"]["objective"] == "playoffs" and rows["p"]["cutoff"] == 2
    assert rows["l"]["objective"] == "libertadores" and rows["l"]["cutoff"] == 3
    assert rows["s"]["objective"] == "sudamericana" and rows["s"]["cutoff"] == 5
    assert all(rows[key]["status"] == "open" for key in ("p", "l", "s"))


def test_batch_reports_direct_libertadores_route_as_resolved_objective():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [
            {"id": "lib", "type": "objective_status", "objective": "libertadores", "team": "Equipo A"},
            {"id": "sud", "type": "objective_status", "objective": "sudamericana", "team": "Equipo A"},
        ],
    })
    rows = {row["id"]: row["result"] for row in response["result"]["queries"]}
    assert rows["lib"]["resolved"] is True
    assert rows["lib"]["status"] == "already_qualified_direct"
    assert "Campeón del Apertura" in rows["lib"]["via"]
    assert rows["sud"]["status"] == "already_qualified_higher_competition"



def test_objective_points_can_use_snapshot_objective_without_cutoff():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [{
            "type": "objective_points",
            "objective": "libertadores",
            "team": "Equipo B",
        }],
    })
    result = response["result"]["queries"][0]["result"]
    assert result["objective"] == "libertadores"
    assert result["cutoff"] == snapshot["qualification"]["libertadores"]["cutoff"]
    assert result["status"] == "open"


def test_validate_snapshot_rejects_corrupt_cup_cutoff():
    from lpf_services import ContractError, prepare_competition_snapshot, validate_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    snapshot["qualification"]["libertadores"]["cutoff"] = 999
    with pytest.raises(ContractError) as exc:
        validate_competition_snapshot({"snapshot": snapshot})
    assert exc.value.code == "inconsistent_snapshot"
    assert exc.value.field == "snapshot.qualification.libertadores.cutoff"

def test_schema_1_remains_valid_for_legacy_queries_but_not_direct_objective_context():
    from lpf_services import ContractError, calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_fixture_payload())["result"]
    snapshot["snapshot_schema_version"] = "1"
    snapshot.pop("qualification", None)
    snapshot.pop("qualification_inputs", None)
    snapshot.pop("format", None)
    legacy = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [{"type": "rank_window", "scope": "zone", "zone": "A", "team": "Equipo A"}],
    })
    assert legacy["result"]["query_count"] == 1
    with pytest.raises(ContractError) as exc:
        calculate_competition_batch({
            "snapshot": snapshot,
            "queries": [{"type": "objective_status", "objective": "playoffs", "zone": "A", "team": "Equipo A"}],
        })
    assert exc.value.code == "missing_qualification_context"

def test_definition_service_exposes_exact_package_json_safe():
    from lpf_services import calculate_definition

    base = {"A": {"pts": 5}, "B": {"pts": 4}, "C": {"pts": 3}, "D": {"pts": 2}}
    remaining = {team: 1 for team in base}
    games = [("A", "D"), ("B", "C")]
    response = calculate_definition({
        "base": base,
        "remaining": remaining,
        "round_matches": [{"home": h, "away": a} for h, a in games],
        "pending_matches": [{"home": h, "away": a} for h, a in games],
        "fixture": [{"f": 12, "l": h, "v": a} for h, a in games],
        "team": "A",
        "cutoff": 2,
        "selected_teams": ["A", "B"],
        "key_team": "B",
    })
    _assert_envelope(response, "definition")
    assert response["result"]["available"] is True
    assert response["result"]["key_rival"]["available"] is True
    assert response["result"]["matrix"][0]["Equipo"] == "A"


def test_definition_service_rejects_unknown_selected_team():
    from lpf_services import calculate_definition

    with pytest.raises(ContractError) as exc:
        calculate_definition({
            "base": {"A": {"pts": 1}, "B": {"pts": 0}},
            "remaining": {"A": 1, "B": 1},
            "round_matches": [{"home": "A", "away": "B"}],
            "team": "A",
            "cutoff": 1,
            "selected_teams": ["A", "X"],
        })
    assert exc.value.code == "unknown_team"
    assert exc.value.field == "selected_teams"


def test_definition_can_use_snapshot_objective_and_round_without_base_or_cutoff():
    from lpf_services import calculate_definition, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_definition({
        "snapshot": snapshot,
        "team": "Equipo B",
        "objective": "playoffs",
        "zone": "A",
        "round": 1,
        "selected_teams": ["Equipo B", "Equipo C"],
    })
    _assert_envelope(response, "definition")
    result = response["result"]
    assert result["available"] is True
    assert result["objective"] == "playoffs"
    assert result["cutoff"] == 2
    assert result["round"] == 1
    assert result["round_label"] == "Fecha 1"
    assert result["zone"] == "A"
    assert [row["Equipo"] for row in result["matrix"]] == ["Equipo B", "Equipo C"]


def test_definition_snapshot_supports_fecha_alias_for_cups():
    from lpf_services import calculate_definition, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_definition({
        "snapshot": snapshot,
        "team": "Equipo B",
        "objective": "libertadores",
        "fecha": 1,
    })
    result = response["result"]
    assert result["objective"] == "libertadores"
    assert result["cutoff"] == snapshot["qualification"]["libertadores"]["cutoff"]
    assert result["round"] == 1
    assert result["definition_needed"] is True


def test_definition_snapshot_resolves_direct_qualification_before_round_math():
    from lpf_services import calculate_definition, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    result = calculate_definition({
        "snapshot": snapshot,
        "team": "Equipo A",
        "objective": "libertadores",
        "round": 99,
    })["result"]
    assert result["resolved"] is True
    assert result["definition_needed"] is False
    assert result["status"] == "already_qualified_direct"
    assert "Campeón del Apertura" in result["via"]


def test_competition_batch_accepts_definition_query_by_objective():
    from lpf_services import calculate_competition_batch, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate_competition_batch({
        "snapshot": snapshot,
        "queries": [{
            "id": "def",
            "type": "definition",
            "objective": "sudamericana",
            "team": "Equipo B",
            "round": 1,
        }],
    })
    row = response["result"]["queries"][0]
    assert row["id"] == "def" and row["type"] == "definition"
    assert row["result"]["objective"] == "sudamericana"
    assert row["result"]["round"] == 1
    assert row["result"]["available"] is True


def test_definition_snapshot_rejects_round_without_pending_matches():
    from lpf_services import ContractError, calculate_definition, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    with pytest.raises(ContractError) as exc:
        calculate_definition({
            "snapshot": snapshot,
            "team": "Equipo B",
            "objective": "playoffs",
            "zone": "A",
            "round": 99,
        })
    assert exc.value.code == "round_not_pending"
    assert exc.value.field == "round"


def test_public_service_surface_exposes_seven_stable_operations():
    from lpf_services import PUBLIC_OPERATIONS, PUBLIC_SERVICE_VERSION, service_capabilities

    assert PUBLIC_SERVICE_VERSION == "1"
    assert PUBLIC_OPERATIONS == (
        "standings",
        "preview",
        "objective_points",
        "objective_chances",
        "definition",
        "relegation",
        "competition_batch",
    )
    result = service_capabilities()["result"]
    assert result["public_service_version"] == "1"
    assert result["public_operations"] == list(PUBLIC_OPERATIONS)


def test_public_dispatcher_uses_snapshot_for_standings_and_objective_points():
    from lpf_services import calculate, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    standings = calculate("standings", {
        "snapshot": snapshot,
        "objective": "playoffs",
        "zone": "A",
    })
    _assert_envelope(standings, "standings")
    assert standings["result"]["objective"] == "playoffs"
    assert standings["result"]["cutoff"] == 2
    assert [row["team"] for row in standings["result"]["table"]] == [
        "Equipo A", "Equipo B", "Equipo C", "Equipo D"
    ]

    points = calculate("objective_points", {
        "snapshot": snapshot,
        "team": "Equipo B",
        "objective": "libertadores",
    })
    _assert_envelope(points, "objective_points")
    assert points["result"]["objective"] == "libertadores"
    assert points["result"]["cutoff"] == snapshot["qualification"]["libertadores"]["cutoff"]
    json.dumps(points, ensure_ascii=False)


def test_public_preview_is_json_safe_and_contains_no_dataframe():
    from lpf_services import calculate, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate("preview", {
        "snapshot": snapshot,
        "team": "Equipo B",
        "objective": "playoffs",
        "scope": "official_round",
        "round": 1,
    })
    _assert_envelope(response, "preview")
    result = response["result"]
    assert result["team"] == "Equipo B"
    assert result["round"] == 1
    assert result["own_match"] == ["Equipo A", "Equipo B"]
    assert isinstance(result["scenarios"], list) and len(result["scenarios"]) >= 3
    assert isinstance(result["markdown"], str) and "Equipo B" in result["markdown"]
    json.dumps(response, ensure_ascii=False)


def test_public_objective_chances_is_estimated_and_defaults_are_not_exact_claims():
    from lpf_services import calculate, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate("objective_chances", {
        "snapshot": snapshot,
        "team": "Equipo B",
        "objective": "playoffs",
        "zone": "A",
        "simulations": 1000,
        "seed": 7,
    })
    _assert_envelope(response, "objective_chances")
    result = response["result"]
    assert result["estimated"] is True
    assert result["simulations"] == 1000
    assert 0.0 <= result["qualification_probability"] <= 1.0
    assert 0.0 <= result["qualification_percentage"] <= 100.0
    assert result["projection"]["simulations"] == 1000
    json.dumps(response, ensure_ascii=False)


def test_public_objective_chances_resolves_direct_qualification_without_monte_carlo():
    from lpf_services import calculate, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate("objective_chances", {
        "snapshot": snapshot,
        "team": "Equipo A",
        "objective": "libertadores",
    })
    result = response["result"]
    assert result["resolved"] is True
    assert result["estimated"] is False
    assert result["simulations"] == 0
    assert result["qualification_probability"] == 1.0


def test_public_relegation_marks_missing_average_history_as_incomplete():
    from lpf_services import calculate, prepare_competition_snapshot

    snapshot = prepare_competition_snapshot(_snapshot_with_qualification_payload())["result"]
    response = calculate("relegation", {"snapshot": snapshot, "team": "Equipo B"})
    _assert_envelope(response, "relegation")
    result = response["result"]
    assert result["average_relegations"] == 1
    assert result["average_data_available"] is False
    assert result["complete"] is False
    assert "promedios" in result["warning"].lower()
    assert result["team"]["name"] == "Equipo B"
    json.dumps(response, ensure_ascii=False)


def test_public_dispatcher_rejects_unknown_operation_with_stable_error():
    from lpf_services import ContractError, calculate

    with pytest.raises(ContractError) as exc:
        calculate("fastapi_magic", {})
    assert exc.value.code == "unknown_operation"
    assert exc.value.field == "operation"
    json.dumps(exc.value.to_dict(), ensure_ascii=False)
