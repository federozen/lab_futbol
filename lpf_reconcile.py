"""Reconciliación e integridad de datos de la LPF.

Capa que se sitúa entre las fuentes (scraping, tablas pegadas, foto de respaldo) y
los cálculos. Ajusta los resultados a las zonas, repara duplicados, hace avanzar las
zonas a partir de resultados confirmados, completa resultados faltantes y valida que
las tablas sean coherentes. Es lógica pura (datos -> datos): no toca Streamlit ni la
red. Depende de la canonicalización de clubes, de los datos fijos de la temporada y
del conteo esperado de partidos.

El objetivo de esta capa es que la calculadora "tome bien los datos" antes de contar.
"""
from __future__ import annotations

from itertools import combinations

from lpf_clubs import canon_base, canon_club
from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026
from lpf_fixture_sources import expected_played_count
from lpf_parsers import parse_tabla_anual


def _known_lpf_zone_rosters():
    known = {"A": set(), "B": set()}
    try:
        for label, raw in (("A", ZONA_A_LPF_2026), ("B", ZONA_B_LPF_2026)):
            parsed = parse_tabla_anual(raw)[0]
            known[label] = {canon_club(name) for name in parsed}
    except Exception:
        pass
    return known


def _validate_base_rows(base, *, expected_size, label, max_pj):
    if len(base or {}) != int(expected_size):
        raise RuntimeError(
            f"{label}: esperaba {expected_size} equipos y encontré {len(base or {})}"
        )
    for team, stats in (base or {}).items():
        pts = int(stats.get("pts", -1))
        pj = int(stats.get("pj", -1))
        gf = int(stats.get("gf", 0))
        ga = int(stats.get("ga", 0))
        dg = int(stats.get("dg", gf - ga))
        if pj < 0 or pj > int(max_pj):
            raise RuntimeError(f"{label}: PJ inválidos para {team}: {pj}")
        if pts < 0 or pts > 3 * pj:
            raise RuntimeError(f"{label}: puntaje imposible para {team}: {pts} en {pj} PJ")
        if gf < 0 or ga < 0:
            raise RuntimeError(f"{label}: goles negativos para {team}")
        if dg != gf - ga:
            # Algunos proveedores publican la DG como texto independiente. Se corrige,
            # pero no se rechaza toda la tabla por esa diferencia.
            stats["dg"] = gf - ga


def _validate_lpf_tables(zones, annual=None):
    if set((zones or {}).keys()) != {"A", "B"}:
        raise RuntimeError("no pude identificar las zonas A y B")
    _validate_base_rows(zones["A"], expected_size=15, label="Zona A", max_pj=16)
    _validate_base_rows(zones["B"], expected_size=15, label="Zona B", max_pj=16)

    known = _known_lpf_zone_rosters()
    expected = known["A"] | known["B"]
    actual_a, actual_b = set(zones["A"]), set(zones["B"])
    actual = actual_a | actual_b
    if actual_a & actual_b:
        raise RuntimeError("hay equipos repetidos entre las zonas")
    if expected and actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("faltan " + ", ".join(missing))
        if extra:
            detail.append("sobran " + ", ".join(extra))
        raise RuntimeError("los clubes no coinciden con el Clausura 2026: " + "; ".join(detail))

    if annual is not None:
        _validate_base_rows(annual, expected_size=30, label="Tabla anual", max_pj=32)
        if set(annual) != actual:
            missing = sorted(actual - set(annual))
            extra = sorted(set(annual) - actual)
            detail = []
            if missing:
                detail.append("faltan " + ", ".join(missing))
            if extra:
                detail.append("sobran " + ", ".join(extra))
            raise RuntimeError("la Tabla Anual no coincide con las zonas: " + "; ".join(detail))
        for team in actual:
            zone_stats = zones["A"].get(team) or zones["B"].get(team) or {}
            annual_stats = annual.get(team) or {}
            if int(annual_stats.get("pj", 0)) < int(zone_stats.get("pj", 0)):
                raise RuntimeError(f"la Anual tiene menos PJ que el Clausura para {team}")
            if int(annual_stats.get("pts", 0)) < int(zone_stats.get("pts", 0)):
                raise RuntimeError(f"la Anual tiene menos puntos que el Clausura para {team}")
    return True


def _lpf_normalize_result_identity(local, visitor, gl, gv):
    """Normaliza un marcador contra la identidad oficial del partido.

    Algunas fuentes pueden publicar la misma ficha con local/visitante invertidos
    o con alias distintos. En el Clausura 2026 cada pareja aparece una sola vez en
    el fixture, por lo que la orientación oficial permite reconocer el mismo partido
    antes de sumar PJ, puntos o goles.
    """
    cl, cv = canon_club(local), canon_club(visitor)
    gl, gv = int(gl), int(gv)
    try:
        fixture_pairs = {
            (canon_club(row.get("l") or row.get("home") or ""),
             canon_club(row.get("v") or row.get("away") or ""))
            for row in LPF_FIXTURE
        }
    except Exception:
        fixture_pairs = set()
    direct = (cl, cv) in fixture_pairs
    reverse = (cv, cl) in fixture_pairs
    if reverse and not direct:
        return cv, cl, gv, gl
    return cl, cv, gl, gv


def _merge_lpf_results(*collections):
    """Une resultados por identidad oficial sin perder la última foto válida.

    Un marcador explícito más nuevo puede reemplazar a uno anterior para el mismo
    partido. También colapsa la misma ficha si una fuente la entrega con los clubes
    invertidos, evitando que un resultado se contabilice dos veces.
    """
    merged = {}
    for collection in collections:
        for local, visitor, gl, gv in collection or []:
            cl, cv, gl, gv = _lpf_normalize_result_identity(local, visitor, gl, gv)
            merged[(cl, cv)] = (cl, cv, int(gl), int(gv))
    return list(merged.values())


def _lpf_result_stats(played):
    """Reconstruye PJ, puntos y goles sin contar dos veces la misma ficha."""
    stats = {}
    for local, visitor, gl, gv in _merge_lpf_results(played):
        local, visitor = canon_club(local), canon_club(visitor)
        gl, gv = int(gl), int(gv)
        for team in (local, visitor):
            stats.setdefault(team, {"pj": 0, "pts": 0, "gf": 0, "ga": 0, "dg": 0})
        stats[local]["pj"] += 1
        stats[visitor]["pj"] += 1
        stats[local]["gf"] += gl
        stats[local]["ga"] += gv
        stats[visitor]["gf"] += gv
        stats[visitor]["ga"] += gl
        if gl > gv:
            stats[local]["pts"] += 3
        elif gv > gl:
            stats[visitor]["pts"] += 3
        else:
            stats[local]["pts"] += 1
            stats[visitor]["pts"] += 1
    for row in stats.values():
        row["dg"] = row["gf"] - row["ga"]
    return stats


def _lpf_results_mismatches(zones, played, limit=None):
    """Detalla qué clubes no cierran entre marcadores y tabla publicada.

    Devuelve filas cortas para auditoría; una lista vacía significa coincidencia
    exacta en PJ, puntos, GF, GC y DG.
    """
    teams = {team for base in (zones or {}).values() for team in base}
    mismatches = []
    outsiders = sorted({
        team
        for local, visitor, _gl, _gv in played or []
        for team in (canon_club(local), canon_club(visitor))
        if team not in teams
    })
    if outsiders:
        mismatches.append("clubes ajenos a las zonas: " + ", ".join(outsiders[:5]))

    actual = _lpf_result_stats(played)
    labels = {"pj": "PJ", "pts": "pts", "gf": "GF", "ga": "GC", "dg": "DG"}
    for label in (zones or {}):
        for team, expected in zones[label].items():
            row = actual.get(team, {})
            diffs = []
            for key in ("pj", "pts", "gf", "ga", "dg"):
                if key not in (expected or {}):
                    continue
                wanted = int((expected or {}).get(key, 0))
                got = int(row.get(key, 0))
                if wanted != got:
                    diffs.append(f"{labels[key]} {got}/{wanted}")
            if diffs:
                mismatches.append(f"{team}: " + ", ".join(diffs))
            if limit and len(mismatches) >= int(limit):
                return mismatches
    return mismatches


def lpf_results_mismatches(zones, played, limit=None):
    """API pública de auditoría para proveedores externos al Streamlit heredado."""
    return _lpf_results_mismatches(zones, played, limit=limit)


def _lpf_results_fit_zones(zones, played):
    """Comprueba que los resultados reconstruyen exactamente las dos zonas."""
    return not _lpf_results_mismatches(zones, played)


def _lpf_reorder_source_positions(base):
    """Recalcula la posición publicada tras avanzar una tabla por resultados.

    Los criterios visibles (PTS, DG y GF) mandan. Si dos clubes siguen exactamente
    empatados se conserva como último desempate el orden de la fuente previa, en vez
    de inventar uno alfabético.
    """
    base = canon_base(base or {})
    original_order = {team: idx for idx, team in enumerate(base)}
    ranked = sorted(
        base,
        key=lambda team: (
            -int(base[team].get("pts", 0)),
            -int(base[team].get("dg", 0)),
            -int(base[team].get("gf", 0)),
            int(base[team].get("source_pos", 10_000 + original_order[team])),
            original_order[team],
        ),
    )
    out = {}
    for pos, team in enumerate(ranked, 1):
        row = dict(base[team])
        row["source_pos"] = pos
        out[team] = row
    return out


def _lpf_complete_results_for_zones(zones, *collections):
    """Elige una combinación completa sin inferir partidos por descarte.

    Las colecciones se reciben en orden de prioridad. Se prueban combinaciones
    que conservan la fuente más prioritaria para cada pareja y sólo se acepta una
    foto que reconstruya PJ, puntos, GF, GC y DG de las zonas publicadas.
    """
    normalized = [_merge_lpf_results(collection) for collection in collections if collection]
    seen = set()
    for first_idx in range(len(normalized)):
        later = list(range(first_idx + 1, len(normalized)))
        for extra_count in range(len(later), -1, -1):
            for extras in combinations(later, extra_count):
                indexes = (first_idx,) + extras
                # _merge_lpf_results deja ganar a la última colección. Se invierte
                # el subconjunto para que la fuente con índice menor tenga prioridad.
                candidate = _merge_lpf_results(*(normalized[idx] for idx in reversed(indexes)))
                fingerprint = tuple(sorted((l, v, gl, gv) for l, v, gl, gv in candidate))
                if not candidate or fingerprint in seen:
                    continue
                seen.add(fingerprint)
                if _lpf_results_fit_zones(zones, candidate):
                    return candidate
    return []


def _lpf_repair_single_duplicate_in_zones(zones, played):
    """Revierte una doble contabilización inequívoca de un resultado ya jugado.

    Se usa para sanear fotos guardadas por versiones anteriores. Sólo actúa si la
    tabla tiene exactamente un partido de más, únicamente dos clubes difieren y el
    exceso de PJ/puntos/GF/GC/DG equivale a repetir una ficha final ya confirmada.
    """
    zones = {label: canon_base(base) for label, base in (zones or {}).items()}
    played = _merge_lpf_results(played)
    if set(zones) != {"A", "B"} or not played:
        return zones, ""
    old_count = expected_played_count(zones)
    if old_count is None or old_count != len(played) + 1:
        return zones, ""
    stats = _lpf_result_stats(played)
    teams = {team for base in zones.values() for team in base}
    if not teams.issubset(stats):
        return zones, ""

    changed = []
    keys = ("pj", "pts", "gf", "ga", "dg")
    for base in zones.values():
        for team, row in base.items():
            delta = {k: int(row.get(k, 0)) - int(stats[team].get(k, 0)) for k in keys}
            if any(delta.values()):
                changed.append((team, delta))
    if len(changed) != 2 or any(delta["pj"] != 1 for _team, delta in changed):
        return zones, ""
    a, b = changed[0][0], changed[1][0]
    matches = [r for r in played if {canon_club(r[0]), canon_club(r[1])} == {a, b}]
    if len(matches) != 1:
        return zones, ""
    home, away, gh, ga = matches[0]
    contrib = {
        home: {"pj": 1, "pts": 3 if gh > ga else 1 if gh == ga else 0,
               "gf": gh, "ga": ga, "dg": gh - ga},
        away: {"pj": 1, "pts": 3 if ga > gh else 1 if gh == ga else 0,
               "gf": ga, "ga": gh, "dg": ga - gh},
    }
    deltas = dict(changed)
    if any(deltas[team] != contrib[team] for team in (home, away)):
        return zones, ""

    rebuilt = {}
    for label, base in zones.items():
        rows = {}
        for team, old in base.items():
            row = {key: int(stats[team].get(key, 0)) for key in keys}
            if old.get("source_pos") is not None:
                row["source_pos"] = int(old.get("source_pos"))
            rows[team] = row
        rebuilt[label] = _lpf_reorder_source_positions(rows)
    try:
        _validate_lpf_tables(rebuilt)
    except Exception:
        return zones, ""
    if not _lpf_results_fit_zones(rebuilt, played):
        return zones, ""
    return rebuilt, (
        f"Se corrigió una doble contabilización de {home} {gh}-{ga} {away}: "
        "la tabla guardada tenía un PJ extra para ambos clubes."
    )


def _lpf_advance_zones_from_confirmed_results(zones, played):
    """Avanza una tabla atrasada usando una foto completa de resultados finales.

    Se acepta sólo una actualización hacia adelante: los resultados deben contener
    más partidos que la tabla y reproducir *exactamente* a todos los clubes que no
    jugaron esos encuentros nuevos. Para los que sí avanzan, PJ, puntos, GF y GC no
    pueden retroceder. De esta manera un feed de resultados que llega primero puede
    poner al día el standings sin permitir que un marcador parcial o una base
    incompleta reescriba la tabla.
    """
    zones = {label: canon_base(base) for label, base in (zones or {}).items()}
    played = _merge_lpf_results(played)
    if set(zones) != {"A", "B"} or not played:
        return zones, ""

    fixture_pairs = {
        (canon_club(row.get("l") or row.get("home") or ""),
         canon_club(row.get("v") or row.get("away") or ""))
        for row in LPF_FIXTURE
    }
    if any((canon_club(l), canon_club(v)) not in fixture_pairs for l, v, _gl, _gv in played):
        return zones, ""

    old_count = expected_played_count(zones)
    if old_count is None or len(played) <= old_count:
        return zones, ""

    result_stats = _lpf_result_stats(played)
    teams = {team for base in zones.values() for team in base}
    if not teams.issubset(result_stats):
        return zones, ""

    advanced = []
    numeric_keys = ("pj", "pts", "gf", "ga", "dg")
    for base in zones.values():
        for team, old in base.items():
            new = result_stats.get(team) or {}
            old_pj, new_pj = int(old.get("pj", 0)), int(new.get("pj", 0))
            if new_pj < old_pj:
                return zones, ""
            if new_pj == old_pj:
                # Un club que no sumó PJ debe quedar idéntico. Si no, la colección
                # de resultados contiene una corrección/conflicto histórico y no es
                # segura para avanzar automáticamente.
                if any(int(new.get(k, 0)) != int(old.get(k, 0)) for k in numeric_keys):
                    return zones, ""
                continue
            if any(int(new.get(k, 0)) < int(old.get(k, 0)) for k in ("pts", "gf", "ga")):
                return zones, ""
            advanced.append(team)

    delta_matches = len(played) - old_count
    delta_pj = sum(
        int(result_stats[team].get("pj", 0)) - int(row.get("pj", 0))
        for base in zones.values() for team, row in base.items()
    )
    if delta_pj != 2 * delta_matches or not advanced:
        return zones, ""

    rebuilt = {}
    for label, base in zones.items():
        rows = {}
        for team, old in base.items():
            stats = result_stats[team]
            row = {key: int(stats.get(key, 0)) for key in numeric_keys}
            if old.get("source_pos") is not None:
                row["source_pos"] = int(old.get("source_pos"))
            rows[team] = row
        rebuilt[label] = _lpf_reorder_source_positions(rows)

    try:
        _validate_lpf_tables(rebuilt)
    except Exception:
        return zones, ""
    if not _lpf_results_fit_zones(rebuilt, played):
        return zones, ""

    note = (
        f"La tabla de posiciones venía {delta_matches} partido(s) atrás y se avanzó "
        f"con {len(played)} resultados finales confirmados. Clubes actualizados: "
        + ", ".join(sorted(advanced)) + "."
    )
    return rebuilt, note
