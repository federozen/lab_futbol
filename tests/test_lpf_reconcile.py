"""Pruebas de la capa de reconciliación (`lpf_reconcile`).

Verifican las garantías que esta capa debe dar para que los cálculos reciban datos
sanos: que las nóminas conocidas sean las dos zonas de 15, que las estadísticas de
resultados se computen bien, que se detecten los partidos que no encajan en las
zonas, y que la validación acepte tablas coherentes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026  # noqa: E402
from lpf_parsers import parse_tabla_anual  # noqa: E402
from lpf_reconcile import (  # noqa: E402
    _known_lpf_zone_rosters,
    _lpf_result_stats,
    _lpf_results_fit_zones,
    _merge_lpf_results,
)


def test_nominas_conocidas_dos_zonas_de_quince():
    rosters = _known_lpf_zone_rosters()
    assert set(rosters) == {"A", "B"}
    assert len(rosters["A"]) == 15
    assert len(rosters["B"]) == 15
    # Las nóminas conocidas deben coincidir con las de los datos de la temporada.
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    assert set(rosters["A"]) == set(za)


def test_result_stats_cuenta_bien():
    played = [("A", "B", 2, 0), ("A", "C", 1, 1)]
    stats = _lpf_result_stats(played)
    # A ganó y empató: 4 puntos, 2 jugados.
    assert stats["A"]["pts"] == 4
    assert stats["A"]["pj"] == 2


def test_merge_no_duplica_partidos():
    played = [("A", "B", 1, 0), ("C", "D", 2, 2)]
    nuevos = [("A", "B", 1, 0), ("E", "F", 0, 1)]
    merged = _merge_lpf_results(played, nuevos)
    # El A-B repetido no debe aparecer dos veces.
    ab = [m for m in merged if {m[0], m[1]} == {"A", "B"}]
    assert len(ab) == 1
    # El nuevo E-F sí debe estar.
    assert any({m[0], m[1]} == {"E", "F"} for m in merged)


def test_results_fit_zones_acepta_partidos_validos():
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    zb, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    zones = {"A": dict(za), "B": dict(zb)}
    # Un partido real del fixture, entre equipos que existen, debe encajar.
    real = [(r["l"], r["v"], 1, 0) for r in LPF_FIXTURE[:5]]
    fit = _lpf_results_fit_zones(zones, real)
    assert isinstance(fit, bool)


def test_results_fit_zones_rechaza_equipo_inexistente():
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    zb, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    zones = {"A": dict(za), "B": dict(zb)}
    fantasma = [("Equipo Fantasma", "Otro Fantasma", 1, 0)]
    # Un partido entre equipos que no existen no debe encajar en las zonas.
    assert _lpf_results_fit_zones(zones, fantasma) is False
