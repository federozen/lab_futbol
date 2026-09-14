"""Pruebas de las utilidades de texto extraídas a `lpf_text`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_text import _norm_txt, _zlow, detectar_equipo  # noqa: E402


def test_zlow_quita_acentos_y_minuscula():
    assert _zlow("Ñúñez") == "nunez"
    assert _zlow("Vélez Sarsfield") == "velez sarsfield"
    assert _zlow("ABC") == "abc"
    assert _zlow("") == ""
    assert _zlow(None) == "none"  # str(None) — comportamiento preservado


def test_norm_txt_ascii():
    assert _norm_txt("Boca Júniors") == "boca juniors"
    assert _norm_txt("Gimnasia (M)") == "gimnasia (m)"
    assert _norm_txt("RIVER") == "river"


EQUIPOS = [
    "River Plate", "Boca Juniors", "Racing Club", "Independiente",
    "Vélez Sarsfield", "Estudiantes", "Estudiantes RC", "Gimnasia",
]


def test_detectar_equipo_nombre_completo():
    assert detectar_equipo("¿cómo viene River Plate?", EQUIPOS) == "River Plate"
    assert detectar_equipo("hablemos de vélez", EQUIPOS) == "Vélez Sarsfield"


def test_detectar_equipo_prefiere_nombre_mas_largo():
    # "Estudiantes RC" contiene a "Estudiantes": debe ganar el más largo.
    assert detectar_equipo("qué necesita Estudiantes RC", EQUIPOS) == "Estudiantes RC"


def test_detectar_equipo_por_palabra_distintiva():
    # "racing" (>=4 letras) alcanza aunque no esté el nombre completo.
    assert detectar_equipo("el partido de racing", EQUIPOS) == "Racing Club"


def test_detectar_equipo_sin_coincidencia():
    assert detectar_equipo("no menciono ningún equipo", EQUIPOS) is None
    assert detectar_equipo("", EQUIPOS) is None


def test_detectar_equipo_peculiaridad_palabras_genericas():
    # Comportamiento preservado del original: una palabra genérica de >=4 letras
    # que aparece en un nombre (p. ej. "club") puede disparar una coincidencia.
    # Se documenta como conocido, no como deseable.
    assert detectar_equipo("es socio del club", EQUIPOS) == "Racing Club"


def test_detectar_equipo_ignora_palabras_cortas():
    # "rc" tiene 2 letras: no debe disparar por sí sola.
    assert detectar_equipo("rc", EQUIPOS) is None
