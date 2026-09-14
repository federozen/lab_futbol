"""Previa pura por equipo para la LPF.

Recibe la ventana de calendario, los partidos abiertos y el contexto de copas ya
resueltos por la capa de Streamlit. Devuelve Markdown y una tabla de escenarios sin
leer ``session_state`` ni hacer red.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import pandas as pd

from lpf_display import display_team
from lpf_scenarios import exact_result_scenarios
from lpf_standings import liga_tabla_df

LPF_RUNTIME_API = 21


def _ord(position):
    return f"{position}º"


def preview_objective(value):
    """Normaliza la etiqueta visible al dominio que usa la Previa."""
    text = str(value or "Playoffs").strip().lower()
    if "desc" in text:
        return "descenso"
    if "libert" in text:
        return "libertadores"
    if "sud" in text or "copa" in text:
        return "copas"
    return "playoffs"


def _scenario_range_text(scenario):
    best, worst = scenario.get("best_rank"), scenario.get("worst_rank")
    if not best or not worst:
        return "—"
    return _ord(best) if best == worst else f"{_ord(best)}–{_ord(worst)}"


def _cup_scenario_reading(scenario, n_lib):
    best, worst = scenario.get("best_rank"), scenario.get("worst_rank")
    if not best or not worst:
        return "No se pudo establecer la situación de copas para esta ventana."
    lib_end = max(0, int(n_lib))
    cup_end = lib_end + 6
    if lib_end and worst <= lib_end:
        return "Termina la ventana en zona de Libertadores por la Tabla Anual."
    if lib_end and best <= lib_end:
        if worst <= cup_end:
            return "Puede quedar en Libertadores o Sudamericana."
        return "Puede entrar a Libertadores o Sudamericana, pero también quedar afuera."
    if best <= cup_end:
        if worst <= cup_end:
            return "Termina al menos en zona de Sudamericana."
        return "Puede entrar a una copa o quedar afuera."
    return "Queda fuera de los puestos de clasificación internacional por la Tabla Anual en esta ventana."


def _descent_scenario_reading(scenario, total_teams, n_annual):
    best, worst = scenario.get("best_rank"), scenario.get("worst_rank")
    if not best or not worst:
        return "No se pudo establecer el rango de la Tabla Anual."
    danger_from = max(1, int(total_teams) - max(1, int(n_annual)) + 1)
    if worst < danger_from:
        return "Continúa fuera de la zona de descenso por Tabla Anual."
    if best >= danger_from:
        return "Termina en la zona de descenso por Tabla Anual."
    return "Puede seguir afuera o caer en la zona de descenso por Tabla Anual."


def _zone_scenario_short(scenario):
    best = scenario.get("best_rank")
    rng = _scenario_range_text(scenario)
    if scenario.get("can_enter") and not scenario.get("can_fail"):
        return f"queda {rng}, siempre dentro de los ocho"
    if scenario.get("can_enter") and scenario.get("can_fail"):
        return f"puede quedar {rng} y también salir de los ocho"
    if best:
        return f"sigue afuera; su mejor puesto es {_ord(best)}"
    return "no tiene un rango confirmado"


def _preview_reusable_line(
    team,
    objective,
    zone_scenarios,
    annual_scenarios=None,
    direct_route="",
    n_lib=0,
    total_teams=30,
    n_annual=1,
    current_zone_rank=None,
    cup_scenarios=None,
):
    def lower_initial(value):
        text = str(value or "").rstrip(".")
        return text[:1].lower() + text[1:] if text else text

    shown = display_team(team)
    labels = ("gana", "empata", "pierde")
    if objective == "descenso" and annual_scenarios:
        parts = [
            f"si {label}, {lower_initial(_descent_scenario_reading(row, total_teams, n_annual))}"
            for label, row in zip(labels, annual_scenarios)
        ]
        return f"{shown} se juega su situación en la Tabla Anual: " + "; ".join(parts) + "."
    if objective in ("copas", "libertadores"):
        if direct_route:
            route = re.sub(r"\s*\(art\.[^)]+\)", "", str(direct_route)).strip()
            return (
                f"{shown} ya tiene asegurada su plaza internacional como {lower_initial(route)}; "
                "su resultado mueve su puesto en la Tabla Anual y puede modificar el corte para los demás."
            )
        if annual_scenarios and cup_scenarios:
            parts = []
            for label, annual_row, cup_row in zip(labels, annual_scenarios, cup_scenarios):
                rango = _scenario_range_text(annual_row)
                lectura = lower_initial(_cup_scenario_reading(cup_row, n_lib))
                parts.append(f"si {label}, puede quedar {rango} en la Tabla Anual y {lectura}")
            return f"{shown} se juega su lugar en las copas: " + "; ".join(parts) + "."
        if annual_scenarios:
            parts = [
                f"si {label}, puede quedar {_scenario_range_text(row)} en la Tabla Anual"
                for label, row in zip(labels, annual_scenarios)
            ]
            return f"{shown}: " + "; ".join(parts) + "."
    purpose = (
        "sostenerse en zona de playoffs"
        if current_zone_rank and current_zone_rank <= 8
        else "entrar en zona de playoffs"
    )
    parts = [f"si {label}, {_zone_scenario_short(row)}" for label, row in zip(labels, zone_scenarios)]
    return f"{shown} se juega {purpose}: " + "; ".join(parts) + "."


def team_preview_text(
    team,
    zones: Mapping,
    pending: Sequence,
    annual: Mapping | None,
    *,
    window: Mapping,
    scenario_games: Sequence,
    objective="Playoffs",
    current_round=None,
    n_annual=1,
    cup_allocation: Mapping | None = None,
    fixed_routes: Mapping | None = None,
    eligible_teams: Sequence | None = None,
    top_eight=8,
):
    """Construye la Previa exacta y su tabla de escenarios sin depender de UI."""
    lab = next((label for label, base in (zones or {}).items() if team in base), None)
    if not lab or team not in zones.get(lab, {}):
        return None, None

    games = list(window.get("games") or [])
    own_match = window.get("own_match")
    own_meta = window.get("own_meta") or {}
    scope = window.get("scope") or "next_team_match"
    title = (
        f"## Próximo partido de {team}"
        if scope == "next_team_match"
        else f"## Previa de {window['label']} para {team}"
    )
    lines = [title]

    if not games:
        lines.append("No hay partidos pendientes en el alcance elegido.")
        return "\n\n".join(lines), None
    if not own_match:
        lines.append(
            f"{team} no juega en esta ventana. La tabla puede moverse por resultados ajenos, "
            "pero no corresponde mostrar ramas gana/empata/pierde."
        )
        return "\n\n".join(lines), None

    local, visitor = own_match
    rival = visitor if local == team else local
    lines.append(f"Juega **{'de local' if local == team else 'de visitante'} ante {rival}**.")
    scheduled = own_meta.get("scheduled_at")
    round_no = own_meta.get("round")
    if scheduled:
        from lpf_schedule import format_datetime

        lines.append(f"Está programado para **{format_datetime(scheduled)}**, en hora argentina.")
    elif scope in ("next_team_match", "next_team_day"):
        lines.append(
            "La fuente no aportó una fecha y hora confiables para este partido; se usó el orden del fixture oficial como respaldo."
        )
    if round_no is not None:
        if current_round is not None and round_no < current_round:
            lines.append(
                f"Es un **partido pendiente de la Fecha {round_no}**, aunque se juegue antes que la próxima jornada completa."
            )
        else:
            lines.append(f"Corresponde a la **Fecha {round_no}**.")

    postponed = window.get("postponed") or []
    if scope == "extended_window" and postponed:
        doubles = sorted(
            candidate
            for candidate in {x for match in games for x in match}
            if sum(candidate in match for match in games) > 1
        )
        lines.append(
            f"La ventana incluye **{len(postponed)} partido(s) postergado(s)**. "
            "El motor analiza todos los encuentros juntos; no omite el segundo partido de los equipos que juegan dos veces."
        )
        if doubles:
            lines.append("Juegan dos veces en la ventana: **" + ", ".join(doubles) + "**.")

    rows = []
    zone_scenarios = exact_result_scenarios(zones[lab], scenario_games, team, own_match, top_eight)
    zone_table = liga_tabla_df(zones[lab])
    current_zone_rank = int(zone_table.index[zone_table["Equipo"] == team][0] + 1)
    result_column = "Si River" if team == "River Plate" else f"Si {team}"
    for scenario in zone_scenarios:
        points = (
            str(scenario["points_min"])
            if scenario["points_min"] == scenario["points_max"]
            else f"{scenario['points_min']}–{scenario['points_max']}"
        )
        rows.append(
            {
                "Tabla": f"Playoffs · Zona {lab}",
                result_column: scenario["result"].lower(),
                "Puntos al cierre": points,
                "Mejor puesto": _ord(scenario["best_rank"]) if scenario["best_rank"] else "—",
                "Peor puesto": _ord(scenario["worst_rank"]) if scenario["worst_rank"] else "—",
                "Lectura": (
                    "Puede quedar entre los ocho primeros"
                    if scenario["can_enter"]
                    else "No puede entrar entre los ocho primeros"
                )
                + (
                    " y también afuera"
                    if scenario["can_enter"] and scenario["can_fail"]
                    else "; no puede salir"
                    if scenario["can_enter"] and not scenario["can_fail"]
                    else ""
                ),
            }
        )

    mode = preview_objective(objective)
    annual_scenarios = None
    cup_scenarios = None
    direct_route = ""
    fixed_routes = dict(fixed_routes or {})
    eligible = list(eligible_teams or [])
    allocation = dict(cup_allocation or {})
    n_lib = 0
    if annual and team in annual:
        if mode == "descenso":
            annual_scenarios = exact_result_scenarios(annual, scenario_games, team, own_match, len(annual))
            for scenario in annual_scenarios:
                points = (
                    str(scenario["points_min"])
                    if scenario["points_min"] == scenario["points_max"]
                    else f"{scenario['points_min']}–{scenario['points_max']}"
                )
                rows.append(
                    {
                        "Tabla": "Descenso · Tabla Anual",
                        result_column: scenario["result"].lower(),
                        "Puntos al cierre": points,
                        "Mejor puesto": _ord(scenario["best_rank"]) if scenario["best_rank"] else "—",
                        "Peor puesto": _ord(scenario["worst_rank"]) if scenario["worst_rank"] else "—",
                        "Lectura": _descent_scenario_reading(scenario, len(annual), n_annual),
                    }
                )
        else:
            annual_positions_for_note = {
                row["Equipo"]: pos
                for pos, (_idx, row) in enumerate(liga_tabla_df(annual).iterrows(), 1)
            }
            n_lib = int(allocation.get("n_tabla_lib", 0))
            direct_route = fixed_routes.get(team, "")
            annual_scenarios = exact_result_scenarios(annual, scenario_games, team, own_match, len(annual))
            if direct_route:
                route = re.sub(r"\s*\(art\.[^)]+\)", "", str(direct_route)).strip()
                for scenario in annual_scenarios:
                    points = (
                        str(scenario["points_min"])
                        if scenario["points_min"] == scenario["points_max"]
                        else f"{scenario['points_min']}–{scenario['points_max']}"
                    )
                    rows.append(
                        {
                            "Tabla": "Copas · Tabla Anual",
                            result_column: scenario["result"].lower(),
                            "Puntos al cierre": points,
                            "Mejor puesto": _ord(scenario["best_rank"]) if scenario["best_rank"] else "—",
                            "Peor puesto": _ord(scenario["worst_rank"]) if scenario["worst_rank"] else "—",
                            "Lectura": f"Ya clasificado por otra vía: {route}. Su puesto en la Anual no define su plaza.",
                        }
                    )
            elif team in eligible:
                eligible_base = {candidate: annual[candidate] for candidate in eligible}
                cup_scenarios = exact_result_scenarios(
                    eligible_base, scenario_games, team, own_match, len(eligible_base)
                )
                for annual_scenario, cup_scenario in zip(annual_scenarios, cup_scenarios):
                    points = (
                        str(annual_scenario["points_min"])
                        if annual_scenario["points_min"] == annual_scenario["points_max"]
                        else f"{annual_scenario['points_min']}–{annual_scenario['points_max']}"
                    )
                    rows.append(
                        {
                            "Tabla": "Copas · Tabla Anual",
                            result_column: annual_scenario["result"].lower(),
                            "Puntos al cierre": points,
                            "Mejor puesto": _ord(annual_scenario["best_rank"])
                            if annual_scenario["best_rank"]
                            else "—",
                            "Peor puesto": _ord(annual_scenario["worst_rank"])
                            if annual_scenario["worst_rank"]
                            else "—",
                            "Lectura": _cup_scenario_reading(cup_scenario, n_lib),
                        }
                    )

    win, draw, loss = zone_scenarios[0], zone_scenarios[1], zone_scenarios[2]
    if win["best_rank"] and win["best_rank"] > 1:
        lines.append(
            f"**No puede terminar primero:** aun ganando, el mejor puesto posible es "
            f"**{_ord(win['best_rank'])}**. El cálculo deja abiertos todos los otros partidos pendientes "
            "de esa misma fecha y contempla sus victorias, empates y derrotas."
        )

    def zone_branch_sentence(label, scenario):
        best = scenario.get("best_rank")
        worst = scenario.get("worst_rank")
        if not best or not worst:
            return f"**Si {label}**, no se pudo establecer un rango completo de posiciones."
        if best == worst:
            position = f"termina **{_ord(best)}** en la Zona"
        else:
            position = f"puede terminar entre **{_ord(best)} y {_ord(worst)}** en la Zona"
        if scenario.get("can_enter") and not scenario.get("can_fail"):
            status = "En todos los escenarios queda entre los ocho primeros."
        elif scenario.get("can_enter") and scenario.get("can_fail"):
            status = "Tiene escenarios en los que queda entre los ocho y otros en los que termina afuera."
        else:
            status = "No puede entrar entre los ocho primeros en esta fecha."
        return f"**Si {label}**, {position}. {status}"

    lines.append(zone_branch_sentence("gana", win))
    lines.append(zone_branch_sentence("empata", draw))
    lines.append(zone_branch_sentence("pierde", loss))
    lines.append(
        "_EXACTO POR PUNTOS · Cada partido tiene una sola salida posible: victoria local, empate o victoria visitante. "
        "Cuando dos equipos terminan igualados, el rango incluye tanto el desempate favorable como el adverso; "
        "no inventa marcadores futuros ni afirma quién ganará por DG, GF, mano a mano, fair play o sorteo._"
    )

    if mode in ("copas", "libertadores") and annual_scenarios:
        annual_table = liga_tabla_df(annual)
        annual_hit = annual_table.index[annual_table["Equipo"] == team].tolist()
        current_annual_rank = int(annual_hit[0] + 1) if annual_hit else None
        lines.append("### Copas · Tabla Anual")
        if current_annual_rank:
            intro = f"Hoy está **{_ord(current_annual_rank)} en la Tabla Anual**."
            fixed_above = [
                qualifier
                for qualifier in fixed_routes
                if qualifier in annual
                and qualifier != team
                and annual_positions_for_note.get(qualifier, 10_000) < current_annual_rank
            ]
            if fixed_above:
                shown = [display_team(qualifier) for qualifier in fixed_above]
                if len(shown) == 1:
                    intro += f" (Arriba está **{shown[0]}**, que ya tiene una plaza directa de Libertadores.)"
                else:
                    intro += (
                        f" (Entre los equipos que tiene arriba están **{', '.join(shown[:-1])}** y **{shown[-1]}**, "
                        "que ya tienen una plaza directa de Libertadores.)"
                    )
            lines.append(intro)
        labels_caps = ("gana", "empata", "pierde")
        if direct_route:
            for label, annual_row in zip(labels_caps, annual_scenarios):
                lines.append(
                    f"**Si {label}**, su mejor posición posible en la Tabla Anual es {_ord(annual_row['best_rank'])} "
                    f"y la peor {_ord(annual_row['worst_rank'])}. Ya tiene la plaza internacional asegurada por otra vía."
                )
        elif cup_scenarios:
            for label, annual_row, cup_row in zip(labels_caps, annual_scenarios, cup_scenarios):
                reading = _cup_scenario_reading(cup_row, n_lib)
                lines.append(
                    f"**Si {label}**, su mejor posición posible en la Tabla Anual es {_ord(annual_row['best_rank'])} "
                    f"y la peor {_ord(annual_row['worst_rank'])}; {reading[:1].lower() + reading[1:]}"
                )

    reusable = _preview_reusable_line(
        team,
        mode,
        zone_scenarios,
        annual_scenarios,
        direct_route,
        n_lib,
        len(annual or {}),
        n_annual,
        current_zone_rank,
        cup_scenarios,
    )
    frame = pd.DataFrame(rows)
    frame.attrs["export_title"] = f"{display_team(team)} · escenarios del próximo partido"
    frame.attrs["export_name"] = f"{display_team(team)}_escenarios_proximo_partido"
    frame.attrs["reusable_line"] = reusable
    return "\n\n".join(lines), frame
