"""Detección de intención del chat (ruteo).

Traduce una consulta en lenguaje natural a un diccionario ``{"intent": ...}`` que
la capa de UI usa para decidir qué responder. Es lógica pura: no toca Streamlit ni
estado global. La lista de equipos (``eqs``) se recibe como parámetro, de modo que
la función puede probarse de forma aislada.

Se extrajo del archivo principal sin cambiar el comportamiento (se importa de vuelta
con el mismo nombre).
"""
from __future__ import annotations

import re as _re

from lpf_text import _norm_txt, detectar_equipo, detectar_equipos


def _pos_pedida(qn):
    m = _re.search(r"\b([1-9])\s*[oº°]?\b", qn)
    if m:
        return int(m.group(1))
    for w, k in [("primer", 1), ("segundo", 2), ("tercer", 3), ("cuarto", 4), ("quinto", 5)]:
        if w in qn:
            return k
    return None


def _parse_kw(q, eqs):
    qn = _norm_txt(q)
    team = detectar_equipo(q, eqs)
    has = lambda *ws: any(w in qn for w in ws)
    nw = len(qn.split())
    if (has("por que", "porque", "porqué") and nw <= 3) or has("explicame", "explicalo", "explica eso", "fundamento", "de donde sale", "de donde sacas", "como llegaste", "como sacas eso"):
        return {"intent": "porque"}
    m = _re.search(r"top\s*(\d+)|primeros?\s*(\d+)|(\d+)\s*primeros|puesto\s*(\d+)|(\d+)\s*[oº]", qn)
    n_det = int(next(g for g in m.groups() if g)) if m else None
    mg = _re.search(r"grupo\s+([a-l])\b", qn)

    if has("ayuda", "help", "que puedo", "como funciona"):
        return {"intent": "ayuda"}
    if has("relato", "contame", "para la nota", "escribime", "escribi ", "narra", "narrá", "parrafo", "párrafo", "escenario escrito", "resumen escrito", "resumime", "redacta"):
        return {"intent": "relato", "equipo": team}
    if has("arbol", "árbol", "flowchart", "diagrama de decision", "arbol de decision", "si entonces", "diagrama si"):
        return {"intent": "arbol", "equipo": team}
    if has("previa", "previa de la fecha", "que se define en cada", "que define cada partido", "preview", "que define cada uno de los partidos", "como puede terminar la fecha", "como termina la fecha", "como le va en la fecha", "como puede quedar la fecha", "como puede terminar la jornada"):
        return {"intent": "previa", "equipo": team}
    if has("que se juega", "qué se juega", "se juega cada", "en una frase", "que necesita cada", "resumen en frases", "que esta en juego"):
        return {"intent": "juega"}
    if has("simulador", "que pasa si", "simular", "y si gana", "y si pierde", "y si empata", "que pasaria si"):
        return {"intent": "simulador"}
    if has("cruces directos", "cruce directo", "duelos directos", "duelo directo", "rivales directos", "mano a mano", "partidos entre", "seis puntos", "finales entre"):
        return {"intent": "duelos"}
    if has("zonas", "por zona", "tabla por zona", "tabla con zona", "mostrar zonas", "ver zonas"):
        return {"intent": "zonas"}
    if has("visual", "grilla", "matriz", "cuadro de escenarios", "mapa de escenarios", "tabla de escenarios", "grafic", "placa"):
        return {"intent": "visual", "equipo": team}
    if has("quien clasifica", "quienes clasifican", "quien entra", "quienes entran", "clasificados hoy", "como esta la zona"):
        return {"intent": "tabla"}
    if has("quien se salva", "quien esta en riesgo", "quienes estan en riesgo", "quien peligra", "zona de descenso", "quien se va"):
        return {"intent": "descenso", "equipo": team}
    if has("quien juega la libertadores", "quienes van a la libertadores", "quien va a la sudamericana", "cupos de copa"):
        return {"intent": "copas", "equipo": team}
    if has("cuantos puntos necesita", "cuanto le falta", "cuantos puntos le faltan", "que le falta", "puede clasificar", "esta eliminado", "sigue con chances"):
        return {"intent": "playoffs", "equipo": team}
    if has("contra quien juega", "quienes le quedan", "que rivales", "quien le queda"):
        return {"intent": "ficha", "equipo": team}
    if has("relato", "contame", "como viene la zona", "resumen de la zona", "panorama de la zona", "como esta la pelea"):
        return {"intent": "relato", "equipo": team}
    if has("estado de la fecha", "como se juega esta fecha", "ultimos resultados", "resultados en vivo",
           "que esta cargado", "quien ya jugo", "que falta jugar", "partidos de hoy", "en vivo"):
        return {"intent": "estado_fecha"}
    if has("actualizado", "al dia", "esta al dia", "datos viejos", "que fecha tengo", "que fecha va"):
        return {"intent": "actualizado"}
    if has("playoff", "play off", "play-off", "octavos", "reducido", "entrar a los ocho", "top 8", "clasificar a octavos"):
        return {"intent": "octavos" if has("octavos", "cruce", "llave", "quien juega con") else "playoffs", "equipo": team}
    if has("conviene", "le sirve", "hinchar", "para quien", "le rinde", "otra cancha", "otros resultados", "que hinchar", "me conviene", "por quien"):
        return {"intent": "conviene", "equipo": team}
    if has("chance", "probabilidad", "porcentaje", "posibilidad", "posibilidades"):
        return {"intent": "probabilidades", "equipo": team}
    if has("copas", "libertadores", "sudamericana", "internacional", "plazas", "cupos"):
        return {"intent": "copas", "equipo": team}
    if has("anual", "tabla general", "campeon de liga", "acumulada"):
        return {"intent": "anual", "equipo": team}
    if has("descenso", "descender", "se va al ascenso", "permanencia", "zona roja"):
        return {"intent": "descenso", "equipo": team}
    if has("promedios", "promedio de", "el promedio", "descenso por promedio", "desciende por promedio"):
        return {"intent": "promedios", "equipo": team}
    if has("ficha de", "ficha del", "stats de", "estadisticas de", "estadisticas del", "numeros de", "los numeros de"):
        return {"intent": "ficha", "equipo": team}
    toks = set(qn.split())
    if ("forma" in toks and "informe" not in qn) or has("ultimos 5", "ultimos cinco", "racha", "rachas", "tabla de forma"):
        return {"intent": "forma", "equipo": team}
    if has("calendario", "dificultad", "fixture dificil", "fixture mas dificil", "fixture restante", "rivales que quedan", "que rivales le quedan", "fixture que queda"):
        return {"intent": "calendario", "equipo": team}
    if has("de local", "de visitante", "localia", "local y visitante", "como local", "como visitante", "rendimiento local"):
        return {"intent": "localia", "equipo": team}
    if has("proyeccion", "proyección", "proyectado", "ritmo", "a este paso", "promedio de puntos", "puntos por partido"):
        return {"intent": "proyeccion"}
    if has("como viene", "como esta", "como llega", "chances", "que chance", "esta complicado", "esta bien parado", "esta para clasificar", "esta adentro", "esta afuera", "termometro"):
        return {"intent": "chances", "equipo": team}
    if has("bisagra", "partido clave", "partido decisivo", "partido mas importante", "que partido define", "que se define", "mas define", "partido mas decisivo"):
        return {"intent": "bisagra", "equipo": team}
    if has("barras", "en barras", "distribucion", "grafico de barras", "chances por puesto", "reparto por puesto"):
        return {"intent": "barras", "equipo": team}
    if has("mapa", "calor", "heatmap", "reparto de puesto", "como se reparten", "donde termina cada"):
        return {"intent": "mapa"}
    if has("comparar", "compara", "versus", " vs ", "vs.", "mano a mano", "frente a", "enfrenta", "contra "):
        dos = detectar_equipos(q, eqs, 2)
        if len(dos) == 2:
            return {"intent": "comparar", "equipo": dos[0], "equipo2": dos[1]}
    _posq = _pos_pedida(qn)
    if _posq and has("puede salir", "puede ser", "puede terminar", "puede quedar", "sale ", "termina", "terminar", "queda ", "salir") and not has("necesita", "conviene"):
        return {"intent": "puesto", "equipo": team, "n": _posq}
    # navegación de grupos
    if has("en que grupo", "en cual grupo", "en que zona", "en cual zona", "donde juega", "donde esta", "de que grupo", "de que zona", "grupo de", "zona de", "que grupo es", "que zona es"):
        return {"intent": "buscar_equipo", "equipo": q}
    if has("que grupos", "cuales grupos", "lista de grupos", "todos los grupos", "ver grupos") or qn.strip() == "grupos":
        return {"intent": "listar_grupos"}
    if mg and has("grupo"):
        return {"intent": "ver_grupo", "grupo": mg.group(1)}

    if has("termina hoy", "terminara hoy", "si terminara", "quedaria hoy", "como quedaria", "quien pasa hoy", "clasifica hoy", "tabla de hoy", "fase hoy"):
        return {"intent": "hoy"}
    if has("de quien depende", "depende de si", "en sus manos", "depende de el mismo", "depende de ella", "lo tiene en sus manos", "quien depende"):
        return {"intent": "depende", "equipo": team}
    if has("tabla", "posicion") and not has("conviene", "necesita"):
        return {"intent": "tabla"}
    if has("panorama", "pantallazo", "como esta el grupo", "como viene") or (has("resumen") and not team):
        return {"intent": "panorama"}
    if has("probabilidad", "chance", "porcentaje"):
        return {"intent": "probabilidades"}
    if has("maximo", "puntos posibles", "techo"):
        return {"intent": "maximos"}
    if has("asegurad", "eliminad", "quien esta adentro", "clasificado"):
        return {"intent": "asegurados", "n": n_det}
    if has("numero magico", "magico", "asegurar"):
        return {"intent": "numero_magico", "equipo": team, "objetivo": "campeon" if has("campeon", "primero") else None, "n": n_det}
    if has("conviene", "le sirve", "hinchar", "para quien", "le rinde", "otra cancha", "otros resultados", "otros partidos", "que hinchar", "por quien", "me conviene"):
        return {"intent": "conviene", "equipo": team}
    if has("exacto", "exactamente") and n_det:
        return {"intent": "puesto_exacto", "equipo": team, "n": n_det}
    if has("campeon", "salir primero", "ganar el grupo", "ganar la zona"):
        return {"intent": "necesita", "equipo": team, "objetivo": "campeon"}
    if has("champions"):
        return {"intent": "necesita", "equipo": team, "objetivo": "champions"}
    if has("descenso", "descender", "salvar", "no bajar"):
        return {"intent": "necesita", "equipo": team, "objetivo": "descenso", "n": n_det or 1}
    if has("tercero", "mejor tercero"):
        return {"intent": "necesita", "equipo": team, "objetivo": "tercero"}
    return {"intent": "necesita", "equipo": team, "objetivo": "clasificar", "n": n_det}


# ─── ROUTER CON LLM (solo interpreta; las cuentas siguen en Python) ────────────────
