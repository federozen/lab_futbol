"""Parsers de tablas pegadas.

Interpretan el texto que el usuario copia (lista de equipos, promedios, fixture,
Tabla Anual estilo Promiedos) y lo convierten en estructuras de datos. Son funciones
puras (texto -> datos), sin Streamlit ni estado global; dependen sólo de la
normalización de texto y de la canonicalización de clubes.

Se extrajeron del archivo principal sin cambiar el comportamiento.
"""
from __future__ import annotations

import re

from lpf_text import _fmt_num_es, _zlow
from lpf_clubs import canon_base, canon_club


def _parse_team_list(texto):
    """Lista tolerante para equipos: una línea, coma o punto medio por nombre."""
    raw = re.split(r"[\n,;·]+", str(texto or ""))
    out = []
    for item in raw:
        name = re.sub(r"^[-*•\s]+", "", item).strip()
        if name and name not in out:
            out.append(name)
    return out


def parse_promedios(texto):
    """Líneas «Equipo, pts, pj» o «Equipo, pts1, pj1, pts2, pj2» (temporadas PREVIAS; se suman).
    La temporada actual la toma sola de la tabla cargada. Devuelve {equipo: (pts_prev, pj_prev)}."""
    out = {}
    for ln in (texto or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        partes = [p.strip() for p in re.split(r"[;,\t]|\s{2,}", ln) if p.strip()]
        if len(partes) < 3:
            continue
        nombre = partes[0]
        nums = [int(p) for p in partes[1:] if re.fullmatch(r"[+-]?\d+", p)]
        if len(nums) < 2:
            continue
        nums = nums[: (len(nums) // 2) * 2]
        pts, pj = sum(nums[0::2]), sum(nums[1::2])
        if nombre and (pj > 0 or (pj == 0 and pts == 0)):
            out[nombre] = (pts, pj)
    return out


def parse_tabla_fixture(text):
    base, pend, gleft = {}, [], None
    for raw in str(text).splitlines():
        ln = raw.strip()
        if not ln:
            continue
        low = _zlow(ln)
        mf = re.search(r"(\d+)\s*(fecha|fechas|jornada|jornadas)", low)
        if mf and any(w in low for w in ("faltan", "restan", "quedan", "fecha")):
            gleft = int(mf.group(1)); continue
        if not re.search(r"\d", ln) and re.search(r"\s+(?:vs?|x|-|–|—)\s+", ln, flags=re.I):
            p = re.split(r"\s+(?:vs?|x|-|–|—)\s+", ln, flags=re.I)
            if len(p) == 2:
                pend.append((p[0].strip(), p[1].strip())); continue
        ln2 = re.sub(r"^\s*\d+[\.\)]?\s+(?=\D)", "", ln)  # saca posición inicial
        if any(sep in ln2 for sep in (",", ";", "\t")):
            f = [x.strip() for x in re.split(r"[;,\t]", ln2) if x.strip()]
            name = f[0]; nums = [x for x in f[1:] if re.match(r"^[+-]?\d+$", x)]
        else:
            mnum = re.search(r"[+-]?\d", ln2)
            if not mnum:
                continue
            name = ln2[:mnum.start()].strip()
            nums = re.findall(r"[+-]?\d+", ln2[mnum.start():])
        if not name or len(nums) < 1:
            continue
        pts = int(nums[0]); pj = int(nums[1]) if len(nums) > 1 else 0
        dg = int(nums[2]) if len(nums) > 2 else 0
        base[name] = {"pts": pts, "pj": pj, "dg": dg, "gf": max(dg, 0), "ga": max(-dg, 0)}
    return base, pend, gleft


def parse_tabla_anual(texto):
    """Lee la Tabla Anual pegada (formato Promiedos: puesto / nombre / nombre / PTS J Gol +/- G E P).
    Devuelve (base, avisos) con base = {equipo: {pts, pj, dg, gf, ga}}."""
    base, cand, avisos = {}, None, []
    for ln in (texto or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        nums = re.findall(r"-?\d+", t)
        # fila de datos: PTS J GF GC DG G E P (el "29:15" aporta dos números)
        if len(nums) >= 6 and re.match(r"^-?\d", t) and cand:
            n = [int(x) for x in nums]
            pts, pj, gf, ga, dg = n[0], n[1], n[2], n[3], n[4]
            if len(n) >= 8:
                g, e, p = n[5], n[6], n[7]
                if pj != g + e + p:
                    avisos.append(f"{cand}: G+E+P no da los partidos jugados; lo cargo igual.")
                elif pts != 3 * g + e:
                    avisos.append(f"{cand}: los puntos no coinciden con G/E; lo cargo igual.")
            base[canon_club(cand)] = {
                "pts": pts, "pj": pj, "dg": dg, "gf": gf, "ga": ga,
                "source_pos": len(base) + 1,
            }
            cand = None
        elif (not re.fullmatch(r"[\d\-:\s]+", t)
              and not _zlow(t).startswith(("tabla", "equipos", "#", "campeon", "conmebol", "descenso",
                                           "grupo", "zona", "octavos", "live", "vivo", "pts"))):
            cand = t
    if not base:
        return {}, ["No pude leer la tabla anual. Pegala tal cual sale de Promiedos."]
    return base, avisos


def parse_promedios_tabla(texto, pj_actual=None):
    """Lee una tabla de promedios y devuelve sólo las temporadas previas.

    ``pj_actual`` puede ser:
    - un entero, para fuentes sin detalle por equipo;
    - una Tabla Anual ``{equipo: {pts, pj, ...}}`` tomada en la misma foto que
      la tabla de promedios. Esta opción es la precisa y respeta partidos
      postergados, porque descuenta los PJ actuales de cada club por separado.

    Si la columna de puntos de la temporada actual no coincide con la Tabla
    Anual suministrada, la fuente queda marcada como no sincronizada. En ese
    caso el dato no debe publicarse hasta pegar fotos del mismo momento.
    """
    filas, cand, avisos = [], None, []
    rx_prom = re.compile(r"^\s*(\d+[.,]\d{2,3})\b")
    for ln in (texto or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        m = rx_prom.match(t)
        if m:
            nums = [float(x.replace(",", ".")) for x in re.findall(r"-?\d+(?:[.,]\d+)?", t)]
            if len(nums) >= 3 and cand:
                prom, pts, pj = nums[0], int(nums[1]), int(nums[2])
                temporadas = [int(x) for x in nums[3:]]
                filas.append({"eq": cand, "prom": prom, "pts": pts, "pj": pj, "temp": temporadas})
                cand = None
        elif not re.fullmatch(r"\d+", t) and not _zlow(t).startswith(("promedios", "descenso", "equipos", "#")):
            cand = t
    if not filas:
        return {}, None, ["BLOQUEO: no pude leer la tabla de promedios. Pegala completa, con Prom, Pts, PJ y temporadas."]

    annual_map = canon_base(pj_actual) if isinstance(pj_actual, dict) else {}
    scalar_pj = int(pj_actual) if isinstance(pj_actual, (int, float)) else None
    if not annual_map and scalar_pj is None:
        # Respaldo heredado: los ascendidos suelen tener sólo la temporada actual.
        solos = [f["pj"] for f in filas if f["temp"] and sum(f["temp"][:-1]) == 0]
        scalar_pj = min(solos) if solos else None
    if not annual_map and scalar_pj is None:
        avisos.append("BLOQUEO: no pude determinar los PJ de la temporada actual para separar el histórico.")
        scalar_pj = 0

    previas = {}
    mismatches = []
    for f in filas:
        team = canon_club(f["eq"])
        c_act = f["temp"][-1] if f["temp"] else 0
        if f["temp"] and sum(f["temp"]) != f["pts"]:
            avisos.append(f"{team}: las columnas por temporada no suman los puntos totales de la fuente.")
        if f["pj"] <= 0 or f["pts"] < 0 or f["pts"] > 3 * f["pj"]:
            avisos.append(f"BLOQUEO: {team} tiene un total imposible de {f['pts']} puntos en {f['pj']} PJ.")

        if annual_map and team in annual_map:
            current_pts = int(annual_map[team].get("pts", 0))
            current_pj = int(annual_map[team].get("pj", 0))
            if c_act != current_pts:
                mismatches.append(f"{team} ({c_act} en promedios / {current_pts} en Anual)")
            previous_pj = f["pj"] - current_pj
        else:
            current_pj = int(scalar_pj or 0)
            previous_pj = f["pj"] - current_pj

        previous_pts = f["pts"] - c_act
        if previous_pts < 0 or previous_pj < 0 or (previous_pj and previous_pts > 3 * previous_pj):
            avisos.append(
                f"BLOQUEO: no se puede separar el histórico de {team}: "
                f"quedan {previous_pts} puntos en {previous_pj} PJ."
            )
            continue
        # Control de la media publicada, con tolerancia por redondeo.
        source_avg = f["pts"] / f["pj"] if f["pj"] else 0.0
        if abs(source_avg - f["prom"]) > 0.006:
            avisos.append(f"{team}: el promedio publicado ({_fmt_num_es(f['prom'], 3)}) no coincide con Pts/PJ ({_fmt_num_es(source_avg, 3)}).")
        previas[team] = (previous_pts, previous_pj)

    if mismatches:
        avisos.insert(0,
            "BLOQUEO: la tabla de Promedios y la Tabla Anual no son de la misma actualización. "
            "Difieren, entre otros: " + ", ".join(mismatches[:5]) + "."
        )
    return previas, (annual_map if annual_map else scalar_pj), avisos
