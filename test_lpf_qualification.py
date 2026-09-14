"""Regresiones para Tabla Anual autoritativa y reparto de plazas internacionales."""
from __future__ import annotations

import random

from lpf_clubs import LPF_CLUBES, canon_base
from lpf_data_quality import sum_opening_and_zones, validate_annual
from lpf_qualification import (
    allocate_cup_slots, annual_base, copa_argentina_alive, copa_snapshot_label,
    fixed_libertadores_qualifiers,
)
from lpf_standings import liga_tabla_df
from lpf_text import _zlow


def _row(pts=0, pj=0, gf=0, ga=0):
    return {"pts": int(pts), "pj": int(pj), "gf": int(gf), "ga": int(ga), "dg": int(gf) - int(ga)}


def _reference_annual(zones, opening, direct, opening_rounds):
    teams = {team for base in (zones or {}).values() for team in base}
    opening = canon_base(opening or {})
    if teams and set(opening) == teams:
        return sum_opening_and_zones(opening, zones)
    direct = canon_base(direct or {})
    if direct and not any(
        issue.level == "blocked"
        for issue in validate_annual(zones, direct, opening_rounds=opening_rounds)
    ):
        return direct
    return {}


def _reference_match(name, teams):
    nn = _zlow(name)
    for team in teams:
        if _zlow(team) == nn:
            return team
    for team in teams:
        candidate = _zlow(team)
        if candidate in nn or nn in candidate:
            return team
    tokens = set(nn.split())
    best, score = None, 0
    for team in teams:
        overlap = len(tokens & set(_zlow(team).split()))
        if overlap > score:
            best, score = team, overlap
    return best if score else None


def _reference_allocate(annual, camps=("", "", ""), extras=("", ""), copa_replacement=""):
    order = list(liga_tabla_df(annual)["Equipo"])

    def norm(value):
        value = (value or "").strip()
        return (_reference_match(value, order) or "") if value else ""

    ca, cc, cq = [norm(x) for x in camps]
    xl, xs = [norm(x) for x in extras]
    cr = norm(copa_replacement)
    lib, notices = [], []

    def already(team):
        return any(team == current for current, _ in lib)

    def add(team, reason):
        if team and not already(team):
            lib.append((team, reason))
            return True
        return False

    if xl:
        add(xl, "Campeón de la Libertadores 2026 — plaza adicional (art. 27.9)")
    if xs:
        add(xs, "Campeón de la Sudamericana 2026 — plaza adicional (art. 27.10)")
    base_slots = 6
    for team, reason, article in ((ca, "Campeón del Apertura", "27.1"), (cc, "Campeón del Clausura", "27.2")):
        if team:
            if already(team):
                notices.append(f"{team} ya tenía plaza, así que su lugar como {reason} lo toma el siguiente mejor de la anual (art. 27.7/27.9).")
            else:
                add(team, f"{reason} (art. {article})")
                base_slots -= 1
    if cq:
        if already(cq):
            if cr and not already(cr):
                add(cr, "Mejor equipo de Primera de la Copa Argentina — hereda ARGENTINA 3 (arts. 27.8 y 27.8.1)")
                notices.append(f"{cq} ya tenía plaza: ARGENTINA 3 fue asignada a {cr}, mejor equipo de Primera cargado de la Copa Argentina.")
            else:
                notices.append(f"{cq} (Copa Argentina) ya tenía plaza: **ARGENTINA 3 la hereda el mejor equipo de Primera de la Copa Argentina 2026**, no el siguiente de la anual (art. 27.8). Cargá ese reemplazo cuando quede definido.")
            base_slots -= 1
        else:
            add(cq, "Campeón de la Copa Argentina (art. 27.3, plaza inalterable)")
            base_slots -= 1
    else:
        notices.append("Falta definirse el campeón de la **Copa Argentina 2026**. Su plaza **ARGENTINA 3** permanece dentro de esa competencia y, cuando se conozca al campeón, ese club ya no consumirá otro cupo por la Tabla Anual.")
        base_slots -= 1
    if not ca:
        notices.append("Falta el campeón del **Apertura**.")
        base_slots -= 1
    if not cc:
        notices.append("Falta el campeón del **Clausura** (se define en los playoffs).")
        base_slots -= 1
    table_slots = max(0, base_slots)
    taken = [team for team, _ in lib]
    reduced = [team for team in order if team not in taken]
    for team in reduced[:table_slots]:
        lib.append((team, f"por Tabla Anual ({order.index(team)+1}º) — arts. 27.4 a 27.6"))
    return {
        "lib": lib,
        "n_tabla_lib": table_slots,
        "orden": order,
        "reducida": reduced,
        "avisos": notices,
        "anual": annual,
        "tomados": [team for team, _ in lib],
    }


def test_annual_base_prefiere_apertura_completo():
    teams = list(LPF_CLUBES)[:4]
    zones = {"A": {team: _row(3 + i, 2, 2 + i, 1) for i, team in enumerate(teams)}}
    opening = {team: _row(20 + i, 14, 15 + i, 10) for i, team in enumerate(teams)}
    direct = {team: _row(99, 16, 50, 0) for team in teams}
    assert annual_base(zones, opening=opening, direct_annual=direct, opening_rounds=14) == sum_opening_and_zones(opening, zones)


def test_annual_base_acepta_directa_valida_si_no_hay_apertura():
    teams = list(LPF_CLUBES)[4:8]
    zones = {"A": {team: _row(3 + i, 2, 2 + i, 1) for i, team in enumerate(teams)}}
    direct = {team: _row(23 + i, 16, 17 + i, 10) for i, team in enumerate(teams)}
    assert annual_base(zones, opening={}, direct_annual=direct, opening_rounds=14) == canon_base(direct)


def test_annual_base_rechaza_directa_bloqueada():
    teams = list(LPF_CLUBES)[8:12]
    zones = {"A": {team: _row(3, 2, 2, 1) for team in teams}}
    direct = {team: _row(20, 15, 10, 5) for team in teams}  # PJ incorrectos: deberían ser 16
    assert annual_base(zones, opening={}, direct_annual=direct, opening_rounds=14) == {}


def test_annual_base_equivale_al_codigo_3822_en_300_casos():
    rng = random.Random(3822)
    teams = list(LPF_CLUBES)[:10]
    for _ in range(300):
        split = rng.randint(4, 6)
        zones = {
            "A": {team: _row(rng.randint(0, 15), rng.randint(0, 5), rng.randint(0, 10), rng.randint(0, 10)) for team in teams[:split]},
            "B": {team: _row(rng.randint(0, 15), rng.randint(0, 5), rng.randint(0, 10), rng.randint(0, 10)) for team in teams[split:]},
        }
        for base in zones.values():
            for row in base.values():
                row["dg"] = row["gf"] - row["ga"]
        if rng.random() < 0.5:
            opening = {team: _row(rng.randint(0, 35), 14, rng.randint(0, 25), rng.randint(0, 25)) for team in teams}
            for row in opening.values():
                row["dg"] = row["gf"] - row["ga"]
        else:
            opening = {}
        direct = {}
        for team, zone_row in [(team, row) for base in zones.values() for team, row in base.items()]:
            pj = 14 + zone_row["pj"] + (0 if rng.random() < 0.8 else 1)
            pts = min(3 * pj, zone_row["pts"] + rng.randint(0, 25))
            gf, ga = rng.randint(0, 30), rng.randint(0, 30)
            direct[team] = _row(pts, pj, gf, ga)
        expected = _reference_annual(zones, opening, direct, 14)
        actual = annual_base(zones, opening=opening, direct_annual=direct, opening_rounds=14)
        assert actual == expected


def test_allocate_cup_slots_equivale_al_codigo_3822_en_600_casos():
    rng = random.Random(2728)
    teams = list(LPF_CLUBES)[:14]
    annual = {}
    for index, team in enumerate(teams):
        annual[team] = _row(50 - index, 30, 40 - index, 20)
    aliases = {
        "River Plate": "river",
        "Boca Juniors": "boca",
        "Atlético Tucumán": "tucuman",
        "Argentinos Juniors": "argentinos",
    }
    options = [""] + teams + [aliases.get(team, team) for team in teams]
    for _ in range(600):
        camps = tuple(rng.choice(options) for _ in range(3))
        extras = tuple(rng.choice(options) for _ in range(2))
        replacement = rng.choice(options)
        assert allocate_cup_slots(
            annual, camps=camps, extras=extras, copa_replacement=replacement
        ) == _reference_allocate(annual, camps, extras, replacement)


def test_modulo_no_depende_de_streamlit_ni_red():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "lpf_qualification.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "import requests" not in source


def _reference_fixed_qualifiers(annual, camps=("", "", ""), extras=("", ""), replacement=""):
    order = list(liga_tabla_df(annual)["Equipo"]) if annual else []
    result = []
    raws = tuple(camps or ()) + tuple(extras or ())
    if replacement:
        raws += (replacement,)
    for raw in raws:
        team = _reference_match(raw, order) if raw else ""
        if team and team not in result:
            result.append(team)
    return result


def _reference_copa_alive(annual, vivos):
    order = list(liga_tabla_df(annual)["Equipo"]) if annual else []
    result = []
    for raw in vivos or []:
        team = _reference_match(raw, order)
        if team and team not in result:
            result.append(team)
    return result


def test_contexto_copas_equivale_al_codigo_3823_en_800_casos():
    rng = random.Random(3823)
    teams = list(LPF_CLUBES)[:16]
    annual = {
        team: _row(60 - index, 30, 45 - index, 20)
        for index, team in enumerate(teams)
    }
    aliases = {
        "River Plate": "river",
        "Boca Juniors": "boca",
        "Atlético Tucumán": "tucuman",
        "Argentinos Juniors": "argentinos",
        "Estudiantes de La Plata": "estudiantes",
    }
    options = [""] + teams + [aliases.get(team, team) for team in teams] + ["equipo inexistente"]

    for _ in range(400):
        camps = tuple(rng.choice(options) for _ in range(3))
        extras = tuple(rng.choice(options) for _ in range(2))
        replacement = rng.choice(options)
        assert fixed_libertadores_qualifiers(
            annual, camps=camps, extras=extras, copa_replacement=replacement
        ) == _reference_fixed_qualifiers(annual, camps, extras, replacement)

    for _ in range(400):
        vivos = [rng.choice(options) for _ in range(rng.randint(0, 12))]
        assert copa_argentina_alive(annual, vivos) == _reference_copa_alive(annual, vivos)


def test_contexto_copas_sin_anual_no_inventa_equipos():
    assert fixed_libertadores_qualifiers(
        {}, camps=("River", "Boca", ""), extras=("Racing", ""), copa_replacement="Tigre"
    ) == []
    assert copa_argentina_alive({}, ["River", "Boca"]) == []


def test_copa_snapshot_label_conserva_formato_editorial_3823():
    assert copa_snapshot_label("2026-08-11", "AFA") == "2026-08-11; fuente: AFA"
    assert copa_snapshot_label("2026-08-11", "") == "2026-08-11"
    assert copa_snapshot_label("", "AFA") == "AFA"
    assert copa_snapshot_label("", "") == ""
