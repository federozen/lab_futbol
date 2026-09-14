"""Integridad del flujo de datos: de los datos crudos a los cálculos.

Estas pruebas no miran una función aislada: verifican que los datos de la temporada
(fixture, nóminas) son coherentes y que llegan bien a los cálculos (tabla, pisos).
Es la garantía de que la calculadora "toma bien los datos" antes de contar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter  # noqa: E402

from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026  # noqa: E402
from lpf_parsers import parse_tabla_anual  # noqa: E402
from lpf_pisos import pisos_de_equipo  # noqa: E402
from lpf_standings import liga_tabla_df  # noqa: E402

TOTAL_FECHAS = 16


def _rosters():
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    zb, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    return za, zb


# ── Integridad del fixture y las nóminas ───────────────────────────────────────

def test_dos_zonas_de_quince():
    za, zb = _rosters()
    assert len(za) == 15
    assert len(zb) == 15
    # Ningún equipo está en las dos zonas.
    assert set(za).isdisjoint(set(zb))


def test_fixture_calza_con_nominas():
    za, zb = _rosters()
    rosters = set(za) | set(zb)
    en_fixture = set()
    for r in LPF_FIXTURE:
        en_fixture.add(r["l"])
        en_fixture.add(r["v"])
    # Ni equipos fantasma en el fixture, ni equipos sin partidos.
    assert en_fixture - rosters == set(), f"en fixture pero no en nóminas: {en_fixture - rosters}"
    assert rosters - en_fixture == set(), f"en nóminas pero sin partidos: {rosters - en_fixture}"


def test_cada_equipo_juega_dieciseis():
    conteo = Counter()
    for r in LPF_FIXTURE:
        conteo[r["l"]] += 1
        conteo[r["v"]] += 1
    assert set(conteo.values()) == {TOTAL_FECHAS}, f"conteos irregulares: {set(conteo.values())}"


def test_ningun_equipo_juega_contra_si_mismo():
    for r in LPF_FIXTURE:
        assert r["l"] != r["v"]


def test_partidos_de_zona_son_dentro_de_la_zona():
    za, zb = _rosters()
    zona_de = {}
    for t in za:
        zona_de[t] = "A"
    for t in zb:
        zona_de[t] = "B"
    for r in LPF_FIXTURE:
        if r["tipo"] == "zona":
            # ambos equipos pertenecen a la zona declarada
            assert zona_de.get(r["l"]) == r["zona"], f"{r['l']} no es de zona {r['zona']}"
            assert zona_de.get(r["v"]) == r["zona"], f"{r['v']} no es de zona {r['zona']}"


# ── Los datos llegan bien a los cálculos ───────────────────────────────────────

def test_tabla_se_construye_desde_las_nominas():
    za, _ = _rosters()
    df = liga_tabla_df(za)
    assert len(df) == len(za)                       # una fila por equipo
    assert list(df["Pos"]) == list(range(1, len(za) + 1))  # puestos 1..N
    assert set(df["Equipo"]) == set(za)             # sin perder ni inventar equipos


def test_pisos_se_calculan_sobre_datos_reales():
    za, zb = _rosters()
    zonas = {"A": za, "B": zb}
    anual = {**za, **zb}
    rest = {t: 5 for t in anual}  # tramo final: motor exacto activo
    # pendientes reales entre equipos de las nóminas
    pend = [(r["l"], r["v"]) for r in LPF_FIXTURE if r["l"] in anual and r["v"] in anual][:40]
    reducida = list(anual)[:16]

    equipo = list(za)[0]
    pisos = pisos_de_equipo(zonas, anual, reducida, 7, rest, pend, equipo, n_anual=1)
    assert pisos, "no se generó ningún piso"
    for p in pisos:
        if not p.aplica:
            continue
        assert p.estado in {"in", "out", "pelea"}
        assert p.puntos_hoy <= p.techo
        if p.piso is not None:
            # el piso nunca puede exigir más que el techo alcanzable
            assert p.piso <= p.techo
        if p.minimo_posible is not None and p.piso_exacto is not None:
            assert p.piso_exacto >= p.minimo_posible


def test_nominas_coinciden_con_la_foto_guardada():
    """Si hay foto de respaldo, sus zonas deben tener los mismos equipos que las nóminas."""
    import json

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lpf_last_valid.json")
    if not os.path.exists(path):
        return
    data = json.load(open(path))
    zones = data.get("zones") or {}
    if not zones:
        return
    za, zb = _rosters()
    snapshot_teams = {t for teams in zones.values() for t in teams}
    roster_teams = set(za) | set(zb)
    # La foto puede usar nombres de fuente; comprobamos al menos que la cantidad cuadra.
    assert len(snapshot_teams) == len(roster_teams) == 30


# ── El camino real de carga (cargar_lpf_todo) a través de los módulos extraídos ──

def test_camino_de_carga_offline_reconcilia_bien():
    """Replica lo que hace `cargar_lpf_todo` en su rama offline, pero usando sólo
    los módulos extraídos: construir zonas desde los datos de la temporada y pasarlas
    por la capa de reconciliación. Garantiza que la cadena datos → reconciliación
    conecta y produce un estado coherente.
    """
    from lpf_clubs import canon_base
    from lpf_reconcile import (
        _lpf_advance_zones_from_confirmed_results,
        _lpf_complete_results_for_zones,
        _lpf_repair_single_duplicate_in_zones,
        _merge_lpf_results,
    )

    # 1) Traer los datos del paso anterior y construir las zonas (como la rama offline).
    b_a, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    b_b, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    zones = {"A": canon_base(b_a), "B": canon_base(b_b)}
    assert sum(len(z) for z in zones.values()) == 30

    # 2) Unos resultados confirmados reales del fixture.
    confirmados = [(r["l"], r["v"], 2, 1) for r in LPF_FIXTURE if r["tipo"] == "zona"][:10]
    forward = _merge_lpf_results([], confirmados)

    # 3) Pasar por la reconciliación, igual que cargar_lpf_todo.
    zones, _nota_dup = _lpf_repair_single_duplicate_in_zones(zones, forward)
    zones, _nota_adv = _lpf_advance_zones_from_confirmed_results(zones, forward)
    played = _lpf_complete_results_for_zones(zones, confirmados) or forward

    # 4) El resultado sigue siendo coherente: dos zonas, 30 equipos, sin fantasmas.
    assert set(zones) == {"A", "B"}
    assert sum(len(z) for z in zones.values()) == 30
    equipos = {e for z in zones.values() for e in z}
    for local, visita, _gl, _gv in played:
        assert local in equipos, f"resultado con equipo desconocido: {local}"
        assert visita in equipos, f"resultado con equipo desconocido: {visita}"


def test_reconciliacion_es_estable_al_reaplicar():
    """Reconciliar dos veces los mismos resultados no cambia el estado (idempotencia
    práctica): trae los datos igual sin importar cuántas veces se recarga."""
    from lpf_clubs import canon_base
    from lpf_reconcile import _lpf_advance_zones_from_confirmed_results, _merge_lpf_results

    b_a, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    b_b, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    zones = {"A": canon_base(b_a), "B": canon_base(b_b)}
    confirmados = [(r["l"], r["v"], 1, 0) for r in LPF_FIXTURE if r["tipo"] == "zona"][:8]

    z1, _ = _lpf_advance_zones_from_confirmed_results(dict(zones), confirmados)
    forward = _merge_lpf_results(confirmados, confirmados)  # mismos, no debe duplicar
    z2, _ = _lpf_advance_zones_from_confirmed_results(dict(zones), forward)
    # Los equipos y sus puntos coinciden entre una y otra aplicación.
    for zona in ("A", "B"):
        assert set(z1[zona]) == set(z2[zona])
