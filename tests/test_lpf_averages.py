"""Contrato explícito entre antecedentes y totales de promedios."""

from lpf_averages import (
    combine_average_totals,
    normalize_previous_averages,
    previous_averages_json,
)


def test_normaliza_formatos_legacy_y_json_y_canonicaliza_nombres():
    previous = {
        "River": (123, 73),
        "Boca": [129, 73],
        "Racing": {"points": 120, "played": 73},
        "Independiente": {"pts": 118, "pj": 73},
        "fila rota": "x",
    }
    out = normalize_previous_averages(previous)
    assert out["River Plate"] == (123, 73)
    assert out["Boca Juniors"] == (129, 73)
    assert out["Racing"] == (120, 73)
    assert out["Independiente"] == (118, 73)
    assert "fila rota" not in out


def test_json_de_previas_no_mezcla_temporada_actual():
    assert previous_averages_json({"River": (123, 73)}) == {
        "River Plate": {"points": 123, "played": 73}
    }


def test_totales_usan_pts_y_pj_de_la_tabla_anual_no_solo_del_clausura():
    annual = {
        "Boca Juniors": {"pts": 30, "pj": 17},
        "River Plate": {"pts": 29, "pj": 17},
    }
    zones = {
        "A": {"Boca Juniors": {"pts": 0, "pj": 1}},
        "B": {"River Plate": {"pts": 0, "pj": 1}},
    }
    previous = {
        "Boca": (129, 73),
        "River": (123, 73),
    }
    totals = combine_average_totals(annual, previous, zones=zones)
    assert totals == {
        "Boca Juniors": (159, 90),
        "River Plate": (152, 90),
    }
    assert round(totals["Boca Juniors"][0] / totals["Boca Juniors"][1], 3) == 1.767


def test_zona_es_solo_respaldo_si_la_anual_legacy_no_trae_pj():
    annual = {"Boca Juniors": {"pts": 30}}
    zones = {"A": {"Boca Juniors": {"pj": 4}}}
    assert combine_average_totals(annual, {"Boca": (129, 73)}, zones=zones) == {
        "Boca Juniors": (159, 77)
    }


def test_equipo_sin_antecedente_queda_solo_con_temporada_actual():
    annual = {
        "Aldosivi": {"pts": 9, "pj": 17},
        "Estudiantes RC": {"pts": 8, "pj": 17},
    }
    previous = {"Aldosivi": (33, 32)}
    assert combine_average_totals(annual, previous) == {
        "Aldosivi": (42, 49),
        "Estudiantes RC": (8, 17),
    }


def test_sin_historico_no_inventa_totales_de_promedios():
    assert combine_average_totals({"A": {"pts": 1, "pj": 1}}, {}) is None
