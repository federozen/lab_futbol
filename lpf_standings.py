"""Motor puro de tablas y posiciones.

Este módulo transforma equipos y partidos ya normalizados en estadísticas, orden,
posiciones y tablas. No depende de Streamlit, de red ni de una fuente de datos
concreta: los criterios de desempate entran como parámetro.

Ese límite permite reutilizar exactamente el mismo cálculo desde la interfaz actual,
una futura API o un adaptador de proveedor (por ejemplo Opta) sin duplicar lógica.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


import pandas as pd


DEFAULT_CRITERIOS = ("dg", "gf", "h2h_pts", "h2h_dg", "h2h_gf", "fair_play")


def _stats(equipos, partidos):
    st_d = {e: {"pts": 0, "gf": 0, "ga": 0, "pj": 0} for e in equipos}
    for l, v, gl, gv in partidos:
        st_d[l]["gf"] += gl; st_d[l]["ga"] += gv; st_d[l]["pj"] += 1
        st_d[v]["gf"] += gv; st_d[v]["ga"] += gl; st_d[v]["pj"] += 1
        if gl > gv: st_d[l]["pts"] += 3
        elif gl < gv: st_d[v]["pts"] += 3
        else: st_d[l]["pts"] += 1; st_d[v]["pts"] += 1
    for e in st_d: st_d[e]["dg"] = st_d[e]["gf"] - st_d[e]["ga"]
    return st_d


def _stats_entre(teams, partidos):
    ts = set(teams)
    st_d = {e: {"pts": 0, "gf": 0, "ga": 0} for e in teams}
    for l, v, gl, gv in partidos:
        if l in ts and v in ts:
            st_d[l]["gf"] += gl; st_d[l]["ga"] += gv
            st_d[v]["gf"] += gv; st_d[v]["ga"] += gl
            if gl > gv: st_d[l]["pts"] += 3
            elif gl < gv: st_d[v]["pts"] += 3
            else: st_d[l]["pts"] += 1; st_d[v]["pts"] += 1
    for e in st_d: st_d[e]["dg"] = st_d[e]["gf"] - st_d[e]["ga"]
    return st_d


def _criterios(criterios):
    """Devuelve una copia inmutable sin confundir ``[]`` con el valor por defecto."""
    return DEFAULT_CRITERIOS if criterios is None else tuple(criterios)


def _resolver(teams, partidos, overall, fair_play=None, ranking=None, criterios=None):
    criterios = _criterios(criterios)
    if len(teams) <= 1: return list(teams)
    h = _stats_entre(teams, partidos) if any(c.startswith("h2h") for c in criterios) else None

    def val(c):
        if c == "h2h_pts": return {e: h[e]["pts"] for e in teams}
        if c == "h2h_dg":  return {e: h[e]["dg"]  for e in teams}
        if c == "h2h_gf":  return {e: h[e]["gf"]  for e in teams}
        if c == "dg":      return {e: overall[e]["dg"] for e in teams}
        if c == "gf":      return {e: overall[e]["gf"] for e in teams}
        if c == "fair_play" and fair_play is not None: return {e: fair_play.get(e, 0) for e in teams}
        if c == "ranking"   and ranking   is not None: return {e: -ranking.get(e, 9999) for e in teams}
        return None

    for c in criterios:
        vals = val(c)
        if vals is None: continue
        if len(set(vals.values())) > 1:
            out = []
            for v in sorted(set(vals.values()), reverse=True):
                out += _resolver(
                    [e for e in teams if vals[e] == v], partidos, overall,
                    fair_play=fair_play, ranking=ranking, criterios=criterios,
                )
            return out
    return sorted(teams)


def _orden(equipos, partidos, fair_play=None, ranking=None, criterios=None):
    overall = _stats(equipos, partidos); porpts = {}
    for e in equipos: porpts.setdefault(overall[e]["pts"], []).append(e)
    orden = []
    for pts in sorted(porpts, reverse=True):
        orden += _resolver(
            porpts[pts], partidos, overall,
            fair_play=fair_play, ranking=ranking, criterios=criterios,
        )
    return orden, overall


def posiciones(equipos, partidos, fair_play=None, ranking=None, criterios=None):
    orden, _ = _orden(
        equipos, partidos, fair_play=fair_play, ranking=ranking, criterios=criterios,
    )
    return {e: i for i, e in enumerate(orden, 1)}


def tabla(equipos, partidos, fair_play=None, ranking=None, criterios=None):
    orden, ov = _orden(
        equipos, partidos, fair_play=fair_play, ranking=ranking, criterios=criterios,
    )
    return pd.DataFrame([{"Pos": i, "Equipo": e, "PJ": ov[e]["pj"], "PTS": ov[e]["pts"],
                          "GF": ov[e]["gf"], "GC": ov[e]["ga"], "DG": ov[e]["dg"]}
                         for i, e in enumerate(orden, 1)])


def liga_tabla_df(base):
    """Ordena la foto actual respetando el puesto publicado como último desempate.

    PTS, DG y GF siguen siendo los criterios visibles. Cuando dos equipos también
    coinciden allí, no se inventa un orden alfabético ni se hereda el orden de una
    base histórica: se conserva ``source_pos`` si la fuente lo informó.
    """
    source_order = {team: index for index, team in enumerate(base or {})}
    rows = sorted(
        (base or {}).items(),
        key=lambda kv: (
            -int(kv[1].get("pts", 0)),
            -int(kv[1].get("dg", 0)),
            -int(kv[1].get("gf", 0)),
            int(kv[1].get("source_pos", 10_000 + source_order[kv[0]])),
            source_order[kv[0]],
        ),
    )
    return pd.DataFrame([{"Pos": i, "Equipo": e, "PJ": d.get("pj", 0), "PTS": d["pts"], "DG": d.get("dg", 0)}
                         for i, (e, d) in enumerate(rows, 1)])


def _liga_in_out(equipo, base, rest, k):
    pts = {e: base[e]["pts"] for e in base}; pmax = {e: pts[e] + 3 * rest.get(e, 0) for e in base}
    arriba = sum(1 for x in base if x != equipo and pmax[x] >= pts[equipo])
    inalc = sum(1 for x in base if x != equipo and pts[x] > pmax[equipo])
    if arriba < k: return "in"
    if inalc >= k: return "out"
    return "pelea"
