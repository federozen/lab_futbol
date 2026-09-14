"""Pruebas del ruteo de intención extraído a `lpf_intents`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_intents import _parse_kw, _pos_pedida  # noqa: E402

EQUIPOS = [
    "River Plate", "Boca Juniors", "Racing Club", "Independiente",
    "Vélez Sarsfield", "Estudiantes", "Estudiantes RC", "Gimnasia",
    "San Lorenzo", "Talleres",
]


def intent(q):
    return _parse_kw(q, EQUIPOS)["intent"]


def test_intents_basicos():
    assert intent("por qué?") == "porque"
    assert intent("explicame de dónde sale eso") == "porque"
    assert intent("ayuda") == "ayuda"
    assert intent("cómo funciona esto") == "ayuda"
    assert intent("hacé un árbol de decisión") == "arbol"
    assert intent("previa de la fecha") == "previa"
    assert intent("qué se juega cada partido") == "juega"
    assert intent("mostrame las zonas") == "zonas"


def test_intent_lleva_equipo():
    r = _parse_kw("contame un relato para la nota sobre River Plate", EQUIPOS)
    assert r["intent"] == "relato"
    assert r["equipo"] == "River Plate"


def test_necesita_con_objetivo_por_defecto():
    r = _parse_kw("qué necesita Vélez Sarsfield", EQUIPOS)
    assert r["intent"] == "necesita"
    assert r["equipo"] == "Vélez Sarsfield"
    assert r["objetivo"] == "clasificar"


def test_siempre_devuelve_intent():
    # Cualquier consulta produce un dict con 'intent' (nunca None ni excepción).
    for q in ["", "hola", "no menciono nada", "xyz 123", "?!"]:
        r = _parse_kw(q, EQUIPOS)
        assert isinstance(r, dict) and "intent" in r


def test_determinista():
    q = "qué necesita Estudiantes RC para la Libertadores"
    assert _parse_kw(q, EQUIPOS) == _parse_kw(q, EQUIPOS)


def test_pos_pedida():
    assert _pos_pedida("3") == 3
    assert _pos_pedida("el primer puesto") == 1
    assert _pos_pedida("segundo") == 2
    assert _pos_pedida("nada de números") is None
