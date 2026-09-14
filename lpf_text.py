"""Utilidades de texto y detección de entidades.

Funciones puras (sólo dependen de sus argumentos) que antes vivían dentro del
archivo principal. Se extrajeron para poder probarlas de forma aislada y para ir
reduciendo el monolito sin cambiar el comportamiento: se importan de vuelta con
el mismo nombre, así que todos los usos siguen funcionando igual.
"""
from __future__ import annotations

import re
import unicodedata


def _zlow(s) -> str:
    """Minúsculas sin acentos (para comparar nombres de forma robusta)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn"
    ).lower()


def _norm_txt(s) -> str:
    """Normaliza a ASCII en minúsculas, descartando acentos y signos."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def detectar_equipo(q, equipos):
    """Devuelve el equipo mencionado en el texto ``q``, o ``None``.

    Prioriza la coincidencia del nombre completo; si no la hay, acepta una palabra
    distintiva de cuatro o más letras. Comparación sin acentos ni mayúsculas.
    """
    qn = _norm_txt(q)
    pares = [(e, _norm_txt(e)) for e in equipos]
    full = [e for e, en in pares if en in qn]
    if full:
        return max(full, key=len)
    for e, en in pares:
        for w in en.split():
            if len(w) >= 4 and w in qn:
                return e
    return None


def detectar_equipos(q, equipos, k=2):
    qn = _norm_txt(q); found = []
    for e in sorted(equipos, key=lambda x: -len(x)):
        if _norm_txt(e) in qn and e not in found:
            found.append(e)
        if len(found) >= k:
            break
    return found


def _fmt_num_es(value, decimals=1):
    if value is None:
        return "—"
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{decimals}f}".replace(".", ",")


# `re` se re-exporta por compatibilidad con módulos que lo esperaban acá.
__all__ = ["_zlow", "_norm_txt", "detectar_equipo", "detectar_equipos", "_fmt_num_es", "re"]
