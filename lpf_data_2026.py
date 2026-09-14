"""Datos fijos de la LPF 2026 y parser del fixture.

Fuente autoritativa de la temporada: el fixture completo del Clausura, las nóminas
de cada zona y la foto fija del Apertura, más el parser que convierte el fixture en
una lista de partidos. Se centraliza acá para que haya una sola copia y para romper
el acoplamiento con el archivo principal. Módulo puro: sólo depende de la
canonicalización de clubes.
"""
from __future__ import annotations

import re

from lpf_clubs import canon_club

_SEP = re.compile(r"\s+[–—-]\s+")


LPF_FIXTURE_2026 = """
Fecha 1
Interzonal: Defensa y Justicia – Aldosivi
Zona A
Deportivo Riestra – Boca
Estudiantes – Independiente
Newell's – Talleres
Vélez – Instituto
Platense – Unión
Lanús – San Lorenzo
Gimnasia (Mza.) – Central Córdoba
Zona B
River – Barracas Central
Racing – Gimnasia
Belgrano – Rosario Central
Estudiantes (Río Cuarto) – Tigre
Sarmiento – Argentinos
Huracán – Banfield
Atlético Tucumán – Independiente Rivadavia Mza.

Fecha 2
Interzonal: Central Córdoba – Atlético Tucumán
Zona A
San Lorenzo – Gimnasia (Mza.)
Unión – Lanús
Instituto – Platense
Talleres – Vélez
Independiente – Newell's
Boca – Estudiantes
Defensa y Justicia – Deportivo Riestra
Zona B
Independiente Rivadavia Mza. – Huracán
Banfield – Sarmiento
Argentinos – Estudiantes (Río Cuarto)
Tigre – Belgrano
Rosario Central – Racing
Gimnasia – River
Barracas Central – Aldosivi

Fecha 3
Interzonal: Deportivo Riestra – Barracas Central
Zona A
Estudiantes – Defensa y Justicia
Newell's – Boca
Vélez – Independiente
Platense – Talleres
Lanús – Instituto
Gimnasia (Mza.) – Unión
Central Córdoba – San Lorenzo
Zona B
Aldosivi – Gimnasia
River – Rosario Central
Racing – Tigre
Belgrano – Argentinos
Estudiantes (Río Cuarto) – Banfield
Sarmiento – Independiente Rivadavia Mza.
Huracán – Atlético Tucumán

Fecha 4
Interzonal: San Lorenzo – Huracán
Zona A
Unión – Central Córdoba
Instituto – Gimnasia (Mza.)
Talleres – Lanús
Independiente – Platense
Boca – Vélez
Defensa y Justicia – Newell's
Deportivo Riestra – Estudiantes
Zona B
Atlético Tucumán – Sarmiento
Independiente Rivadavia (Mza.) – Estudiantes (Río Cuarto)
Banfield – Belgrano
Argentinos – Racing
Tigre – River
Rosario Central – Aldosivi
Gimnasia – Barracas Central

Fecha 5
Interzonal: Estudiantes – Gimnasia
Zona A
Newell's – Deportivo Riestra
Vélez – Defensa y Justicia
Platense – Boca
Lanús – Independiente
Gimnasia (Mza.) – Talleres
Central Córdoba – Instituto
San Lorenzo – Unión
Zona B
Barracas Central – Rosario Central
Aldosivi – Tigre
River – Argentinos
Racing – Banfield
Belgrano – Independiente Rivadavia Mza.
Estudiantes (Río Cuarto) – Atlético Tucumán
Sarmiento – Huracán

Fecha 6 (fecha interzonal completa)
River – Vélez
Barracas Central – Platense
Talleres – Rosario Central
Sarmiento – Estudiantes
Belgrano – Defensa y Justicia
Lanús – Argentinos
Racing – Boca
Independiente – Independiente Rivadavia Mza.
Aldosivi – Unión
Atlético Tucumán – Instituto
Estudiantes (Río Cuarto) – San Lorenzo
Gimnasia – Gimnasia (Mza.)
Tigre – Central Córdoba
Huracán – Deportivo Riestra
Newell's – Banfield

Fecha 7
Interzonal: Unión – Sarmiento
Zona A
Instituto – San Lorenzo
Talleres – Central Córdoba
Independiente – Gimnasia (Mza.)
Boca – Lanús
Defensa y Justicia – Platense
Deportivo Riestra – Vélez
Estudiantes – Newell's
Zona B
Huracán – Estudiantes (Río Cuarto)
Atlético Tucumán – Belgrano
Independiente Rivadavia Mza. – Racing
Banfield – River
Argentinos – Aldosivi
Tigre – Barracas Central
Rosario Central – Gimnasia

Fecha 8
Interzonal: Rosario Central – Newell's
Zona A
Vélez – Estudiantes
Platense – Deportivo Riestra
Lanús – Defensa y Justicia
Gimnasia (Mza.) – Boca
Central Córdoba – Independiente
San Lorenzo – Talleres
Unión – Instituto
Zona B
Gimnasia – Tigre
Barracas Central – Argentinos
Aldosivi – Banfield
River – Independiente Rivadavia Mza.
Racing – Atlético Tucumán
Belgrano – Huracán
Estudiantes (Río Cuarto) – Sarmiento

Fecha 9
Interzonal: Instituto – Estudiantes (Río Cuarto)
Zona A
Talleres – Unión
Independiente – San Lorenzo
Boca – Central Córdoba
Defensa y Justicia – Gimnasia (Mza.)
Deportivo Riestra – Lanús
Estudiantes – Platense
Newell's – Vélez
Zona B
Sarmiento – Belgrano
Huracán – Racing
Atlético Tucumán – River
Independiente Rivadavia Mza. – Aldosivi
Banfield – Barracas Central
Argentinos – Gimnasia
Tigre – Rosario Central

Fecha 10
Interzonal: Vélez – Tigre
Zona A
Platense – Newell's
Lanús – Estudiantes
Gimnasia (Mza.) – Deportivo Riestra
Central Córdoba – Defensa y Justicia
San Lorenzo – Boca
Unión – Independiente
Instituto – Talleres
Zona B
Rosario Central – Argentinos
Gimnasia – Banfield
Barracas Central – Independiente Rivadavia Mza.
Aldosivi – Atlético Tucumán
River – Huracán
Racing – Sarmiento
Belgrano – Estudiantes (Río Cuarto)

Fecha 11
Interzonal: Talleres – Belgrano
Zona A
Independiente – Instituto
Boca – Unión
Defensa y Justicia – San Lorenzo
Deportivo Riestra – Central Córdoba
Estudiantes – Gimnasia (Mza.)
Newell's – Lanús
Vélez – Platense
Zona B
Estudiantes (Río Cuarto) – Racing
Sarmiento – River
Huracán – Aldosivi
Atlético Tucumán – Barracas Central
Independiente Rivadavia Mza. – Gimnasia
Banfield – Rosario Central
Argentinos – Tigre

Fecha 12
Interzonal: Platense – Argentinos
Zona A
Lanús – Vélez
Gimnasia (Mza.) – Newell's
Central Córdoba – Estudiantes
San Lorenzo – Deportivo Riestra
Unión – Defensa y Justicia
Instituto – Boca
Talleres – Independiente
Zona B
Tigre – Banfield
Rosario Central – Independiente Rivadavia Mza.
Gimnasia – Atlético Tucumán
Barracas Central – Huracán
Aldosivi – Sarmiento
River – Estudiantes (Río Cuarto)
Racing – Belgrano

Fecha 13
Interzonal: Racing – Independiente
Zona A
Boca – Talleres
Defensa y Justicia – Instituto
Deportivo Riestra – Unión
Estudiantes – San Lorenzo
Newell's – Central Córdoba
Vélez – Gimnasia (Mza.)
Platense – Lanús
Zona B
Belgrano – River
Estudiantes (Río Cuarto) – Aldosivi
Sarmiento – Barracas Central
Huracán – Gimnasia
Atlético Tucumán – Rosario Central
Independiente Rivadavia Mza. – Tigre
Banfield – Argentinos

Fecha 14
Interzonal: Banfield – Lanús
Zona A
Gimnasia (Mza.) – Platense
Central Córdoba – Vélez
San Lorenzo – Newell's
Unión – Estudiantes
Instituto – Deportivo Riestra
Talleres – Defensa y Justicia
Independiente – Boca
Zona B
Argentinos – Independiente Rivadavia Mza.
Tigre – Atlético Tucumán
Rosario Central – Huracán
Gimnasia – Sarmiento
Barracas Central – Estudiantes (Río Cuarto)
Aldosivi – Belgrano
River – Racing

Fecha 15
Interzonal: Boca – River
Zona A
Defensa y Justicia – Independiente
Deportivo Riestra – Talleres
Estudiantes – Instituto
Newell's – Unión
Vélez – San Lorenzo
Platense – Central Córdoba
Lanús – Gimnasia (Mza.)
Zona B
Racing – Aldosivi
Belgrano – Barracas Central
Estudiantes de Río Cuarto – Gimnasia
Sarmiento – Rosario Central
Huracán – Tigre
Atlético Tucumán – Argentinos Juniors
Independiente Rivadavia Mza. – Banfield

Fecha 16
Interzonal: Gimnasia (Mza.) – Independiente Rivadavia Mza.
Zona A
Central Córdoba – Lanús
San Lorenzo – Platense
Unión – Vélez
Instituto – Newell's
Talleres – Estudiantes
Independiente – Deportivo Riestra
Boca – Defensa y Justicia
Zona B
Banfield – Atlético Tucumán
Argentinos – Huracán
Tigre – Sarmiento
Rosario Central – Estudiantes (Río Cuarto)
Gimnasia – Belgrano
Barracas Central – Racing
Aldosivi – River
"""


ZONA_A_LPF_2026 = """1
Gimnasia (M)
4	2	1:0	1	1	1	0
2
Riestra
3	1	3:0	3	1	0	0
3
Independiente
3	1	2:0	2	1	0	0
4
Newell's
3	1	1:0	1	1	0	0
5
Vélez
3	1	1:0	1	1	0	0
6
Lanús
3	1	1:0	1	1	0	0
7
Unión
1	1	2:2	0	0	1	0
8
Platense
1	1	2:2	0	0	1	0
9
Defensa
1	1	1:1	0	0	1	0
10
San Lorenzo
1	2	0:1	-1	0	1	1
11
Central Córdoba
0	1	0:1	-1	0	0	1
12
Instituto
0	1	0:1	-1	0	0	1
13
Talleres
0	1	0:1	-1	0	0	1
14
Estudiantes
0	1	0:2	-2	0	0	1
15
Boca Jrs.
0	1	0:3	-3	0	0	1"""


ZONA_B_LPF_2026 = """1
Argentinos
3	1	3:2	1	1	0	0
2
Belgrano
3	1	2:1	1	1	0	0
3
Racing
3	1	2:1	1	1	0	0
4
Huracán
3	1	1:0	1	1	0	0
5
Estudiantes RC
3	1	1:0	1	1	0	0
6
Barracas
3	1	1:0	1	1	0	0
7
Aldosivi
1	1	1:1	0	0	1	0
8
Atl. Tucumán
1	1	0:0	0	0	1	0
9
Independiente Riv.
1	1	0:0	0	0	1	0
10
Sarmiento
1	2	2:3	-1	0	1	1
11
Banfield
1	2	0:1	-1	0	1	1
12
Central
0	1	1:2	-1	0	0	1
13
Gimnasia
0	1	1:2	-1	0	0	1
14
River
0	1	0:1	-1	0	0	1
15
Tigre
0	1	0:1	-1	0	0	1"""


TABLA_ANUAL_LPF_2026 = """1
Independiente Riv.
35\t17\t29:15\t14\t10\t5\t2
2
Argentinos
32\t17\t20:15\t5\t9\t5\t3
3
Estudiantes
31\t17\t19:9\t10\t9\t4\t4
4
Vélez
31\t17\t19:12\t7\t8\t7\t2
5
Boca Jrs.
30\t17\t22:12\t10\t8\t6\t3
6
River
29\t17\t22:13\t9\t9\t2\t6
7
Belgrano
29\t17\t19:14\t5\t8\t5\t4
8
Central
28\t17\t21:18\t3\t8\t4\t5
9
Independiente
27\t17\t26:20\t6\t7\t6\t4
10
Lanús
27\t17\t19:15\t4\t7\t6\t4
11
Talleres
26\t17\t17:14\t3\t7\t5\t5
12
Gimnasia
26\t17\t20:21\t-1\t8\t2\t7
13
Huracán
25\t17\t18:13\t5\t6\t7\t4
14
Racing
24\t17\t19:16\t3\t6\t6\t5
15
Barracas
24\t17\t16:15\t1\t6\t6\t5
16
Unión
22\t17\t26:22\t4\t5\t7\t5
17
San Lorenzo
22\t17\t14:15\t-1\t5\t7\t5
18
Gimnasia (M)
22\t17\t15:22\t-7\t6\t4\t7
19
Instituto
21\t17\t17:18\t-1\t6\t3\t8
20
Tigre
20\t17\t18:16\t2\t4\t8\t5
21
Defensa
20\t17\t19:22\t-3\t4\t8\t5
22
Sarmiento
19\t17\t15:23\t-8\t6\t1\t10
23
Banfield
18\t17\t17:20\t-3\t5\t3\t9
24
Newell's
18\t17\t16:27\t-11\t4\t6\t7
25
Platense
17\t17\t12:17\t-5\t3\t8\t6
26
Central Córdoba
16\t17\t11:22\t-11\t4\t4\t9
27
Atl. Tucumán
15\t17\t15:20\t-5\t3\t6\t8
28
Riestra
14\t17\t8:12\t-4\t2\t8\t7
29
Aldosivi
9\t17\t7:20\t-13\t0\t9\t8
30
Estudiantes RC
8\t17\t6:24\t-18\t2\t2\t13"""


def parse_fixture_lpf(text=None, canon=None):
    if text is None: text = LPF_FIXTURE_2026
    if canon is None: canon = canon_club
    """Devuelve lista de dicts: {'f':fecha, 'tipo':'zona'|'inter', 'zona':'A'/'B'/None, 'l':local, 'v':visita}.
    Canoniza ambos nombres con canon_club para que peguen con las zonas cargadas."""
    import re
    juegos, f, tipo, zona = [], 0, None, None
    for raw in str(text).splitlines():
        ln = raw.strip()
        if not ln:
            continue
        mf = re.match(r"(?i)^fecha\s+(\d+)", ln)
        if mf:
            f = int(mf.group(1)); zona = None
            tipo = "inter" if "interzonal" in ln.lower() else None
            continue
        low = ln.lower()
        if low.startswith("zona a"):
            zona, tipo = "A", "zona"; continue
        if low.startswith("zona b"):
            zona, tipo = "B", "zona"; continue
        if low.startswith("interzonal"):
            resto = ln.split(":", 1)[1] if ":" in ln else ""
            partes = _SEP.split(resto.strip())
            if len(partes) == 2:
                juegos.append({"f": f, "tipo": "inter", "zona": None,
                               "l": canon(partes[0]), "v": canon(partes[1])})
            continue
        partes = _SEP.split(ln)
        if len(partes) == 2:
            juegos.append({"f": f, "tipo": tipo or "inter", "zona": zona,
                           "l": canon(partes[0]), "v": canon(partes[1])})
    return juegos


LPF_FIXTURE = parse_fixture_lpf()
