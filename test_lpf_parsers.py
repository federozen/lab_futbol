"""Pruebas de los parsers de tablas pegadas (`lpf_parsers`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_parsers import (  # noqa: E402
    _parse_team_list,
    parse_promedios,
    parse_tabla_anual,
    parse_tabla_fixture,
)


def test_parse_team_list_separadores_mixtos():
    out = _parse_team_list("River, Boca, Racing\nIndependiente; Vélez")
    assert "River" in out and "Boca" in out and "Racing" in out
    assert "Independiente" in out and "Vélez" in out


def test_parse_team_list_vacio():
    assert _parse_team_list("") == []


def test_parse_promedios_una_temporada():
    out = parse_promedios("River, 40, 20\nBoca, 38, 20")
    assert out["River"] == (40, 20)
    assert out["Boca"] == (38, 20)


def test_parse_promedios_suma_temporadas():
    # «Equipo, pts1, pj1, pts2, pj2» -> se suman.
    out = parse_promedios("River, 40, 20, 35, 19")
    assert out["River"] == (75, 39)


def test_parse_tabla_fixture_detecta_partidos():
    fix = "Fecha 5\nZona A\nRiver - Boca\nRacing vs Independiente\n"
    result = parse_tabla_fixture(fix)
    # Devuelve una tupla; la lista de pares está en la posición 1.
    pares = result[1]
    normal = {tuple(sorted(p)) for p in pares}
    assert ("Boca", "River") in normal
    assert ("Independiente", "Racing") in normal


def test_parse_tabla_anual_devuelve_dict_y_avisos():
    anual = (
        "1 River Plate 40 20 30 +10 12 4 4\n"
        "2 Boca Juniors 38 20 28 +8 11 5 4\n"
    )
    tabla, avisos = parse_tabla_anual(anual)
    assert isinstance(tabla, dict)
    assert isinstance(avisos, list)
    # Determinista: misma entrada, misma salida.
    assert parse_tabla_anual(anual) == (tabla, avisos)


def test_parsers_son_deterministas():
    fix = "Fecha 1\nZona B\nTalleres - Lanús\n"
    assert parse_tabla_fixture(fix) == parse_tabla_fixture(fix)
