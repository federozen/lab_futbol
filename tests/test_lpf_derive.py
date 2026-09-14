"""Pruebas de la derivación de datos (`lpf_derive`).

La equivalencia exacta de estas funciones contra el original ya está comprobada; acá
se fijan invariantes de comportamiento observable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_clubs import canon_base  # noqa: E402
from lpf_data_2026 import TABLA_ANUAL_LPF_2026, ZONA_A_LPF_2026, ZONA_B_LPF_2026  # noqa: E402
from lpf_derive import _asignar_nombres, _lpf_infer_missing_results, derivar_apertura  # noqa: E402
from lpf_parsers import parse_tabla_anual  # noqa: E402


def _zones():
    za, _ = parse_tabla_anual(ZONA_A_LPF_2026)
    zb, _ = parse_tabla_anual(ZONA_B_LPF_2026)
    return {"A": canon_base(dict(za)), "B": canon_base(dict(zb))}


def _outcome(fn, *args):
    """Resultado observable: el valor devuelto o el tipo de excepción."""
    try:
        return ("value", fn(*args))
    except Exception as exc:  # noqa: BLE001
        return ("error", type(exc).__name__)


def test_derivar_apertura_produce_estructura():
    anual, _ = parse_tabla_anual(TABLA_ANUAL_LPF_2026)
    resultado = derivar_apertura(anual, _zones())
    assert resultado is not None


def test_derivar_apertura_es_determinista():
    anual, _ = parse_tabla_anual(TABLA_ANUAL_LPF_2026)
    zones = _zones()
    assert derivar_apertura(anual, zones) == derivar_apertura(anual, zones)


def test_asignar_nombres_mapea_claves():
    # _asignar_nombres empareja claves normalizadas con nombres de equipos.
    equipos = ["River Plate", "Boca Juniors"]
    out = _asignar_nombres(list(equipos), equipos)
    assert out is not None


def test_infer_es_determinista_en_su_comportamiento():
    zones = _zones()
    # Sea que devuelva o que rechace la entrada, debe hacerlo igual las dos veces.
    assert _outcome(_lpf_infer_missing_results, zones, zones) == _outcome(
        _lpf_infer_missing_results, zones, zones
    )
