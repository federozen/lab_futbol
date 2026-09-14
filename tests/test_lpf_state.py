"""Pruebas del constructor puro del estado canónico LPF."""
from __future__ import annotations

from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026
from lpf_parsers import parse_tabla_anual
from lpf_state import LPF_APERTURA_PJ, add_source_issues, build_lpf_state, opening_is_valid


def _rosters():
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    zb, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    return list(za), list(zb)


def _base(teams, *, pj=0):
    return {
        team: {"pts": 0, "pj": pj, "dg": 0, "gf": 0, "ga": 0, "source_pos": pos}
        for pos, team in enumerate(teams, start=1)
    }


def _fixture_state_inputs():
    za, zb = _rosters()
    teams = za + zb
    zones = {"A": _base(za), "B": _base(zb)}
    opening = {
        team: {"pts": 0, "pj": LPF_APERTURA_PJ, "dg": 0, "gf": 0, "ga": 0}
        for team in teams
    }
    annual = {
        team: {
            "pts": 0,
            "pj": LPF_APERTURA_PJ,
            "dg": 0,
            "gf": 0,
            "ga": 0,
            "source_pos": pos,
        }
        for pos, team in enumerate(teams, start=1)
    }
    return zones, opening, annual


def test_opening_is_valid_usa_nomina_y_fechas():
    zones, opening, _annual = _fixture_state_inputs()
    assert opening_is_valid(opening, zones)

    wrong_rounds = {team: dict(row) for team, row in opening.items()}
    first = next(iter(wrong_rounds))
    wrong_rounds[first]["pj"] = LPF_APERTURA_PJ - 1
    assert not opening_is_valid(wrong_rounds, zones)

    missing_team = dict(opening)
    missing_team.pop(first)
    assert not opening_is_valid(missing_team, zones)


def test_build_lpf_state_prioriza_opening_explicito():
    zones, opening, annual = _fixture_state_inputs()
    stored = {team: dict(row, pts=1) for team, row in opening.items()}
    state, report = build_lpf_state(
        zones,
        annual_direct=annual,
        opening=opening,
        stored_opening=stored,
        fixture=LPF_FIXTURE,
        camps=("Belgrano", "", ""),
        intl=("", ""),
    )

    assert state["apertura"] == opening
    assert report.opening_snapshot == opening
    assert state["anual_directo"] == report.authoritative_annual
    assert state["camps"] == ("Belgrano", "", "")


def test_build_lpf_state_usa_opening_guardado_si_el_explicito_es_invalido():
    zones, opening, annual = _fixture_state_inputs()
    invalid = {team: dict(row) for team, row in opening.items()}
    invalid[next(iter(invalid))]["pj"] = 15

    state, _report = build_lpf_state(
        zones,
        annual_direct=annual,
        opening=invalid,
        stored_opening=opening,
        fixture=LPF_FIXTURE,
    )
    assert state["apertura"] == opening


def test_build_lpf_state_deriva_opening_sin_estado_de_interfaz():
    zones, opening, annual = _fixture_state_inputs()
    state, report = build_lpf_state(
        zones,
        annual_direct=annual,
        fixture=LPF_FIXTURE,
    )

    assert state["apertura"] == opening
    assert report.opening_snapshot == opening
    assert set(state["equipos"]) == set(opening)
    assert len(state["rest"]) == 30


def test_source_issues_se_inyectan_sin_streamlit():
    zones, opening, annual = _fixture_state_inputs()
    _state, report = build_lpf_state(
        zones,
        annual_direct=annual,
        opening=opening,
        fixture=LPF_FIXTURE,
        source_issues=["BLOQUEO: fuentes desincronizadas"],
    )
    matches = [issue for issue in report.issues if issue.code == "prom_source_sync"]
    assert len(matches) == 1
    assert matches[0].level == "blocked"


def test_add_source_issues_no_duplica_lo_ya_existente():
    zones, opening, annual = _fixture_state_inputs()
    _state, report = build_lpf_state(
        zones,
        annual_direct=annual,
        opening=opening,
        fixture=LPF_FIXTURE,
        source_issues=["aviso"],
    )
    before = len(report.issues)
    same = add_source_issues(report, ["aviso"])
    assert same is report
    assert len(report.issues) == before
