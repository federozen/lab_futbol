"""Tabla Anual autoritativa y reparto puro de plazas internacionales LPF 2026.

El módulo no consulta ``st.session_state`` ni proveedores. Recibe zonas, Apertura,
Anual directa y campeones por parámetro, de modo que Streamlit y una futura API
puedan reutilizar exactamente la misma regla.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from lpf_clubs import canon_base
from lpf_data_quality import sum_opening_and_zones, validate_annual
from lpf_standings import liga_tabla_df
from lpf_text import _zlow

LPF_RUNTIME_API = 21


def annual_base(
    zones: Mapping[str, Mapping[str, Mapping[str, object]]] | None,
    *,
    opening: Mapping[str, Mapping[str, object]] | None = None,
    direct_annual: Mapping[str, Mapping[str, object]] | None = None,
    opening_rounds: int,
) -> dict[str, dict[str, object]]:
    """Resuelve la Tabla General con la misma prioridad histórica de la app.

    1. Si el Apertura cubre exactamente los equipos de las zonas, reconstruye la
       Anual como Apertura + zonas actuales.
    2. Si no, acepta una Anual directa sólo cuando supera ``validate_annual``.
    3. Si ninguna foto es válida, devuelve ``{}``.
    """
    zones = zones or {}
    teams = {team for base in zones.values() for team in base}
    opening_canon = canon_base(opening or {})
    if teams and set(opening_canon) == teams:
        return sum_opening_and_zones(opening_canon, zones)

    direct = canon_base(direct_annual or {})
    if direct and not any(
        issue.level == "blocked"
        for issue in validate_annual(zones, direct, opening_rounds=opening_rounds)
    ):
        return direct
    return {}


def _match_team_name_raw(name: object, teams: Sequence[str]) -> str:
    """Replica ``_match_eq`` incluso para valores vacíos/no string históricos."""
    normalized = _zlow(name)
    for team in teams:
        if _zlow(team) == normalized:
            return team
    for team in teams:
        candidate = _zlow(team)
        if candidate in normalized or normalized in candidate:
            return team
    tokens = set(normalized.split())
    best, score = None, 0
    for team in teams:
        overlap = len(tokens & set(_zlow(team).split()))
        if overlap > score:
            best, score = team, overlap
    return str(best) if score and best is not None else ""


def _match_team_name(name: object, teams: Sequence[str]) -> str:
    """Empareja un nombre externo conservando la heurística histórica de la UI."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    return _match_team_name_raw(raw, teams)



def fixed_libertadores_qualifiers(
    annual: Mapping[str, Mapping[str, object]],
    *,
    camps: Sequence[object] = ("", "", ""),
    extras: Sequence[object] = ("", ""),
    copa_replacement: object = "",
) -> list[str]:
    """Normaliza los clasificados ya fijos a Libertadores contra la Anual.

    Mantiene la prioridad histórica de la app: campeones del Apertura, Clausura y
    Copa Argentina, campeones argentinos de Libertadores/Sudamericana y, por
    último, el reemplazo cargado para Copa Argentina. Los duplicados se eliminan
    conservando el primer motivo/origen.
    """
    order = list(liga_tabla_df(annual)["Equipo"]) if annual else []
    result: list[str] = []
    raws = tuple(camps or ()) + tuple(extras or ())
    if copa_replacement:
        raws += (copa_replacement,)
    for raw in raws:
        team = _match_team_name(raw, order) if raw else ""
        if team and team not in result:
            result.append(team)
    return result


def copa_argentina_alive(
    annual: Mapping[str, Mapping[str, object]],
    alive: Sequence[object] | None = None,
    *,
    eligible_pool: Sequence[object] | None = None,
) -> list[str]:
    """Normaliza equipos todavía vivos en Copa Argentina contra la Anual.

    ``eligible_pool`` es un guard opcional de instancia: cuando se conoce el
    conjunto que alcanzó una ronda posterior, una foto vieja no puede reintroducir
    eliminados de rondas previas. Es aditivo y no cambia la semántica histórica
    cuando el argumento se omite.
    """
    order = list(liga_tabla_df(annual)["Equipo"]) if annual else []
    allowed: set[str] | None = None
    if eligible_pool is not None:
        allowed = set()
        for raw in eligible_pool:
            team = _match_team_name_raw(raw, order)
            if team:
                allowed.add(team)
    result: list[str] = []
    for raw in alive or ():
        # El helper histórico llamaba ``_match_eq`` incluso con cadenas vacías.
        # Preservamos esa semántica exacta por compatibilidad de comportamiento.
        team = _match_team_name_raw(raw, order)
        if team and (allowed is None or team in allowed) and team not in result:
            result.append(team)
    return result


def copa_snapshot_label(updated: object = "", source: object = "") -> str:
    """Devuelve la etiqueta editorial compacta de actualización/fuente de Copa."""
    updated_text = str(updated or "").strip()
    source_text = str(source or "").strip()
    if updated_text and source_text:
        return f"{updated_text}; fuente: {source_text}"
    return updated_text or source_text

def allocate_cup_slots(
    annual: Mapping[str, Mapping[str, object]],
    *,
    camps: Sequence[object] = ("", "", ""),
    extras: Sequence[object] = ("", ""),
    copa_replacement: object = "",
) -> dict[str, object]:
    """Reparte las plazas 2027 según arts. 27 y 28, incluido reordenamiento.

    ``camps`` = campeón Apertura, campeón Clausura, campeón Copa Argentina.
    ``extras`` = campeón Libertadores 2026 argentino, campeón Sudamericana 2026
    argentino. ``copa_replacement`` es el mejor equipo de Primera de Copa
    Argentina cuando debe heredar ARGENTINA 3.
    """
    order = list(liga_tabla_df(annual)["Equipo"])

    def norm(value: object) -> str:
        raw = str(value or "").strip()
        return _match_team_name(raw, order) if raw else ""

    aperture_champion, clausura_champion, copa_champion = [norm(x) for x in camps]
    lib_champion, sud_champion = [norm(x) for x in extras]
    copa_heir = norm(copa_replacement)

    libertadores: list[tuple[str, str]] = []
    notices: list[str] = []

    def already(team: str) -> bool:
        return any(team == current for current, _reason in libertadores)

    def add(team: str, reason: str) -> bool:
        if team and not already(team):
            libertadores.append((team, reason))
            return True
        return False

    if lib_champion:
        add(lib_champion, "Campeón de la Libertadores 2026 — plaza adicional (art. 27.9)")
    if sud_champion:
        add(sud_champion, "Campeón de la Sudamericana 2026 — plaza adicional (art. 27.10)")

    base_slots = 6
    for team, reason, article in (
        (aperture_champion, "Campeón del Apertura", "27.1"),
        (clausura_champion, "Campeón del Clausura", "27.2"),
    ):
        if team:
            if already(team):
                notices.append(
                    f"{team} ya tenía plaza, así que su lugar como {reason} lo toma el siguiente mejor de la anual (art. 27.7/27.9)."
                )
            else:
                add(team, f"{reason} (art. {article})")
                base_slots -= 1

    if copa_champion:
        if already(copa_champion):
            if copa_heir and not already(copa_heir):
                add(
                    copa_heir,
                    "Mejor equipo de Primera de la Copa Argentina — hereda ARGENTINA 3 (arts. 27.8 y 27.8.1)",
                )
                notices.append(
                    f"{copa_champion} ya tenía plaza: ARGENTINA 3 fue asignada a {copa_heir}, mejor equipo de Primera cargado de la Copa Argentina."
                )
            else:
                notices.append(
                    f"{copa_champion} (Copa Argentina) ya tenía plaza: **ARGENTINA 3 la hereda el mejor equipo de Primera de la Copa Argentina 2026**, "
                    "no el siguiente de la anual (art. 27.8). Cargá ese reemplazo cuando quede definido."
                )
            base_slots -= 1
        else:
            add(copa_champion, "Campeón de la Copa Argentina (art. 27.3, plaza inalterable)")
            base_slots -= 1
    else:
        notices.append(
            "Falta definirse el campeón de la **Copa Argentina 2026**. Su plaza **ARGENTINA 3** permanece dentro de esa competencia y, cuando se conozca al campeón, ese club ya no consumirá otro cupo por la Tabla Anual."
        )
        base_slots -= 1

    if not aperture_champion:
        notices.append("Falta el campeón del **Apertura**.")
        base_slots -= 1
    if not clausura_champion:
        notices.append("Falta el campeón del **Clausura** (se define en los playoffs).")
        base_slots -= 1

    table_slots = max(0, base_slots)
    taken = [team for team, _reason in libertadores]
    reduced = [team for team in order if team not in taken]
    for team in reduced[:table_slots]:
        libertadores.append(
            (team, f"por Tabla Anual ({order.index(team) + 1}º) — arts. 27.4 a 27.6")
        )

    return {
        "lib": libertadores,
        "n_tabla_lib": table_slots,
        "orden": order,
        "reducida": reduced,
        "avisos": notices,
        "anual": annual,
        "tomados": [team for team, _reason in libertadores],
    }
