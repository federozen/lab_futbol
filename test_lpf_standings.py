"""Pruebas de las primitivas de tabla (`lpf_standings`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_standings import (  # noqa: E402
    DEFAULT_CRITERIOS, _liga_in_out, _orden, _stats, _stats_entre, liga_tabla_df,
    posiciones, tabla,
)


def test_stats_puntos_y_diferencia():
    partidos = [("A", "B", 2, 0), ("A", "C", 1, 1), ("B", "C", 0, 3)]
    s = _stats(["A", "B", "C"], partidos)
    assert s["A"]["pts"] == 4  # gana + empata
    assert s["A"]["pj"] == 2
    assert s["A"]["dg"] == 3 - 1
    assert s["C"]["pts"] == 4  # empata + gana
    assert s["B"]["pts"] == 0


def test_stats_entre_solo_cuenta_partidos_internos():
    partidos = [("A", "B", 1, 0), ("A", "X", 5, 0)]  # X está fuera del subgrupo
    s = _stats_entre(["A", "B"], partidos)
    assert s["A"]["pts"] == 3
    assert s["A"]["gf"] == 1  # el 5-0 contra X no cuenta


def test_liga_tabla_df_ordena_por_pts_dg_gf():
    base = {
        "A": {"pts": 10, "dg": 5, "gf": 12, "pj": 8},
        "B": {"pts": 10, "dg": 8, "gf": 15, "pj": 8},
        "C": {"pts": 7, "dg": 0, "gf": 6, "pj": 8},
    }
    df = liga_tabla_df(base)
    assert list(df["Equipo"]) == ["B", "A", "C"]  # B arriba de A por DG
    assert list(df["Pos"]) == [1, 2, 3]


def test_liga_tabla_df_respeta_source_pos_en_empate_total():
    base = {
        "A": {"pts": 5, "dg": 0, "gf": 3, "pj": 4, "source_pos": 2},
        "B": {"pts": 5, "dg": 0, "gf": 3, "pj": 4, "source_pos": 1},
    }
    df = liga_tabla_df(base)
    assert list(df["Equipo"]) == ["B", "A"]  # B tenía mejor puesto publicado


def test_liga_in_out():
    base = {"A": {"pts": 20}, "B": {"pts": 18}, "C": {"pts": 8}, "D": {"pts": 5}}
    rest = {"A": 0, "B": 0, "C": 0, "D": 0}  # temporada terminada
    assert _liga_in_out("A", base, rest, 2) == "in"
    assert _liga_in_out("C", base, rest, 2) == "out"


def test_liga_in_out_en_carrera():
    base = {"A": {"pts": 10}, "B": {"pts": 9}, "C": {"pts": 8}}
    rest = {"A": 3, "B": 3, "C": 3}  # todo por definirse
    assert _liga_in_out("B", base, rest, 1) == "pelea"


def test_orden_default_equivale_a_criterios_lpf_explicitos():
    equipos = ["A", "B", "C"]
    partidos = [("A", "B", 1, 0), ("B", "C", 2, 0), ("C", "A", 3, 1)]
    assert _orden(equipos, partidos)[0] == _orden(
        equipos, partidos, criterios=DEFAULT_CRITERIOS,
    )[0]


def test_orden_respeta_criterios_vacios_sin_reemplazarlos_por_default():
    equipos = ["B", "A"]
    partidos = [("B", "A", 2, 0), ("A", "B", 2, 0)]
    # Igualados en puntos; sin criterios finos, el fallback histórico es alfabético.
    assert _orden(equipos, partidos, criterios=[])[0] == ["A", "B"]


def test_mano_a_mano_puede_definir_un_empate_en_puntos():
    equipos = ["A", "B", "C"]
    partidos = [
        ("A", "B", 1, 0),
        ("A", "C", 0, 3),
        ("B", "C", 4, 0),
    ]
    # A y B terminan con 3 puntos; A ganó el duelo directo.
    assert _orden(equipos, partidos, criterios=["h2h_pts"])[0][:2] == ["A", "B"]


def test_fair_play_y_ranking_son_dependencias_explicitas():
    equipos = ["A", "B"]
    partidos = [("A", "B", 0, 0)]
    assert _orden(
        equipos, partidos, fair_play={"A": -5, "B": -2}, criterios=["fair_play"],
    )[0] == ["B", "A"]
    assert _orden(
        equipos, partidos, ranking={"A": 2, "B": 1}, criterios=["ranking"],
    )[0] == ["B", "A"]


def test_posiciones_y_tabla_comparten_el_mismo_orden_puro():
    equipos = ["A", "B", "C"]
    partidos = [("A", "B", 2, 0), ("C", "A", 1, 1)]
    criterios = ["dg", "gf"]
    pos = posiciones(equipos, partidos, criterios=criterios)
    df = tabla(equipos, partidos, criterios=criterios)
    assert list(df["Equipo"]) == [e for e, _ in sorted(pos.items(), key=lambda kv: kv[1])]
    assert list(df.columns) == ["Pos", "Equipo", "PJ", "PTS", "GF", "GC", "DG"]
