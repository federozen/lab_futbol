"""Canonicalización de nombres de clubes de la LPF.

Traduce cualquier variante de un nombre (alias, con o sin acentos, con el paréntesis
desambiguador de Gimnasia o Estudiantes) al nombre canónico único. Es una capa de
dominio pura: sólo depende de la normalización de texto y de la tabla de alias.

Se extrajo del archivo principal sin cambiar el comportamiento; se importa de vuelta
con los mismos nombres.
"""
from __future__ import annotations

import re

from lpf_text import _zlow


LPF_CLUBES = {
 "Argentinos Juniors": ["argentinos", "argentinos jrs", "aa argentinos juniors"],
 "Aldosivi": ["aldosivi"],
 "Atlético Tucumán": ["atl tucuman", "atletico tucuman", "tucuman", "ca tucuman"],
 "Banfield": ["banfield", "ca banfield"],
 "Barracas Central": ["barracas", "barracas central"],
 "Belgrano": ["belgrano", "ca belgrano"],
 "Boca Juniors": ["boca", "boca jrs", "boca juniors", "ca boca juniors"],
 "Central Córdoba": ["central cordoba", "central cordoba sde", "ca central cordoba"],
 "Defensa y Justicia": ["defensa", "defensa y justicia"],
 "Deportivo Riestra": ["riestra", "deportivo riestra"],
 "Estudiantes de La Plata": ["estudiantes", "estudiantes lp", "estudiantes de la plata", "edlp", "estudiantes (la plata)"],
 "Estudiantes de Río Cuarto": ["estudiantes rc", "estudiantes de rio cuarto", "estudiantes (rc)", "estudiantes rio cuarto",
                              "estudiantes (río cuarto)", "estudiantes (rio cuarto)"],
 "Gimnasia La Plata": ["gimnasia", "gimnasia lp", "gimnasia y esgrima la plata", "gelp",
                      "gimnasia la plata", "gimnasia (la plata)", "gimnasia y esgrima"],
 "Gimnasia de Mendoza": ["gimnasia m", "gimnasia (m)", "gimnasia y esgrima de mendoza", "gimnasia mendoza",
                         "gimnasia mza", "gimnasia (mza)", "gimnasia (mza )", "gimnasia de mza", "gimnasia y esgrima mendoza"],
 "Godoy Cruz": ["godoy cruz", "godoy"],
 "Huracán": ["huracan", "ca huracan"],
 "Independiente": ["independiente", "ca independiente"],
 "Independiente Rivadavia": ["independiente riv", "independiente rivadavia", "ind rivadavia", "sportivo independiente rivadavia"],
 "Instituto": ["instituto", "instituto atletico central cordoba"],
 "Lanús": ["lanus", "ca lanus"],
 "Newell's Old Boys": ["newells", "newell s old boys", "newells old boys", "noob"],
 "Platense": ["platense", "ca platense"],
 "Racing": ["racing", "racing club"],
 "River Plate": ["river", "river plate", "ca river plate"],
 "Rosario Central": ["central", "rosario central", "ca rosario central"],
 "San Lorenzo": ["san lorenzo", "san lorenzo de almagro"],
 "Sarmiento": ["sarmiento", "sarmiento junin"],
 "Talleres": ["talleres", "talleres cordoba"],
 "Tigre": ["tigre", "ca tigre"],
 "Unión": ["union", "union santa fe"],
 "Vélez Sarsfield": ["velez", "velez sarsfield", "ca velez sarsfield"],
}
def _norm_club(x):
    t = _zlow(str(x or ""))
    t = t.replace("'", "").replace("\u2019", "").replace(".", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t

_LPF_LOOKUP = {}
for _c, _als in LPF_CLUBES.items():
    _LPF_LOOKUP[_norm_club(_c)] = _c
    for _a in _als:
        _LPF_LOOKUP[_norm_club(_a)] = _c

def canon_club(nombre):
    """Nombre canónico del club, venga de donde venga. Compara SIEMPRE el nombre completo primero,
    para no confundir «Gimnasia (M)» con «Gimnasia» ni «Estudiantes RC» con «Estudiantes»."""
    n = _norm_club(nombre)
    if not n:
        return nombre
    if n in _LPF_LOOKUP:
        return _LPF_LOOKUP[n]
    # variante conservando lo que hay entre paréntesis: "Gimnasia (Mza.)" -> "gimnasia mza"
    n_llano = _norm_club(re.sub(r"[()]", " ", str(nombre or "")))
    if n_llano and n_llano in _LPF_LOOKUP:
        return _LPF_LOOKUP[n_llano]
    # recién al final probamos sin el paréntesis, y solo si no era un desambiguador
    # sin el paréntesis: se permite salvo en los nombres que tienen "hermano" (Gimnasia, Estudiantes, etc.)
    _AMBIGUOS = {"gimnasia", "estudiantes", "independiente", "central", "atletico tucuman"}
    n2 = _norm_club(re.sub(r"\s*\([^)]*\)", " ", str(nombre or "")))
    if n2 and n2 not in _AMBIGUOS and n2 in _LPF_LOOKUP:
        return _LPF_LOOKUP[n2]
    cands = {c for k, c in _LPF_LOOKUP.items() if (k in n or n in k) and abs(len(k) - len(n)) <= 8}
    return cands.pop() if len(cands) == 1 else str(nombre).strip()

def canon_base(base):
    return {canon_club(e): d for e, d in (base or {}).items()}
