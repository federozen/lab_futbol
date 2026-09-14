"""
⚽ Calculadora de escenarios — LPF 2026
Convertido de Jupyter Notebook (v2) a Streamlit

La versión vigente está en ``lpf_version.__version__`` (única fuente de verdad).
El historial completo está en ``CHANGELOG.md``.
"""

from lpf_version import __version__

import streamlit as st
from lpf_runtime import LPF_RUNTIME_API, runtime_compatibility, runtime_error_message
from lpf_services import (
    ContractError as _LPFServiceContractError,
    calculate as _lpf_service_calculate_public,
    prepare_competition_snapshot as _lpf_service_prepare_snapshot,
    service_capabilities as _lpf_service_capabilities,
)

_REQUIRED_RUNTIME_API = 21
_RUNTIME_REPORT = runtime_compatibility()
if LPF_RUNTIME_API != _REQUIRED_RUNTIME_API:
    st.error("⚠️ Archivos del motor desincronizados")
    st.write(
        f"lpf_runtime.py usa el contrato interno {LPF_RUNTIME_API}, "
        f"pero esta app requiere {_REQUIRED_RUNTIME_API}. Actualizá el núcleo completo."
    )
    st.caption(f"Versión esperada de la app: {__version__}")
    st.stop()
if not _RUNTIME_REPORT["ok"]:
    st.error("⚠️ Archivos del motor desincronizados")
    st.write(runtime_error_message(_RUNTIME_REPORT))
    st.caption(f"Versión esperada de la app: {__version__}")
    st.stop()

from itertools import product, combinations
import hashlib
import json
import pandas as pd
import numpy as np
import re
import requests
from lpf_data_quality import (
    build_quality_report, derive_opening_from_results, pending_pairs,
)
from lpf_models import DataQualityReport
from lpf_competition_narratives import (
    libertadores_story, relegation_story, round_preview_story, sudamericana_story, zone_story,
)
from lpf_scenarios import can_fail_with_points, can_finish_exact_rank_by_points, exact_objective_result_states, exact_result_scenarios, point_ladder, scenario_rank_bounds, best_worst_window_scenarios, reachable_point_totals
from lpf_pisos import (
    VENTANA_EXACTA, piso_no_descenso, piso_por_corte, pisos_de_equipo,
    promedio_totales, tabla_pisos_objetivo,
)
from lpf_competitive_context import competition_context, historical_reference
from lpf_conditionals import branch_explanation, key_rival_matrix, next_round_conditionals
from lpf_editorial_definition import (
    all_teams_matrix, branch_cell, branch_state, definition_clock, fight_zone,
    definition_guarantee as _editorial_definition_guarantee,
    guarantee_round_label as _editorial_guarantee_round_label,
    objective_context as _editorial_objective_context,
)
from lpf_relegation import current_relegation_picture
from lpf_preview import preview_objective as _preview_objective, team_preview_text as _team_preview_text_core
from lpf_display import (
    cup_current_slots_spec, cup_probability_heatmap_spec, display_team, editorialize_frame,
    editorialize_spec, editorialize_text,
)
from lpf_fixture_sources import (
    expected_played_count, merge_match_records, parse_futbolargentino_results_html,
    parse_lpf_official_listing_html, parse_lpf_official_results_article_html,
    played_pending_from_records,
    validate_fixture_records,
)
from lpf_schedule import (
    build_schedule_map as _schedule_build_map,
    current_round as _schedule_current_round,
    format_datetime as _schedule_format_datetime,
    match_round as _schedule_match_round,
    next_team_match as _schedule_next_team_match,
    ordered_team_matches as _schedule_ordered_team_matches,
    parse_datetime as _schedule_parse_datetime,
    pending_round_map as _schedule_pending_round_map,
    resolve_scope_games as _schedule_resolve_scope_games,
    round_label as _schedule_round_label,
)
from lpf_standings import (
    DEFAULT_CRITERIOS, _stats, liga_tabla_df, _liga_in_out,
    posiciones as _standings_posiciones, tabla as _standings_tabla,
)
from lpf_result_updates import apply_completed_results, table_position_changes
from lpf_form import (
    estimate_team_strength as _estimate_team_strength,
    result_letter as _form_result_letter,
    team_form as _team_form,
    team_streak as _team_streak,
)
from lpf_simulation import (
    build_simulation_context as _build_simulation_context_core,
    match_outcome_probabilities as _match_outcome_probabilities,
    objective_mask as _obj_bool,
    simulate_point_additions as _sim_lpf_add,
    simulate_zone_rank_points as _simulate_zone_rank_points_core,
    summarize_rank_condition as _summarize_rank_condition,
)
from lpf_qualification import (
    allocate_cup_slots, annual_base as _qualification_annual_base,
    copa_argentina_alive as _qualification_copa_argentina_alive,
    copa_snapshot_label as _qualification_copa_snapshot_label,
    fixed_libertadores_qualifiers as _qualification_fixed_libertadores_qualifiers,
)
from lpf_state import (
    LPF_APERTURA_PJ, build_lpf_state, opening_is_valid, refresh_lpf_quality_state,
)


_LPF_PUBLIC_MC_RUNS = 6000


def _piso_garantia_exacta(obj):
    """Compatibilidad con PisoObjetivo 3.8.7 y anteriores."""
    try:
        return obj.garantia_exacta
    except AttributeError:
        return getattr(obj, "piso_exacto", None) if bool(getattr(obj, "exacto", False)) else None


def _piso_referencia_conservadora(obj):
    """Compatibilidad con PisoObjetivo 3.8.7 y anteriores."""
    try:
        return obj.referencia_conservadora
    except AttributeError:
        if bool(getattr(obj, "exacto", False)):
            return None
        value = getattr(obj, "piso_conservador", None)
        if value is not None:
            return value
        return getattr(obj, "piso_exacto", None)

# La interfaz muestra nombres periodísticos (River, Boca, Vélez, etc.) sin
# cambiar las claves canónicas que usa el motor para fixtures y cálculos.
_ST_MARKDOWN = st.markdown
_ST_DATAFRAME = st.dataframe
_ST_INFO = st.info
_ST_SUCCESS = st.success
_ST_WARNING = st.warning
_ST_ERROR = st.error
_ST_CAPTION = st.caption
_ST_SELECTBOX = st.selectbox
_ST_GRAPHVIZ = st.graphviz_chart

def ui_markdown(body, *args, **kwargs):
    return _ST_MARKDOWN(editorialize_text(body), *args, **kwargs)

_UI_TABLE_SEQUENCE = 0


def _safe_export_name(value):
    import unicodedata

    text = editorialize_text(str(value or "tabla")).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "tabla"


def _table_html_fragment(frame, title):
    import html

    safe_title = html.escape(editorialize_text(str(title or "Tabla")))
    table_html = frame.to_html(index=False, border=0, classes="tabla-editorial", escape=True)
    return f'''<div class="tabla-editorial-wrap">
<style>
.tabla-editorial-wrap {{max-width:100%; overflow-x:auto; font-family:Arial,Helvetica,sans-serif; color:#202124;}}
.tabla-editorial-title {{font-size:20px; font-weight:700; margin:0 0 12px;}}
table.tabla-editorial {{border-collapse:collapse; width:100%; font-size:14px; line-height:1.35;}}
table.tabla-editorial th {{background:#f1f3f4; text-align:left; font-weight:700; padding:9px 10px; border:1px solid #d9dde3;}}
table.tabla-editorial td {{padding:9px 10px; border:1px solid #d9dde3; vertical-align:top;}}
table.tabla-editorial tbody tr:nth-child(even) {{background:#fafafa;}}
</style>
<div class="tabla-editorial-title">{safe_title}</div>
{table_html}
</div>'''


def _table_html_document(frame, title):
    import html

    safe_title = html.escape(editorialize_text(str(title or "Tabla")))
    fragment = _table_html_fragment(frame, title)
    return f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
</head>
<body>
{fragment}
</body>
</html>'''


def _table_fingerprint(frame, title, file_name):
    import hashlib

    raw = frame.to_csv(index=False, sep="\x1f").encode("utf-8", errors="replace")
    seed = (str(title or "") + "\x1e" + str(file_name or "")).encode("utf-8", errors="replace")
    return hashlib.sha1(seed + raw).hexdigest()[:14]


def _table_png_bytes(frame, title):
    import textwrap
    from io import BytesIO
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    visible = frame.copy().fillna("")
    visible.columns = [str(col) for col in visible.columns]
    for col in visible.columns:
        visible[col] = visible[col].map(
            lambda value: "\n".join(textwrap.wrap(str(value), 34)) if len(str(value)) > 34 else str(value)
        )
    nrows, ncols = visible.shape
    longest = max([len(str(x)) for x in visible.columns] + [len(str(x)) for x in visible.astype(str).to_numpy().ravel()] + [8])
    fig_w = min(24, max(8, 1.55 * max(1, ncols) + min(9, longest / 18)))
    fig_h = min(48, max(2.8, 0.62 * (nrows + 1) + 1.2))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=180)
    ax.axis("off")
    ax.set_title(editorialize_text(str(title or "Tabla")), loc="left", fontsize=15, fontweight="bold", pad=14)
    table = ax.table(
        cellText=visible.values,
        colLabels=visible.columns,
        cellLoc="left",
        colLoc="left",
        loc="upper left",
        bbox=[0, 0, 1, 0.94],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.8 if ncols >= 7 else 8.7 if ncols >= 5 else 9.5)
    table.auto_set_column_width(col=list(range(max(1, ncols))))
    for (row, _col), cell in table.get_celld().items():
        cell.set_linewidth(0.45)
        if row == 0:
            cell.set_text_props(fontweight="bold")
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.18)
    plt.close(fig)
    return buf.getvalue()


def _build_table_export_payload(frame, title):
    payload = {
        "html_fragment": _table_html_fragment(frame, title),
        "html_document": _table_html_document(frame, title).encode("utf-8"),
        "csv": frame.to_csv(index=False, sep=";").encode("utf-8-sig"),
        "text": frame.to_csv(index=False, sep="\t").encode("utf-8"),
        "png": None,
        "png_error": "",
    }
    try:
        payload["png"] = _table_png_bytes(frame, title)
    except Exception as exc:
        payload["png_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _render_table_exports(frame, title, file_name, key):
    title = editorialize_text(str(title or "Tabla"))
    slug = _safe_export_name(file_name or title)
    fingerprint = _table_fingerprint(frame, title, file_name)
    state_prefix = f"{key}_{fingerprint}"
    ready_key = f"{state_prefix}_ready"
    payload_key = f"{state_prefix}_payload"
    ready = bool(st.session_state.get(ready_key))

    with st.expander("Exportar esta tabla", expanded=ready):
        if not ready:
            ui_caption("Generá los archivos cuando los necesites. El exportador conservará la tabla abierta después del clic.")
            if st.button("Generar PNG, HTML, CSV y texto", key=f"{state_prefix}_prepare", use_container_width=True):
                try:
                    with st.spinner("Preparando archivos…"):
                        st.session_state[payload_key] = _build_table_export_payload(frame, title)
                    st.session_state[ready_key] = True
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudieron preparar los archivos: {type(exc).__name__}: {exc}")
            return

        payload = st.session_state.get(payload_key)
        if not payload:
            try:
                with st.spinner("Reconstruyendo archivos…"):
                    payload = _build_table_export_payload(frame, title)
                st.session_state[payload_key] = payload
            except Exception as exc:
                st.error(f"No se pudieron preparar los archivos: {type(exc).__name__}: {exc}")
                return

        c1, c2, c3, c4 = st.columns(4)
        if payload.get("png"):
            c1.download_button(
                "Descargar PNG", payload["png"], file_name=f"{slug}.png", mime="image/png",
                key=f"{state_prefix}_png", use_container_width=True,
            )
        else:
            c1.button("PNG no disponible", key=f"{state_prefix}_png_disabled", disabled=True, use_container_width=True)
        c2.download_button(
            "Descargar HTML", payload["html_document"], file_name=f"{slug}.html", mime="text/html",
            key=f"{state_prefix}_html", use_container_width=True,
        )
        c3.download_button(
            "Descargar CSV", payload["csv"], file_name=f"{slug}.csv", mime="text/csv",
            key=f"{state_prefix}_csv", use_container_width=True,
        )
        c4.download_button(
            "Descargar texto", payload["text"], file_name=f"{slug}.txt", mime="text/plain",
            key=f"{state_prefix}_txt", use_container_width=True,
        )
        if payload.get("png_error"):
            ui_warning("El resto de los formatos está disponible, pero no se pudo construir el PNG: " + payload["png_error"])

        show_html = st.checkbox("Mostrar HTML listo para pegar en el administrador", key=f"{state_prefix}_show_html")
        if show_html:
            st.code(payload["html_fragment"], language="html")
            ui_caption("El ícono de copia del bloque permite llevar este fragmento directamente a un módulo de HTML libre.")

        if st.button("Volver a generar", key=f"{state_prefix}_reset", use_container_width=True):
            st.session_state.pop(payload_key, None)
            st.session_state[ready_key] = False
            st.rerun()
        ui_caption("PNG para insertar como imagen; HTML para el administrador; CSV y texto para edición.")

def ui_dataframe(data, *args, **kwargs):
    global _UI_TABLE_SEQUENCE
    exportable = bool(kwargs.pop("exportable", True))
    export_title = kwargs.pop("export_title", None)
    export_name = kwargs.pop("export_name", None)
    original_attrs = dict(getattr(data, "attrs", {}) or {})
    frame = editorialize_frame(data)
    if hasattr(frame, "attrs"):
        frame.attrs.update(original_attrs)
    result = _ST_DATAFRAME(frame, *args, **kwargs)
    if exportable and isinstance(frame, pd.DataFrame) and not frame.empty:
        _UI_TABLE_SEQUENCE += 1
        title = export_title or frame.attrs.get("export_title") or "Tabla"
        name = export_name or frame.attrs.get("export_name") or title
        _render_table_exports(frame, title, name, key=f"tabla_export_{_UI_TABLE_SEQUENCE}")
    reusable = frame.attrs.get("reusable_line") if hasattr(frame, "attrs") else None
    if reusable:
        ui_markdown("**Renglón reutilizable**")
        st.code(editorialize_text(str(reusable)), language="text")
    return result

def ui_info(body, *args, **kwargs):
    return _ST_INFO(editorialize_text(body), *args, **kwargs)

def ui_success(body, *args, **kwargs):
    return _ST_SUCCESS(editorialize_text(body), *args, **kwargs)

def ui_warning(body, *args, **kwargs):
    return _ST_WARNING(editorialize_text(body), *args, **kwargs)

def ui_error(body, *args, **kwargs):
    return _ST_ERROR(editorialize_text(body), *args, **kwargs)

def ui_caption(body, *args, **kwargs):
    return _ST_CAPTION(editorialize_text(body), *args, **kwargs)

def ui_selectbox(label, options, *args, **kwargs):
    kwargs.setdefault("format_func", lambda item: editorialize_text(item) if isinstance(item, str) else item)
    return _ST_SELECTBOX(editorialize_text(label), options, *args, **kwargs)

def ui_graphviz_chart(figure_or_dot, *args, **kwargs):
    if isinstance(figure_or_dot, str):
        figure_or_dot = editorialize_text(figure_or_dot)
    return _ST_GRAPHVIZ(figure_or_dot, *args, **kwargs)
# El núcleo exacto vive en lpf_exact.py. Si ese archivo no está junto a este
# (por ejemplo, si se subió sólo este .py al repo), se usa la copia espejo de
# abajo para que la app funcione igual. Mantener ambas versiones sincronizadas.
try:
    from lpf_exact import next_round_rank_bounds, safe_guarantee_line, safe_average_guarantee_points
except (ModuleNotFoundError, ImportError):
    _LPF_EXACT_ESPEJO = r'''
"""Núcleo exacto y auditable para las cuentas sensibles de la LPF.

No importa Streamlit ni usa azar. Las funciones de este módulo se pueden probar
por separado de la interfaz.
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable, Mapping, Sequence


def _points(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("pts", 0))
    return int(value)


def safe_guarantee_line(
    base: Mapping[str, object],
    remaining: Mapping[str, int],
    matches: Iterable[tuple[str, str]],
    team: str,
    rivals_above: int,
) -> int:
    """Línea superior segura para el puntaje del rival k-ésimo.

    Devuelve el mayor ``P`` para el que *todavía es posible* que al menos ``k``
    rivales terminen con ``P`` puntos. Por eso, terminar con ``P + 1`` garantiza
    quedar por encima de ese grupo (sin depender de desempates).

    La relajación descuenta correctamente los partidos entre los rivales elegidos:
    cada uno aparece dos veces en la suma de partidos restantes, pero reparte como
    máximo tres puntos en total. Se prueban todos los subconjuntos relevantes, no
    sólo los equipos con mayor techo. La prueba es necesaria, no suficiente; puede
    pedir algún punto de más, pero nunca declarar una garantía falsa.
    """
    rivals = [name for name in base if name != team]
    k = int(rivals_above)
    if k <= 0:
        return -1
    if len(rivals) < k:
        return -1

    pts = {name: _points(value) for name, value in base.items()}
    games_left = {name: max(0, int(remaining.get(name, 0))) for name in base}
    relevant_edges = [
        (a, b)
        for a, b in matches
        if a in base and b in base and a != team and b != team
    ]
    ceilings = {name: pts[name] + 3 * games_left[name] for name in rivals}

    def relaxed_feasible(target_points: int) -> bool:
        candidates = [name for name in rivals if ceilings[name] >= target_points]
        if len(candidates) < k:
            return False

        # Los candidatos más ajustados primero suelen descartar antes; en los casos
        # fáciles la función sale con el primer subconjunto factible.
        candidates.sort(key=lambda name: (ceilings[name], -pts[name]))
        for chosen in combinations(candidates, k):
            deficits = [max(0, target_points - pts[name]) for name in chosen]
            if any(deficit > 3 * games_left[name] for name, deficit in zip(chosen, deficits)):
                continue
            chosen_set = set(chosen)
            internal_edges = [
                (a, b) for a, b in relevant_edges if a in chosen_set and b in chosen_set
            ]
            degree = {name: 0 for name in chosen}
            for a, b in internal_edges:
                degree[a] += 1
                degree[b] += 1
            # Primero se asigna a cada club el máximo de sus partidos externos.
            # Lo que todavía necesita debe salir de los cruces internos, que
            # reparten como máximo tres puntos por partido entre ambos equipos.
            residual = []
            valid = True
            for name, deficit in zip(chosen, deficits):
                external_games = max(0, games_left[name] - degree[name])
                need_internal = max(0, deficit - 3 * external_games)
                if need_internal > 3 * degree[name]:
                    valid = False
                    break
                residual.append(need_internal)
            if valid and sum(residual) <= 3 * len(internal_edges):
                return True
        return False

    low = min(pts.values(), default=0)
    high = max(ceilings.values(), default=0)
    answer = low - 1
    while low <= high:
        middle = (low + high) // 2
        if relaxed_feasible(middle):
            answer = middle
            low = middle + 1
        else:
            high = middle - 1
    return answer


def safe_average_guarantee_points(
    totals: Mapping[str, int],
    played: Mapping[str, int],
    remaining: Mapping[str, int],
    matches: Iterable[tuple[str, str]],
    team: str,
    relegation_slots: int,
) -> int | None:
    """Puntos adicionales alcanzables que garantizan escapar de los promedios.

    La comparación se hace por cocientes finales y sin usar ``float``. Un empate
    de promedio se considera desfavorable: para estar garantizado el equipo debe
    dejar estrictamente por debajo a, como mínimo, ``relegation_slots`` rivales.

    La relajación prueba todos los subconjuntos de rivales que podrían terminar
    igual o por encima del promedio objetivo. Descuenta los cruces internos,
    porque dos clubes que se enfrentan no pueden sumar tres puntos cada uno.
    Como no fija qué partidos producen los puntos del equipo analizado, conserva
    como disponibles los puntos de sus rivales directos; por eso puede pedir algún
    punto de más, pero nunca declarar una salvación que aún dependa de resultados.
    """
    if team not in totals:
        return None
    names = [name for name in totals if name != team]
    k = max(0, int(relegation_slots))
    n = len(names) + 1
    if k <= 0:
        return 0
    if k >= n:
        return None

    total_points = {name: int(totals.get(name, 0)) for name in totals}
    games_played = {name: max(0, int(played.get(name, 0))) for name in totals}
    games_left = {name: max(0, int(remaining.get(name, 0))) for name in totals}
    final_games = {name: games_played[name] + games_left[name] for name in totals}
    if final_games.get(team, 0) <= 0:
        return None

    # Si al menos n-k rivales pueden terminar igual o por encima, el equipo
    # todavía podría quedar entre los k peores (los empates se toman adversos).
    rivals_needed = n - k
    relevant_edges = [
        (a, b)
        for a, b in matches
        if a in totals and b in totals and a != team and b != team
    ]

    def minimum_add_to_reach(name: str, target_num: int, target_den: int) -> int:
        den = final_games.get(name, 0)
        if den <= 0:
            return 10**9
        numerator = target_num * den - total_points[name] * target_den
        return max(0, -(-numerator // target_den))

    def rivals_can_keep_team_in_bottom(target_add: int) -> bool:
        target_num = total_points[team] + int(target_add)
        target_den = final_games[team]
        deficits = {
            name: minimum_add_to_reach(name, target_num, target_den)
            for name in names
        }
        candidates = [
            name for name in names
            if deficits[name] <= 3 * games_left[name]
        ]
        if len(candidates) < rivals_needed:
            return False
        candidates.sort(key=lambda name: (3 * games_left[name] - deficits[name], total_points[name]))

        for chosen in combinations(candidates, rivals_needed):
            chosen_set = set(chosen)
            internal_edges = [
                (a, b) for a, b in relevant_edges if a in chosen_set and b in chosen_set
            ]
            degree = {name: 0 for name in chosen}
            for a, b in internal_edges:
                degree[a] += 1
                degree[b] += 1
            residual = []
            valid = True
            for name in chosen:
                external_games = max(0, games_left[name] - degree[name])
                need_internal = max(0, deficits[name] - 3 * external_games)
                if need_internal > 3 * degree[name]:
                    valid = False
                    break
                residual.append(need_internal)
            if valid and sum(residual) <= 3 * len(internal_edges):
                return True
        return False

    r = games_left[team]
    reachable = sorted({3 * wins + draws for wins in range(r + 1) for draws in range(r - wins + 1)})
    for added in reachable:
        if not rivals_can_keep_team_in_bottom(added):
            return added
    return None


def next_round_rank_bounds(
    target: str,
    table: Mapping[str, Mapping[str, int]],
    games: Sequence[tuple[str, str]],
) -> tuple[int, int] | None:
    """Mejor y peor puesto posible tras una fecha, sin fingir un desempate.

    La frontera se calcula por puntos. En el mejor caso, un empate en puntos puede
    favorecer al equipo; en el peor, puede perjudicarlo. Ese intervalo incluye los
    marcadores y los criterios reglamentarios todavía desconocidos (fair play o
    sorteo). Dos rivales que se enfrentan se evalúan juntos, así que no se les
    adjudican simultáneamente tres puntos.
    """
    if target not in table:
        return None

    current = {name: int(stats.get("pts", 0)) for name, stats in table.items()}
    target_best = current[target] + 3
    target_worst = current[target]
    best_above = 0
    worst_above = 0
    seen = {target}

    for local, visitor in games:
        if target in (local, visitor):
            opponent = visitor if local == target else local
            if opponent in current:
                seen.add(opponent)
                best_above += int(current[opponent] > target_best)
                worst_above += int(current[opponent] + 3 >= target_worst)
            continue

        in_local = local in current
        in_visitor = visitor in current
        if in_local and in_visitor:
            seen.update((local, visitor))
            outcomes = ((3, 0), (1, 1), (0, 3))
            best_above += min(
                int(current[local] + dl > target_best)
                + int(current[visitor] + dv > target_best)
                for dl, dv in outcomes
            )
            worst_above += max(
                int(current[local] + dl >= target_worst)
                + int(current[visitor] + dv >= target_worst)
                for dl, dv in outcomes
            )
        elif in_local or in_visitor:
            rival = local if in_local else visitor
            seen.add(rival)
            best_above += min(int(current[rival] + add > target_best) for add in (3, 1, 0))
            worst_above += max(int(current[rival] + add >= target_worst) for add in (3, 1, 0))

    for rival in current:
        if rival not in seen:
            best_above += int(current[rival] > target_best)
            worst_above += int(current[rival] >= target_worst)

    return best_above + 1, worst_above + 1
'''
    _ns_exact = {}
    exec(compile(_LPF_EXACT_ESPEJO, 'lpf_exact_espejo.py', 'exec'), _ns_exact)
    next_round_rank_bounds = _ns_exact['next_round_rank_bounds']
    safe_guarantee_line = _ns_exact['safe_guarantee_line']

# ─── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=f"⚽ Calculadora del Fútbol Argentino · v{__version__}",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

ui_markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    padding: 2rem 2rem 1.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    border-left: 4px solid #e94560;
}
.main-header h1 { color: white; font-size: 2rem; font-weight: 700; margin: 0; }
.main-header p  { color: #a0aec0; margin: 0.3rem 0 0; font-size: 0.95rem; }
div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# ─── CONSTANTES CONFIGURABLES ────────────────────────────────────────────────────
PRESETS = {
    "LPF 2026 — DG, GF, mano a mano, fair play (Reglamento art. 16)": list(DEFAULT_CRITERIOS),
    "Olímpico — mano a mano primero (FIFA, Euro, La Liga, Serie A)": ["h2h_pts","h2h_dg","h2h_gf","dg","gf"],
    "Diferencia de gol primero (Premier, Bundesliga, Champions fase liga)": ["dg","gf"],
    "Solo puntos (sin desempate fino)": [],
}

if "CRITERIOS"          not in st.session_state: st.session_state.CRITERIOS          = list(DEFAULT_CRITERIOS)
if "DIRECTO"            not in st.session_state: st.session_state.DIRECTO            = 2
if "MEJORES_TERCEROS"   not in st.session_state: st.session_state.MEJORES_TERCEROS   = 0
if "CAMPEON"            not in st.session_state: st.session_state.CAMPEON            = "campeón"
if "ESTADO"             not in st.session_state: st.session_state.ESTADO             = {}
if "LPF_SOURCE_META"    not in st.session_state: st.session_state.LPF_SOURCE_META    = {
    "source_name": "Estado actual de Streamlit",
    "source_updated_at": None,
    "data_as_of": None,
    "sources": [],
    "warnings": ["La fuente actual no informó todavía un timestamp de actualización."],
}
if "texto_torneo_cache" not in st.session_state: st.session_state.texto_torneo_cache = ""
if "ZONAS"              not in st.session_state: st.session_state.ZONAS              = []
if "ZONAS_TXT"          not in st.session_state: st.session_state.ZONAS_TXT          = ""

# Copa Argentina 2026 · control de equipos todavía vivos.
# La foto vieja de octavos se conserva sólo para migrar session_state de releases
# anteriores. La foto canónica vigente es la de cuartos confirmada el 08/09/2026.
COPA_ARGENTINA_FIXTURE_OFICIAL = "https://www.copaargentina.org/es/fixture.html"
COPA_ARGENTINA_CUARTOS_OFICIAL = "https://www.copaargentina.org/es/news/11971_Diez-datos-en-la-previa-a-los-Cuartos-de-Final.html"
COPA_ARGENTINA_CUADRO_ESPN = "https://www.espn.com.ar/futbol/argentina/nota/_/id/16215014/copa-argentina-2026-asi-esta-el-cuadro-llave-fase-final"
COPA_ARGENTINA_OCTAVOS_2026 = [
    "Banfield", "Ferrocarril Midland", "Atlético Tucumán", "Independiente",
    "Platense", "Instituto", "Estudiantes de La Plata", "Barracas Central",
    "Deportivo Riestra", "Gimnasia La Plata", "Racing", "Belgrano",
    "Boca Juniors", "Vélez Sarsfield", "Aldosivi", "Independiente Rivadavia",
]
COPA_ARGENTINA_CUARTOS_2026 = [
    "Deportivo Riestra", "Banfield", "Racing", "Boca Juniors",
    "Atlético Tucumán", "Independiente Rivadavia",
    "Estudiantes de La Plata", "Platense",
]
COPA_ARGENTINA_CUARTOS_UPDATED = "08/09/2026 · cuadro de cuartos completo"
COPA_ARGENTINA_CUARTOS_SOURCE = "Sitio oficial de Copa Argentina · previa de Cuartos de Final"

_old_copa_default = list(COPA_ARGENTINA_OCTAVOS_2026)
_old_copa_text = "\n".join(_old_copa_default)
if "LPF_COPA_ARG_VIVOS" not in st.session_state:
    st.session_state.LPF_COPA_ARG_VIVOS = list(COPA_ARGENTINA_CUARTOS_2026)
else:
    # Migración automática: un usuario que tenía abierta la app antes del cambio
    # puede conservar session_state aun después del redeploy. Sólo reemplazamos la
    # foto histórica exacta de octavos; una lista editada manualmente se respeta.
    _saved_copa = list(st.session_state.get("LPF_COPA_ARG_VIVOS") or [])
    _saved_updated = str(st.session_state.get("LPF_COPA_ARG_UPDATED") or "")
    if _saved_copa == _old_copa_default or _saved_updated.startswith("18/07/2026"):
        st.session_state.LPF_COPA_ARG_VIVOS = list(COPA_ARGENTINA_CUARTOS_2026)
        st.session_state.LPF_COPA_ARG_UPDATED = COPA_ARGENTINA_CUARTOS_UPDATED
        st.session_state.LPF_COPA_ARG_SOURCE = COPA_ARGENTINA_CUARTOS_SOURCE
if "LPF_COPA_ARG_UPDATED" not in st.session_state:
    st.session_state.LPF_COPA_ARG_UPDATED = COPA_ARGENTINA_CUARTOS_UPDATED
if "LPF_COPA_ARG_SOURCE" not in st.session_state:
    st.session_state.LPF_COPA_ARG_SOURCE = COPA_ARGENTINA_CUARTOS_SOURCE
if "LPF_COPA_ARG_REEMPLAZO" not in st.session_state:
    st.session_state.LPF_COPA_ARG_REEMPLAZO = ""
if "lpf_copa_arg_alive_txt" not in st.session_state:
    st.session_state.lpf_copa_arg_alive_txt = "\n".join(st.session_state.LPF_COPA_ARG_VIVOS)
elif str(st.session_state.get("lpf_copa_arg_alive_txt") or "").strip() == _old_copa_text.strip():
    st.session_state.lpf_copa_arg_alive_txt = "\n".join(COPA_ARGENTINA_CUARTOS_2026)

def _secret(k, default=""):
    try:
        return st.secrets.get(k, default)
    except Exception:
        return default

def DIRECTO():          return st.session_state.DIRECTO
def MEJORES_TERCEROS(): return st.session_state.MEJORES_TERCEROS
def CAMPEON():          return st.session_state.CAMPEON
def CRITERIOS():        return st.session_state.CRITERIOS

# ─── MOTOR ──────────────────────────────────────────────────────────────────────
def fixture_completo(equipos): return list(combinations(equipos, 2))



def posiciones(equipos, partidos, fair_play=None, ranking=None, criterios=None):
    """Adaptador Streamlit: inyecta los criterios de sesión al motor puro."""
    return _standings_posiciones(
        equipos, partidos, fair_play=fair_play, ranking=ranking,
        criterios=CRITERIOS() if criterios is None else criterios,
    )


def tabla(equipos, partidos, fair_play=None, ranking=None, criterios=None):
    """Adaptador Streamlit: inyecta los criterios de sesión al motor puro."""
    return _standings_tabla(
        equipos, partidos, fair_play=fair_play, ranking=ranking,
        criterios=CRITERIOS() if criterios is None else criterios,
    )

def simular(equipos, jugados, pendientes, resultados, fair_play=None, ranking=None):
    part = list(jugados) + [(l, v, gl, gv) for (l, v), (gl, gv) in zip(pendientes, resultados)]
    return tabla(equipos, part, fair_play, ranking)

def texto_resultados(pend, res):
    return " | ".join(f"{l} {gl}-{gv} {v}" for (l, v), (gl, gv) in zip(pend, res))

def elegir_max_goles(n_pend, tope=300000):
    for mg in (5, 4, 3, 2, 1):
        if (mg + 1) ** (2 * n_pend) <= tope: return mg
    return 1

def todos_los_escenarios(equipos, jugados, pendientes, max_goles=None, fair_play=None, ranking=None):
    if max_goles is None: max_goles = elegir_max_goles(len(pendientes))
    posib = list(product(range(max_goles + 1), repeat=2)); filas = []
    for res in product(posib, repeat=len(pendientes)):
        t = simular(equipos, jugados, pendientes, res, fair_play, ranking)
        fila = {"Resultados": texto_resultados(pendientes, res)}
        for i, ((l, v), (gl, gv)) in enumerate(zip(pendientes, res), 1):
            fila[f"P{i}_local"] = l; fila[f"P{i}_vis"] = v; fila[f"P{i}_gl"] = gl; fila[f"P{i}_gv"] = gv
        for _, r in t.iterrows():
            e = r["Equipo"]; fila[f"Pos {e}"] = r["Pos"]; fila[f"PTS {e}"] = r["PTS"]
            fila[f"DG {e}"] = r["DG"]; fila[f"GF {e}"] = r["GF"]
        filas.append(fila)
    return pd.DataFrame(filas)

# ─── ANÁLISIS ───────────────────────────────────────────────────────────────────
def _pd_de(equipo, pend): return [(i, l, v) for i, (l, v) in enumerate(pend, 1) if equipo in (l, v)]

def _res_propio(row, equipo, pend):
    et = []
    for i, l, v in _pd_de(equipo, pend):
        gl, gv = row[f"P{i}_gl"], row[f"P{i}_gv"]
        gf, gc = (gl, gv) if l == equipo else (gv, gl); riv = v if l == equipo else l
        et.append(f"le gana a {riv}" if gf > gc else (f"pierde con {riv}" if gf < gc else f"empata con {riv}"))
    return " y ".join(et)

def _res_otros(row, equipo, pend):
    et = []; mios = {i for i, _, _ in _pd_de(equipo, pend)}
    for i, (l, v) in enumerate(pend, 1):
        if i in mios: continue
        gl, gv = row[f"P{i}_gl"], row[f"P{i}_gv"]
        et.append(f"gana {l}" if gl > gv else (f"gana {v}" if gl < gv else f"empatan {l} y {v}"))
    return " y ".join(et) if et else "(no hay otros partidos)"

def _combo(row, pend):
    parts = []
    for i, (l, v) in enumerate(pend, 1):
        gl, gv = row[f"P{i}_gl"], row[f"P{i}_gv"]
        parts.append(f"gana {l}" if gl > gv else (f"gana {v}" if gl < gv else f"empatan {l} y {v}"))
    return " · ".join(parts)

def _margen_pend(eq, pend, row):
    m = 0; opp = None
    for i, l, v in _pd_de(eq, pend):
        gl, gv = row[f"P{i}_gl"], row[f"P{i}_gv"]
        m += (gl - gv) if l == eq else (gv - gl)
        opp = v if l == eq else l
    return m, opp

def _gol(k): return f"{abs(k)} gol" + ("es" if abs(k) != 1 else "")

def _detalle_gol(g2, equipo, pend):
    """Describe exactamente cuántos goles necesita para superar a un rival en desempate."""
    fila = g2.iloc[0]; Pe = fila[f"PTS {equipo}"]
    teams = [c[4:] for c in g2.columns if c.startswith("PTS ")]
    rivales = [t for t in teams if t != equipo and g2[f"PTS {t}"].iloc[0] == Pe]
    if len(rivales) != 1:
        extra = f" (igualado en {int(Pe)} pts con {', '.join(rivales)})" if rivales else ""
        return f"depende de la diferencia de gol{extra}"
    riv = rivales[0]
    me0, opp = _margen_pend(equipo, pend, fila); mr0, _ = _margen_pend(riv, pend, fila)
    de = int(fila[f"DG {equipo}"]) - me0; dr = int(fila[f"DG {riv}"]) - mr0
    gap = dr - de; K = gap + 1; riv_pend = bool(_pd_de(riv, pend))
    solo_e = len(_pd_de(equipo, pend)) == 1; solo_r = len(_pd_de(riv, pend)) == 1
    if me0 > 0 and solo_e and solo_r:
        if K >= 2:
            return (f"necesita ganarle a {opp} por al menos {_gol(K)} más que {riv}; "
                    f"si gana por {_gol(K-1)} más, igualan en diferencia de gol y se define por los goles a favor")
        if K == 1:
            return (f"necesita ganarle a {opp} por al menos 1 gol más que {riv}; "
                    f"si ganan por la misma diferencia, igualan en DG y se define por los goles a favor")
        return (f"le alcanza con que su diferencia de gol final supere a la de {riv} (parte {_gol(-gap)} arriba); "
                f"si {riv} la empareja, se define por los goles a favor")
    if me0 > 0 and solo_e and not riv_pend and K >= 1:
        cola = (f"con {_gol(K-1)} igualan en DG y define los goles a favor" if K - 1 >= 1
                else "si igualan la DG, define los goles a favor")
        return f"necesita ganar por al menos {_gol(K)} para superar la diferencia de gol de {riv}; {cola}"
    return (f"necesita terminar con mejor diferencia de gol que {riv} "
            f"(hoy {equipo} {de:+d} y {riv} {dr:+d}); si igualan, se define por los goles a favor")

def situacion(equipo, esc, directo=None):
    d = DIRECTO() if directo is None else directo
    pos = esc[f"Pos {equipo}"]
    vivo = 3 if MEJORES_TERCEROS() > 0 else d
    return {"mejor": int(pos.min()), "peor": int(pos.max()), "total": len(esc),
            "n1": int((pos == 1).sum()), "ndir": int((pos <= d).sum()),
            "ntercero": int((pos == 3).sum()), "ntop3": int((pos <= 3).sum()),
            "ya_1": bool((pos == 1).all()), "ya_directo": bool((pos <= d).all()),
            "puede_1": bool((pos == 1).any()), "puede_directo": bool((pos <= d).any()),
            "puede_tercero": bool((pos == 3).any()), "asegura_vivo": bool((pos <= vivo).all()),
            "eliminado": bool((pos > vivo).all()), "vivo": vivo, "directo": d}

def que_necesita_texto(equipo, esc, pend, objetivo="directo", directo=None, n=2):
    d = DIRECTO() if directo is None else directo
    pos = esc[f"Pos {equipo}"]
    T = sum(1 for c in esc.columns if c.startswith("Pos "))
    if objetivo in ("primero", "campeon"):
        ok = (pos == 1); verbo = f"es {CAMPEON()}"
    elif objetivo == "top3":
        ok = (pos <= 3); verbo = "queda 3º o mejor"
    elif objetivo == "tercero":
        ok = (pos == 3); verbo = "queda 3º"
    elif objetivo == "top":
        ok = (pos <= n); verbo = f"entra al top {n}"
    elif objetivo == "exacto":
        ok = (pos == n); verbo = f"queda {n}º"
    elif objetivo == "descenso":
        corte = T - n; ok = (pos <= corte); verbo = "se salva"
    else:
        ok = (pos <= d); verbo = "clasifica"
    df = esc.copy()
    df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    df["_o"] = df.apply(lambda r: _res_otros(r, equipo, pend), axis=1)
    df["_ok"] = ok.values
    lineas = []
    for prop, g in sorted(df.groupby("_p"), key=lambda kv: -kv[1]["_ok"].mean()):
        m, k = len(g), int(g["_ok"].sum())
        cab = "✅ SEGURO" if k == m else ("❌ IMPOSIBLE" if k == 0 else "⚠️ DEPENDE")
        lineas.append(f"**• Si {equipo} {prop}:** {cab}")
        if 0 < k < m:
            for otros, g2 in sorted(g.groupby("_o"), key=lambda kv: -kv[1]["_ok"].mean()):
                n2, k2 = len(g2), int(g2["_ok"].sum())
                if k2 == n2:
                    e = f"→ {verbo} ✅"
                elif k2 == 0:
                    e = f"→ no {verbo} ❌"
                else:
                    detalle = _detalle_gol(g2, equipo, pend)
                    e = f"→ {detalle} ⚠️"
                lineas.append(f"&nbsp;&nbsp;&nbsp;&nbsp;· y {otros}: {e}")
    return "\n\n".join(lineas)

def apartado_terceros_texto(equipo, esc, pend):
    if MEJORES_TERCEROS() <= 0:
        return ""
    pos = esc[f"Pos {equipo}"]; n3 = int((pos == 3).sum())
    lineas = ["**— MEJOR TERCERO —**"]
    if n3 == 0:
        lineas.append(f"{equipo} no termina 3º en ningún escenario.")
        return "\n\n".join(lineas)
    lineas.append(f"⚠️ Quedar 3º **NO** asegura clasificar: entran los **{MEJORES_TERCEROS()} mejores terceros** del torneo, "
                  f"así que depende de lo que pase en los otros grupos.")
    lineas.append(f"{equipo} termina 3º en **{n3}/{len(esc)}** escenarios.")
    lineas.append(que_necesita_texto(equipo, esc, pend, "tercero"))
    return "\n\n".join(lineas)

def _cab_completo(g, d, hay3):
    pmin, pmax = int(g["_pos"].min()), int(g["_pos"].max())
    if pmax <= d:            return "✅ CLASIFICA DIRECTO"
    if pmin <= d:            return "⚠️ DEPENDE (puede entrar directo)"
    if hay3 and pmax <= 3:   return "⚠️ A LO SUMO 3º (depende de otros grupos)"
    if hay3 and pmin <= 3:   return "⚠️ DEPENDE (3º o afuera)"
    return "❌ QUEDA AFUERA"

def _meaning_pos(equipo, g2, pend, d, hay3):
    pmin, pmax = int(g2["_pos"].min()), int(g2["_pos"].max())
    rng = f"{pmin}º" if pmin == pmax else f"{pmin}º-{pmax}º"
    if pmax <= d:
        return f"→ {rng} · clasifica directo ✅"
    if pmin <= d:
        cola = "si no, 3º (depende de otros grupos)" if hay3 else "si no, afuera"
        return f"→ {rng} · directo según diferencia de gol; {cola} ⚠️"
    if hay3 and pmax <= 3:
        return "→ 3º · entra solo si es de los mejores terceros (depende de otros grupos) ⚠️"
    if hay3 and pmin <= 3:
        return "→ 3º o peor · si es 3º depende de otros grupos; si no, afuera ⚠️"
    return f"→ {rng} · afuera ❌"

def que_necesita_completo_texto(equipo, esc, pend):
    """Árbol único: para cada resultado propio muestra el puesto final (directo / 3º que depende / afuera)."""
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    df = esc.copy()
    df["_pos"] = esc[f"Pos {equipo}"].values
    df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    df["_o"] = df.apply(lambda r: _res_otros(r, equipo, pend), axis=1)
    lineas = []
    for prop, g in sorted(df.groupby("_p"), key=lambda kv: kv[1]["_pos"].mean()):
        lineas.append(f"**• Si {equipo} {prop}:** {_cab_completo(g, d, hay3)}")
        uniforme = int(g["_pos"].min()) == int(g["_pos"].max())
        grupos_otros = sorted(g.groupby("_o"), key=lambda kv: kv[1]["_pos"].mean())
        if not uniforme:
            if len(grupos_otros) > 1:
                for otros, g2 in grupos_otros:
                    lineas.append(f"&nbsp;&nbsp;&nbsp;&nbsp;· y {otros}: {_meaning_pos(equipo, g2, pend, d, hay3)}")
            else:
                lineas.append(f"&nbsp;&nbsp;&nbsp;&nbsp;{_meaning_pos(equipo, g, pend, d, hay3)}")
    return "\n\n".join(lineas)

def _mask_gana_todos(esc, equipo, pend):
    mask = pd.Series(True, index=esc.index)
    for i, l, v in _pd_de(equipo, pend):
        gl, gv = esc[f"P{i}_gl"], esc[f"P{i}_gv"]
        mask &= (gl > gv) if l == equipo else (gv > gl)
    return mask

def en_sus_manos(equipo, esc, pend):
    """Devuelve (categoría, frase) sobre si el equipo depende de sí mismo."""
    s = situacion(equipo, esc); d = DIRECTO()
    if s["ya_directo"]: return ("ya", "ya está clasificado directo, pase lo que pase")
    if s["eliminado"]: return ("out", "ya no puede clasificar en ningún escenario")
    own = _pd_de(equipo, pend)
    if not own:
        return ("ayuda", "ya jugó todos sus partidos: su suerte depende solo de los otros")
    mask = _mask_gana_todos(esc, equipo, pend)
    pos = esc[f"Pos {equipo}"]
    n = "su partido" if len(own) == 1 else "todos sus partidos"
    peor = int(pos[mask].max())
    if peor <= d:
        return ("manos", f"lo tiene en sus manos: ganando {n} clasifica directo, sin depender de nadie")
    mejor = int(pos[mask].min())
    if MEJORES_TERCEROS() > 0 and mejor <= 3:
        return ("ayuda", f"aun ganando {n} puede no entrar directo; quedaría como posible mejor 3º (depende de otros grupos)")
    return ("ayuda", f"aun ganando {n} necesita que se den otros resultados")

def en_sus_manos_texto(eqs, jug, esc, pend):
    icon = {"manos": "🟢", "ayuda": "🟡", "ya": "✅", "out": "🔴"}
    lineas = ["**¿Quién depende de sí mismo?**"]
    for _, r in tabla(eqs, jug).iterrows():
        e = r["Equipo"]; cat, msg = en_sus_manos(e, esc, pend)
        lineas.append(f"{icon.get(cat, '•')} **{e}** — {msg}")
    return "\n\n".join(lineas)

def si_terminara_hoy_texto(eqs, jug, pend=None):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    lineas = ["**Si la fase terminara hoy (con la tabla actual):**"]
    for _, r in tabla(eqs, jug).iterrows():
        p = int(r["Pos"])
        if p <= d: est = "✅ clasifica directo"
        elif p == 3 and hay3: est = "🔵 3º — pelearía un lugar entre los mejores terceros"
        else: est = "🔴 quedaría afuera"
        lineas.append(f"{p}º **{r['Equipo']}** · {int(r['PTS'])} pts · {int(r.get('PJ', 0))} PJ (DG {int(r['DG']):+d}) — {est}")
    if pend:
        lineas.append(f"_Todavía falta(n) {len(pend)} partido(s); esto puede cambiar._")
    return "\n\n".join(lineas)

_ZCOL = {"campeon": "#1b5e20", "libertadores": "#1b5e20", "sudamericana": "#00838f",
         "clasifica": "#1b5e20", "directo": "#1b5e20", "ascenso": "#1b5e20",
         "repechaje": "#f9a825", "reduccion": "#ef6c00", "promocion": "#ef6c00",
         "playoff": "#f9a825", "descenso": "#b71c1c", "desciende": "#b71c1c"}

from lpf_text import _zlow, _norm_txt, detectar_equipo, _fmt_num_es
from lpf_intents import _parse_kw
from lpf_clubs import LPF_CLUBES, _norm_club, canon_club, canon_base
from lpf_parsers import _parse_team_list, parse_promedios, parse_tabla_fixture, parse_tabla_anual, parse_promedios_tabla
from lpf_data_2026 import LPF_FIXTURE, ZONA_A_LPF_2026, ZONA_B_LPF_2026, TABLA_ANUAL_LPF_2026
from lpf_derive import _asignar_nombres, derivar_apertura, _lpf_infer_missing_results
_LPF_PROM_HISTORY_VERSION = "2026-previas-fijas-v2"
from lpf_reconcile import (
    _known_lpf_zone_rosters, _validate_base_rows, _validate_lpf_tables,
    _lpf_normalize_result_identity, _merge_lpf_results,
    _lpf_complete_results_for_zones,
)
from lpf_loading import (
    normalize_results_for_zones, prepare_automatic_update, prepare_offline_load,
)
from lpf_data_provider import CurrentProvider, provider_payload as _lpf_provider_payload
from lpf_http import (
    fetch_espn_json, fetch_espn_scoreboard_window, fetch_futbolargentino_results_pages,
    fetch_html, fetch_html_pages, fetch_url_text,
)
from lpf_provider_adapters import (
    parse_espn_lpf_zones_payload, parse_espn_scoreboard_payloads,
    parse_espn_table_payload, parse_futbolargentino_annual_html,
    parse_futbolargentino_zones_html,
)
from competition_html_adapters import parse_cross_table_html, parse_standings_table_html
from lpf_table_selection import select_lpf_tables
from lpf_table_backup import build_table_backup, load_table_backup, write_table_backup

def _color_zona(nombre):
    k = _zlow(nombre)
    for key, c in _ZCOL.items():
        if key in k:
            return c
    return _C_NEU

def parse_zonas(text):
    z = []
    for ln in str(text).splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            hasta = int(parts[0])
        except ValueError:
            continue
        nombre = parts[1].strip()
        z.append((hasta, nombre, _color_zona(nombre)))
    z.sort(key=lambda x: x[0])
    return z

def zona_de(pos, zonas):
    for hasta, nombre, color in zonas:
        if pos <= hasta:
            return nombre, color
    return "—", _C_NEU

def tabla_zonas_texto(eqs, jug, zonas):
    return tabla_zonas_texto_df(tabla(eqs, jug), zonas)

def tabla_zonas_texto_df(orden, zonas):
    L = ["**Si terminara hoy (por zonas):**"]; cur = object()
    for _, r in orden.iterrows():
        p = int(r["Pos"]); nombre, _ = zona_de(p, zonas)
        if nombre != cur:
            L.append(f"\n__{nombre}__"); cur = nombre
        L.append(f"{p}º **{r['Equipo']}** · {int(r['PTS'])} pts · {int(r.get('PJ', 0))} PJ (DG {int(r['DG']):+d})")
    return "\n\n".join(L)

def spec_zonas(eqs, jug, zonas):
    return spec_zonas_df(tabla(eqs, jug), zonas)

def spec_zonas_df(orden, zonas):
    if not zonas:
        return None
    rows, cells, seen = [], [], []
    for _, r in orden.iterrows():
        p = int(r["Pos"]); nombre, color = zona_de(p, zonas)
        rows.append(f"{p}º {r['Equipo']}")
        cells.append([(f"{int(r['PTS'])}", color), (f"{int(r.get('PJ', 0))}", color), (f"{int(r['DG']):+d}", color), (nombre, color)])
        if nombre not in [s[1] for s in seen]:
            seen.append((color, nombre))
    return {"titulo": "Tabla por zonas (hoy)", "col_headers": ["Pts", "PJ", "DG", "Zona"],
            "row_headers": rows, "cells": cells, "corner": "", "leyenda": seen,
            "footer": "Coloreado por zona según la posición actual."}

# ─── MODO LIGA POR TABLA (pegás tabla + «faltan N fechas», sin resultados) ──────

def liga_restantes(equipos, pend, gleft):
    if pend:
        r = {e: 0 for e in equipos}
        for l, v in pend:
            if l in r: r[l] += 1
            if v in r: r[v] += 1
        return r
    return {e: (gleft or 0) for e in equipos}


def liga_maxmin_df(base, rest):
    rows = [{"Equipo": e, "PJ": d.get("pj", 0), "PTS": d["pts"], "Restan": rest.get(e, 0),
             "PTS máx": d["pts"] + 3 * rest.get(e, 0)} for e, d in base.items()]
    return pd.DataFrame(rows).sort_values(["PTS", "PTS máx"], ascending=False).reset_index(drop=True)

def liga_aseg_df(base, rest, n):
    pts = {e: base[e]["pts"] for e in base}; pmax = {e: pts[e] + 3 * rest.get(e, 0) for e in base}
    rows = []
    for e in base:
        arriba = sum(1 for x in base if x != e and pmax[x] >= pts[e])
        inalc = sum(1 for x in base if x != e and pts[x] > pmax[e])
        estado = "🟢 asegurado" if arriba < n else ("🔴 sin chances" if inalc >= n else "🟡 depende")
        rows.append({"Equipo": e, "PTS": pts[e], "PTS máx": pmax[e], f"Top {n}": estado})
    return pd.DataFrame(rows).sort_values("PTS", ascending=False).reset_index(drop=True)

def zona_target(zonas, texto):
    """Devuelve (k_puesto, nombre) para «entrar a X» o «no descender»."""
    if not zonas:
        return None
    t = _zlow(texto)
    if any(w in t for w in ("no desc", "no baj", "salv", "permanec", "mantener la categoria", "no se va")):
        rele = [i for i, (h, n, c) in enumerate(zonas) if c == "#b71c1c"]
        if rele:
            idx = rele[0]
            k = zonas[idx - 1][0] if idx > 0 else zonas[idx][0] - 1
            return max(1, k), "no descender"
    for h, n, c in zonas:
        if _zlow(n) and _zlow(n) in t:
            return h, n
    return None


def liga_duelos_texto(base, rest, pend, zonas):
    if not pend:
        return ("Para los cruces entre rivales directos necesito el **fixture** (los partidos que faltan), no solo «faltan N fechas». "
                "Pegalos como «River vs Boca», uno por línea, y te marco los mano a mano por cada zona.")
    if not zonas:
        return "Configurá las zonas en «🎨 Zonas con nombre» (panel) y te detecto los cruces entre rivales directos."
    L = ["**Cruces entre rivales directos** (partidos que faltan entre dos que pelean la misma zona):"]; any_ = False
    for h, nombre, c in zonas:
        pelea = {e for e in base if _liga_in_out(e, base, rest, h) == "pelea"}
        duelos = [(a, b) for (a, b) in pend if a in pelea and b in pelea]
        if duelos:
            any_ = True; L.append(f"\n__{nombre}__")
            for a, b in duelos:
                L.append(f"• {a} vs {b}")
    if not any_:
        return "No encontré cruces directos entre equipos que peleen la misma zona en el fixture cargado."
    L.append("\n_Estos son los partidos donde un rival le saca puntos directos al otro: valen doble en la pelea._")
    return "\n\n".join(L)

def _opciones_liga(equipo, base, rest, pend, k, nombre, linea=None):
    """Caminos alrededor del total seguro: rivales del corte y mano a mano.

    El total es seguro pero puede pedir puntos de más; el mínimo que asegura se
    publica por separado cuando el motor exacto está disponible.
    """
    if not pend:
        return []
    pts = {e: base[e]["pts"] for e in base}
    pmax = {e: pts[e] + 3 * rest.get(e, 0) for e in base}
    if linea is None:
        linea = _linea_garantia(base, rest, pend, equipo, k)
    F = linea + 1
    otros = sorted(((x, pmax[x]) for x in base if x != equipo), key=lambda kv: -kv[1])
    L = []
    # (1) rivales al borde del corte (los que realmente disputan el puesto)
    lo = max(0, k - 3); hi = min(len(otros), k + 2)
    borde = otros[lo:hi]
    if borde:
        lst = ", ".join(f"{x} (máx {m})" for x, m in borde)
        L.append(f"📊 **El corte de {nombre} lo disputan:** {lst}. Para asegurar sin depender tenés que quedar "
                 f"por encima de suficientes de ellos; con menos que el total seguro también podés entrar si se quedan cortos "
                 f"(mirá «chances de {equipo}» o «qué le conviene a {equipo}»).")
    # (2) mano a mano: detalle si son pocos, resumen si son muchos
    enpelea = {x for x in base if x != equipo and _liga_in_out(x, base, rest, k) == "pelea"}
    h2h = [(b if a == equipo else a) for (a, b) in pend if equipo in (a, b) and (b if a == equipo else a) in enpelea]
    if h2h:
        rest2 = dict(rest)
        for r in h2h:
            rest2[r] = max(0, rest2.get(r, 0) - 1)
        F2 = _linea_garantia(base, rest2, pend, equipo, k) + 1
        if len(h2h) <= 5 and F2 < F:
            L.append(f"🔑 **Mano a mano:** si les ganás a {', '.join(h2h)}, el total seguro baja de {F} a **{F2}** "
                     f"(sumás vos y ellos no).")
        else:
            L.append(f"🔑 **Mano a mano:** te quedan {len(h2h)} cruces con rivales directos; ganarlos puede bajar el total seguro "
                     f"y los deja sin sumar. Pesa más en las últimas fechas, cuando la tabla se separa.")
    return L

def liga_que_necesita_texto(equipo, base, rest, zonas, texto, pend=None):
    pts = {e: base[e]["pts"] for e in base}
    orden = liga_tabla_df(base)
    pos = int(orden.set_index("Equipo").loc[equipo, "Pos"])
    tgt = zona_target(zonas, texto)
    if not tgt:
        nombres = ", ".join(n for _, n, _ in zonas) if zonas else "—"
        return (
            f"¿Para qué zona? Configurá las zonas en el panel y preguntá, por ej., "
            f"«qué necesita {equipo} para Libertadores». Zonas activas: {nombres}."
        )
    k, nombre = tgt
    gx = int(rest.get(equipo, 0))
    meta = "no descender" if nombre == "no descender" else f"entrar a {nombre}"
    calc = piso_por_corte(
        base, rest, list(pend or []), equipo, k,
        clave="liga", nombre=nombre,
    )
    L = [
        f"**¿Qué necesita {equipo} para {meta}?**",
        f"Está {pos}º con **{pts[equipo]} pts** y le quedan {gx} partidos ({3 * gx} en juego).",
    ]
    if calc.estado == "in":
        L.append(f"✅ Ya está adentro de **{nombre}** pase lo que pase.")
    elif calc.estado == "out":
        L.append(f"❌ Ya no puede entrar a **{nombre}** (matemáticamente quedó afuera).")
    elif _piso_garantia_exacta(calc) is not None:
        falta = max(0, _piso_garantia_exacta(calc) - pts[equipo])
        L.append(
            f"🔒 **Mínimo que asegura: {_piso_garantia_exacta(calc)} puntos.** Es el menor total comprobado con el que "
            f"asegura {nombre} sin depender de otros resultados ni de desempates. Le faltan **{falta} puntos**."
        )
    elif _piso_referencia_conservadora(calc) is not None:
        ref = int(_piso_referencia_conservadora(calc))
        falta = max(0, ref - pts[equipo])
        if ref <= calc.techo:
            L.append(
                f"📌 **Total seguro: {ref} puntos.** Si llega a ese total, asegura {nombre}; "
                f"le faltan **{falta} puntos**. **Todavía no sabemos si {ref} es el menor total que asegura.** "
                f"Puede alcanzar con menos. El mínimo que asegura se calcula cuando quedan {VENTANA_EXACTA} partidos "
                "o menos con fixture disponible."
            )
        else:
            L.append(
                f"📌 El **total seguro** queda en {ref} puntos, por encima de su techo de {calc.techo}. "
                "Eso no demuestra por sí solo que el objetivo sea imposible: sólo indica que este total seguro "
                "no alcanza para resolver el caso y hay que mirar el motor exacto o los resultados ajenos."
            )
        if pend and ref > pts[equipo]:
            L.extend(_opciones_liga(equipo, base, rest, pend, k, nombre, ref - 1))
    else:
        L.append(
            "Sigue en carrera, pero con los datos disponibles todavía no hay un total seguro publicable ni un "
            "mínimo que asegura calculado."
        )

    if pend:
        mios = [(a, b) for (a, b) in pend if equipo in (a, b)]
        if mios:
            rivs = [b if a == equipo else a for (a, b) in mios]
            L.append("Le queda(n) por jugar: " + ", ".join(rivs) + ".")
            directos = [r for r in rivs if r in base and _liga_in_out(r, base, rest, k) == "pelea"]
            if directos:
                L.append(
                    f"⚔️ **Mano a mano:** se cruza con {', '.join(directos)}, rival(es) directo(s) por {nombre} — "
                    "ganarles vale doble (suma y los deja sin sumar)."
                )
    pq = _porque_liga(equipo, base, rest, zonas, texto, pend)
    if pq:
        L.append("🔍 **Por qué:** " + pq)
    if _piso_garantia_exacta(calc) is not None:
        L.append(
            f"_El mínimo que asegura está comprobado porque el equipo está dentro de la ventana de {VENTANA_EXACTA} partidos o menos "
            "y el fixture permite resolver los escenarios compatibles._"
        )
    elif _piso_referencia_conservadora(calc) is not None:
        L.append(
            "_El total seguro alcanza, pero puede pedir puntos de más. Todavía no sabemos si es el menor total que "
            f"asegura. El mínimo que asegura se busca con {VENTANA_EXACTA} partidos restantes o menos y fixture disponible._"
        )
    return "\n\n".join(L)

def _porque_liga(equipo, base, rest, zonas, texto, pend=None):
    tgt = zona_target(zonas, texto)
    if not tgt or equipo not in base:
        return None
    k, nombre = tgt
    pts = {e: base[e]["pts"] for e in base}
    pmax = {e: pts[e] + 3 * rest.get(e, 0) for e in base}
    calc = piso_por_corte(base, rest, list(pend or []), equipo, k, clave="liga", nombre=nombre)
    g = int(rest.get(equipo, 0))
    if calc.estado == "in":
        pueden = sorted([x for x in base if x != equipo and pmax[x] >= pts[equipo]], key=lambda x: -pmax[x])
        cuales = f"solo {', '.join(pueden)} pueden igualar o superar ese puntaje" if pueden else "nadie puede igualar o superar ese puntaje"
        return f"aunque {equipo} pierda todo lo que le queda, {cuales}; como entran {k}, ya está adentro."
    if calc.estado == "out":
        arr = sorted([x for x in base if x != equipo and pts[x] > pmax[equipo]], key=lambda x: -pts[x])
        muestra = ", ".join(arr[:4]) + (f" y {len(arr)-4} más" if len(arr) > 4 else "")
        return (
            f"su máximo es {pmax[equipo]} pts (ganando sus {g}), y ya hay {len(arr)} por encima de ese total "
            f"({muestra}): no los puede pasar."
        )
    if _piso_garantia_exacta(calc) is not None:
        falta = max(0, _piso_garantia_exacta(calc) - pts[equipo])
        return (
            f"el motor exacto resolvió el fixture pendiente y comprobó que {_piso_garantia_exacta(calc)} es el menor total "
            f"que asegura {nombre} en todos los escenarios compatibles; hoy tiene {pts[equipo]}, por eso le faltan {falta}."
        )
    if _piso_referencia_conservadora(calc) is not None:
        ref = int(_piso_referencia_conservadora(calc))
        falta = max(0, ref - pts[equipo])
        if pend:
            return (
                f"el cálculo del total seguro descuenta los cruces entre rivales que no pueden ganar ambos a la vez. "
                f"Con {ref} puntos asegura {nombre}; hoy tiene {pts[equipo]}, por eso le faltan {falta} puntos. "
                "Puede ser más exigente que el mínimo que asegura."
            )
        return (
            f"sin fixture, el cálculo del total seguro supone el escenario más exigente para los rivales. "
            f"Marca {ref} puntos ({falta} más que hoy), pero puede pedir puntos de más porque no descuenta todos los cruces reales."
        )
    return "la tabla sigue abierta y todavía no hay un número seguro publicable con los datos disponibles."

def _porque_numero_magico(equipo, eqs, jug, pen, n):
    ov = _stats(eqs, jug); rest = _restantes(eqs, pen)
    pts = {e: ov[e]["pts"] for e in eqs}; pmax = {e: pts[e] + 3 * rest[e] for e in eqs}
    arriba = sum(1 for x in eqs if x != equipo and pmax[x] >= pts[equipo])
    if arriba < n:
        return f"aunque {equipo} no sume más, solo {arriba} pueden igualar o superar ese puntaje y entran {n}."
    otros = sorted(((x, pmax[x]) for x in eqs if x != equipo), key=lambda kv: -kv[1])
    rt, rm = otros[n-1]
    return (f"el cálculo del total seguro toma al {n}º rival con mayor máximo posible: {rt}, hasta {rm} puntos. "
            f"Superar ese total ({rm+1}) es suficiente; hoy tenés {pts[equipo]} → faltan "
            f"{max(0, rm+1-pts[equipo])} puntos más. Puede ser más exigente que el mínimo que asegura.")

def _porque_chances(equipo, esc):
    d = DIRECTO(); T = len(esc); pos = esc[f"Pos {equipo}"]; n = int((pos <= d).sum())
    return (f"de los {T} escenarios posibles (todas las formas en que pueden salir los goles de los partidos que faltan), "
            f"en {n} {equipo} queda entre los {d} primeros y en {T-n} no. Es un conteo de escenarios, no una probabilidad.")

def _porque_bisagra(eqs, jug, pen, esc):
    sc = bisagra_scores(eqs, jug, pen, esc)
    if not sc:
        return None
    a, b = sc[0]["match"]
    return (f"según cómo termine {a} vs {b} cambia más que en cualquier otro partido la cantidad de equipos "
            f"que clasifican; por eso es el que más define.")

def relato_equipo_texto(equipo, eqs, jug, esc, pend):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    pos = posiciones(eqs, jug)[equipo]
    row = tabla(eqs, jug).set_index("Equipo").loc[equipo]
    partes = [f"{equipo} marcha {pos}º del grupo con {int(row.PTS)} puntos en {int(row.PJ)} PJ (diferencia de gol {int(row.DG):+d})."]
    own = _pd_de(equipo, pend)
    if own:
        rivales = [(v if l == equipo else l) for i, l, v in own]
        partes.append(f"Le queda{'n' if len(rivales) > 1 else ''} por jugar contra {', '.join(rivales)}.")
    cat, manos = en_sus_manos(equipo, esc, pend)
    partes.append(manos[0].upper() + manos[1:] + ".")
    pmin, pmax = int(esc[f"Pos {equipo}"].min()), int(esc[f"Pos {equipo}"].max())
    if pmin != pmax:
        partes.append(f"En el mejor de los casos puede terminar {pmin}º y en el peor, {pmax}º.")
    if not situacion(equipo, esc)["ya_1"] and situacion(equipo, esc)["puede_1"] and pmin == 1:
        partes.append("Todavía tiene chances de quedarse con el primer puesto del grupo.")
    if cat not in ("ya", "out") and own:
        df = esc.copy(); df["_pos"] = esc[f"Pos {equipo}"].values
        df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
        frases = []
        for prop, g in sorted(df.groupby("_p"), key=lambda kv: kv[1]["_pos"].mean()):
            pmin, pmax = int(g["_pos"].min()), int(g["_pos"].max())
            if pmax <= d:               res = "se mete entre los que clasifican directo, sin depender de nadie"
            elif pmin <= d:             res = "puede entrar directo, aunque depende del otro resultado y de la diferencia de gol"
            elif hay3 and pmax <= 3:    res = "termina tercero y queda a la espera de ser uno de los mejores terceros del torneo"
            elif hay3 and pmin <= 3:    res = "puede salvarse como tercero o quedar afuera, según los otros grupos"
            else:                       res = "queda eliminado"
            frases.append(f"si {prop}, {res}")
        partes.append("De cara al cierre: " + "; ".join(frases) + ".")
    return " ".join(partes)

def relato_grupo_texto(eqs, jug, esc, pend):
    t = tabla(eqs, jug)
    lider = t.iloc[0]
    partes = [f"{lider.Equipo} encabeza el grupo con {int(lider.PTS)} puntos."]
    clasif, elim, vivos = [], [], []
    for e in eqs:
        s = situacion(e, esc)
        (clasif if s["ya_directo"] else elim if s["eliminado"] else vivos).append(e)
    if clasif: partes.append(("Ya tiene el pasaje asegurado " if len(clasif) == 1 else "Ya tienen el pasaje asegurado ") + ", ".join(clasif) + ".")
    if elim:   partes.append(("Quedó sin chances " if len(elim) == 1 else "Quedaron sin chances ") + ", ".join(elim) + ".")
    if vivos:  partes.append(("Sigue con vida " if len(vivos) == 1 else "Siguen con vida ") + ", ".join(vivos) + ".")
    manos = [e for e in eqs if en_sus_manos(e, esc, pend)[0] == "manos"]
    if manos:  partes.append(("Depende de sí mismo " if len(manos) == 1 else "Dependen de sí mismos ") + ", ".join(manos) + ".")
    if pend:   partes.append("Todo se define en: " + ", ".join(f"{l} vs {v}" for l, v in pend) + ".")
    if pend:
        try:
            sc = bisagra_scores(eqs, jug, pend, esc)
            if sc and sc[0]["swing"] > 0:
                partes.append(f"El partido que más define la clasificación es {sc[0]['match'][0]} vs {sc[0]['match'][1]}.")
        except Exception:
            pass
    if len(t) >= 3:
        margen = int(t.iloc[0]["PTS"]) - int(t.iloc[2]["PTS"])
        partes.append(f"Hoy {t.iloc[0].Equipo} le saca {margen} punto{'s' if margen != 1 else ''} al 3º ({t.iloc[2].Equipo}).")
    return " ".join(partes)

def _celda_estado(g2, d, hay3):
    pmin, pmax = int(g2["_pos"].min()), int(g2["_pos"].max())
    rng = f"{pmin}º" if pmin == pmax else f"{pmin}º-{pmax}º"
    if pmax <= d:            return ("#1b5e20", f"{rng} ✓")
    if pmin <= d:            return ("#ef6c00", "DG")
    if hay3 and pmax <= 3:   return ("#f9a825", "3º*")
    if hay3 and pmin <= 3:   return ("#ef6c00", "3º/✗")
    return ("#b71c1c", "✗")

def matriz_necesita_html(equipo, esc, pend):
    s = spec_necesita(equipo, esc, pend)
    return _html_tabla(s) if s else None

_C_DIR, _C_DG, _C_3, _C_OUT, _C_GREY, _C_HEAD, _C_NEU = "#1b5e20", "#ef6c00", "#f9a825", "#b71c1c", "#9e9e9e", "#f4f6ef", "#eef1e8"

def _is_dark(c):
    c = c.lstrip("#")
    if len(c) != 6: return False
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 150

def _verde(pct):
    t = max(0, min(1, pct / 100))
    r = int(255 + (27 - 255) * t); g = int(255 + (94 - 255) * t); b = int(255 + (32 - 255) * t)
    return f"#{r:02x}{g:02x}{b:02x}"

def _html_tabla(spec):
    spec = editorialize_spec(spec)
    th = "padding:8px 10px;font:600 13px Barlow,sans-serif;color:#1a1a2e;border:1px solid #e0e0e0;background:#f4f6ef;text-align:center"
    ch, rh, cells = spec["col_headers"], spec["row_headers"], spec["cells"]
    h = [f'<div style="font:700 17px Barlow,sans-serif;color:#1a1a2e;margin:8px 0 4px">{spec["titulo"]}</div>'] if spec.get("titulo") else []
    h.append('<div style="overflow-x:auto"><table style="border-collapse:collapse;margin:6px 0">')
    h.append(f'<tr><th style="{th};text-align:left">{spec.get("corner","")}</th>' + "".join(f'<th style="{th}">{c}</th>' for c in ch) + "</tr>")
    for i, rl in enumerate(rh):
        h.append(f'<tr><th style="{th};text-align:left">{rl}</th>')
        for j in range(len(ch)):
            text, color = cells[i][j]
            tcol = "#fff" if _is_dark(color) else "#1a1a2e"
            h.append(f'<td style="padding:12px 10px;border:1px solid #fff;text-align:center;background:{color};color:{tcol};font:700 15px Barlow,sans-serif">{text}</td>')
        h.append("</tr>")
    h.append("</table></div>")
    if spec.get("leyenda"):
        chip = "color:#fff;padding:1px 7px;border-radius:3px;font:600 12px Barlow,sans-serif"
        h.append('<div style="margin-top:6px;line-height:2">' + " &nbsp; ".join(f'<span style="background:{c};{chip}">{l}</span>' for c, l in spec["leyenda"]) + "</div>")
    if spec.get("footer"):
        h.append(f'<div style="font:italic 12px Barlow,sans-serif;color:#666;margin-top:4px">{spec["footer"]}</div>')
    return "".join(h)

def _png_tabla(spec):
    spec = editorialize_spec(spec)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from io import BytesIO
    import textwrap
    ch, rh, cells = spec["col_headers"], spec["row_headers"], spec["cells"]
    nC, nR = len(ch), len(rh)
    cw, rhw, rht, headh, titleh = 2.6, 2.6, 0.78, 0.74, 0.6
    legh = 0.5 if spec.get("leyenda") else 0.0
    footh = 0.4 if spec.get("footer") else 0.0
    W, H = rhw + cw * nC, titleh + headh + rht * nR + legh + footh
    fig, ax = plt.subplots(figsize=(W, H), dpi=200)
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off"); ax.invert_yaxis()
    if spec.get("titulo"):
        ax.text(0.05, titleh * 0.55, spec["titulo"], fontsize=15, fontweight="bold", color="#1a1a2e", va="center")
    y = titleh
    ax.add_patch(Rectangle((0, y), rhw, headh, facecolor=_C_HEAD, edgecolor="#e0e0e0"))
    ax.text(0.12, y + headh / 2, spec.get("corner", ""), fontsize=9, fontweight="bold", color="#1a1a2e", va="center")
    for j, hd in enumerate(ch):
        x = rhw + cw * j
        ax.add_patch(Rectangle((x, y), cw, headh, facecolor=_C_HEAD, edgecolor="#e0e0e0"))
        ax.text(x + cw / 2, y + headh / 2, "\n".join(textwrap.wrap(str(hd), 18)), fontsize=9, fontweight="bold", color="#1a1a2e", ha="center", va="center")
    y += headh
    for i, rl in enumerate(rh):
        ax.add_patch(Rectangle((0, y), rhw, rht, facecolor=_C_HEAD, edgecolor="#e0e0e0"))
        ax.text(0.12, y + rht / 2, "\n".join(textwrap.wrap(str(rl), 22)), fontsize=9, fontweight="bold", color="#1a1a2e", va="center")
        for j in range(nC):
            text, color = cells[i][j]
            x = rhw + cw * j
            ax.add_patch(Rectangle((x, y), cw, rht, facecolor=color, edgecolor="#ffffff", linewidth=2))
            ax.text(x + cw / 2, y + rht / 2, "\n".join(textwrap.wrap(str(text), 17)), fontsize=11.5, fontweight="bold",
                    color="#fff" if _is_dark(color) else "#1a1a2e", ha="center", va="center")
        y += rht
    if spec.get("leyenda"):
        lx = 0.05
        for color, label in spec["leyenda"]:
            ax.add_patch(Rectangle((lx, y + 0.12), 0.34, 0.26, facecolor=color, edgecolor="none"))
            ax.text(lx + 0.44, y + 0.25, label, fontsize=8.5, color="#444", va="center")
            lx += 0.6 + 0.085 * len(label)
        y += legh
    if spec.get("footer"):
        ax.text(0.05, y + 0.2, spec["footer"], fontsize=8, style="italic", color="#666", va="center")
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.18)
    plt.close(fig)
    return buf.getvalue()

def spec_necesita(equipo, esc, pend):
    if len(_pd_de(equipo, pend)) != 1:
        return None
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    df = esc.copy(); df["_pos"] = esc[f"Pos {equipo}"].values
    df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    df["_o"] = df.apply(lambda r: _res_otros(r, equipo, pend), axis=1)
    filas = [k for k, _ in sorted(df.groupby("_p"), key=lambda kv: kv[1]["_pos"].mean())]
    cols = [k for k, _ in sorted(df.groupby("_o"), key=lambda kv: kv[1]["_pos"].mean())]
    cells = []
    for fp in filas:
        row = []
        for c in cols:
            g2 = df[(df["_p"] == fp) & (df["_o"] == c)]
            if len(g2) == 0:
                row.append(("—", "#e0e0e0")); continue
            color, label = _celda_estado(g2, d, hay3)
            row.append((label, color))
        cells.append(row)
    leyenda = [(_C_DIR, "clasifica directo"), (_C_DG, "según dif. de gol"), (_C_3, "3º (depende)"), (_C_OUT, "afuera")]
    return {"titulo": f"Qué necesita {equipo}", "col_headers": cols, "row_headers": filas, "cells": cells,
            "corner": f"{equipo} ⬇ / otros ➡", "leyenda": leyenda,
            "footer": f"Filas = resultado de {equipo}; columnas = el otro partido del grupo."}

def spec_puesto(equipo, esc, pend, puesto):
    if len(_pd_de(equipo, pend)) != 1:
        return None
    df = esc.copy(); df["_pos"] = esc[f"Pos {equipo}"].values
    df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    df["_o"] = df.apply(lambda r: _res_otros(r, equipo, pend), axis=1)
    filas = [k for k, _ in sorted(df.groupby("_p"), key=lambda kv: kv[1]["_pos"].mean())]
    cols = [k for k, _ in sorted(df.groupby("_o"), key=lambda kv: kv[1]["_pos"].mean())]
    cells = []
    for fp in filas:
        row = []
        for c in cols:
            g2 = df[(df["_p"] == fp) & (df["_o"] == c)]
            S = set(int(x) for x in g2["_pos"].unique())
            if S == {puesto}:     row.append((f"{puesto}º ✓", _C_DIR))
            elif puesto in S:     row.append(("a veces", _C_DG))
            else:                 row.append(("—", _C_GREY))
        cells.append(row)
    leyenda = [(_C_DIR, f"termina {puesto}º"), (_C_DG, f"puede ({puesto}º o no)"), (_C_GREY, "no")]
    return {"titulo": f"¿Cuándo {equipo} termina {puesto}º?", "col_headers": cols, "row_headers": filas, "cells": cells,
            "corner": f"{equipo} ⬇ / otros ➡", "leyenda": leyenda,
            "footer": f"Verde = {equipo} queda {puesto}º seguro; ámbar = depende; gris = no llega."}

def spec_mapa(eqs, esc):
    T = len(esc); n = len(eqs)
    order = sorted(eqs, key=lambda e: esc[f"Pos {e}"].mean())
    cols = [f"{k}º" for k in range(1, n + 1)]
    cells = []
    for e in order:
        pos = esc[f"Pos {e}"]; row = []
        for k in range(1, n + 1):
            pct = round(100 * (pos == k).sum() / T)
            row.append((f"{pct}%" if pct else "·", _verde(pct)))
        cells.append(row)
    return {"titulo": "Mapa del grupo · dónde termina cada uno", "col_headers": cols, "row_headers": order, "cells": cells,
            "corner": "equipo ⬇ / puesto ➡", "leyenda": None,
            "footer": "% de escenarios en que cae en cada puesto (conteo de marcadores, no probabilidad real)."}

def spec_comparar(e1, e2, eqs, jug, esc, pend):
    t = tabla(eqs, jug).set_index("Equipo"); pos = posiciones(eqs, jug); rest = _restantes(eqs, pend)
    pmax = lambda e: int(t.loc[e].PTS) + 3 * rest[e]
    s1 = round(100 * (esc[f"Pos {e1}"] < esc[f"Pos {e2}"]).sum() / len(esc))
    s2 = round(100 * (esc[f"Pos {e2}"] < esc[f"Pos {e1}"]).sum() / len(esc))
    N = _C_NEU
    rows = [("Posición actual", [(f"{pos[e1]}º", N), (f"{pos[e2]}º", N)]),
            ("Puntos", [(str(int(t.loc[e1].PTS)), N), (str(int(t.loc[e2].PTS)), N)]),
            ("Dif. de gol", [(f"{int(t.loc[e1].DG):+d}", N), (f"{int(t.loc[e2].DG):+d}", N)]),
            ("Máx. posible", [(str(pmax(e1)), N), (str(pmax(e2)), N)]),
            ("Termina arriba", [(f"{s1}%", _C_DIR if s1 >= s2 else _C_OUT), (f"{s2}%", _C_DIR if s2 > s1 else _C_OUT)])]
    return {"titulo": f"{e1} vs {e2}", "col_headers": [e1, e2], "row_headers": [r[0] for r in rows],
            "cells": [r[1] for r in rows], "corner": "", "leyenda": None,
            "footer": "«Termina arriba» = en qué % de escenarios cada uno queda por encima del otro."}

def bisagra_scores(eqs, jug, pen, esc):
    d = DIRECTO(); pos = {e: esc[f"Pos {e}"] for e in eqs}
    res = []
    for i, (L, V) in enumerate(pen, 1):
        gl, gv = esc[f"P{i}_gl"], esc[f"P{i}_gv"]
        masks = {"gana " + L: gl > gv, "empate": gl == gv, "gana " + V: gl < gv}
        swing = 0.0; afectados = []
        for t in eqs:
            ps = []
            for m in masks.values():
                sub = pos[t][m]
                ps.append(100 * (sub <= d).mean() if len(sub) else 0)
            rng = max(ps) - min(ps); swing += rng
            if rng >= 60:
                afectados.append(t)
        res.append({"match": (L, V), "i": i, "swing": swing, "teams": afectados})
    res.sort(key=lambda x: -x["swing"])
    return res

def partido_bisagra_texto(eqs, jug, pen, esc):
    sc = bisagra_scores(eqs, jug, pen, esc)
    if not sc:
        return "No quedan partidos por jugar en el grupo."
    L = ["**Partidos que más definen** (de mayor a menor peso):"]
    for k, s in enumerate(sc):
        a, b = s["match"]; tag = "🔑 " if k == 0 else "• "
        det = (" — decisivo para " + ", ".join(s["teams"])) if s["teams"] else ""
        L.append(f"{tag}**{a} vs {b}**{det}")
    return "\n\n".join(L)

def placa_bisagra_png(eqs, jug, pen, esc):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from io import BytesIO
    sc = bisagra_scores(eqs, jug, pen, esc)
    if not sc:
        return None
    labels = [f"{display_team(s['match'][0])} vs {display_team(s['match'][1])}" for s in sc]
    vals = [s["swing"] for s in sc]
    cols = ["#1b5e20"] + ["#7aa53d"] * (len(sc) - 1)
    fig, ax = plt.subplots(figsize=(6.8, 0.7 * len(sc) + 1.3), dpi=200)
    ax.barh(range(len(sc)), vals, color=cols, edgecolor="white")
    ax.set_yticks(range(len(sc))); ax.set_yticklabels(labels, fontsize=11.5, fontweight="bold")
    ax.invert_yaxis()
    ax.set_title("Partidos que más definen el grupo", fontsize=14, fontweight="bold", color="#1a1a2e", loc="left")
    for sp in ["top", "right", "bottom"]:
        ax.spines[sp].set_visible(False)
    ax.get_xaxis().set_visible(False)
    if vals:
        ax.text(vals[0] * 0.5, 0, "★ BISAGRA", va="center", ha="center", fontsize=11, color="white", fontweight="bold")
    fig.text(0.01, -0.02, "Mayor barra = el resultado cambia más quién clasifica.", fontsize=8, style="italic", color="#666")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.2); plt.close(fig)
    return buf.getvalue()

def barras_puesto_png(equipo, esc):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from io import BytesIO
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    teams = [c[4:] for c in esc.columns if c.startswith("Pos ")]
    n = len(teams); T = len(esc); pos = esc[f"Pos {equipo}"]
    pcts = [100 * (pos == k).sum() / T for k in range(1, n + 1)]
    cols = ["#1b5e20" if k <= d else ("#f9a825" if (k == 3 and hay3) else "#b71c1c") for k in range(1, n + 1)]
    fig, ax = plt.subplots(figsize=(6.4, 3.5), dpi=200)
    bars = ax.bar([f"{k}º" for k in range(1, n + 1)], pcts, color=cols, edgecolor="white")
    for b, p in zip(bars, pcts):
        ax.text(b.get_x() + b.get_width() / 2, p + 1, f"{p:.0f}%", ha="center", va="bottom", fontsize=11.5, fontweight="bold", color="#1a1a2e")
    ax.set_ylim(0, max(pcts) * 1.2 + 4)
    ax.set_title(f"Dónde puede terminar {display_team(equipo)}", fontsize=14, fontweight="bold", color="#1a1a2e", loc="left")
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.get_yaxis().set_visible(False); ax.tick_params(axis="x", labelsize=12)
    fig.text(0.01, -0.03, "% de escenarios (conteo de marcadores, no probabilidad real). Verde = clasifica.", fontsize=8, style="italic", color="#666")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.2); plt.close(fig)
    return buf.getvalue()

def _chances_label(pct, s):
    if s.get("ya_directo"): return "YA CLASIFICÓ", "#1b5e20"
    if s.get("eliminado"): return "ELIMINADO", "#b71c1c"
    if pct >= 85: return "MUY BIEN", "#1b5e20"
    if pct >= 60: return "BIEN ENCAMINADO", "#7aa53d"
    if pct >= 40: return "MANO A MANO", "#f9a825"
    if pct >= 15: return "COMPLICADO", "#ef6c00"
    return "CASI SIN CHANCES", "#b71c1c"

def chances_texto(equipo, eqs, jug, esc, pend):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0; s = situacion(equipo, esc)
    pos = esc[f"Pos {equipo}"]; pct = 100 * float((pos <= d).mean())
    if s["ya_directo"]: pct = 100
    if s["eliminado"]: pct = 0
    verdict, _ = _chances_label(pct, s)
    icon = "✅" if s["ya_directo"] else ("🔴" if s["eliminado"] else ("🟢" if pct >= 60 else ("🟡" if pct >= 40 else "🟠")))
    diez = max(0, min(10, round(pct / 10)))
    L = [f"**¿Cómo viene {equipo}?**", f"{icon} **{verdict}**"]
    if s["ya_directo"]:
        L.append(f"{equipo} ya tiene la clasificación asegurada pase lo que pase.")
    elif s["eliminado"]:
        L.append(f"{equipo} ya no puede clasificar: quedó sin chances matemáticas.")
    else:
        L.append(f"En **{diez} de cada 10** formas en que pueden salir los partidos que faltan, {equipo} clasifica entre los {d} primeros.")
        df = esc.copy(); df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1); df["_ok"] = (pos <= d).values
        rates = {p: g["_ok"].mean() for p, g in df.groupby("_p") if p}
        gana = [p for p in rates if p.startswith("le gana")]
        if gana and all(rates[p] >= 0.999 for p in gana):
            L.append("Lo tiene en sus manos: **ganando** lo suyo queda adentro sin depender de nadie.")
        else:
            cat, manos = en_sus_manos(equipo, esc, pend)
            L.append(manos[0].upper() + manos[1:] + ".")
        if hay3 and s.get("puede_tercero"):
            L.append(f"_Aun sin entrar entre los {d} primeros, puede colarse como uno de los mejores terceros._")
    L.append("_Guía didáctica: cuenta de cuántas formas pueden salir los goles, no es una probabilidad real._")
    return "\n\n".join(L)

def placa_chances_png(equipo, eqs, jug, esc, pend):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from io import BytesIO
    d = DIRECTO(); s = situacion(equipo, esc); pos = esc[f"Pos {equipo}"]
    pct = 100 * float((pos <= d).mean())
    if s["ya_directo"]: pct = 100
    if s["eliminado"]: pct = 0
    verdict, _ = _chances_label(pct, s)
    diez = max(0, min(10, round(pct / 10)))
    fig, ax = plt.subplots(figsize=(7.2, 2.2), dpi=200)
    cmap = LinearSegmentedColormap.from_list("c", ["#b71c1c", "#ef6c00", "#f9a825", "#7aa53d", "#1b5e20"])
    ax.imshow(np.linspace(0, 1, 256).reshape(1, -1), extent=[0, 100, 0, 1], aspect="auto", cmap=cmap)
    ax.plot([pct], [1.12], marker="v", markersize=18, color="#1a1a2e", clip_on=False)
    ax.text(pct, 1.45, verdict, ha="center", va="bottom", fontsize=15, fontweight="bold", color="#1a1a2e", clip_on=False)
    for x, lab in [(10, "Casi nada"), (30, "Difícil"), (50, "Parejo"), (70, "Probable"), (90, "Casi seguro")]:
        ax.text(x, -0.22, lab, ha="center", va="top", fontsize=9.5, color="#444")
    ax.set_xlim(0, 100); ax.set_ylim(-1.4, 2.3); ax.axis("off")
    ax.set_title(f"¿Cómo viene {display_team(equipo)}?", fontsize=15, fontweight="bold", color="#1a1a2e", loc="left", y=0.92)
    sub = ("Ya clasificó" if s["ya_directo"] else ("Quedó eliminado" if s["eliminado"]
           else f"Clasifica en {diez} de cada 10 formas posibles"))
    ax.text(50, -0.62, sub, ha="center", va="top", fontsize=10.5, style="italic", color="#555")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.3); plt.close(fig)
    return buf.getvalue()

def aplicar_resultados(eqs, jugados, pend, fixed):
    """fixed: {indice_1based: 'L'/'E'/'V'}. Triunfos 1-0, empates 0-0. Devuelve (jugados_sim, pendientes_restantes)."""
    jug = list(jugados); rem = []
    for i, (l, v) in enumerate(pend, 1):
        o = fixed.get(i)
        if o == "L":   jug.append((l, v, 1, 0))
        elif o == "E": jug.append((l, v, 0, 0))
        elif o == "V": jug.append((l, v, 0, 1))
        else:          rem.append((l, v))
    return jug, rem

def filtrar_esc(esc, fixed):
    m = pd.Series(True, index=esc.index)
    for i, o in fixed.items():
        gl, gv = esc[f"P{i}_gl"], esc[f"P{i}_gv"]
        if o == "L":   m &= gl > gv
        elif o == "E": m &= gl == gv
        elif o == "V": m &= gl < gv
    return esc[m]

def previa_condicional_texto(eqs, jugados, pend, esc, fixed):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    desc = []
    for i, (l, v) in enumerate(pend, 1):
        o = fixed.get(i)
        if o == "L":   desc.append(f"{l} le gana a {v}")
        elif o == "E": desc.append(f"empatan {l} y {v}")
        elif o == "V": desc.append(f"{v} le gana a {l}")
    sub = filtrar_esc(esc, fixed)
    if len(sub) == 0:
        return "Esa combinación no es posible con los partidos cargados."
    L = []
    if desc:
        L.append("**Si " + ", y ".join(desc) + ":**")
    clasi, afue, dep = [], [], []
    for e in eqs:
        pos = sub[f"Pos {e}"]; r = float((pos <= d).mean())
        if r >= 0.999:
            clasi.append(e)
        elif r <= 0.001:
            if hay3 and float((pos == 3).mean()) > 0:
                dep.append(e + " (a pelear el 3er puesto)")
            else:
                afue.append(e)
        else:
            dep.append(e)
    if clasi: L.append(f"Clasifican entre los {d}: **{', '.join(clasi)}**.")
    if dep:   L.append("En duda según el resto: " + ", ".join(dep) + ".")
    if afue:  L.append("Quedaría(n) afuera: " + ", ".join(afue) + ".")
    rem = [f"{l} vs {v}" for i, (l, v) in enumerate(pend, 1) if i not in fixed]
    if rem:
        L.append("_Falta definir: " + ", ".join(rem) + "._")
    L.append("_La tabla de arriba asume triunfos 1-0 y empates 0-0 (el DG real depende del marcador). La clasificación considera todos los marcadores posibles de los partidos que fijaste; en empates de puntos muy finos puede definirse por desempate._")
    return "\n\n".join(L)

def _branch_label(equipo, own, combo):
    parts = []
    for i, l, v in own:
        o = combo[i]; other = v if l == equipo else l
        if (o == "L" and l == equipo) or (o == "V" and v == equipo):
            parts.append(f"le gana a {other}")
        elif o == "E":
            parts.append(f"empata con {other}")
        else:
            parts.append(f"pierde con {other}")
    return " y ".join(parts)

def arbol_branches(equipo, eqs, jug, esc, pend):
    import itertools
    own = _pd_de(equipo, pend)
    if not own or len(own) > 2:
        return None
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    res = []
    for vals in itertools.product(["L", "E", "V"], repeat=len(own)):
        combo = {i: o for (i, l, v), o in zip(own, vals)}
        m = pd.Series(True, index=esc.index)
        for i, o in combo.items():
            gl, gv = esc[f"P{i}_gl"], esc[f"P{i}_gv"]
            m &= (gl > gv) if o == "L" else ((gl == gv) if o == "E" else (gl < gv))
        sub = esc[m]
        if len(sub) == 0:
            continue
        pos = sub[f"Pos {equipo}"]; rd = float((pos <= d).mean()); r3 = float((pos == 3).mean())
        if rd >= 0.999:
            verd, col = "Clasifica", "#1b5e20"
        elif rd <= 0.001:
            verd, col = ("Pelea 3º", "#f9a825") if (hay3 and r3 > 0) else ("Afuera", "#b71c1c")
        else:
            verd, col = "Depende", "#ef6c00"
        # orden desde la óptica del equipo: gana(0) / empata(1) / pierde(2)
        pkey = []
        for i, l, v in own:
            o = combo[i]
            pkey.append(0 if ((o == "L" and l == equipo) or (o == "V" and v == equipo)) else (1 if o == "E" else 2))
        res.append({"label": _branch_label(equipo, own, combo).capitalize(), "verd": verd,
                    "col": col, "key": tuple(pkey)})
    res.sort(key=lambda r: r["key"])
    return res

def placa_arbol_png(equipo, eqs, jug, esc, pend):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import textwrap
    from io import BytesIO
    br = arbol_branches(equipo, eqs, jug, esc, pend)
    if not br:
        return None
    n = len(br); fig, ax = plt.subplots(figsize=(7.6, 0.92 * n + 1.1), dpi=200)
    ax.set_xlim(0, 10); ax.set_ylim(0, n); ax.axis("off")
    ax.set_title(f"¿Qué pasa con {display_team(equipo)}?", fontsize=15, fontweight="bold", color="#1a1a2e", loc="left", pad=12)
    ymid = n / 2
    ax.add_patch(FancyBboxPatch((0.1, ymid - 0.42), 2.3, 0.84, boxstyle="round,pad=0.03,rounding_size=0.12",
                                facecolor="#1a1a2e", edgecolor="none"))
    ax.text(1.25, ymid, display_team(equipo), ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    for j, b in enumerate(br):
        y = n - 0.5 - j
        ax.plot([2.4, 3.4], [ymid, y], color="#bbb", lw=2, zorder=0)
        ax.add_patch(FancyBboxPatch((3.4, y - 0.36), 3.6, 0.72, boxstyle="round,pad=0.03,rounding_size=0.1",
                                    facecolor="#eef1e8", edgecolor="#d8ddcf"))
        ax.text(5.2, y, "\n".join(textwrap.wrap(b["label"], 26)), ha="center", va="center", fontsize=10.5,
                color="#1a1a2e", fontweight="bold")
        ax.plot([7.0, 7.5], [y, y], color="#bbb", lw=2, zorder=0)
        ax.add_patch(FancyBboxPatch((7.5, y - 0.36), 2.3, 0.72, boxstyle="round,pad=0.03,rounding_size=0.1",
                                    facecolor=b["col"], edgecolor="none"))
        ax.text(8.65, y, b["verd"], ha="center", va="center", color="white", fontsize=11, fontweight="bold")
    fig.text(0.01, -0.02, "Según el resultado de su partido. «Depende» = puede clasificar o no según los otros partidos.",
             fontsize=8, style="italic", color="#666")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.25); plt.close(fig)
    return buf.getvalue()

def _porque_pasar(equipo, eqs, jug, esc, pend, n):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    s = situacion(equipo, esc, d)
    ov = _stats(eqs, jug); rest = _restantes(eqs, pend)
    pts = {e: ov[e]["pts"] for e in eqs}; pmax = {e: pts[e] + 3 * rest[e] for e in eqs}
    p = pts[equipo]; mx = pmax[equipo]; g = rest[equipo]
    def lst(ts, lim=4):
        ts = list(ts); return ", ".join(ts[:lim]) + (f" y {len(ts)-lim} más" if len(ts) > lim else "")
    # YA CLASIFICADO ENTRE LOS DIRECTOS
    if s["ya_directo"]:
        nopas = sorted([x for x in eqs if x != equipo and pmax[x] < p], key=lambda x: -pmax[x])
        extra = ("; " + "; ".join(f"{x}, aun ganando todo, llega a {pmax[x]}" for x in nopas[:3]) + " — no te alcanzan") if nopas else ""
        return f"{equipo} ya termina entre los {d} pase lo que pase: tiene {p} pts y los de atrás no lo pueden dejar afuera{extra}."
    # ELIMINADO DE TODO (ni mejor tercero)
    if s["eliminado"]:
        arr = sorted([x for x in eqs if x != equipo and pts[x] > mx], key=lambda x: -pts[x])
        det = f" Ya hay {len(arr)} por encima de su techo de {mx} ({lst(arr)}), no los puede pasar." if arr else ""
        cola = " (ni siquiera le da para pelear el mejor tercero)" if hay3 else ""
        return f"{equipo} quedó afuera{cola}: su techo es {mx} pts (ganando sus {g}) y no alcanza.{det}"
    # EN JUEGO
    pueden = sorted([x for x in eqs if x != equipo and pmax[x] >= p], key=lambda x: -pmax[x])
    partes = []
    if s["puede_directo"]:
        if pueden:
            partes.append(f"{equipo} tiene {p} pts (techo {mx}) y puede entrar entre los {d}, pero todavía lo pueden alcanzar {lst(pueden)}, así que depende de esos partidos")
        else:
            partes.append(f"{equipo} puede entrar entre los {d}")
        igualan = [x for x in eqs if x != equipo and pmax[x] >= mx]
        if len(igualan) >= n:
            partes.append(f"aun ganando todo (llega a {mx}) no se asegura, porque {lst(igualan)} también pueden llegar a {mx} o más")
        if hay3 and s["puede_tercero"]:
            partes.append(f"si no entra entre los {d}, igual puede colarse como **mejor tercero**, que depende de cómo terminen los otros grupos")
    else:
        if hay3 and s["asegura_vivo"]:
            partes.append(f"{equipo} ya no entra entre los {d}, pero tiene **asegurado el 3er puesto**; que ese 3º clasifique depende de los otros grupos (entran los 8 mejores terceros)")
        elif hay3 and s["puede_tercero"]:
            partes.append(f"{equipo} ya no entra entre los {d}; su chance es ser uno de los **mejores terceros**, que depende de cómo terminen los otros grupos")
        else:
            partes.append(f"{equipo} la tiene muy cuesta arriba")
    return ". ".join(x[0].upper() + x[1:] for x in partes) + "."

# ═══ CIENCIA DE DATOS: fuerza estimada, Monte Carlo liga, proyección, importador ═══

# ── Métricas periodísticas: forma, rachas, local/visitante, dificultad de fixture ──

def _res_letra(e, l, v, gl, gv):
    return _form_result_letter(e, l, v, gl, gv)

def forma_equipo(e, jug, n=5):
    return _team_form(e, jug, n)

def racha_equipo(e, jug):
    return _team_streak(e, jug)

def tabla_forma_df(eqs, jug, n=5):
    ov = _stats(eqs, jug)
    rows = []
    for e in eqs:
        ult, p5 = forma_equipo(e, jug, n)
        rows.append({"Equipo": e, "PTS": ov[e]["pts"], "Últimos 5": "".join(ult) or "—",
                     "Pts últ. 5": p5, "Racha": racha_equipo(e, jug)})
    return pd.DataFrame(rows).sort_values(["Pts últ. 5", "PTS"], ascending=False).reset_index(drop=True)

def local_visitante_df(eqs, jug):
    rows = []
    for e in eqs:
        pl = pjl = pv = pjv = 0
        for (l, v, gl, gv) in jug:
            if l == e:
                pjl += 1; pl += 3 if gl > gv else (1 if gl == gv else 0)
            elif v == e:
                pjv += 1; pv += 3 if gv > gl else (1 if gl == gv else 0)
        rows.append({"Equipo": e, "PJ local": pjl, "Pts local": pl,
                     "Pts/PJ local": round(pl / pjl, 2) if pjl else 0.0,
                     "PJ visita": pjv, "Pts visita": pv,
                     "Pts/PJ visita": round(pv / pjv, 2) if pjv else 0.0})
    return pd.DataFrame(rows).sort_values("Pts/PJ local", ascending=False).reset_index(drop=True)

def dificultad_fixture_df(eqs, pen, ppg, rest=None):
    med = (sum(ppg.values()) / len(ppg)) if ppg else 0.0
    rows = []
    for e in eqs:
        rivs = [v if l == e else l for (l, v) in pen if e in (l, v)]
        extra = max(0, (rest or {}).get(e, len(rivs)) - len(rivs)) if rest else 0
        vals = [ppg.get(r, med) for r in rivs] + [med] * extra
        idx = round(sum(vals) / len(vals), 2) if vals else np.nan
        rows.append({"Equipo": e, "Restan": len(rivs) + extra,
                     "Rivales que quedan": (", ".join(rivs[:6]) + ("…" if len(rivs) > 6 else "")) or "—",
                     "Dificultad (pts/PJ rival)": idx})
    return pd.DataFrame(rows).sort_values("Dificultad (pts/PJ rival)", ascending=False,
                                          na_position="last").reset_index(drop=True)

def ficha_equipo_texto(e, eqs, jug, pen):
    ov = _stats(eqs, jug); t = tabla(eqs, jug)
    pos = list(t["Equipo"]).index(e) + 1 if e in list(t["Equipo"]) else "?"
    d = ov[e]; pj = d["pj"]; ppg = d["pts"] / pj if pj else 0.0
    ult, p5 = forma_equipo(e, jug)
    pl = pjl = pv = pjv = 0
    for (l, v, gl, gv) in jug:
        if l == e:   pjl += 1; pl += 3 if gl > gv else (1 if gl == gv else 0)
        elif v == e: pjv += 1; pv += 3 if gv > gl else (1 if gl == gv else 0)
    rest = _restantes(eqs, pen)
    rivs = [v if l == e else l for (l, v) in pen if e in (l, v)]
    ppgs = {x: (ov[x]["pts"] / ov[x]["pj"]) if ov[x]["pj"] else 0.0 for x in eqs}
    med = (sum(ppgs.values()) / len(ppgs)) if ppgs else 0.0
    dif = round(sum(ppgs.get(r, med) for r in rivs) / len(rivs), 2) if rivs else None
    L = [f"**Ficha de {e}**",
         f"{pos}º con **{d['pts']} pts** en {pj} PJ ({round(ppg,2)} por partido) · GF {d['gf']} / GC {d['ga']} (DG {d['dg']:+d}).",
         f"**Forma (últ. 5):** {''.join(ult) or '—'} ({p5} pts) · **Racha:** {racha_equipo(e, jug)}.",
         f"**Local:** {pl} pts en {pjl} PJ ({round(pl/pjl,2) if pjl else 0}/PJ) · **Visitante:** {pv} pts en {pjv} PJ ({round(pv/pjv,2) if pjv else 0}/PJ)."]
    if rivs:
        L.append(f"**Le quedan {rest[e]}:** {', '.join(rivs)}" +
                 (f" · dificultad {dif} pts/PJ ({'más brava que' if dif and dif>med else 'más liviana que'} la media {round(med,2)})." if dif is not None else "."))
    L.append(f"**Techo:** {d['pts'] + 3*rest[e]} pts ganando todo.")
    return "\n\n".join(L)

def ficha_liga_texto(e, base, rest, pend, zonas):
    t = liga_tabla_df(base); pos = int(t.set_index("Equipo").loc[e, "Pos"])
    d = base[e]; pj = int(d.get("pj", 0)); ppg = d["pts"] / pj if pj else 0.0; r = rest.get(e, 0)
    rivs = [v if l == e else l for (l, v) in pend if e in (l, v)]
    ppgs = {x: (base[x]["pts"] / base[x].get("pj", 1)) if base[x].get("pj") else 1.35 for x in base}
    med = (sum(ppgs.values()) / len(ppgs)) if ppgs else 1.35
    cutoff_pos = min(8, len(t))
    cutoff_pts = int(t.iloc[cutoff_pos - 1]["PTS"]) if len(t) >= cutoff_pos else None
    distance = int(d["pts"] - cutoff_pts) if cutoff_pts is not None else None
    state = "Adentro" if pos <= cutoff_pos else "Afuera"
    L = [f"## Ficha de {e}",
         f"**{pos}º** con **{d['pts']} puntos** en {pj} PJ · DG {d.get('dg',0):+d} · "
         f"situación actual: **{state}**.",
         f"Le quedan **{r} partidos** y **{3*r} puntos** en juego. Su techo matemático es **{d['pts'] + 3*r}**."]
    if distance is not None:
        if distance > 0:
            unidad = "punto" if distance == 1 else "puntos"
            L.append(f"Está **{distance} {unidad} por encima** del corte actual, ubicado en {cutoff_pts} puntos.")
        elif distance == 0:
            L.append(f"Está **igualado con el corte actual**, ubicado en {cutoff_pts} puntos.")
        else:
            distancia = abs(distance)
            unidad = "punto" if distancia == 1 else "puntos"
            L.append(f"Está a **{distancia} {unidad}** del corte actual, ubicado en {cutoff_pts} puntos.")
    if pj >= 5:
        L.append(f"**Proyección lineal descriptiva:** {round(d['pts'] + ppg*r,1)} puntos si mantuviera exactamente "
                 "su promedio actual. No es la probabilidad del modelo.")
    else:
        L.append("**Proyección lineal:** se oculta porque la muestra todavía es demasiado chica. "
                 "Las probabilidades usan una fuerza regularizada con antecedentes del Apertura.")
    if rivs:
        dif = round(sum(ppgs.get(x, med) for x in rivs) / len(rivs), 2)
        if dif > med + 0.08:
            label = "más exigente que el promedio"
        elif dif < med - 0.08:
            label = "más accesible que el promedio"
        else:
            label = "similar al promedio"
        L.append(f"**Próximos tres:** {', '.join(rivs[:3])}.")
        L.append(f"**Calendario restante:** {label}. Índice técnico {dif} pts/PJ rival (media {round(med,2)}), "
                 "visible para auditoría pero no usado como sentencia editorial.")
        if len(rivs) > 3:
            L.append(f"_Fixture completo: {', '.join(rivs)}._")
    else:
        L.append("_No hay un fixture pendiente confiable. Revisá Datos y auditoría._")
    return "\n\n".join(L)


def fuerza_desde_stats(eqs, jug):
    """Fuerza por equipo: mezcla rendimiento global (70%) + forma últimos 5 (30%)."""
    ov = _stats(eqs, jug)
    ppg = {e: (ov[e]["pts"] / ov[e]["pj"]) if ov[e]["pj"] else 1.0 for e in eqs}
    ppg5 = {}
    for e in eqs:
        ult, p5 = forma_equipo(e, jug, 5)
        ppg5[e] = (p5 / len(ult)) if ult else ppg[e]
    mix = {e: 0.7 * ppg[e] + 0.3 * ppg5[e] for e in eqs}
    med = sum(mix.values()) / len(mix) if mix else 1.0
    if not med:
        return None
    return {e: min(1.7, max(0.55, mix[e] / med)) for e in eqs}

def _fuerza_liga(base):
    ppg = {e: (d["pts"] / d.get("pj", 0)) if d.get("pj") else 1.0 for e, d in base.items()}
    med = sum(ppg.values()) / len(ppg) if ppg else 1.0
    return {e: min(1.8, max(0.4, (ppg[e] / med) if med else 1.0)) for e in base}

def liga_probabilidades_df(base, rest, pend, zonas, n=_LPF_PUBLIC_MC_RUNS, seed=7, pdraw=0.26, fuerza=None):
    """Monte Carlo del cierre de la liga: % de terminar en cada zona. Usa el fixture pegado
    para los cruces reales y rival promedio para los partidos sin rival conocido."""
    rng = np.random.default_rng(seed)
    eqs = list(base.keys()); idx = {e: i for i, e in enumerate(eqs)}
    s = fuerza or _fuerza_liga(base)
    pts0 = np.array([base[e]["pts"] for e in eqs], float)
    dg0 = np.array([float(base[e].get("dg", 0)) for e in eqs])
    pts = np.tile(pts0, (n, 1))
    # Un interzonal también afecta la tabla de esta zona: se simula contra el
    # rival real una sola vez, aunque el rival no pertenezca a ``base``.
    fix = [(a, b) for (a, b) in pend if a in idx or b in idx]
    en_fix = {e: 0 for e in eqs}
    for a, b in fix:
        if a in idx:
            en_fix[a] += 1
        if b in idx:
            en_fix[b] += 1
        sa = float(s.get(a, 1.0))
        sb = float(s.get(b, 1.0))
        pa = (1 - pdraw) * (sa * 1.22) / (sa * 1.22 + sb)  # ventaja de localía
        u = rng.random(n)
        ga = u < pa
        gb = u >= pa + pdraw
        if a in idx:
            pts[:, idx[a]] += np.where(ga, 3, np.where(gb, 0, 1))
        if b in idx:
            pts[:, idx[b]] += np.where(gb, 3, np.where(ga, 0, 1))
    for e in eqs:
        extra = max(0, rest.get(e, 0) - en_fix[e])
        if extra:
            pa = (1 - pdraw) * s[e] / (s[e] + 1.0)
            u = rng.random((n, extra))
            pts[:, idx[e]] += np.where(u < pa, 3, np.where(u < pa + pdraw, 1, 0)).sum(axis=1)
    key = pts + dg0[None, :] * 1e-4 + rng.random((n, len(eqs))) * 1e-7
    pos = np.argsort(np.argsort(-key, axis=1), axis=1) + 1
    bandas = []
    prev = 0
    for h, nombre, _c in sorted(zonas or [], key=lambda z: z[0]):
        bandas.append((prev + 1, h, nombre)); prev = h
    rows = []
    orden = sorted(eqs, key=lambda e: (-base[e]["pts"], -base[e].get("dg", 0)))
    for e in orden:
        p = pos[:, idx[e]]
        row = {"Equipo": e, "PTS": base[e]["pts"], "PJ": int(base[e].get("pj", 0)),
               "1º %": round(100 * float((p == 1).mean()), 1)}
        for lo, hi, nombre in bandas:
            row[f"{nombre} %"] = round(100 * float(((p >= lo) & (p <= hi)).mean()), 1)
        if not bandas:
            row["Top 3 %"] = round(100 * float((p <= 3).mean()), 1)
        rows.append(row)
    out = pd.DataFrame(rows)
    checks = {}
    for lo, hi, nombre in bandas:
        observed = float(((pos >= lo) & (pos <= hi)).mean(axis=0).sum())
        expected = float(hi - lo + 1)
        if not np.isclose(observed, expected, atol=1e-10):
            raise AssertionError(f"Invariante Monte Carlo rota en {nombre}: {observed} != {expected}")
        checks[nombre] = {"observado": observed, "cupos": expected}
    out.attrs["mc_invariants"] = checks
    return out

NOTA_MC_LIGA = ("_Estimación por simulación (6.000 torneos): la fuerza de cada equipo sale de sus puntos por "
                "partido (ponderando la forma reciente si hay resultados), con los cruces reales del fixture, "
                "ventaja de localía y rival promedio en lo demás. Es una guía para la nota, no un pronóstico: "
                "no ve lesiones ni bajas._")

def liga_proyeccion_df(base, rest):
    rows = []
    for e, d in base.items():
        pj = d.get("pj", 0); ppg = (d["pts"] / pj) if pj else 0.0; r = rest.get(e, 0)
        rows.append({"Equipo": e, "PJ": pj, "PTS": d["pts"], "Pts/partido": round(ppg, 2), "Restan": r,
                     "Proyección (ritmo)": round(d["pts"] + ppg * r, 1), "Techo": d["pts"] + 3 * r})
    return pd.DataFrame(rows).sort_values(["Proyección (ritmo)", "PTS"], ascending=False).reset_index(drop=True)

def liga_comparar_df(a, b, base, rest, zonas):
    t = liga_tabla_df(base).set_index("Equipo")
    def fila(e):
        pos = int(t.loc[e, "Pos"]); pj = base[e].get("pj", 0); r = rest.get(e, 0)
        z = zona_de(pos, zonas)[0] if zonas else "—"
        return {"Posición": pos, "Puntos": base[e]["pts"], "PJ": pj, "DG": base[e].get("dg", 0),
                "Pts/partido": round(base[e]["pts"] / pj, 2) if pj else 0.0,
                "Restan": r, "Techo": base[e]["pts"] + 3 * r, "Zona hoy": z}
    fa, fb = fila(a), fila(b)
    return pd.DataFrame([{"Dato": k, a: fa[k], b: fb[k]} for k in fa])

def chances_mc(equipo, eqs, jug, pen, n=_LPF_PUBLIC_MC_RUNS):
    """Chances de clasificar sin enumeración: simulación con fuerza estimada. Devuelve (pct, df)."""
    d = DIRECTO()
    f = fuerza_desde_stats(eqs, jug)
    df = probabilidades(eqs, jug, pen, n=n, fuerza=f)
    col = "1º %" if d == 1 else ("Top 2 %" if d == 2 else "Top 3 %")
    fila = df[df["Equipo"] == equipo]
    pct = float(fila[col].iloc[0]) if len(fila) else 0.0
    return pct, df

def placa_chances_mc_png(equipo, pct, nota="Estimación por simulación", verdict_override=None):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from io import BytesIO
    verdict, _ = _chances_label(pct, {})
    if verdict_override:
        verdict = str(verdict_override)
    fig, ax = plt.subplots(figsize=(7.2, 2.2), dpi=200)
    cmap = LinearSegmentedColormap.from_list("c", ["#b71c1c", "#ef6c00", "#f9a825", "#7aa53d", "#1b5e20"])
    ax.imshow(np.linspace(0, 1, 256).reshape(1, -1), extent=[0, 100, 0, 1], aspect="auto", cmap=cmap)
    ax.plot([pct], [1.12], marker="v", markersize=18, color="#1a1a2e", clip_on=False)
    ax.text(pct, 1.45, verdict, ha="center", va="bottom", fontsize=15, fontweight="bold", color="#1a1a2e", clip_on=False)
    for x, lab in [(10, "Casi nada"), (30, "Difícil"), (50, "Parejo"), (70, "Probable"), (90, "Casi seguro")]:
        ax.text(x, -0.22, lab, ha="center", va="top", fontsize=9.5, color="#444")
    ax.set_xlim(0, 100); ax.set_ylim(-1.4, 2.3); ax.axis("off")
    ax.set_title(f"¿Cómo viene {display_team(equipo)}?", fontsize=15, fontweight="bold", color="#1a1a2e", loc="left", y=0.92)
    ax.text(50, -0.62, nota, ha="center", va="top", fontsize=10.5, style="italic", color="#555")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.3); plt.close(fig)
    return buf.getvalue()

def partidos_desde_url(url):
    """Descarga una página y delega la matriz equipo × equipo a un parser puro."""
    try:
        html = fetch_url_text(url, timeout=30)
    except Exception as exc:
        return [], [], f"No pude descargar la página: {exc}", ""
    return parse_cross_table_html(html)


def tabla_desde_url(url):
    """Descarga una página y delega la tabla de posiciones a un parser puro."""
    try:
        html = fetch_url_text(url, timeout=30)
    except Exception as exc:
        return "", f"No pude descargar la página: {exc}"
    return parse_standings_table_html(html)


# ═══ API ESPN (gratis, sin token) — incluye Liga Argentina y ligas que no están en football-data ═══

ESPN_LIGAS = {
    "Argentina · Liga Profesional": "arg.1",
    "Argentina · Copa Argentina": "arg.copa",
    "Inglaterra · Premier League": "eng.1",
    "España · LaLiga": "esp.1",
    "Italia · Serie A": "ita.1",
    "Alemania · Bundesliga": "ger.1",
    "Francia · Ligue 1": "fra.1",
    "EE.UU. · MLS": "usa.1",
    "México · Liga MX": "mex.1",
    "Copa Libertadores": "conmebol.libertadores",
    "Copa Sudamericana": "conmebol.sudamericana",
    "Champions League": "uefa.champions",
    "Mundial FIFA": "fifa.world",
}


FUTBOLARGENTINO_ZONES_URL = (
    "https://www.futbolargentino.com/primera-division/"
    "clausura/tabla-de-posiciones"
)
FUTBOLARGENTINO_ANNUAL_URL = (
    "https://www.futbolargentino.com/primera-division/"
    "tabla-general/tabla-de-posiciones"
)
FUTBOLARGENTINO_RESULTS_URL = (
    "https://www.futbolargentino.com/primera-division/"
    "resultados"
)
FUTBOLARGENTINO_RESULTS_URLS = (
    FUTBOLARGENTINO_RESULTS_URL,
    "https://www.futbolargentino.com/primera-division/clausura/resultados",
)
FUTBOLARGENTINO_REFERER = "https://www.futbolargentino.com/primera-division/"
LPF_OFFICIAL_PRIMERA_URL = "https://www.ligaprofesional.ar/notas/primera/"
LPF_OFFICIAL_PRIMERA_PAGES = tuple(
    LPF_OFFICIAL_PRIMERA_URL if page == 1 else f"{LPF_OFFICIAL_PRIMERA_URL}page/{page}/"
    for page in range(1, 7)
)
LPF_SNAPSHOT_MAX_AGE_HOURS = 168  # una semana; después obliga a revisar/cargar manualmente


@st.cache_data(ttl=600, show_spinner=False)
def _standings_html_get(url, referer="", timeout=30, retries=1):
    """Cache de UI sobre el transporte HTTP puro."""
    return fetch_html(url, referer=referer, timeout=timeout, retries=retries)


def futbolargentino_zones(timeout=30):
    """Carga las dos zonas; el fetch y el parser viven en capas separadas."""
    html, final_url = _standings_html_get(
        FUTBOLARGENTINO_ZONES_URL,
        FUTBOLARGENTINO_REFERER,
        timeout=timeout,
    )
    return parse_futbolargentino_zones_html(html), final_url

def futbolargentino_annual(timeout=30):
    """Carga la Tabla Anual; el fetch y el parser viven en capas separadas."""
    html, final_url = _standings_html_get(
        FUTBOLARGENTINO_ANNUAL_URL,
        FUTBOLARGENTINO_REFERER,
        timeout=timeout,
    )
    return parse_futbolargentino_annual_html(html), final_url

def lpf_official_results(zones, baseline_played=None, timeout=30):
    """Carga marcadores explícitos desde las notas oficiales de Primera.

    Recorre páginas de noticias en orden reciente y sólo descarga artículos cuyos
    títulos parecen cierres/resultados. Se detiene cuando, junto con la base validada,
    ya hay suficientes parejas para explicar los PJ publicados. La reconciliación
    exacta posterior sigue siendo la que decide si la foto es aceptable.
    """
    expected = expected_played_count(zones)
    baseline = _merge_lpf_results(baseline_played or [])
    baseline_pairs = {(l, v) for l, v, _gl, _gv in baseline}
    records = []
    seen_articles = set()
    errors = []
    last_url = LPF_OFFICIAL_PRIMERA_URL

    for listing_url in LPF_OFFICIAL_PRIMERA_PAGES:
        listing_transport = fetch_html_pages(
            (listing_url,),
            referer=LPF_OFFICIAL_PRIMERA_URL,
            timeout=timeout,
            get_html=_standings_html_get,
        )
        attempt = (listing_transport.get("attempts") or [{}])[0]
        if attempt.get("error"):
            errors.append(f"{listing_url}: {attempt['error']}")
            continue
        last_url = attempt.get("final_url") or listing_url
        try:
            links = parse_lpf_official_listing_html(
                attempt.get("html") or "", base_url=last_url
            )
        except Exception as exc:
            errors.append(f"{listing_url}: {exc}")
            continue
        article_urls = [
            item["url"] for item in links
            if item.get("url") and item["url"] not in seen_articles
        ]
        seen_articles.update(article_urls)
        if article_urls:
            article_transport = fetch_html_pages(
                tuple(article_urls),
                referer=last_url,
                timeout=timeout,
                get_html=_standings_html_get,
            )
            for article in article_transport.get("attempts") or []:
                if article.get("error"):
                    errors.append(f"{article.get('source_url')}: {article['error']}")
                    continue
                try:
                    records.extend(parse_lpf_official_results_article_html(
                        article.get("html") or "",
                        canon_club=canon_club,
                        official_fixture=LPF_FIXTURE,
                        source_url=article.get("final_url") or article.get("source_url") or "",
                    ))
                except Exception as exc:
                    errors.append(f"{article.get('source_url')}: {exc}")

        merged_records = merge_match_records(records)
        played, pending = played_pending_from_records(merged_records)
        union_pairs = baseline_pairs | {(l, v) for l, v, _gl, _gv in played}
        if expected is not None and len(union_pairs) >= expected:
            return played, pending, last_url

    merged_records = merge_match_records(records)
    played, pending = played_pending_from_records(merged_records)
    if not played:
        raise RuntimeError(
            "; ".join(errors[:3])
            or "no pude identificar marcadores del Clausura en las notas oficiales de Primera"
        )
    return played, pending, last_url


def futbolargentino_fixture(zones, timeout=30):
    """Carga resultados y programación del Clausura desde FutbolArgentino.com.

    La orquestación HTTP vive en :mod:`lpf_http`; este wrapper conserva el cache de
    Streamlit, delega el parsing al adaptador existente y mantiene la validación
    histórica de cobertura antes de entregar jugados y pendientes.
    """
    transport = fetch_futbolargentino_results_pages(
        FUTBOLARGENTINO_RESULTS_URLS,
        referer=FUTBOLARGENTINO_REFERER,
        timeout=timeout,
        get_html=_standings_html_get,
    )

    records = []
    final_urls = []
    errors = []
    for attempt in transport["attempts"]:
        source_url = attempt["source_url"]
        if attempt["error"]:
            errors.append(f"{source_url}: {attempt['error']}")
            continue
        try:
            parsed = parse_futbolargentino_results_html(
                attempt["html"],
                canon_club=canon_club,
                official_fixture=LPF_FIXTURE,
            )
            records.extend(parsed)
            final_urls.append(attempt["final_url"])
        except Exception as exc:
            errors.append(f"{source_url}: {exc}")

    if not records:
        raise RuntimeError("; ".join(errors[:2]) or "no se obtuvieron partidos")

    # No exigir aquí que una sola respuesta explique todos los PJ: durante una
    # actualización el sitio puede servir 42, 43 y 44 partidos desde nodos CDN
    # distintos. El reconciliador transaccional decide después si la combinación
    # completa reproduce exactamente PJ, puntos, GF, GC y DG.
    records = validate_fixture_records(
        records,
        official_fixture=LPF_FIXTURE,
        expected_played=None,
    )
    played, pending = played_pending_from_records(records)
    # No descartar una fuente porque tenga más finales que la tabla de posiciones.
    # Ese es precisamente el caso que ocurre cuando un pendiente termina y el feed
    # de resultados se actualiza antes que el de standings. La reconciliación se hace
    # después, de forma transaccional, y sólo si los marcadores avanzan la tabla sin
    # contradecir ninguno de sus datos ya publicados.
    return played, pending, " · ".join(dict.fromkeys(final_urls))


def _save_lpf_snapshot(zones, annual, source_name):
    """Guarda la última foto válida en sesión y, si se puede, en disco."""
    payload = build_table_backup(zones, annual, source_name)
    st.session_state["LPF_LAST_VALID_SNAPSHOT"] = payload
    try:
        write_table_backup(payload)
    except Exception as exc:
        # En algunos hostings el filesystem es efímero o de sólo lectura. La sesión
        # sigue conservando la foto y se informa el detalle sin bloquear la carga.
        return f"No pude guardar el respaldo en disco: {exc}"
    return ""


def _set_lpf_source_meta(*, source_name, sources=(), warnings=(), updated_at=None, data_as_of=None):
    """Guarda metadatos de procedencia sin inventar timestamps ausentes."""
    st.session_state.LPF_SOURCE_META = {
        "source_name": str(source_name or "Estado actual de Streamlit"),
        "source_updated_at": updated_at,
        "data_as_of": data_as_of or updated_at,
        "sources": [str(value) for value in sources if str(value).strip()],
        "warnings": [str(value) for value in warnings if str(value).strip()],
    }


def _load_lpf_snapshot(max_age_hours=LPF_SNAPSHOT_MAX_AGE_HOURS):
    """Recupera la última foto válida delegando persistencia fuera de Streamlit."""
    return load_table_backup(
        session_payload=st.session_state.get("LPF_LAST_VALID_SNAPSHOT"),
        max_age_hours=max_age_hours,
    )

def _annual_fallback_candidates():
    """Candidatos locales de Anual; la política de selección vive fuera de Streamlit."""
    candidates = [("Tabla Anual de la sesión", st.session_state.get("LPF_ANUAL") or {})]
    try:
        embedded = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]
    except Exception:
        embedded = {}
    candidates.append(("Tabla Anual incluida en la aplicación", embedded))
    return candidates


def lpf_tables_with_fallback(liga="arg.1", timeout=30):
    """Obtiene candidatos y delega la prioridad/fallback a una política pura."""
    espn_zones, espn_error = espn_lpf_zonas(liga, timeout=timeout)

    fa_zones, fa_annual = {}, {}
    fa_zones_error = None
    fa_annual_error = None
    try:
        fa_zones, _ = futbolargentino_zones(timeout=timeout)
    except Exception as exc:
        fa_zones_error = str(exc)
    try:
        fa_annual, _ = futbolargentino_annual(timeout=timeout)
    except Exception as exc:
        fa_annual_error = str(exc)

    snap_zones, snap_annual, snap_source, age_hours, snap_error = _load_lpf_snapshot()
    selected = select_lpf_tables(
        espn_zones=espn_zones,
        espn_error=espn_error,
        fa_zones=fa_zones,
        fa_zones_error=fa_zones_error,
        fa_annual=fa_annual,
        fa_annual_error=fa_annual_error,
        snapshot_zones=snap_zones,
        snapshot_annual=snap_annual,
        snapshot_source=snap_source,
        snapshot_age_hours=age_hours,
        snapshot_error=snap_error,
        annual_fallbacks=_annual_fallback_candidates(),
    )

    warnings = list(selected["warnings"])
    if selected["save_snapshot"]:
        disk_warning = _save_lpf_snapshot(
            selected["zones"], selected["annual"], selected["source_name"]
        )
        if disk_warning:
            warnings.append(disk_warning)

    return (
        selected["zones"],
        selected["annual"],
        selected["source_name"],
        warnings,
        selected["error"],
    )


def lpf_zones_with_fallback(liga="arg.1", timeout=30):
    """Compatibilidad con llamadas anteriores: devuelve sólo las zonas."""
    zones, _annual, source_name, warnings, error = lpf_tables_with_fallback(
        liga=liga,
        timeout=timeout,
    )
    return zones, source_name, warnings, error


@st.cache_data(ttl=600, show_spinner=False)
def _espn_get(url, timeout=30, retries=2):
    """Cache de UI sobre el transporte HTTP puro de ESPN."""
    return fetch_espn_json(url, timeout=timeout, retries=retries)

def espn_tabla(liga, timeout=30):
    """Tabla de posiciones desde ESPN. Devuelve (base, zonas_sugeridas_txt, error)."""
    lg = (liga or "").strip()
    if not lg:
        return {}, "", "Indicá el código de liga (ej.: arg.1)."
    try:
        data = _espn_get(
            f"https://site.api.espn.com/apis/v2/sports/soccer/{lg}/standings",
            timeout,
        )
    except Exception as exc:
        return {}, "", f"No pude obtener la tabla desde ESPN. {exc}"
    base, zones_text, error = parse_espn_table_payload(data, lg)
    if error:
        return {}, "", error
    return base, zones_text, None

def espn_fixture(liga, dias=120, timeout=30, max_req=30, desde=None):
    """Trae scoreboards por HTTP y delega su interpretacion al adaptador puro."""
    lg = (liga or "").strip()
    if not lg:
        return [], [], "", "Indicá el código de liga."

    try:
        window = fetch_espn_scoreboard_window(
            lg, dias=dias, timeout=timeout, max_req=max_req, desde=desde, get_json=_espn_get
        )
    except Exception as exc:
        return [], [], "", f"No pude obtener el fixture desde ESPN. {exc}"

    parsed = parse_espn_scoreboard_payloads(
        window["payloads"],
        initial_event_meta=st.session_state.get("LPF_EVENT_META") or {},
        initial_schedule=st.session_state.get("LPF_SCHEDULE") or {},
    )
    st.session_state["LPF_SCHEDULE"] = parsed["schedule"]
    st.session_state["LPF_EVENT_META"] = parsed["event_meta"]
    st.session_state["LPF_RESULTS_COVERAGE"] = {
        "league": lg,
        "from": window["start_date"].isoformat(),
        "to": window["end_date"].isoformat(),
        "requests": window["requests"],
        "failed_chunks": window["failed_chunks"],
    }
    globals()["_ESPN_DIA"] = {**(globals().get("_ESPN_DIA") or {}), **parsed["day_map"]}
    globals()["_ESPN_FECHA_HORA"] = {
        **(globals().get("_ESPN_FECHA_HORA") or {}),
        **parsed["datetime_map"],
    }

    played = parsed["played"]
    pending = parsed["pending"]
    notes = [f"resultados cotejados desde {window['start_date']:%d/%m/%Y}"]
    if window["limited"]:
        notes.append(f"consulta limitada a {window['requests']} bloques")
    if window["failed_chunks"]:
        notes.append(f"{window['failed_chunks']} bloque(s) no respondieron")
    note = "(" + " · ".join(notes) + ")"

    if not played and not pending:
        return [], [], note, (
            "ESPN no devolvió partidos en la ventana consultada. "
            "Revisá el código de liga o cargá los resultados manualmente."
        )
    return played, pending, note, None

def espn_copa_argentina_vivos(timeout=30):
    """Coteja los clubes que aparecen en partidos pendientes de la Copa Argentina.

    Es una ayuda de actualización, no una fuente única. Si ESPN no devuelve al
    menos dos cruces pendientes, la función no reemplaza la foto vigente.
    """
    _jug, pen, nota, err = espn_fixture("arg.copa", dias=365, timeout=timeout, max_req=80)
    if err:
        return [], "", err
    vivos = []
    for local, visita in pen:
        for team in (canon_club(local), canon_club(visita)):
            if team and team not in vivos:
                vivos.append(team)
    if len(vivos) < 4:
        return [], nota, ("ESPN respondió, pero no devolvió una fase pendiente completa. "
                          "No reemplacé la lista actual; revisala contra el cuadro oficial.")
    return vivos, nota, None

def espn_lpf_zonas(liga="arg.1", timeout=30):
    """Trae las zonas ESPN y delega la adaptacion del JSON a una funcion pura."""
    lg = (liga or "arg.1").strip()
    try:
        data = _espn_get(
            f"https://site.api.espn.com/apis/v2/sports/soccer/{lg}/standings",
            timeout,
        )
    except Exception as exc:
        return {}, f"No pude obtener las zonas desde ESPN. {exc}"
    zones, error = parse_espn_lpf_zones_payload(data, lg)
    return zones, error

def traer_de_apify(token, actor, input_json, timeout=120):
    """Corre un actor de Apify en modo sync y devuelve los items del dataset (lista de dicts)."""
    import requests as _rq, json as _json
    act = (actor or "").strip().replace("/", "~")
    if not act:
        raise ValueError("Indicá el actor (ej.: crawlerbros/flashscore-scraper).")
    try:
        inp = _json.loads(input_json) if str(input_json or "").strip() else {}
    except Exception:
        raise ValueError("El input del actor no es JSON válido.")
    url = f"https://api.apify.com/v2/acts/{act}/run-sync-get-dataset-items?token={token}&format=json"
    r = _rq.post(url, json=inp, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Apify respondió {r.status_code}: {r.text[:300]}")
    data = r.json()
    if isinstance(data, dict):
        for k in ("items", "data"):
            if isinstance(data.get(k), list):
                return data[k]
    return data if isinstance(data, list) else []

def _match_eq(nombre, equipos):
    """Empareja un nombre externo (Flashscore/SofaScore) con los equipos ya cargados, tolerando variantes."""
    nn = _zlow(nombre)
    for e in equipos:
        if _zlow(e) == nn:
            return e
    for e in equipos:
        ee = _zlow(e)
        if ee in nn or nn in ee:
            return e
    tn = set(nn.split())
    mejor, score = None, 0
    for e in equipos:
        s = len(tn & set(_zlow(e).split()))
        if s > score:
            mejor, score = e, s
    return mejor if score else None

def mapear_fixture(pend, equipos):
    out, caidos = [], []
    for a, b in pend:
        ca_, cb_ = canon_club(a), canon_club(b)
        ma = ca_ if ca_ in equipos else _match_eq(a, equipos)
        mb = cb_ if cb_ in equipos else _match_eq(b, equipos)
        if ma and mb and ma != mb:
            out.append((ma, mb))
        else:
            caidos.append(f"{a} vs {b}")
    return out, caidos

def importar_partidos_json(texto, filtro=""):
    """Convierte un export de Apify (JSON/NDJSON/CSV) u otra fuente en (jugados, pendientes, ligas, error).
    Reconoce homeTeam/awayTeam/homeScore/awayScore/status/league-tournament con varios alias."""
    import json as _json, csv as _csv, io as _io
    txt = (texto or "").strip()
    if not txt:
        return [], [], {}, "Pegá el contenido exportado (JSON o CSV)."
    recs = []
    try:
        data = _json.loads(txt)
        if isinstance(data, dict):
            for k in ("items", "data", "results", "matches"):
                if isinstance(data.get(k), list):
                    data = data[k]; break
        if isinstance(data, list):
            recs = [r for r in data if isinstance(r, dict)]
    except Exception:
        nd = []
        for ln in txt.splitlines():
            ln = ln.strip().rstrip(",")
            if ln.startswith("{") and ln.endswith("}"):
                try: nd.append(_json.loads(ln))
                except Exception: pass
        recs = nd
    if not recs and ("," in txt or ";" in txt):
        try:
            head = txt.splitlines()[0]
            delim = ";" if head.count(";") > head.count(",") else ","
            recs = [dict(r) for r in _csv.DictReader(_io.StringIO(txt), delimiter=delim)]
        except Exception:
            recs = []
    if not recs:
        return [], [], {}, "No reconocí el formato. Pegá el JSON del actor (lista de partidos) o un CSV con encabezado."
    def pick(r, *keys):
        low = {str(k).lower(): v for k, v in r.items()}
        for k in keys:
            v = low.get(k.lower())
            if v not in (None, ""):
                return v
        return None
    fl = _zlow(filtro or "")
    jugados, pendientes, ligas = [], [], {}
    for r in recs:
        liga = str(pick(r, "league", "tournament", "liga", "competition", "torneo") or "").strip()
        if liga:
            ligas[liga] = ligas.get(liga, 0) + 1
        if fl and fl not in _zlow(liga):
            continue
        h = pick(r, "homeTeam", "home_team", "home", "local", "homeName")
        a = pick(r, "awayTeam", "away_team", "away", "visitante", "awayName")
        if not h or not a:
            continue
        h, a = str(h).strip(), str(a).strip()
        hs, asn = pick(r, "homeScore", "home_score", "golesLocal"), pick(r, "awayScore", "away_score", "golesVisitante")
        stt = _zlow(str(pick(r, "status", "estado") or ""))
        try:
            hs, asn = int(str(hs).strip()), int(str(asn).strip())
        except Exception:
            hs = asn = None
        fin = any(w in stt for w in ("finish", "final", "termin", "ended", "after", "ft"))
        if hs is not None and asn is not None and (fin or not stt):
            jugados.append((h, a, hs, asn))
        elif not any(w in stt for w in ("postpon", "cancel", "aband", "suspend", "walkover", "aplaz")):
            pendientes.append((h, a))
    return jugados, pendientes, ligas, ""

# ── PROMEDIOS (descenso a la argentina: puntos ÷ partidos de las últimas temporadas) ──



def _prom_rangos(base, rest, prev):
    """Por equipo: promedio actual, mínimo final (perdiendo todo) y máximo final (ganando todo)."""
    eqs = list(base.keys())
    mapped = {}
    asign = _asignar_nombres(list((prev or {}).keys()), eqs)
    for nombre, (pp, jp) in (prev or {}).items():
        m = asign.get(nombre)
        if m:
            mapped[m] = (pp, jp)
    out = {}
    for e in eqs:
        pa, ja = base[e]["pts"], base[e].get("pj", 0)
        pp, jp = mapped.get(e, (0, 0))
        tp, tj = pa + pp, ja + jp
        r = rest.get(e, 0)
        hoy = tp / tj if tj else 0.0
        piso = tp / (tj + r) if (tj + r) else 0.0
        techo = (tp + 3 * r) / (tj + r) if (tj + r) else 0.0
        out[e] = {"hoy": hoy, "piso": piso, "techo": techo, "tp": tp, "tj": tj, "r": r, "con_prev": e in mapped}
    return out

def promedios_df(base, rest, prev):
    P = _prom_rangos(base, rest, prev)
    rows = [{"Equipo": e, "PROMEDIO": round(d["hoy"], 3), "Pts": d["tp"], "PJ": d["tj"],
             "Mínimo final": round(d["piso"], 3), "Máximo final": round(d["techo"], 3),
             "Previas": "sí" if d["con_prev"] else "solo actual"} for e, d in P.items()]
    df = pd.DataFrame(rows).sort_values("PROMEDIO", ascending=False).reset_index(drop=True)
    df.insert(0, "Pos", range(1, len(df) + 1))
    return df

def promedio_que_necesita_texto(e, base, rest, prev, k=1, pend=None):
    """Explica el descenso por promedios con un total seguro colectivo.

    El mínimo y el máximo individual son exactos: corresponden a perder o ganar todo.
    El cálculo del total seguro para salvarse sin depender descuenta los cruces entre
    rivales mediante ``safe_average_guarantee_points`` y considera adverso un empate de
    promedio. Puede pedir puntos de más, por lo que no necesariamente es el mínimo que asegura.
    """
    if e not in base:
        return f"No encuentro a {e} en la tabla cargada."
    pend = list(pend or [])
    P = _prom_rangos(base, rest, prev)
    n = len(P)
    d = P[e]
    df = promedios_df(base, rest, prev)
    pos = int(df[df["Equipo"] == e]["Pos"].iloc[0])
    abajo_seguro = sorted(
        [x for x in P if x != e and P[x]["techo"] < d["piso"]],
        key=lambda x: P[x]["techo"],
    )
    arriba_seguro = sorted(
        [x for x in P if x != e and P[x]["piso"] > d["techo"]],
        key=lambda x: -P[x]["piso"],
    )
    L = [
        f"**¿{e} y el descenso por promedios?** (descienden los {k} peores)",
        f"Está {pos}º de {n} con promedio **{_fmt_num_es(d['hoy'], 3)}** "
        f"({d['tp']} pts en {d['tj']} PJ, contando temporadas previas). "
        f"Perdiendo todo baja a **{_fmt_num_es(d['piso'], 3)}**; ganando todo sube a **{_fmt_num_es(d['techo'], 3)}**.",
    ]

    if len(abajo_seguro) >= k:
        muestra = ", ".join(abajo_seguro[:4])
        L.append(
            f"✅ **Ya está a salvo del promedio:** aunque pierda todo lo que le queda, {muestra} "
            "no pueden alcanzarlo ni ganando todo: sus máximos posibles quedan por debajo del mínimo final de este equipo."
        )
    elif len(arriba_seguro) >= n - k:
        L.append(
            f"❌ **Condenado por promedio:** aun ganando todo llega a {_fmt_num_es(d['techo'], 3)} y ya hay "
            f"{len(arriba_seguro)} equipos cuyos mínimos finales quedan por encima de ese número."
        )
    else:
        pelea = sorted(
            [
                x for x in P if x != e
                and not (P[x]["techo"] < d["piso"])
                and not (P[x]["piso"] > d["techo"])
            ],
            key=lambda x: P[x]["hoy"],
        )
        if pelea:
            L.append("⚔️ **Pelea mano a mano con:** " + ", ".join(pelea[:6]) + ".")

        totals = {x: P[x]["tp"] for x in P}
        played = {x: P[x]["tj"] for x in P}
        pts_need = safe_average_guarantee_points(
            totals,
            played,
            rest,
            pend,
            e,
            k,
        )
        max_points = 3 * d["r"]
        if pts_need is not None and pts_need <= max_points:
            final_den = d["tj"] + d["r"]
            final_avg = (d["tp"] + pts_need) / final_den if final_den else 0.0
            if pts_need == 0:
                L.append(
                    "✅ **Total seguro:** aun sin sumar más puntos, los cruces pendientes impiden que "
                    f"todos los rivales necesarios lo alcancen. Su promedio final quedaría en {_fmt_num_es(final_avg, 3)}."
                )
            else:
                L.append(
                    f"Para salvarse **sin depender de nadie**, el total seguro exige sumar "
                    f"**{_texto_cantidad(pts_need, 'punto')}** de los {max_points} en juego y terminar con "
                    f"un promedio de al menos **{_fmt_num_es(final_avg, 3)}**."
                )
            L.append(
                "La cuenta evalúa los cocientes finales con sus denominadores reales y descuenta los "
                "enfrentamientos entre rivales: cuando dos competidores se cruzan, no pueden ganar ambos. "
                "Un empate de promedio se considera desfavorable para no declarar una salvación prematura."
            )
        else:
            L.append(
                "El total seguro queda fuera de su alcance incluso ganando todo. Eso **no prueba por sí "
                "solo** que su máximo sea insuficiente: para afirmarlo hace falta un chequeo exacto del fixture."
            )

        # En el escenario explícito de ganar todos, cada rival directo pierde ese
        # encuentro y no puede conservar su techo individual general.
        cruces_con_equipo = {}
        for local, visitante in pend:
            if e not in (local, visitante):
                continue
            rival = visitante if local == e else local
            if rival in P and rival != e:
                cruces_con_equipo[rival] = cruces_con_equipo.get(rival, 0) + 1
        if cruces_con_equipo:
            condicionados = []
            for rival, cruces in cruces_con_equipo.items():
                rd = P[rival]
                den = rd["tj"] + rd["r"]
                general = rd["techo"]
                condicionado = (
                    (rd["tp"] + 3 * max(0, rd["r"] - cruces)) / den
                    if den else 0.0
                )
                condicionados.append((rival, condicionado, general))
            condicionados.sort(key=lambda item: (-item[1], item[0]))
            muestra = " · ".join(
                f"{rival}: {_fmt_num_es(cond, 3)} condicionado (techo general {_fmt_num_es(general, 3)})"
                for rival, cond, general in condicionados[:6]
            )
            if len(condicionados) > 6:
                muestra += f" · y {len(condicionados) - 6} más"
            L.append(
                f"**Si {e} gana todos:** sus rivales directos pierden necesariamente ese partido, por lo que "
                f"sus techos bajan. {muestra}."
            )

    L.append(
        "_El mínimo y el máximo individual de promedio son exactos: perder todo o ganar todo. El total seguro "
        "puede pedir algún punto de más; por eso no se presenta como el mínimo que asegura. Descuenta los cruces "
        "entre rivales y, cuando se supone que el equipo gana todo, también las derrotas obligatorias de sus "
        "rivales directos. Los recién ascendidos computan sólo la temporada actual. Cargá las temporadas previas "
        "en el panel «📉 Promedios»._"
    )
    return "\n\n".join(L)

# ═══════════════════════════════════════════════════════════════════════════════════
# LPF 2026 — Liga Profesional Argentina (Reglamento Torneos Primera División 2026)
# Zonas A y B de 15, una rueda, 16 fechas. Top 8 de cada zona → Octavos (art. 8.2/14.2).
# Tabla General 2026 = fase de zonas del Apertura + fase de zonas del Clausura (art. 24.1).
# ═══════════════════════════════════════════════════════════════════════════════════

LPF_ZONAS_PLAYOFF = [(8, "Playoffs", "#1b5e20"), (15, "Afuera", "#eef1e8")]
LPF_OCTAVOS = [(1, "A", 8, "B"), (1, "B", 8, "A"), (2, "A", 7, "B"), (2, "B", 7, "A"),
               (3, "A", 6, "B"), (3, "B", 6, "A"), (4, "A", 5, "B"), (4, "B", 5, "A")]

def lpf_zona_de_equipo(e, Z):
    for lab, base in (Z or {}).items():
        if e in base:
            return lab
    return None

def lpf_playoffs_texto(equipo, Z, rest, pend=None, jugados=None):
    """Informe de playoffs con proyección, total seguro y mínimo exacto separados."""
    lab = lpf_zona_de_equipo(equipo, Z)
    if not lab:
        return f"No encuentro a **{equipo}** en las zonas cargadas."
    base = Z[lab]
    k = _LPF_TOP_OCTAVOS
    pts = {e: base[e]["pts"] for e in base}
    gx = rest.get(equipo, 0)
    mio = pts[equipo]
    pj = int(base[equipo].get("pj", 0))
    pos = 1 + sum(
        1 for x in base if x != equipo and
        (pts[x], base[x].get("dg", 0), base[x].get("gf", 0)) >
        (mio, base[equipo].get("dg", 0), base[equipo].get("gf", 0))
    )
    estado = _liga_in_out(equipo, base, rest, k)
    strength_base = {name: row for zona in (Z or {}).values() for name, row in zona.items()}
    contexto, historial = _armar_contexto_competitivo(
        equipo, base, pend, k, "playoffs", strength_base=strength_base, jugados=jugados
    )
    if estado == "in":
        titular = f"{equipo} ya está clasificado a los octavos."
    elif estado == "out":
        titular = f"{equipo} quedó sin chances de clasificar a los octavos."
    else:
        titular = (
            f"{equipo} sigue en carrera. La exigencia depende de la tabla actual, del fixture pendiente y de los "
            "cruces entre los equipos que pelean por entrar a los octavos."
        )
    L = [
        f"## {equipo} · Playoffs — Zona {lab}",
        f"**{titular}**",
        f"Hoy está **{pos}º** de su zona, con **{mio} puntos totales en {pj} PJ**. Le quedan **{gx} partidos por jugar** y "
        f"**{3 * gx} puntos** disponibles. Clasifican los **8 primeros**.",
    ]
    L += _copas_bloque_objetivo(
        equipo, base, rest, pend, k, "Octavos",
        contexto=contexto, historial=historial, objetivo="playoffs",
    )
    if pend:
        mis = [(b if a == equipo else a) for (a, b) in pend if equipo in (a, b)]
        if mis:
            L.append("### Partidos por jugar")
            for rival in mis:
                L.append(f"- {rival}")
    L.append("### Cómo leer estos números")
    L.append(
        "El informe separa el **corte actual**, la **proyección del modelo**, la **referencia histórica** y la "
        "**mínimo que asegura**. La proyección y el antecedente describen una exigencia posible o probable. "
        "El mínimo que asegura responde otra pregunta: cuál es el **menor puntaje alcanzable** que asegura clasificar pase lo "
        "que pase. Si ese mínimo todavía no fue comprobado por el motor exacto, no se publica como mínimo que asegura."
    )
    L.append(
        "_Art. 14.1.2: si un club termina en zona de descenso o debe jugar un desempate por el descenso, no puede "
        "jugar las instancias finales; su lugar lo ocupa el siguiente mejor ubicado de su zona._"
    )
    return editorialize_text("\n\n".join(L))

def lpf_cruces_texto(Z):
    if len(Z or {}) < 2:
        return "Necesito las dos zonas cargadas (A y B) para armar los cruces."
    ord_ = {lab: liga_tabla_df(base) for lab, base in Z.items()}
    def eq(lab, pos):
        df = ord_.get(lab)
        if df is None or len(df) < pos:
            return "—"
        r = df.iloc[pos - 1]
        return f"{r['Equipo']} ({int(r['PTS'])})"
    L = ["**Octavos de Final si la fase de zonas terminara hoy** (art. 14.2):"]
    for i, (pa, za, pb, zb) in enumerate(LPF_OCTAVOS, 1):
        L.append(f"**Partido {i}:** {pa}º Zona {za} — {eq(za, pa)}  vs  {pb}º Zona {zb} — {eq(zb, pb)}")
    L.append("_Partido único, en cancha del mejor ubicado en la fase de zonas. "
             "Cuartos: G1-G8, G2-G7, G3-G6, G4-G5 (art. 14.3)._")
    return "\n\n".join(L)

def lpf_anual_base(Z, apertura=None):
    """Tabla General autoritativa: Apertura fijo + zonas actuales.

    Streamlit sólo resuelve los candidatos de sesión; la prioridad y validación
    viven en ``lpf_qualification.annual_base``.
    """
    estado = st.session_state.get("ESTADO") or {}
    opening = apertura or estado.get("apertura") or st.session_state.get("LPF_APERTURA") or {}
    direct = estado.get("anual_directo") or st.session_state.get("LPF_ANUAL") or {}
    return _qualification_annual_base(
        Z, opening=opening, direct_annual=direct, opening_rounds=LPF_APERTURA_PJ
    )


def lpf_anual_df(Z, apertura=None):
    return liga_tabla_df(lpf_anual_base(Z, apertura))

def lpf_descenso_texto(Z, rest, apertura=None, prev=None, n_anual=1, n_prom=1, equipo=None, pend=None):
    anual = lpf_anual_base(Z, apertura)
    n = len(anual)
    if n < 4:
        return "Cargá las dos zonas para calcular el descenso."
    L = [f"**Descenso 2026** — bajan **{n_anual}** por la Tabla General (anual) y **{n_prom}** por promedios "
         f"(art. 26; la cantidad la fija el Estatuto de AFA, art. 93)."]
    if equipo:
        if equipo not in anual:
            return f"No encuentro a **{equipo}** en las zonas cargadas."
        k_salvarse = max(1, n - n_anual)
        pts_e = anual[equipo]["pts"]; gx = rest.get(equipo, 0); techo = pts_e + 3 * gx
        pos_anual = 1 + sum(1 for x in anual if x != equipo and
                            (anual[x]["pts"], anual[x].get("dg", 0), anual[x].get("gf", 0)) >
                            (pts_e, anual[equipo].get("dg", 0), anual[equipo].get("gf", 0)))
        est = _liga_in_out(equipo, anual, rest, k_salvarse)
        if est == "in":
            tit = f"{equipo} ya está salvado por la Tabla General."
        elif est == "out":
            tit = f"{equipo} no puede escapar del último puesto de la Tabla General."
        else:
            _lin = _linea_garantia(anual, rest, pend, equipo, k_salvarse)
            if (_lin + 1 - pts_e) <= 3 * gx:
                tit = (f"{equipo} tiene un total seguro de puntos al alcance para salvarse por la Tabla General, "
                       "pero el mínimo exacto todavía debe comprobarse.")
            else:
                tit = (f"{equipo} sigue en pelea por la Tabla General. El total seguro queda fuera de su techo, "
                       "pero eso no prueba que necesite ayuda: la dependencia exacta debe resolverla el motor completo.")
        L = [f"## {equipo} · Descenso 2026", f"**{tit}**",
             f"Bajan **{n_anual}** por la Tabla General y **{n_prom}** por promedios. "
             f"Hay que zafar de **las dos** tablas: alcanza con caer en una para descender.",
             f"En la anual está **{pos_anual}º de {n}** con **{pts_e} puntos** y **{gx} partidos** por jugar "
             f"({3*gx} en juego); su techo es **{techo}**."]
        L.append("## Vía 1 · Tabla General (anual)")
        L += _copas_bloque_objetivo(equipo, anual, rest, pend, k_salvarse, "Permanencia por la anual", modo="salvarse")
        L.append("## Vía 2 · Promedios")
        L.append(promedio_que_necesita_texto(equipo, anual, rest, prev or {}, n_prom, pend))
        if pend:
            mis = [(b if a == equipo else a) for (a, b) in pend if equipo in (a, b)]
            if mis:
                L.append("### Los partidos que le quedan")
                L.append(" · ".join(mis))
        L.append("### Cómo leer estos números")
        L.append("Los rangos y escenarios describen lo que todavía puede pasar. **Mínimo que asegura** se "
                 "reserva para un mínimo exacto comprobado; un total seguro que puede pedir puntos de más "
                 "no se presenta como garantía.")
        L.append("**Regla clave:** si el mismo equipo termina último en las dos tablas, desciende por promedios y el "
                 "segundo descenso pasa al siguiente peor de la anual (Estatuto AFA, art. 93).")
    else:
        dfp = promedios_df(anual, rest, prev or {})
        picture = current_relegation_picture(
            anual, dfp.to_dict("records"),
            annual_relegations=int(n_anual), average_relegations=int(n_prom),
        )
        avg_note = "" if (prev or {}) else " _(sin temporadas previas cargadas: el promedio sale solo del 2026)_"
        if picture["average_playoff"]:
            L.append(
                "**Promedios:** hay un **desempate por el descenso** entre "
                + ", ".join(picture["average_playoff"]) + "." + avg_note
            )
        elif picture["average_confirmed"]:
            L.append("**Baja por promedios si terminara hoy:** " + ", ".join(picture["average_confirmed"]) + "." + avg_note)
        if picture["annual_depends_on_average_playoff"]:
            L.append(
                "**Tabla General:** la identidad del descenso queda condicionada por el desempate de promedios. "
                "Los equipos que pueden quedar alcanzados por esa vía son: " + ", ".join(picture["annual_candidates"]) + "."
            )
        else:
            scenario = picture["annual_scenarios"][0] if picture["annual_scenarios"] else {}
            if scenario.get("annual_playoff"):
                L.append(
                    "**Tabla General:** hay un **desempate por el descenso** entre "
                    + ", ".join(scenario["annual_playoff"]) + "."
                )
            elif scenario.get("annual_confirmed"):
                L.append("**Baja por la Tabla General si terminara hoy:** " + ", ".join(scenario["annual_confirmed"]) + ".")
        if picture["average_confirmed"]:
            raw_min = min(int(row.get("pts", 0)) for row in anual.values())
            raw_bottom = [team for team, row in anual.items() if int(row.get("pts", 0)) == raw_min]
            overlap = [team for team in raw_bottom if team in set(picture["average_confirmed"])]
            if overlap:
                L.append(
                    "_" + ", ".join(overlap) + " ocupa también el fondo de la Anual: al bajar por promedios, "
                    "la plaza de la Tabla General corre al siguiente equipo según la regla de duplicación._"
                )
    L.append("_En posiciones que definen descenso, un empate en puntos NO se define por diferencia de gol: "
             "se juega un partido desempate (art. 26.2 y 111 del Reglamento General de AFA)._")
    return "\n\n".join(L)

def lpf_plazas_copas(Z, apertura=None, camps=("", "", ""), extras=("", ""), copa_reemplazo=""):
    """Wrapper Streamlit del reparto puro de plazas internacionales."""
    anual = lpf_anual_base(Z, apertura)
    replacement = copa_reemplazo or st.session_state.get("LPF_COPA_ARG_REEMPLAZO", "")
    return allocate_cup_slots(
        anual, camps=camps, extras=extras, copa_replacement=replacement
    )


def lpf_copas_texto(Z, apertura=None, camp_apertura="", camp_clausura="", camp_copa_arg="",
                    camp_lib26="", camp_sud26=""):
    if len((Z or {})) < 2:
        return "Cargá las dos zonas para calcular las plazas a las copas."
    P = lpf_plazas_copas(Z, apertura, (camp_apertura, camp_clausura, camp_copa_arg), (camp_lib26, camp_sud26))
    orden, red, n_t = P["orden"], P["reducida"], P["n_tabla_lib"]
    L = ["**Clasificación a copas 2027** (arts. 27 y 28 del Reglamento LPF 2026)"]
    L.append("### 🏆 Copa Libertadores 2027")
    for i, (e, motivo) in enumerate(P["lib"], 1):
        L.append(f"**{i}.** {e} — {motivo}")
    L.append(f"**Cupos de Libertadores que se definen por la Tabla Anual: {n_t}.** "
             f"Entran los **{n_t} mejores de la Anual que todavía no tengan plaza**. La posición mostrada siempre es la de la tabla completa. "
             "Si Apertura y Clausura tienen el mismo campeón, su plaza duplicada sí corre a la anual (art. 27.7). "
             "Una duplicación del campeón de Copa Argentina se resuelve dentro de esa Copa, no por la anual (art. 27.8).")
    sud = [e for e in red[n_t:]][:6]
    L.append("### 🥈 Copa Sudamericana 2027 (art. 28.1: los 6 mejores de la anual sin plaza en Libertadores)")
    for i, e in enumerate(sud, 1):
        L.append(f"**ARGENTINA {i}** · {e} ({orden.index(e)+1}º de la anual)")
    if P["avisos"]:
        L.append("**⚠️ Ojo:**")
        for a in P["avisos"]:
            L.append(f"- {a}")
    L.append("_Un campeón que descienda pierde la plaza y se corre el orden (art. 28.2.1); si el campeón de la Copa Argentina "
             "es del ascenso o desciende, su plaza va al mejor equipo de Primera de esa Copa (art. 28.2.2)._")
    return "\n\n".join(L)

def _lpf_clausura_candidates(Z, rest):
    """Clubes que todavía pueden terminar entre los ocho y, por lo tanto, ser campeones."""
    out = []
    for _lab, base in (Z or {}).items():
        for team in liga_tabla_df(base)["Equipo"]:
            if _liga_in_out(team, base, rest, _LPF_TOP_OCTAVOS) != "out":
                out.append(team)
    return out

def _lpf_fixed_lib_qualifiers(anual, camps=("", "", ""), extras=("", "")):
    """Wrapper Streamlit del contexto puro de clasificados fijos a Libertadores."""
    return _qualification_fixed_libertadores_qualifiers(
        anual,
        camps=camps,
        extras=extras,
        copa_replacement=st.session_state.get("LPF_COPA_ARG_REEMPLAZO", ""),
    )

def _lpf_copa_arg_alive_for_annual(anual, vivos=None):
    """Wrapper Streamlit de los equipos vivos en Copa Argentina 2026.

    Además de normalizar nombres contra la Tabla Anual, aplica como techo la
    última instancia oficialmente confirmada (cuartos). Así una sesión vieja de
    octavos no puede volver a presentar a un eliminado como posible campeón.
    Las futuras actualizaciones manuales sólo pueden reducir este conjunto.
    """
    if vivos is None:
        vivos = st.session_state.get("LPF_COPA_ARG_VIVOS") or []
    return _qualification_copa_argentina_alive(
        anual, vivos, eligible_pool=COPA_ARGENTINA_CUARTOS_2026
    )

def _lpf_copa_snapshot(updated="", source=""):
    """Wrapper Streamlit de la etiqueta de actualización de Copa Argentina."""
    updated = updated or st.session_state.get("LPF_COPA_ARG_UPDATED", "")
    source = source or st.session_state.get("LPF_COPA_ARG_SOURCE", "")
    return _qualification_copa_snapshot_label(updated, source)

def lpf_relato_libertadores_texto(Z, rest, apertura=None, camps=("", "", ""), extras=("", ""),
                                   copa_alive=None, copa_updated="", copa_source=""):
    anual = lpf_anual_base(Z, apertura)
    if not anual:
        return "No hay una Tabla Anual válida para narrar la Libertadores."
    allocation = lpf_plazas_copas(Z, apertura, camps, extras)
    fixed = _lpf_fixed_lib_qualifiers(anual, camps, extras)
    return libertadores_story(
        anual, fixed_qualified=fixed, table_slots=allocation["n_tabla_lib"],
        aperture_champion=(camps or ("", "", ""))[0],
        clausura_champion=(camps or ("", "", ""))[1],
        copa_argentina_champion=(camps or ("", "", ""))[2],
        clausura_candidates=_lpf_clausura_candidates(Z, rest),
        copa_argentina_alive=_lpf_copa_arg_alive_for_annual(anual, copa_alive),
        copa_snapshot=_lpf_copa_snapshot(copa_updated, copa_source),
    )

def lpf_relato_sudamericana_texto(Z, rest, apertura=None, camps=("", "", ""), extras=("", ""),
                                    copa_alive=None, copa_updated="", copa_source=""):
    anual = lpf_anual_base(Z, apertura)
    if not anual:
        return "No hay una Tabla Anual válida para narrar la Sudamericana."
    allocation = lpf_plazas_copas(Z, apertura, camps, extras)
    fixed = _lpf_fixed_lib_qualifiers(anual, camps, extras)
    return sudamericana_story(
        anual, fixed_qualified=fixed, table_slots_lib=allocation["n_tabla_lib"],
        aperture_champion=(camps or ("", "", ""))[0],
        clausura_champion=(camps or ("", "", ""))[1],
        clausura_candidates=_lpf_clausura_candidates(Z, rest),
        copa_argentina_alive=_lpf_copa_arg_alive_for_annual(anual, copa_alive),
        copa_snapshot=_lpf_copa_snapshot(copa_updated, copa_source),
    )

def lpf_relato_descenso_texto(Z, rest, apertura=None, prev=None, n_anual=1, n_prom=1):
    anual = lpf_anual_base(Z, apertura)
    if not anual:
        return "No hay una Tabla Anual válida para narrar el descenso."
    avg_records = []
    if prev:
        avg_records = promedios_df(anual, rest, prev).to_dict("records")
    return relegation_story(
        anual, avg_records, annual_relegations=int(n_anual), average_relegations=int(n_prom),
    )


def _combos_puntos(faltan, juegos):
    """Combinaciones (ganados, empatados) que suman **al menos** `faltan` puntos.

    La meta es un piso, no una igualdad obligatoria. Para la salida editorial se
    muestran primero los caminos más simples de leer: menos empates y más triunfos.
    Así, 21 puntos en 13 fechas aparece como siete victorias antes que cuatro
    victorias y nueve empates, sin afirmar que sea el único camino.
    """
    out = []
    for g in range(0, juegos + 1):
        # con g triunfos, empates mínimos para alcanzar la meta
        e = max(0, faltan - 3 * g)
        if e <= juegos - g:
            out.append((g, e))
    out.sort(key=lambda ge: (ge[1], -ge[0], juegos - ge[0] - ge[1]))
    return out

def _texto_cantidad(n, singular, plural=None):
    plural = plural or f"{singular}s"
    return f"{n} {singular if n == 1 else plural}"


def _minimo_puntos_alcanzable(faltan, juegos):
    """Menor suma realizable en `juegos` partidos que alcanza o supera `faltan`."""
    cs = _combos_puntos(faltan, juegos)
    return min((3 * g + e for g, e in cs), default=None)


def _texto_combos(faltan, juegos):
    cs = _combos_puntos(faltan, juegos)
    if not cs:
        return ""
    g0, e0 = cs[0]
    partes = []
    for g, e in cs[:3]:
        p = f"**{g} triunfo{'s' if g != 1 else ''}**"
        if e:
            p += f" + {e} empate{'s' if e != 1 else ''}"
        pierde = juegos - g - e
        if pierde > 0:
            p += f" y {pierde} derrota{'s' if pierde != 1 else ''}"
        elif g == juegos:
            p += " (gana todos)"
        elif e == juegos:
            p += " (empata todos)"
        else:
            p += " (gana o empata todos)"
        p += f" = {3*g + e}"
        partes.append(p)
    txt = "**Cómo llegar** (sirve alcanzar la meta *o superarla*): " + " · ".join(partes) + "."
    margen = juegos - g0 - e0
    if margen == 0:
        if len(cs) > 1:
            txt += (" Con el mínimo de triunfos no le sobra ningún partido; ganando alguno más sí puede permitirse "
                    "una derrota.")
        elif g0 == juegos:
            txt += " No tiene margen para empatar ni perder: debe ganar todos."
        elif e0 == juegos:
            txt += " No tiene margen para perder: debe empatar todos."
        else:
            txt += " No le sobra ningún partido: debe ganar o empatar todos."
    return txt





def _fmt_entero_es(value):
    """Miles con punto, como se muestran habitualmente en Argentina."""
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _armar_contexto_competitivo(equipo, base, pend, k, objetivo, strength_base=None, jugados=None):
    """Construye la capa viva de tabla + fixture y la referencia histórica.

    Si la simulación falla, el mínimo que asegura sigue disponible: esta capa es
    estimativa y nunca bloquea el informe exacto/conservador.
    """
    if not pend or equipo not in base:
        return None, None
    try:
        seed = 20260804 + {"playoffs": 11, "libertadores": 23, "sudamericana": 37}.get(objetivo, 0)
        model_strength = _fuerza_lpf(strength_base, jugados) if strength_base else None
        contexto = competition_context(
            base, pend, equipo, k, strength_base=strength_base, strength=model_strength,
            simulations=6000, seed=seed,
        )
    except Exception:
        contexto = None
    try:
        if objetivo == "playoffs":
            historial = historical_reference(objetivo, target_matches=16)
        else:
            pj_final = int(base[equipo].get("pj", 0)) + (
                int(contexto.get("games_left", 0)) if contexto else
                sum(equipo in partido for partido in (pend or []))
            )
            historial = historical_reference(objetivo, target_matches=max(1, pj_final))
    except Exception:
        historial = None
    return contexto, historial


def _filas_probabilidad_cercanas(projection, pivot, limit=4):
    rows = [row for row in (projection or {}).get("by_final_points", []) if row.get("stable")]
    if not rows:
        return []
    if pivot is None:
        pivot = (projection or {}).get("target_points_median")
    rows.sort(key=lambda row: (abs(int(row["final_points"]) - int(pivot or 0)), int(row["final_points"])))
    chosen = sorted(rows[:limit], key=lambda row: int(row["final_points"]))
    return chosen


def _lista_natural(items):
    items = [str(item) for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _contexto_competitivo_bloque(equipo, nombre_obj, objetivo, contexto, historial, *, mostrar_cruces=True, mostrar_rivales=True):
    """Separa con claridad realidad actual, proyección, historia y fixture."""
    if not contexto:
        return []
    projection = contexto.get("projection") or {}
    actual = int(contexto.get("current_cutoff_points", 0))
    mediana = projection.get("cutoff_median")
    bajo = projection.get("cutoff_low")
    alto = projection.get("cutoff_high")
    target70 = projection.get("target_70")
    target50 = projection.get("target_50")
    target85 = projection.get("target_85")
    target_editorial = target70 if target70 is not None else target50
    puntos_actuales = int(contexto.get("current_points", 0))
    partidos_restantes = int(contexto.get("games_left", 0))

    nombre_proyeccion = "Al menos Sudamericana" if objetivo == "sudamericana" else nombre_obj
    L = [f"### 📊 {nombre_proyeccion}: realidad y proyección"]

    if objetivo == "playoffs":
        realidad = f"el **8.º puesto de la zona** tiene **{actual} puntos**"
    elif objetivo == "libertadores":
        realidad = f"el **último cupo de Libertadores por la Tabla Anual** está en **{actual} puntos**"
    else:
        realidad = f"el **último lugar que hoy obtiene al menos Sudamericana por la Tabla Anual** está en **{actual} puntos**"
    L.append(
        f"**📍 Realidad hoy.** Si la competencia terminara ahora, {realidad}. "
        "Ese número describe la tabla de hoy: **no es una estimación del corte final** y tampoco garantiza que "
        "alcance cuando termine el torneo."
    )

    if mediana is not None and bajo is not None and alto is not None:
        L.append(
            f"**🔮 Proyección al final.** El modelo simuló **{_fmt_entero_es(projection.get('simulations', 0))} "
            f"formas de completar el fixture**, resolviendo cada partido una sola vez. En esas simulaciones, el "
            f"corte final tuvo una mediana de **{_fmt_num_es(mediana)} puntos** y el 50% central quedó entre "
            f"**{_fmt_num_es(bajo)} y {_fmt_num_es(alto)}**. En otras palabras, **{_fmt_num_es(mediana)} es el "
            "corte final típico dentro del modelo**: no reemplaza al corte de hoy y no es un mínimo que asegura."
        )

    if target_editorial is not None:
        target_editorial = int(target_editorial)
        necesita = max(0, target_editorial - puntos_actuales)
        alcance = (
            "obtuvo al menos Sudamericana —incluidos los casos en que subió a Libertadores—"
            if objetivo == "sudamericana" else "clasificó"
        )
        nivel = "70%" if target70 is not None else "50%"
        L.append(
            f"**🎯 Qué significa para {equipo}.** Tiene **{puntos_actuales} puntos**. Si termina con "
            f"**{target_editorial}**, {alcance} en al menos el **{nivel}** de las simulaciones **en las que terminó "
            f"exactamente con ese puntaje**. Para llegar a {target_editorial} necesita sumar **{necesita} de los "
            f"{3 * partidos_restantes} puntos** que quedan. Ese {nivel} **no es la probabilidad general de que "
            f"{equipo} clasifique ni la probabilidad de que llegue a {target_editorial}**: describe solamente qué "
            "ocurrió dentro de ese grupo de escenarios simulados."
        )
        rows = _filas_probabilidad_cercanas(projection, target_editorial)
        if rows:
            detalle = " · ".join(
                f"{int(row['final_points'])} puntos: {round(100 * float(row['probability']))}% "
                f"({_fmt_entero_es(row.get('samples', 0))} casos)"
                for row in rows
            )
            L.append(
                f"**Frecuencias del modelo según el puntaje final de {equipo}:** {detalle}. La frecuencia de cada "
                f"fila se calcula sólo sobre los escenarios en los que {equipo} terminó con ese puntaje."
            )
            try:
                if min(int(row.get('samples', 0)) for row in rows) < 100:
                    L.append(
                        "_Lectura de la muestra:_ algunos puntajes aparecieron en menos de 100 simulaciones; esos "
                        "porcentajes son más sensibles al azar de la simulación y conviene leerlos como orientación, "
                        "no como una precisión fina."
                    )
            except Exception:
                pass
        if target85 is not None and int(target85) != target_editorial:
            target85_row = next(
                (row for row in (projection.get("by_final_points") or [])
                 if int(row.get("final_points", -1)) == int(target85)),
                None,
            )
            target85_pct = (
                round(100 * float(target85_row.get("probability", 0)))
                if target85_row else 85
            )
            target85_samples = int(target85_row.get("samples", 0)) if target85_row else 0
            sample_note = f" ({_fmt_entero_es(target85_samples)} casos)" if target85_samples else ""
            L.append(
                f"Con **{int(target85)} puntos**, {equipo} {alcance} en el **{target85_pct}%** de las simulaciones "
                f"en las que terminó con ese puntaje{sample_note}. Sigue siendo una **proyección del modelo**, no "
                "una garantía."
            )
        if projection.get("model_note") and objetivo != "sudamericana":
            params = projection.get("model_parameters") or {}
            draw_pct = round(100 * float(params.get("draw_probability", _LPF_PDRAW)))
            local_factor = float(params.get("home_advantage", _LPF_LOCALIA))
            L.append(
                "**Cómo se arma la proyección.** Usa la misma fuerza del simulador principal —rendimiento actual, "
                "antecedente del Apertura y forma reciente cuando hay resultados— y el mismo modelo de partido: "
                f"**{draw_pct}% de empate** y factor local **{local_factor:.2f}**. La diferencia de gol actual sirve "
                "como referencia para posibles desempates, pero no se inventa una diferencia futura exacta."
            )

    if historial:
        if objetivo == "playoffs":
            L.append(
                f"**🕰️ Referencia histórica.** En {int(historial['sample_size'])} zonas comparables, el octavo "
                f"terminó entre **{_fmt_num_es(historial['minimum'])} y {_fmt_num_es(historial['maximum'])} puntos**, "
                f"con mediana de **{_fmt_num_es(historial['median'])}**. Es un antecedente para comparar; **no es el "
                "corte actual, no es la proyección y no asegura la clasificación**."
            )
        else:
            etiqueta = "Libertadores" if objetivo == "libertadores" else "Sudamericana"
            central = int(round(float(historial["median"])))
            L.append(
                f"**🕰️ Referencia histórica.** Al normalizar las últimas {int(historial['sample_size'])} tablas al "
                f"formato actual de {int(historial['target_matches'])} partidos, la marca central para {etiqueta} "
                f"queda alrededor de **{central} puntos**. Es sólo contexto histórico: **no se debe confundir con el "
                "corte real de hoy ni con la proyección del modelo**."
            )
            if historial.get("latest_same_format") is not None:
                L.append(
                    f"El antecedente más comparable es **{int(historial['latest_season'])}**, con la misma cantidad "
                    f"de partidos: el último clasificado por puntos terminó con "
                    f"**{_fmt_num_es(historial['latest_same_format'])}**."
                )

    directos = int(contexto.get("direct_match_count", 0))
    internos = int(contexto.get("internal_match_count", 0))
    if mostrar_cruces and (directos or internos):
        L.append("### El peso del fixture")
    if mostrar_cruces and directos:
        nombres = list((contexto.get("direct_rivals") or {}).keys())
        L.append(
            f"A **{equipo}** le quedan **{directos} cruces directos** contra equipos de esta pelea: "
            f"{_lista_natural(nombres)}. Cada victoria suma tres y, al mismo tiempo, obliga al rival a sumar cero. "
            "El motor registra ese cruce como un solo partido."
        )
    if mostrar_cruces and internos:
        L.append(
            f"Entre los equipos considerados en esta pelea quedan **{internos} enfrentamientos entre sí**. Por eso "
            "no se pueden sumar sus máximos individuales como si todos pudieran ganar todos sus partidos: el modelo "
            "resuelve cada encuentro una sola vez y evita combinar resultados incompatibles."
        )
    rivales = contexto.get("rivals") or []
    if mostrar_rivales and rivales:
        etiqueta_rivales = "Equipos próximos al corte" if mostrar_cruces else f"Equipos próximos al corte de {nombre_obj}"
        L.append(f"**{etiqueta_rivales}:**")
        for row in rivales[:6]:
            detalle = (
                f"- **{row['team']}:** {row['points']} puntos · {row.get('played', 0)} PJ · "
                f"{row['games_left']} por jugar · máximo {row['ceiling']}"
            )
            if row.get("direct_matches"):
                detalle += f"; máximo {row['ceiling_if_target_wins']} si pierde con {equipo}"
            L.append(detalle + ".")
    return L

def _copas_bloque_objetivo(equipo, base_red, rest, pend, k, nombre_obj, modo="entrar",
                            cupos_reales=None, nota_desempate="", contexto=None,
                            historial=None, objetivo=None, mostrar_cruces=True,
                            mostrar_rivales=True, mostrar_amenazas=True,
                            meta_override=None):
    """Explica proyección, mínimo posible, mínimo que asegura y total seguro.

    El mínimo que asegura es el menor total comprobado. El total seguro
    también asegura si se alcanza, pero puede pedir puntos de más y por eso nunca
    se presenta como el mínimo necesario.
    """
    salva = modo == "salvarse"
    verbo = "se salva" if salva else "entra"
    objetivo = objetivo or (
        "playoffs" if nombre_obj == "Octavos" else
        "libertadores" if nombre_obj == "Libertadores" else
        "sudamericana" if nombre_obj == "Sudamericana" else None
    )
    if contexto is None and objetivo:
        contexto, historial_auto = _armar_contexto_competitivo(equipo, base_red, pend, k, objetivo)
        historial = historial if historial is not None else historial_auto
    prefacio = _contexto_competitivo_bloque(
        equipo, nombre_obj, objetivo, contexto, historial,
        mostrar_cruces=mostrar_cruces, mostrar_rivales=mostrar_rivales,
    ) if objetivo else []

    pts = {e: base_red[e]["pts"] for e in base_red}
    gx = int(rest.get(equipo, 0))
    mio = int(pts[equipo])
    techo = mio + 3 * gx
    estado = _liga_in_out(equipo, base_red, rest, k)

    if estado == "in":
        return prefacio + [
            f"### ✅ {nombre_obj}: " + ("ya está salvado" if salva else "ya está adentro"),
            f"Tiene {mio} puntos y ningún escenario compatible puede sacarlo del objetivo. No depende de nada.",
        ]
    if estado == "out":
        return prefacio + [
            f"### ❌ {nombre_obj}: " + ("condenado matemáticamente" if salva else "matemáticamente afuera"),
            f"La cuenta: {mio} puntos + {gx} partidos × 3 = **{techo} como máximo**, y no alcanza.",
        ]

    # Total seguro: es un total suficiente, pero puede no ser el menor.
    if meta_override is None:
        referencia_prudente = _linea_garantia(base_red, rest, pend, equipo, k) + 1
    else:
        referencia_prudente = int(meta_override)

    ladder = None
    guarantee_exact = False
    meta_exacta = None
    # El Radar se mantiene acotado a la parte final del torneo para no convertir
    # una consulta editorial en un problema de optimización demasiado costoso.
    if pend and gx <= VENTANA_EXACTA:
        try:
            ladder = point_ladder(base_red, pend, equipo, k, max_rows=8, max_matches=110)
            if ladder.get("available") and ladder.get("guarantee") is not None:
                meta_exacta = int(ladder["guarantee"])
                guarantee_exact = True
        except Exception:
            ladder = None

    # Chequeo exacto puntual del máximo: no encuentra el mínimo, pero permite
    # responder con rigor si ganar todo todavía puede dejar al equipo afuera.
    max_fail_exact = None
    if pend and len(pend) <= 100:
        try:
            check = can_fail_with_points(base_red, pend, equipo, k, techo)
            if check.feasible:
                max_fail_exact = True
            elif "infeasible" in str(check.message).lower():
                max_fail_exact = False
        except Exception:
            max_fail_exact = None

    L = list(prefacio)

    cruces_con_equipo = {}
    for a, b in (pend or []):
        if equipo not in (a, b):
            continue
        rival = b if a == equipo else a
        if rival in base_red and rival != equipo:
            cruces_con_equipo[rival] = cruces_con_equipo.get(rival, 0) + 1
    pmax_si_gana_todo = {
        x: pts[x] + 3 * max(0, int(rest.get(x, 0)) - cruces_con_equipo.get(x, 0))
        for x in base_red
    }
    amenazas_techo = sorted(
        [(x, pmax_si_gana_todo[x]) for x in base_red if x != equipo and pmax_si_gana_todo[x] >= techo],
        key=lambda kv: (-kv[1], -pts[kv[0]], kv[0]),
    )

    objetivo_titulo = {
        "Octavos": "los octavos",
        "Libertadores": "la Libertadores",
        "Sudamericana": "al menos la Sudamericana",
    }.get(nombre_obj, nombre_obj)

    if guarantee_exact and meta_exacta is not None:
        faltan = max(0, meta_exacta - mio)
        L.append(f"### 🔒 Mínimo que asegura · {objetivo_titulo}")
        L.append(
            f"El motor exacto comprobó que **{meta_exacta} puntos totales** es el menor total alcanzable con el que "
            f"{equipo} {verbo} **pase lo que pase**. Tiene {mio}: necesita sumar **{faltan} de los "
            f"{3 * gx} puntos** que quedan."
        )
        cb = _texto_combos(faltan, gx)
        if cb:
            L.append(cb)
        L.append(
            f"Con cualquier puntaje alcanzable menor a **{meta_exacta}**, todavía existe al menos un escenario "
            f"compatible que puede dejar a {equipo} afuera. Por eso {meta_exacta} es el mínimo que asegura."
        )
        L.append(
            "**Cómo se obtuvo.** El motor resuelve el fixture pendiente como un único sistema: cada partido tiene "
            "una sola salida y los cruces entre rivales no pueden contarse dos veces."
        )
    else:
        if referencia_prudente is not None and mio <= referencia_prudente <= techo:
            faltan_ref = max(0, referencia_prudente - mio)
            L.append("### 📌 Total seguro")
            L.append(
                f"**{referencia_prudente} puntos totales** es un total que asegura el objetivo: si {equipo} llega a esa marca, "
                f"{verbo} sin depender de otros resultados. Le faltan **{faltan_ref} puntos**. "
                f"**Todavía no sabemos si {referencia_prudente} es el menor total que asegura.** Puede que alcance con menos."
            )
            if gx > VENTANA_EXACTA:
                L.append(
                    f"El **mínimo que asegura** se busca cuando a {equipo} le quedan {VENTANA_EXACTA} partidos o menos."
                )

        L.append("### 🔒 Mínimo que asegura")
        if max_fail_exact is True:
            L.append(
                f"**No existe un total alcanzable que asegure el objetivo.** Incluso ganando sus {gx} partidos y llegando a "
                f"**{techo} puntos**, el motor encontró al menos una combinación compatible que puede dejarlo afuera. "
                "Como ése es su máximo, ningún puntaje menor puede asegurar la clasificación."
            )
        elif max_fail_exact is False:
            L.append(
                f"El chequeo exacto confirmó que con su máximo de **{techo} puntos**, {equipo} {verbo} pase lo que pase. "
                "Pero todavía **no está calculado el menor total exacto** que lo asegura. El total seguro, "
                "si aparece arriba, es suficiente pero puede ser más alto que ese mínimo."
            )
        else:
            L.append(
                "**Todavía no está calculado.** El mínimo que asegura aparecerá sólo cuando el motor pueda demostrar cuál "
                "es el menor puntaje alcanzable que asegura el objetivo en todos los escenarios compatibles. Mientras "
                "tanto, el total seguro se identifica por separado y nunca se presenta como el mínimo."
            )

        if mostrar_amenazas and amenazas_techo:
            muestra = amenazas_techo[:12]
            L.append(
                f"**Si termina con {techo} puntos:** hay **{len(amenazas_techo)} equipos** que, mirados por separado, "
                f"todavía pueden alcanzar o superar ese total aun descontando los partidos que perderían ante {equipo}. "
                "**Eso no significa que todos puedan hacerlo al mismo tiempo**: varios se enfrentan entre sí y sus "
                "máximos individuales son incompatibles entre sí."
            )
            for x, m in muestra:
                L.append(
                    f"- **{x}:** {pts[x]} pts · {base_red[x].get('pj', 0)} PJ · "
                    f"{rest.get(x, 0)} por jugar · máximo condicionado {m}."
                )
            if len(amenazas_techo) > len(muestra):
                L.append(f"- Y {len(amenazas_techo) - len(muestra)} equipos más.")
            L.append(
                "El cálculo del total seguro y del mínimo que asegura considera el fixture completo a la vez, "
                "por eso no suma esos máximos individuales como si pudieran darse todos juntos."
            )
            if nota_desempate:
                L.append(nota_desempate)

    if ladder and ladder.get("available") and ladder.get("rows"):
        conditioned = [row for row in ladder["rows"] if not row.guaranteed]
        if conditioned:
            L.append("### Cómo puede alcanzar con menos")
            L.append(
                "Estos puntajes todavía permiten clasificar en algunos escenarios, pero no aseguran el objetivo:"
            )
            for row in conditioned[-4:]:
                example = "; ".join(row.example[:3]) if row.example else "una combinación favorable de resultados"
                L.append(
                    f"- **{row.final_points} puntos:** clasificación condicionada. Un camino posible incluye "
                    f"{example}; también existe un escenario de eliminación."
                )
            if guarantee_exact and meta_exacta is not None:
                L.append(f"- **{meta_exacta} puntos:** mínimo que asegura el objetivo.")

    return L

def _escenario_maximo_copas_bloque(equipo, base_red, rest, pend, k_lib, k_sud, meta_lib, meta_sud):
    """Explica una sola vez qué pasa si el equipo gana todos sus partidos.

    Los máximos de los rivales se condicionan a las derrotas obligatorias ante el
    equipo consultado. La lista es común a Libertadores y Sudamericana; después se
    explican por separado las exigencias de cada frontera.
    """
    if not pend or equipo not in base_red:
        return []
    pts = {name: int(row.get("pts", 0)) for name, row in base_red.items()}
    gx = int(rest.get(equipo, 0))
    techo = pts[equipo] + 3 * gx
    if meta_lib <= techo and meta_sud <= techo:
        return []

    cruces = {}
    for local, visitante in pend:
        if equipo not in (local, visitante):
            continue
        rival = visitante if local == equipo else local
        if rival in base_red and rival != equipo:
            cruces[rival] = cruces.get(rival, 0) + 1

    amenazas = []
    for rival in base_red:
        if rival == equipo:
            continue
        maximo = pts[rival] + 3 * max(0, int(rest.get(rival, 0)) - cruces.get(rival, 0))
        if maximo >= techo:
            amenazas.append((rival, maximo))
    amenazas.sort(key=lambda item: (-item[1], -pts[item[0]], item[0]))
    if not amenazas:
        return []

    partidos = "partido" if gx == 1 else "partidos"
    L = [f"### Si {equipo} gana los {gx} {partidos}"]
    L.append(
        f"Terminaría con **{techo} puntos**. Aun descontando las derrotas obligatorias de sus rivales directos, "
        f"**{len(amenazas)} equipos** conservan un máximo individual de {techo} o más. Esos máximos no pueden "
        "alcanzarse todos al mismo tiempo porque varios de esos clubes todavía deben enfrentarse entre sí."
    )
    L.append("**Rivales que todavía pueden alcanzar ese total:**")
    for rival, maximo in amenazas:
        L.append(
            f"- **{rival}:** {pts[rival]} puntos · {base_red[rival].get('pj', 0)} PJ · "
            f"{rest.get(rival, 0)} por jugar · máximo condicionado {maximo}."
        )

    deben_ceder_lib = max(0, len(amenazas) - (k_lib - 1))
    deben_ceder_sud = max(0, len(amenazas) - (k_sud - 1))
    L.append(
        f"**Para la Libertadores:** con la distribución actual de plazas por la Tabla Anual, al menos "
        f"**{deben_ceder_lib} de esos {len(amenazas)} equipos** deben terminar detrás de {equipo}, ya sea por "
        "puntos o por los criterios de desempate."
    )
    L.append(
        f"**Para obtener al menos Sudamericana:** con la distribución actual de plazas por la Tabla Anual, "
        f"al menos **{deben_ceder_sud} de esos {len(amenazas)} equipos** deben "
        f"terminar detrás de {equipo}."
    )
    L.append(
        "Si dos o más equipos terminan igualados en puntos, la Tabla General se ordena por diferencia de gol, "
        "goles a favor, Fair Play y, si persiste la igualdad, sorteo."
    )
    return L

def lpf_copas_necesita_texto(equipo, Z, rest, apertura=None, camps=("", "", ""), extras=("", ""), pend=None, jugados=None):
    """Informe de copas por la Tabla General: conclusión arriba, cada número con su
    porqué al lado, los rivales una sola vez y la letra chica al final."""
    if len((Z or {})) < 2:
        return "Cargá las dos zonas."
    P = lpf_plazas_copas(Z, apertura, camps, extras)
    anual, red, n_t = P["anual"], P["reducida"], P["n_tabla_lib"]
    if equipo in P["tomados"] and equipo not in red:
        motivo = dict(P["lib"]).get(equipo, "")
        return f"## {equipo} ya tiene su plaza\n\n{motivo}. No depende de la tabla anual."
    if equipo not in anual:
        return f"No encuentro a **{equipo}**."
    base_red = {e: anual[e] for e in red}
    n = len(base_red)
    pos_red = red.index(equipo) + 1
    anual_df = liga_tabla_df(anual)
    pos_general = next(
        (int(index) + 1 for index, value in enumerate(anual_df["Equipo"].tolist()) if value == equipo),
        pos_red,
    )
    k_lib = n_t
    k_sud = min(n, n_t + 6)
    e_lib = _liga_in_out(equipo, base_red, rest, k_lib)
    e_sud = _liga_in_out(equipo, base_red, rest, k_sud)
    pts_e = base_red[equipo]["pts"]; gx = rest.get(equipo, 0)
    clausura_strength_base = {
        name: row for zone in (Z or {}).values() for name, row in zone.items()
    }
    contexto_lib, historial_lib = _armar_contexto_competitivo(
        equipo, base_red, pend, k_lib, "libertadores",
        strength_base=clausura_strength_base, jugados=jugados,
    )
    contexto_sud, historial_sud = _armar_contexto_competitivo(
        equipo, base_red, pend, k_sud, "sudamericana",
        strength_base=clausura_strength_base, jugados=jugados,
    )

    projection_lib = (contexto_lib or {}).get("projection") or {}
    projection_sud = (contexto_sud or {}).get("projection") or {}
    target_lib = projection_lib.get("target_70") or projection_lib.get("target_50")
    target_sud = projection_sud.get("target_70") or projection_sud.get("target_50")
    pj_e = int(base_red[equipo].get("pj", 0))
    referencias = []

    if e_lib == "in":
        titular = f"Por la Tabla Anual, {equipo} ya tiene la Libertadores asegurada."
    elif e_lib == "out" and e_sud == "out":
        titular = f"Por la Tabla Anual, {equipo} quedó sin chances de copa."
    elif e_lib == "out":
        titular = f"{equipo} ya no llega a la Libertadores por la Tabla Anual: su pelea es por la Sudamericana."
    else:
        titular = (
            f"{equipo} sigue en carrera por las copas de 2027. La Libertadores exige una remontada mayor; la "
            "Sudamericana aparece como el objetivo más cercano según la tabla y el fixture actuales."
        )
        if target_lib is not None:
            referencias.append(
                f"Libertadores: alrededor de {int(target_lib)} puntos totales "
                f"(+{max(0, int(target_lib) - pts_e)} desde hoy)"
            )
        if target_sud is not None:
            referencias.append(
                f"al menos Sudamericana: alrededor de {int(target_sud)} puntos totales "
                f"(+{max(0, int(target_sud) - pts_e)} desde hoy)"
            )
    posicion_actual = (
        f"Hoy está **{pos_general}º en la Tabla Anual**, con **{pts_e} puntos en {pj_e} PJ**. "
        f"Le quedan **{gx} partidos** y **{3 * gx} puntos** disponibles."
    )

    excluidos_antes = [
        e for e in P["orden"][: max(0, pos_general - 1)]
        if e not in red
    ]
    nota_clasificados_arriba = ""
    if excluidos_antes:
        nombres = [f"**{e}**" for e in excluidos_antes]
        if len(nombres) == 1:
            nota_clasificados_arriba = (
                f" (Entre los equipos que tiene arriba, {nombres[0]} ya tiene una plaza directa de Libertadores.)"
            )
        else:
            nota_clasificados_arriba = (
                f" (Entre los equipos que tiene arriba, {', '.join(nombres[:-1])} y {nombres[-1]} "
                "ya tienen una plaza directa de Libertadores.)"
            )

    posicion_ventana = ""
    try:
        _prox, _oficiales, _postergados = lpf_jornada_actual(pend or [])
        _ventana = _lpf_dedupe_scenario_games(list(_oficiales) + [m for m, _f in _postergados])
        if _ventana:
            _anual_bounds = scenario_rank_bounds(
                anual, [m for m in _ventana if m[0] in anual or m[1] in anual], equipo
            )
            if _anual_bounds.get("available"):
                _best_a = int(_anual_bounds["best_rank"])
                _worst_a = int(_anual_bounds["worst_rank"])
                posicion_ventana = (
                    f"En la próxima ventana, su **mejor posición posible en la Tabla Anual es {_best_a}º** "
                    f"y la **peor {_worst_a}º**."
                )
    except Exception:
        posicion_ventana = ""

    L = [
        f"## {equipo} · Copas 2027",
        f"**{titular}**",
        posicion_actual + nota_clasificados_arriba,
        "Este informe calcula la vía de la **Tabla Anual** —denominada **Tabla General** en el reglamento—. "
        "La simulación usa la distribución actual de los cupos y **no asigna probabilidades a los "
        "campeones todavía pendientes**. Esos títulos se explican después como escenarios separados.",
    ]
    if posicion_ventana:
        L.append(posicion_ventana)
    if referencias:
        L.append("**Referencias del modelo:**")
        for referencia in referencias:
            L.append(f"- {referencia}.")
        if target_lib is not None:
            faltan_lib = max(0, int(target_lib) - pts_e)
            ejemplo_lib = _texto_combos(faltan_lib, gx)
            if ejemplo_lib:
                L.append("**Ejemplos de caminos hacia la referencia de Libertadores:** " + ejemplo_lib.replace("**Cómo llegar** (sirve alcanzar la meta *o superarla*): ", ""))
        if target_sud is not None:
            faltan_sud = max(0, int(target_sud) - pts_e)
            ejemplo_sud = _texto_combos(faltan_sud, gx)
            if ejemplo_sud:
                L.append("**Ejemplos de caminos hacia la referencia de Sudamericana:** " + ejemplo_sud.replace("**Cómo llegar** (sirve alcanzar la meta *o superarla*): ", ""))
        L.append("Son ejemplos de combinaciones posibles, no los únicos caminos.")

    # ── Cada objetivo, por separado ──
    _nota_desempate_anual = ("Si dos o más equipos terminan igualados en puntos, la Tabla General se ordena por "
                             "diferencia de gol, goles a favor, Fair Play y, si persiste la igualdad, sorteo.")
    meta_lib_pre = _linea_garantia(base_red, rest, pend, equipo, k_lib) + 1
    meta_sud_pre = _linea_garantia(base_red, rest, pend, equipo, k_sud) + 1
    L += _copas_bloque_objetivo(
        equipo, base_red, rest, pend, k_lib, "Libertadores",
        cupos_reales=k_lib, nota_desempate=_nota_desempate_anual,
        contexto=contexto_lib, historial=historial_lib, objetivo="libertadores",
        mostrar_amenazas=False, meta_override=meta_lib_pre,
    )
    L += _copas_bloque_objetivo(
        equipo, base_red, rest, pend, k_sud, "Sudamericana",
        cupos_reales=6, nota_desempate=_nota_desempate_anual,
        contexto=contexto_sud, historial=historial_sud, objetivo="sudamericana",
        mostrar_cruces=False, mostrar_rivales=True, mostrar_amenazas=False,
        meta_override=meta_sud_pre,
    )

    L += _escenario_maximo_copas_bloque(
        equipo, base_red, rest, pend, k_lib, k_sud, meta_lib_pre, meta_sud_pre,
    )

    # ── Rivales que le quedan: UNA sola vez ──
    if pend:
        mis = [(b if a == equipo else a) for (a, b) in pend if equipo in (a, b)]
        if mis:
            L.append("### Los partidos que le quedan")
            L.append(" · ".join(mis))

    # ── Cómo pueden correr los cupos por campeones futuros ──
    _clausura_vivos = set(_lpf_clausura_candidates(Z, rest))
    _copa_vivos = set(_lpf_copa_arg_alive_for_annual(anual))
    if n_t > 0 and len(red) > n_t:
        _lib_hoy = red[:n_t]
        _lib_espera = red[n_t]
        _via_cl = [x for x in _lib_hoy if x in _clausura_vivos]
        _via_ca = [x for x in _lib_hoy if x in _copa_vivos]
        L.append("### Cómo pueden mover los cupos los campeones")
        _cond = []
        if _via_cl:
            _cond.append(f"uno de los actuales cupos por tabla gana el Clausura ({', '.join(_via_cl)})")
        if _via_ca:
            _cond.append(f"uno de ellos gana la Copa Argentina ({', '.join(_via_ca)})")
        if camps and camps[0] and not camps[1]:
            _cond.append(f"{camps[0]} también gana el Clausura")
        if _cond:
            L.append(f"Hoy el primero que espera es **{_lib_espera}**. Entraría a la Libertadores si "
                     + "; o si ".join(_cond) + ".")
        else:
            L.append(f"Hoy el primero que espera es **{_lib_espera}**. La identidad de los campeones del Clausura "
                     "y de la Copa Argentina definirá si la línea baja hasta su puesto.")
    if len(red) > n_t + 6:
        _sud_espera = red[n_t + 6]
        L.append(f"Para la Sudamericana, el primero que espera hoy es **{_sud_espera}**. Puede entrar si un equipo "
                 "ubicado por encima obtiene una plaza directa de Libertadores y el reordenamiento corre un lugar "
                 "hacia abajo la línea de clasificación.")
    L.append(
        "**Excepción Copa Argentina:** cuando quede definido quién ocupa la plaza ARGENTINA 3, ese equipo será "
        "considerado ya clasificado por otra vía. Si el campeón ya obtuvo la plaza del Apertura o del Clausura, "
        "ARGENTINA 3 pasa al siguiente equipo de Primera mejor ubicado dentro de la Copa Argentina; no pasa al "
        "siguiente de la Tabla Anual."
    )

    # ── Letra chica ──
    chica = ["### Cómo leer estos números",
             "La Tabla General suma únicamente los puntos de las fases regulares del Apertura y del Clausura; "
             "los playoffs no agregan puntos a esta clasificación.",
             "En todo el informe, la **posición mostrada es siempre la posición real de la Tabla Anual**. "
             "Para asignar las plazas, un club que ya clasificó a la Libertadores por otra vía no consume otro cupo; "
             "por eso la línea puede correrse al siguiente equipo, pero no se muestra una segunda numeración.",
             "Además de esta vía, el campeón del Clausura obtiene una plaza directa. Si un club argentino gana "
             "la Libertadores o la Sudamericana 2026, obtiene una plaza adicional para la Libertadores 2027."]
    _camp_plaza = [(e, m) for (e, m) in P["lib"] if e not in red]
    if _camp_plaza:
        _cl = "; ".join(f"**{e}** ({m.split('(art')[0].split('—')[0].strip()})" for e, m in _camp_plaza)
        if len(_camp_plaza) == 1:
            _e, _m = _camp_plaza[0]
            _motivo = _m.split('(art')[0].split('—')[0].strip()
            _motivo_txt = _motivo[:1].lower() + _motivo[1:] if _motivo else "campeón"
            chica.append(f"**{_e}** ya tiene una plaza como {_motivo_txt}. Conserva su puesto normal en la Tabla Anual, "
                         "pero no consume otro cupo por esa vía.")
        else:
            chica.append(f"Ya tienen plaza por otra vía: {_cl}. Conservan su puesto normal en la Tabla Anual, "
                         "pero no consumen otro cupo por esa vía.")
    chica.append(
        "El informe separa el **corte actual**, la **proyección del modelo**, la **referencia histórica** y la "
        "**mínimo que asegura**. El mínimo que asegura es el **menor puntaje alcanzable** que asegura entrar pase "
        "lo que pase. Si el motor exacto todavía no puede demostrar ese mínimo, el informe dice que el mínimo aún "
        "no está calculado y no reemplaza ese dato por una aproximación."
    )
    if P["avisos"]:
        chica.append(
            "**Definiciones pendientes.** " + " ".join(P["avisos"]) + " La simulación no asigna probabilidades "
            "a esos campeones: los presenta como escenarios separados porque pueden modificar qué equipos ocupan "
            "los cupos que entrega la Tabla Anual."
        )
    L += chica
    return editorialize_text("\n\n".join(L))

def lpf_tabla_zonas_texto(Z):
    if not Z:
        return "No hay zonas cargadas."
    L = []
    for lab in sorted(Z):
        df = liga_tabla_df(Z[lab])
        L.append(f"**Zona {lab}** (clasifican los 8 primeros)")
        for _, r in df.iterrows():
            ic = "🟢" if int(r["Pos"]) <= 8 else "⚪"
            L.append(f"{ic} {int(r['Pos'])}º **{r['Equipo']}** · {int(r['PTS'])} pts · {int(r.get('PJ', 0))} PJ (DG {int(r['DG']):+d})")
        L.append("")
    return editorialize_text("\n\n".join(L))


# ═══ Nombres canónicos de los 30 clubes de la LPF 2026 (evita que "River" y "River Plate" sean dos equipos) ═══

# ═══ FIXTURE Clausura 2026 (Tarea 2) — texto crudo + parser + pendientes ═══



def lpf_pendientes(Z, games=None, canon=None, played=None):
    """Devuelve pendientes reconciliados por identidad de partido.

    Los marcadores explícitos tienen prioridad. Los PJ sólo se usan como respaldo y
    quedan señalados en la auditoría, evitando asumir que las primeras N fechas se
    jugaron cuando hubo postergados.
    """
    if games is None:
        games = LPF_FIXTURE
    if played is None:
        played = ((st.session_state.get("ESTADO") or {}).get("jugados") or
                  parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or None))
    report = build_quality_report(
        Z or {},
        ((st.session_state.get("ESTADO") or {}).get("anual_directo") or st.session_state.get("LPF_ANUAL") or {}),
        st.session_state.get("PROMEDIOS") or {},
        games,
        played,
        opening_snapshot=((st.session_state.get("ESTADO") or {}).get("apertura") or st.session_state.get("LPF_APERTURA") or {}),
    )
    st.session_state.LPF_DATA_QUALITY = report
    return pending_pairs(report.match_records)


def _linea_garantia(base, rest, pend, equipo, k):
    """Total seguro, delegada al núcleo aislado y validada por fuerza bruta.

    La línea prueba todos los subconjuntos relevantes y descuenta los puntos que no
    pueden existir cuando dos rivales se enfrentan. Puede ser conservadora, pero no
    declara una clasificación garantizada que todavía dependa de otros resultados.
    """
    return safe_guarantee_line(base, rest, pend or [], equipo, k)


# fixture parseado una sola vez (nombres canónicos), para pendientes/rest

def lpf_rest_desde_fixture(Z):
    """rest por equipo = 16 - PJ (coherente con las tablas cargadas)."""
    return {e: max(0, LPF_FECHAS_TOTAL - d.get('pj', 0)) for b in (Z or {}).values() for e, d in b.items()}




def _record_prom_source_issues(messages):
    """Guarda advertencias de procedencia para incorporarlas al semáforo."""
    st.session_state.PROM_SOURCE_ISSUES = list(messages or [])

def promedios_previas_texto(previas):
    return "\n".join(f"{e}, {p}, {j}" for e, (p, j) in previas.items())

# Foto histórica sincronizada de Promedios + Anual (17 PJ de 2026), usada sólo para extraer temporadas previas.
PROMEDIOS_LPF_2026 = """1
Boca Jrs.
Boca Jrs.
1.767\t159\t90\t67\t62\t30
2
River
River
1.689\t152\t90\t70\t53\t29
3
Vélez
Vélez
1.633\t147\t90\t76\t40\t31
4
Racing
Racing
1.633\t147\t90\t70\t53\t24
5
Argentinos
Argentinos
1.611\t145\t90\t56\t57\t32
6
Central
Central
1.567\t141\t90\t47\t66\t28
7
Independiente
Independiente
1.522\t137\t90\t63\t47\t27
8
Estudiantes
Estudiantes
1.511\t136\t90\t63\t42\t31
9
Lanús
Lanús
1.511\t136\t90\t59\t50\t27
10
Huracán
Huracán
1.489\t134\t90\t62\t47\t25
11
Talleres
Talleres
1.467\t132\t90\t72\t34\t26
12
Independiente Riv.
Independiente Riv.
1.378\t124\t90\t46\t43\t35
13
Barracas
Barracas
1.356\t122\t90\t49\t49\t24
14
Unión
Unión
1.344\t121\t90\t60\t39\t22
15
San Lorenzo
San Lorenzo
1.311\t118\t90\t45\t51\t22
16
Gimnasia (M)
Gimnasia (M)
1.294\t22\t17\t0\t0\t22
17
Defensa
Defensa
1.289\t116\t90\t58\t38\t20
18
Belgrano
Belgrano
1.278\t115\t90\t49\t37\t29
19
Riestra
Riestra
1.267\t114\t90\t48\t52\t14
20
Gimnasia
Gimnasia
1.244\t112\t90\t48\t38\t26
21
Platense
Platense
1.211\t109\t90\t57\t35\t17
22
Instituto
Instituto
1.200\t108\t90\t53\t34\t21
23
Tigre
Tigre
1.200\t108\t90\t39\t49\t20
24
Newell's
Newell's
1.111\t100\t90\t49\t33\t18
25
Central Córdoba
Central Córdoba
1.111\t100\t90\t42\t42\t16
26
Atl. Tucumán
Atl. Tucumán
1.100\t99\t90\t50\t34\t15
27
Banfield
Banfield
1.044\t94\t90\t41\t35\t18
28
Sarmiento
Sarmiento
0.989\t89\t90\t35\t35\t19
29
Aldosivi
Aldosivi
0.857\t42\t49\t0\t33\t9
30
Estudiantes RC
Estudiantes RC
0.471\t8\t17\t0\t0\t8"""


# Zonas del Clausura 2026 (fecha 2 en curso). Fuente: tablas pegadas por el usuario.


LPF_FECHAS_TOTAL = 16  # fase de zonas del Clausura (art. 14.1)




def _embedded_lpf_prom_history():
    """Extrae las temporadas previas desde dos fotos históricas sincronizadas.

    La tabla de promedios incluida y ``TABLA_ANUAL_LPF_2026`` pertenecen al mismo
    momento (17 PJ de 2026). Usar la Anual viva para volver a separarlas hacía que
    el histórico perdiera un PJ en cada fecha: 73 pasaba a 72, luego a 71, etc.
    """
    annual_snapshot = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]
    return parse_promedios_tabla(PROMEDIOS_LPF_2026, annual_snapshot)


def _ensure_lpf_prom_history(force=False):
    """Instala o migra el histórico incluido sin pisar una carga manual válida."""
    expected, _snapshot, warnings = _embedded_lpf_prom_history()
    current = st.session_state.get("PROMEDIOS") or {}
    marker_version = st.session_state.get("LPF_PROM_HISTORY_VERSION")

    comparable = 0
    stale = 0
    for team, value in expected.items():
        current_value = current.get(team)
        if not isinstance(current_value, (tuple, list)) or len(current_value) < 2:
            continue
        if int(current_value[0]) == int(value[0]):
            comparable += 1
            if int(current_value[1]) != int(value[1]):
                stale += 1

    migrate_internal = marker_version != _LPF_PROM_HISTORY_VERSION and comparable >= 10 and stale >= 3
    if force or not current or migrate_internal:
        st.session_state.PROM_TXT = promedios_previas_texto(expected)
        st.session_state.PROMEDIOS = parse_promedios(st.session_state.PROM_TXT)
        st.session_state.LPF_PROM_HISTORY_VERSION = _LPF_PROM_HISTORY_VERSION
        _record_prom_source_issues(warnings)
        return expected, warnings, True
    return current, [], False

# Calendario oficial de la fase de zonas del Clausura 2026 (art. 17.1 del Reglamento LPF)
LPF_FECHAS_CLAUSURA = ["2026-07-26", "2026-07-29", "2026-08-02", "2026-08-09", "2026-08-16",
                       "2026-08-23", "2026-08-30", "2026-09-06", "2026-09-13", "2026-09-20",
                       "2026-10-04", "2026-10-11", "2026-10-18", "2026-10-25", "2026-11-01",
                       "2026-11-08"]

def lpf_fecha_esperada(hoy=None):
    """Cuántas fechas del Clausura deberían estar jugadas hoy, según el calendario del reglamento."""
    import datetime as _dt
    hoy = hoy or _dt.date.today()
    n = 0
    for d in LPF_FECHAS_CLAUSURA:
        if _dt.datetime.strptime(d, "%Y-%m-%d").date() <= hoy:
            n += 1
    return n, len(LPF_FECHAS_CLAUSURA)

def lpf_estado_datos(Z, hoy=None):
    """Compara lo cargado con el calendario oficial. Devuelve (texto, esta_al_dia)."""
    pjs = [d.get("pj", 0) for b in (Z or {}).values() for d in b.values()]
    if not pjs:
        return "No hay zonas cargadas.", False
    cargadas, mx = min(pjs), max(pjs)
    esperadas, total = lpf_fecha_esperada(hoy)
    detalle = f"fecha **{cargadas}** de {total}" + (f" — {sum(1 for p in pjs if p > cargadas)} equipos ya jugaron {mx}: la fecha está en curso (o hay postergados)" if mx != cargadas else "")
    import datetime as _dt
    hoyd = hoy or _dt.date.today()
    en_juego = None
    for i, d in enumerate(LPF_FECHAS_CLAUSURA, 1):
        fd = _dt.datetime.strptime(d, "%Y-%m-%d").date()
        if 0 <= (fd - hoyd).days <= 2 and i > cargadas:
            en_juego = i; break
    if cargadas >= esperadas:
        base_ok = f"✅ Datos al día: tenés cargada la {detalle}."
        if en_juego:
            return (base_ok + f"\n\n🔴 **La fecha {en_juego} se está jugando en estos días.** "
                    "Los partidos en curso todavía no están (o están con resultado parcial): "
                    "actualizá las zonas cuando termine la fecha.", False)
        return base_ok, True
    faltan = esperadas - cargadas
    return (f"⚠️ **Datos desactualizados**: tenés la {detalle}, pero según el calendario oficial "
            f"ya se jugaron **{esperadas}**. Te faltan **{faltan}** fecha(s) por cargar — los resultados "
            f"que no cargues **no se toman**, y las cuentas de playoffs, descenso y copas van a salir viejas."), False

def lpf_jornada_de_dia(dia):
    """Convierte la fecha de un partido en el número de jornada, con el calendario del reglamento."""
    import datetime as _dt
    try:
        d = _dt.datetime.strptime(str(dia)[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    mejor, dif = None, 99
    for i, f in enumerate(LPF_FECHAS_CLAUSURA, 1):
        fd = _dt.datetime.strptime(f, "%Y-%m-%d").date()
        dd = abs((d - fd).days)
        if dd < dif:
            mejor, dif = i, dd
    return mejor if dif <= 5 else None

def _etiq(a, b):
    d = (globals().get("_ESPN_DIA") or {}).get((a, b))
    j = lpf_jornada_de_dia(d) if d else None
    return f" _(f{j})_" if j else ""

def lpf_estado_fecha_texto(Z, liga="arg.1", con_vivo=True):
    """Qué está tomado y qué no: por PJ de cada equipo, más los partidos de hoy según ESPN."""
    pjs = [d.get("pj", 0) for b in (Z or {}).values() for d in b.values()]
    if not pjs:
        return "No hay zonas cargadas."
    mn, mx = min(pjs), max(pjs)
    L = ["**¿Qué tiene cargado la app?** (sale de los partidos jugados de cada equipo)"]
    if mn == mx:
        L.append(f"Todos los equipos tienen **{mx} partidos**: la fecha {mx} está completa y tomada. ✅")
    else:
        L.append(f"La fecha **{mx}** está a medias: unos equipos van {mx} y otros {mn}.")
        for lab in sorted(Z):
            ya = sorted([e for e, d in Z[lab].items() if d.get("pj", 0) >= mx])
            no = sorted([e for e, d in Z[lab].items() if d.get("pj", 0) < mx])
            L.append(f"**Zona {lab} — ya jugaron y están tomados ({len(ya)}):** " + (", ".join(ya) or "—"))
            L.append(f"**Zona {lab} — todavía NO ({len(no)}):** " + (", ".join(no) or "—"))
        L.append("_Los que todavía no jugaron no suman nada en las cuentas: cuando terminen, recargá las zonas._")
    if con_vivo:
        try:
            jg, pen, _n, err = espn_fixture(liga, dias=3)
            if not err:
                if jg:
                    porf = {}
                    for a, b, x, y in jg:
                        porf.setdefault(_etiq(a, b) or " _(s/f)_", []).append(f"{canon_club(a)} {x}-{y} {canon_club(b)}")
                    L.append("**Terminados (según ESPN):**")
                    for et, lst in sorted(porf.items()):
                        L.append(f"· **Fecha{et.replace(' _(f','').replace(')_','').replace(' _(s/f)_','?')}**: " + ", ".join(lst))
                if pen:
                    porf2 = {}
                    for a, b in pen:
                        porf2.setdefault(_etiq(a, b) or " _(s/f)_", []).append(f"{canon_club(a)} vs {canon_club(b)}")
                    L.append("**Por jugarse / en curso (según ESPN):**")
                    for et, lst in sorted(porf2.items()):
                        L.append(f"· **Fecha{et.replace(' _(f','').replace(')_','').replace(' _(s/f)_','?')}**: " + ", ".join(lst))
                L.append("_Esto último sale en vivo de ESPN y es solo informativo: la app calcula con las tablas cargadas, "
                         "no con estos partidos._")
        except Exception:
            pass
    return "\n\n".join(L)

def lpf_relato_zona_texto(Z, lab, rest, hoy_fecha=None):
    """Narración editorial de una zona con PTS, PJ, DG, GF y situación exacta."""
    base = (Z or {}).get(lab)
    if not base:
        return f"No tengo cargada la Zona {lab}."
    orden = list(liga_tabla_df(base)["Equipo"])
    dentro = [e for e in orden if _liga_in_out(e, base, rest, _LPF_TOP_OCTAVOS) == "in"]
    fuera = [e for e in orden if _liga_in_out(e, base, rest, _LPF_TOP_OCTAVOS) == "out"]
    return zone_story(
        str(lab), base, rest, top_n=_LPF_TOP_OCTAVOS, total_rounds=LPF_FECHAS_TOTAL,
        qualified=dentro, eliminated=fuera,
    )

def panorama(equipos, jugados, esc, directo=None):
    d = DIRECTO() if directo is None else directo; hay3 = MEJORES_TERCEROS() > 0
    filas = []
    for e in equipos:
        s = situacion(e, esc, d)
        if s["ya_directo"]: est = "🟢 Clasificado directo"
        elif s["eliminado"]: est = "🔴 Eliminado"
        elif s["puede_directo"]: est = "🟡 En disputa"
        elif hay3: est = "🔵 Chance vía mejor 3º"
        else: est = "🔴 Eliminado"
        filas.append({"Equipo": e, "Estado": est, "Mejor": s["mejor"], "Peor": s["peor"],
                      "Puede 1º": "sí" if s["puede_1"] else "no",
                      "Directo en": f"{s['ndir']}/{s['total']}"})
    orden = {r["Equipo"]: r["Pos"] for _, r in tabla(equipos, jugados).iterrows()}
    return pd.DataFrame(filas).sort_values("Equipo", key=lambda c: c.map(orden)).reset_index(drop=True)

def _desc_obj(o):
    return {"exacto": f"exactamente {o[1]}º", "al_menos": f"{o[1]}º o mejor",
            "como_mucho": f"{o[1]}º o peor", "entre": f"entre {o[1]}º y {o[-1]}º"}[o[0]]

def _ok_pos(pos, o):
    if o[0] == "exacto":    return pos == o[1]
    if o[0] == "al_menos":  return pos <= o[1]
    if o[0] == "como_mucho":return pos >= o[1]
    return (pos >= o[1]) & (pos <= o[2])

def resultados_para_puesto_texto(equipo, esc, pend, objetivo):
    pos = esc[f"Pos {equipo}"]; ok = _ok_pos(pos, objetivo); desc = _desc_obj(objetivo)
    n, tot = int(ok.sum()), len(esc)
    if n == 0:
        alc = ", ".join(f"{int(p)}º" for p in sorted(pos.unique()))
        return f"❌ **IMPOSIBLE**: {equipo} no puede terminar {desc}.\n\nPuestos alcanzables: {alc}."
    if n == tot:
        return f"✅ {equipo} termina {desc} **pase lo que pase**."
    df = esc.copy(); df["_c"] = df.apply(lambda r: _combo(r, pend), axis=1); df["_ok"] = ok.values
    siempre, aveces = [], []
    for c, g in df.groupby("_c"):
        k, m = int(g["_ok"].sum()), len(g)
        if k == m: siempre.append(c)
        elif k > 0: aveces.append((c, k, m))
    lineas = []
    if siempre:
        lineas.append("**Lo logra SIEMPRE con:**")
        for c in siempre: lineas.append(f"✅ {c}")
    if aveces:
        lineas.append("\n**Lo logra SOLO si la dif. de gol acompaña:**")
        for c, k, m in sorted(aveces, key=lambda x: -x[1]/x[2]):
            lineas.append(f"⚠️ {c} &nbsp;({k}/{m} marcadores)")
    return "\n\n".join(lineas)

def probabilidades(equipos, jugados, pendientes, n=_LPF_PUBLIC_MC_RUNS, media=1.3, fuerza=None, seed=1):
    rng = np.random.default_rng(seed)
    lam = {e: media * (fuerza.get(e, 1.0) if fuerza else 1.0) for e in equipos}
    cuenta = {e: np.zeros(len(equipos) + 1, dtype=int) for e in equipos}
    base = list(jugados)
    for _ in range(n):
        part = base + [(l, v, int(rng.poisson(lam[l] * 1.12)), int(rng.poisson(lam[v] * 0.92))) for (l, v) in pendientes]
        for e, p in posiciones(equipos, part).items(): cuenta[e][p] += 1
    rows = [{"Equipo": e, "1º %": round(100 * cuenta[e][1] / n, 1),
             "Top 2 %": round(100 * cuenta[e][1:3].sum() / n, 1),
             "Top 3 %": round(100 * cuenta[e][1:4].sum() / n, 1)} for e in equipos]
    return pd.DataFrame(rows).sort_values("Top 2 %", ascending=False).reset_index(drop=True)

def que_pasa_si(esc, pend, condiciones, equipos):
    mask = pd.Series(True, index=esc.index)
    for i, cond in enumerate(condiciones, 1):
        if not cond: continue
        gl, gv = esc[f"P{i}_gl"], esc[f"P{i}_gv"]
        mask &= (gl > gv) if cond == "L" else (gl == gv) if cond == "E" else (gl < gv)
    sub = esc[mask]
    rows = [{"Equipo": e, "Mejor": int(sub[f"Pos {e}"].min()), "Peor": int(sub[f"Pos {e}"].max()),
             "Directo posible": "sí" if (sub[f"Pos {e}"] <= 2).any() else "no",
             "Directo seguro": "sí" if (sub[f"Pos {e}"] <= 2).all() else "no"} for e in equipos]
    return sub, pd.DataFrame(rows)

def distribucion(equipos, esc):
    d = pd.DataFrame({e: esc[f"Pos {e}"].value_counts() for e in equipos}).fillna(0).astype(int).sort_index()
    d.index.name = "Puesto"; return d

def _restantes(equipos, pend):
    r = {e: 0 for e in equipos}
    for l, v in pend: r[l] += 1; r[v] += 1
    return r

def maximos_minimos(equipos, jugados, pend):
    ov = _stats(equipos, jugados); rest = _restantes(equipos, pend)
    rows = [{"Equipo": e, "PJ": ov[e]["pj"], "PTS": ov[e]["pts"], "Restan": rest[e],
             "PTS máx": ov[e]["pts"] + 3 * rest[e]} for e in equipos]
    return pd.DataFrame(rows).sort_values(["PTS", "PTS máx"], ascending=False).reset_index(drop=True)

def clasificado_eliminado(equipos, jugados, pend, n=1):
    ov = _stats(equipos, jugados); rest = _restantes(equipos, pend)
    pts = {e: ov[e]["pts"] for e in equipos}; pmax = {e: pts[e] + 3 * rest[e] for e in equipos}
    col = CAMPEON().capitalize() if n == 1 else f"Top {n}"
    rows = []
    for e in equipos:
        arriba = sum(1 for x in equipos if x != e and pmax[x] >= pts[e])
        inalc  = sum(1 for x in equipos if x != e and pts[x] > pmax[e])
        estado = "🟢 asegurado" if arriba < n else ("🔴 sin chances" if inalc >= n else "🟡 depende")
        rows.append({"Equipo": e, "PTS": pts[e], "PTS máx": pmax[e], col: estado})
    return pd.DataFrame(rows).sort_values("PTS", ascending=False).reset_index(drop=True)

def numero_magico_texto(equipo, equipos, jugados, pend, n=1):
    ov = _stats(equipos, jugados); rest = _restantes(equipos, pend)
    pts = {e: ov[e]["pts"] for e in equipos}; pmax = {e: pts[e] + 3 * rest[e] for e in equipos}
    otros = sorted((pmax[x] for x in equipos if x != equipo), reverse=True)
    meta = f"ser {CAMPEON()}" if n == 1 else f"entrar al top {n}"
    lineas = [f"**{equipo}** — para {meta}:",
              f"Tiene **{pts[equipo]} pts** y le quedan {rest[equipo]} partidos ({3*rest[equipo]} en juego)."]
    if len(otros) < n:
        lineas.append(f"✅ Ya está en el top {n}.")
    else:
        necesita = max(0, (otros[n-1] + 1) - pts[equipo]); tope = 3 * rest[equipo]
        if necesita == 0:
            lineas.append("✅ Ya está asegurado pase lo que pase.")
        elif necesita <= tope:
            ref = pts[equipo] + necesita
            lineas.append(
                f"📌 **Total seguro: {ref} puntos.** Si llega a ese total, asegura el objetivo sin "
                f"depender de nadie. Le faltan **{necesita} puntos**; el mínimo exacto puede ser menor."
            )
        else:
            lineas.append(
                f"El total seguro queda fuera de alcance: exigiría {necesita} puntos más y sólo hay "
                f"{tope} en juego. Eso no prueba por sí solo que sea imposible: puede depender de que los rivales pinchen."
            )
    pq = _porque_numero_magico(equipo, equipos, jugados, pend, n)
    if pq:
        lineas.append("🔍 **Por qué:** " + pq)
    return "\n\n".join(lineas)

def mejor_resultado_texto(equipo, esc, pend, directo=None):
    d = DIRECTO() if directo is None else directo
    df = esc.copy(); df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    rk = lambda p: 0 if p.startswith("le gana") else (1 if p.startswith("empata") else 2)
    opciones = []
    for prop, g in df.groupby("_p"):
        gp = esc.loc[g.index, f"Pos {equipo}"]
        opciones.append({"r": prop, "peor": int(gp.max()), "mejor": int(gp.min()),
                         "prom": float(gp.mean()), "uno": int((gp == 1).sum()),
                         "dir": int((gp <= d).sum()), "n": len(g), "rk": rk(prop)})
    opciones.sort(key=lambda o: (round(o["prom"], 6), o["peor"], o["mejor"], o["rk"]))
    lineas = []
    for i, o in enumerate(opciones):
        flag = " 👍 lo que más le conviene" if i == 0 else ""
        lineas.append(f"• Si {equipo} **{o['r']}**: termina entre {o['mejor']}º y {o['peor']}º · "
                      f"sale 1º en {o['uno']}/{o['n']} · clasifica directo en {o['dir']}/{o['n']}{flag}")
    return "\n\n".join(lineas)

def _gana_todo(p): return bool(p) and all(s.startswith("le gana") for s in p.split(" y "))

def conviene_otros_texto(equipo, esc, pend, directo=None):
    """Qué le conviene al equipo en los partidos que NO juega."""
    d = DIRECTO() if directo is None else directo
    otros_pend = [p for p in pend if equipo not in p]
    if not otros_pend:
        return ""
    df = esc.copy()
    df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    df["_o"] = df.apply(lambda r: _res_otros(r, equipo, pend), axis=1)
    if _pd_de(equipo, pend):
        sub = df[df["_p"].map(_gana_todo)]
        cab = f"Si **{equipo} gana lo suyo**, le conviene en los otros partidos (de mejor a peor):"
        if sub.empty: sub, cab = df, f"A **{equipo}** le conviene en los otros partidos (de mejor a peor):"
    else:
        sub, cab = df, f"A **{equipo}** le conviene en los otros partidos (de mejor a peor):"
    rows = []
    for o, g in sub.groupby("_o"):
        gp = esc.loc[g.index, f"Pos {equipo}"]
        rows.append({"o": o, "prom": float(gp.mean()), "uno": int((gp == 1).sum()),
                     "dir": int((gp <= d).sum()), "n": len(g)})
    rows.sort(key=lambda r: (round(r["prom"], 6), -r["dir"] / r["n"]))
    lineas = [cab]
    for i, r in enumerate(rows):
        flag = " 👍" if i == 0 else ""
        lineas.append(f"• Que {r['o']}: sale 1º en {r['uno']}/{r['n']} · clasifica directo en {r['dir']}/{r['n']}{flag}")
    return "\n\n".join(lineas)

def combo_ideal_texto(equipo, esc, pend, directo=None):
    """Cierra el 'conviene' con el combo ideal: lo propio + lo de los otros en una frase."""
    d = DIRECTO() if directo is None else directo
    if not pend:
        return ""
    pos = esc[f"Pos {equipo}"]; best = int(pos.min())
    mios = _pd_de(equipo, pend)
    df = esc.copy(); df["_p"] = df.apply(lambda r: _res_propio(r, equipo, pend), axis=1)
    verd = "sale 1º" if best == 1 else (f"clasifica (termina {best}º)" if best <= d else f"termina {best}º")
    # ¿algún resultado propio garantiza el mejor puesto sin depender de nadie?
    solo = None
    if mios:
        for prop, g in df.groupby("_p"):
            gp = esc.loc[g.index, f"Pos {equipo}"]
            if int(gp.max()) == best:
                if solo is None or prop.startswith("le gana"):
                    solo = prop
    if solo:
        return f"🎯 **Escenario ideal de {equipo}:** que **{solo}** — con eso {verd} sin depender de nadie."
    # combinar: elegir el mejor resultado propio (preferir ganar) y, dentro, un combo de otros que logre 'best'
    cand = []
    for prop, g in df.groupby("_p"):
        gp = esc.loc[g.index, f"Pos {equipo}"]
        cand.append((int(gp.min()), 0 if prop.startswith("le gana") else (1 if prop.startswith("empata") else 2), prop, g.index))
    cand.sort()
    _, _, prop_best, idx = cand[0]
    sub = esc.loc[idx]
    sub = sub[sub[f"Pos {equipo}"] == best]
    if len(sub) == 0:
        return ""
    row = esc.loc[sub.index[0]]
    otros = _res_otros(row, equipo, pend)
    if mios and otros and otros != "(no hay otros partidos)":
        return f"🎯 **Escenario ideal de {equipo}:** que **{prop_best}** y que en los otros **{otros}** → así {verd}."
    if mios:
        return f"🎯 **Escenario ideal de {equipo}:** que **{prop_best}** → así {verd}."
    return f"🎯 **Escenario ideal de {equipo}:** que en los otros partidos **{_combo(row, pend)}** → así {verd}."

def _efecto_eq(team, sub, d, hay3):
    pos = sub[f"Pos {team}"]; rd = float((pos <= d).mean())
    if rd >= 0.999:
        return "termina 1º" if float((pos == 1).mean()) >= 0.999 else "clasifica"
    if rd <= 0.001:
        if hay3 and float((pos == 3).mean()) > 0:
            return "queda a pelear el 3º"
        return "queda afuera"
    return "queda a depender"

def _match_define(a, b, esc, i, d, hay3):
    teams = []
    for t in (a, b):
        efs = set()
        for res in ("L", "E", "V"):
            sub = filtrar_esc(esc, {i: res})
            if len(sub):
                efs.add(_efecto_eq(t, sub, d, hay3))
        if len(efs) > 1:
            teams.append(t)
    return teams

def previa_fecha_texto(eqs, jug, esc, pend):
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    if not pend:
        return "No quedan partidos: el grupo ya está definido."
    sc = bisagra_scores(eqs, jug, pend, esc)
    L = ["**Previa de la fecha — qué se define en cada partido:**"]
    for s in sc:
        a, b = s["match"]; afect = _match_define(a, b, esc, s["i"], d, hay3)
        head = ("define la clasificación de " + ", ".join(afect)) if afect else "incide solo en el desempate"
        L.append(f"\n**{a} vs {b}** — {head}.")
        for res, lbl in [("L", f"Gana {a}"), ("E", "Empate"), ("V", f"Gana {b}")]:
            sub = filtrar_esc(esc, {s["i"]: res})
            if len(sub) == 0:
                continue
            L.append(f"- {lbl}: {a} {_efecto_eq(a, sub, d, hay3)}; {b} {_efecto_eq(b, sub, d, hay3)}.")
    return "\n\n".join(L)

def placa_previa_fecha_png(eqs, jug, esc, pend, etiqueta=""):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    from io import BytesIO
    d = DIRECTO(); hay3 = MEJORES_TERCEROS() > 0
    sc = bisagra_scores(eqs, jug, pend, esc)
    if not sc:
        return None
    nblocks = len(sc); rows = nblocks * 4
    fig, ax = plt.subplots(figsize=(8.4, 0.52 * rows + 1.2), dpi=200)
    ax.set_xlim(0, 12); ax.set_ylim(0, rows); ax.axis("off")
    titulo = "Previa de la fecha: ¿qué define cada partido?" + (f"  ·  Grupo {etiqueta}" if etiqueta else "")
    ax.set_title(titulo, fontsize=14.5, fontweight="bold", color="#1a1a2e", loc="left", pad=12)
    y = rows
    colmap = {"L": "#1b5e20", "E": "#9e9e9e", "V": "#1b5e20"}
    import textwrap
    for s in sc:
        a, b = s["match"]; afect = _match_define(a, b, esc, s["i"], d, hay3)
        head = ("Define la clasificación de " + ", ".join(afect)) if afect else "Incide solo en el desempate"
        y -= 1
        ax.add_patch(FancyBboxPatch((0.1, y + 0.08), 11.8, 0.86, boxstyle="round,pad=0.02,rounding_size=0.08",
                                    facecolor="#1a1a2e", edgecolor="none"))
        ax.text(0.35, y + 0.62, f"{display_team(a)} vs {display_team(b)}", ha="left", va="center", color="white", fontsize=11.5, fontweight="bold")
        ax.text(0.35, y + 0.27, head, ha="left", va="center", color="#cfe3cf", fontsize=9, style="italic")
        for res, lbl in [("L", f"Gana {a}"), ("E", "Empate"), ("V", f"Gana {b}")]:
            sub = filtrar_esc(esc, {s["i"]: res}); y -= 1
            if len(sub) == 0:
                continue
            ax.add_patch(FancyBboxPatch((0.3, y + 0.1), 3.3, 0.78, boxstyle="round,pad=0.02,rounding_size=0.08",
                                        facecolor=colmap[res], edgecolor="none"))
            lbl_w = "\n".join(textwrap.wrap(editorialize_text(lbl), 16))
            fs = 10.5 if len(lbl) <= 14 else 9
            ax.text(1.95, y + 0.5, lbl_w, ha="center", va="center", color="white", fontsize=fs, fontweight="bold")
            ax.text(3.85, y + 0.5, f"{display_team(a)} {_efecto_eq(a, sub, d, hay3)}  ·  {display_team(b)} {_efecto_eq(b, sub, d, hay3)}",
                    ha="left", va="center", color="#1a1a2e", fontsize=10.5)
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.25); plt.close(fig)
    return buf.getvalue()

def _frase_equipo(equipo, eqs, jug, esc, pend):
    s = situacion(equipo, esc)
    if s["ya_directo"]:
        if s.get("ya_1"): return "ya está 1º y clasificado."
        if s.get("puede_1"): return "ya clasificado; todavía pelea el 1º."
        return "ya clasificado."
    if s["eliminado"]:
        return "ya sin chances."
    br = arbol_branches(equipo, eqs, jug, esc, pend)
    if not br:
        cat, manos = en_sus_manos(equipo, esc, pend)
        return manos + "."
    vd = {}
    for b in br:
        lab = b["label"].lower()
        if lab.startswith("le gana"): vd["G"] = b["verd"]
        elif lab.startswith("empata"): vd["E"] = b["verd"]
        elif lab.startswith("pierde"): vd["P"] = b["verd"]
    G, E, P = vd.get("G"), vd.get("E"), vd.get("P")
    if E == "Clasifica":
        if G == "Clasifica" and s.get("puede_1"):
            return "con un empate ya pasa; ganando puede ser 1º."
        return "le alcanza con un empate."
    if G == "Clasifica":
        if E == "Depende":
            return "gana y pasa; si empata, queda a depender de otros."
        if "Pelea 3º" in (E, P):
            return "gana y pasa; si no, a esperar como mejor 3º."
        return "tiene que ganar para clasificar."
    if G == "Depende":
        return "ni ganando se asegura: necesita ganar y que lo ayuden."
    if G == "Pelea 3º":
        return "fuera de los 2 primeros; se juega la chance de mejor 3º."
    return "complicado: necesita ganar y esperar resultados."

def que_se_juega_texto(eqs, jug, esc, pend):
    t = tabla(eqs, jug)
    L = ["**Qué se juega cada equipo:**"]
    for _, r in t.iterrows():
        e = r["Equipo"]
        L.append(f"**{e}** ({int(r['PTS'])} pts): {_frase_equipo(e, eqs, jug, esc, pend)}")
    return "\n\n".join(L)

def placa_que_se_juega_png(eqs, jug, esc, pend, etiqueta=""):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import textwrap
    from io import BytesIO
    t = tabla(eqs, jug); filas = list(t["Equipo"])
    n = len(filas); fig, ax = plt.subplots(figsize=(8.2, 0.95 * n + 1.2), dpi=200)
    ax.set_xlim(0, 12); ax.set_ylim(0, n); ax.axis("off")
    titulo = "¿Qué se juega cada equipo?" + (f"  ·  Grupo {etiqueta}" if etiqueta else "")
    ax.set_title(titulo, fontsize=15.5, fontweight="bold", color="#1a1a2e", loc="left", pad=12)
    for j, e in enumerate(filas):
        y = n - 0.5 - j
        s = situacion(e, esc)
        col = "#1b5e20" if s["ya_directo"] else ("#b71c1c" if s["eliminado"] else "#37474f")
        ax.add_patch(FancyBboxPatch((0.1, y - 0.38), 3.0, 0.76, boxstyle="round,pad=0.02,rounding_size=0.1",
                                    facecolor=col, edgecolor="none"))
        ax.text(1.6, y, display_team(e), ha="center", va="center", color="white", fontsize=11.5, fontweight="bold")
        frase = _frase_equipo(e, eqs, jug, esc, pend)
        ax.text(3.35, y, "\n".join(textwrap.wrap(frase, 52)), ha="left", va="center", fontsize=11, color="#1a1a2e")
    fig.text(0.01, -0.015, "Verde = ya clasificado · Rojo = sin chances · Gris = en juego.", fontsize=8.5, style="italic", color="#666")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", pad_inches=0.25); plt.close(fig)
    return buf.getvalue()

def resumen_grupo_texto(equipos, jugados, esc=None, pend=None, directo=None):
    """Pantallazo en texto del grupo: líder, escoltas y estado de la pelea."""
    d = DIRECTO() if directo is None else directo
    t = tabla(equipos, jugados); top = t.iloc[0]
    txt = f"📋 **{top['Equipo']}** lidera con **{int(top['PTS'])} pts**"
    if len(t) > 1: txt += f", escolta {t.iloc[1]['Equipo']} ({int(t.iloc[1]['PTS'])})."
    else: txt += "."
    partes = [txt]
    if pend: partes.append("Falta(n): " + ", ".join(f"{l} vs {v}" for l, v in pend) + ".")
    if esc is not None:
        S = {e: situacion(e, esc, d) for e in equipos}
        clas = [e for e in equipos if S[e]["ya_directo"]]
        elim = [e for e in equipos if S[e]["eliminado"]]
        disp = [e for e in equipos if not S[e]["ya_directo"] and not S[e]["eliminado"]]
        if clas: partes.append("Ya clasificó: " + ", ".join(clas) + ".")
        if elim: partes.append("Sin chances: " + ", ".join(elim) + ".")
        pelean = [e for e in disp if S[e]["puede_directo"]]
        if len(pelean) >= 2 and len(clas) < d:
            partes.append(f"Pelean por entrar: {', '.join(pelean)}.")
        elif disp:
            partes.append("En disputa: " + ", ".join(disp) + ".")
    return " ".join(partes)

def necesita_por_resultados_texto(equipo, equipos, jugados, pendientes, n=None):
    """Para muchos partidos: razona por resultado (G/E/P) y puntos, sin simular goles."""
    n = DIRECTO() if n is None else n
    if not pendientes:
        return "No quedan partidos."
    base = {e: _stats(equipos, jugados)[e]["pts"] for e in equipos}
    mios  = [i for i, p in enumerate(pendientes) if equipo in p]
    otros = [i for i in range(len(pendientes)) if i not in mios]
    meta     = f"ser {CAMPEON()}" if n == 1 else f"clasificar (top {n})"
    verbo_ok = f"es {CAMPEON()}"  if n == 1 else f"entra al top {n}"
    porpts = {}
    for own in product("LEV", repeat=len(mios)):
        add = {e: 0 for e in equipos}
        for k, i in enumerate(mios):
            l, v = pendientes[i]
            if own[k] == "L": add[l] += 3
            elif own[k] == "V": add[v] += 3
            else: add[l] += 1; add[v] += 1
        for oth in product("LEV", repeat=len(otros)):
            final = {e: base[e] + add[e] for e in equipos}
            for k, i in enumerate(otros):
                l, v = pendientes[i]
                if oth[k] == "L": final[l] += 3
                elif oth[k] == "V": final[v] += 3
                else: final[l] += 1; final[v] += 1
            p = final[equipo]
            arriba = sum(1 for x in equipos if x != equipo and final[x] > p)
            igual  = sum(1 for x in equipos if x != equipo and final[x] == p)
            rem    = n - arriba
            porpts.setdefault(p, []).append("safe" if rem >= igual + 1 else ("out" if rem <= 0 else "tie"))
    niveles  = sorted(porpts, reverse=True)
    safe_pts = [p for p in niveles if all(s == "safe" for s in porpts[p])]
    out_pts  = [p for p in niveles if all(s == "out"  for s in porpts[p])]
    medio    = [p for p in niveles if p not in safe_pts and p not in out_pts]
    total_comb = 3 ** len(pendientes)
    lineas = [f"**¿Qué necesita {equipo} para {meta}?** — por resultados ({total_comb:,} combinaciones)\n"]
    if safe_pts:
        lineas.append(f"✅ Con **{min(safe_pts)} pts** o más: {equipo} {verbo_ok} **pase lo que pase**.")
    if medio:
        borde = any("tie" in porpts[p] for p in medio)
        rng = f"{min(medio)} a {max(medio)}" if min(medio) != max(medio) else f"{medio[0]}"
        lineas.append(f"⚠️ Con **{rng} pts**: depende de los otros resultados" +
                      (" (y en algunos casos de la diferencia de gol)" if borde else "") + ".")
    if out_pts:
        lineas.append(f"❌ Con **{max(out_pts)} pts** o menos: no le alcanza.")
    lineas.append("\n_(Se razona por resultados; los empates de puntos por el último cupo se deciden por diferencia de gol.)_")
    return "\n\n".join(lineas)

# ─── TORNEO COMPLETO ─────────────────────────────────────────────────────────────
def analizar_torneo(texto):
    d = DIRECTO(); tablas, terceros, directos, avisos = {}, [], [], []
    for lab, txt in dividir_grupos(texto).items():
        eq, jug, pen = parsear_resultados(txt)
        if len(eq) < 3: avisos.append(f"Grupo {lab}: pocos equipos."); continue
        t = tabla(eq, jug); tablas[lab] = t
        if pen: avisos.append(f"Grupo {lab}: faltan {len(pen)} partido(s) → terceros provisorios.")
        for _, r in t.iterrows():
            if r["Pos"] <= d: directos.append((lab, r["Equipo"], int(r["Pos"])))
            if r["Pos"] == 3: terceros.append((f"{lab} · {r['Equipo']}", int(r["PTS"]), int(r["DG"]), int(r["GF"])))
    def clave(t): return (t[1], t[2], t[3])
    tbl3 = (pd.DataFrame([{"Pos": i, "Grupo": t[0], "PTS": t[1], "DG": t[2], "GF": t[3],
                            "Clasifica": "✅ sí" if i <= MEJORES_TERCEROS() else "❌ no"}
                           for i, t in enumerate(sorted(terceros, key=clave, reverse=True), 1)])
            if terceros and MEJORES_TERCEROS() > 0 else None)
    return tablas, directos, tbl3, avisos

# ─── PARSER ─────────────────────────────────────────────────────────────────────
_MESES = r"(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic|jan|apr|aug|dec)"
_DIAS  = r"(lun|mar|mié|mie|jue|vie|sáb|sab|dom|mon|tue|wed|thu|fri|sat|sun)"
_RE_SCORE = re.compile(r"^(.+?)\s+(\d{1,2})\s*(?:[-–—xX]\s*(\d{1,2})|:\s*(\d))\s+(.+?)$")
_RE_VS    = re.compile(r"^(.+?)\s+(?:vs?\.?|–|—|-|x)\s+(.+?)$", re.I)

def _limpiar(ln):
    ln = ln.strip()
    pref = [rf"^{_DIAS}\w*\.?,?\s+", r"^\d{1,2}[:.]\d{2}\s+",
            r"^\d{1,2}[/\-.]\d{1,2}([/\-.]\d{2,4})?\s+",
            rf"^\d{{1,2}}\s+{_MESES}\w*\.?,?\s+", rf"^{_MESES}\w*\.?\s+\d{{1,2}},?\s+"]
    ch = True
    while ch:
        ch = False
        for p in pref:
            nu = re.sub(p, "", ln, flags=re.I)
            if nu != ln: ln = nu; ch = True
    ln = re.sub(r"\s*\(.*?\)\s*$", "", ln)
    ln = re.sub(r"\s*(FT|Finalizado|Final|Termin\w*|Ver resumen|Resumen)\s*$", "", ln, flags=re.I)
    return ln.strip()

def _norm(t): return re.sub(r"\s+", " ", t).strip(" -–—\t")
def _let(t):  return bool(re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]", t))

def parsear_resultados(texto):
    jug, pen, eq = [], [], []
    def add(t):
        if t and t not in eq: eq.append(t)
    for raw in texto.splitlines():
        ln = _limpiar(raw)
        if not ln: continue
        m = _RE_SCORE.match(ln)
        if m:
            loc, vis = _norm(m.group(1)), _norm(m.group(5))
            gl = int(m.group(2)); gv = int(m.group(3) if m.group(3) is not None else m.group(4))
            if _let(loc) and _let(vis): add(loc); add(vis); jug.append((loc, vis, gl, gv)); continue
        m = _RE_VS.match(ln)
        if m:
            loc, vis = _norm(m.group(1)), _norm(m.group(2))
            if _let(loc) and _let(vis) and not re.search(r"\d", loc + vis):
                add(loc); add(vis); pen.append((loc, vis))
    jp = {frozenset((l, v)) for l, v, _, _ in jug}
    pp = {frozenset(p) for p in pen}
    for a, b in combinations(eq, 2):
        fs = frozenset((a, b))
        if fs not in jp and fs not in pp: pen.append((a, b)); pp.add(fs)
    return eq, jug, pen

_RE_HEADER = re.compile(r"^\s*(grupo|group|gpo)\s*[:.]?\s*([A-Za-z0-9]+)\s*[:.]?\s*$", re.I)

def dividir_grupos(texto):
    g, act, suelto = {}, None, []
    for ln in texto.splitlines():
        m = _RE_HEADER.match(ln.strip())
        if m: act = m.group(2).upper(); g.setdefault(act, [])
        else: (g[act] if act is not None else suelto).append(ln)
    if not g and any(s.strip() for s in suelto): g["Único"] = suelto
    return {k: "\n".join(v) for k, v in g.items()}

# ─── API ─────────────────────────────────────────────────────────────────────────
_FIN = {"FINISHED", "AWARDED"}

def _grp(lbl): return re.split(r"[ _]", str(lbl).strip())[-1].upper() if lbl else "?"
def _nom(t):   return (t.get("shortName") or t.get("name") or t.get("tla") or "¿?").strip()

def matches_a_texto(matches):
    grupos = {}; liga = []
    for m in matches:
        loc, vis = _nom(m["homeTeam"]), _nom(m["awayTeam"])
        ft = (m.get("score") or {}).get("fullTime") or {}; gl, gv = ft.get("home"), ft.get("away")
        jugado = m.get("status") in _FIN and gl is not None and gv is not None
        linea = f"{loc} {gl}-{gv} {vis}" if jugado else f"{loc} vs {vis}"
        if "GROUP" in str(m.get("stage", "")).upper() or m.get("group"):
            grupos.setdefault(_grp(m.get("group")), []).append(linea)
        elif str(m.get("stage", "")).upper() == "REGULAR_SEASON":
            liga.append(linea)
    out = []
    if grupos:
        for g in sorted(grupos):
            out += [f"Grupo {g}", *grupos[g], ""]
    elif liga:
        out += liga  # liga entera: una sola tabla, sin encabezado de grupo
    return "\n".join(out).strip()

def traer_de_api(token, comp="WC"):
    base = f"https://api.football-data.org/v4/competitions/{comp}"
    h = {"X-Auth-Token": (token or "").strip()}
    r = requests.get(base + "/matches", headers=h, timeout=30)
    if r.status_code == 200:
        return r.json().get("matches", [])
    # football-data manda el motivo real en el cuerpo JSON
    try:
        msg = r.json().get("message", "") or r.text[:200]
    except Exception:
        msg = (r.text or "")[:200]
    # Si falla sin temporada, busco la temporada actual y reintento (útil para copas como el Mundial)
    try:
        info = requests.get(base, headers=h, timeout=30)
        if info.status_code == 200:
            cs = info.json().get("currentSeason") or {}
            yr = str(cs.get("startDate") or "")[:4]
            if yr:
                r2 = requests.get(base + f"/matches?season={yr}", headers=h, timeout=30)
                if r2.status_code == 200:
                    return r2.json().get("matches", [])
                try:
                    msg = r2.json().get("message", "") or msg
                except Exception:
                    pass
    except Exception:
        pass
    raise RuntimeError(f"{r.status_code} — {msg}" if msg else f"{r.status_code} (sin detalle de la API)")

def listar_competiciones(token):
    r = requests.get("https://api.football-data.org/v4/competitions",
                     headers={"X-Auth-Token": token}, timeout=30)
    r.raise_for_status()
    return [(c.get("code"), c.get("name")) for c in r.json().get("competitions", [])]

# ─── HELPER: cargar estado ────────────────────────────────────────────────────────
def cargar_estado(equipos, jugados, pendientes):
    mg = elegir_max_goles(len(pendientes))
    total = (mg+1)**(2*len(pendientes))
    if total > 200000:   # demasiados partidos (liga): no se puede enumerar, vamos por puntos
        st.session_state.ESTADO = dict(equipos=equipos, jugados=jugados, pendientes=pendientes,
                                       esc=None, mg=mg, solo_puntos=True)
        return
    with st.spinner(f"Calculando {_fmt_entero_es(total)} escenarios…"):
        esc = todos_los_escenarios(equipos, jugados, pendientes, mg)
    st.session_state.ESTADO = dict(equipos=equipos, jugados=jugados, pendientes=pendientes,
                                   esc=esc, mg=mg, solo_puntos=False)
    return esc

def _procesar_import(jg, pd_, ligas, filtro, solo_fixture=False):
    """Carga lo importado: como estado completo, o solo como fixture de la liga (tabla) ya cargada."""
    if len(ligas) > 1 and not (filtro or "").strip():
        ui_warning("Hay varias ligas en el export. Afiná el filtro con alguna de estas:")
        for lg, cnt in sorted(ligas.items(), key=lambda kv: -kv[1])[:12]:
            ui_caption(f"· {lg} ({cnt})")
        return False
    if solo_fixture:
        E = st.session_state.ESTADO
        if not (E and E.get("modo") == "liga_tabla"):
            ui_error("Primero cargá la tabla (fuente «Pegar tabla + fixture»)."); return False
        pares, caidos = mapear_fixture(pd_ or [], E["equipos"])
        if not pares:
            ui_error("No pude emparejar los partidos con los equipos de tu tabla. Revisá los nombres."); return False
        E["pendientes"] = pares
        E["rest"] = liga_restantes(E["equipos"], pares, None)
        E["gleft"] = None
        st.session_state.ESTADO = E
        ui_success(f"Fixture actualizado: {len(pares)} partidos emparejados" +
                   (f" ({len(caidos)} sin emparejar: {', '.join(caidos[:3])}…)" if caidos else " ✓"))
        return True
    eqs_imp = sorted({t for par in ((jg or []) + (pd_ or [])) for t in (par[0], par[1])})
    if len(eqs_imp) < 3:
        ui_error("Muy pocos equipos tras el filtro. Revisá el filtro o el export."); return False
    if not jg and not pd_:
        ui_error("No encontré partidos válidos tras el filtro."); return False
    cargar_estado(eqs_imp, jg, pd_)
    ui_success(f"Importados {len(jg)} resultados y {len(pd_)} por jugar ({len(eqs_imp)} equipos) ✓")
    return True

# ═══════════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════════

ui_markdown("""
<div class="main-header">
  <h1>⚽ Calculadora del Fútbol Argentino</h1>
  <p>Versión 3.1 · Base autorreparable, panel por equipo y auditoría por objetivo</p>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
#  TAREA 3 — Resultados partido a partido (forma / rachas / local-visitante)
#  Alimenta forma_equipo / racha_equipo / local_visitante_df y la fuerza del
#  simulador. La tabla (puntos/PJ/DG) sigue siendo la fuente autoritativa; estos
#  resultados se usan solo para forma/rachas/localía, nunca se re-suman a los puntos.
# ═══════════════════════════════════════════════════════════════════════════
RESULTADOS_LPF_FECHA_1_2026 = """Belgrano 2-1 Rosario Central
Sarmiento 2-3 Argentinos
Defensa y Justicia 1-1 Aldosivi
Gimnasia (Mza.) 1-0 Central Córdoba
Racing 2-1 Gimnasia
Vélez 1-0 Instituto
Huracán 1-0 Banfield
Platense 2-2 Unión
Estudiantes (Río Cuarto) 1-0 Tigre
Newell's 1-0 Talleres
River 0-1 Barracas Central
Lanús 1-0 San Lorenzo
Atlético Tucumán 0-0 Ind. Rivadavia Mza.
Estudiantes 0-2 Independiente
Deportivo Riestra 3-0 Boca"""

RESULTADOS_LPF_2026 = """Belgrano 2-1 Rosario Central
Sarmiento 2-3 Argentinos
Defensa y Justicia 1-1 Aldosivi
Gimnasia (Mza.) 1-0 Central Córdoba
Racing 2-1 Gimnasia
Vélez 1-0 Instituto
Huracán 1-0 Banfield
Platense 2-2 Unión
Estudiantes (Río Cuarto) 1-0 Tigre
Newell's 1-0 Talleres
River 0-1 Barracas Central
Lanús 1-0 San Lorenzo
Atlético Tucumán 0-0 Ind. Rivadavia Mza.
Estudiantes 0-2 Independiente
Deportivo Riestra 3-0 Boca
Banfield 3-2 Sarmiento
San Lorenzo 1-0 Gimnasia (Mza.)
Rosario Central 0-0 Racing
Argentinos 3-0 Estudiantes (Río Cuarto)
Barracas Central 1-0 Aldosivi
Defensa y Justicia 2-1 Deportivo Riestra
Gimnasia 1-0 River
Instituto 2-1 Platense
Independiente Rivadavia Mza. 2-1 Huracán
Talleres 1-3 Vélez
Independiente 1-0 Newell's
Central Córdoba 0-2 Atlético Tucumán
Gimnasia (Mza.) 2-0 Unión
Estudiantes (Río Cuarto) 0-0 Banfield
Belgrano 0-1 Argentinos
Estudiantes 3-0 Defensa y Justicia
Racing 1-3 Tigre
Deportivo Riestra 0-1 Barracas Central
Aldosivi 1-2 Gimnasia
Newell's 2-2 Boca
River 0-1 Rosario Central
Lanús 0-1 Instituto
Sarmiento 2-1 Independiente Rivadavia Mza.
Platense 0-4 Talleres
Vélez 1-0 Independiente
Huracán 0-0 Atlético Tucumán
Central Córdoba 1-0 San Lorenzo
Boca 1-0 Estudiantes
Tigre 0-0 Belgrano
Unión 2-1 Lanús
Rosario Central 2-1 Aldosivi
Independiente Rivadavia Mza. 2-1 Estudiantes (Río Cuarto)
Deportivo Riestra 2-0 Estudiantes
Atlético Tucumán 1-2 Sarmiento"""

def parse_resultados_lpf(text=None, canon=None):
    """Parsea líneas «Local G1-G2 Visita» → lista de tuplas (local, visita, gl, gv)
    con nombres canónicos. Ignora líneas que no matcheen."""
    import re
    if text is None:
        text = RESULTADOS_LPF_2026
    if canon is None:
        canon = canon_club
    rgx = re.compile(r"^(.*?)\s+(\d+)\s*[-–:]\s*(\d+)\s+(.*)$")
    out = []
    for raw in str(text).splitlines():
        ln = raw.strip()
        if not ln:
            continue
        m = rgx.match(ln)
        if not m:
            continue
        out.append((canon(m.group(1)), canon(m.group(4)), int(m.group(2)), int(m.group(3))))
    return out





def _lpf_result_counts(played):
    counts = {}
    for local, visitor, _gl, _gv in played or []:
        counts[local] = counts.get(local, 0) + 1
        counts[visitor] = counts.get(visitor, 0) + 1
    return counts


















def _lpf_infer_single_missing_result(zones, baseline, fixture=None):
    """Compatibilidad: usa el reconciliador general y acepta sólo un partido."""
    inferred, note = _lpf_infer_missing_results(zones, baseline, fixture)
    return (inferred, note) if len(inferred) == 1 else ([], "")


def _lpf_builtin_results():
    return parse_resultados_lpf(RESULTADOS_LPF_2026)


def _lpf_builtin_opening_snapshot():
    """Foto fija y autoritativa del Apertura 2026.

    Se reconstruye una sola vez desde la Tabla Anual de referencia (17 PJ) y los
    15 resultados de la primera fecha del Clausura. Después, toda Tabla Anual
    vigente se obtiene sumando esta foto a las zonas actuales. La tabla anual
    pegada por el usuario queda como control, no como una segunda fuente viva.
    """
    annual_ref = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]
    played_ref = parse_resultados_lpf(RESULTADOS_LPF_FECHA_1_2026)
    opening, issues = derive_opening_from_results(
        annual_ref, LPF_FIXTURE, played_ref, opening_rounds=16
    )
    if any(issue.level == "blocked" for issue in issues):
        return {}
    return canon_base(opening)


LPF_APERTURA_BASE_2026 = _lpf_builtin_opening_snapshot()


def _lpf_opening_is_valid(opening, zones=None):
    """Adaptador de compatibilidad hacia el validador puro de estado LPF."""
    return opening_is_valid(opening, zones, opening_rounds=LPF_APERTURA_PJ)


def _lpf_forma_zona_df(base, jugados, n=5):
    """Tabla de forma de una zona SIN usar _stats (tolera rivales de la otra zona en
    los interzonales): puntos de la tabla + forma/racha por equipo."""
    rows = []
    for e in base:
        ult, p5 = forma_equipo(e, jugados, n)
        rows.append({"Equipo": e, "PTS": base[e]["pts"], "Últimos 5": "".join(ult) or "—",
                     "Pts últ. 5": p5, "Racha": racha_equipo(e, jugados)})
    return pd.DataFrame(rows).sort_values(["Pts últ. 5", "PTS"], ascending=False).reset_index(drop=True)

def _fuerza_lpf(base, jugados=None):
    """Wrapper Streamlit del modelo puro de fuerza regularizada."""
    opening = ((st.session_state.get("ESTADO") or {}).get("apertura") or
               st.session_state.get("LPF_APERTURA") or {})
    return _estimate_team_strength(base, jugados or [], opening)


def lpf_apertura_desde_anual(anual, zonas, jugados=None, games=None):
    """Deriva la tabla FIJA del Apertura a partir de la Anual cargada.

    El Apertura terminó, así que su tabla no cambia más. Guardándola, la Anual se
    recalcula siempre como Apertura + zonas actuales y ya no puede quedar vieja
    respecto de las zonas (origen de varios números incorrectos).

    Ojo: la Anual cargada puede incluir sólo parte del Clausura. Por eso no se resta
    la zona entera, sino únicamente los partidos de Clausura que la Anual sí incorporó
    (`anual_pj - 16`), tomados de los resultados conocidos.
    """
    games = games or LPF_FIXTURE
    fmap = {(g["l"], g["v"]): g["f"] for g in games}
    porfecha = {}
    for (l, v, gl, gv) in (jugados or []):
        f = fmap.get((l, v))
        if f is None:
            continue
        porfecha.setdefault(l, []).append((f, gl, gv))
        porfecha.setdefault(v, []).append((f, gv, gl))
    ap = {}
    for lab, base in (zonas or {}).items():
        for e in base:
            a = (anual or {}).get(e)
            if not a:
                continue
            n_inc = int(a.get("pj", 0)) - LPF_APERTURA_PJ      # partidos de Clausura ya sumados
            pts = int(a.get("pts", 0)); pj = int(a.get("pj", 0))
            gf = int(a.get("gf", 0)); ga = int(a.get("ga", 0))
            if n_inc > 0:
                mios = sorted(porfecha.get(e, []))[:n_inc]
                for (_f, favor, contra) in mios:
                    pts -= 3 if favor > contra else (1 if favor == contra else 0)
                    pj -= 1; gf -= favor; ga -= contra
                if len(mios) < n_inc:                # faltan resultados para restar
                    ap[e] = {"pts": pts, "pj": pj, "dg": gf - ga, "gf": gf, "ga": ga, "_dudoso": True}
                    continue
            ap[e] = {"pts": pts, "pj": pj, "dg": gf - ga, "gf": gf, "ga": ga}
    return ap

def _lpf_rebuild_state(zones, *, played=None, annual_direct=None, opening=None,
                       camps=None, intl=None, n_anual=1, n_prom=1):
    """Adaptador Streamlit del constructor puro de estado LPF."""
    resolved_camps = camps or (
        st.session_state.get("lpf_c1", "Belgrano"),
        st.session_state.get("lpf_c2", ""),
        st.session_state.get("lpf_c3", ""),
    )
    resolved_intl = intl or ("", "")
    state, report = build_lpf_state(
        zones,
        played=played,
        annual_direct=annual_direct,
        opening=opening,
        stored_opening=st.session_state.get("LPF_APERTURA") or {},
        builtin_opening=globals().get("LPF_APERTURA_BASE_2026") or {},
        promedios=st.session_state.get("PROMEDIOS") or {},
        fixture=LPF_FIXTURE,
        source_issues=st.session_state.get("PROM_SOURCE_ISSUES") or [],
        camps=resolved_camps,
        intl=resolved_intl,
        n_anual=n_anual,
        n_prom=n_prom,
        copa_arg_vivos=st.session_state.get("LPF_COPA_ARG_VIVOS") or [],
        copa_arg_updated=st.session_state.get("LPF_COPA_ARG_UPDATED", ""),
        copa_arg_source=st.session_state.get("LPF_COPA_ARG_SOURCE", ""),
        copa_arg_reemplazo=st.session_state.get("LPF_COPA_ARG_REEMPLAZO", ""),
        opening_rounds=LPF_APERTURA_PJ,
    )
    if report.opening_snapshot:
        st.session_state.LPF_APERTURA = state["apertura"]
    if report.authoritative_annual:
        st.session_state.LPF_ANUAL = state["anual_directo"]
    st.session_state.LPF_DATA_QUALITY = report
    return state, report


def _lpf_domain_ready(E, domain):
    """Indica si un dominio se puede publicar con la foto actual."""
    report = (E or {}).get("data_quality") or st.session_state.get("LPF_DATA_QUALITY")
    if not isinstance(report, DataQualityReport):
        return True, []
    aliases = {
        "playoffs": {"playoffs", "data"},
        "annual": {"annual", "data"},
        "copas": {"annual", "data"},
        "promedios": {"promedios", "annual", "data"},
        "descenso": {"promedios", "annual", "data"},
    }
    relevant = aliases.get(domain, {domain, "data"})
    blocked = [i for i in report.issues if i.level == "blocked" and i.domain in relevant]
    return not blocked, blocked


def _lpf_data_gate(E, domain):
    # También repara sesiones creadas por versiones anteriores antes de decidir.
    try:
        if (E or {}).get("modo") == "lpf2026":
            zones = (E or {}).get("zonas_lpf") or {}
            repaired = _lpf_complete_results_for_zones(
                zones,
                (E or {}).get("jugados") or [],
                parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or ""),
                _lpf_builtin_results(),
            )
            if repaired and len(repaired) != len((E or {}).get("jugados") or []):
                state, _report = _lpf_rebuild_state(
                    zones,
                    played=repaired,
                    annual_direct=(E or {}).get("anual_directo") or st.session_state.get("LPF_ANUAL") or {},
                    opening=(E or {}).get("apertura") or st.session_state.get("LPF_APERTURA") or {},
                    camps=(E or {}).get("camps"),
                    intl=(E or {}).get("intl"),
                    n_anual=(E or {}).get("n_anual", 1),
                    n_prom=(E or {}).get("n_prom", 1),
                )
                st.session_state.ESTADO = state
                st.session_state.LPF_RES_TXT = "\n".join(
                    f"{local} {gl}-{gv} {visitor}" for local, visitor, gl, gv in repaired
                )
                E = state
            _lpf_refresh_quality(E)
    except NameError:
        pass
    ready, issues = _lpf_domain_ready(E, domain)
    if ready:
        return None
    detail = "\n".join(f"- {issue.message}" for issue in issues[:8])
    return ("warning", "### Cálculo bloqueado por datos inconsistentes\n\n"
                       + detail
                       + "\n\nAbrí **Datos y auditoría** para corregir la base antes de publicar.")


def cargar_lpf_todo():
    """Carga la última foto offline válida y la reconcilia antes de calcular."""
    if _lpf_opening_is_valid(globals().get("LPF_APERTURA_BASE_2026") or {}):
        st.session_state.LPF_APERTURA = canon_base(LPF_APERTURA_BASE_2026)

    snap_zones, snap_annual, _snap_source, _snap_age, _snap_error = _load_lpf_snapshot()
    if snap_zones:
        zones = snap_zones
        st.session_state.LPF_ANUAL = canon_base(snap_annual)
    else:
        b_a = parse_tabla_anual(ZONA_A_LPF_2026)[0]
        b_b = parse_tabla_anual(ZONA_B_LPF_2026)[0]
        zones = {"A": canon_base(b_a), "B": canon_base(b_b)}
        if not st.session_state.get("LPF_ANUAL"):
            st.session_state.LPF_ANUAL = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]

    _pv0, _pav0, _prom_changed = _ensure_lpf_prom_history()
    if _prom_changed or not st.session_state.get("LPF_HIST_OK"):
        st.session_state.LPF_HIST_OK = f"{len(st.session_state.LPF_ANUAL)} equipos en la anual · {len(_pv0)} en promedios"

    prepared = prepare_offline_load(
        zones,
        manual_played=parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or ""),
        previous_played=list(((st.session_state.get("ESTADO") or {}).get("jugados") or [])),
        builtin_played=_lpf_builtin_results(),
    )
    zones = prepared["zones"]
    played = prepared["played"]
    if played and not st.session_state.get("LPF_RES_TXT"):
        st.session_state.LPF_RES_TXT = prepared["results_text"]

    state, report = _lpf_rebuild_state(
        zones,
        played=played,
        annual_direct=st.session_state.get("LPF_ANUAL") or {},
    )
    st.session_state.ESTADO = state
    _set_lpf_source_meta(
        source_name="Carga offline/manual",
        sources=("tablas/resultados incluidos o pegados en Streamlit",),
        warnings=("La carga offline/manual no informa un timestamp de origen verificable.",),
    )
    return len(zones["A"]), len(zones["B"]), len(state.get("anual_directo") or {}), len(state["pendientes"])

def cargar_lpf_espn(liga="arg.1"):
    """Actualiza tablas y reconcilia resultados entre fuentes públicas.

    Los marcadores de la web oficial LPF son la primera opción. ESPN y
    FutbolArgentino.com quedan como respaldo cuando la fuente oficial no alcanza.
    """
    # Este flujo se ejecuta por acción explícita del editor. No debe reutilizar un
    # scoreboard de minutos antes mientras la tabla ya refleja partidos terminados.
    for cached_getter in (_espn_get, _standings_html_get):
        try:
            cached_getter.clear()
        except Exception:
            pass

    if _lpf_opening_is_valid(globals().get("LPF_APERTURA_BASE_2026") or {}):
        st.session_state.LPF_APERTURA = canon_base(LPF_APERTURA_BASE_2026)

    zones, annual, source_name, source_warnings, err = lpf_tables_with_fallback(liga)
    if err:
        return None, err

    if annual:
        st.session_state.LPF_ANUAL = canon_base(annual)
    elif not st.session_state.get("LPF_ANUAL"):
        st.session_state.LPF_ANUAL = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]

    previous_state = st.session_state.get("ESTADO") or {}
    previous_played = list(previous_state.get("jugados") or [])
    manual_played = parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or "")
    builtin_played = _lpf_builtin_results()
    trusted_before_network = _merge_lpf_results(
        builtin_played, previous_played, manual_played
    )

    official_raw = []
    official_played = []
    official_error = ""
    official_url = LPF_OFFICIAL_PRIMERA_URL
    try:
        official_raw, _official_pending, official_url = lpf_official_results(
            zones, baseline_played=trusted_before_network, timeout=30
        )
        official_played = normalize_results_for_zones(zones, official_raw or [])
    except Exception as exc:
        official_error = str(exc)

    # Si la LPF oficial + la base validada ya reconstruyen exactamente la tabla,
    # no golpear proveedores que hoy pueden bloquear servidores (ESPN 403) o
    # devolver HTML sin resultados. Se mantienen como fallback real.
    official_complete = _lpf_complete_results_for_zones(
        zones, manual_played, official_played, previous_played, builtin_played
    )

    jug_raw = []
    espn_played = []
    nota_espn = ""
    ferr_espn = ""
    fa_raw = []
    fa_played = []
    fa_error = ""
    fa_url = ""
    if not official_complete:
        jug_raw, _pen_raw, nota_espn, ferr_espn = espn_fixture(
            liga, 120, desde="2026-07-01"
        )
        espn_played = normalize_results_for_zones(zones, jug_raw or [])
        try:
            fa_raw, _fa_pending, fa_url = futbolargentino_fixture(zones, timeout=30)
            fa_played = normalize_results_for_zones(zones, fa_raw or [])
        except Exception as exc:
            fa_error = str(exc)
    opening_for_reconcile = canon_base(
        st.session_state.get("LPF_APERTURA")
        or globals().get("LPF_APERTURA_BASE_2026")
        or {}
    )

    prepared = prepare_automatic_update(
        zones,
        annual=annual or {},
        opening=opening_for_reconcile,
        manual_played=manual_played,
        previous_played=previous_played,
        builtin_played=builtin_played,
        futbolargentino_played=fa_played,
        espn_played=espn_played,
        official_played=official_played,
        fixture=LPF_FIXTURE,
    )
    zones = prepared["zones"]
    played = prepared["played"]
    reconcile_note = prepared["reconcile_note"]
    reconciled_annual = prepared["reconciled_annual"]
    inferred_played = prepared["inferred_played"]
    inferred_note = prepared["inferred_note"]
    coverage_note = prepared["coverage_note"]
    diagnostic_notes = prepared["diagnostic_notes"]

    if reconcile_note:
        source_warnings = list(source_warnings or []) + [reconcile_note]
        source_name = f"{source_name} + resultados finales conciliados"
        if reconciled_annual:
            st.session_state.LPF_ANUAL = canon_base(reconciled_annual)

    source_notes = []
    if official_played:
        source_notes.append(f"LPF oficial: {len(official_played)} resultados")
    if fa_played:
        source_notes.append(f"FutbolArgentino.com: {len(fa_played)} resultados")
    if espn_played:
        source_notes.append(f"ESPN: {len(espn_played)} resultados")
    if inferred_played:
        source_notes.append(
            f"conciliación determinística: {len(inferred_played)} resultado"
            + ("s" if len(inferred_played) != 1 else "")
        )
    if nota_espn:
        source_notes.append(str(nota_espn).strip("()"))
    nota = "(" + " · ".join(source_notes) + ")" if source_notes else ""

    result_source_warnings = []
    if official_error:
        result_source_warnings.append("LPF oficial no pudo completar los resultados: " + official_error)
    if ferr_espn:
        result_source_warnings.append("ESPN no pudo completar los resultados: " + ferr_espn)
    if fa_error:
        result_source_warnings.append("FutbolArgentino.com no pudo completar los resultados: " + fa_error)
    if official_raw and not official_played:
        result_source_warnings.append(
            f"LPF oficial devolvió {len(official_raw)} partido(s), pero ninguno coincidió con los clubes/fixture de la tabla cargada."
        )
    if jug_raw and not espn_played:
        result_source_warnings.append(
            f"ESPN devolvió {len(jug_raw)} partido(s), pero ninguno coincidió con los clubes/fixture de la tabla cargada."
        )
    if fa_raw and not fa_played:
        result_source_warnings.append(
            f"FutbolArgentino.com devolvió {len(fa_raw)} partido(s), pero ninguno coincidió con los clubes/fixture de la tabla cargada."
        )
    if inferred_note:
        result_source_warnings.append(inferred_note)

    # La actualización es transaccional: una consulta vacía o incompleta jamás
    # reemplaza una foto válida por cero resultados. Si ninguna combinación explica
    # los PJ actuales, se conserva el estado anterior y se informa el problema.
    if not played:
        previous_zones = previous_state.get("zonas_lpf") or {}
        if previous_state and previous_zones:
            return {
                "A": len(previous_zones.get("A", {})),
                "B": len(previous_zones.get("B", {})),
                "anual": len(previous_state.get("anual_directo") or {}),
                "jug": len(previous_played),
                "pend": len(previous_state.get("pendientes") or []),
                "nota": nota or "",
                "fixture_err": "Las fuentes de resultados no reconstruyen la tabla publicada.",
                "calidad": getattr(previous_state.get("data_quality"), "level", "warning"),
                "sin_confirmar": sum(
                    r.status == "unconfirmed"
                    for r in getattr(previous_state.get("data_quality"), "match_records", [])
                ),
                "fuente": source_name,
                "avisos_fuente": list(source_warnings or []) + result_source_warnings + [
                    coverage_note,
                    *diagnostic_notes[:2],
                    "No reemplacé la base anterior porque los resultados no explicaban los PJ de la tabla."
                ],
            }, None
        detail_parts = []
        detail_parts.extend(result_source_warnings[:2])
        detail_parts.extend(diagnostic_notes[:2])
        detail = (" " + " ".join(detail_parts)) if detail_parts else ""
        return None, (
            "Las tablas se actualizaron, pero ninguna fuente de resultados explica "
            "exactamente PJ, puntos y goles publicados. " + coverage_note + detail +
            " No se reemplazó la base con datos incompletos."
        )

    st.session_state.LPF_RES_TXT = prepared["results_text"]
    _ensure_lpf_prom_history()

    state, report = _lpf_rebuild_state(
        zones,
        played=played,
        annual_direct=(reconciled_annual or st.session_state.get("LPF_ANUAL") or {}),
        opening=st.session_state.get("LPF_APERTURA") or {},
    )
    st.session_state.ESTADO = state
    import datetime as _dt
    _source_updated_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if str(source_name).startswith("Último respaldo válido"):
        _source_updated_at = (st.session_state.get("LPF_LAST_VALID_SNAPSHOT") or {}).get("updated_at")
    _result_source_name = " + ".join(
        [name for name, rows in (
            ("Liga Profesional de Fútbol", official_played),
            ("FutbolArgentino.com", fa_played),
            ("ESPN", espn_played),
        ) if rows]
        + (["conciliación por resultados finales"] if reconcile_note else [])
        + (["conciliación determinística por tabla"] if inferred_played else [])
    ) or "base validada"
    _set_lpf_source_meta(
        source_name=source_name,
        sources=(source_name, _result_source_name),
        warnings=list(source_warnings or []) + result_source_warnings,
        updated_at=_source_updated_at,
    )
    if reconcile_note and state.get("anual_directo"):
        disk_warning = _save_lpf_snapshot(
            zones, state.get("anual_directo") or {}, source_name
        )
        if disk_warning:
            source_warnings = list(source_warnings or []) + [disk_warning]
    return {
        "A": len(zones.get("A", {})),
        "B": len(zones.get("B", {})),
        "anual": len(st.session_state.get("LPF_ANUAL") or {}),
        "jug": len(played),
        "pend": len(state["pendientes"]),
        "nota": nota or "",
        "fixture_err": "",
        "calidad": report.level,
        "sin_confirmar": sum(r.status == "unconfirmed" for r in report.match_records),
        "fuente": source_name,
        "avisos_fuente": list(source_warnings or []) + result_source_warnings,
        "fuente_resultados": _result_source_name,
        "url_resultados": official_url if official_played else fa_url,
    }, None

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔧 Configuración")
    ui_caption(f"Motor de cálculo · v{__version__}")

    # Desempate
    st.subheader("Criterio de desempate")
    preset_sel = ui_selectbox("Regla", list(PRESETS.keys()), label_visibility="collapsed")
    if PRESETS[preset_sel] != st.session_state.CRITERIOS:
        st.session_state.CRITERIOS = PRESETS[preset_sel]
        if st.session_state.ESTADO:
            E = st.session_state.ESTADO
            if E.get("modo") != "lpf2026":
                cargar_estado(E["equipos"], E["jugados"], E["pendientes"])
            st.rerun()

    st.divider()

    # Estructura de clasificación
    st.subheader("Estructura de clasificación")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.DIRECTO = st.number_input("Clasifican directos", min_value=1, max_value=10, value=st.session_state.DIRECTO)
    with col2:
        st.session_state.MEJORES_TERCEROS = st.number_input("Mejores 3ºs", min_value=0, max_value=20, value=st.session_state.MEJORES_TERCEROS,
                                                              help="0 = los terceros NO clasifican")
    st.session_state.CAMPEON = st.text_input("Nombre del 1º", value=st.session_state.CAMPEON,
                                              help='Ej: "campeón", "1º de zona", "ganador del grupo"')

    with st.expander("🎨 Zonas con nombre (para ligas)"):
        ui_caption("Pinta la tabla por zonas. Una por línea: «hasta_puesto nombre». Ej.: «3 Libertadores».")
        _PZ = {"(sin zonas)": "",
               "Liga Argentina (tabla anual)": "3 Libertadores\n9 Sudamericana\n29 Permanece\n30 Descenso",
               "Clasificación simple": "4 Clasifica\n17 Permanece\n20 Descenso"}
        _pzsel = ui_selectbox("Preset", list(_PZ.keys()), key="zpreset")
        if st.session_state.get("_zlast") != _pzsel:
            st.session_state.ZONAS_TXT = _PZ[_pzsel]
            st.session_state["_zlast"] = _pzsel
        _ztxt = st.text_area("Zonas", value=st.session_state.ZONAS_TXT, height=120, label_visibility="collapsed")
        st.session_state.ZONAS_TXT = _ztxt
        st.session_state.ZONAS = parse_zonas(_ztxt)
        if st.session_state.ZONAS:
            ui_caption("Activas: " + " · ".join(f"≤{h} {n}" for h, n, _ in st.session_state.ZONAS))

    with st.expander("📉 Promedios (descenso a la argentina)"):
        if "prom_tabla_fetch" in st.session_state:
            st.session_state["prom_tabla_txt"] = st.session_state.pop("prom_tabla_fetch")
        if st.button("🇦🇷 Cargar histórico de promedios LPF 2026", use_container_width=True):
            _ensure_lpf_prom_history(force=True)
            st.session_state["prom_tabla_fetch"] = PROMEDIOS_LPF_2026
            st.rerun()
        _ptab = st.text_area("Pegá la tabla de promedios (formato Promiedos)", height=120, key="prom_tabla_txt",
                             placeholder="1\nBoca Jrs.\nBoca Jrs.\n1.767\t159\t90\t67\t62\t30\n…")
        if (_ptab or "").strip():
            if (_ptab or "").strip() == PROMEDIOS_LPF_2026.strip():
                _pv, _pja, _avs = _embedded_lpf_prom_history()
            else:
                _pv, _pja, _avs = parse_promedios_tabla(_ptab, st.session_state.get("LPF_ANUAL") or {})
            _record_prom_source_issues(_avs)
            if _pv:
                st.session_state.PROM_TXT = promedios_previas_texto(_pv)
                _modo_desc = ("PJ actuales por equipo desde la Tabla Anual" if isinstance(_pja, dict)
                              else f"{_pja} PJ actuales como referencia")
                ui_caption(f"Leí {len(_pv)} equipos · separé el histórico usando {_modo_desc}.")
                if any(str(x).startswith("BLOQUEO:") for x in (_avs or [])):
                    ui_error("La fuente de Promedios no está sincronizada con la Tabla Anual. No se habilita descenso hasta corregirla.")
            for _a in (_avs or [])[:3]:
                ui_caption("⚠️ " + _a)
        else:
            st.session_state.PROM_SOURCE_ISSUES = []
        ui_caption("O pegá las temporadas **previas** a mano: «Equipo, pts, pj».")
        _ptxt = st.text_area("Temporadas previas", value=st.session_state.get("PROM_TXT", ""), height=100,
                             placeholder="River, 123, 73\nBoca, 129, 73", label_visibility="collapsed")
        st.session_state.PROM_TXT = _ptxt
        st.session_state.PROMEDIOS = parse_promedios(_ptxt)
        st.session_state.PROM_K = st.number_input("Descienden por promedio", 1, 5, int(st.session_state.get("PROM_K", 1)))
        if st.session_state.PROMEDIOS:
            ui_caption(f"Cargadas previas de {len(st.session_state.PROMEDIOS)} equipos. Pedí «promedios» o «promedio de X» en el chat.")

    st.divider()

    # Cargar datos
    st.subheader("📥 Cargar datos")
    ui_caption("Un solo bot\u00f3n carga todo. El resto es para editar a mano o traer de otra fuente.")
    if st.button("\U0001F4E5 Cargar TODO (Clausura + Anual + Promedios)", use_container_width=True, type="primary", key="btn_cargar_todo_side"):
        _a, _b, _an, _pn = cargar_lpf_todo()
        ui_success(f"Listo \u2713 Zona A ({_a}) \u00b7 Zona B ({_b}) \u00b7 Anual ({_an}) \u00b7 {_pn} partidos pendientes")
        st.rerun()
    ui_caption("Incluye Zonas A y B, Tabla Anual, el histórico fijo usado por los Promedios "
               "y el **fixture completo de las 16 fechas** para los cruces mano a mano.")
    if st.button("\U0001F504 Actualizar a hoy (automático)", use_container_width=True, key="btn_espn_refresh_side"):
        with st.spinner("Consultando LPF oficial, ESPN y FutbolArgentino.com\u2026"):
            _r, _e = cargar_lpf_espn("arg.1")
        if _e:
            ui_warning(_e + "  \u2014 mientras tanto podés pegar las tablas en «Otras formas de cargar».")
        else:
            _fuente = _r.get("fuente") or "fuente automática"
            _fuente_res = _r.get("fuente_resultados") or "respaldo validado"

            ui_success(f"Actualizado desde {_fuente} \u2713 Zona A ({_r['A']}) \u00b7 Zona B ({_r['B']}) \u00b7 "

                       f"{_r['jug']} resultados \u00b7 {_r['pend']} pendientes")

            ui_caption(f"Resultados cotejados con {_fuente_res}.")

            if _r.get("avisos_fuente"):

                ui_caption("Avisos de fuentes: " + " | ".join(_r["avisos_fuente"]))

            if _r.get("fixture_err"):

                ui_warning("Las tablas se actualizaron, pero no pude actualizar resultados: " + _r["fixture_err"])

            if _r.get("sin_confirmar"):
                ui_warning(
                    f"Hay {_r['sin_confirmar']} partido(s) con estado sin confirmar. "
                    "La aplicación no los toma como jugados ni como pendientes hasta completar los marcadores."
                )

            st.rerun()
    ui_caption("Para las tablas intenta ESPN y FutbolArgentino.com. Para los resultados usa primero las notas oficiales de Primera de la LPF y deja ESPN/FutbolArgentino.com como respaldo; sólo acepta una combinación que reconstruya exactamente PJ, puntos y goles. Si un resultado final confirmado llega antes que la tabla, puede avanzar esa tabla únicamente cuando todos los acumulados cierran sin contradicciones; cada partido se identifica contra el fixture oficial para impedir dobles contabilizaciones. "
               "_La Tabla Anual se recalcula automáticamente desde el Apertura fijo; revisá el semáforo después de actualizar._")
    with st.expander("\U0001F6E0\ufe0f Otras formas de cargar o editar a mano (avanzado)", expanded=False):
        modo_carga = st.radio("Fuente", ["🇦🇷 LPF 2026 (Clausura: zonas A y B)", "Otra liga / copa (avanzado)"], label_visibility="collapsed")

        if modo_carga == "🇦🇷 LPF 2026 (Clausura: zonas A y B)":
            ui_caption("Reglamento LPF 2026: dos zonas de 15, una rueda, 16 fechas. Clasifican los **8 primeros de cada zona** "
                       "a Octavos. La **Tabla General** (para copas y descenso) suma Apertura + Clausura.")
            if st.button("⚡ Traer el Clausura automáticamente", use_container_width=True):
                with st.spinner("Consultando LPF oficial, ESPN y FutbolArgentino.com…"):
                    _r, _e = cargar_lpf_espn("arg.1")
                if _e:
                    ui_warning(_e)
                else:
                    _fuente = _r.get("fuente") or "fuente automática"
                    _fuente_res = _r.get("fuente_resultados") or "respaldo validado"

                    ui_success(f"Cargado desde {_fuente}: Zona A ({_r['A']}) y Zona B ({_r['B']}) · {_r['jug']} resultados ✓")

                    ui_caption(f"Resultados cotejados con {_fuente_res}.")

                    if _r.get("avisos_fuente"):

                        ui_caption("Avisos de fuentes: " + " | ".join(_r["avisos_fuente"]))

                    if _r.get("fixture_err"):

                        ui_warning("Las tablas se cargaron, pero no pude actualizar resultados: " + _r["fixture_err"])

                    st.rerun()
            _za = st.text_area("Tabla Zona A", height=130, key="lpf_a",
                               placeholder="River, 28, 12, +11\nBoca, 25, 12, +7\n…")
            _zb = st.text_area("Tabla Zona B", height=130, key="lpf_b",
                               placeholder="Racing, 27, 12, +9\nIndependiente, 22, 12, +3\n…")
            _fx = st.text_area("Fixture que falta (opcional)", height=70, key="lpf_fx",
                               placeholder="faltan 4 fechas\n— o los partidos: River vs Boca …")
            ui_markdown("**Paso 1 — histórico (una sola vez)**")
            if st.button("📦 Cargar Tabla Anual + Promedios LPF 2026", use_container_width=True, type="secondary"):
                _anual_b, _av1 = parse_tabla_anual(TABLA_ANUAL_LPF_2026)
                _prev_b, _pja_b, _av2 = _embedded_lpf_prom_history()
                _record_prom_source_issues(_av2)
                st.session_state.LPF_ANUAL = _anual_b
                if _lpf_opening_is_valid(globals().get("LPF_APERTURA_BASE_2026") or {}):
                    st.session_state.LPF_APERTURA = canon_base(LPF_APERTURA_BASE_2026)
                st.session_state.PROM_TXT = promedios_previas_texto(_prev_b)
                st.session_state.PROMEDIOS = parse_promedios(st.session_state.PROM_TXT)
                st.session_state.LPF_HIST_OK = f"{len(_anual_b)} equipos en la anual · {len(_prev_b)} en promedios"
                st.rerun()
            if st.session_state.get("LPF_HIST_OK"):
                ui_success("Histórico cargado: " + st.session_state.LPF_HIST_OK + " ✓")
            ui_markdown("**Paso 2 — el Clausura de esta fecha**")
            if st.button("🇦🇷 Cargar Zonas A y B del Clausura 2026", use_container_width=True, type="primary"):
                if not st.session_state.get("LPF_ANUAL"):
                    st.session_state.LPF_ANUAL = parse_tabla_anual(TABLA_ANUAL_LPF_2026)[0]
                    if _lpf_opening_is_valid(globals().get("LPF_APERTURA_BASE_2026") or {}):
                        st.session_state.LPF_APERTURA = canon_base(LPF_APERTURA_BASE_2026)
                    _pv0, _pja0, _pav0 = _embedded_lpf_prom_history()
                    _record_prom_source_issues(_pav0)
                    st.session_state.PROM_TXT = promedios_previas_texto(_pv0)
                    st.session_state.PROMEDIOS = parse_promedios(st.session_state.PROM_TXT)
                    st.session_state.LPF_HIST_OK = f"{len(st.session_state.LPF_ANUAL)} equipos en la anual · {len(_pv0)} en promedios"
                _bA, _avA = parse_tabla_anual(ZONA_A_LPF_2026)
                _bB, _avB = parse_tabla_anual(ZONA_B_LPF_2026)
                _Zc = {"A": canon_base(_bA), "B": canon_base(_bB)}
                _played = parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or None)
                _state, _report = _lpf_rebuild_state(
                    _Zc, played=_played,
                    annual_direct=st.session_state.get("LPF_ANUAL") or {},
                )
                st.session_state.ESTADO = _state
                ui_success(f"Zonas cargadas: A ({len(_Zc['A'])}) y B ({len(_Zc['B'])}) ✓")
                st.rerun()
            with st.expander("🥅 Resultados partido a partido (forma, rachas, local/visitante)"):
                if "lpf_res_fetch" in st.session_state:
                    st.session_state["lpf_res_box"] = st.session_state.pop("lpf_res_fetch")
                if st.button("🇦🇷 Traer resultados LPF 2026 (Fecha 1)", use_container_width=True):
                    st.session_state["lpf_res_fetch"] = RESULTADOS_LPF_2026
                    st.rerun()
                _resbox = st.text_area("Resultados «Local 2-1 Visita», uno por línea",
                                       value=st.session_state.get("lpf_res_box", ""), height=140, key="lpf_res_box",
                                       placeholder="River 2-1 Boca\nRacing 0-0 Independiente\n…")
                st.session_state["LPF_RES_TXT"] = _resbox
                _resn = len(parse_resultados_lpf(_resbox)) if (_resbox or "").strip() else 0
                ui_caption((f"Leo {_resn} partidos. Volvé a tocar «Cargar TODO» o «Cargar Zonas» para aplicarlos." if _resn
                            else "Con esto se activan forma, rachas y rendimiento local/visitante, y el simulador pondera la forma reciente.")
                           + " La tabla de posiciones manda igual; los resultados solo alimentan forma y localía.")
            with st.expander("📊 Actualizar histórico a mano (opcional)"):
                if "lpf_anual_fetch" in st.session_state:
                    st.session_state["lpf_anual"] = st.session_state.pop("lpf_anual_fetch")
                if st.button("🇦🇷 Cargar Tabla Anual LPF 2026 (previa a la fecha 2)", use_container_width=True):
                    st.session_state["lpf_anual_fetch"] = TABLA_ANUAL_LPF_2026
                    st.rerun()
                _an = st.text_area("Tabla Anual pegada (formato Promiedos) — recomendado", height=110, key="lpf_anual",
                                   placeholder="1\nIndependiente Riv.\n35\t17\t29:15\t14\t10\t5\t2\n…")
                ui_caption("De la anual saco solo el Apertura (le resto lo que ya se jugó del Clausura), "
                           "así la tabla sigue viva fecha a fecha en vez de quedar congelada.")
                _ap = st.text_area("…o pegá la fase de zonas del APERTURA", height=90, key="lpf_ap",
                                   placeholder="River, 30, 16, +14\nBoca, 29, 16, +12\n…")
                _c1 = st.text_input("Campeón del Apertura 2026", value=st.session_state.get("lpf_c1", "Belgrano"), key="lpf_c1")
                _c2 = st.text_input("Campeón del Clausura 2026 (si ya se definió)", key="lpf_c2")
                _c3 = st.text_input("Campeón de la Copa Argentina 2026", key="lpf_c3")
                _cr = st.text_input(
                    "Reemplazo de Copa Argentina si el campeón ya tenía plaza",
                    value=st.session_state.get("LPF_COPA_ARG_REEMPLAZO", ""), key="lpf_copa_arg_reemplazo",
                    help="Arts. 27.8 y 27.8.1: es el mejor equipo de Primera ubicado en la Copa Argentina, no el siguiente de la Anual.",
                )
                st.session_state.LPF_COPA_ARG_REEMPLAZO = _cr
                _x1 = st.text_input("Campeón Libertadores 2026 (si es argentino)", key="lpf_x1",
                                    help="Da una plaza ADICIONAL a Libertadores 2027 (art. 27.9).")
                _x2 = st.text_input("Campeón Sudamericana 2026 (si es argentino)", key="lpf_x2",
                                    help="Da una plaza ADICIONAL a Libertadores 2027 (art. 27.10).")
                ui_markdown("**Copa Argentina 2026 · equipos que siguen en carrera**")
                _ca1, _ca2 = st.columns([1, 1])
                if _ca1.button("Cotejar pendientes con ESPN", use_container_width=True, key="lpf_ca_espn"):
                    with st.spinner("Consultando la Copa Argentina en ESPN…"):
                        _vivos_espn, _nota_espn, _err_espn = espn_copa_argentina_vivos()
                    if _err_espn:
                        ui_warning(_err_espn)
                    else:
                        import datetime as _dt
                        st.session_state.LPF_COPA_ARG_VIVOS = list(_vivos_espn)
                        st.session_state.lpf_copa_arg_alive_txt = "\n".join(_vivos_espn)
                        st.session_state.LPF_COPA_ARG_UPDATED = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
                        st.session_state.LPF_COPA_ARG_SOURCE = "ESPN API · arg.copa" + (f" · {_nota_espn}" if _nota_espn else "")
                        ui_success(f"Cotejo aplicado: {len(_vivos_espn)} equipos en partidos pendientes.")
                        st.rerun()
                if _ca2.button("Restaurar cuadro actual de cuartos", use_container_width=True, key="lpf_ca_reset"):
                    st.session_state.LPF_COPA_ARG_VIVOS = list(COPA_ARGENTINA_CUARTOS_2026)
                    st.session_state.lpf_copa_arg_alive_txt = "\n".join(COPA_ARGENTINA_CUARTOS_2026)
                    st.session_state.LPF_COPA_ARG_UPDATED = COPA_ARGENTINA_CUARTOS_UPDATED
                    st.session_state.LPF_COPA_ARG_SOURCE = COPA_ARGENTINA_CUARTOS_SOURCE
                    st.rerun()
                _ca_txt = st.text_area(
                    "Un equipo por línea", key="lpf_copa_arg_alive_txt", height=150,
                    help="Se usa para explicar quién todavía puede obtener la plaza de Copa Argentina y hacer correr las líneas de copas.",
                )
                st.session_state.LPF_COPA_ARG_VIVOS = _parse_team_list(_ca_txt)
                ui_caption(
                    f"Foto: {st.session_state.get('LPF_COPA_ARG_UPDATED','sin fecha')} · "
                    f"{st.session_state.get('LPF_COPA_ARG_SOURCE','sin fuente')}. "
                    "Filtro de seguridad 2026: los eliminados antes de cuartos no pueden volver a liberar cupos aunque persistan en una sesión vieja. "
                    "Después de cada cruce de cuartos, actualizá esta lista con los sobrevivientes."
                )
                ui_markdown(
                    f"[Abrir previa oficial de cuartos]({COPA_ARGENTINA_CUARTOS_OFICIAL}) · "
                    f"[Abrir fixture oficial]({COPA_ARGENTINA_FIXTURE_OFICIAL}) · "
                    f"[Abrir cuadro de ESPN]({COPA_ARGENTINA_CUADRO_ESPN})"
                )
                _na = st.number_input("Descensos por Tabla General", 0, 4, 1, key="lpf_na")
                _np = st.number_input("Descensos por promedio", 0, 4, 1, key="lpf_np")
            if st.button("✅ Cargar LPF 2026", use_container_width=True, type="primary"):
                _ba, _p1, _g1 = parse_tabla_fixture((_za or "") + "\n" + (_fx or ""))
                _bb, _p2, _g2 = parse_tabla_fixture((_zb or "") + "\n" + (_fx or ""))
                if len(_ba) < 3 or len(_bb) < 3:
                    ui_error("Necesito las dos tablas (Zona A y Zona B), una línea por equipo: «Equipo, Pts, PJ, DG».")
                else:
                    _Z = {"A": canon_base(_ba), "B": canon_base(_bb)}
                    _ba, _bb = _Z["A"], _Z["B"]
                    if (_an or "").strip():
                        _anual, _avA = parse_tabla_anual(_an)
                        _bap, _avD = derivar_apertura(_anual, _Z)
                        for _a in (_avA + _avD)[:3]:
                            ui_warning(_a)
                    elif (_ap or "").strip():
                        _bap = parse_tabla_fixture(_ap)[0]
                    else:
                        _bap = {}
                    _anual_dir = st.session_state.get("LPF_ANUAL") or {}
                    if (_an or "").strip():
                        _anual_dir = parse_tabla_anual(_an)[0]
                    _played = parse_resultados_lpf(st.session_state.get("LPF_RES_TXT") or None)
                    _state, _report = _lpf_rebuild_state(
                        _Z, played=_played, annual_direct=_anual_dir, opening=_bap,
                        camps=(_c1, _c2, _c3), intl=(_x1, _x2),
                        n_anual=int(_na), n_prom=int(_np),
                    )
                    st.session_state.ESTADO = _state
                    ui_success(f"LPF 2026 cargada: Zona A ({len(_ba)}) y Zona B ({len(_bb)}) ✓")
                    st.rerun()
            texto_torneo = ""

        elif modo_carga == "Otra liga / copa (avanzado)" and False and "API ESPN (gratis, incluye Liga Argentina)":
            ui_caption("Gratis y sin token. Trae la **tabla** y los **partidos que faltan** (y las zonas sugeridas). "
                       "Para ligas que no estén en la lista, escribí el código (ej.: `bra.1`, `por.1`).")
            _lnom = ui_selectbox("Liga", list(ESPN_LIGAS.keys()), key="espn_liga_sel")
            _lcod = st.text_input("Código de liga", value=ESPN_LIGAS.get(_lnom, "arg.1"), key="espn_liga_cod")
            _ldias = st.number_input("Traer partidos de los próximos (días)", 7, 365, 120, key="espn_dias")
            if st.button("⚽ Traer de ESPN y cargar", use_container_width=True, type="primary"):
                with st.spinner("Consultando ESPN…"):
                    _base, _zon, _err = espn_tabla(_lcod)
                if _err:
                    ui_error(_err)
                else:
                    with st.spinner("Buscando los partidos que faltan…"):
                        _jg, _pd, _nota, _errf = espn_fixture(_lcod, _ldias)
                    _eqs = list(_base.keys())
                    _pares, _caidos = mapear_fixture(_pd or [], _eqs)
                    _rest = liga_restantes(_eqs, _pares, None) if _pares else {e: 0 for e in _eqs}
                    st.session_state.ESTADO = dict(modo="liga_tabla", equipos=_eqs, base=_base,
                                                   pendientes=_pares, rest=_rest, gleft=None,
                                                   jugados=[], esc=None, mg=0, solo_puntos=True)
                    if _zon and not st.session_state.get("ZONAS"):
                        st.session_state.ZONAS_TXT = _zon
                        st.session_state.ZONAS = parse_zonas(_zon)
                    _msg = f"Cargado de ESPN: {len(_eqs)} equipos · {len(_pares)} partidos por jugar"
                    if _errf and not _pares:
                        _msg += " (sin fixture: revisá los días o pegalo a mano)"
                    ui_success(_msg + f" {_nota} ✓")
                    if _caidos:
                        ui_caption("Sin emparejar: " + ", ".join(_caidos[:3]) + ("…" if len(_caidos) > 3 else ""))
                    st.rerun()
            texto_torneo = ""

        elif modo_carga == "Otra liga / copa (avanzado)" and False and "API football-data.org":
            token = st.text_input("API Key", value=_secret("FOOTBALL_DATA_TOKEN", ""), type="password",
                                   placeholder="Tu token de football-data.org",
                                   help="Cargala una vez en Secrets (FOOTBALL_DATA_TOKEN) y queda precargada.")
            comp  = st.text_input("Código torneo", value="WC",
                                  help="Ej.: WC=Mundial, CL=Champions, PL=Premier, PD=LaLiga, SA=Serie A, "
                                       "BL1=Bundesliga, FL1=Ligue 1, BSA=Brasileirão, PPL=Portugal, "
                                       "DED=Eredivisie, ELC=Championship. Tocá «Ver torneos» para ver los tuyos.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🌐 Traer datos", use_container_width=True):
                    if not token:
                        ui_error("Pegá tu API key.")
                    else:
                        try:
                            with st.spinner("Trayendo…"):
                                matches = traer_de_api(token, comp)
                            st.session_state.texto_torneo_cache = matches_a_texto(matches)
                            ui_success("Datos cargados ✓")
                        except Exception as e:
                            ui_error(f"Error: {e}")
            with col2:
                if st.button("Ver torneos", use_container_width=True):
                    if token:
                        try:
                            st.session_state["lista_comps"] = listar_competiciones(token)
                        except Exception as e:
                            ui_error(str(e))
            if "lista_comps" in st.session_state:
                for code, name in st.session_state["lista_comps"]:
                    ui_caption(f"`{code}` — {name}")
            texto_torneo = st.session_state.texto_torneo_cache

        elif modo_carga == "Otra liga / copa (avanzado)" and False and "Pegar tabla + fixture (ligas)":
            if "liga_tabla_fetch" in st.session_state:
                st.session_state["liga_tabla_txt"] = st.session_state.pop("liga_tabla_fetch")
            ui_caption("Pegá la **tabla** (una línea por equipo: «Equipo, Pts, PJ, DG»). Abajo, lo ideal es pegar el **fixture** que viene (líneas «River vs Boca») para captar los cruces entre rivales; si no, poné «faltan N fechas» (atajo, no ve los cruces).")
            with st.expander("🌐 Traer la tabla desde una URL (Wikipedia, gratis)"):
                _LIGAS = {
                    "— elegir —": "",
                    "Argentina · Tabla acumulada (copas + un descenso)": "https://es.wikipedia.org/wiki/Campeonato_de_Primera_División_2025_(Argentina)",
                    "Argentina · Tabla de promedios (descenso)": "https://es.wikipedia.org/wiki/Campeonato_de_Primera_División_2025_(Argentina)",
                    "Premier League (Inglaterra)": "https://es.wikipedia.org/wiki/Premier_League_2025-26",
                    "La Liga (España)": "https://es.wikipedia.org/wiki/Primera_División_de_España_2025-26",
                    "Serie A (Italia)": "https://es.wikipedia.org/wiki/Serie_A_2025-26",
                    "Brasileirão (Brasil)": "https://es.wikipedia.org/wiki/Campeonato_Brasileño_de_Serie_A_2025",
                }
                _lsel = ui_selectbox("Liga (rellena el link solo)", list(_LIGAS.keys()), key="liga_preset")
                if _LIGAS.get(_lsel) and st.session_state.get("_lsel_last") != _lsel:
                    st.session_state["url_tabla"] = _LIGAS[_lsel]
                    st.session_state["_lsel_last"] = _lsel
                    st.rerun()
                ui_caption("Ojo Argentina: la acumulada y la de promedios se leen bien; el fixture de la fecha se pega aparte "
                           "(o vía Apify). El torneo en curso por zonas no trae partidos legibles desde Wikipedia.")
                url_tabla = st.text_input("URL de la página con la tabla", key="url_tabla",
                                          placeholder="https://es.wikipedia.org/wiki/Torneo_… (página del torneo)")
                if st.button("Leer tabla de la URL", use_container_width=True):
                    txt_t, err_t = tabla_desde_url(url_tabla)
                    if err_t:
                        ui_error(err_t)
                    else:
                        st.session_state["liga_tabla_fetch"] = txt_t
                        st.rerun()
                if st.button("Leer TODO: resultados + fixture (tabla cruzada) y cargar", use_container_width=True, type="primary"):
                    jg2, pd2, err2, nota2 = partidos_desde_url(url_tabla)
                    if err2:
                        ui_error(err2)
                    elif not jg2 and not pd2:
                        ui_error("La matriz está vacía. Pegá tabla y fixture a mano.")
                    else:
                        eqs2 = sorted({t for par in (jg2 + pd2) for t in (par[0], par[1])})
                        base2 = _stats(eqs2, jg2)
                        rest2 = liga_restantes(eqs2, pd2, None)
                        st.session_state.ESTADO = dict(modo="liga_tabla", equipos=eqs2, base=base2,
                                                       pendientes=pd2, rest=rest2, gleft=None,
                                                       jugados=jg2, esc=None, mg=0, solo_puntos=True)
                        ui_success(f"Cargado desde la matriz: {len(jg2)} resultados y {len(pd2)} por jugar ({nota2}) ✓")
                        st.rerun()
            tabla_txt = st.text_area("Tabla de posiciones", height=170,
                                     placeholder="River, 31, 14, +12\nBoca, 28, 14, +7\nRacing, 27, 14, +5\n...",
                                     key="liga_tabla_txt")
            fix_txt = st.text_area("Fechas que faltan (o fixture)", height=80,
                                   placeholder="faltan 5 fechas\n— o pegá los partidos: River vs Boca …",
                                   key="liga_fix_txt")
            if st.button("✅ Cargar liga (tabla)", use_container_width=True, type="primary"):
                base, pend, gleft = parse_tabla_fixture((tabla_txt or "") + "\n" + (fix_txt or ""))
                if len(base) >= 3:
                    eqs = list(base.keys()); rest = liga_restantes(eqs, pend, gleft)
                    st.session_state.ESTADO = dict(modo="liga_tabla", equipos=eqs, base=base,
                                                   pendientes=pend, rest=rest, gleft=gleft,
                                                   jugados=[], esc=None, mg=0, solo_puntos=True)
                    st.rerun()
                else:
                    ui_error("No pude leer la tabla. Probá el formato «Equipo, Pts, PJ, DG» (una línea por equipo).")
            texto_torneo = ""

        elif modo_carga == "Otra liga / copa (avanzado)" and False and "Importar JSON/CSV (Apify u otra fuente)":
            ui_caption("Para ligas que no están en la API. Reconoce `homeTeam/awayTeam/homeScore/awayScore/status/league`: "
                       "los terminados van como resultados y los programados como fixture.")
            imp_fil = st.text_input("Filtrar por liga (texto que contenga)", key="imp_fil",
                                    placeholder="ej.: liga profesional / argentina")
            solo_fix = False
            if st.session_state.ESTADO and st.session_state.ESTADO.get("modo") == "liga_tabla":
                solo_fix = st.toggle("Usar solo como fixture de la tabla ya cargada", value=False,
                                     help="Ideal: tabla pegada a mano + fixture automático. Empareja nombres aunque no coincidan exactos.")
            with st.expander("⚡ Traer directo de Apify", expanded=True):
                apify_tok = st.text_input("Apify token", value=_secret("APIFY_TOKEN", ""), type="password",
                                          help="Gratis en apify.com → Settings → API tokens. Cargalo una vez en Secrets (APIFY_TOKEN).")
                apify_act = st.text_input("Actor", value="crawlerbros/flashscore-scraper",
                                          help="También sirve extractify-labs/flashscore-extractor (filtra por fecha −7..+7) o cualquier actor que devuelva partidos.")
                apify_inp = st.text_area("Input del actor (JSON)", value='{"sport": "football", "liveOnly": false, "maxItems": 500}', height=70)
                if st.button("🌐 Traer de Apify e importar", use_container_width=True, type="primary"):
                    if not apify_tok:
                        ui_error("Pegá tu token de Apify (o cargalo en Secrets como APIFY_TOKEN).")
                    else:
                        try:
                            import json as _json
                            with st.spinner("Corriendo el actor…"):
                                items = traer_de_apify(apify_tok, apify_act, apify_inp)
                            jg, pd_, ligas, err = importar_partidos_json(_json.dumps(items), imp_fil)
                            if err:
                                ui_error(err)
                            elif _procesar_import(jg, pd_, ligas, imp_fil, solo_fix):
                                st.rerun()
                        except Exception as e:
                            ui_error(f"Error: {e}")
            imp_txt = st.text_area("…o pegá el JSON/CSV exportado", height=140, key="imp_txt",
                                   placeholder='[{"homeTeam":"Lanus","awayTeam":"Banfield","homeScore":1,"awayScore":0,'
                                               '"status":"finished","league":"ARGENTINA: Liga Profesional"}, …]')
            if st.button("✅ Importar y cargar", use_container_width=True):
                jg, pd_, ligas, err = importar_partidos_json(imp_txt, imp_fil)
                if err:
                    ui_error(err)
                elif _procesar_import(jg, pd_, ligas, imp_fil, solo_fix):
                    st.rerun()
            texto_torneo = ""

        else:
            texto_torneo = st.text_area(
                "Pegá los resultados",
                height=200,
                placeholder="Grupo A\nRiver 1-0 Boca\nRacing 1-1 Independiente\n...",
            )
            if texto_torneo.strip():
                st.session_state.texto_torneo_cache = texto_torneo

        grupos_disponibles = list(dividir_grupos(texto_torneo).keys()) if texto_torneo.strip() else []

        if grupos_disponibles:
            grupo_sel = ui_selectbox("📂 Grupo a analizar", grupos_disponibles)
            if st.button("✅ Cargar grupo", use_container_width=True, type="primary"):
                texto_grupo = dividir_grupos(texto_torneo).get(grupo_sel, "")
                eq, jug, pen = parsear_resultados(texto_grupo)
                if len(eq) >= 3:
                    cargar_estado(eq, jug, pen)
                    st.rerun()
                else:
                    ui_error("No se detectaron suficientes equipos.")

    if st.session_state.ESTADO:
        E = st.session_state.ESTADO
        st.divider()
        if E.get("modo") == "lpf2026":
            _txt, _ok = lpf_estado_datos(E.get("zonas_lpf"))
            (st.success if _ok else st.warning)(_txt)
        elif E.get("modo") == "liga_tabla":
            ui_success(f"Liga cargada (tabla) · {len(E['equipos'])} equipos")
            falt = E.get("gleft")
            ui_caption((f"Faltan {falt} fechas" if falt else f"{len(E['pendientes'])} partidos pendientes") + " · cuentas por puntos.")
        elif E.get("esc") is None:
            ui_success(f"Liga cargada · {len(E['equipos'])} equipos · modo por puntos")
            ui_caption(f"Pendientes: {len(E['pendientes'])} — son demasiados para enumerar marcador por marcador, así que voy por puntos.")
        else:
            ui_success(f"Grupo cargado · {len(E['equipos'])} equipos · {_fmt_entero_es(len(E['esc']))} escenarios")
            ui_caption(f"Máx goles/equipo: {E['mg']} · Pendientes: {len(E['pendientes'])}")

# ─── MAIN TABS ───────────────────────────────────────────────────────────────────
if not st.session_state.ESTADO:
    ui_info("\U0001F449 Todav\u00eda no cargaste datos. Toc\u00e1 el bot\u00f3n para cargar el Clausura 2026 completo (o traelo de las fuentes automáticas).")
    if st.button("\U0001F4E5 Cargar TODO (Clausura + Anual + Promedios)", type="primary", use_container_width=True, key="btn_cargar_todo_main"):
        cargar_lpf_todo()
        st.rerun()
    with st.expander("\u2026o traerlo de fuentes autom\u00e1ticas"):
        if st.button("\u26a1 Traer el Clausura autom\u00e1ticamente", use_container_width=True, key="btn_espn_main"):
            with st.spinner("Consultando LPF oficial, ESPN y FutbolArgentino.com\u2026"):
                _r, _e = cargar_lpf_espn("arg.1")
            if _e:
                ui_error(_e)
            else:
                st.rerun()
    st.stop()

E = st.session_state.ESTADO
equipos    = E["equipos"]
jugados    = E["jugados"]
pendientes = E["pendientes"]
esc        = E["esc"]

# ─── INTERFAZ DE CHAT ────────────────────────────────────────────────────────────

if "LLM_KEY"   not in st.session_state: st.session_state.LLM_KEY   = _secret("ANTHROPIC_API_KEY", "")
if "LLM_MODEL" not in st.session_state: st.session_state.LLM_MODEL = _secret("ANTHROPIC_MODEL", "claude-haiku-4-5")
if "LLM_ON"    not in st.session_state: st.session_state.LLM_ON    = bool(str(st.session_state.LLM_KEY).strip())


_LPF_OBJECTIVE_UI_OPTIONS = ("Playoffs", "Libertadores", "Al menos Sudamericana", "Descenso")
_LPF_OBJECTIVE_BY_LABEL = {
    "Playoffs": "playoffs",
    "Libertadores": "libertadores",
    "Al menos Sudamericana": "al_menos_sudamericana",
    "Descenso": "descenso",
}
_LPF_OBJECTIVE_LABEL_BY_CODE = {
    "playoffs": "Playoffs",
    "libertadores": "Libertadores",
    "al_menos_sudamericana": "Al menos Sudamericana",
    # El chat puede pedir Sudamericana estricta. La UI conserva la familia de copa
    # sin inventar una quinta opción que mezcle dos definiciones editoriales.
    "sudamericana": "Al menos Sudamericana",
    "descenso": "Descenso",
}


def _lpf_service_objective(value):
    """Código de objetivo entendido por la frontera pública v1."""
    code = _LPF_OBJECTIVE_BY_LABEL.get(value, value)
    code = str(code or "playoffs").strip().lower()
    if code == "al_menos_sudamericana":
        return "sudamericana"
    return code


def _lpf_service_snapshot_payload(E):
    """Traduce la fuente actual al contrato común ``DataProvider``.

    Streamlit deja de ser una excepción: entrega exactamente el mismo ``ProviderData``
    que puede producir un CSV o, más adelante, un adaptador Opta.
    """
    E = E or {}
    camps = tuple(E.get("camps") or (
        st.session_state.get("lpf_c1", "Belgrano"),
        st.session_state.get("lpf_c2", ""),
        st.session_state.get("lpf_c3", ""),
    ))
    camps = (camps + ("", "", ""))[:3]
    intl = tuple(E.get("intl") or (
        st.session_state.get("lpf_x1", ""),
        st.session_state.get("lpf_x2", ""),
    ))
    intl = (intl + ("", ""))[:2]
    source_meta = dict(st.session_state.get("LPF_SOURCE_META") or {})
    raw = {
        "zones": E.get("zonas_lpf") or {},
        "played": E.get("jugados") or [],
        "annual": E.get("anual_directo") or st.session_state.get("LPF_ANUAL") or {},
        "opening": E.get("apertura") or st.session_state.get("LPF_APERTURA") or {},
        "previous_averages": E.get("promedios") or st.session_state.get("PROMEDIOS") or {},
        "fixture": list(globals().get("LPF_FIXTURE") or []),
        "qualification": {
            "champions": {
                "apertura": camps[0],
                "clausura": camps[1],
                "copa_argentina": camps[2],
            },
            "international_champions": {
                "libertadores": intl[0],
                "sudamericana": intl[1],
            },
            "copa_argentina_replacement": E.get("copa_arg_reemplazo")
            or st.session_state.get("LPF_COPA_ARG_REEMPLAZO", ""),
        },
        "rules": {
            "annual_relegations": int(E.get("n_anual", 1) or 1),
            "average_relegations": int(E.get("n_prom", 1) or 1),
            "opening_rounds": int(globals().get("LPF_APERTURA_PJ", 16)),
            "playoff_cutoff": 8,
            "sudamericana_slots": 6,
        },
        "provenance": source_meta,
    }
    return _lpf_provider_payload(CurrentProvider(raw))


def _lpf_service_snapshot(E):
    """Snapshot público memoizado por contenido del estado actual.

    La caché vive en ``session_state`` para que varias vistas del mismo rerun no
    vuelvan a reconciliar tablas. Si cambia un resultado, una tabla, un campeón o
    los promedios, cambia la huella y se regenera automáticamente.
    """
    payload = _lpf_service_snapshot_payload(E)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    fingerprint = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    cached = st.session_state.get("LPF_PUBLIC_SERVICE_SNAPSHOT") or {}
    if cached.get("fingerprint") == fingerprint and isinstance(cached.get("snapshot"), dict):
        return cached["snapshot"]
    prepared = _lpf_service_prepare_snapshot(payload)
    snapshot = prepared.get("result") or {}
    st.session_state["LPF_PUBLIC_SERVICE_SNAPSHOT"] = {
        "fingerprint": fingerprint,
        "snapshot": snapshot,
    }
    return snapshot


def _lpf_service_schedule_payload():
    """Agenda real en un objeto JSON-compatible para la operación ``preview``."""
    schedule = {}
    for match, when in (_lpf_schedule_map() or {}).items():
        if not isinstance(match, (tuple, list)) or len(match) != 2 or not when:
            continue
        key = f"{match[0]}|||{match[1]}"
        schedule[key] = when.isoformat() if hasattr(when, "isoformat") else str(when)
    return schedule


def _lpf_service_result(operation, E, **payload):
    """Ejecuta una operación pública y devuelve sólo ``result``.

    Los ``ContractError`` se propagan: la UI decide si debe mostrar un bloqueo o
    usar un fallback legacy. Esto evita convertir errores de contrato en resultados.
    """
    request = {"snapshot": _lpf_service_snapshot(E), **payload}
    response = _lpf_service_calculate_public(operation, request)
    return response.get("result") or {}


def _record_lpf_service_fallback(area, exc):
    """Registra un fallback de compatibilidad para exponerlo luego en auditoría."""
    rows = list(st.session_state.get("LPF_PUBLIC_SERVICE_FALLBACKS") or [])
    marker = {
        "area": str(area),
        "code": str(getattr(exc, "code", "service_error")),
        "message": str(getattr(exc, "message", exc)),
    }
    if marker not in rows:
        rows.append(marker)
    st.session_state["LPF_PUBLIC_SERVICE_FALLBACKS"] = rows[-20:]


def _lpf_service_need_text(E, team, objective, zone=None):
    """Lectura editorial corta desde la frontera pública v1."""
    code = _lpf_service_objective(objective)
    if code == "descenso":
        result = _lpf_service_result("relegation", E, team=team)
        team_result = result.get("team") or {}
        return str(team_result.get("reading") or result.get("warning") or "No hay una lectura de descenso disponible.")
    payload = {"team": team, "objective": code}
    if code == "playoffs" and zone:
        payload["zone"] = zone
    result = _lpf_service_result("objective_points", E, **payload)
    if result.get("resolved"):
        return str(result.get("message") or "El objetivo ya está resuelto por otra vía.")
    return str(result.get("reading") or "No hay una lectura de puntos disponible.")


def _lpf_editorial_need_text(E, team, objective, zone=None):
    """Informe editorial largo para la pregunta «qué necesita».

    Esta es la salida principal de la UI editorial. El contrato público v1
    conserva su resumen JSON-safe para API/auditoría, pero no sustituye esta
    narrativa: Panel por equipo y Últimas fechas comparten este mismo helper.
    """
    Z = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    played = E.get("jugados") or []
    if objective == "Playoffs":
        return lpf_playoffs_texto(team, Z, rest, pending, jugados=played)
    if objective in ("Libertadores", "Al menos Sudamericana"):
        return lpf_copas_necesita_texto(
            team, Z, rest, E.get("apertura") or {},
            E.get("camps") or ("", "", ""), E.get("intl") or ("", ""),
            pending, jugados=played,
        )
    previous = st.session_state.get("PROMEDIOS") or {}
    return lpf_descenso_texto(
        Z, rest, E.get("apertura") or {}, previous, E.get("n_anual", 1),
        E.get("n_prom", 1), team, pending,
    )


def _lpf_objective_label(code=None):
    """Etiqueta de UI para el objetivo recordado entre chat y vistas."""
    code = code or st.session_state.get("LPF_LAST_OBJECTIVE") or "playoffs"
    return _LPF_OBJECTIVE_LABEL_BY_CODE.get(code, "Playoffs")


def _remember_lpf_objective(value):
    """Guarda un objetivo canónico a partir de su código o etiqueta visible."""
    code = _LPF_OBJECTIVE_BY_LABEL.get(value, value)
    if code in _LPF_OBJECTIVE_LABEL_BY_CODE:
        st.session_state["LPF_LAST_OBJECTIVE"] = code
        return code
    return st.session_state.get("LPF_LAST_OBJECTIVE") or "playoffs"


def _sync_lpf_objective_widget(key):
    """Sincroniza un selector antes de crearlo sin pisar cambios del usuario.

    Los callbacks de Streamlit corren antes del rerun: si el usuario cambió el
    selector, ``LPF_LAST_OBJECTIVE`` ya contiene el valor nuevo cuando entra acá.
    Si el objetivo cambió desde el chat, en cambio, este paso lleva ese valor a
    la próxima vista antes de instanciar el widget.
    """
    desired = _lpf_objective_label()
    if st.session_state.get(key) != desired:
        st.session_state[key] = desired


def _lpf_objective_widget_changed(key):
    _remember_lpf_objective(st.session_state.get(key))


def _lpf_objective_prompt(team, action):
    """Consulta del explorador respetando el último objetivo elegido/consultado."""
    code = st.session_state.get("LPF_LAST_OBJECTIVE") or "playoffs"
    targets = {
        "playoffs": "los playoffs",
        "libertadores": "la Libertadores",
        "al_menos_sudamericana": "entrar a las copas",
        "sudamericana": "la Sudamericana",
        "descenso": "salvarse",
    }
    target = targets.get(code, "los playoffs")
    if action == "conviene":
        return f"¿Qué le conviene a {team} para {target}?"
    if action == "necesita":
        if code == "descenso":
            return f"¿Qué necesita {team} para no descender?"
        return f"¿Qué necesita {team} para {target}?"
    raise ValueError(f"Acción de objetivo desconocida: {action}")


def _placa(spec, fname):
    return ("placa", _html_tabla(spec), _png_tabla(spec), fname)

def _placa_png(png, fname):
    return ("placa", None, png, fname)


# ─── NAVEGACIÓN ENTRE GRUPOS (si se cargó el torneo completo) ─────────────────────
def _tour_grupos():
    """Devuelve {label: (equipos, jugados, pendientes)} desde el texto del torneo."""
    txt = st.session_state.get("texto_torneo_cache", "")
    if not txt or not txt.strip():
        return {}
    out = {}
    for lab, sub in dividir_grupos(txt).items():
        try:
            eqs, jug, pen = parsear_resultados(sub)
        except Exception:
            continue
        if len(eqs) >= 3:
            out[lab] = (eqs, jug, pen)
    return out


def _buscar_grupo_de(team_q):
    for lab, (eqs, jug, pen) in _tour_grupos().items():
        t = detectar_equipo(team_q, eqs)
        if t:
            return lab, t, (eqs, jug, pen)
    return None, None, None


AYUDA_MD = """**Todo esto funciona escribiéndolo (no hace falta el asistente Claude).** Ejemplos:

**Qué necesita cada uno**
- *¿Qué necesita River para los playoffs?* · *¿Puede salir campeón Racing?* · *¿Qué necesita Aldosivi para no descender?*
- *¿Qué le conviene a Boca?* (su resultado + qué hinchar en los otros partidos)
- *¿De quién depende?* (si cada equipo depende de sí mismo o necesita ayuda) · *Si terminara hoy*

**Datos del grupo**
- *Tabla* · *Panorama* · *Probabilidades* · *Número mágico de River* · *Máximos* · *Asegurados*

**Buscar grupos** (con el torneo completo cargado)
- *¿En qué zona está Belgrano?* · *Equipos de la Zona A*

**Placas visuales (se descargan como imagen)**
- *Grilla de River* — qué necesita, en cuadro de colores
- *Comparar River y Boca* — cara a cara
- *River puede salir 1º* — cuándo termina en ese puesto
- *Mapa del grupo* — mapa de calor de en qué puesto termina cada uno
- *¿Cómo viene River?* — explicación didáctica de sus chances, con medidor (placa)
- *Árbol de River* — flowchart si/entonces: gana → clasifica, empata → depende, etc. (placa)
- *Qué se juega cada equipo* — un renglón por equipo de todo el grupo, para placa o copete (placa)
- *Previa de la fecha* — qué define cada partido que falta y qué pasa con cada resultado (texto + placa)
- *Previa de River* (o *cómo puede terminar la fecha para River*) — su partido y entre qué puestos puede terminar la fecha, en playoffs/copas/descenso según le toque
- *Proyección* — cuántos puntos junta cada uno si mantiene su ritmo (tabla)
- *Ficha de River* — pts, ritmo, forma, racha, local/visitante, rivales que quedan y dificultad
- *Forma* / *Racha* — tabla de últimos 5 · *De local y de visitante* — rendimiento por condición
- *Calendario* — qué tan difícil es el fixture que le queda a cada uno
- *Mejores terceros* — el tablero de los 12 terceros con la línea de corte (necesita el torneo completo; placa)
- *Promedios* / *Promedio de X* — el descenso a la argentina, con promedio actual, mínimo si pierde todo, máximo si gana todo y análisis (cargá las previas en el panel)
- *Barras de River* — distribución de en qué puesto puede terminar (gráfico)
- *Partido bisagra* — qué partido de los que faltan define más cosas
- *Tabla por zonas* — para ligas: pinta la tabla por Libertadores/Sudamericana/descenso (configurá las zonas en el panel)

**Simulador**
- *¿Qué pasa si…?* — panel interactivo: elegís los resultados que faltan y ves la tabla, quién clasifica y la previa en prosa.

**Entender el porqué**
- Después de casi cualquier respuesta, escribí *¿por qué?* y te desarmo la cuenta en criollo.
- Sirve sobre: *qué necesita X*, *ya clasificó / quedó afuera*, *número mágico*, *cómo viene X*, *partido bisagra*.

**Para la nota**
- *Contame el escenario de Boca* · *Relato de la zona* — texto listo para publicar

Podés encadenar sin repetir el equipo: *«¿qué necesita Boca?»* y después *«¿y qué le conviene?»*.
Si preguntás por un equipo de otro grupo, **cambio solo** a ese grupo."""

AYUDA_LIGA = """Esto es una **liga** (muchas fechas): trabajo **por puntos**. Comandos:

- **Tabla por zonas** — pinta Libertadores/Sudamericana/descenso (configurá las zonas en el panel)
- **¿Qué necesita River para Libertadores?** · **…para no descender** · **…para Sudamericana**
- **Número mágico de River** · **Máximos** (techo de cada uno) · **Asegurados top 4**
- **Si terminara hoy** · Después de cualquier respuesta, **¿por qué?** te desarma la cuenta
- **Chances de cada zona** (*probabilidades* o *¿cómo viene River?*) — simulación de miles de torneos, ideal a varias fechas del final
- **Proyección** — puntos finales si cada uno mantiene su ritmo
- **Comparar River y Boca** — cara a cara por puntos, techo y zona
- **Ficha de River** · **Calendario** (dificultad del fixture restante, con fixture pegado)
- **Promedios** · **Promedio de X** — descenso por promedios con temporadas previas (panel «📉 Promedios»)

Si cargaste por **tabla + fechas**, con eso me alcanza para todas estas cuentas (no necesito los resultados).
Configurá las zonas con nombre en «🎨 Zonas con nombre» del panel."""

BIENVENIDA = ("👋 Este es el **Chat guiado + libre**. Arriba tenés un explorador con todas las "
              "consultas ordenadas por tema: elegí equipo, categoría y tocá una opción. También podés "
              "buscar una función por palabra. El campo libre queda para preguntas propias y seguimientos "
              "como *«¿y si empata?»*, *«sumá los postergados»* o *«explicame por qué»*.")


def _chat_catalog(E, team, other):
    """Catálogo visible del chat. Cada opción termina en una consulta soportada por el router."""
    team = team or ((E.get("equipos") or ["River Plate"])[0])
    other = other or team
    if E.get("modo") == "lpf2026":
        active_objective = _lpf_objective_label()
        need_prompt = _lpf_objective_prompt(team, "necesita")
        conviene_prompt = _lpf_objective_prompt(team, "conviene")
        return {
            "⭐ Más usadas": [
                ("Previa del equipo", "Partido, rango de puestos e impacto en playoffs, copas o descenso.", f"Previa de {team}"),
                (f"Qué necesita · {active_objective}", "Mínimo que asegura o total seguro, cruces directos y caminos para alcanzar el objetivo.", need_prompt),
                (f"Qué le conviene · {active_objective}", "Resultados de otras canchas que mejoran su escenario.", conviene_prompt),
                ("Tabla de las zonas", "Posiciones actuales y línea de clasificación.", "Tabla de las dos zonas"),
                ("Libertadores", "Panorama general de los cupos por la Tabla Anual.", "¿Cómo está la clasificación a la Libertadores?"),
                ("Sudamericana", "Panorama general de los cupos por la Tabla Anual.", "¿Cómo está la clasificación a la Sudamericana?"),
                ("Descenso", "Impacto combinado de la anual y los promedios.", "¿Cómo está el descenso?"),
                ("Previa de la fecha", "Pantallazo partido por partido de la próxima jornada.", "Previa de la fecha"),
            ],
            "🏆 Playoffs": [
                ("Qué necesita para entrar", "Cuenta exacta para terminar entre los ocho.", f"¿Qué necesita {team} para los playoffs?"),
                ("Chances de playoffs", "Probabilidad estimada de entrar entre los ocho primeros.", f"Chances de {team} para los playoffs"),
                ("Depende de sí mismo", "Distingue garantía propia de resultados ajenos.", f"¿{team} depende de sí mismo para los playoffs?"),
                ("Qué resultados le sirven", "La otra cancha y los cruces que más lo favorecen.", f"¿Qué le conviene a {team} para los playoffs?"),
                ("Cómo puede terminar la fecha", "Mejor y peor posición posible en la próxima ventana.", f"¿Cómo puede terminar la fecha {team}?"),
                ("Árbol gana/empata/pierde", "Cómo cambian sus chances según su próximo resultado.", f"Árbol de {team}"),
                ("Cruces de octavos", "Llaves si el torneo terminara hoy.", "Cruces de octavos"),
                ("Proyección de puntos", "Puntaje final si cada equipo mantiene su ritmo.", "Proyección de puntos"),
                ("Puntos máximos", "Techo matemático de los equipos de cada zona.", "Puntos máximos"),
                ("Relato de la zona", "Texto breve y publicable sobre la pelea por los playoffs.", f"Relato de la zona de {team}"),
            ],
            "🌎 Copas": [
                ("Panorama de Libertadores", "Clasificados actuales, corte y cupos que pueden liberarse.", "¿Cómo está la clasificación a la Libertadores?"),
                ("Panorama de Sudamericana", "Clasificados actuales y distancia al corte.", "¿Cómo está la clasificación a la Sudamericana?"),
                ("Tabla Anual", "Acumulada del año que reparte copas y define un descenso.", "Tabla Anual"),
                ("Llega a Libertadores", "Caminos y puntaje que necesita el equipo.", f"¿{team} llega a la Libertadores?"),
                ("Llega a Sudamericana", "Caminos y puntaje que necesita el equipo.", f"¿{team} llega a la Sudamericana?"),
                ("Chances de Libertadores", "Probabilidad estimada sobre la anual sin campeones.", f"Chances de {team} para la Libertadores"),
                ("Chances de Sudamericana", "Probabilidad estimada sobre la anual sin campeones.", f"Chances de {team} para la Sudamericana"),
                ("Qué le conviene para Libertadores", "Resultados ajenos que mejoran su acceso a la copa.", f"¿Qué le conviene a {team} para la Libertadores?"),
                ("Qué le conviene para entrar a las copas", "Resultados ajenos que mejoran su acceso a Sudamericana o Libertadores.", f"¿Qué le conviene a {team} para entrar a las copas?"),
                ("Panorama completo de copas", "Libertadores y Sudamericana en una misma respuesta.", "Copas 2027"),
            ],
            "📉 Descenso": [
                ("Panorama del descenso", "Quién baja hoy por anual y quién por promedio.", "¿Cómo está el descenso?"),
                ("Tabla de promedios", "Coeficientes, mínimo y máximo posible de cada equipo.", "Promedios"),
                ("Situación del equipo", "Riesgo por las dos vías y qué necesita para salvarse.", f"¿Qué necesita {team} para no descender?"),
                ("Chances de descenso", "Probabilidad estimada para equipos de la zona baja.", f"Chances de {team} para el descenso"),
                ("Qué le conviene para salvarse", "Resultados ajenos que lo alejan de la zona roja.", f"¿Qué le conviene a {team} para salvarse?"),
                ("Promedio del equipo", "Coeficiente actual y efecto de sumar 0, 1 o 3 puntos.", f"Promedio de {team}"),
                ("Relato del descenso", "Texto breve sobre la pelea de abajo.", "Relato del descenso"),
                ("Tabla Anual", "La otra vía del descenso, además de los promedios.", "Tabla Anual"),
            ],
            "📅 Fecha y escenarios": [
                ("Previa de toda la fecha", "Resumen de todos los partidos y lo que está en juego.", "Previa de la fecha"),
                ("Previa de un equipo", "Su partido y el rango de posiciones posible.", f"Previa de {team}"),
                ("Qué se juega cada equipo", "Una frase editorial por participante.", "Qué se juega cada equipo"),
                ("Partido bisagra", "Encuentro que puede mover más la clasificación.", f"Partido bisagra de {team}"),
                ("Árbol del próximo partido", "Gana, empata o pierde y cómo cambia el escenario.", f"Árbol de {team}"),
                ("Distribución de la zona", "Probabilidad estimada de terminar en cada franja de la tabla.", f"Distribución de puestos de {team}"),
                ("Estado de la fecha", "Qué ya está cargado, qué se jugó y qué falta.", "Estado de la fecha"),
                ("Si terminara hoy", "Foto actual de posiciones y clasificaciones.", "Si terminara hoy"),
                ("Partidos que le quedan", "Fixture restante y dificultad del camino.", f"¿Contra quién juega {team}?"),
            ],
            "🔎 Equipo y rendimiento": [
                ("Ficha completa", "Puesto, puntos, DG, ritmo y rivales pendientes.", f"Ficha de {team}"),
                ("Forma reciente", "Últimos cinco partidos y puntos obtenidos.", f"Forma de {team}"),
                ("Racha", "Secuencia actual de triunfos, empates o derrotas.", f"Racha de {team}"),
                ("Local y visitante", "Rendimiento separado por condición.", f"De local y de visitante {team}"),
                ("Calendario restante", "Dificultad del fixture que le queda.", f"Calendario de {team}"),
                ("Comparar equipos", "Cara a cara por puntos, techo y objetivo.", f"Comparar {team} y {other}"),
                ("Cómo viene", "Termómetro general de sus chances.", f"¿Cómo viene {team}?"),
                ("Distribución de puestos", "Probabilidad estimada de terminar en cada zona.", f"Distribución de puestos de {team}"),
                ("Explicar la última respuesta", "Desarma la cuenta anterior paso a paso.", "¿Por qué?"),
            ],
            "🗞️ Para redactar": [
                ("Relato de la zona", "Panorama breve con posiciones, puntos y diferencia de gol.", f"Relato de la zona de {team}"),
                ("Previa general de la fecha", "Pantallazo editorial de todos los partidos.", "Previa de la fecha"),
                ("Qué se juega cada equipo", "Un renglón utilizable como copete o placa.", "Qué se juega cada equipo"),
                ("Relato de Libertadores", "Texto publicable sobre la clasificación a la copa.", "Relato de la Libertadores"),
                ("Relato de Sudamericana", "Texto publicable sobre la clasificación a la copa.", "Relato de la Sudamericana"),
                ("Relato del descenso", "Texto publicable sobre anual y promedios.", "Relato del descenso"),
                ("Relato de su zona", "Resumen periodístico de la pelea en la zona donde juega.", f"Contame el escenario de {team}"),
            ],
            "📊 Tablas y visuales": [
                ("Tabla de las zonas", "Vista completa con la línea de clasificación.", "Tabla de las dos zonas"),
                ("Tabla Anual", "Acumulada para copas y descenso.", "Tabla Anual"),
                ("Promedios", "Coeficientes con mínimo y máximo posible.", "Promedios"),
                ("Proyección", "Puntos finales al ritmo actual.", "Proyección"),
                ("Máximos", "Puntaje máximo alcanzable por cada equipo.", "Máximos"),
                ("Distribución", "Chances por puesto o zona del equipo elegido.", f"Barras de {team}"),
                ("Chances por zonas", "Distribución probabilística de clasificación en ambas zonas.", "Mapa de posiciones"),
                ("Comparación", "Cuadro cara a cara entre dos equipos.", f"Comparar {team} y {other}"),
            ],
            "🧾 Datos y ayuda": [
                ("Estado de la fecha", "Partidos cargados, pendientes y en curso.", "Estado de la fecha"),
                ("Verificar actualización", "Controla si las tablas quedaron viejas.", "¿Está actualizado?"),
                ("Buscar un equipo", "Ubica automáticamente su zona.", f"¿En qué zona está {team}?"),
                ("Ver todos los grupos", "Lista grupos y equipos cargados.", "¿Qué grupos hay?"),
                ("Guía completa", "Muestra la ayuda extensa con todos los comandos.", "Ayuda"),
            ],
        }

    return {
        "⭐ Más usadas": [
            ("Qué necesita", "Resultados que lo clasifican o acercan al objetivo.", f"¿Qué necesita {team}?"),
            ("Qué le conviene", "Resultados propios y ajenos más favorables.", f"¿Qué le conviene a {team}?"),
            ("Tabla", "Posiciones actuales del grupo o liga.", "Tabla"),
            ("Panorama", "Resumen general de la competencia.", "Panorama"),
            ("Probabilidades", "Distribución estimada de clasificación o puestos.", "Probabilidades"),
            ("Relato", "Texto periodístico listo para usar.", f"Contame el escenario de {team}"),
        ],
        "🎯 Escenarios": [
            ("Qué necesita", "Cuenta por resultados o puntos.", f"¿Qué necesita {team}?"),
            ("Qué le conviene", "Mejor combinación propia y ajena.", f"¿Qué le conviene a {team}?"),
            ("Puesto exacto", "Qué resultados lo dejan en una posición concreta.", f"{team} puede salir 1º"),
            ("Número mágico", "Mínimo que asegura o total seguro para el objetivo.", f"Número mágico de {team}"),
            ("Si terminara hoy", "Clasificados y orden actual.", "Si terminara hoy"),
            ("Simulador", "Fija resultados y recalcula la tabla.", "Simulador: qué pasa si"),
        ],
        "📊 Análisis y visuales": [
            ("Comparar", "Cara a cara entre dos equipos.", f"Comparar {team} y {other}"),
            ("Mapa", "Mapa de calor de puestos posibles.", "Mapa del grupo"),
            ("Distribución", "Barras de posiciones posibles.", f"Barras de {team}"),
            ("Partido bisagra", "Encuentro que más define.", "Partido bisagra"),
            ("Proyección", "Puntaje final al ritmo actual.", "Proyección"),
            ("Máximos", "Techos matemáticos.", "Máximos"),
        ],
        "🗞️ Para redactar": [
            ("Relato del grupo", "Panorama listo para publicar.", "Relato del grupo"),
            ("Escenario de un equipo", "Texto centrado en un participante.", f"Contame el escenario de {team}"),
            ("Previa de la fecha", "Qué define cada partido pendiente.", "Previa de la fecha"),
            ("Qué se juega cada uno", "Una frase por equipo.", "Qué se juega cada equipo"),
        ],
        "🧾 Ayuda": [
            ("Guía completa", "Lista extensa de capacidades y ejemplos.", "Ayuda"),
            ("Explicar la cuenta", "Desarma la última respuesta.", "¿Por qué?"),
            ("Buscar grupo", "Ubica un equipo en el torneo cargado.", f"¿En qué grupo está {team}?"),
            ("Listar grupos", "Muestra todos los grupos disponibles.", "¿Qué grupos hay?"),
        ],
    }


def _render_chat_explorer(E):
    """Selector y buscador de capacidades. Devuelve la consulta elegida o None."""
    equipos_chat = list(dict.fromkeys(E.get("equipos") or []))
    if not equipos_chat:
        equipos_chat = ["River Plate"]
    default_team = "River Plate" if "River Plate" in equipos_chat else equipos_chat[0]
    if st.session_state.get("ultimo_equipo") in equipos_chat:
        default_team = st.session_state["ultimo_equipo"]
    default_idx = equipos_chat.index(default_team)
    if "chat_guide_team" in st.session_state and st.session_state.get("chat_guide_team") not in equipos_chat:
        st.session_state["chat_guide_team"] = default_team

    ui_markdown("#### 🧭 Encontrá una opción del chat")
    ui_caption("No hace falta recordar frases: elegí un equipo, el objetivo activo y un tema. El objetivo se conserva también en Panel por equipo, Visualizaciones y seguimientos del chat.")
    if E.get("modo") == "lpf2026":
        _sync_lpf_objective_widget("chat_guide_objective")
        c_team, c_obj, c_other, c_search = st.columns([1.0, 1.05, 1.0, 1.35])
    else:
        c_team, c_other, c_search = st.columns([1.05, 1.05, 1.4])
        c_obj = None
    team = c_team.selectbox("Equipo principal", equipos_chat, index=default_idx, key="chat_guide_team")
    if c_obj is not None:
        c_obj.selectbox(
            "Objetivo activo",
            _LPF_OBJECTIVE_UI_OPTIONS,
            key="chat_guide_objective",
            on_change=_lpf_objective_widget_changed,
            args=("chat_guide_objective",),
        )
    otros = [e for e in equipos_chat if e != team] or [team]
    if "chat_guide_other" in st.session_state and st.session_state.get("chat_guide_other") not in otros:
        st.session_state["chat_guide_other"] = otros[0]
    other = c_other.selectbox("Comparar con", otros, key="chat_guide_other")
    search = c_search.text_input(
        "Buscar una función",
        placeholder="Ej.: Libertadores, previa, promedios, distribución…",
        key="chat_guide_search",
    ).strip()

    catalog = _chat_catalog(E, team, other)
    categories = list(catalog)
    if "chat_guide_category" in st.session_state and st.session_state.get("chat_guide_category") not in categories:
        st.session_state["chat_guide_category"] = categories[0]
    category = ui_selectbox("Tema", categories, key="chat_guide_category")

    if search:
        needle = _zlow(search)
        visible = []
        for cat, options in catalog.items():
            for label, desc, prompt in options:
                if needle in _zlow(" ".join((cat, label, desc, prompt))):
                    visible.append((cat, label, desc, prompt))
        ui_caption(f"Resultados para **{search}**: {len(visible)} opción{'es' if len(visible) != 1 else ''}.")
    else:
        visible = [(category, *option) for option in catalog[category]]

    clicked = None
    if not visible:
        ui_info("No encontré esa función. Probá otra palabra o tocá **Guía completa** en el índice.")
    else:
        for start in range(0, len(visible), 3):
            row = visible[start:start + 3]
            cols = st.columns(3)
            for offset, (cat, label, desc, prompt) in enumerate(row):
                col = cols[offset]
                key_base = f"chat_catalog_{categories.index(cat)}_{catalog[cat].index((label, desc, prompt))}"
                if col.button(label, use_container_width=True, help=prompt, key=key_base):
                    clicked = prompt
                col.caption(desc)

    with st.expander("📚 Índice completo de opciones"):
        ui_caption("Este índice reúne todas las consultas disponibles en el chat. Cambiá el tema de arriba para convertirlas en botones.")
        for cat, options in catalog.items():
            ui_markdown(f"**{cat}**")
            ui_markdown("\n".join(f"- **{label}:** {desc}" for label, desc, _ in options))

    return clicked


# ─── EJECUTOR DETERMINÍSTICO (las cuentas las hace el motor, nunca el LLM) ─────────

# ═══════════════════════════════════════════════════════════════════════════
#  TAREA 4 — Previa de la fecha y árbol de un equipo POR SIMULACIÓN (modo LPF)
#  Reusa el MISMO modelo que liga_probabilidades_df: fuerza por puntos/partido
#  (_fuerza_liga), ventaja de localía y probabilidad de empate. No enumera
#  marcadores: es estimación. Todo lo calcula Python; el número va rotulado.
# ═══════════════════════════════════════════════════════════════════════════
_LPF_PDRAW = 0.26
_LPF_LOCALIA = 1.22
_LPF_TOP_OCTAVOS = 8   # clasifican los 8 primeros de cada zona

def _lpf_fecha_de(pend, games=None):
    """Dict {(local, visita): fecha} para los pendientes, según el fixture."""
    return _schedule_pending_round_map(pend, games or LPF_FIXTURE)


def lpf_jornada_actual(pend, games=None, umbral=0.5, forzar=None):
    """Distingue la jornada operativa de los partidos postergados."""
    return _schedule_current_round(pend, games or LPF_FIXTURE, umbral=umbral, forzar=forzar)


def lpf_etiqueta_jornada(jornada, atrasados):
    return _schedule_round_label(jornada, atrasados)


def _lpf_parse_datetime(value):
    return _schedule_parse_datetime(value)


def _lpf_schedule_map():
    """Agenda conocida por partido, con nombres canónicos y datetimes de Argentina."""
    return _schedule_build_map(
        globals().get("_ESPN_FECHA_HORA") or {},
        st.session_state.get("LPF_SCHEDULE") or {},
        globals().get("_ESPN_DIA") or {},
    )


def _lpf_match_round(match, games=None):
    return _schedule_match_round(match, games or LPF_FIXTURE)


def _lpf_match_datetime(match):
    return _lpf_schedule_map().get(tuple(match))


def _lpf_format_datetime(value):
    return _schedule_format_datetime(value)


def lpf_partidos_equipo_ordenados(equipo, pend, games=None):
    """Pendientes del equipo ordenados primero por fecha/hora real y luego por fecha oficial."""
    return _schedule_ordered_team_matches(
        equipo, pend, games or LPF_FIXTURE, _lpf_schedule_map()
    )


def lpf_proximo_partido_equipo(equipo, pend, games=None):
    return _schedule_next_team_match(
        equipo, pend, games or LPF_FIXTURE, _lpf_schedule_map()
    )


def _lpf_scope_games(equipo, pend, scope="next_team_match", fecha=None):
    """Resuelve la ventana de análisis sin confundir fecha oficial con calendario real."""
    return _schedule_resolve_scope_games(
        equipo,
        pend,
        LPF_FIXTURE,
        _lpf_schedule_map(),
        scope=scope,
        fecha=fecha,
    )


def _lpf_normalize_match_identity(match):
    """Devuelve la identidad canónica de un partido usando el fixture oficial.

    Sirve para que todas las herramientas de escenarios compartan la misma noción
    de partido y no puedan contar dos veces una ficha por alias u orientación.
    """
    if not match or len(match) < 2:
        return None
    local, visitor = match[0], match[1]
    cl, cv, _gl, _gv = _lpf_normalize_result_identity(local, visitor, 0, 0)
    return (cl, cv)


def _lpf_dedupe_scenario_games(games):
    """Normaliza y deduplica partidos antes de enviarlos a cualquier solver."""
    out = []
    seen = set()
    for match in games or []:
        normalized = _lpf_normalize_match_identity(tuple(match))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _lpf_preview_scenario_games(window, pend, scope="next_team_match"):
    """Partidos que deben quedar abiertos al calcular gana/empata/pierde.

    La tarjeta puede estar centrada en un único próximo partido, pero su rango de
    puesto al cierre de la fecha depende también de las otras canchas de esa misma
    jornada. La expansión se hace para cualquier equipo, no para un caso particular.
    Para un postergado aislado se consideran los pendientes de su fecha oficial; si
    esa referencia no existe, se usa el mismo día real como respaldo.
    """
    games = _lpf_dedupe_scenario_games(window.get("games") or [])
    own = window.get("own_match")
    if scope == "next_team_match" and own:
        own = _lpf_normalize_match_identity(tuple(own))
        own_meta = window.get("own_meta") or {}
        round_no = own_meta.get("round") or _lpf_match_round(own)
        expected = []
        if round_no is not None:
            expected = [
                tuple(match) for match in (pend or [])
                if _lpf_match_round(tuple(match)) == round_no
            ]
        elif own_meta.get("scheduled_at"):
            day = own_meta["scheduled_at"].date()
            expected = [
                tuple(match) for match in (pend or [])
                if (_lpf_match_datetime(tuple(match)) and _lpf_match_datetime(tuple(match)).date() == day)
            ]
        # Unión, no reemplazo ciego: si una fuente omite temporalmente una ficha de
        # la fecha, el partido propio sigue incluido y el resto de la jornada no se
        # congela. La deduplicación usa identidad oficial.
        games = _lpf_dedupe_scenario_games(list(expected) + list(games) + ([own] if own else []))
    return games


def _lpf_round_from_query(q):
    """Fecha oficial pedida en lenguaje natural, si aparece explícita."""
    text = _zlow(q)
    match = re.search(r"\bfecha(?:\s+oficial)?\s*(?:n[°ºo]?\s*)?(\d{1,2})\b", text)
    return int(match.group(1)) if match else None


def _lpf_scope_from_query(q, default="next_team_day"):
    text = _zlow(q)
    explicit_round = _lpf_round_from_query(q)
    if any(token in text for token in ("solo posterg", "sólo posterg")):
        return "postponed_only"
    if any(token in text for token in ("fecha y posterg", "fecha + posterg", "ventana completa", "fecha completa")):
        return "extended_window"
    if explicit_round is not None:
        return "extended_window" if "posterg" in text else "official_round"
    if "fecha oficial" in text:
        return "official_round"
    if any(token in text for token in ("proximo partido", "próximo partido", "partido real")):
        return "next_team_match"
    if any(token in text for token in ("mismo dia", "mismo día", "ese dia", "ese día", "otra cancha")):
        return "next_team_day"
    return default

def lpf_equipos_con_atraso(pend, games=None):
    """{equipo: partidos atrasados} — los que tienen partidos de fechas previas a
    la jornada en juego (juegan menos partidos que el resto: distorsiona la tabla)."""
    jornada, _, atrasados = lpf_jornada_actual(pend, games)
    out = {}
    for (l, v), _f in atrasados:
        out[l] = out.get(l, 0) + 1
        out[v] = out.get(v, 0) + 1
    return out

def _lpf_tipo_de(games=None):
    games = games or LPF_FIXTURE
    return {(g["l"], g["v"]): (g["tipo"], g.get("zona")) for g in games}

def _lpf_prob_partido(l, v, s, pdraw=_LPF_PDRAW, loc=_LPF_LOCALIA):
    """(p_local, p_empate, p_visita) con el kernel canónico del simulador."""
    return _match_outcome_probabilities(s.get(l, 1.0), s.get(v, 1.0), pdraw, loc)

def lpf_previa_fecha_sim(Z, rest, pend, jugados=None, fecha=None):
    """Previa de la PRÓXIMA fecha por jugar: para cada partido, probabilidad
    estimada de que gane el local, empaten o gane la visita. Devuelve (fecha, df)
    o (None, None) si no hay pendientes."""
    base_all = {}
    for b in Z.values():
        base_all.update(b)
    s = _fuerza_lpf(base_all, jugados)
    fmap = _lpf_fecha_de(pend)
    con_fecha = [(lv, f) for lv, f in fmap.items() if f is not None]
    if not con_fecha:
        return None, None
    prox, juegos, atrasados = lpf_jornada_actual(pend, forzar=fecha)
    if prox is None:
        return None, None
    tipo_map = _lpf_tipo_de()
    def _orden(lv):
        tipo, zona = tipo_map.get(lv, ("zona", "Z"))
        return (0 if tipo == "zona" else 1, zona or "Z", lv[0])
    rows = []
    for (l, v) in sorted(juegos, key=_orden):
        pl, pe, pv = _lpf_prob_partido(l, v, s)
        tipo, zona = tipo_map.get((l, v), ("zona", None))
        etiqueta = (f"Zona {zona}" if tipo == "zona" and zona else "Interzonal")
        rows.append({"Partido": f"{l} – {v}", "Cuándo": (_lpf_format_datetime(_lpf_match_datetime((l, v))) or f"Fecha {prox}"), "Tipo": etiqueta,
                     "Gana local %": round(100 * pl),
                     "Empate %": round(100 * pe),
                     "Gana visita %": round(100 * pv)})
    for (l, v), f in sorted(atrasados, key=lambda x: (x[1], x[0][0])):
        pl, pe, pv = _lpf_prob_partido(l, v, s)
        tipo, zona = tipo_map.get((l, v), ("zona", None))
        etiqueta = (f"Zona {zona}" if tipo == "zona" and zona else "Interzonal")
        rows.append({"Partido": f"{l} – {v}", "Cuándo": ((_lpf_format_datetime(_lpf_match_datetime((l, v))) + f" · postergado F{f}") if _lpf_match_datetime((l, v)) else f"Postergado F{f}"), "Tipo": etiqueta,
                     "Gana local %": round(100 * pl),
                     "Empate %": round(100 * pe),
                     "Gana visita %": round(100 * pv)})
    return prox, pd.DataFrame(rows)


def lpf_que_se_juega_fecha(
    Z, pend, fecha=None, apertura=None, camps=("", "", ""), extras=("", ""),
    previous=None, rest=None, n_anual=1, n_prom=1,
):
    """Un renglón periodístico por club para la próxima ventana de partidos.

    La salida combina rivales, rango de playoffs por puntos, carrera por las copas
    y alertas de descenso. No presenta los extremos de puesto como pronósticos.
    """
    prox, official_games, postponed = lpf_jornada_actual(pend, forzar=fecha)
    if prox is None:
        return "No quedan partidos pendientes.", None
    games = _lpf_dedupe_scenario_games(list(official_games) + [match for match, _round in postponed])
    if not games:
        return "No hay partidos en la ventana elegida.", None

    participants = []
    for match in games:
        for team in match:
            if team not in participants:
                participants.append(team)

    rest = rest or {}
    annual = lpf_anual_base(Z, apertura or {}) if Z else {}
    allocation = lpf_plazas_copas(Z, apertura or {}, camps or ("", "", ""), extras or ("", "")) if annual else {}
    fixed_routes = {
        team: motive for team, motive in allocation.get("lib", [])
        if "arts. 27.4 a 27.6" not in str(motive)
    }
    eligible = [team for team in allocation.get("orden", []) if team not in fixed_routes and team in annual]
    eligible_base = {team: annual[team] for team in eligible}
    n_lib = int(allocation.get("n_tabla_lib", 0))
    cup_end = n_lib + 6
    annual_table = liga_tabla_df(annual) if annual else pd.DataFrame()
    annual_positions = {
        row["Equipo"]: pos for pos, (_idx, row) in enumerate(annual_table.iterrows(), 1)
    } if not annual_table.empty else {}

    average_positions = {}
    average_danger_from = None
    if annual and previous:
        try:
            avg = promedios_df(annual, rest, previous)
            average_positions = {row["Equipo"]: int(row["Pos"]) for _, row in avg.iterrows()}
            average_danger_from = max(1, len(avg) - max(1, int(n_prom)) + 1)
        except Exception:
            average_positions = {}
            average_danger_from = None

    def _clean_route(route):
        return re.sub(r"\s*\(art\.[^)]+\)", "", str(route or "")).strip()

    def _word_number(value):
        words = {1: "un", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez"}
        return words.get(int(value), str(value))

    def _range(best, worst):
        return _ord(best) if best == worst else f"{_ord(best)}–{_ord(worst)}"

    lines = []
    rows = []
    for team in participants:
        lab = lpf_zona_de_equipo(team, Z)
        base = (Z or {}).get(lab or "", {})
        if not base or team not in base:
            continue
        table = liga_tabla_df(base)
        hit = table.index[table["Equipo"] == team].tolist()
        if not hit:
            continue
        current = int(hit[0] + 1)
        zone_games = [match for match in games if match[0] in base or match[1] in base]
        bounds = scenario_rank_bounds(base, zone_games, team)
        appearances = sum(team in match for match in games)
        rivals = [visitor if local == team else local for local, visitor in games if team in (local, visitor)]
        rivals_display = [display_team(rival) for rival in rivals]
        if appearances == 1:
            schedule = f"{display_team(team)} juega ante {rivals_display[0]}"
        elif appearances == 2:
            schedule = f"{display_team(team)} juega dos veces, ante {rivals_display[0]} y {rivals_display[1]}"
        else:
            schedule = f"{display_team(team)} juega {appearances} veces, ante " + ", ".join(rivals_display[:-1]) + f" y {rivals_display[-1]}"

        if not bounds.get("available"):
            playoff_text = "No tiene un rango de playoffs confirmado para esta ventana."
            best = worst = None
        else:
            best = int(bounds["best_rank"])
            worst = int(bounds["worst_rank"])
            rank_text = _range(best, worst)
            short_window = (worst - best + 1) <= 5
            if current <= _LPF_TOP_OCTAVOS and worst <= _LPF_TOP_OCTAVOS:
                if short_window:
                    playoff_text = f"Ya aseguró cerrar entre los ocho; puede quedar {rank_text} por puntos."
                else:
                    playoff_text = f"Ya aseguró cerrar entre los ocho; puede subir hasta {_ord(best)} por puntos."
            elif current <= _LPF_TOP_OCTAVOS:
                if short_window:
                    playoff_text = f"Puede sostenerse o salir de playoffs; su rango es {rank_text} por puntos."
                else:
                    playoff_text = f"Comienza dentro de los playoffs; puede subir hasta {_ord(best)}, pero también terminar la fecha fuera de los ocho."
            elif best <= _LPF_TOP_OCTAVOS:
                if short_window:
                    playoff_text = f"Puede entrar a playoffs o seguir afuera; su rango es {rank_text} por puntos."
                else:
                    playoff_text = f"Parte fuera de los playoffs; puede subir hasta {_ord(best)} y tiene escenarios para entrar entre los ocho, aunque también puede continuar afuera."
            else:
                playoff_text = f"No puede entrar a playoffs en esta ventana; su mejor puesto por puntos es {_ord(best)}."

        annual_bounds_team = scenario_rank_bounds(annual, games, team) if annual and team in annual else {}
        current_annual = annual_positions.get(team)
        annual_rank_text = ""
        if current_annual:
            annual_rank_text = f"Está {_ord(current_annual)} en la Tabla Anual."
        if annual_bounds_team.get("available"):
            abest_team = int(annual_bounds_team["best_rank"])
            aworst_team = int(annual_bounds_team["worst_rank"])
            annual_rank_text += (
                f" Su mejor posición posible al cierre de la ventana es {_ord(abest_team)} "
                f"y la peor {_ord(aworst_team)}."
            )

        cup_text = ""
        cup_material = False
        direct_route = fixed_routes.get(team, "")
        if direct_route:
            cup_text = (annual_rank_text + " " if annual_rank_text else "") + (
                f"Ya está clasificado a las copas por {_clean_route(direct_route)}."
            )
            cup_material = True
        elif team in eligible_base:
            cup_bounds = scenario_rank_bounds(eligible_base, games, team)
            if cup_bounds.get("available"):
                cbest, cworst = int(cup_bounds["best_rank"]), int(cup_bounds["worst_rank"])
                current_eligible = 1 + sum(
                    1 for rival in eligible_base
                    if rival != team and int(eligible_base[rival].get("pts", 0)) > int(eligible_base[team].get("pts", 0))
                )
                status = ""
                if n_lib and cworst <= n_lib:
                    status = "Asegura cerrar la ventana en zona de Libertadores por la Tabla Anual."
                elif n_lib and cbest <= n_lib:
                    if cworst <= cup_end:
                        status = "Puede terminar la ventana en zona de Libertadores o Sudamericana."
                    else:
                        status = "Puede terminar en Libertadores, Sudamericana o fuera de los puestos de clasificación internacional."
                elif cbest <= cup_end:
                    if cworst <= cup_end:
                        status = "Asegura cerrar al menos en zona de Sudamericana por la Tabla Anual."
                    else:
                        status = "Puede entrar a una copa o terminar afuera de los puestos de clasificación internacional."
                elif current_eligible <= cup_end + 2 or cbest <= cup_end + 1:
                    status = "Sigue fuera de los puestos de clasificación internacional en esta ventana."
                if status:
                    cup_text = (annual_rank_text + " " if annual_rank_text else "") + status
                    fixed_above = [
                        q for q in fixed_routes
                        if annual_positions.get(q) and current_annual and annual_positions[q] < current_annual
                    ]
                    if fixed_above:
                        shown_fixed = [display_team(q) for q in fixed_above]
                        if len(shown_fixed) == 1:
                            cup_text += f" (Arriba está {shown_fixed[0]}, que ya tiene una plaza directa de Libertadores.)"
                        else:
                            cup_text += (
                                f" (Entre los equipos que tiene arriba están {', '.join(shown_fixed[:-1])} y {shown_fixed[-1]}, "
                                "que ya tienen una plaza directa de Libertadores.)"
                            )
                    cup_material = True

        descent_parts = []
        descent_material = False
        if annual and team in annual:
            annual_bounds = annual_bounds_team
            danger_from = max(1, len(annual) - max(1, int(n_anual)) + 1)
            if annual_bounds.get("available"):
                abest, aworst = int(annual_bounds["best_rank"]), int(annual_bounds["worst_rank"])
                if abest >= danger_from:
                    descent_parts.append("Termina la ventana en zona de descenso por Tabla Anual")
                    descent_material = True
                elif aworst >= danger_from:
                    if current_annual and current_annual >= danger_from:
                        descent_parts.append("Puede salir o seguir en zona de descenso por Tabla Anual")
                    else:
                        descent_parts.append("Puede caer en zona de descenso por Tabla Anual")
                    descent_material = True
                elif current_annual and current_annual >= danger_from - 2:
                    descent_parts.append("Sigue cerca de la zona de descenso por Tabla Anual")
                    descent_material = True
        avg_pos = average_positions.get(team)
        if avg_pos and average_danger_from:
            if avg_pos >= average_danger_from:
                descent_parts.append("está en zona de descenso por promedios")
                descent_material = True
            elif avg_pos >= average_danger_from - 2:
                descent_parts.append("tiene margen corto en los promedios")
                descent_material = True
        descent_text = "; ".join(descent_parts)
        if descent_text:
            descent_text = descent_text[:1].upper() + descent_text[1:] + "."

        sentences = [schedule + ".", playoff_text]
        if cup_material and cup_text:
            sentences.append(cup_text)
        if descent_material and descent_text:
            sentences.append(descent_text)
        line = " ".join(sentences)
        lines.append(line)
        rows.append({
            "Equipo": display_team(team),
            "Partidos": appearances,
            "Rivales": " · ".join(rivals_display),
            "Playoffs": playoff_text.rstrip("."),
            "Copas": cup_text.rstrip(".") if cup_material else "Sin cambio decisivo en esta ventana",
            "Descenso": descent_text.rstrip(".") if descent_material else "Sin alerta inmediata en esta ventana",
            "Renglón reutilizable": line,
        })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame.attrs["export_title"] = f"Qué se juega cada equipo · Fecha {prox}"
        frame.attrs["export_name"] = f"que_se_juega_fecha_{prox}"
        frame.attrs["reusable_line"] = "\n".join(lines)

    heading = f"### Qué se juega cada equipo · Fecha {prox}"
    if postponed:
        rounds = sorted({round_number for _match, round_number in postponed if round_number is not None})
        count_text = _word_number(len(postponed))
        noun = "partido pendiente" if len(postponed) == 1 else "partidos pendientes"
        if len(rounds) == 1:
            heading += f" y {count_text} {noun} de la Fecha {rounds[0]}"
        else:
            heading += f" y {count_text} {noun} de fechas anteriores"
    intro = ("Los puestos son rangos exactos por puntos dentro de esta ventana; no son pronósticos y, "
             "si hay igualdad, contemplan tanto el desempate favorable como el adverso.")
    return heading + "\n\n" + intro + "\n\n" + "\n\n".join(f"- {line}" for line in lines), frame


def lpf_previa_fecha_narrativa(
    Z, rest, pend, jugados=None, fecha=None, partido=None,
    apertura=None, camps=("", "", ""), extras=("", ""), previous=None,
    n_anual=1, n_prom=1, include_cups=True, include_relegation=True,
):
    """Texto editorial breve para toda la fecha o para un encuentro puntual.

    Reutiliza la misma ventana que la pestaña de resultados: fecha oficial más
    postergados anteriores. La vista general calcula rangos exactos por puntos para
    toda la ventana; la vista individual agrega las ramas gana/empata/pierde.
    """
    prox, official_games, postponed = lpf_jornada_actual(pend, forzar=fecha)
    if prox is None:
        return "No quedan partidos pendientes."
    games = list(official_games) + [match for match, _round in postponed]
    base_all = {team: data for base in (Z or {}).values() for team, data in base.items()}
    strength = _fuerza_lpf(base_all, jugados)
    probabilities = {
        match: _lpf_prob_partido(match[0], match[1], strength)
        for match in games
    }
    postponed_rounds = {match: round_number for match, round_number in postponed}
    annual = lpf_anual_base(Z, apertura or {})
    allocation = lpf_plazas_copas(Z, apertura or {}, camps, extras) if annual else {}
    fixed = _lpf_fixed_lib_qualifiers(annual, camps, extras) if annual else []
    averages = []
    if annual and previous:
        averages = promedios_df(annual, rest, previous).to_dict("records")
    return round_preview_story(
        Z,
        games,
        round_label=lpf_etiqueta_jornada(prox, postponed),
        cutoff=_LPF_TOP_OCTAVOS,
        match_types=_lpf_tipo_de(),
        probabilities=probabilities,
        postponed_rounds=postponed_rounds,
        selected_match=partido,
        detailed=partido is not None,
        annual=annual,
        remaining=rest,
        fixed_qualified=fixed,
        table_slots_lib=int(allocation.get("n_tabla_lib") or 0),
        averages=averages,
        annual_relegations=int(n_anual),
        average_relegations=int(n_prom),
        include_cups=bool(include_cups),
        include_relegation=bool(include_relegation),
    )

def _sim_zone_rank_points(base, rest, pend, target, n, seed, forced=None,
                          pdraw=_LPF_PDRAW, loc=_LPF_LOCALIA, jugados=None, strength_base=None):
    """Devuelve posición y puntos finales simulados del equipo objetivo."""
    return _simulate_zone_rank_points_core(
        base, rest, pend, target, n, seed,
        strength=_fuerza_lpf(strength_base or base, jugados),
        forced=forced, pdraw=pdraw, loc=loc,
    )


def _sim_zone_pos(base, rest, pend, target, n, seed, forced=None,
                  pdraw=_LPF_PDRAW, loc=_LPF_LOCALIA, jugados=None, strength_base=None):
    """Array (n,) con la posición final de ``target`` dentro de su zona."""
    positions, _points_final = _sim_zone_rank_points(
        base, rest, pend, target, n, seed, forced=forced,
        pdraw=pdraw, loc=loc, jugados=jugados, strength_base=strength_base,
    )
    return positions


def lpf_arbol_sim(equipo, Z, rest, pend, top=_LPF_TOP_OCTAVOS, seed=17, jugados=None):
    """Árbol por simulación: cómo cambian las chances de entrar a octavos (top 8
    de la zona) según el resultado del PRÓXIMO partido del equipo, más el 'partido
    bisagra' de los próximos tres. Devuelve (texto, df) o (None, None)."""
    lab = lpf_zona_de_equipo(equipo, Z)
    if not lab or equipo not in Z.get(lab, {}):
        return None, None
    base = Z[lab]
    strength_base = {name: row for zone in (Z or {}).values() for name, row in zone.items()}
    mios = [(row["match"], row["round"]) for row in lpf_partidos_equipo_ordenados(equipo, pend)]
    if not mios:
        return None, None
    n = 12000 if len(pend) <= 30 else 5000
    def chance(forced):
        pos = _sim_zone_pos(
            base, rest, pend, equipo, n, seed, forced=forced, jugados=jugados,
            strength_base=strength_base,
        )
        return 100.0 * float((pos <= top).mean())
    base_ch = chance(None)
    (l, v), fx = mios[0]
    rival = v if l == equipo else l
    localia = "de local" if l == equipo else "de visitante"
    win = "L" if l == equipo else "V"
    lose = "V" if l == equipo else "L"
    ch_g = chance({(l, v): win}); ch_e = chance({(l, v): "E"}); ch_p = chance({(l, v): lose})
    df = pd.DataFrame([
        {"Si en la Fecha " + str(fx): f"le gana a {rival} ({localia})", "Chances de octavos": f"{round(ch_g)}%"},
        {"Si en la Fecha " + str(fx): f"empata con {rival}", "Chances de octavos": f"{round(ch_e)}%"},
        {"Si en la Fecha " + str(fx): f"pierde con {rival}", "Chances de octavos": f"{round(ch_p)}%"},
    ])
    # partido bisagra entre los próximos tres
    swings = []
    for (ll, vv), ff in mios[:3]:
        gw = "L" if ll == equipo else "V"; lw = "V" if ll == equipo else "L"
        sg = chance({(ll, vv): gw}); sp = chance({(ll, vv): lw})
        riv = vv if ll == equipo else ll
        swings.append((abs(sg - sp), riv, ff, sg, sp))
    swings.sort(reverse=True)
    sw = swings[0]
    L = [f"**Árbol de {equipo}** — chances de entrar a octavos (los 8 primeros de la Zona {lab}).",
         f"Hoy, sin jugar nada, está en **{round(base_ch)}%**.",
         f"Su próximo partido es {localia} ante **{rival}**" + (f" (**Fecha {fx}**)" if fx is not None else "") + ":"]
    if len(swings) > 1 and sw[0] >= 3:
        L.append(f"De los próximos partidos, el **bisagra es ante {sw[1]} (Fecha {sw[2]})**: "
                 f"ganarlo lo pone en {round(sw[3])}% y perderlo lo deja en {round(sw[4])}%.")
    L.append(f"_ESTIMADO · {n:,} simulaciones. Los veredictos «ya está» / «quedó afuera» se calculan por separado; "
             "esta distribución es una probabilidad del modelo, no un cálculo exacto ni un pronóstico._")
    return "\n\n".join(L), df


def lpf_otros_resultados_sim(equipo, Z, rest, pend, top=_LPF_TOP_OCTAVOS, jugados=None, seed=19, fecha=None, scope="next_team_day"):
    """Impacto de la otra cancha con control explícito del ruido Monte Carlo."""
    import math
    lab = lpf_zona_de_equipo(equipo, Z)
    if not lab or equipo not in Z.get(lab, {}):
        return None, None
    base = Z[lab]
    strength_base = {name: row for zone in (Z or {}).values() for name, row in zone.items()}
    window = _lpf_scope_games(equipo, pend, scope=scope, fecha=fecha)
    all_games = list(window["games"])
    games = [(l, v) for l, v in all_games if equipo not in (l, v) and (l in base or v in base)]
    if not games:
        return None, None

    n = 30000
    def chance(forced):
        pos = _sim_zone_pos(
            base, rest, pend, equipo, n, seed, forced=forced, jugados=jugados,
            strength_base=strength_base,
        )
        return 100.0 * float((pos <= top).mean())

    base_ch = chance(None)
    p = min(0.999, max(0.001, base_ch / 100.0))
    # Umbral de ruido aproximado para comparar dos simulaciones. Se conserva un
    # mínimo editorial de 0,35 pp para no sobrerreaccionar a diferencias diminutas.
    noise = max(0.35, 1.96 * math.sqrt(2 * p * (1 - p) / n) * 100)
    rows = []
    labels = {"L": lambda l, v: f"gana {l}", "E": lambda l, v: "empatan", "V": lambda l, v: f"gana {v}"}
    for local, visitor in games:
        opts = {
            "L": chance({(local, visitor): "L"}),
            "E": chance({(local, visitor): "E"}),
            "V": chance({(local, visitor): "V"}),
        }
        best = max(opts, key=opts.get); worst = min(opts, key=opts.get)
        impact = opts[best] - opts[worst]
        if impact < noise:
            relevance = "Sin diferencia apreciable"
            recommendation = "Indistinguible dentro del ruido"
        elif impact < 0.5:
            relevance = "Impacto mínimo"
            recommendation = labels[best](local, visitor)
        elif impact < 2:
            relevance = "Ayuda"
            recommendation = labels[best](local, visitor)
        elif impact < 5:
            relevance = "Importante"
            recommendation = labels[best](local, visitor)
        else:
            relevance = "Decisivo"
            recommendation = labels[best](local, visitor)
        rows.append({
            "Partido": f"{local} – {visitor}",
            "Mejor para River" if equipo == "River Plate" else "Mejor resultado": recommendation,
            "Gana local": f"{_fmt_num_es(opts['L'], 1)}%",
            "Empate": f"{_fmt_num_es(opts['E'], 1)}%",
            "Gana visitante": f"{_fmt_num_es(opts['V'], 1)}%",
            "Diferencia": f"{_fmt_num_es(impact, 2)} pp",
            "Relevancia": relevance,
            "_impact": impact,
        })
    rows.sort(key=lambda row: -row["_impact"])
    significant = [row for row in rows if row["_impact"] >= noise]
    scope_label = window["label"]
    text = [f"## La otra cancha para {equipo} · {scope_label}",
            f"**Objetivo:** entrar a los playoffs de la Zona {lab}.  "
            f"**Probabilidad base estimada:** {_fmt_num_es(base_ch, 1)}%."]
    if significant:
        top_row = significant[0]
        best_col = "Mejor para River" if equipo == "River Plate" else "Mejor resultado"
        text.append(f"El partido ajeno de mayor impacto es **{top_row['Partido']}**. "
                    f"El resultado que más ayuda es **{top_row[best_col]}**, con una diferencia de "
                    f"**{top_row['Diferencia']}** entre el mejor y el peor desenlace.")
        text.append("La tabla ordena todos los encuentros por impacto. Una diferencia pequeña puede ayudar, "
                    "pero no debe presentarse como condición indispensable.")
    else:
        text.append("**No hay una otra cancha decisiva en esta ventana.** Ninguno de los resultados ajenos "
                    f"supera el umbral de ruido del modelo (**{_fmt_num_es(noise, 2)} puntos porcentuales**). "
                    "El resultado propio pesa bastante más.")
        text.append("En lugar de decir que todos los partidos ‘dan igual’, el detalle muestra las diferencias "
                    "mínimas para auditoría, pero las rotula como no apreciables.")
    text.append(f"_ESTIMADO · {_fmt_entero_es(n)} simulaciones, semilla {seed}. Las columnas comparan la chance de playoffs "
                "fijando por separado victoria local, empate y victoria visitante. No es un mínimo que asegura._")
    visible = [{k: v for k, v in row.items() if k != "_impact"} for row in rows]
    # Si nada es significativo, alcanza con los cinco partidos que más se acercan al umbral.
    if not significant:
        visible = visible[:5]
    return "\n\n".join(text), pd.DataFrame(visible)


def _empatados_en_tope(equipo, tabla, pts_de, games):
    """Equipos que quedarían IGUALADOS en puntos con el objetivo en su mejor caso.
    Sirve para no cantar un puesto que en realidad depende de ganar el desempate."""
    tope = pts_de(equipo) + 3
    juegan = {x for lv in games for x in lv}
    out = []
    for e in tabla:
        if e == equipo:
            continue
        piso_e = pts_de(e)                      # si pierde, se queda como está
        techo_e = piso_e + (3 if e in juegan else 0)
        if piso_e <= tope <= techo_e:           # puede terminar empatado en puntos
            out.append(e)
    return out

def _rango_puesto_fecha(target, tabla, score_after, games):
    """Mejor/peor puesto por puntos, incluyendo la incertidumbre del desempate.

    ``score_after`` se conserva por compatibilidad con los llamadores, pero la
    cuenta no congela la diferencia de gol actual: un resultado futuro la cambia.
    Los equipos igualados pueden favorecer o perjudicar al objetivo y el texto lo
    muestra como intervalo, en vez de inventar quién gana el desempate.
    """
    base = {e: {"pts": int(score_after(e, 0)[0] if isinstance(score_after(e, 0), tuple)
                                  else score_after(e, 0))} for e in tabla}
    r = next_round_rank_bounds(target, base, games)
    if not r:
        return r
    # Red de seguridad: ningún puesto puede caer fuera de 1..N. Si pasa, hay un
    # equipo contado dos veces (por ejemplo, si `games` trae partidos de dos fechas).
    n = len(base)
    b, w = r
    return max(1, min(b, n)), max(1, min(w, n))


def _rango_puesto_fecha_score(target, tabla, score_after, games):
    """Versión genérica para cocientes (promedios), donde no hay DG futura."""
    if target not in tabla:
        return None
    best_target = score_after(target, 3)
    worst_target = score_after(target, 0)
    best_above = worst_above = 0
    seen = {target}
    for local, visitor in games:
        if target in (local, visitor):
            rival = visitor if local == target else local
            if rival in tabla:
                seen.add(rival)
                best_above += int(score_after(rival, 0) > best_target)
                worst_above += int(score_after(rival, 3) > worst_target)
            continue
        in_local, in_visitor = local in tabla, visitor in tabla
        if in_local and in_visitor:
            seen.update((local, visitor))
            outcomes = ((3, 0), (1, 1), (0, 3))
            best_above += min(
                int(score_after(local, dl) > best_target) + int(score_after(visitor, dv) > best_target)
                for dl, dv in outcomes
            )
            worst_above += max(
                int(score_after(local, dl) > worst_target) + int(score_after(visitor, dv) > worst_target)
                for dl, dv in outcomes
            )
        elif in_local or in_visitor:
            rival = local if in_local else visitor
            seen.add(rival)
            best_above += min(int(score_after(rival, add) > best_target) for add in (3, 1, 0))
            worst_above += max(int(score_after(rival, add) > worst_target) for add in (3, 1, 0))
    for rival in tabla:
        if rival not in seen:
            best_above += int(score_after(rival, 0) > best_target)
            worst_above += int(score_after(rival, 0) > worst_target)
    return best_above + 1, worst_above + 1

def _pos_hoy(target, tabla, score_after):
    x = score_after(target, 0)
    return 1 + sum(1 for e in tabla if e != target and score_after(e, 0) > x)

def _ord(p):
    return f"{p}º"


def _preview_cup_context(Z, annual):
    E = st.session_state.get("ESTADO") or {}
    opening = E.get("apertura") or {}
    camps = E.get("camps") or (
        st.session_state.get("lpf_c1", "Belgrano"),
        st.session_state.get("lpf_c2", ""),
        st.session_state.get("lpf_c3", ""),
    )
    extras = E.get("intl") or (
        st.session_state.get("lpf_xl", ""),
        st.session_state.get("lpf_xs", ""),
    )
    allocation = lpf_plazas_copas(Z, opening, camps, extras)
    fixed_routes = {
        team: motive
        for team, motive in allocation.get("lib", [])
        if "arts. 27.4 a 27.6" not in str(motive)
    }
    eligible = [team for team in allocation.get("orden", []) if team not in fixed_routes and team in annual]
    return allocation, fixed_routes, eligible


def _lpf_previa_equipo_texto_legacy(equipo, Z, rest, pend, anual, prom, fecha=None,
                                     scope="next_team_match", objective="Playoffs"):
    """Fallback legacy de Previa para sesiones que aún no puedan crear snapshot."""
    window = dict(_lpf_scope_games(equipo, pend, scope=scope, fecha=fecha))
    window["scope"] = scope
    scenario_games = _lpf_preview_scenario_games(window, pend, scope=scope)

    own_match = window.get("own_match")
    own_meta = dict(window.get("own_meta") or {})
    if own_match:
        if not own_meta.get("scheduled_at"):
            own_meta["scheduled_at"] = _lpf_match_datetime(own_match)
        if own_meta.get("round") is None:
            own_meta["round"] = _lpf_match_round(own_match)
    window["own_meta"] = own_meta

    current_round, _official, _postponed = lpf_jornada_actual(pend, forzar=fecha)
    n_annual = int((st.session_state.get("ESTADO") or {}).get("n_anual", 1))

    allocation = {}
    fixed_routes = {}
    eligible = []
    if anual and equipo in anual and _preview_objective(objective) != "descenso":
        allocation, fixed_routes, eligible = _preview_cup_context(Z, anual)

    return _team_preview_text_core(
        equipo, Z, pend, anual,
        window=window, scenario_games=scenario_games, objective=objective,
        current_round=current_round, n_annual=n_annual,
        cup_allocation=allocation, fixed_routes=fixed_routes, eligible_teams=eligible,
        top_eight=_LPF_TOP_OCTAVOS,
    )


def lpf_previa_equipo_texto(equipo, Z, rest, pend, anual, prom, fecha=None,
                             scope="next_team_match", objective="Playoffs"):
    """Previa Streamlit consumiendo la operación pública ``preview``.

    Conserva la firma histórica de la UI para no forzar cambios en las vistas. La
    salida pública JSON vuelve a DataFrame sólo en esta última milla de presentación.
    """
    E = st.session_state.get("ESTADO") or {}
    try:
        result = _lpf_service_result(
            "preview", E,
            team=equipo,
            objective=_lpf_service_objective(objective),
            scope=scope,
            round=fecha,
            schedule=_lpf_service_schedule_payload(),
        )
        frame = pd.DataFrame(result.get("scenarios") or [])
        if result.get("reusable_line"):
            frame.attrs["reusable_line"] = result.get("reusable_line")
        return result.get("markdown"), frame
    except _LPFServiceContractError as exc:
        _record_lpf_service_fallback("preview", exc)
        return _lpf_previa_equipo_texto_legacy(
            equipo, Z, rest, pend, anual, prom, fecha=fecha, scope=scope, objective=objective
        )

def _lpf_ctx(Z, rest, apertura, camps, extras, previous_averages, n_anual=1, n_prom=1):
    """Wrapper de sesión del contexto puro compartido por las simulaciones."""
    estado = st.session_state.get("ESTADO") or {}
    opening = apertura or estado.get("apertura") or st.session_state.get("LPF_APERTURA") or {}
    direct = estado.get("anual_directo") or st.session_state.get("LPF_ANUAL") or {}
    replacement = st.session_state.get("LPF_COPA_ARG_REEMPLAZO", "")
    return _build_simulation_context_core(
        Z, rest, opening, camps, extras, previous_averages,
        direct_annual=direct, opening_rounds=LPF_APERTURA_PJ,
        copa_replacement=replacement, n_annual=n_anual, n_average=n_prom,
    )

def _objetivo_lpf(q):
    z = _zlow(q)
    explicit = None
    if "libertad" in z:
        explicit = "libertadores"
    elif "sudameric" in z and any(word in z for word in ("estricta", "especificamente", "específicamente", "solo sudamericana", "sólo sudamericana")):
        explicit = "sudamericana"
    elif "sudameric" in z:
        explicit = "al_menos_sudamericana"
    elif any(w in z for w in ("descenso", "descender", "no descend", "salvar", "salvarse", "permanencia", "no bajar", "no se va")):
        explicit = "descenso"
    elif any(w in z for w in ("copa", "internacional")):
        explicit = "al_menos_sudamericana"
    elif any(w in z for w in ("playoff", "octavos", "top 8", "zona")):
        explicit = "playoffs"
    if explicit:
        return _remember_lpf_objective(explicit)
    remembered = st.session_state.get("LPF_LAST_OBJECTIVE")
    if remembered in ("playoffs", "libertadores", "al_menos_sudamericana", "sudamericana", "descenso"):
        return remembered
    return "playoffs"

_OBJ_NOMBRE = {
    "libertadores": "la Libertadores",
    "al_menos_sudamericana": "al menos la Sudamericana",
    "sudamericana": "la Sudamericana sin contar Libertadores",
    "descenso": "no descender",
    "playoffs": "los playoffs",
}

def _lpf_riesgo_descenso(X, ctx, margen=6):
    """True si X está entre los últimos `margen` de promedios o de la anual (hoy)."""
    average_totals = ctx.get("average_totals") or ctx.get("prom") or {}
    if X in average_totals:
        pr = sorted(average_totals, key=lambda e: average_totals[e][0] / average_totals[e][1])   # peor primero
        if X in pr[:margen]:
            return True, pr
    at = sorted(ctx["apts"], key=lambda e: (ctx["apts"][e], ctx["adg"][e]))  # peor primero
    return (X in at[:margen]), None

def lpf_chances_obj(objetivo, ctx, pend, jugados, n=_LPF_PUBLIC_MC_RUNS, seed=23, destacar=None):
    """Tabla de probabilidades del objetivo para los equipos relevantes.
    Devuelve (df, nota, titular) — titular resalta al equipo `destacar` si se pasa."""
    eqs = ctx["equipos"]; base_all = {}
    for b in ctx["Z"].values():
        base_all.update(b)
    s = _fuerza_lpf(base_all, jugados)
    add, idx = _sim_lpf_add(eqs, pend, s, n, seed)
    if objetivo in ("libertadores", "sudamericana", "al_menos_sudamericana"):
        red = ctx["reducida"]
        rows = []
        sum_lib = sum_sud = 0.0
        for e in red:
            pl = _obj_bool("libertadores", e, add, idx, ctx).mean()
            ps = _obj_bool("sudamericana", e, add, idx, ctx).mean()
            sum_lib += float(pl); sum_sud += float(ps)
            rows.append({"Equipo": e, "Anual": f"{ctx['orden'].index(e)+1}º",
                         "Libertadores %": round(100 * pl), "Sudamericana %": round(100 * ps),
                         "Al menos Sudamericana %": round(100 * (pl + ps)),
                         "_k": pl if objetivo == "libertadores" else (pl + ps if objetivo == "al_menos_sudamericana" else ps)})
        rows.sort(key=lambda r: -r["_k"])
        if not np.isclose(sum_lib, ctx["n_lib"], atol=1e-10):
            raise AssertionError(f"Invariante Libertadores rota: {sum_lib} != {ctx['n_lib']}")
        if not np.isclose(sum_sud, min(6, max(0, len(red) - ctx["n_lib"])), atol=1e-10):
            raise AssertionError(f"Invariante Sudamericana rota: {sum_sud} != 6")
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "_k"} for r in rows]).head(14)
        df.attrs["mc_invariants"] = {"Libertadores": sum_lib, "Sudamericana": sum_sud}
        _camps = [e for e in ctx["orden"] if e not in ctx["reducida"]]
        _cnota = (f" No aparecen los que ya tienen plaza como campeones ({', '.join(_camps)}): liberan cupo y por eso "
                  f"Libertadores se cuenta sobre esta tabla." if _camps else "")
        nota = (f"Entran **{ctx['n_lib']}** a Libertadores por la tabla sin campeones y los **6** siguientes a Sudamericana.{_cnota} "
                f"{NOTA_MC_LIGA}")
        tit = ""
        if destacar and destacar in red:
            rr = next(r for r in rows if r["Equipo"] == destacar)
            tit = (f"**{destacar}:** {rr['Libertadores %']}% de entrar a la **Libertadores**, "
                       f"{rr['Sudamericana %']}% de terminar específicamente en **Sudamericana** y "
                       f"{rr['Al menos Sudamericana %']}% de obtener **al menos una copa**.")
        return df, nota, tit
    if objetivo == "descenso":
        rows = []
        sum_desc = 0.0
        for e in eqs:
            pd_ = _obj_bool("descenso", e, add, idx, ctx).mean()
            sum_desc += float(pd_)
            rows.append({"Equipo": e, "En promedios": ("sí" if e in ctx["prom"] else "no"),
                         "Prob. de descender %": round(100 * pd_), "_k": pd_})
        rows.sort(key=lambda r: -r["_k"])
        if ctx["prom"] and not np.isclose(sum_desc, 2.0, atol=1e-10):
            raise AssertionError(f"Invariante descenso rota: {sum_desc} != 2")
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "_k"} for r in rows if r["_k"] >= 0.005]).head(10)
        df.attrs["mc_invariants"] = {"Descensos": sum_desc}
        nota = (f"Bajan **{ctx['n_anual']}** por la Anual y **{ctx['n_prom']}** por Promedios (con la regla de reasignación "
                f"si coincide el último). {NOTA_MC_LIGA}")
        tit = ""
        if destacar:
            rr = next((r for r in rows if r["Equipo"] == destacar), None)
            if rr is not None:
                tit = f"**{destacar}:** {rr['Prob. de descender %']}% de descender (⇒ {100-rr['Prob. de descender %']}% de salvarse)."
        return df, nota, tit
    return None, None, ""

def lpf_conviene_obj(equipo, objetivo, ctx, pend, jugados, n=20000, seed=29, fecha=None, scope="next_team_day"):
    """La otra cancha para Anual/Promedios, con impacto y ruido explícitos."""
    import math
    eqs = ctx["equipos"]
    if objetivo in ("libertadores", "sudamericana", "al_menos_sudamericana") and equipo not in ctx["reducida"]:
        if equipo not in ctx["orden"]:
            return f"## La otra cancha para {equipo}\n\n{equipo} no figura en la Tabla Anual cargada.", None, None
        if objetivo == "sudamericana":
            message = (f"**{equipo} ya tiene una plaza directa de Libertadores.** Por eso no puede terminar "
                       "específicamente en Sudamericana por la Tabla Anual y ninguna otra cancha cambia esa vía directa.")
        else:
            message = (f"**{equipo} ya tiene una plaza directa de Libertadores.** El objetivo ya está cumplido por una vía "
                       "que no depende de estos resultados ajenos, así que no corresponde recomendar una ‘otra cancha’.")
        return f"## La otra cancha para {equipo}\n\n{message}", None, None
    if objetivo == "descenso":
        risk, _ = _lpf_riesgo_descenso(equipo, ctx)
        if not risk:
            return (f"## La otra cancha para {equipo} · salvarse del descenso\n\n"
                    f"**{equipo} no está hoy en la zona de riesgo usada por esta herramienta** "
                    "(últimos seis de Promedios o Tabla Anual). No publico una recomendación de otra cancha "
                    "a partir de diferencias residuales del Monte Carlo."), None, None
    base_all = {team: row for base in ctx["Z"].values() for team, row in base.items()}
    strength = _fuerza_lpf(base_all, jugados)
    fmap = _lpf_fecha_de(pend)
    window = _lpf_scope_games(equipo, pend, scope=scope, fecha=fecha)
    games = [match for match in window["games"] if equipo not in match]
    if not window["games"]:
        return None, None, None
    saving = objetivo == "descenso"

    def probability(forced):
        add, idx = _sim_lpf_add(eqs, pend, strength, n, seed, forced=forced)
        p = float(_obj_bool(objetivo, equipo, add, idx, ctx).mean())
        return (1 - p) * 100 if saving else p * 100

    baseline = probability(None)
    p0 = min(0.999, max(0.001, baseline / 100.0))
    noise = max(0.4, 1.96 * math.sqrt(2 * p0 * (1 - p0) / n) * 100)
    label = lambda l, v, result: {"L": f"gana {l}", "E": "empatan", "V": f"gana {v}"}[result]

    def evaluate(local, visitor):
        opts = {
            "L": probability({(local, visitor): "L"}),
            "E": probability({(local, visitor): "E"}),
            "V": probability({(local, visitor): "V"}),
        }
        best = max(opts, key=opts.get); worst = min(opts, key=opts.get)
        impact = opts[best] - opts[worst]
        if impact < noise:
            relevance = "Sin diferencia apreciable"
            recommendation = "Indistinguible dentro del ruido"
        elif impact < 0.5:
            relevance = "Impacto mínimo"; recommendation = label(local, visitor, best)
        elif impact < 2:
            relevance = "Ayuda"; recommendation = label(local, visitor, best)
        elif impact < 5:
            relevance = "Importante"; recommendation = label(local, visitor, best)
        else:
            relevance = "Decisivo"; recommendation = label(local, visitor, best)
        return {
            "Partido": f"{local} – {visitor}",
            "Mejor resultado": recommendation,
            "Gana local": f"{_fmt_num_es(opts['L'], 1)}%", "Empate": f"{_fmt_num_es(opts['E'], 1)}%",
            "Gana visitante": f"{_fmt_num_es(opts['V'], 1)}%", "Diferencia": f"{_fmt_num_es(impact, 2)} pp",
            "Relevancia": relevance, "_impact": impact,
        }

    rows = sorted((evaluate(l, v) for l, v in games), key=lambda row: -row["_impact"])
    significant = [row for row in rows if row["_impact"] >= noise]
    visible = [{k: v for k, v in row.items() if k != "_impact"} for row in (rows if significant else rows[:5])]
    df = pd.DataFrame(visible) if visible else None

    # Cruces futuros entre competidores directos.
    add0, idx0 = _sim_lpf_add(eqs, pend, strength, n, seed)
    universe = ctx["reducida"] if objetivo in ("libertadores", "sudamericana", "al_menos_sudamericana") else eqs
    target_prob = {team: float(_obj_bool(objetivo, team, add0, idx0, ctx).mean()) for team in universe}
    contested = [(team, p) for team, p in target_prob.items() if 0.03 <= p <= 0.97 and team != equipo]
    contested.sort(key=lambda item: -min(item[1], 1 - item[1]))
    competitors = {team for team, _p in contested[:8]}
    crosses = [((l, v), f) for (l, v), f in fmap.items()
               if f is not None and l in competitors and v in competitors]
    cross_rows = []
    for (local, visitor), rnd in sorted(crosses, key=lambda item: item[1])[:20]:
        row = evaluate(local, visitor)
        if row["_impact"] >= noise:
            row["Fecha"] = rnd
            cross_rows.append(row)
    cross_rows.sort(key=lambda row: -row["_impact"])
    df_cross = pd.DataFrame([
        {"Fecha": row["Fecha"], **{k: v for k, v in row.items() if k not in ("_impact", "Fecha")}}
        for row in cross_rows[:8]
    ]) if cross_rows else None

    objective_name = ("salvarse del descenso" if saving else
                      "obtener al menos Sudamericana" if objetivo == "al_menos_sudamericana" else
                      f"entrar a {_OBJ_NOMBRE[objetivo]}")
    scope_label = window["label"]
    text = [f"## La otra cancha para {equipo} · {objective_name}",
            f"**Ventana:** {scope_label}. **Probabilidad base estimada:** {_fmt_num_es(baseline, 1)}%."]
    if significant:
        top = significant[0]
        text.append(f"El partido de mayor impacto es **{top['Partido']}**: el mejor resultado es "
                    f"**{top['Mejor resultado']}** y la diferencia entre extremos es **{top['Diferencia']}**.")
    else:
        text.append("**Ningún partido ajeno supera el ruido de la simulación.** El detalle muestra los valores "
                    "más altos, pero no corresponde transformarlos en una recomendación categórica.")
    if df_cross is not None:
        text.append("También se muestran los cruces futuros entre competidores directos que sí superan el umbral de ruido.")
    text.append(f"_ESTIMADO · {_fmt_entero_es(n)} simulaciones, semilla {seed}, umbral de diferencia apreciable {_fmt_num_es(noise, 2)} pp. "
                "Las probabilidades no alimentan las garantías matemáticas._")
    return "\n\n".join(text), df, df_cross


def _router_lpf(acc, E):
    intent = acc.get("intent"); q = acc.get("q", "")
    Z = E.get("zonas_lpf") or {}; rest = E.get("rest") or {}
    ap = E.get("apertura") or {}; pend = E.get("pendientes") or []
    eqs = E.get("equipos") or []
    jugados = E.get("jugados") or []
    equipo = acc.get("equipo")
    if equipo and equipo not in eqs:
        equipo = detectar_equipo(equipo, eqs) or equipo
    c1, c2, c3 = (E.get("camps") or ("", "", ""))
    na, npro = int(E.get("n_anual", 1)), int(E.get("n_prom", 1))
    prev = st.session_state.get("PROMEDIOS") or {}
    anual = lpf_anual_base(Z, ap)

    _domain = None
    if intent in ("copas", "anual"):
        _domain = "copas"
    elif intent in ("promedios", "descenso"):
        _domain = "descenso"
    elif intent in ("necesita", "chances", "depende", "conviene"):
        _obj_gate = _objetivo_lpf(q)
        _domain = "descenso" if _obj_gate == "descenso" else "copas" if _obj_gate in ("libertadores", "sudamericana", "al_menos_sudamericana") else "playoffs"
    elif intent in ("octavos", "cruces", "duelos", "camino", "playoffs", "numero_magico", "puesto_exacto", "previa", "juega"):
        _domain = "playoffs"
    if _domain:
        _gate = _lpf_data_gate(E, _domain)
        if _gate:
            return [_gate]

    if intent in ("octavos", "cruces", "duelos", "camino"):
        return [("md", lpf_cruces_texto(Z))]
    xl, xs = (E.get("intl") or ("", ""))
    if intent == "copas" and not lpf_anual_base(Z, ap):
        return [("warning", "No pude reconstruir la Tabla Anual desde el Apertura fijo y las zonas. Abrí **Datos y auditoría** y tocá **Reconciliar toda la base**.")]
    if intent == "copas":
        if equipo:
            return [("md", lpf_copas_necesita_texto(equipo, Z, rest, ap, (c1, c2, c3), (xl, xs), pend, jugados=jugados)),
                    ("df", lpf_anual_df(Z, ap), "Tabla General 2026")]
        _obj = _objetivo_lpf(q)
        _alive = E.get("copa_arg_vivos") or []
        _updated = E.get("copa_arg_updated", "")
        _source = E.get("copa_arg_source", "")
        if _obj in ("sudamericana", "al_menos_sudamericana"):
            _story = lpf_relato_sudamericana_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), _alive, _updated, _source
            )
        elif _obj == "libertadores":
            _story = lpf_relato_libertadores_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), _alive, _updated, _source
            )
        else:
            _story = (lpf_relato_libertadores_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), _alive, _updated, _source
            ) + "\n\n---\n\n" + lpf_relato_sudamericana_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), _alive, _updated, _source
            ))
        return [("md", _story),
                ("df", lpf_anual_df(Z, ap), "Tabla General 2026 (Apertura + Clausura)")]
    if intent == "anual":
        out = [("df", lpf_anual_df(Z, ap), "Tabla General 2026 (art. 24.1)")]
        if not lpf_anual_base(Z, ap):
            out.insert(0, ("warning", "⚠️ No pude reconstruir la Tabla Anual. Abrí **Datos y auditoría** y reconciliá la base."))
        out.append(("md", "_El 1º de esta tabla es el **Campeón de Liga 2026** (art. 24.2)._"))
        return out
    if intent in ("promedios", "descenso"):
        _text = (lpf_descenso_texto(Z, rest, ap, prev, na, npro, equipo, pend) if equipo
                 else lpf_relato_descenso_texto(Z, rest, ap, prev, na, npro))
        out = [("md", _text)]
        if prev:
            out.append(("df", promedios_df(anual, rest, prev), "Promedios (mínimo = perdiendo todo · máximo = ganando todo)"))
        out.append(("df", lpf_anual_df(Z, ap), "Tabla General 2026"))
        return out
    if intent == "estado_fecha":
        return [("md", lpf_estado_fecha_texto(Z))]
    if intent == "actualizado":
        t, ok = lpf_estado_datos(Z)
        return [("success" if ok else "warning", t)]
    if intent in ("tabla", "hoy", "zonas", "panorama"):
        t, ok = lpf_estado_datos(Z)
        out = [("md", lpf_tabla_zonas_texto(Z))]
        if not ok:
            out.insert(0, ("warning", t))
        return out
    if intent == "conviene":
        if not equipo:
            return [("warning", "Decime el equipo. Ej.: «qué le conviene a River» o «qué le conviene a River para la Libertadores».")]
        obj = _objetivo_lpf(q)
        _scope = _lpf_scope_from_query(q)
        _round = _lpf_round_from_query(q)
        if obj == "playoffs":
            txt, dfc = lpf_otros_resultados_sim(
                equipo, Z, rest, pend, jugados=jugados, scope=_scope, fecha=_round
            )
            if dfc is None:
                return [("info", f"En la ventana elegida no hay partidos de rivales de zona de {equipo} que le muevan la tabla "
                                 f"(o {equipo} no está en zona de playoffs).")]
            return [("md", txt), ("df", dfc, f"{equipo}: qué te conviene en la otra cancha (playoffs)")]
        ctx = _lpf_ctx(Z, rest, ap, (c1, c2, c3), (xl, xs), prev, na, npro)
        if obj == "descenso" and not prev:
            return [("info", "Para el descenso necesito los **promedios** cargados. Tocá «📥 Cargar TODO».")]
        txt, dfc, dfx = lpf_conviene_obj(
            equipo, obj, ctx, pend, jugados, scope=_scope, fecha=_round
        )
        if txt is None:
            return [("info", "No hay partidos pendientes para analizar la otra cancha.")]
        out = [("md", txt)]
        if dfc is not None:
            out.append(("df", dfc, f"{equipo}: la próxima fecha para {_OBJ_NOMBRE[obj]}"))
        if dfx is not None:
            out.append(("df", dfx, f"{equipo}: cruces entre tus rivales que más te convienen"))
        return out
    if intent in ("playoffs", "necesita", "numero_magico", "puesto_exacto", "chances", "depende"):
        if not equipo:
            return [("warning", "Decime el equipo. Ej.: «qué necesita River para los playoffs».")]
        qn = _zlow(q)
        if any(w in qn for w in ("descenso", "descender", "promedio", "bajar", "salvar", "permanencia")):
            return [("md", lpf_descenso_texto(Z, rest, ap, prev, na, npro, equipo, pend))]
        if any(w in qn for w in ("libertadores", "sudamericana", "copa")):
            return [("md", lpf_copas_necesita_texto(equipo, Z, rest, ap, (c1, c2, c3), (xl, xs), pend, jugados=jugados))]
        lab = lpf_zona_de_equipo(equipo, Z)
        out = [("md", lpf_playoffs_texto(equipo, Z, rest, pend, jugados=jugados))]
        if lab:
            out.append(("df", liga_maxmin_df(Z[lab], rest), f"Zona {lab}: puntos máximos posibles"))
        return out
    if intent == "proyeccion":
        base_all = {}
        for b in Z.values(): base_all.update(b)
        return [("df", liga_proyeccion_df(base_all, rest), "Proyección del Clausura si cada uno mantiene su ritmo"),
                ("md", "_Puntos de hoy + puntos por partido × fechas que faltan._")]
    if intent in ("probabilidades", "chances_zona"):
        obj = _objetivo_lpf(q)
        if obj == "playoffs":
            out = []
            for lab in sorted(Z):
                out.append(("df", liga_probabilidades_df(Z[lab], rest, pend, LPF_ZONAS_PLAYOFF,
                                                          fuerza=_fuerza_lpf({name: row for zone in Z.values() for name, row in zone.items()}, jugados)),
                            f"Zona {lab}: chances de entrar a los playoffs (simulación)"))
            out.append(("md", NOTA_MC_LIGA))
            return out
        if obj == "descenso" and not prev:
            return [("info", "Para las chances de descenso necesito los **promedios** cargados. Tocá «📥 Cargar TODO».")]
        ctx = _lpf_ctx(Z, rest, ap, (c1, c2, c3), (xl, xs), prev, na, npro)
        df, nota, tit = lpf_chances_obj(obj, ctx, pend, jugados, destacar=equipo)
        if df is None:
            return [("info", "No pude calcular esas chances.")]
        titulo = {"libertadores": "Chances de Libertadores y Sudamericana (por la anual)",
                  "al_menos_sudamericana": "Chances de obtener al menos una copa (por la anual)",
                  "sudamericana": "Chances de terminar específicamente en Sudamericana (por la anual)",
                  "descenso": "Chances de descenso"}[obj]
        out = []
        if tit:
            out.append(("md", tit))
        out.append(("df", df, titulo))
        out.append(("md", nota))
        return out
    if intent == "comparar":
        e2 = acc.get("equipo2")
        if e2 and e2 not in eqs:
            e2 = detectar_equipo(e2, eqs)
        if not equipo or not e2:
            return [("warning", "Decime los dos equipos. Ej.: «comparar River y Boca».")]
        la, lb = lpf_zona_de_equipo(equipo, Z), lpf_zona_de_equipo(e2, Z)
        base_all = {}
        for b in Z.values(): base_all.update(b)
        out = [("df", liga_comparar_df(equipo, e2, base_all, rest, LPF_ZONAS_PLAYOFF), f"{equipo} (Zona {la}) vs {e2} (Zona {lb})")]
        if la != lb:
            out.append(("info", "Ojo: están en zonas distintas, así que compiten por lugares distintos."))
        return out
    if intent == "relato":
        _obj = _objetivo_lpf(q)
        if _obj == "libertadores":
            return [("md", lpf_relato_libertadores_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), E.get("copa_arg_vivos") or [],
                E.get("copa_arg_updated", ""), E.get("copa_arg_source", "")
            ))]
        if _obj == "sudamericana":
            return [("md", lpf_relato_sudamericana_texto(
                Z, rest, ap, (c1, c2, c3), (xl, xs), E.get("copa_arg_vivos") or [],
                E.get("copa_arg_updated", ""), E.get("copa_arg_source", "")
            ))]
        if _obj == "descenso":
            return [("md", lpf_relato_descenso_texto(Z, rest, ap, prev, na, npro))]
        if equipo:
            lab = lpf_zona_de_equipo(equipo, Z)
            return [("md", lpf_relato_zona_texto(Z, lab, rest))] if lab else [("warning", f"No encuentro a {equipo}.")]
        return [("md", lpf_relato_zona_texto(Z, l, rest)) for l in sorted(Z)]
    if intent == "juega" and not equipo:
        txt, frame = lpf_que_se_juega_fecha(
            Z, pend, apertura=ap, camps=(c1, c2, c3), extras=(xl, xs),
            previous=prev, rest=rest, n_anual=na, n_prom=npro,
        )
        if frame is None:
            return [("info", txt)]
        return [("md", txt), ("df", frame, "Qué se juega cada equipo")]
    if intent in ("previa", "juega"):
        if equipo:
            txt, dfe = lpf_previa_equipo_texto(
                equipo, Z, rest, pend, anual, prev,
                fecha=_lpf_round_from_query(q),
                scope=_lpf_scope_from_query(q, default="next_team_match"),
                objective=_objetivo_lpf(q) or "Playoffs",
            )
            if dfe is not None:
                return [("md", txt), ("df", dfe, f"{equipo}: cómo puede terminar la Fecha")]
        fx, dfp = lpf_previa_fecha_sim(Z, rest, pend, jugados)
        if dfp is None:
            return [("info", "No me quedan partidos pendientes para armar la previa.")]
        return [("df", dfp, f"Previa de la Fecha {fx} — estimación de cada partido"),
                ("md", "_Estimación del modelo (fuerza por puntos + forma reciente si hay resultados + ventaja de localía). No es un pronóstico: no ve lesiones ni bajas._")]
    if intent in ("arbol", "bisagra", "simulador"):
        if not equipo:
            return [("warning", "Decime el equipo. Ej.: «árbol de River» o «partido bisagra de Boca».")]
        txt, dfa = lpf_arbol_sim(equipo, Z, rest, pend, jugados=jugados)
        if dfa is None:
            return [("info", f"No tengo partidos pendientes de {equipo} para armar el árbol.")]
        return [("md", txt), ("df", dfa, f"{equipo}: chances de octavos según el próximo resultado")]
    if intent in ("forma",):
        if not jugados:
            return [("info", "Todavía no hay resultados partido a partido cargados. En el panel, abrí "
                             "**🛠️ Otras formas de cargar → 🥅 Resultados partido a partido**, tocá «Traer resultados LPF 2026» "
                             "(o pegá los tuyos) y volvé a cargar. Con eso se activan forma, rachas y local/visitante.")]
        _poco = max((_stats(eqs, jugados)[e]["pj"] for e in eqs), default=0) <= 1
        if equipo:
            lab = lpf_zona_de_equipo(equipo, Z)
            ult, p5 = forma_equipo(equipo, jugados, 5)
            L = [f"**Forma de {equipo}**",
                 f"Últimos {len(ult) or 0}: **{''.join(ult) or '—'}** ({p5} pts) · Racha: **{racha_equipo(equipo, jugados)}**."]
            if _poco:
                L.append("_Con una sola fecha jugada, la forma todavía dice poco._")
            out = [("md", "\n\n".join(L))]
            if lab:
                out.append(("df", local_visitante_df(Z[lab], jugados), f"Zona {lab}: rendimiento local/visitante"))
            return out
        out = [("df", _lpf_forma_zona_df(Z[lab], jugados), f"Zona {lab}: forma (últimos 5) y racha") for lab in sorted(Z)]
        if _poco:
            out.append(("md", "_Con una sola fecha jugada, la forma todavía dice poco; se afina fecha a fecha._"))
        return out
    if intent in ("localia", "local_visitante"):
        if not jugados:
            return [("info", "Necesito los resultados partido a partido. En el panel: **🛠️ Otras formas de cargar → "
                             "🥅 Resultados partido a partido**, y volvé a cargar.")]
        if equipo:
            lab = lpf_zona_de_equipo(equipo, Z)
            return [("df", local_visitante_df(Z.get(lab, {}), jugados), f"Zona {lab}: local/visitante")]
        return [("df", local_visitante_df(Z[lab], jugados), f"Zona {lab}: local/visitante") for lab in sorted(Z)]
    if intent in ("visual", "mapa", "barras", "puesto"):
        out = []
        for lab in sorted(Z):
            out.append(("df", liga_probabilidades_df(Z[lab], rest, pend, LPF_ZONAS_PLAYOFF,
                                                      fuerza=_fuerza_lpf({name: row for zone in Z.values() for name, row in zone.items()}, jugados)),
                        f"Zona {lab}: chances de entrar a los playoffs (simulación)"))
        out.append(("md", NOTA_MC_LIGA))
        return out
    if intent == "maximos":
        dfs = []
        for lab in sorted(Z):
            dfs.append(("df", liga_maxmin_df(Z[lab], rest), f"Zona {lab}"))
        return dfs or [("info", "Cargá las zonas.")]
    if intent == "calendario":
        if not pend:
            return [("info", "Para la dificultad del calendario pegá el **fixture** («River vs Boca»), no solo «faltan N fechas».")]
        ppg = {e: (anual[e]["pts"] / anual[e]["pj"]) if anual[e].get("pj") else 0.0 for e in anual}
        return [("df", dificultad_fixture_df(eqs, pend, ppg, rest), "Dificultad del fixture restante")]
    if intent == "ficha":
        if not equipo:
            return [("warning", "¿De qué equipo? Ej.: «ficha de River».")]
        lab = lpf_zona_de_equipo(equipo, Z)
        base = Z.get(lab, {})
        return [("md", ficha_liga_texto(equipo, base, rest, pend, LPF_ZONAS_PLAYOFF) if base else f"No encuentro a {equipo}.")]
    return [("md", AYUDA_LPF)]


AYUDA_LPF = """### ⚽ Calculadora LPF 2026 — guía de uso

**Cómo cargar y actualizar los datos**
1. Botón grande **«📥 Cargar TODO»** — trae de una las dos zonas, la Tabla Anual, los promedios, el fixture de las 16 fechas y los resultados de la fecha 1 (datos internos, sirve sin internet).
2. **«🔄 Actualizar a hoy (automático)»** — una vez por fecha: intenta ESPN y FutbolArgentino.com para las tablas. Para resultados consulta primero las notas oficiales de Primera de la LPF y usa ESPN/FutbolArgentino.com como respaldo. Sólo aplica marcadores que reconstruyen exactamente PJ, puntos y goles; si no, conserva la última base válida y queda el pegado manual.
3. En **«🛠️ Otras formas de cargar»**: pegar las tablas de Promiedos, editar el histórico, y **«🥅 Resultados partido a partido»** para pegar/actualizar marcadores a mano.
4. La app te avisa sola si los datos quedaron viejos o si hay una fecha en curso.

---

### 🏆 Playoffs (entran los 8 primeros de cada zona)
- **¿Qué necesita River para los playoffs?** — la cuenta con el **mínimo que asegura** o el **total seguro**, los **mano a mano**, las **opciones** (con cuánto entrás si les ganás a los de arriba, o terminando por encima de tal rival) y el «🔍 por qué»
- **Tabla** — las dos zonas con la línea de clasificación · **Octavos** — los 8 cruces si terminara hoy
- **Relato de la zona** — el panorama escrito, listo para la nota
- **Probabilidades** (o «chances de River») — % de entrar a los playoffs por simulación
- **Proyección** — con cuántos puntos termina cada uno si mantiene el ritmo
- _También:_ ¿quién clasifica hoy? · ¿está eliminado X? · máximos

### 📉 Descenso (bajan 2: uno por promedios y otro por la anual)
- **Descenso** — quiénes se irían hoy por cada tabla, con la regla si el mismo es último en las dos
- **¿Se salva Aldosivi?** — por promedio y por anual, con rango posible, total seguro/mínimo que asegura y **opciones** (mano a mano incluido)
- **Chances de Aldosivi para el descenso** — probabilidad de descender/salvarse por simulación (solo para equipos entre los últimos 6 de promedios o de la anual)
- **¿Qué le conviene a Aldosivi para salvarse?** — qué resultado de la otra cancha lo aleja del descenso
- **Promedios** — la tabla completa con PROMEDIO, mínimo si pierde todo y máximo si gana todo
- _También:_ ¿quién se salva? · ¿quién está en riesgo? · zona de descenso

### 🌎 Copas 2027 (siempre primero la Libertadores)
- **Copas** — cómo quedan las plazas de Libertadores y Sudamericana
- **¿River llega a la Libertadores?** — tu puesto en la tabla **sin campeones**, con total seguro/mínimo que asegura y **opciones**
- **Chances de River para la Libertadores** / **para la Sudamericana** — probabilidad por simulación (tabla de la anual sin campeones), cada copa por separado
- **¿Qué le conviene a River para la Libertadores?** (o para la Sudamericana) — qué hinchar en la otra cancha para esa copa
- **Anual** — la Tabla General 2026 (su 1º es Campeón de Liga)
- _También:_ ¿quiénes van a la Sudamericana?

### 🎯 Previa y escenarios por equipo
- **Previa de River** (o «cómo puede terminar la fecha para River») — su partido y **entre qué puestos puede terminar la fecha**, en playoffs, copas y/o descenso según le corresponda. Rango **exacto** para la fecha.
- **¿Qué le conviene a River?** (o «la otra cancha», «para quién hinchar») — qué resultado de cada partido de sus rivales le sirve, por simulación. Si venías consultando un objetivo, lo conserva. También podés aclarar **«para playoffs»**, **«para Libertadores»**, **«para entrar a las copas»** o **«para salvarse»**.
- **Árbol de River** — cómo cambian sus chances según gane, empate o pierda el próximo; marca el **partido bisagra**
- **Previa de Boca** — toma el próximo partido real por fecha y hora, aunque sea un postergado. **Previa de la fecha** mantiene la jornada oficial.

### 🔎 Por equipo
- **Ficha de River** — puesto, ritmo, DG, rivales que le quedan y dificultad
- **Forma de River** / **racha de Boca** — los últimos 5 y la racha (requiere resultados cargados)
- **De local y de visitante** — rendimiento por condición
- **Comparar River y Boca** — cara a cara · **Calendario** — qué tan bravo es el fixture · **¿Contra quién juega River?**

### 🔴 Control de datos
- **Estado de la fecha** — quién ya jugó y está tomado, y los partidos de estos días (en vivo desde ESPN)
- **¿Está actualizado?** — compara lo cargado con el calendario oficial
- Después de casi cualquier respuesta: **¿por qué?** — te desarma la cuenta paso a paso

---

_Todo se calcula en Python con los datos cargados: los veredictos («ya está», «quedó afuera», puntos que faltan, mejor/peor puesto de la fecha) son **exactos**, y lo que es estimación (probabilidades, árbol, qué conviene, previa por partido) va siempre rotulado como tal. Nada lo escribe una IA por su cuenta._

_La marca es una **línea segura** que ya descuenta los mano a mano. El árbol, las chances y «qué conviene» son **por simulación** (no enumeran marcador por marcador); cuando quedan pocas fechas, se vuelven prácticamente exactos. La previa por equipo (mejor/peor puesto) es exacta para la fecha._"""


def _router_liga_tabla(acc, E):
    intent = acc.get("intent"); equipo = acc.get("equipo"); q = acc.get("q", "")
    base, rest = E["base"], E["rest"]; eqs = E["equipos"]
    z = st.session_state.get("ZONAS") or []
    if equipo and equipo not in eqs:
        equipo = detectar_equipo(equipo, eqs)
    # En modo liga «libertadores/descenso/playoffs» suelen ser NOMBRES DE ZONA, no intents LPF
    if intent in ("copas", "descenso", "playoffs"):
        intent = "necesita" if equipo else "zonas"
    elif intent in ("anual", "octavos"):
        intent = "tabla"
    if intent == "ayuda":
        return [("md", AYUDA_LIGA)]
    if intent in ("tabla", "hoy", "panorama"):
        out = []
        if z:
            out.append(_placa(spec_zonas_df(liga_tabla_df(base), z), "tabla_zonas.png"))
            out.append(("md", tabla_zonas_texto_df(liga_tabla_df(base), z)))
        else:
            out.append(("df", liga_tabla_df(base), "Tabla actual"))
        return out
    if intent == "zonas":
        if not z:
            return [("info", "Configurá las zonas en «🎨 Zonas con nombre» (panel) y volvé a preguntar.")]
        return [_placa(spec_zonas_df(liga_tabla_df(base), z), "tabla_zonas.png"),
                ("md", tabla_zonas_texto_df(liga_tabla_df(base), z))]
    if intent == "maximos":
        return [("df", liga_maxmin_df(base, rest), "Puntos máximos posibles")]
    if intent in ("probabilidades", "chances"):
        df = liga_probabilidades_df(base, rest, E["pendientes"], z)
        out = []
        if equipo:
            fila = df[df["Equipo"] == equipo]
            if len(fila):
                partes = [f"{c.replace(' %','')}: {fila[c].iloc[0]}%" for c in df.columns if c.endswith("%")]
                out.append(("md", f"**¿Cómo viene {equipo}?** (simulación) → " + " · ".join(partes)))
        out += [("df", df, "Chances por zona (cada 100 torneos simulados)"), ("md", NOTA_MC_LIGA)]
        return out
    if intent == "promedios":
        prevP = st.session_state.get("PROMEDIOS") or {}
        kk = int(st.session_state.get("PROM_K", 1))
        if equipo:
            return [("md", promedio_que_necesita_texto(equipo, base, rest, prevP, kk, E["pendientes"])),
                    ("df", promedios_df(base, rest, prevP), "Tabla de promedios (mínimo = perdiendo todo · máximo = ganando todo)")]
        return [("df", promedios_df(base, rest, prevP), "Tabla de promedios (mínimo = perdiendo todo · máximo = ganando todo)"),
                ("md", "_«Solo actual» = sin temporadas previas cargadas (recién ascendidos: es la regla). "
                       "Cargá las previas en el panel «📉 Promedios» y pedí «promedio de X» para el análisis._")]
    if intent == "terceros":
        return [("info", "Ese tablero es para torneos por grupos. En modo liga usá zonas, promedios o chances.")]
    if intent == "ficha":
        if not equipo:
            return [("warning", "¿De qué equipo? Ej.: «ficha de River».")]
        return [("md", ficha_liga_texto(equipo, base, rest, E["pendientes"], z))]
    if intent == "calendario":
        if not E["pendientes"]:
            return [("info", "Para la dificultad del calendario necesito el **fixture** (pegá los partidos «A vs B» en el panel).")]
        ppg = {e: (base[e]["pts"] / base[e].get("pj", 1)) if base[e].get("pj") else 0.0 for e in base}
        return [("df", dificultad_fixture_df(eqs, E["pendientes"], ppg, rest), "Dificultad del fixture restante"),
                ("md", "_«Dificultad» = promedio de puntos por partido de los rivales que le quedan a cada uno: cuanto más alto, más bravo el calendario._")]
    if intent in ("forma", "localia"):
        jugE = E.get("jugados") or []
        if not jugE:
            return [("info", "Para **forma** y **local/visitante** necesito los resultados partido a partido: "
                             "usá «Leer TODO» desde la URL de Wikipedia, importá el JSON del actor o pegá los resultados. "
                             "Con la tabla sola no puedo reconstruirlos.")]
        if intent == "localia":
            return [("df", local_visitante_df(eqs, jugE), "Rendimiento como local y como visitante")]
        out = []
        if equipo:
            ult, p5 = forma_equipo(equipo, jugE)
            out.append(("md", f"**{equipo}** viene {''.join(ult) or '—'} ({p5} pts en los últimos {len(ult)}) · racha: {racha_equipo(equipo, jugE)}."))
        out.append(("df", tabla_forma_df(eqs, jugE), "Tabla de forma (últimos 5: G/E/P)"))
        return out
    if intent == "proyeccion":
        return [("df", liga_proyeccion_df(base, rest), "Proyección a fin de torneo si cada uno mantiene su ritmo"),
                ("md", "_«Proyección (ritmo)» = puntos actuales + puntos por partido × partidos que restan. "
                       "Es la vara clásica para la nota; el techo es ganando todo._")]
    if intent == "comparar":
        e2 = acc.get("equipo2")
        if e2 and e2 not in eqs:
            e2 = detectar_equipo(e2, eqs)
        if not equipo or not e2:
            return [("warning", "Decime los dos equipos. Ej.: «comparar River y Boca».")]
        return [("df", liga_comparar_df(equipo, e2, base, rest, z), f"{equipo} vs {e2}")]
    if intent == "asegurados":
        nn = acc.get("n") or DIRECTO()
        return [("df", liga_aseg_df(base, rest, nn), f"Asegurados / sin chances (top {nn})")]
    if intent in ("duelos", "cruces"):
        return [("md", liga_duelos_texto(base, rest, E["pendientes"], z))]
    if intent in ("necesita", "numero_magico", "puesto_exacto", "conviene", "depende"):
        if not equipo:
            return [("warning", "Decime el equipo. Ej.: «qué necesita River para Libertadores».")]
        return [("md", liga_que_necesita_texto(equipo, base, rest, z, q, E["pendientes"])),
                ("df", liga_maxmin_df(base, rest), "Puntos máximos posibles")]
    if intent == "relato":
        if not equipo:
            return [("info", "En modo liga, contame el equipo y la zona. Ej.: «qué necesita River para Libertadores».")]
        return [("md", liga_que_necesita_texto(equipo, base, rest, z, q or "", E["pendientes"])),
                ("df", liga_maxmin_df(base, rest), "Puntos máximos posibles")]
    return [("info", "Cargaste una **liga por tabla**. Probá: «tabla por zonas», «qué necesita River para Libertadores», "
                     "«máximos», «asegurados top 4». (Para escenarios marcador-a-marcador, cargá un grupo por resultados.)")]


def _explicar_porque(E):
    u = st.session_state.get("ULTIMO") or {}
    equipo = u.get("equipo"); q = u.get("q", ""); intent = u.get("intent")
    if E.get("modo") == "liga_tabla":
        base, rest = E["base"], E["rest"]; z = st.session_state.get("ZONAS") or []
        if equipo:
            eq = detectar_equipo(equipo, E["equipos"]) or equipo
            r = _porque_liga(eq, base, rest, z, q)
            if r:
                return [("md", "🔍 **Por qué:** " + r)]
        return [("info", "Preguntá algo concreto (ej.: «qué necesita River para Libertadores») y después «¿por qué?».")]
    eqs, jug, pen, esc = E["equipos"], E["jugados"], E["pendientes"], E["esc"]
    if esc is None:
        if equipo:
            nn = 1 if u.get("objetivo") == "campeon" else (u.get("n") or DIRECTO())
            return [("md", "🔍 **Por qué:** " + _porque_numero_magico(detectar_equipo(equipo, eqs) or equipo, eqs, jug, pen, nn))]
        return [("info", "Preguntá «número mágico de X» o «qué necesita X» y después «¿por qué?».")]
    if intent == "bisagra":
        r = _porque_bisagra(eqs, jug, pen, esc)
        return [("md", "🔍 **Por qué:** " + r)] if r else [("info", "No quedan partidos para analizar.")]
    if equipo:
        eq = detectar_equipo(equipo, eqs) or equipo
        nn = u.get("n") or DIRECTO()
        return [("md", "🔍 **Por qué:** " + _porque_pasar(eq, eqs, jug, esc, pen, nn))]
    return [("info", "Preguntá algo concreto (ej.: «cómo viene River», «qué necesita River», «partido bisagra») y después «¿por qué?».")]


def ejecutar_accion(acc):
    intent = acc.get("intent")
    equipo = acc.get("equipo")
    objetivo = acc.get("objetivo")
    n = acc.get("n")
    E = st.session_state.ESTADO

    if intent == "porque":
        return _explicar_porque(E)

    # ── MODO LPF 2026 (zonas A/B + anual + promedios + copas) ──
    if E.get("modo") == "lpf2026":
        return _router_lpf(acc, E)

    # ── MODO LIGA POR TABLA (pegaste tabla + fechas) ──
    if E.get("modo") == "liga_tabla":
        return _router_liga_tabla(acc, E)

    eqs, jug, pen, esc = E["equipos"], E["jugados"], E["pendientes"], E["esc"]
    if equipo and equipo not in eqs:
        equipo = detectar_equipo(equipo, eqs)

    # ── TABLA POR ZONAS (sirve por puntos; ideal para ligas) ──
    if intent == "zonas":
        z = st.session_state.get("ZONAS") or []
        if not z:
            return [("info", "Todavía no configuraste zonas. Abrí «🎨 Zonas con nombre» en el panel y elegí un preset (ej.: Liga Argentina), o escribí las tuyas.")]
        return [_placa(spec_zonas(eqs, jug, z), "tabla_zonas.png"), ("md", tabla_zonas_texto(eqs, jug, z))]

    if intent == "ficha":
        if not equipo:
            return [("warning", "¿De qué equipo? Ej.: «ficha de River».")]
        return [("md", ficha_equipo_texto(equipo, eqs, jug, pen))]
    if intent == "forma":
        out = []
        if equipo:
            ult, p5 = forma_equipo(equipo, jug)
            out.append(("md", f"**{equipo}** viene {''.join(ult) or '—'} ({p5} pts en los últimos {len(ult)}) · racha: {racha_equipo(equipo, jug)}."))
        out.append(("df", tabla_forma_df(eqs, jug), "Tabla de forma (últimos 5: G/E/P)"))
        return out
    if intent == "localia":
        return [("df", local_visitante_df(eqs, jug), "Rendimiento como local y como visitante")]
    if intent == "calendario":
        if not pen:
            return [("info", "No quedan partidos por jugar.")]
        ovx = _stats(eqs, jug); ppg = {e: (ovx[e]["pts"] / ovx[e]["pj"]) if ovx[e]["pj"] else 0.0 for e in eqs}
        return [("df", dificultad_fixture_df(eqs, pen, ppg), "Dificultad del fixture restante"),
                ("md", "_«Dificultad» = promedio de puntos por partido de los rivales que quedan: cuanto más alto, más bravo._")]

    if intent == "promedios":
        ovx = _stats(eqs, jug); restx = _restantes(eqs, pen)
        basex = {e: {"pts": ovx[e]["pts"], "pj": ovx[e]["pj"], "dg": ovx[e]["dg"]} for e in eqs}
        prev = st.session_state.get("PROMEDIOS") or {}
        kk = int(st.session_state.get("PROM_K", 1))
        if equipo:
            return [("md", promedio_que_necesita_texto(equipo, basex, restx, prev, kk, pen)),
                    ("df", promedios_df(basex, restx, prev), "Tabla de promedios (mínimo = perdiendo todo · máximo = ganando todo)")]
        return [("df", promedios_df(basex, restx, prev), "Tabla de promedios (mínimo = perdiendo todo · máximo = ganando todo)"),
                ("md", "_«Solo actual» = sin temporadas previas cargadas (recién ascendidos: es la regla). "
                       "Cargá las previas en el panel «📉 Promedios» y pedí «promedio de X» para el análisis._")]

    # ── MODO LIGA (por puntos): cuando hay demasiados partidos para enumerar ──
    if esc is None:
        if intent == "ayuda":
            return [("md", AYUDA_LIGA)]
        if intent == "tabla":
            return [("df", tabla(eqs, jug), "Tabla actual"), ("md", si_terminara_hoy_texto(eqs, jug, pen))]
        if intent in ("hoy", "panorama"):
            return [("md", si_terminara_hoy_texto(eqs, jug, pen)), ("df", tabla(eqs, jug), "Tabla actual")]
        if intent == "maximos":
            return [("df", maximos_minimos(eqs, jug, pen), "Puntos máximos posibles")]
        if intent == "asegurados":
            nn = n or DIRECTO()
            return [("df", clasificado_eliminado(eqs, jug, pen, nn), f"Asegurados / sin chances (top {nn})")]
        if intent == "probabilidades":
            return [("md", "Estimación por simulación (Poisson, 8.000 sorteos) con **fuerza estimada** por el rendimiento de cada equipo."),
                    ("df", probabilidades(eqs, jug, pen, fuerza=fuerza_desde_stats(eqs, jug)), "Probabilidades")]
        if intent == "chances":
            if not equipo:
                return [("warning", "¿De qué equipo? Ej.: «¿cómo viene River?».")]
            pct, dfp = chances_mc(equipo, eqs, jug, pen)
            return [_placa_png(placa_chances_mc_png(equipo, pct), f"chances_{equipo}.png"),
                    ("md", f"**¿Cómo viene {equipo}?** Clasifica en **{round(pct)} de cada 100 torneos simulados** "
                           f"(fuerza estimada por su rendimiento). _Como hay muchas fechas por delante, esto es simulación, no cuenta exacta._"),
                    ("df", dfp, "Probabilidades (simulación)")]
        if intent == "proyeccion":
            ov = _stats(eqs, jug); restx = _restantes(eqs, pen)
            basex = {e: {"pts": ov[e]["pts"], "pj": ov[e]["pj"], "dg": ov[e]["dg"]} for e in eqs}
            return [("df", liga_proyeccion_df(basex, restx), "Proyección si cada uno mantiene su ritmo"),
                    ("md", "_Proyección = puntos actuales + puntos por partido × partidos restantes._")]
        if intent in ("necesita", "numero_magico", "depende", "conviene", "visual", "puesto_exacto"):
            if not equipo:
                return [("warning", "Decime el equipo. Ej.: «número mágico de River» o «qué necesita River».")]
            nn = 1 if objetivo == "campeon" else (n or DIRECTO())
            return [("md", numero_magico_texto(equipo, eqs, jug, pen, nn)),
                    ("df", maximos_minimos(eqs, jug, pen), "Puntos máximos posibles")]
        return [("info", "Es una **liga** con muchas fechas, así que trabajo por puntos. Probá: "
                         "**tabla**, **si terminara hoy**, **número mágico de X**, **máximos**, "
                         "**asegurados** o **probabilidades**.")]

    if intent == "ayuda":
        return [("md", AYUDA_MD)]
    if intent == "tabla":
        return [("df", tabla(eqs, jug), "Tabla actual"),
                ("info", resumen_grupo_texto(eqs, jug, esc, pen))]
    if intent == "panorama":
        return [("info", resumen_grupo_texto(eqs, jug, esc, pen)),
                ("df", panorama(eqs, jug, esc), "Panorama de clasificación")]
    if intent == "probabilidades":
        return [("md", "Probabilidades estimadas por simulación (Poisson, ~8.000 sorteos) con **fuerza estimada** por el rendimiento de cada equipo. Es una estimación, no la cuenta exacta."),
                ("df", probabilidades(eqs, jug, pen, fuerza=fuerza_desde_stats(eqs, jug)), "Probabilidades")]
    if intent == "proyeccion":
        ov = _stats(eqs, jug); restx = _restantes(eqs, pen)
        basex = {e: {"pts": ov[e]["pts"], "pj": ov[e]["pj"], "dg": ov[e]["dg"]} for e in eqs}
        return [("df", liga_proyeccion_df(basex, restx), "Proyección si cada uno mantiene su ritmo"),
                ("md", "_Proyección = puntos actuales + puntos por partido × partidos restantes._")]
    if intent == "maximos":
        return [("df", maximos_minimos(eqs, jug, pen), "Puntos máximos posibles")]
    if intent == "hoy":
        return [("md", si_terminara_hoy_texto(eqs, jug, pen)),
                ("df", tabla(eqs, jug), "Tabla actual")]
    if intent == "depende":
        if equipo:
            cat, msg = en_sus_manos(equipo, esc, pen)
            icon = {"manos": "🟢", "ayuda": "🟡", "ya": "✅", "out": "🔴"}.get(cat, "•")
            return [("md", f"### ¿De qué depende {equipo}?"), ("md", f"{icon} **{equipo}** — {msg}"),
                    ("df", tabla(eqs, jug), "Tabla actual")]
        return [("md", en_sus_manos_texto(eqs, jug, esc, pen)),
                ("df", tabla(eqs, jug), "Tabla actual")]
    if intent == "relato":
        if equipo:
            return [("md", f"### {equipo} · el escenario"),
                    ("md", relato_equipo_texto(equipo, eqs, jug, esc, pen))]
        return [("md", "### El grupo · el escenario"),
                ("md", relato_grupo_texto(eqs, jug, esc, pen))]
    if intent == "visual":
        if not equipo:
            return [("warning", "¿De qué equipo querés la grilla? Probá «grilla de River».")]
        spec = spec_necesita(equipo, esc, pen)
        if not spec:
            return [("info", f"A {equipo} le queda más de un partido, así que la grilla sería enorme. Va el detalle en texto:"),
                    ("md", que_necesita_completo_texto(equipo, esc, pen))]
        return [_placa(spec, f"necesita_{equipo}.png")]
    if intent == "mapa":
        return [_placa(spec_mapa(eqs, esc), "mapa_grupo.png")]
    if intent == "bisagra":
        out = [("md", "### Partidos que más definen"), ("md", partido_bisagra_texto(eqs, jug, pen, esc))]
        png = placa_bisagra_png(eqs, jug, pen, esc)
        if png:
            out.append(_placa_png(png, "partidos_bisagra.png"))
        return out
    if intent == "barras":
        if not equipo:
            return [("warning", "¿De qué equipo? Ej.: «barras de River».")]
        return [_placa_png(barras_puesto_png(equipo, esc), f"barras_{equipo}.png")]
    if intent == "chances":
        if not equipo:
            return [("warning", "¿De qué equipo querés ver las chances? Ej.: «¿cómo viene River?».")]
        return [_placa_png(placa_chances_png(equipo, eqs, jug, esc, pen), f"chances_{equipo}.png"),
                ("md", chances_texto(equipo, eqs, jug, esc, pen))]
    if intent == "arbol":
        if not equipo:
            return [("warning", "¿De qué equipo querés el árbol? Ej.: «árbol de River».")]
        png = placa_arbol_png(equipo, eqs, jug, esc, pen)
        if not png:
            return [("info", f"{equipo} tiene demasiados partidos pendientes para un árbol claro; probá «qué necesita {equipo}».")]
        return [_placa_png(png, f"arbol_{equipo}.png"),
                ("md", f"Árbol de decisión de **{equipo}** según su resultado. Para el detalle escrito, pedí «qué necesita {equipo}».")]
    if intent == "previa":
        lab = ""
        for L2, (e2, _, _) in _tour_grupos().items():
            if set(e2) == set(eqs):
                lab = L2; break
        out = [("md", previa_fecha_texto(eqs, jug, esc, pen))]
        png = placa_previa_fecha_png(eqs, jug, esc, pen, lab)
        if png:
            out.append(_placa_png(png, "previa_fecha.png"))
        return out
    if intent == "juega":
        lab = ""
        for L2, (e2, _, _) in _tour_grupos().items():
            if set(e2) == set(eqs):
                lab = L2; break
        return [_placa_png(placa_que_se_juega_png(eqs, jug, esc, pen, lab), "que_se_juega.png"),
                ("md", que_se_juega_texto(eqs, jug, esc, pen))]
    if intent == "simulador":
        return [("info", "Abrí el panel **🎮 Simulador: ¿qué pasa si…?** (arriba de las sugerencias). "
                         "Elegí el resultado de cada partido que falta y te muestro la tabla resultante, quién clasifica y la previa en prosa.")]
    if intent == "comparar":
        e2 = acc.get("equipo2")
        if not (equipo and e2):
            return [("warning", "Decime los dos equipos. Ej.: «comparar River y Boca».")]
        if e2 not in eqs:
            e2 = detectar_equipo(e2, eqs)
        if not e2 or e2 == equipo:
            return [("warning", "Necesito dos equipos distintos del mismo grupo para comparar.")]
        return [_placa(spec_comparar(equipo, e2, eqs, jug, esc, pen), f"comparar_{equipo}_{e2}.png")]
    if intent == "puesto":
        if not equipo:
            return [("warning", "¿De qué equipo? Ej.: «River puede salir 1º».")]
        puesto = n or 1
        spec = spec_puesto(equipo, esc, pen, puesto)
        if not spec:
            return [("info", f"A {equipo} le queda más de un partido; la grilla sería enorme. Va el detalle en texto:"),
                    ("md", resultados_para_puesto_texto(equipo, esc, pen, ("exacto", puesto)))]
        return [_placa(spec, f"{equipo}_puesto_{puesto}.png")]
    if intent == "asegurados":
        nn = n or DIRECTO()
        return [("df", clasificado_eliminado(eqs, jug, pen, nn), f"Asegurados / sin chances (top {nn})")]
    if intent == "numero_magico":
        if not equipo:
            return [("warning", "¿De qué equipo? Probá: «número mágico de River».")]
        nn = 1 if objetivo == "campeon" else (n or DIRECTO())
        return [("md", numero_magico_texto(equipo, eqs, jug, pen, nn))]

    if not equipo:
        return [("md", "No identifiqué a qué equipo te referís. " + AYUDA_MD)]

    team_pend = sum(1 for p in pen if equipo in p)
    muchos = team_pend >= 2

    if intent == "conviene":
        out = [("md", f"### Qué le conviene a {equipo}"), ("md", mejor_resultado_texto(equipo, esc, pen))]
        co = conviene_otros_texto(equipo, esc, pen)
        if co:
            out.append(("md", co))
        ideal = combo_ideal_texto(equipo, esc, pen)
        if ideal:
            out.append(("md", ideal))
        out.append(("df", tabla(eqs, jug), "Tabla actual"))
        return out

    if intent == "puesto_exacto" and n:
        return [("md", f"### {equipo}: terminar exactamente {n}º"),
                ("md", resultados_para_puesto_texto(equipo, esc, pen, ("exacto", n))),
                ("df", tabla(eqs, jug), "Tabla actual")]

    # intent == "necesita"
    if objetivo == "campeon":
        obj, nn = "campeon", 1
    elif objetivo == "champions":
        obj, nn = "top", 4
    elif objetivo == "descenso":
        obj, nn = "descenso", (n or 1)
    elif objetivo == "tercero":
        obj, nn = "tercero", 3
    else:
        obj, nn = "top", (n or DIRECTO())
    es_default = (obj == "top" and nn == DIRECTO())

    blocks = [("md", f"### ¿Qué necesita {equipo}?")]
    if obj == "tercero":
        if MEJORES_TERCEROS() > 0:
            blocks.append(("md", apartado_terceros_texto(equipo, esc, pen)))
        else:
            blocks.append(("info", "En este torneo los terceros no clasifican (Mejores 3ºs = 0 en el panel)."))
    elif muchos:
        blocks.append(("info", f"A {equipo} le quedan {team_pend} partidos: con tantos por jugar el detalle "
                               f"gol por gol es enorme, así que va el resumen por puntos."))
        blocks.append(("md", necesita_por_resultados_texto(equipo, eqs, jug, pen, nn)))
    else:
        s = situacion(equipo, esc)
        if es_default and s["ya_directo"]:
            blocks.append(("success", f"🟢 {equipo} ya clasificó directo (siempre entre los {DIRECTO()} primeros)."))
        elif es_default and s["eliminado"]:
            blocks.append(("error", f"🔴 {equipo} no llega a zona de clasificación en ningún escenario."))
        else:
            usar_unificado = es_default and MEJORES_TERCEROS() > 0 and s["puede_tercero"] and not s["ya_directo"]
            if usar_unificado:
                blocks.append(("md", que_necesita_completo_texto(equipo, esc, pen)))
                n3, T = s["ntercero"], s["total"]
                blocks.append(("info",
                    f"«3º · depende de otros grupos»: quedar tercero clasifica solo si {equipo} entra "
                    f"entre los {MEJORES_TERCEROS()} mejores terceros del torneo (se compara con los terceros "
                    f"de los otros grupos). {equipo} termina 3º en {n3}/{T} escenarios."))
                # El árbol ya muestra cuándo puede salir 1º (rango «1º-2º»), así que no repetimos el bloque de campeón.
            else:
                blocks.append(("md", que_necesita_texto(equipo, esc, pen, obj, n=nn)))
                if es_default and s["puede_1"] and not s["ya_1"]:
                    blocks += [("md", "---"), ("md", que_necesita_texto(equipo, esc, pen, "campeon"))]
    blocks.append(("df", tabla(eqs, jug), "Tabla actual (para ubicarse)"))
    return blocks


# ─── BLOQUES DE NAVEGACIÓN ────────────────────────────────────────────────────────
def _bloques_listar_grupos():
    gs = _tour_grupos()
    if len(gs) <= 1:
        return [("info", "Tenés cargado un solo grupo. Para tener todos, pegá o importá el torneo "
                         "completo desde el panel lateral (API o pegar texto).")]
    lineas = ["**Grupos cargados:**"]
    for lab, (eqs, _, _) in gs.items():
        lineas.append(f"- **Grupo {lab}**: " + ", ".join(eqs))
    return [("md", "\n".join(lineas))]


def _bloques_ver_grupo(lab):
    gs = _tour_grupos()
    lab = _norm_txt(lab or "").replace("grupo", "").strip().upper()
    if lab not in gs:
        disp = ", ".join(gs) if gs else "—"
        return [("warning", f"No encuentro el Grupo {lab}. Disponibles: {disp}. "
                            "(Si falta, cargá el torneo completo en el panel lateral.)")]
    eqs, jug, pen = gs[lab]
    cargar_estado(eqs, jug, pen)
    return [("success", f"Cargué el **Grupo {lab}**: {', '.join(eqs)}."),
            ("df", tabla(eqs, jug), f"Grupo {lab} — tabla actual"),
            ("info", resumen_grupo_texto(eqs, jug, st.session_state.ESTADO["esc"], pen))]


def _bloques_buscar_equipo(team_q):
    lab, team, datos = _buscar_grupo_de(team_q)
    if not lab:
        gs = _tour_grupos()
        if len(gs) <= 1:
            return [("warning", "Solo tengo un grupo cargado, así que no puedo buscar en otros. "
                                "Cargá el torneo completo (API o pegar) desde el panel lateral.")]
        return [("warning", "No encontré ese equipo en los grupos cargados. ¿Está bien escrito?")]
    eqs, jug, pen = datos
    cargar_estado(eqs, jug, pen)
    comp = [e for e in eqs if e != team]
    return [("success", f"**{team}** está en el **Grupo {lab}**, junto a {', '.join(comp)}."),
            ("info", f"Cambié a ese grupo: ya podés preguntar, por ejemplo «¿qué necesita {team}?»."),
            ("df", tabla(eqs, jug), f"Grupo {lab} — tabla actual")]


# ─── ROUTER POR PALABRAS CLAVE (fallback, sin LLM) ────────────────────────────────
# _parse_kw y _pos_pedida viven ahora en lpf_intents.py
def _llm_parse(q):
    gs = _tour_grupos()
    if gs:
        contexto = "Grupos y equipos del torneo:\n" + "\n".join(f"- Grupo {lab}: {', '.join(d[0])}" for lab, d in gs.items())
    else:
        contexto = "Equipos del grupo cargado: " + ", ".join(st.session_state.ESTADO["equipos"])
    sistema = (
        "Sos un router de intención para una calculadora de escenarios de fútbol.\n" + contexto + "\n\n"
        "Respondé EXCLUSIVAMENTE un objeto JSON (sin texto extra, sin ```), con estas claves:\n"
        '- "intent": uno de [necesita, conviene, tabla, panorama, probabilidades, numero_magico, '
        'asegurados, maximos, puesto_exacto, buscar_equipo, ver_grupo, listar_grupos, depende, hoy, relato, '
        'visual, comparar, puesto, mapa, bisagra, barras, zonas, chances, relato, duelos, porque, simulador, arbol, juega, previa, proyeccion, ficha, forma, calendario, localia, promedios, playoffs, octavos, copas, anual, descenso, ayuda]\n'
        '- "equipo": nombre EXACTO de un equipo (de cualquier grupo) o null\n'
        '- "equipo2": segundo equipo (solo para comparar) o null\n'
        '- "grupo": letra del grupo (para ver_grupo) o null\n'
        '- "objetivo": solo si intent=necesita: [clasificar, campeon, champions, descenso, tercero]; default clasificar\n'
        '- "n": entero o null (top N, descenso N, o el puesto para intent=puesto/puesto_exacto)\n'
        '- "intro": una frase breve en español rioplatense que presente la respuesta, SIN dar números ni resultados.\n'
        "Pistas: 'en qué grupo está X'/'dónde juega X' => buscar_equipo (equipo=X). "
        "'equipos del grupo C'/'grupo C' => ver_grupo (grupo='C'). 'qué grupos hay' => listar_grupos. "
        "'de quién depende X'/'lo tiene en sus manos' => depende. 'si terminara hoy'/'quién pasa hoy' => hoy. "
        "'contame/escribime/relato/para la nota' => relato (equipo si lo nombran, si no el grupo). "
        "'grilla/visual/matriz' => visual (equipo). 'comparar X y Z'/'X vs Z' => comparar (equipo=X, equipo2=Z). "
        "'X puede salir/terminar Nº' => puesto (equipo=X, n=N). 'mapa/mapa de calor/dónde termina cada uno' => mapa. "
        "'promedios'/'promedio de X'/'desciende por promedio' => promedios (equipo=X si lo nombra). 'ficha de X'/'stats de X' => ficha. 'forma'/'racha'/'últimos 5' => forma. 'calendario'/'dificultad del fixture'/'rivales que quedan' => calendario. 'de local'/'de visitante' => localia. 'proyección'/'ritmo'/'a este paso cuánto suma' => proyeccion. 'por qué'/'explicame'/'de dónde sale eso' (a secas, sin equipo) => porque (explica la última respuesta). 'cómo viene X'/'qué chances tiene X'/'está para clasificar X'/'termómetro de X' => chances (equipo=X). 'contame el escenario de X'/'relato de X' => relato (equipo=X); 'relato del grupo' => relato sin equipo. 'playoffs'/'octavos'/'cruces' => octavos. 'copas'/'libertadores'/'sudamericana' => copas. 'anual'/'tabla general' => anual. 'descenso'/'promedios' => descenso. "
        "'campeón'/'ganar el grupo' => objetivo campeon. 'no descender' => descenso."
    )
    body = {"model": st.session_state.LLM_MODEL, "max_tokens": 400,
            "system": sistema, "messages": [{"role": "user", "content": q}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": st.session_state.LLM_KEY,
                               "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    obj = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    return obj, obj.get("intro")


def responder(q):
    usar_llm = st.session_state.LLM_ON and str(st.session_state.LLM_KEY).strip()
    intro = None
    err_note = None
    if usar_llm:
        try:
            acc, intro = _llm_parse(q)
            st.session_state["LLM_ERROR"] = ""
        except Exception as e:
            acc = _parse_kw(q, st.session_state.ESTADO["equipos"])
            st.session_state["LLM_ERROR"] = str(e)[:200]
            err_note = ("info", f"⚠️ El asistente Claude no respondió ({str(e)[:90]}…). Te respondo igual por palabras clave. "
                                "Revisá la API key y el modelo en el panel; o desactivalo (todo funciona por palabras clave: escribí «ayuda»).")
    else:
        acc = _parse_kw(q, st.session_state.ESTADO["equipos"])

    pre = [("md", f"_{intro}_")] if intro else []
    if err_note:
        pre = [err_note] + pre
    acc["q"] = q
    intent = acc.get("intent")

    if intent == "listar_grupos":
        return pre + _bloques_listar_grupos()
    if intent == "ver_grupo":
        return pre + _bloques_ver_grupo(acc.get("grupo"))
    if intent == "buscar_equipo":
        return pre + _bloques_buscar_equipo(acc.get("equipo") or q)

    # Cambio automático de grupo si el equipo no está en el grupo cargado
    cur = st.session_state.ESTADO["equipos"]
    team_intents = {"necesita", "conviene", "numero_magico", "puesto_exacto", "visual", "puesto", "barras", "chances", "arbol", "ficha"}
    ya = acc.get("equipo") and detectar_equipo(acc["equipo"], cur)
    if intent in team_intents and not ya:
        lab, team, datos = _buscar_grupo_de(acc.get("equipo") or q)
        if lab:
            cargar_estado(*datos)
            acc["equipo"] = team
            pre = pre + [("info", f"Cambié al Grupo {lab}, donde juega {team}.")]
        elif st.session_state.get("ultimo_equipo") and not acc.get("equipo"):
            acc["equipo"] = st.session_state["ultimo_equipo"]  # seguir hablando del último equipo

    # Memoria de contexto: recordar el último equipo mencionado
    if acc.get("equipo"):
        st.session_state["ultimo_equipo"] = acc["equipo"]

    if intent != "porque":
        st.session_state["ULTIMO"] = {"intent": intent, "equipo": acc.get("equipo"),
                                      "n": acc.get("n"), "objetivo": acc.get("objetivo"), "q": q}
    return pre + ejecutar_accion(acc)


def render_blocks(blocks, prefix="x"):
    for i, b in enumerate(blocks):
        kind = b[0]
        if kind == "md":
            ui_markdown(b[1])
        elif kind == "placa":
            if b[1]:
                ui_markdown(b[1], unsafe_allow_html=True)
            else:
                st.image(b[2], use_container_width=True)
            st.download_button("Descargar imagen", b[2], file_name=b[3], mime="image/png", key=f"{prefix}_dl{i}")
        elif kind == "df":
            table_title = b[2] if len(b) > 2 and b[2] else "Tabla"
            ui_dataframe(
                b[1], use_container_width=True, hide_index=True,
                export_title=table_title, export_name=table_title,
            )
            if len(b) > 2 and b[2]:
                ui_caption(b[2])
        elif kind == "html":
            ui_markdown(b[1], unsafe_allow_html=True)
        elif kind == "info":
            ui_info(b[1])
        elif kind == "success":
            ui_success(b[1])
        elif kind == "warning":
            ui_warning(b[1])
        elif kind == "error":
            ui_error(b[1])


# ─── MESA DE REDACCIÓN ───────────────────────────────────────────────────────
def _rd_position(base, team):
    df = liga_tabla_df(base)
    hit = df.index[df["Equipo"] == team].tolist()
    return int(hit[0] + 1) if hit else None


def _rd_competition_table(base, rest, cutoff, probability=None):
    probability = probability or {}
    rows = []
    for _, row in liga_tabla_df(base).iterrows():
        team = row["Equipo"]
        pos = int(row["Pos"])
        ceiling = int(row["PTS"]) + 3 * int(rest.get(team, 0))
        if pos <= cutoff:
            status = "Adentro hoy"
        elif ceiling < int(liga_tabla_df(base).iloc[min(cutoff - 1, len(base) - 1)]["PTS"]):
            status = "Muy comprometido"
        else:
            status = "En pelea"
        out = {"Pos": pos, "Equipo": team, "PTS": int(row["PTS"]),
               "PJ": int(row.get("PJ", base.get(team, {}).get("pj", 0))),
               "Techo": ceiling, "Estado": status}
        if team in probability:
            out["Chance estimada"] = f"{probability[team]:.0f}%"
        rows.append(out)
    return pd.DataFrame(rows)


def lpf_estado_hitos(Z, rest, pend, apertura=None, camps=("", "", ""), extras=("", ""), prom=None):
    """Foto EXACTA del estado de cada equipo frente a cada objetivo.
    Devuelve {equipo: {objetivo: 'in'|'out'|'pelea'}} usando solo cuentas exactas
    (techos y mínimos), nunca simulación. Base del detector de hitos."""
    out = {}
    anual = lpf_anual_base(Z, apertura or {})
    try:
        P = lpf_plazas_copas(Z, apertura, camps, extras)
        red = P.get("reducida") or []
        n_lib = int(P.get("n_tabla_lib") or 0)
    except Exception:
        red, n_lib = [], 0
    base_red = {e: anual[e] for e in red if e in anual}
    for lab, base in (Z or {}).items():
        for e in base:
            st_e = {}
            st_e["playoffs"] = _liga_in_out(e, base, rest, _LPF_TOP_OCTAVOS)
            if e in base_red and n_lib:
                st_e["libertadores"] = _liga_in_out(e, base_red, rest, n_lib)
                st_e["sudamericana"] = _liga_in_out(e, base_red, rest, n_lib + 6)
            if anual and e in anual:
                # permanencia por la Anual: 'in' = salvado (no puede ser último)
                st_e["permanencia_anual"] = _liga_in_out(e, anual, rest, max(1, len(anual) - 1))
            out[e] = st_e
    return out

_HITO_NOMBRE = {"playoffs": "los playoffs (octavos)", "libertadores": "la Copa Libertadores",
                "sudamericana": "la Copa Sudamericana", "permanencia_anual": "la permanencia (Tabla Anual)"}

def lpf_detectar_hitos(antes, ahora):
    """Compara dos fotos de lpf_estado_hitos y devuelve los HECHOS nuevos, listos
    para publicar. Solo cambios de estado matemáticos (exactos)."""
    hitos = []
    for e, objs in (ahora or {}).items():
        prev = (antes or {}).get(e, {})
        for obj, val in objs.items():
            old = prev.get(obj)
            if old is None or old == val or val == "pelea":
                continue
            nombre = _HITO_NOMBRE.get(obj, obj)
            if val == "in":
                if obj == "permanencia_anual":
                    txt = f"**{e} se salvó del descenso por la Tabla Anual.** Ya no puede terminar último: la permanencia por esa vía está asegurada."
                    tipo = "bueno"
                else:
                    txt = f"**{e} aseguró {nombre}.** Ya no depende de nadie: matemáticamente no puede quedar afuera."
                    tipo = "bueno"
            else:
                if obj == "permanencia_anual":
                    txt = f"**{e} quedó condenado por la Tabla Anual**: ya no puede escapar del último puesto de esa tabla."
                    tipo = "malo"
                else:
                    txt = f"**{e} quedó eliminado de {nombre}.** Ni ganando todo lo que le queda llega."
                    tipo = "malo"
            hitos.append({"equipo": e, "objetivo": obj, "de": old, "a": val, "tipo": tipo, "texto": txt})
    orden = {"libertadores": 0, "playoffs": 1, "permanencia_anual": 2, "sudamericana": 3}
    hitos.sort(key=lambda h: (orden.get(h["objetivo"], 9), h["equipo"]))
    return hitos

def lpf_hitos_posibles(Z, rest, pend, apertura=None, camps=("", "", ""), extras=("", ""), fecha=None):
    """Anticipa qué hitos PODRÍAN darse en la jornada: para cada equipo en pelea,
    si existe algún resultado de la fecha que lo deje adentro (o afuera) de un objetivo.
    Exacto: prueba el mejor y el peor caso de la jornada."""
    jornada, juegos, atrasados = lpf_jornada_actual(pend or [], forzar=fecha)
    if jornada is None:
        return []
    todos = list(juegos) + [lv for lv, _f in atrasados]
    estado = lpf_estado_hitos(Z, rest, pend, apertura, camps, extras)
    avisos = []
    for lab, base in (Z or {}).items():
        for e in base:
            if estado.get(e, {}).get("playoffs") != "pelea":
                continue
            mio = next((lv for lv in todos if e in lv), None)
            if not mio:
                continue
            # mejor caso: gana el equipo y pierden los rivales de arriba de su zona
            b2 = {x: dict(base[x]) for x in base}
            r2 = dict(rest)
            b2[e]["pts"] = b2[e]["pts"] + 3
            r2[e] = max(0, r2.get(e, 0) - 1)
            for (l, v) in todos:
                for x in (l, v):
                    if x in b2 and x != e:
                        r2[x] = max(0, r2.get(x, 0) - 1)
            if _liga_in_out(e, b2, r2, _LPF_TOP_OCTAVOS) == "in":
                avisos.append(f"**{e}** puede **asegurar los playoffs esta fecha**: le alcanza con ganar y que se den los resultados de arriba.")
    return avisos

def lpf_chequeo_datos(E, annual=None, prom=None):
    """Compatibilidad con la validación anterior usando una única fuente de verdad.

    Ya no compara la tabla importada contra las zonas: primero reconstruye la
    Tabla Anual autoritativa desde Apertura fijo + Clausura actual.
    """
    try:
        report = _lpf_refresh_quality(E)
    except Exception:
        report = (E or {}).get("data_quality") or st.session_state.get("LPF_DATA_QUALITY")
    if not isinstance(report, DataQualityReport):
        return "vacio", ["la base reconciliada de la LPF"], []
    faltan = [issue.message for issue in report.issues]
    detalle = list(report.details)
    nivel = "ok" if report.level == "ok" else "parcial"
    return nivel, faltan, detalle


def _rd_next_round(pend, fecha=None):
    """Jornada en juego + sus partidos, INCLUYENDO los postergados de fechas
    anteriores (se juegan en esta misma ventana y hay que poder cargarlos)."""
    jornada, juegos, atrasados = lpf_jornada_actual(pend or [], forzar=fecha)
    if jornada is None:
        return None, []
    return jornada, list(juegos) + [lv for lv, _f in atrasados]


def _rd_apply_results(E, results):
    """Aplica marcadores y reconstruye Zonas, Anual, Promedios y pendientes.

    La mutación estadística y el cálculo de cambios de puestos viven en
    ``lpf_result_updates``. Streamlit conserva sólo el rebuild y la persistencia.
    """
    before_zones = E.get("zonas_lpf") or {}
    before_annual = lpf_anual_base(before_zones, E.get("apertura") or {})
    zones, played, applied = apply_completed_results(
        before_zones,
        E.get("jugados") or [],
        E.get("pendientes") or [],
        results,
    )
    if not applied:
        return 0

    updated, _report = _lpf_rebuild_state(
        zones,
        played=played,
        annual_direct=E.get("anual_directo") or {},
        opening=E.get("apertura") or {},
        camps=E.get("camps"), intl=E.get("intl"),
        n_anual=E.get("n_anual", 1), n_prom=E.get("n_prom", 1),
    )
    st.session_state.ESTADO = updated
    annual = updated.get("anual_directo") or {}
    changes = table_position_changes(before_zones, before_annual, zones, annual)
    st.session_state.RD_LAST_CHANGES = pd.DataFrame(changes)
    st.session_state.RD_LAST_RESULTS = applied
    return len(applied)

def _rd_tree_dot(team, objective, base, pending):
    next_info = lpf_proximo_partido_equipo(team, pending)
    match = next_info["match"] if next_info else None
    if not match:
        return None
    rival = match[1] if match[0] == team else match[0]
    points = int(base.get(team, {}).get("pts", 0))
    goal = {"Playoffs": "seguir en carrera por los playoffs",
            "Libertadores": "pelear la Libertadores",
            "Al menos Sudamericana": "entrar a las copas",
            "Descenso": "alejarse del descenso"}[objective]
    return f'''digraph {{
      graph [rankdir=LR, bgcolor="transparent", pad="0.2"];
      node [shape=box, style="rounded,filled", fontname="Arial", color="#cbd5e1"];
      start [label="{team}\n{points} puntos", fillcolor="#e2e8f0"];
      win [label="Gana a {rival}\n{points + 3} puntos\nMejor impulso para {goal}", fillcolor="#dcfce7"];
      draw [label="Empata con {rival}\n{points + 1} puntos\nSuma, pero deja pasar una chance", fillcolor="#fef3c7"];
      lose [label="Pierde con {rival}\n{points} puntos\nQueda más atado a otros resultados", fillcolor="#fee2e2"];
      start -> win [label=" G"];
      start -> draw [label=" E"];
      start -> lose [label=" P"];
    }}'''


def _rd_publication(team, objective, mode, exact_text, Z, annual, rest):
    lab = lpf_zona_de_equipo(team, Z)
    source = Z.get(lab, {}).get(team, {}) if objective == "Playoffs" else annual.get(team, {})
    pts = int(source.get("pts", 0))
    ceiling = pts + 3 * int(rest.get(team, 0))
    action = "La previa" if mode == "Previa" else "El nuevo escenario"
    title = f"{team}: {action.lower()} de su pelea por {objective.lower()}"
    deck = (f"Tiene {pts} puntos y un techo de {ceiling}. La cuenta separa lo ya comprobable "
            "de las probabilidades del simulador.")
    return f"# {title}\n\n{deck}\n\n{exact_text}\n\n— Cuentas determinísticas con el fixture LPF 2026; las estimaciones se publican por separado."


def render_chat_workspace(E):
    """Chat guiado/libre embebido dentro de Mesa de redacción."""
    modo = "🤖 con Claude" if (st.session_state.LLM_ON and str(st.session_state.LLM_KEY).strip()) else "🔤 por palabras clave"
    st.subheader(f"Consultas y chat · {modo}")
    ui_caption(
        "Usalo para preguntas excepcionales o para pedir una salida redactada. "
        "Las cuentas siguen saliendo del motor determinístico; el LLM sólo interpreta y redacta."
    )

    grupos = _tour_grupos()
    if len(grupos) > 1:
        ui_caption(
            f"✅ Tenés **{len(grupos)} grupos** cargados ({', '.join(grupos)}). "
            "Podés preguntar por cualquier equipo y el motor cambia de grupo automáticamente."
        )

    if "chat" not in st.session_state:
        st.session_state.chat = [{"role": "assistant", "blocks": [("md", BIENVENIDA)]}]

    catalog_click = _render_chat_explorer(E)
    st.divider()

    for index, msg in enumerate(st.session_state.chat):
        with st.chat_message(msg["role"], avatar="⚽" if msg["role"] == "assistant" else None):
            render_blocks(msg["blocks"], prefix=f"m{index}")

    equipos_chat = E.get("equipos") or []
    jugados_chat = E.get("jugados") or []
    pendientes_chat = E.get("pendientes") or []
    escenarios_chat = E.get("esc")
    if escenarios_chat is not None and pendientes_chat:
        abrir_simulador = st.toggle(
            "Abrir simulador rápido de resultados", value=False, key="newsroom_chat_sim_toggle"
        )
        if abrir_simulador:
            with st.expander("🎮 Simulador rápido: ¿qué pasa si…?", expanded=True):
                fixed = {}
                for index, (local, visitor) in enumerate(pendientes_chat, 1):
                    option = ui_selectbox(
                        f"{local} vs {visitor}",
                        ["— sin definir", f"Gana {local}", "Empate", f"Gana {visitor}"],
                        key=f"newsroom_sim_{index}",
                    )
                    if option == f"Gana {local}":
                        fixed[index] = "L"
                    elif option == "Empate":
                        fixed[index] = "E"
                    elif option == f"Gana {visitor}":
                        fixed[index] = "V"
                if fixed:
                    jugados_sim, _rem = aplicar_resultados(equipos_chat, jugados_chat, pendientes_chat, fixed)
                    ui_dataframe(tabla(equipos_chat, jugados_sim), use_container_width=True, hide_index=True)
                    ui_markdown(
                        previa_condicional_texto(
                            equipos_chat, jugados_chat, pendientes_chat, escenarios_chat, fixed
                        )
                    )
                else:
                    ui_caption("Elegí al menos un resultado para ver el efecto.")

    prompt = st.chat_input("Escribí una pregunta o elegí una opción del explorador…", key="newsroom_chat_input")
    consulta = prompt or catalog_click
    if consulta:
        st.session_state.chat.append({"role": "user", "blocks": [("md", consulta)]})
        try:
            bloques = responder(consulta)
        except Exception as exc:
            bloques = [("error", f"Tuve un problema procesando esa consulta: {exc}")]
        st.session_state.chat.append({"role": "assistant", "blocks": bloques})
        st.rerun()


def render_newsroom(E):
    Z = E.get("zonas_lpf") or {}
    if len(Z) < 2:
        ui_warning("Cargá las dos zonas de la LPF para abrir la mesa de redacción.")
        return
    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    annual = lpf_anual_base(Z, E.get("apertura") or {})
    previous = st.session_state.get("PROMEDIOS") or {}
    teams = sorted(E.get("equipos") or [team for base in Z.values() for team in base])
    c1, c2, c3 = E.get("camps") or ("", "", "")
    xl, xs = E.get("intl") or ("", "")
    _jor, _jue, _atr = lpf_jornada_actual(pending or [])
    _fechas_disp = sorted({f for _lv, f in _lpf_fecha_de(pending or []).items() if f is not None}) if pending else []
    _sel = st.session_state.get("rd_fecha_sel")
    if _sel not in _fechas_disp:
        _sel = None
    next_date, next_games = _rd_next_round(pending, fecha=_sel)
    _jor2, _jue2, _atr2 = lpf_jornada_actual(pending or [], forzar=_sel)
    _etq_jornada = lpf_etiqueta_jornada(_jor2, _atr2)
    _con_atraso = lpf_equipos_con_atraso(pending or [])

    st.subheader("Mesa de redacción")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Datos cargados", f"Fecha {next_date - 1}" if next_date else "Fase terminada")
    m2.metric("Partidos pendientes", len(pending))
    m3.metric("Tabla Anual", f"{len(annual)} equipos")
    m4.metric("Regla", "LPF 2026 oficial")
    _quality = _lpf_refresh_quality(E)
    _niv = "ok" if _quality.level == "ok" else "parcial"
    _faltan = [issue.message for issue in _quality.issues]
    _det = list(_quality.details)
    if _quality.level == "ok":
        ui_success("🟢 **Datos completos y coherentes.** " + " · ".join(_det))
    else:
        _icon = "🔴" if _quality.level == "blocked" else "🟡"
        _label = "Hay cálculos bloqueados" if _quality.level == "blocked" else "Hay advertencias para revisar"
        ui_warning(f"{_icon} **{_label}.** Abrí **Datos y auditoría** antes de publicar.")
        with st.expander("Problemas y datos cargados", expanded=_quality.level == "blocked"):
            for _issue in _quality.issues:
                ui_markdown(f"- **{_issue.domain}:** {_issue.message}")
            for _d in _det:
                ui_caption(_d)
    ui_caption("EXACTO = cuenta determinística y verificable · ESTIMADO = simulación Monte Carlo rotulada como tal")

    report_tab, preview_tab, chat_tab, load_tab, rules_tab = st.tabs(
        ["Informe por equipo", "Previa de la fecha", "Consultas y chat", "Cargar resultados", "Reglas y auditoría"])

    with report_tab:
        col_team, col_obj, col_mode = st.columns([1.4, 1, 0.8])
        team = col_team.selectbox("Equipo", teams, index=teams.index("River Plate") if "River Plate" in teams else 0)
        _sync_lpf_objective_widget("rd_report_objective")
        objective = col_obj.selectbox(
            "Objetivo", _LPF_OBJECTIVE_UI_OPTIONS, key="rd_report_objective",
            on_change=_lpf_objective_widget_changed, args=("rd_report_objective",),
        )
        mode = col_mode.radio("Momento", ["Previa", "Post"], horizontal=True)
        lab = lpf_zona_de_equipo(team, Z)
        _domain = ("playoffs" if objective == "Playoffs" else
                   "copas" if objective in ("Libertadores", "Al menos Sudamericana") else "descenso")
        _gate = _lpf_data_gate(E, _domain)
        if _gate:
            ui_warning(_gate[1])
            st.stop()

        with st.expander("Panorama general de la competencia", expanded=False):
            if objective == "Playoffs":
                ui_markdown(lpf_relato_zona_texto(Z, lab, rest))
            elif objective == "Libertadores":
                ui_markdown(lpf_relato_libertadores_texto(
                    Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                    E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                    E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
                ))
            elif objective == "Al menos Sudamericana":
                ui_markdown(lpf_relato_sudamericana_texto(
                    Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                    E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                    E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
                ))
            else:
                ui_markdown(lpf_relato_descenso_texto(
                    Z, rest, E.get("apertura") or {}, previous, E.get("n_anual", 1), E.get("n_prom", 1)
                ))

        ui_markdown("#### EXACTO · Qué se sabe y qué necesita")
        if objective == "Playoffs":
            exact = lpf_playoffs_texto(team, Z, rest, pending, jugados=E.get("jugados") or [])
            base = Z[lab]
            cutoff = 8
        elif objective in ("Libertadores", "Al menos Sudamericana"):
            exact = lpf_copas_necesita_texto(
                team, Z, rest, E.get("apertura") or {}, (c1, c2, c3), (xl, xs), pending,
                jugados=E.get("jugados") or [],
            )
            allocation = lpf_plazas_copas(Z, E.get("apertura") or {}, (c1, c2, c3), (xl, xs))
            base = {name: annual[name] for name in allocation["reducida"]}
            cutoff = allocation["n_tabla_lib"] + (0 if objective == "Libertadores" else 6)
        else:
            exact = lpf_descenso_texto(Z, rest, E.get("apertura") or {}, previous,
                                       int(E.get("n_anual", 1)), int(E.get("n_prom", 1)), team, pending)
            base = annual
            cutoff = max(1, len(base) - 1)
        ui_markdown(exact)

        with st.expander("🔍 Control rápido: ¿los datos coinciden con la tabla oficial?", expanded=(_niv != "ok")):
            ui_caption("Compará estas 6 líneas con Promiedos. Si no coinciden, los informes van a estar mal: "
                       "cargá los resultados que faltan en la pestaña **Cargar resultados**.")
            _cc1, _cc2 = st.columns(2)
            with _cc1:
                ui_markdown("**Tabla Anual (top 6)**")
                _ord_an = sorted(annual.items(), key=lambda kv: (-kv[1].get("pts", 0), -kv[1].get("dg", 0),
                                                                 -kv[1].get("gf", 0)))
                for _i, (_e, _d) in enumerate(_ord_an[:6], 1):
                    ui_markdown(f"{_i}. {_e} — **{_d.get('pts',0)}** pts ({_d.get('pj',0)} PJ, DG {_d.get('dg',0):+d})")
            with _cc2:
                ui_markdown(f"**{team}**")
                _p_an = 1 + sum(1 for _x, _d in annual.items() if _x != team and
                                (_d.get("pts", 0), _d.get("dg", 0), _d.get("gf", 0)) >
                                (annual.get(team, {}).get("pts", 0), annual.get(team, {}).get("dg", 0),
                             annual.get(team, {}).get("gf", 0)))
                _lab_z = lpf_zona_de_equipo(team, Z)
                _bz = Z.get(_lab_z or "", {})
                _p_z = 1 + sum(1 for _x, _d in _bz.items() if _x != team and
                               (_d.get("pts", 0), _d.get("dg", 0), _d.get("gf", 0)) >
                               (_bz.get(team, {}).get("pts", 0), _bz.get(team, {}).get("dg", 0),
                            _bz.get(team, {}).get("gf", 0)))
                ui_markdown(f"- Anual: **{_p_an}º** con {annual.get(team, {}).get('pts', 0)} pts "
                            f"({annual.get(team, {}).get('pj', 0)} PJ)")
                if _bz:
                    ui_markdown(f"- Zona {_lab_z}: **{_p_z}º** con {_bz.get(team, {}).get('pts', 0)} pts "
                                f"({_bz.get(team, {}).get('pj', 0)} PJ)")
        _domains_by_report = {
            "playoffs": {"playoffs", "data"},
            "copas": {"annual", "data"},
            "descenso": {"promedios", "annual", "data"},
        }
        _relevant_domains = _domains_by_report.get(_domain, {_domain, "data"})
        _relevant_warnings = [issue for issue in _quality.issues
                              if issue.level == "warning" and issue.domain in _relevant_domains]
        _other_blocks = [issue for issue in _quality.issues
                         if issue.level == "blocked" and issue.domain not in _relevant_domains]
        if _relevant_warnings:
            ui_warning("🟡 **Este informe es utilizable, pero tiene estas salvedades:** "
                       + "; ".join(issue.message for issue in _relevant_warnings[:5]))
        if _other_blocks:
            _areas = ", ".join(sorted({issue.domain for issue in _other_blocks}))
            ui_info(f"Hay bloqueos pendientes en otras áreas ({_areas}), pero **no afectan este informe de {objective.lower()}**.")
        if _con_atraso.get(team):
            ui_warning(f"⚠️ **{team} tiene {_con_atraso[team]} partido(s) pendiente(s) de fechas anteriores.** "
                       f"Jugó menos que el resto: su lugar en la tabla se lee con esa salvedad (puede sumar de más) "
                       f"y su promedio se calcula sobre los partidos que le corresponden.")
        _preview_scope_label = st.radio(
            "Alcance de la Previa",
            ["Próximo partido real", "Fecha oficial específica", "Fecha + postergados"],
            horizontal=True,
            key=f"rd_report_preview_scope_{team}",
            help=("Próximo partido real usa la agenda por fecha/hora. Fecha oficial específica permite elegir una "
                  "jornada del fixture. Fecha + postergados amplía esa jornada con atrasados anteriores."),
        )
        _preview_scope = {
            "Próximo partido real": "next_team_match",
            "Fecha oficial específica": "official_round",
            "Fecha + postergados": "extended_window",
        }[_preview_scope_label]
        _preview_round = None
        if _preview_scope in ("official_round", "extended_window") and _fechas_disp:
            _preview_round = st.selectbox(
                "Fecha oficial para la Previa",
                _fechas_disp,
                index=_fechas_disp.index(_jor) if _jor in _fechas_disp else 0,
                format_func=lambda value: f"Fecha {value}",
                key=f"rd_report_preview_round_{team}",
            )
        preview_text, preview_df = lpf_previa_equipo_texto(
            team, Z, rest, pending, annual, previous, fecha=_preview_round,
            scope=_preview_scope, objective=objective,
        )
        if preview_text:
            ui_info(preview_text)
        if preview_df is not None:
            ui_dataframe(preview_df, use_container_width=True, hide_index=True)

        left, right = st.columns([1.25, 1])
        with left:
            ui_markdown("#### Tabla de situación")
            ui_dataframe(_rd_competition_table(base, rest, cutoff), use_container_width=True,
                         hide_index=True, height=460)
        with right:
            ui_markdown("#### Árbol de la próxima decisión")
            dot = _rd_tree_dot(team, objective, annual if objective != "Playoffs" else Z[lab], pending)
            if dot:
                ui_graphviz_chart(dot, use_container_width=True)
            else:
                ui_info("No hay un próximo partido pendiente para armar el árbol.")

        ui_markdown("#### ESTIMADO · Probabilidades por simulación")
        calculate = st.toggle("Calcular ahora (6.000 simulaciones)", key=f"rd_mc_{team}_{objective}")
        if calculate:
            if objective != "Descenso":
                try:
                    chance_payload = {
                        "team": team,
                        "objective": _lpf_service_objective(objective),
                        "simulations": _LPF_PUBLIC_MC_RUNS,
                        "seed": 23,
                    }
                    if objective == "Playoffs":
                        chance_payload["zone"] = lab
                    public_chance = _lpf_service_result("objective_chances", E, **chance_payload)
                    if public_chance.get("resolved"):
                        ui_markdown(f"**{team}:** {public_chance.get('message') or 'objetivo ya resuelto.'}")
                    else:
                        ui_markdown(
                            f"**{team}: {public_chance.get('qualification_percentage', 0)}%** en "
                            f"{public_chance.get('simulations', _LPF_PUBLIC_MC_RUNS)} simulaciones del contrato público."
                        )
                except _LPFServiceContractError as exc:
                    _record_lpf_service_fallback("objective_chances", exc)
                else:
                    ui_caption(
                        "La cifra destacada sale de `objective_chances`; la tabla comparativa completa conserva "
                        "por ahora el simulador contextual para evitar repetir una simulación completa por club."
                    )
            else:
                ui_caption(
                    "La probabilidad de descenso conserva por ahora la ruta de simulación contextual. "
                    "El contrato público de `relegation` ya cubre la foto y los pisos exactos, no esta tabla estimada."
                )
            if objective == "Playoffs":
                probs = liga_probabilidades_df(Z[lab], rest, pending, LPF_ZONAS_PLAYOFF,
                                                fuerza=_fuerza_lpf({name: row for zone in Z.values() for name, row in zone.items()}, E.get("jugados") or []))
                ui_dataframe(probs, use_container_width=True, hide_index=True)
                ui_caption(NOTA_MC_LIGA)
            else:
                ctx = _lpf_ctx(Z, rest, E.get("apertura") or {}, (c1, c2, c3), (xl, xs), previous,
                               int(E.get("n_anual", 1)), int(E.get("n_prom", 1)))
                obj = {"Libertadores": "libertadores", "Al menos Sudamericana": "al_menos_sudamericana",
                       "Descenso": "descenso"}[objective]
                probs, note, headline = lpf_chances_obj(obj, ctx, pending, E.get("jugados") or [], destacar=team)
                if headline:
                    ui_markdown(headline)
                if probs is not None:
                    ui_dataframe(probs, use_container_width=True, hide_index=True)
                ui_caption(note or "Estimación no disponible.")
        else:
            ui_caption("No se mezcla con el bloque exacto: activalo sólo cuando necesites una probabilidad publicable.")

        publishable = _rd_publication(team, objective, mode, exact, Z, annual, rest)
        with st.expander("Texto listo para copiar a la nota", expanded=False):
            st.text_area("Titular + bajada + cuerpo", publishable, height=360, label_visibility="collapsed")
            st.download_button("Descargar .md", publishable.encode("utf-8"),
                               file_name=f"{_norm_club(team).replace(' ', '-')}-{objective.lower()}.md",
                               mime="text/markdown")

    with preview_tab:
        ui_markdown(f"#### {_etq_jornada}" if next_date else "#### No quedan fechas pendientes")
        if _fechas_disp:
            _cs1, _cs2 = st.columns([1, 3])
            with _cs1:
                ui_selectbox("Ver fecha", ["Automático"] + [f"Fecha {f}" for f in _fechas_disp],
                             key="rd_fecha_pick",
                             index=0 if _sel is None else 1 + _fechas_disp.index(_sel),
                             on_change=lambda: st.session_state.__setitem__(
                                 "rd_fecha_sel",
                                 None if st.session_state.get("rd_fecha_pick") == "Automático"
                                 else int(str(st.session_state.get("rd_fecha_pick")).split()[-1])))
            with _cs2:
                if _atr2:
                    ui_info(f"Hay {len(_atr2)} partido(s) postergado(s) de fecha(s) anterior(es). "
                            f"Los incluyo abajo, marcados como **Postergado**, porque se juegan en esta ventana.")
        if next_games:
            ui_markdown("##### Narrativa para la previa")
            _nm1, _nm2 = st.columns([1, 1.35])
            with _nm1:
                _narrative_mode = st.radio(
                    "Alcance del relato",
                    ["Toda la fecha", "Un partido"],
                    horizontal=True,
                    key="rd_preview_narrative_mode",
                )
            with _nm2:
                _narrative_layers = st.multiselect(
                    "Sumar al impacto de la zona",
                    ["Copas", "Descenso"],
                    default=["Copas", "Descenso"],
                    key="rd_preview_narrative_layers",
                    help=("Copas muestra sólo a los equipos que ocupan o están cerca de un cupo por la Tabla Anual. "
                          "Descenso se limita a los últimos puestos de la Anual o de los promedios."),
                )
            _cups_ready, _cups_blocks = _lpf_domain_ready(E, "copas")
            _desc_ready, _desc_blocks = _lpf_domain_ready(E, "descenso")
            if "Copas" in _narrative_layers and not _cups_ready:
                ui_warning("La capa **Copas** no se agrega porque la Tabla Anual está bloqueada: "
                           + "; ".join(issue.message for issue in _cups_blocks[:3]))
            if "Descenso" in _narrative_layers and not _desc_ready:
                ui_warning("La capa **Descenso** no se agrega porque faltan datos consistentes de Anual o promedios: "
                           + "; ".join(issue.message for issue in _desc_blocks[:3]))
            if "Descenso" in _narrative_layers and not previous:
                ui_caption("La capa de descenso mostrará la Tabla Anual. Los promedios aparecerán cuando haya antecedentes válidos cargados.")
            _narrative_match = None
            if _narrative_mode == "Un partido":
                _postponed_lookup = {match: round_number for match, round_number in _atr2}

                def _preview_match_label(match):
                    _post = _postponed_lookup.get(match)
                    _suffix = f" · postergado F{_post}" if _post is not None else ""
                    _when = _lpf_format_datetime(_lpf_match_datetime(match))
                    _time = f" · {_when}" if _when else ""
                    return f"{match[0]} – {match[1]}{_time}{_suffix}"

                _ordered_preview_games = sorted(
                    next_games,
                    key=lambda match: (0, _lpf_match_datetime(match)) if _lpf_match_datetime(match) else (1, _lpf_match_round(match) or 999),
                )
                _narrative_match = ui_selectbox(
                    "Partido",
                    _ordered_preview_games,
                    format_func=_preview_match_label,
                    key="rd_preview_narrative_match",
                )
            _narrative_text = lpf_previa_fecha_narrativa(
                Z,
                rest,
                pending,
                E.get("jugados") or [],
                fecha=_sel,
                partido=_narrative_match,
                apertura=E.get("apertura") or {},
                camps=E.get("camps") or ("", "", ""),
                extras=E.get("intl") or ("", ""),
                previous=previous,
                n_anual=int(E.get("n_anual", 1)),
                n_prom=int(E.get("n_prom", 1)),
                include_cups="Copas" in _narrative_layers and _cups_ready,
                include_relegation="Descenso" in _narrative_layers and _desc_ready,
            )
            ui_markdown(_narrative_text)

            ui_markdown("##### Probabilidades de los partidos")
            date, matches_df = lpf_previa_fecha_sim(Z, rest, pending, E.get("jugados") or [], fecha=_sel)
            if matches_df is not None:
                ui_dataframe(matches_df, use_container_width=True, hide_index=True)
                ui_caption("ESTIMADO · Fuerza por puntos/partido, forma reciente, localía y probabilidad de empate.")
        z1, z2 = st.columns(2)
        for container, lab in zip((z1, z2), sorted(Z)):
            with container:
                ui_markdown(f"##### Zona {lab}")
                ui_dataframe(_rd_competition_table(Z[lab], rest, 8), use_container_width=True,
                             hide_index=True, height=520)
        with st.expander("Cruces de octavos si terminara hoy"):
            ui_markdown(lpf_cruces_texto(Z))

    with chat_tab:
        render_chat_workspace(E)

    with load_tab:
        ui_markdown("#### Carga rápida y recálculo inmediato")
        ui_caption("Marcá sólo los partidos terminados. El marcador actualiza Zona, Tabla Anual, promedios, forma y pendientes.")
        if next_games:
            with st.form("rd_results_form"):
                captured = []
                for index, (local, visitor) in enumerate(next_games):
                    done, label, goals_l, goals_v = st.columns([0.45, 2.2, 0.65, 0.65])
                    checked = done.checkbox("Final", key=f"rd_done_{index}")
                    label.markdown(f"**{local} — {visitor}**")
                    gl = goals_l.number_input("Local", 0, 20, 0, key=f"rd_gl_{index}", label_visibility="collapsed")
                    gv = goals_v.number_input("Visita", 0, 20, 0, key=f"rd_gv_{index}", label_visibility="collapsed")
                    if checked:
                        captured.append((local, visitor, int(gl), int(gv)))
                submitted = st.form_submit_button("Aplicar y recalcular", type="primary", use_container_width=True)
            if submitted:
                _hitos_antes = lpf_estado_hitos(Z, rest, pending, E.get("apertura") or {}, (c1, c2, c3), (xl, xs))
                count = _rd_apply_results(E, captured)
                if count:
                    _E2 = st.session_state.get("ESTADO") or {}
                    _Z2 = _E2.get("zonas_lpf") or Z
                    _r2 = _E2.get("rest") or rest
                    _p2 = _E2.get("pendientes") or []
                    _hitos_ahora = lpf_estado_hitos(_Z2, _r2, _p2, _E2.get("apertura") or {}, (c1, c2, c3), (xl, xs))
                    st.session_state["RD_HITOS"] = lpf_detectar_hitos(_hitos_antes, _hitos_ahora)
                    ui_success(f"Se aplicaron {count} resultados. Tablas, informes y simulaciones quedaron recalculados.")
                    st.rerun()
                else:
                    ui_warning("No marcaste partidos terminados o esos resultados ya estaban cargados.")
        else:
            ui_success("No quedan partidos pendientes.")
        _hitos = st.session_state.get("RD_HITOS") or []
        if _hitos:
            ui_markdown("#### 🏁 Hitos de esta carga (noticias)")
            for _h in _hitos:
                (st.success if _h["tipo"] == "bueno" else st.error)(_h["texto"])
            ui_caption("EXACTO · Son cambios matemáticos de estado, no probabilidades. Cada uno se puede verificar en el informe del equipo.")
        changes = st.session_state.get("RD_LAST_CHANGES")
        if isinstance(changes, pd.DataFrame) and not changes.empty:
            ui_markdown("#### Qué cambió con la última carga")
            ui_dataframe(changes, use_container_width=True, hide_index=True)
        _posibles = lpf_hitos_posibles(Z, rest, pending, E.get("apertura") or {}, (c1, c2, c3), (xl, xs), fecha=_sel)
        if _posibles:
            with st.expander("🔮 Qué se puede definir en esta fecha", expanded=False):
                for _a in _posibles:
                    ui_markdown("- " + _a)
                ui_caption("EXACTO · Se puede dar si se combinan los resultados indicados.")

    with rules_tab:
        ui_markdown("""
#### Reglas confirmadas para 2026

- Dos zonas de 15, 16 fechas y ocho clasificados por zona (arts. 14–17).
- Desempate de zona: DG, GF, mano a mano, fair play y sorteo (art. 16).
- Tabla General: sólo las fases de zonas del Apertura y Clausura (art. 24).
- Dos descensos: último promedio y último de la Anual; si coincide, baja el siguiente peor de la Anual (Estatuto AFA, art. 93).
- Un empate en una posición de descenso obliga a partido desempate (art. 26.2).
- Libertadores: campeones de Apertura, Clausura y Copa Argentina, más tres por la Tabla General. Si Apertura y Clausura tienen el mismo campeón, se libera un lugar por tabla. La plaza duplicada de Copa Argentina se reasigna por esa Copa, no automáticamente por la Anual (art. 27).
- Sudamericana: los seis mejores de la Tabla General que no tengan plaza en Libertadores (art. 28).

#### Cómo leer las cuentas

**Mínimo que asegura:** es el **menor puntaje alcanzable** que asegura el objetivo pase lo que pase. Sólo se muestra cuando el motor exacto puede comprobarlo sobre el fixture completo. Antes de ese tramo no se publica un número aproximado como si fuera el mínimo exacto: se muestran por separado el corte actual, la proyección, el total seguro y los puntajes condicionados.

**Rango de una fecha:** es exacto por puntos y respeta los partidos entre rivales. Si hay igualdad, abre el intervalo porque el marcador futuro cambia DG/GF y todavía pueden intervenir mano a mano, fair play o sorteo.

**Probabilidad:** siempre aparece bajo el rótulo ESTIMADO. Usa Monte Carlo sobre el fixture real; no decide ni alimenta una cuenta exacta.
""")



def _lpf_refresh_quality(E):
    """Revalida una sesión vieja delegando toda la lógica al estado puro LPF."""
    opening, authoritative, report = refresh_lpf_quality_state(
        E.get("zonas_lpf") or {},
        annual_imported=E.get("anual_importada") or {},
        annual_direct=E.get("anual_directo") or {},
        opening_candidates=(
            E.get("apertura") or {},
            st.session_state.get("LPF_APERTURA") or {},
            globals().get("LPF_APERTURA_BASE_2026") or {},
        ),
        promedios=st.session_state.get("PROMEDIOS") or {},
        fixture=LPF_FIXTURE,
        played=E.get("jugados") or [],
        source_issues=st.session_state.get("PROM_SOURCE_ISSUES") or [],
        opening_rounds=LPF_APERTURA_PJ,
    )
    if opening:
        E["apertura"] = opening
        E["anual_directo"] = authoritative
        st.session_state.LPF_APERTURA = opening
        st.session_state.LPF_ANUAL = authoritative
    E["data_quality"] = report
    st.session_state.LPF_DATA_QUALITY = report
    return report


def render_data_audit(E):
    """Panel único para verificar Zonas, Anual, Promedios y fixture."""
    import json
    ui_markdown("## Datos y auditoría")
    report = _lpf_refresh_quality(E)
    icon = {"ok": "🟢", "warning": "🟡", "blocked": "🔴"}[report.level]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estado", f"{icon} {report.level.upper()}")
    c2.metric("Partidos pendientes", sum(r.status == "scheduled" for r in report.match_records))
    c3.metric("Resultados explícitos", sum(r.status == "played" for r in report.match_records))
    c4.metric("Sin confirmar", sum(r.status == "unconfirmed" for r in report.match_records))
    ui_caption("Una cuenta publicable requiere que el dominio correspondiente no tenga bloqueos. "
               "Si faltan marcadores, la aplicación no adivina qué partido se jugó: lo deja sin confirmar hasta completar la fuente.")

    if report.issues:
        issue_rows = [{
            "Nivel": issue.level,
            "Área": issue.domain,
            "Problema": issue.message,
            "Cómo corregir": issue.suggestion or "Revisar la carga",
        } for issue in report.issues]
        ui_dataframe(pd.DataFrame(issue_rows), use_container_width=True, hide_index=True)
    else:
        ui_success("Las zonas, la Tabla Anual, los promedios y el fixture pasan los controles principales.")

    zones = E.get("zonas_lpf") or {}
    annual = report.authoritative_annual or E.get("anual_directo") or {}
    previous = st.session_state.get("PROMEDIOS") or {}
    control = []
    for lab, base in zones.items():
        for team, row in base.items():
            ar = annual.get(team, {})
            prev = previous.get(team)
            if isinstance(prev, (tuple, list)) and len(prev) >= 2:
                prev_label = f"{prev[0]} pts / {prev[1]} PJ"
            elif isinstance(prev, dict):
                prev_label = f"{prev.get('pts', prev.get('tp', 0))} pts / {prev.get('pj', prev.get('tj', 0))} PJ"
            else:
                prev_label = "Falta"
            control.append({
                "Equipo": team, "Zona": lab,
                "Zona PTS": int(row.get("pts", 0)), "Zona PJ": int(row.get("pj", 0)),
                "Anual PTS": int(ar.get("pts", 0)) if ar else None,
                "Anual PJ": int(ar.get("pj", 0)) if ar else None,
                "Previo promedios": prev_label,
                "Anual esperada PJ": LPF_APERTURA_PJ + int(row.get("pj", 0)),
            })
    with st.expander("Control equipo por equipo", expanded=report.level != "ok"):
        ui_dataframe(pd.DataFrame(control), use_container_width=True, hide_index=True, height=520)
    with st.expander("Detalle técnico de la foto"):
        for detail in report.details:
            ui_markdown("- " + detail)
        ui_markdown(f"- Apertura fijo reconstruido: **{len(report.opening_snapshot)} equipos**")
        ui_markdown(f"- Tabla Anual autoritativa: **{len(annual)} equipos**")

    with st.expander("Contrato público usado por Streamlit", expanded=False):
        capabilities = (_lpf_service_capabilities().get("result") or {})
        try:
            public_snapshot = _lpf_service_snapshot(E)
            snapshot_schema = public_snapshot.get("snapshot_schema_version", "—")
            trace = public_snapshot.get("traceability") or {}
            source_trace = trace.get("source") or {}
            coverage_trace = trace.get("coverage") or {}
            quality_trace = trace.get("quality") or {}
            ui_success(
                f"Contrato público v{capabilities.get('public_service_version', '—')} activo · "
                f"snapshot schema {snapshot_schema} · DataProvider current v{capabilities.get('data_provider_contract_version', '—')}."
            )
            ui_markdown(
                f"**Snapshot ID:** `{trace.get('snapshot_id', '—')}` · "
                f"**Fuente:** {source_trace.get('name') or 'sin identificar'}"
            )
            _fresh_ref = source_trace.get("data_as_of") or source_trace.get("updated_at")
            if _fresh_ref:
                try:
                    import datetime as _dt
                    _parsed = _dt.datetime.fromisoformat(str(_fresh_ref).replace("Z", "+00:00"))
                    if _parsed.tzinfo is None:
                        _parsed = _parsed.replace(tzinfo=_dt.timezone.utc)
                    _age_h = max(
                        0.0,
                        (_dt.datetime.now(_dt.timezone.utc) - _parsed.astimezone(_dt.timezone.utc)).total_seconds() / 3600.0,
                    )
                    ui_caption(f"Fuente actualizada: {_fresh_ref} · antigüedad aproximada: {_age_h:.1f} h.")
                except Exception:
                    ui_warning(f"La fuente declaró un timestamp que no pude interpretar: {_fresh_ref}")
            else:
                ui_warning("La fuente no informó un timestamp verificable; la antigüedad de los datos es desconocida.")
            _last_round = coverage_trace.get("last_confirmed_round")
            _fixture_round = coverage_trace.get("fixture_through_round")
            ui_caption(
                f"Cobertura: {coverage_trace.get('played_match_count', 0)} resultados confirmados · "
                f"{coverage_trace.get('pending_match_count', 0)} pendientes · "
                f"fixture hasta fecha {_fixture_round if _fixture_round is not None else '—'} · "
                f"última fecha con resultados confirmados {_last_round if _last_round is not None else '—'}."
            )
            if not quality_trace.get("complete", False):
                ui_warning(
                    "La foto tiene datos incompletos o bloqueos: "
                    + ", ".join(quality_trace.get("blocked_domains") or ["revisar auditoría"])
                )
            _source_warnings = list(source_trace.get("warnings") or [])
            if _source_warnings:
                ui_caption("Trazabilidad: " + " | ".join(_source_warnings[:4]))
        except _LPFServiceContractError as exc:
            _record_lpf_service_fallback("audit_snapshot", exc)
            ui_warning(f"No se pudo construir el snapshot público: {exc}")
        ui_markdown(
            "**Rutas principales migradas:** Previa · Últimas fechas/definición · Puntos por objetivo · "
            "Descenso exacto · cifra destacada de chances para Playoffs/Copas."
        )
        ui_caption(
            "Excepciones deliberadas de esta etapa: la matriz de rival clave sigue usando el helper exacto directo "
            "y las tablas comparativas completas de probabilidades conservan el simulador contextual."
        )
        fallbacks = list(st.session_state.get("LPF_PUBLIC_SERVICE_FALLBACKS") or [])
        if fallbacks:
            ui_warning("Hubo rutas que necesitaron fallback de compatibilidad en esta sesión.")
            ui_dataframe(pd.DataFrame(fallbacks), use_container_width=True, hide_index=True)
        else:
            ui_success("No se registraron fallbacks del contrato público en esta sesión.")

    col_a, col_b = st.columns(2)
    if col_a.button("🔄 Reconciliar toda la base", type="primary", use_container_width=True):
        state, new_report = _lpf_rebuild_state(
            zones,
            played=E.get("jugados") or [],
            annual_direct=E.get("anual_directo") or st.session_state.get("LPF_ANUAL") or {},
            opening=E.get("apertura") or {},
            camps=E.get("camps"), intl=E.get("intl"),
            n_anual=E.get("n_anual", 1), n_prom=E.get("n_prom", 1),
        )
        st.session_state.ESTADO = state
        ui_success(f"Base reconciliada: {new_report.level}.")
        st.rerun()
    snapshot = {
        "zones": zones,
        "annual": annual,
        "opening": report.opening_snapshot,
        "previous_averages": previous,
        "played": E.get("jugados") or [],
        "pending": E.get("pendientes") or [],
    }
    col_b.download_button(
        "⬇️ Descargar respaldo JSON", json.dumps(snapshot, ensure_ascii=False, indent=2),
        file_name="lpf_snapshot_auditado.json", mime="application/json", use_container_width=True,
    )


def _render_point_ladder(team, base, rest, pending, cutoff, title):
    current = int(base[team].get("pts", 0))
    ceiling = current + 3 * int(rest.get(team, 0))
    table = liga_tabla_df(base)
    current_cutoff = int(table.iloc[min(cutoff, len(table)) - 1]["PTS"])
    ui_markdown(f"### {title}")
    with st.spinner("Resolviendo el fixture completo…"):
        exact = point_ladder(base, pending, team, cutoff, max_rows=8, max_matches=110)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Puntos actuales", current)
    c2.metric("Corte actual", current_cutoff)
    c3.metric("Techo", ceiling)
    c4.metric("Mínimo que asegura", exact.get("guarantee") if exact.get("available") else "No calculado")
    if not exact.get("available"):
        ui_warning(exact.get("reason") or "No se pudo ejecutar el motor exacto.")
        ui_info("No se publica un mínimo aproximado como si fuera exacto. El mínimo que asegura será el menor puntaje alcanzable que el motor compruebe suficiente pase lo que pase.")
        return
    ui_markdown(
        f"**Mínimo todavía posible:** {exact.get('minimum_possible')} · "
        f"**Mínimo que asegura:** {exact.get('guarantee')}"
    )
    rows = []
    for row in exact.get("rows", []):
        rows.append({
            "Puntos finales": row.final_points,
            "Situación": row.status,
            "¿Puede entrar?": "Sí" if row.can_qualify else "No",
            "¿También puede quedar afuera?": "Sí" if row.can_fail else "No",
            "Un camino posible": "; ".join(row.example[:4]) if row.example else "No necesita ayuda",
        })
    ui_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    ui_caption("Los caminos mostrados son ejemplos suficientes, no necesariamente las únicas combinaciones. "
               "El motor no inventa marcadores: los empates en puntos se abren según desempate favorable o adverso.")


def _render_exact_next_round_conditionals(team, base, rest, pending):
    """Matriz exacta de qué tiene que pasar en la próxima fecha.

    Las frecuencias son combinatorias: no usan el modelo probabilístico.
    """
    jornada, juegos, _atrasados = lpf_jornada_actual(pending or [])
    if jornada is None or not juegos:
        ui_info("No hay una fecha oficial pendiente para construir condicionales exactos.")
        return
    report = next_round_conditionals(base, rest, juegos, team, 8, max_other_matches=8)
    ui_markdown("#### Qué tiene que pasar esta fecha · EXACTO")
    team_left = int(rest.get(team, 0))
    if team_left <= 4:
        ui_success(
            f"Modo definición: a {team} le quedan {team_left} partidos. Esta vista prioriza condiciones simples, gráficos y narrativa."
        )
    else:
        ui_info(
            f"Esta vista ya está disponible porque {team} entró en la ventana exacta de {VENTANA_EXACTA} partidos. "
            "A partir de 4 partidos restantes se marca como modo definición, cuando los condicionales suelen ser más decisivos."
        )
    ui_caption(
        "Ubicación: Visualizaciones → Últimas fechas → Condicionales de un equipo. "
        "Las condiciones describen la próxima fecha oficial y no mezclan postergados salvo que formen parte de esa fecha."
    )
    if not report.get("available"):
        ui_warning(report.get("reason") or "No se pudieron enumerar los condicionales de la fecha.")
        return

    branches = report["branches"]
    rows = []
    for branch in branches:
        total = max(1, int(branch["total_combinations"]))
        rows.append({
            "Rama": branch["result_label"],
            "PTS tras la fecha": int(branch["final_points_after_round"]),
            "Combinaciones ajenas": total,
            "Asegura playoffs": int(branch["season_in"]),
            "Sigue en carrera": int(branch["season_pelea"]),
            "Queda eliminado": int(branch["season_out"]),
            "Termina la fecha adentro": int(branch["round_safe"]),
            "Empate en la línea": int(branch["round_tiebreak"]),
            "Termina afuera": int(branch["round_out"]),
            "Condición exacta simple": branch.get("sufficient_condition") or "Requiere combinar más de dos resultados",
        })
    matrix = pd.DataFrame(rows)
    ui_dataframe(matrix, use_container_width=True, hide_index=True)

    season_chart = pd.DataFrame([
        {
            "Rama": branch["result_label"],
            "Asegura playoffs": 100.0 * branch["season_in"] / max(1, branch["total_combinations"]),
            "Sigue en carrera": 100.0 * branch["season_pelea"] / max(1, branch["total_combinations"]),
            "Queda eliminado": 100.0 * branch["season_out"] / max(1, branch["total_combinations"]),
        }
        for branch in branches
    ]).set_index("Rama")
    ui_markdown("##### Cómo cambia la definición según su propio resultado")
    st.bar_chart(season_chart)
    ui_caption(
        "Frecuencia combinatoria, NO probabilidad: cada combinación de resultados ajenos cuenta una vez. "
        "El gráfico muestra en cuántas combinaciones cada rama asegura, mantiene abierta o termina la pelea."
    )

    round_chart = pd.DataFrame([
        {
            "Rama": branch["result_label"],
            "Adentro sin desempate": 100.0 * branch["round_safe"] / max(1, branch["total_combinations"]),
            "Empatado en la línea": 100.0 * branch["round_tiebreak"] / max(1, branch["total_combinations"]),
            "Afuera al cierre": 100.0 * branch["round_out"] / max(1, branch["total_combinations"]),
        }
        for branch in branches
    ]).set_index("Rama")
    ui_markdown("##### Dónde termina la próxima fecha")
    st.bar_chart(round_chart)
    ui_caption("También es frecuencia combinatoria. Una igualdad en la línea no se presenta como clasificación asegurada.")

    ui_markdown("##### Narrativa exacta de la fecha")
    for branch in branches:
        total = max(1, int(branch["total_combinations"]))
        label = branch["result_label"]
        if branch["season_in"] == total:
            text = f"**{label}: asegura los playoffs pase lo que pase en las otras canchas.**"
        elif branch["season_in"]:
            text = (
                f"**{label}: puede asegurar los playoffs esta fecha** en {branch['season_in']} de {total} combinaciones "
                "de resultados ajenos."
            )
        elif branch["season_out"] == total:
            text = f"**{label}: queda eliminado pase lo que pase en las otras canchas.**"
        elif branch["round_safe"]:
            text = (
                f"**{label}: todavía no puede asegurar la clasificación**, pero termina la fecha dentro del top 8 sin "
                f"depender de desempate en {branch['round_safe']} de {total} combinaciones ajenas."
            )
        elif branch["round_tiebreak"]:
            text = (
                f"**{label}: no hay una combinación que lo deje adentro sin desempate**, aunque puede terminar igualado "
                f"en la línea en {branch['round_tiebreak']} de {total} combinaciones."
            )
        else:
            text = f"**{label}: termina la fecha fuera del top 8 en todas las combinaciones de las otras canchas.**"
        if branch.get("sufficient_condition") and branch["sufficient_condition"] != "No depende de otros resultados":
            target = "asegurar los playoffs" if branch["target"] == "season_in" else "terminar la fecha adentro sin desempate"
            text += f" Condición simple suficiente para **{target}**: **{branch['sufficient_condition']}**."
        elif branch.get("sufficient_condition") == "No depende de otros resultados":
            text += " **No depende de nadie.**"
        elif branch.get("necessary_condition"):
            text += (
                f" En todos los caminos favorables aparece esta condición necesaria: **{branch['necessary_condition']}**; "
                "por sí sola no alcanza para garantizar el objetivo."
            )
        ui_markdown("- " + text)

    branch_labels = [branch["result_label"] for branch in branches]
    selected_label = ui_selectbox(
        "Rama para medir qué otra cancha pesa más", branch_labels, key=f"radar_exact_branch_{team}"
    )
    selected = next(branch for branch in branches if branch["result_label"] == selected_label)
    lever_rows = []
    for lever in selected.get("levers", []):
        outcomes = lever.get("outcomes") or []
        if not outcomes:
            continue
        best = max(outcomes, key=lambda item: item["share"])
        worst = min(outcomes, key=lambda item: item["share"])
        lever_rows.append({
            "Partido": lever["match"],
            "Objetivo medido": lever["target"],
            "Resultado más favorable": best["label"],
            "Frecuencia favorable": round(float(best["share"]), 1),
            "Resultado menos favorable": worst["label"],
            "Frecuencia menos favorable": round(float(worst["share"]), 1),
            "Brecha combinatoria": round(float(lever["spread"]), 1),
        })
    if lever_rows:
        leverage = pd.DataFrame(lever_rows)
        ui_markdown(f"##### Las otras canchas que más pesan · {selected_label.lower()}")
        ui_dataframe(leverage, use_container_width=True, hide_index=True)
        st.bar_chart(leverage.set_index("Partido")[["Brecha combinatoria"]])
        ui_caption(
            "Brecha combinatoria = cuánto cambia la frecuencia de caminos favorables entre el mejor y el peor resultado de esa cancha. "
            "Es una sensibilidad exacta de combinaciones, no una probabilidad."
        )


def _definition_objective_context(E, objective, zone=None):
    """Resuelve sesión/proveedores y delega el contexto a la capa pura."""
    Z = E.get("zonas_lpf") or {}
    estado = st.session_state.get("ESTADO") or {}
    opening = E.get("apertura") or estado.get("apertura") or st.session_state.get("LPF_APERTURA") or {}
    direct_annual = estado.get("anual_directo") or st.session_state.get("LPF_ANUAL") or {}
    camps = E.get("camps") or ("", "", "")
    extras = E.get("intl") or ("", "")
    replacement = st.session_state.get("LPF_COPA_ARG_REEMPLAZO", "")
    return _editorial_objective_context(
        Z, objective=objective, zone=zone, opening=opening, direct_annual=direct_annual,
        opening_rounds=LPF_APERTURA_PJ, camps=camps, extras=extras,
        copa_replacement=replacement, playoff_cutoff=_LPF_TOP_OCTAVOS,
    )


def _definition_state_cell(branch):
    """Celda visual corta para matrices exactas, sin exponer frecuencias como probabilidades."""
    if not branch:
        return ("—", "#e5e7eb")
    state = branch_state(branch)
    colors = {"green": "#1b5e20", "yellow": "#f9a825", "red": "#b71c1c"}
    labels = {
        "Asegura": "ASEGURA",
        "Queda eliminado": "ELIMINADO",
        "Puede asegurar": "PUEDE ASEGURAR",
        "Puede quedar eliminado": "PUEDE QUEDAR AFUERA",
        "Sigue abierto": "SIGUE ABIERTO",
        "Sigue dependiendo": "DEPENDE",
    }
    return (labels.get(state["label"], str(state["label"]).upper()), colors[state["signal"]])


def _definition_fill_milp_matrix(rows, base, rest, current_games, pending, cutoff):
    """Completa G/E/P con MILP cuando la enumeración 3^N supera el límite.

    El informe completo de condicionales sigue necesitando enumeración para poder
    explicar otras canchas y construir el árbol. La matriz semáforo no: si la
    enumeración corta no está disponible, resolvemos sólo si cada rama asegura,
    elimina o deja abierto el objetivo usando todo el fixture pendiente.
    """
    out = []
    used_solver = []
    all_pending = _lpf_dedupe_scenario_games(pending or [])
    current_games = _lpf_dedupe_scenario_games(current_games or [])
    for raw in rows or []:
        row = dict(raw)
        report = dict(row.get("_report") or {})
        team = str(row.get("Equipo") or "")
        if not report.get("available") and team in base:
            own = next((match for match in current_games if team in match), None)
            if own is not None:
                solver_report = exact_objective_result_states(
                    base, rest, all_pending, team, own, int(cutoff)
                )
                if solver_report.get("available"):
                    report = solver_report
                    row["_report"] = report
                    by_result = {str(branch.get("result")): branch for branch in report.get("branches", [])}
                    row["Si gana"] = branch_cell(by_result.get("G") or {})
                    row["Si empata"] = branch_cell(by_result.get("E") or {})
                    row["Si pierde"] = branch_cell(by_result.get("P") or {})
                    used_solver.append(team)
        out.append(row)
    return out, used_solver


def _definition_general_matrix_spec(rows, team_focus, objective_label):
    """Grilla tipo Mundial: equipos en filas, G/E/P en columnas."""
    row_headers, cells = [], []
    for row in rows or []:
        team = str(row.get("Equipo") or "")
        report = row.get("_report") or {}
        branches = {str(b.get("result")): b for b in report.get("branches", [])} if report.get("available") else {}
        pts = row.get("PTS", "—")
        prefix = "★ " if team == team_focus else ""
        row_headers.append(f"{prefix}{team} · {pts} pts")
        cells.append([
            _definition_state_cell(branches.get("G")),
            _definition_state_cell(branches.get("E")),
            _definition_state_cell(branches.get("P")),
        ])
    return {
        "titulo": f"Qué pasa si gana, empata o pierde · {objective_label}",
        "col_headers": ["Gana", "Empata", "Pierde"],
        "row_headers": row_headers,
        "cells": cells,
        "corner": "Equipo ↓ / resultado →",
        "leyenda": [("#1b5e20", "objetivo cerrado a favor"), ("#f9a825", "sigue condicionado"), ("#b71c1c", "objetivo cerrado en contra")],
        "footer": "★ = equipo principal. Los comparadores sólo aparecen si los agregaste. Estados matemáticos exactos; no son probabilidades.",
    }


def _definition_key_matrix_spec(team_focus, key_match, key_team, key_report, objective_label):
    """Doble entrada por PARTIDO ajeno, no por un segundo equipo seleccionado."""
    home, away = key_match
    cells_by_code = {(c["own_result"], c["key_result"]): c for c in key_report.get("cells", [])}
    # key_rival_matrix expresa G/E/P desde la óptica de key_team. Convertimos a
    # desenlaces naturales del partido: gana local / empate / gana visitante.
    if key_team == home:
        columns = [(f"Gana {home}", "G"), ("Empatan", "E"), (f"Gana {away}", "P")]
    else:
        columns = [(f"Gana {home}", "P"), ("Empatan", "E"), (f"Gana {away}", "G")]
    row_headers, matrix_cells = [], []
    for own_code, own_label in (("G", "Gana"), ("E", "Empata"), ("P", "Pierde")):
        row_headers.append(own_label)
        matrix_cells.append([_definition_state_cell(cells_by_code.get((own_code, key_code))) for _label, key_code in columns])
    return {
        "titulo": f"{team_focus} vs la otra cancha · {objective_label}",
        "col_headers": [label for label, _code in columns],
        "row_headers": row_headers,
        "cells": matrix_cells,
        "corner": f"{team_focus} ↓ / {home}–{away} →",
        "leyenda": [("#1b5e20", "objetivo cerrado a favor"), ("#f9a825", "depende de lo demás"), ("#b71c1c", "objetivo cerrado en contra")],
        "footer": f"Filas = resultado de {team_focus}. Columnas = resultado de {home}–{away}. Los demás partidos quedan abiertos y se enumeran exactamente.",
        "_columns": columns,
    }


def _definition_decisive_matches(report):
    """Ranking exacto de otras canchas por cuánto cambian los caminos favorables."""
    best_by_match = {}
    affected = {}
    for branch in (report or {}).get("branches", []):
        branch_label = str(branch.get("result_label") or "")
        for lever in branch.get("levers", []):
            outcomes = list(lever.get("outcomes") or [])
            if not outcomes:
                continue
            high = max(outcomes, key=lambda item: (int(item.get("success", 0)), str(item.get("label", ""))))
            low = min(outcomes, key=lambda item: (int(item.get("success", 0)), str(item.get("label", ""))))
            delta = int(high.get("success", 0)) - int(low.get("success", 0))
            total = max(int(item.get("total", 0) or 0) for item in outcomes)
            match = str(lever.get("match") or "")
            if delta > 0:
                affected.setdefault(match, set()).add(branch_label)
            score = (delta / total) if total else 0.0
            candidate = {
                "Partido": match,
                "Se nota más si": branch_label,
                "Más favorable": str(high.get("label") or "—"),
                "Menos favorable": str(low.get("label") or "—"),
                "Caminos que cambian": delta,
                "Combinaciones por desenlace": total,
                "_score": score,
            }
            current = best_by_match.get(match)
            if current is None or (candidate["_score"], delta, match) > (current["_score"], current["Caminos que cambian"], match):
                best_by_match[match] = candidate
    rows = []
    for match, item in best_by_match.items():
        if item["Caminos que cambian"] <= 0:
            continue
        out = dict(item)
        out["Ramas afectadas"] = len(affected.get(match, set()))
        rows.append(out)
    rows.sort(key=lambda item: (-item["_score"], -item["Caminos que cambian"], item["Partido"]))
    for idx, item in enumerate(rows, 1):
        item["Orden"] = idx
    return rows


def _definition_tree_dot(team, objective_label, report):
    """Árbol corto: sólo abre condiciones que cambian el estado matemático."""
    if not report or not report.get("available"):
        return None
    points = int(report.get("branches", [{}])[0].get("proof", {}).get("team_points", 0) or 0)
    lines = [
        'digraph {',
        'graph [rankdir=LR, bgcolor="transparent", pad="0.2", nodesep="0.28", ranksep="0.45"];',
        'node [shape=box, style="rounded,filled", fontname="Arial", color="#cbd5e1"];',
        f'start [label="{team}\\n{objective_label}", fillcolor="#e2e8f0"];',
    ]
    for idx, branch in enumerate(report.get("branches", [])):
        state_total = max(1, int(branch.get("total_combinations", 0) or 0))
        inside = int(branch.get("season_in", 0) or 0)
        outside = int(branch.get("season_out", 0) or 0)
        label = str(branch.get("result_label", ""))
        pts = int(branch.get("final_points_after_round", points) or points)
        bid = f"b{idx}"
        if inside == state_total:
            text, fill = f"{label}\\n{pts} pts\\nASEGURA", "#dcfce7"
        elif outside == state_total:
            text, fill = f"{label}\\n{pts} pts\\nELIMINADO", "#fee2e2"
        else:
            text, fill = f"{label}\\n{pts} pts\\nSIGUE ABIERTO", "#fef3c7"
        lines.append(f'{bid} [label="{text}", fillcolor="{fill}"];')
        lines.append(f'start -> {bid} [label=" {branch.get("result", "")}"];')
        condition = str(branch.get("sufficient_condition") or "").strip()
        if inside != state_total and outside != state_total and condition and condition != "No depende de otros resultados":
            safe = condition.replace('"', "'")
            cid = f"c{idx}"
            lines.append(f'{cid} [label="{safe}\\n→ condición suficiente", fillcolor="#dcfce7"];')
            lines.append(f'{bid} -> {cid};')
    lines.append('}')
    return "\n".join(lines)


def _definition_guarantee(base, pending, team, cutoff, rest):
    return _editorial_definition_guarantee(
        base, pending, team, cutoff, rest, exact_window=VENTANA_EXACTA, max_rows=4, max_matches=110
    )


def _definition_guarantee_round(team, pending, current, guarantee):
    return _editorial_guarantee_round_label(
        team, pending, LPF_FIXTURE, current, guarantee
    )


def _lpf_definition_package(E, objective, zone, team, selected_teams, round_no, *,
                            base, rest, games, pending, cutoff):
    """Paquete de Últimas fechas a través de ``lpf_services.definition``.

    El fallback conserva sesiones legacy; queda registrado en auditoría para que
    no pueda convertirse en una dependencia invisible.
    """
    try:
        return _lpf_service_result(
            "definition", E,
            team=team,
            objective=_lpf_service_objective(objective),
            zone=zone,
            round=round_no,
            selected_teams=list(selected_teams or [team]),
            exact_window=VENTANA_EXACTA,
        )
    except _LPFServiceContractError as exc:
        _record_lpf_service_fallback("definition", exc)
        if team not in base:
            return {
                "available": False,
                "definition_needed": False,
                "reason": (
                    f"{team} no forma parte de la tabla reducida de este objetivo y el servicio no pudo resolver su vía directa."
                ),
                "_fallback": True,
            }
        report = next_round_conditionals(base, rest, games, team, cutoff, max_other_matches=8)
        guarantee, ladder = _definition_guarantee(base, pending, team, cutoff, rest)
        current = int((base.get(team) or {}).get("pts", 0))
        guarantee_round = _definition_guarantee_round(team, pending, current, guarantee)
        return {
            "available": bool(report.get("available")),
            "fight_zone": fight_zone(base, rest, team, cutoff, radius=2),
            "matrix": all_teams_matrix(
                base, rest, games, list(selected_teams or [team]), cutoff, max_other_matches=8
            ),
            "report": report,
            "guarantee": guarantee,
            "ladder": ladder,
            "guarantee_round_label": guarantee_round,
            "clock": definition_clock(
                report, current_points=current, guarantee=guarantee,
                guarantee_round_label=guarantee_round,
            ),
            "_fallback": True,
        }


def _radar_add_suggested_comparators(state_key, suggestions, allowed):
    """Callback seguro: actualiza el multiselect antes del rerun de Streamlit."""
    allowed_set = {str(name) for name in allowed or []}
    current = [
        str(name) for name in st.session_state.get(state_key, [])
        if str(name) in allowed_set
    ]
    additions = [str(name) for name in suggestions or [] if str(name) in allowed_set]
    st.session_state[state_key] = list(dict.fromkeys(current + additions))


def _radar_clear_comparators(state_key):
    """Callback seguro para vaciar comparadores sin mutar el widget después de crearlo."""
    st.session_state[state_key] = []


def _definition_rank_map_spec(base, games, teams, cutoff, objective_label, team_focus):
    """Mapa exacto del rango de puesto tras la fecha para principal/comparadores."""
    row_headers, cells = [], []
    for team in teams or []:
        bounds = scenario_rank_bounds(base, games, team)
        prefix = "★ " if team == team_focus else ""
        row_headers.append(prefix + str(team))
        if not bounds.get("available"):
            cells.append([("—", "#e5e7eb")] * 4)
            continue
        best = int(bounds["best_rank"])
        worst = int(bounds["worst_rank"])
        pmin = int(bounds["points_min"])
        pmax = int(bounds["points_max"])
        if worst <= int(cutoff):
            status_color = "#1b5e20"
        elif best > int(cutoff):
            status_color = "#b71c1c"
        else:
            status_color = "#f9a825"
        cells.append([
            (str(pmin), "#eef1e8"),
            (str(pmax), "#eef1e8"),
            (f"{best}º", status_color),
            (f"{worst}º", status_color),
        ])
    return {
        "titulo": f"Mapa de puestos después de esta fecha · {objective_label}",
        "col_headers": ["Puntos mín.", "Puntos máx.", "Mejor puesto", "Peor puesto"],
        "row_headers": row_headers,
        "cells": cells,
        "corner": "Equipo ↓ / rango exacto →",
        "leyenda": [
            ("#1b5e20", "queda dentro del corte en todo el rango"),
            ("#f9a825", "puede quedar dentro o fuera"),
            ("#b71c1c", "queda fuera del corte en todo el rango"),
        ],
        "footer": "Rango matemático de la fecha por puntos. Contempla desempate favorable/adverso cuando los puntos no alcanzan para resolverlo.",
    }


def _definition_compare_spec(base, rest, rows, team_focus, comparator, objective_label):
    """Cara a cara tipo Mundial usando la misma matriz exacta G/E/P ya calculada."""
    table = liga_tabla_df(base).set_index("Equipo")
    by_team = {str(row.get("Equipo")): row for row in rows or []}
    neutral = "#eef1e8"

    def metrics(team):
        row = by_team.get(team) or {}
        report = row.get("_report") or {}
        branches = {str(b.get("result")): b for b in report.get("branches", [])} if report.get("available") else {}
        pos = int(table.loc[team, "Pos"]) if team in table.index else None
        pts = int((base.get(team) or {}).get("pts", 0))
        left = int(rest.get(team, 0))
        return {
            "pos": f"{pos}º" if pos is not None else "—",
            "pts": str(pts),
            "left": str(left),
            "ceiling": str(pts + 3 * left),
            "G": _definition_state_cell(branches.get("G")),
            "E": _definition_state_cell(branches.get("E")),
            "P": _definition_state_cell(branches.get("P")),
        }

    a, b = metrics(team_focus), metrics(comparator)
    return {
        "titulo": f"Cara a cara · {team_focus} vs {comparator} · {objective_label}",
        "col_headers": [team_focus, comparator],
        "row_headers": ["Posición actual", "Puntos", "PJ por jugar", "Techo", "Si gana", "Si empata", "Si pierde"],
        "cells": [
            [(a["pos"], neutral), (b["pos"], neutral)],
            [(a["pts"], neutral), (b["pts"], neutral)],
            [(a["left"], neutral), (b["left"], neutral)],
            [(a["ceiling"], neutral), (b["ceiling"], neutral)],
            [a["G"], b["G"]],
            [a["E"], b["E"]],
            [a["P"], b["P"]],
        ],
        "corner": "Dato ↓ / equipo →",
        "leyenda": [
            ("#1b5e20", "objetivo cerrado a favor"),
            ("#f9a825", "sigue condicionado"),
            ("#b71c1c", "objetivo cerrado en contra"),
        ],
        "footer": "Comparación exacta de la fecha. Las filas G/E/P usan el mismo motor de la matriz principal.",
    }


def _definition_editorial_report_text(E, objective, team, zone):
    """Informe largo que acompaña al tablero visual de Últimas fechas."""
    if objective == "Descenso":
        return ""
    return _lpf_editorial_need_text(E, team, objective, zone)


def _cup_visual_context(E):
    """Contexto único de Copas para visuales exactos y estimados de Streamlit."""
    Z = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    return _lpf_ctx(
        Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
        E.get("intl") or ("", ""), st.session_state.get("PROMEDIOS") or {},
        int(E.get("n_anual", 1)), int(E.get("n_prom", 1)),
    )


def _cup_probability_package(E, objective, team):
    """Una sola corrida comparativa de Copas para heatmap/tabla; sigue siendo ESTIMADO."""
    ctx = _cup_visual_context(E)
    code = "libertadores" if objective == "Libertadores" else "al_menos_sudamericana"
    probs, note, headline = lpf_chances_obj(
        code, ctx, E.get("pendientes") or [], E.get("jugados") or [],
        n=_LPF_PUBLIC_MC_RUNS, seed=23, destacar=team,
    )
    return {
        "rows": probs.to_dict("records") if isinstance(probs, pd.DataFrame) else [],
        "note": note or "",
        "headline": headline or "",
        "simulations": _LPF_PUBLIC_MC_RUNS,
    }


def _resolved_objective_gep_spec(team, objective_label, message="Objetivo ya resuelto"):
    """Matriz G/E/P informativa cuando el objetivo ya está cerrado a favor."""
    label = "YA CLASIFICADO" if "libert" in str(objective_label).lower() else "OBJETIVO CUMPLIDO"
    return {
        "titulo": f"Qué pasa si gana, empata o pierde · {objective_label}",
        "col_headers": ["Gana", "Empata", "Pierde"],
        "row_headers": [f"★ {team}"],
        "cells": [[(label, "#1b5e20"), (label, "#1b5e20"), (label, "#1b5e20")]],
        "corner": "Equipo ↓ / resultado →",
        "leyenda": [("#1b5e20", "objetivo ya cerrado a favor")],
        "footer": f"{message}. El resultado de la próxima fecha no modifica este objetivo.",
    }


def _cup_definition_visual_package(E, objective, team):
    """Paquete exacto de una fila G/E/P para Copas, compartido con el radar."""
    ctx = _definition_objective_context(E, objective, None)
    if not ctx or not ctx.get("base") or int(ctx.get("cutoff") or 0) <= 0:
        return {"available": False, "reason": "No hay una tabla/corte válido para este objetivo."}
    pending = E.get("pendientes") or []
    current_round, games, _postponed = lpf_jornada_actual(pending)
    base = ctx["base"]
    rest = E.get("rest") or {}
    try:
        package = _lpf_definition_package(
            E, objective, None, team, [team], current_round,
            base=base, rest=rest, games=games or [], pending=pending, cutoff=int(ctx["cutoff"]),
        )
    except Exception as exc:
        return {"available": False, "reason": str(exc), "context": ctx}
    return {
        "available": True, "context": ctx, "package": package, "round": current_round,
        "games": list(games or []), "pending": list(pending or []),
    }


def _cup_cut_metrics(ctx, team):
    """Cortes de hoy en la tabla reducida, sin confundirlos con proyección final."""
    annual = ctx.get("anual") or {}
    reduced = [name for name in ctx.get("reducida") or [] if name in annual]
    n_lib = int(ctx.get("n_lib") or 0)
    lib_team = reduced[n_lib - 1] if n_lib and len(reduced) >= n_lib else None
    sud_index = n_lib + 6 - 1
    sud_team = reduced[sud_index] if sud_index >= 0 and len(reduced) > sud_index else None
    annual_order = [name for name in ctx.get("orden") or [] if name in annual]
    team_pos = annual_order.index(team) + 1 if team in annual_order else None
    return {
        "team_points": int((annual.get(team) or {}).get("pts", 0)),
        "team_position": team_pos,
        "lib_cut_points": int((annual.get(lib_team) or {}).get("pts", 0)) if lib_team else None,
        "lib_cut_team": lib_team,
        "sud_cut_points": int((annual.get(sud_team) or {}).get("pts", 0)) if sud_team else None,
        "sud_cut_team": sud_team,
    }


def _render_radar_estimated_visuals(E, objective, lab, team_focus, ctx, Z, rest, pending):
    """Visuales ESTIMADOS independientes de la enumeración exacta de otras canchas."""
    ui_markdown("### ESTIMADO · visual de chances")
    ui_caption(
        f"Este bloque recupera el termómetro visual del Mundial, pero usa el contrato público `objective_chances` con {_LPF_PUBLIC_MC_RUNS:,} simulaciones. "
        "No modifica ninguna conclusión exacta de arriba. El impacto Monte Carlo sigue separado como ESTIMADO. Para Copas suma además un mapa comparativo rojo→amarillo→verde."
    )
    chance_cache_key = f"radar_chance_visual_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}"
    cup_map_cache_key = f"radar_cup_probability_map_{objective}_{team_focus}"
    if st.button(
        f"Calcular visual de chances · {_LPF_PUBLIC_MC_RUNS:,} simulaciones",
        key=f"radar_chance_button_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}",
        use_container_width=True,
    ):
        try:
            chance_payload = {
                "team": team_focus,
                "objective": _lpf_service_objective(objective),
                "simulations": _LPF_PUBLIC_MC_RUNS,
                "seed": 23,
            }
            if objective == "Playoffs":
                chance_payload["zone"] = lab
            st.session_state[chance_cache_key] = _lpf_service_result("objective_chances", E, **chance_payload)
        except _LPFServiceContractError as exc:
            _record_lpf_service_fallback("objective_chances", exc)
            ui_warning("No pude calcular la estimación por la frontera pública; el fallo quedó registrado en auditoría.")
        if objective in ("Libertadores", "Al menos Sudamericana"):
            try:
                st.session_state[cup_map_cache_key] = _cup_probability_package(E, objective, team_focus)
            except Exception as exc:
                st.session_state.pop(cup_map_cache_key, None)
                ui_warning(f"No pude construir el mapa comparativo de Copas: {exc}")

    chance_result = st.session_state.get(chance_cache_key) or {}
    if chance_result:
        if chance_result.get("resolved"):
            ui_markdown(f"**{team_focus}:** {chance_result.get('message') or 'objetivo ya resuelto.'}")
        else:
            pct = float(chance_result.get("qualification_percentage", 0.0) or 0.0)
            st.image(
                placa_chances_mc_png(
                    team_focus, pct,
                    nota=f"ESTIMADO · {int(chance_result.get('simulations', _LPF_PUBLIC_MC_RUNS)):,} simulaciones · {ctx['label']}",
                ),
                use_container_width=True,
            )
            ui_caption(
                f"{pct:.1f}% en {int(chance_result.get('simulations', _LPF_PUBLIC_MC_RUNS)):,} simulaciones. "
                "Es una estimación del modelo, no una garantía matemática."
            )

    if objective in ("Libertadores", "Al menos Sudamericana"):
        cup_map = st.session_state.get(cup_map_cache_key) or {}
        cup_rows = list(cup_map.get("rows") or [])
        if cup_rows:
            ui_markdown("#### Mapa de probabilidades de Copas · escala de color")
            ui_markdown(
                _html_tabla(
                    cup_probability_heatmap_spec(
                        cup_rows,
                        active_objective=objective,
                        focus_team=team_focus,
                        simulations=int(cup_map.get("simulations", _LPF_PUBLIC_MC_RUNS)),
                    )
                ),
                unsafe_allow_html=True,
            )
            if cup_map.get("headline"):
                ui_markdown(cup_map["headline"])
            ui_caption(cup_map.get("note") or "Mapa comparativo del mismo Monte Carlo de Copas.")
            with st.expander("Ver probabilidades de Copas en tabla", expanded=False):
                ui_dataframe(pd.DataFrame(cup_rows), use_container_width=True, hide_index=True)

    ui_markdown("#### ESTIMADO · impacto de otras canchas")
    ui_caption(
        "Se calcula sólo a demanda. La barra compara cuánto cambia la chance estimada entre el mejor y el peor desenlace de cada partido ajeno; "
        "no convierte ese partido en una condición matemática obligatoria."
    )
    other_cache_key = f"radar_estimated_other_cache_{objective}_{team_focus}"
    if st.button(
        "Calcular impacto estimado de otras canchas",
        key=f"radar_estimated_other_{objective}_{team_focus}",
        use_container_width=True,
    ):
        try:
            if objective == "Playoffs":
                other_text, other_frame = lpf_otros_resultados_sim(
                    team_focus, Z, rest, pending, jugados=E.get("jugados") or [], scope="official_round"
                )
                other_crosses = None
            else:
                cup_ctx = _cup_visual_context(E)
                cup_objective = "libertadores" if objective == "Libertadores" else "al_menos_sudamericana"
                other_text, other_frame, other_crosses = lpf_conviene_obj(
                    team_focus, cup_objective, cup_ctx, pending, E.get("jugados") or [], scope="official_round"
                )
            st.session_state[other_cache_key] = {
                "text": other_text or "",
                "rows": other_frame.to_dict("records") if isinstance(other_frame, pd.DataFrame) else [],
                "crosses": other_crosses.to_dict("records") if isinstance(other_crosses, pd.DataFrame) else [],
            }
        except Exception as exc:
            st.session_state.pop(other_cache_key, None)
            ui_warning(f"No pude calcular el impacto estimado de otras canchas: {exc}")

    other_result = st.session_state.get(other_cache_key) or {}
    if other_result.get("text"):
        ui_markdown(other_result["text"])
    other_rows = list(other_result.get("rows") or [])
    if other_rows:
        other_frame = pd.DataFrame(other_rows)
        if {"Partido", "Diferencia"} <= set(other_frame.columns):
            impact = other_frame[["Partido", "Diferencia"]].copy()
            impact["Impacto (pp)"] = pd.to_numeric(
                impact["Diferencia"].astype("string").str.replace(" pp", "", regex=False).str.replace(",", ".", regex=False),
                errors="coerce",
            )
            impact = impact.dropna(subset=["Impacto (pp)"])
            if not impact.empty:
                st.bar_chart(impact.set_index("Partido")[["Impacto (pp)"]])
        with st.expander("Ver detalle del impacto de otras canchas", expanded=False):
            ui_dataframe(other_frame, use_container_width=True, hide_index=True)
    other_crosses = list(other_result.get("crosses") or [])
    if other_crosses:
        with st.expander("Cruces futuros entre competidores de Copas", expanded=False):
            ui_dataframe(pd.DataFrame(other_crosses), use_container_width=True, hide_index=True)
    ui_caption("ESTIMADO · diferencia entre el mejor y el peor desenlace de cada partido ajeno. No es una prueba exacta de clasificación.")



def render_definition_radar(E):
    """Visuales periodísticos exactos para el tramo abierto y la definición."""
    Z = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    if not Z:
        ui_warning("Cargá las zonas.")
        return

    ui_markdown("## Últimas fechas · tablero de definición")
    ui_caption(
        "EXACTO = cuentas matemáticas con puntos y fixture. Los semáforos, matrices, árbol, zona de pelea y reloj "
        "no usan probabilidades. Las estimaciones Monte Carlo siguen fuera de este bloque."
    )
    ui_caption(
        "🔍 ¿Por qué? está dentro de este mismo tablero: debajo de la matriz G/E/P, dentro de Otra cancha clave · doble entrada "
        "y en el resumen exacto de G/E/P. La otra cancha se elige como partido completo, no como segundo equipo."
    )
    ui_caption(
        "Visuales tipo Mundial visibles en esta pantalla: grilla G/E/P · mapa de puestos tras la fecha · cara a cara · "
        "doble entrada · árbol · partidos bisagra · visual de chances · reloj. En Copas se suma el mapa de probabilidades "
        "rojo→amarillo→verde y la otra cancha estimada en esta misma pantalla. No quedan escondidos detrás del chat."
    )

    ui_markdown("### Configurá el tablero")
    ui_caption(
        "Todas las decisiones del análisis están juntas acá arriba. Elegir un equipo no abre una vista distinta ni termina el flujo: "
        "sólo fija el protagonista. El resultado completo aparece más abajo, en la sección de resultados."
    )
    _sync_lpf_objective_widget("radar_objective")
    objective = ui_selectbox(
        "Objetivo", _LPF_OBJECTIVE_UI_OPTIONS, key="radar_objective",
        on_change=_lpf_objective_widget_changed, args=("radar_objective",),
    )
    if objective == "Descenso":
        ui_info(
            "Para descenso no mezclo este semáforo con una simplificación incompleta: la definición combina Tabla Anual, "
            "Promedios y la regla de reasignación. Usá el Panel por equipo/Descenso; este paquete visual queda por ahora "
            "reservado a Playoffs y copas."
        )
        return

    lab = None
    if objective == "Playoffs":
        lab = ui_selectbox("Zona", sorted(Z), key="radar_zone")
    ctx = _definition_objective_context(E, objective, lab)
    if not ctx or not ctx.get("base") or int(ctx.get("cutoff") or 0) <= 0:
        ui_warning("No hay una tabla/corte válido para construir este objetivo con los datos cargados.")
        return
    base = ctx["base"]
    cutoff = int(ctx["cutoff"])
    ordered = list(liga_tabla_df(base)["Equipo"])
    current_round, games, _postponed = lpf_jornada_actual(pending or [])
    if current_round is None or not games:
        ui_info("No hay una fecha oficial pendiente para construir los condicionales.")
        return
    ui_caption(f"Ámbito: **{ctx['scope']}** · corte del objetivo: **puesto {cutoff}**.")
    if ctx.get("direct"):
        ui_caption("Clasificados por vías directas a Libertadores, fuera de esta tabla de pelea: " + ", ".join(ctx["direct"]))

    ui_info(
        "Cómo aparecen los equipos: **Equipo principal** = lo elegís vos y gobierna todo el tablero. "
        "**Contexto automático** = clubes cercanos al principal o al corte, sólo para ubicar la pelea. "
        "**Comparadores** = únicamente los que vos agregás en la matriz G/E/P. "
        "**Otra cancha clave** = un partido sugerido automáticamente por impacto exacto que podés cambiar."
    )

    selection_ordered = list(ordered)
    if objective in ("Libertadores", "Al menos Sudamericana") and ctx.get("annual"):
        selection_ordered = list(liga_tabla_df(ctx["annual"])["Equipo"])
    team_placeholder = "— Elegí un equipo —"
    team_options = [team_placeholder] + selection_ordered
    if "radar_team_focus" not in st.session_state or st.session_state.get("radar_team_focus") not in team_options:
        st.session_state["radar_team_focus"] = team_placeholder
    team_focus = ui_selectbox(
        "Equipo principal", team_options, key="radar_team_focus",
        help="Elegí el club protagonista. Esto no ejecuta el análisis por separado: las demás opciones siguen visibles debajo.",
    )
    team_selected = team_focus != team_placeholder

    package = {}
    report = {}
    fight = pd.DataFrame()
    resolved = False
    if team_selected:
        package = _lpf_definition_package(
            E, objective, lab, team_focus, [team_focus], current_round,
            base=base, rest=rest, games=games, pending=pending, cutoff=cutoff,
        )
        resolved = bool(package.get("resolved") and not package.get("definition_needed", True))
        if not resolved:
            report = package.get("report") or {}
            fight = pd.DataFrame(package.get("fight_zone") or [])

    ui_markdown("**Comparadores de la matriz G/E/P**")
    suggested_matrix = []
    comparator_options = [name for name in ordered if (not team_selected or name != team_focus)]
    if team_selected and not resolved:
        around = fight.loc[fight["Equipo"] != "…", "Equipo"].tolist() if not fight.empty and "Equipo" in fight else ordered[:6]
        suggested_matrix = [name for name in around if name in ordered and name != team_focus][:4]
        matrix_state_key = f"radar_matrix_comparators_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}"
        if matrix_state_key not in st.session_state:
            st.session_state[matrix_state_key] = []
        else:
            st.session_state[matrix_state_key] = [
                name for name in st.session_state.get(matrix_state_key, []) if name in comparator_options
            ]
        comparators = st.multiselect(
            "Comparar también con… (opcional)", comparator_options,
            key=matrix_state_key,
            help=(
                f"{team_focus} ya está incluido. Los clubes que marques acá sólo agregan filas a la matriz; "
                "no cambian el equipo principal."
            ),
        )
        if suggested_matrix:
            ui_caption(
                "Sugeridos por cercanía al equipo y al corte: " + ", ".join(suggested_matrix)
                + ". Son sugerencias; **no se agregan solas**."
            )
            add_col, clear_col = st.columns(2)
            add_col.button(
                "Agregar sugeridos", key=f"radar_add_suggested_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}",
                use_container_width=True,
                on_click=_radar_add_suggested_comparators,
                args=(matrix_state_key, tuple(suggested_matrix), tuple(comparator_options)),
            )
            clear_col.button(
                "Quitar comparadores", key=f"radar_clear_comparators_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}",
                use_container_width=True,
                on_click=_radar_clear_comparators,
                args=(matrix_state_key,),
            )
    else:
        comparators = st.multiselect(
            "Comparar también con… (opcional)", comparator_options,
            key=f"radar_matrix_comparators_disabled_{objective}_{ctx.get('zone') or 'annual'}",
            disabled=True,
            help="Esta opción queda visible desde el inicio y se habilita cuando elegís un equipo principal con el objetivo abierto.",
        )
    selected_teams = [team_focus] + [name for name in comparators if name != team_focus] if team_selected else []

    ui_markdown("**Otra cancha para la doble entrada**")
    automatic_match_choice = "Automática · sugerir la otra cancha más influyente"
    match_options = []
    match_by_label = {}
    candidate_scores = {}
    if team_selected and not resolved and report.get("available"):
        other_matches = list(report.get("other_matches") or [])
        for branch in report.get("branches", []):
            for lever in branch.get("levers", []):
                candidate_scores[lever["match"]] = max(candidate_scores.get(lever["match"], 0.0), float(lever.get("spread", 0.0)))
        for match in other_matches:
            label = f"{match[0]} – {match[1]}"
            match_options.append(label)
            match_by_label[label] = match
        match_options = sorted(set(match_options), key=lambda label: (-candidate_scores.get(label, 0.0), label))
        match_choice_options = [automatic_match_choice] + match_options
        key_state = f"radar_key_match_choice_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}"
        if st.session_state.get(key_state) not in match_choice_options:
            st.session_state[key_state] = automatic_match_choice
        key_match_choice = ui_selectbox(
            "Partido de la otra cancha", match_choice_options, key=key_state,
            help=(
                "Dejá Automática para que el motor use la otra cancha que más cambia los caminos exactos. "
                "O elegí vos un partido de la fecha. No se elige al azar."
            ),
        )
    else:
        key_match_choice = ui_selectbox(
            "Partido de la otra cancha", [automatic_match_choice],
            key=f"radar_key_match_disabled_{objective}_{ctx.get('zone') or 'annual'}",
            disabled=True,
            help="Esta opción queda visible desde el inicio y se habilita cuando el equipo principal tiene una definición abierta.",
        )

    if team_selected:
        ui_caption(
            f"Configuración actual: **{ctx['label']}** · equipo principal: **{team_focus}** · "
            + ("comparadores: " + ", ".join(comparators) if comparators else "sin comparadores")
            + " · otra cancha: " + (key_match_choice if key_match_choice else automatic_match_choice) + "."
        )
    else:
        ui_caption(
            "Las opciones ya están desplegadas. Elegí el equipo principal para habilitar comparadores y otra cancha; "
            "recién debajo se mostrará el resultado. No se selecciona ninguno automáticamente."
        )

    st.divider()
    ui_markdown("## Resultado del análisis")
    if not team_selected:
        ui_info(
            "Todavía no hay un resultado para mostrar. Elegí el equipo principal en la configuración de arriba; "
            "comparadores y otra cancha ya están visibles y se habilitarán sin abrir una pantalla nueva."
        )
        return
    # El informe editorial largo no se esconde detrás de un expander: es parte
    # del resultado, y convive con la lectura visual en vez de ser reemplazado.
    ui_markdown("### Informe editorial del equipo")
    ui_caption(
        "Lectura completa: realidad de hoy, proyección del modelo, referencia histórica, peso del fixture, "
        "mínimo que asegura cuando está demostrado y partidos pendientes. EXACTO y ESTIMADO quedan rotulados dentro del propio informe."
    )
    editorial_report = _definition_editorial_report_text(E, objective, team_focus, lab)
    if editorial_report:
        ui_markdown(editorial_report)

    if resolved:
        resolved_message = str(package.get("message") or f"{team_focus} ya tiene resuelto este objetivo.")
        ui_success(resolved_message)
        if package.get("via"):
            ui_caption(f"Vía: **{package['via']}**.")
        ui_markdown("## Lectura visual de la fecha")
        ui_markdown("### Qué pasa si gana, empata o pierde · EXACTO")
        ui_markdown(
            _html_tabla(_resolved_objective_gep_spec(team_focus, ctx["label"], resolved_message)),
            unsafe_allow_html=True,
        )
        ui_caption(
            "El objetivo ya está cerrado a favor: ganar, empatar o perder la próxima fecha no cambia esa clasificación."
        )
        ui_markdown("### ¿Cómo viene? · objetivo resuelto")
        st.image(
            placa_chances_mc_png(
                team_focus, 100.0,
                nota=f"OBJETIVO RESUELTO · {ctx['label']}",
                verdict_override="YA CLASIFICÓ" if objective == "Libertadores" else "OBJETIVO CUMPLIDO",
            ),
            use_container_width=True,
        )
        ui_caption(
            "Esta marca es EXACTA y proviene de la vía de clasificación ya resuelta; no es una estimación Monte Carlo."
        )
        if objective in ("Libertadores", "Al menos Sudamericana"):
            resolved_map_key = f"radar_resolved_cup_map_{objective}_{team_focus}"
            if st.button(
                f"Ver mapa comparativo de Copas · {_LPF_PUBLIC_MC_RUNS:,} simulaciones",
                key=f"radar_resolved_cup_map_button_{objective}_{team_focus}",
                use_container_width=True,
            ):
                try:
                    st.session_state[resolved_map_key] = _cup_probability_package(E, objective, team_focus)
                except Exception as exc:
                    st.session_state.pop(resolved_map_key, None)
                    ui_warning(f"No pude construir el mapa comparativo de Copas: {exc}")
            resolved_map = st.session_state.get(resolved_map_key) or {}
            resolved_rows = list(resolved_map.get("rows") or [])
            if resolved_rows:
                ui_markdown("### Mapa de probabilidades de Copas · ESTIMADO")
                ui_markdown(
                    _html_tabla(
                        cup_probability_heatmap_spec(
                            resolved_rows, active_objective=objective, focus_team=team_focus,
                            simulations=int(resolved_map.get("simulations", _LPF_PUBLIC_MC_RUNS)),
                        )
                    ),
                    unsafe_allow_html=True,
                )
                ui_caption(
                    "El mapa compara al resto de los equipos mediante simulación. Para el equipo principal, la clasificación ya resuelta sigue siendo exacta."
                )
        ui_caption(
            "No se construye doble entrada para el equipo principal porque ya no disputa este cupo por el corte de la Tabla Anual."
        )
        return

    ui_markdown("## Lectura visual de la fecha")
    ui_caption(
        "Estas visualizaciones complementan el informe editorial de arriba: resumen rápido y auditable de la fecha, sin reemplazar su contexto ni su explicación."
    )

    # Contexto de la pelea: siempre alrededor del equipo principal.
    ui_markdown("### Zona de pelea · contexto automático · quiénes están alrededor")
    fight = pd.DataFrame(package.get("fight_zone") or [])
    if not fight.empty:
        ui_dataframe(fight, use_container_width=True, hide_index=True)
    ui_caption(
        "Estos equipos aparecen automáticamente porque están cerca del equipo principal o del corte. "
        "Son contexto de la pelea: no fueron elegidos como comparadores y no cambian el protagonista. "
        "Techo = puntos actuales + todos los puntos propios todavía disponibles; no es una proyección."
    )

    # Matriz general / semáforo. El principal es fijo y los comparadores ya se eligieron arriba.
    ui_markdown("### Matriz de la fecha · todos los equipos que quieras seguir")
    ui_caption("Qué pasa si gana, empata o pierde: lectura G/E/P del equipo principal y de los comparadores elegidos.")
    ui_markdown(f"**Equipo principal: {team_focus}**")
    ui_caption(
        f"La primera fila siempre es **{team_focus}**. "
        + ("También vas a ver: " + ", ".join(comparators) + "." if comparators else "No agregaste comparadores.")
    )

    # Si el editor agrega comparadores, pedimos de nuevo el mismo paquete público
    # con esa selección. El caso por defecto reutiliza la primera consulta.
    if comparators:
        package = _lpf_definition_package(
            E, objective, lab, team_focus, selected_teams, current_round,
            base=base, rest=rest, games=games, pending=pending, cutoff=cutoff,
        )
    rows = list(package.get("matrix") or [])
    solver_matrix_teams = []
    if rows:
        rows, solver_matrix_teams = _definition_fill_milp_matrix(
            rows, base, rest, games, pending, cutoff
        )
        # Lectura principal tipo Mundial: una sola grilla, sin obligar a elegir entre modos.
        visual_spec = _definition_general_matrix_spec(rows, team_focus, ctx["label"])
        ui_markdown(_html_tabla(visual_spec), unsafe_allow_html=True)
        ui_caption("Semáforo compacto: 🟢 objetivo cerrado a favor · 🟡 sigue condicionado · 🔴 objetivo cerrado en contra. El texto de la celda manda sobre el color.")
        if solver_matrix_teams:
            ui_caption(
                "Para " + ", ".join(solver_matrix_teams) +
                " la fecha tiene demasiadas otras canchas para enumerar 3^N combinaciones. "
                "Estas tres celdas se resolvieron igualmente de manera EXACTA con el solver MILP de temporada: "
                "prueba garantía con el peor recorrido propio posterior y eliminación con el mejor. No es Monte Carlo."
            )

        with st.expander("Ver detalle tabular y exportar", expanded=False):
            visible = [{k: v for k, v in row.items() if not str(k).startswith("_")} for row in rows]
            ui_dataframe(
                pd.DataFrame(visible), use_container_width=True, hide_index=True,
                export_title=f"Matriz G-E-P · {team_focus} · {ctx['label']}",
                export_name=f"matriz_gep_{team_focus}",
            )

        with st.expander("¿Por qué? · explicar un equipo de la matriz", expanded=False):
            why_team = ui_selectbox(
                "Equipo a explicar", selected_teams,
                key=f"radar_matrix_why_team_{objective}_{ctx.get('zone') or 'annual'}_{team_focus}",
            )
            why_result_label = ui_selectbox(
                "Resultado propio", ["Gana", "Empata", "Pierde"],
                key=f"radar_matrix_why_result_{objective}_{ctx.get('zone') or 'annual'}",
            )
            why_row = next((row for row in rows if row.get("Equipo") == why_team), None)
            why_report = (why_row or {}).get("_report") or {}
            why_code = {"Gana": "G", "Empata": "E", "Pierde": "P"}[why_result_label]
            why_branch = next((branch for branch in why_report.get("branches", []) if branch.get("result") == why_code), None)
            if why_branch:
                if why_branch.get("solver_explanation"):
                    ui_markdown(str(why_branch["solver_explanation"]))
                else:
                    ui_markdown(branch_explanation(why_branch, ctx["label"]))
            else:
                ui_caption("No hay una rama exacta disponible para ese equipo/resultado en la fecha seleccionada.")

    # Mapa de puestos tipo Mundial: rango exacto de esta fecha para principal y comparadores.
    ui_markdown("### Mapa de puestos después de esta fecha · EXACTO")
    rank_spec = _definition_rank_map_spec(base, games, selected_teams, cutoff, ctx["label"], team_focus)
    ui_markdown(_html_tabla(rank_spec), unsafe_allow_html=True)
    ui_caption(
        "Recupera el mapa de posiciones del Mundial, pero sin convertir conteos de marcadores en probabilidad: "
        "muestra el mejor y peor puesto matemáticamente posible al terminar esta fecha."
    )

    if comparators:
        ui_markdown("### Cara a cara · principal vs comparadores")
        for comparator in comparators[:3]:
            compare_spec = _definition_compare_spec(base, rest, rows, team_focus, comparator, ctx["label"])
            ui_markdown(_html_tabla(compare_spec), unsafe_allow_html=True)
        if len(comparators) > 3:
            ui_caption(f"Mostrando 3 de {len(comparators)} comparadores en el cara a cara. La matriz G/E/P de arriba conserva todos.")
    else:
        ui_caption("El cara a cara aparece acá cuando agregás al menos un comparador arriba; no se selecciona ninguno automáticamente.")

    # Informe exacto del equipo seleccionado, también desde ``definition``.
    report = package.get("report") or {}
    if not report.get("available"):
        ui_info(
            (report.get("reason") or "El equipo no tiene un condicional enumerado para esta fecha.")
            + " La matriz G/E/P de arriba no queda vacía: cuando el fixture completo está disponible, "
              "sus estados se resuelven con el solver exacto. La doble entrada, el árbol y el ranking exacto "
              "de otras canchas sí requieren la enumeración corta y por eso se omiten en esta fecha."
        )
        ui_markdown("### Visuales estimados disponibles igualmente")
        ui_caption(
            "El límite de enumeración exacta no bloquea el termómetro, el mapa de probabilidades de Copas ni el impacto estimado de otras canchas."
        )
        _render_radar_estimated_visuals(E, objective, lab, team_focus, ctx, Z, rest, pending)
        return

    current = int((base[team_focus] or {}).get("pts", 0))
    left = int(rest.get(team_focus, 0))
    guarantee = package.get("guarantee")
    ladder = package.get("ladder")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Puntos", current)
    c2.metric("PJ por jugar", left)
    c3.metric("Techo", current + 3 * left)
    c4.metric("Mínimo que asegura", guarantee if guarantee is not None else "—")

    # Otra cancha clave: la elección ya se hizo en la configuración superior.
    ui_markdown("### Matriz de rival clave · otra cancha clave · doble entrada")
    ui_caption(
        "Acá se aplica el partido elegido arriba. Si dejaste Automática, el motor toma la otra cancha que más cambia los caminos exactos. "
        "La doble entrada cruza el resultado del equipo principal con gana local / empate / gana visitante."
    )
    if match_options:
        key_match_label = match_options[0] if key_match_choice == automatic_match_choice else key_match_choice
        if key_match_label not in match_by_label:
            key_match_label = match_options[0]
        key_match = match_by_label[key_match_label]
        key_team = key_match[0] if key_match[0] in base else key_match[1]
        ui_caption(
            f"Otra cancha seleccionada: **{key_match[0]} – {key_match[1]}**. "
            "Las columnas muestran gana local / empate / gana visitante; no hace falta elegir un segundo equipo."
        )
        key_report = key_rival_matrix(base, rest, games, team_focus, key_team, cutoff)
        if key_report.get("available"):
            key_spec = _definition_key_matrix_spec(team_focus, key_match, key_team, key_report, ctx["label"])
            ui_markdown(_html_tabla(key_spec), unsafe_allow_html=True)
            ui_caption(
                f"**{team_focus} ↓ / {key_match[0]}–{key_match[1]} →** · filas = resultado propio; columnas = resultado completo de la otra cancha. "
                "Los demás partidos de la fecha quedan abiertos y se enumeran exactamente dentro de cada celda."
            )

            with st.expander("¿Por qué? · explicar una celda", expanded=False):
                ec1, ec2 = st.columns(2)
                own_explain = ec1.selectbox(
                    "Resultado de " + team_focus, ["Gana", "Empata", "Pierde"],
                    key=f"why_own_{team_focus}_{key_match[0]}_{key_match[1]}",
                )
                outcome_labels = [label for label, _code in key_spec["_columns"]]
                other_explain = ec2.selectbox(
                    f"Resultado de {key_match[0]} – {key_match[1]}", outcome_labels,
                    key=f"why_match_{team_focus}_{key_match[0]}_{key_match[1]}",
                )
                own_code = {"Gana": "G", "Empata": "E", "Pierde": "P"}[own_explain]
                key_code = dict(key_spec["_columns"])[other_explain]
                cells = {(c["own_result"], c["key_result"]): c for c in key_report["cells"]}
                cell = dict(cells[(own_code, key_code)])
                cell["result_label"] = f"Si {team_focus} {own_explain.lower()} y en {key_match[0]}–{key_match[1]} {other_explain.lower()}"
                ui_markdown(branch_explanation(cell, ctx["label"]))

            with st.expander("Ver doble entrada detallada y exportar", expanded=False):
                cells = {(c["own_result"], c["key_result"]): c for c in key_report["cells"]}
                detailed_rows = []
                for own_code, own_label in (("G", "Gana"), ("E", "Empata"), ("P", "Pierde")):
                    detailed_rows.append({
                        team_focus: own_label,
                        **{label: branch_cell(cells[(own_code, key_code)]) for label, key_code in key_spec["_columns"]},
                    })
                ui_dataframe(
                    pd.DataFrame(detailed_rows), use_container_width=True, hide_index=True,
                    export_title=f"Doble entrada · {team_focus} · {key_match[0]}-{key_match[1]}",
                    export_name=f"doble_entrada_{team_focus}_{key_match[0]}_{key_match[1]}",
                )
        else:
            ui_info(key_report.get("reason") or "No se pudo construir la doble entrada.")
    else:
        ui_caption("No hay otra cancha independiente para cruzar en esta fecha.")

    # Árbol reducido: sólo ramas con información nueva.
    ui_markdown("### Árbol reducido del camino")
    tree = _definition_tree_dot(team_focus, ctx["label"], report)
    if tree:
        _ST_GRAPHVIZ(tree, use_container_width=True)
        ui_caption("El árbol corta las ramas terminales y no dibuja todas las combinaciones del torneo. Sólo muestra qué cambia el estado.")

    # Partidos que más definen: ranking exacto de sensibilidad, no pronóstico.
    ui_markdown("### Partidos que más definen")
    decisive_rows = _definition_decisive_matches(report)
    if decisive_rows:
        decisive_chart = pd.DataFrame([
            {"Partido": item["Partido"], "Caminos exactos que cambian": int(item["Caminos que cambian"])}
            for item in decisive_rows
        ])
        if not decisive_chart.empty:
            st.bar_chart(decisive_chart.set_index("Partido")[["Caminos exactos que cambian"]])
            ui_caption("Versión visual del partido bisagra del Mundial: barra más alta = más caminos exactos cambian. No es probabilidad.")
        visible_decisive = []
        for item in decisive_rows:
            visible_decisive.append({
                "Orden": item["Orden"],
                "Partido": item["Partido"],
                "Se nota más si": item["Se nota más si"],
                "Resultado más favorable": item["Más favorable"],
                "Resultado menos favorable": item["Menos favorable"],
                "Caminos exactos que cambian": f"{item['Caminos que cambian']} de {item['Combinaciones por desenlace']}",
                "Ramas G/E/P afectadas": item["Ramas afectadas"],
            })
        ui_dataframe(
            pd.DataFrame(visible_decisive), use_container_width=True, hide_index=True,
            export_title=f"Partidos que más definen · {team_focus}",
            export_name=f"partidos_que_mas_definen_{team_focus}",
        )
        ui_caption(
            "Orden exacto: mide cuánto cambia la cantidad de caminos favorables al fijar un desenlace u otro de cada partido ajeno. "
            "Por ejemplo, ‘6 de 9’ significa seis combinaciones exactas de diferencia entre el desenlace más favorable y el menos favorable. No es probabilidad."
        )
    else:
        ui_caption("Ninguna otra cancha cambia los caminos favorables del equipo principal en esta fecha.")

    # 8) Explicación exacta de G/E/P, a demanda.
    with st.expander("¿Por qué? · explicar gana / empata / pierde · resumen exacto", expanded=False):
        for branch in report.get("branches", []):
            ui_markdown(f"**{branch['result_label']}**")
            ui_markdown(branch_explanation(branch, ctx["label"]))

    # Reloj: ya viene en el mismo paquete público exacto.
    ui_markdown("### Reloj de definición")
    guarantee_round = package.get("guarantee_round_label")
    clock = package.get("clock") or []
    if clock:
        ui_dataframe(pd.DataFrame(clock).rename(columns={"when": "Cuándo", "status": "Qué puede pasar", "detail": "Por qué"}),
                     use_container_width=True, hide_index=True)
    if guarantee is None:
        if left > VENTANA_EXACTA:
            ui_caption(f"El mínimo exacto que asegura se incorpora al reloj cuando queden {VENTANA_EXACTA} partidos o menos.")
        else:
            ui_caption("Todavía no hay un mínimo que asegure demostrado por el solver exacto.")

    # Herramientas técnicas quedan disponibles, pero fuera de la lectura principal.
    with st.expander("Detalle técnico exacto", expanded=False):
        preview_text, preview_frame = lpf_previa_equipo_texto(
            team_focus, Z, rest, pending, ctx.get("annual") or {}, st.session_state.get("PROMEDIOS") or {},
            scope="next_team_match", objective=objective,
        )
        if preview_text:
            ui_markdown(preview_text)
        if preview_frame is not None and not preview_frame.empty:
            ui_dataframe(preview_frame, use_container_width=True, hide_index=True)
        _render_exact_next_round_conditionals(team_focus, base, rest, pending)
        if ladder and ladder.get("available"):
            if st.button("Abrir escalera exacta de puntos", key=f"radar_ladder_new_{objective}_{team_focus}"):
                _render_point_ladder(
                    team_focus, base, rest, pending, cutoff,
                    f"{team_focus} · posibilidades exactas por puntaje final",
                )
            else:
                ui_caption("La escalera exacta completa sigue disponible en Puntos por objetivo.")

    _render_radar_estimated_visuals(E, objective, lab, team_focus, ctx, Z, rest, pending)

def _scenario_window_games(pending, scope="official_round"):
    jornada, juegos, atrasados = lpf_jornada_actual(pending or [])
    postponed = [match for match, _round in atrasados]
    if scope == "postponed_only":
        return jornada, _lpf_dedupe_scenario_games(postponed)
    if scope == "extended_window":
        return jornada, _lpf_dedupe_scenario_games(list(juegos) + postponed)
    return jornada, _lpf_dedupe_scenario_games(list(juegos))


def _scenario_outcome_label(match, outcome):
    home, away = match
    if outcome == "L":
        return f"gana {home}"
    if outcome == "V":
        return f"gana {away}"
    return f"empatan {home} y {away}"


def _scenario_outcomes_frame(outcomes):
    rows = []
    for match, outcome in (outcomes or {}).items():
        rows.append({"Partido": f"{match[0]} – {match[1]}", "Resultado": _scenario_outcome_label(match, outcome)})
    return pd.DataFrame(rows)


def render_scenarios_workspace(E, default_team=None, embedded=False):
    """Herramientas del proyecto del Mundial adaptadas a la LPF.

    Reúne en una sola pantalla gana/empata/pierde, constructor de escenarios,
    puesto puntual, mejor/peor caso y distribución estimada. Así estas funciones
    no quedan escondidas detrás de comandos del chat.
    """
    if not embedded:
        ui_markdown("## Escenarios")
    ui_caption("Herramientas inspiradas en la calculadora del Mundial, adaptadas a zonas de 15 equipos. "
               "Los rangos y escenarios por puntos son exactos; las distribuciones están rotuladas como estimación.")
    Z = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    teams = sorted(E.get("equipos") or [])
    if not teams or len(Z) < 2:
        ui_warning("Cargá las dos zonas antes de abrir Escenarios.")
        return
    gate = _lpf_data_gate(E, "playoffs")
    if gate:
        ui_warning(gate[1])
        return
    if default_team in teams:
        team = default_team
        ui_markdown(f"### {team}")
    else:
        team = ui_selectbox("Equipo", teams, index=teams.index("River Plate") if "River Plate" in teams else 0,
                            key="scenario_team")
    lab = lpf_zona_de_equipo(team, Z)
    base = Z[lab]
    annual = lpf_anual_base(Z, E.get("apertura") or {})
    previous = st.session_state.get("PROMEDIOS") or {}
    scenario_labels = [
        "Gana / empata / pierde",
        "Qué pasa si…",
        "Puntos y puesto final",
        "Mejor y peor caso",
        "Distribución",
        "Clasificados y eliminados",
    ]
    if st.session_state.get("scenario_tool_nav") == "Puntaje y puesto":
        st.session_state["scenario_tool_nav"] = "Puntos y puesto final"
    if st.session_state.get("scenario_tool_nav") not in scenario_labels:
        st.session_state["scenario_tool_nav"] = scenario_labels[0]
    scenario_tool = st.radio(
        "Herramienta de escenarios",
        scenario_labels,
        horizontal=True,
        key="scenario_tool_nav",
        help="Todas las herramientas vuelven a quedar visibles y accesibles desde el inicio.",
    )

    if scenario_tool == "Gana / empata / pierde":
        scope_label = st.radio(
            "Alcance",
            ["Próximo partido real", "Día del próximo partido", "Fecha oficial", "Sólo postergados", "Fecha + postergados"],
            horizontal=True,
            key=f"scenario_result_scope_{team}",
        )
        scope = {
            "Próximo partido real": "next_team_match",
            "Día del próximo partido": "next_team_day",
            "Fecha oficial": "official_round",
            "Sólo postergados": "postponed_only",
            "Fecha + postergados": "extended_window",
        }[scope_label]
        preview_objective = st.radio(
            "Lectura complementaria",
            ["Playoffs", "Libertadores", "Al menos Sudamericana", "Descenso"],
            horizontal=True,
            key=f"scenario_result_objective_{team}",
        )
        text, frame = lpf_previa_equipo_texto(
            team, Z, rest, pending, annual, previous, scope=scope, objective=preview_objective
        )
        if text:
            ui_markdown(text)
        if frame is not None:
            ui_dataframe(frame, use_container_width=True, hide_index=True)
        ui_caption("Esta vista recupera la lógica central del Mundial: separar claramente qué ocurre si el equipo gana, empata o pierde.")

    if scenario_tool == "Qué pasa si…":
        scope_label = st.radio(
            "Ventana a simular",
            ["Fecha oficial", "Sólo postergados", "Fecha + postergados"],
            horizontal=True,
            key=f"scenario_builder_scope_{team}",
        )
        scope = {"Fecha oficial": "official_round", "Sólo postergados": "postponed_only",
                 "Fecha + postergados": "extended_window"}[scope_label]
        round_no, games = _scenario_window_games(pending, scope)
        relevant = [match for match in games if match[0] in base or match[1] in base]
        if not relevant:
            ui_info("No hay partidos en esa ventana que afecten a la zona del equipo.")
        else:
            ui_markdown(f"**Ventana:** {('Fecha ' + str(round_no)) if round_no is not None else 'partidos pendientes'} · "
                        f"{len(relevant)} partido(s) que afectan la Zona {lab}")
            fixed = {}
            for idx, match in enumerate(relevant):
                home, away = match
                choice = ui_selectbox(
                    f"{home} – {away}",
                    ["Sin definir", f"Gana {home}", "Empate", f"Gana {away}"],
                    key=f"scenario_fix_{team}_{scope}_{idx}",
                )
                if choice == f"Gana {home}":
                    fixed[match] = "L"
                elif choice == "Empate":
                    fixed[match] = "E"
                elif choice == f"Gana {away}":
                    fixed[match] = "V"
            if fixed:
                result = scenario_rank_bounds(base, relevant, team, fixed)
                if result.get("available"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Puntos posibles", f"{result['points_min']}–{result['points_max']}")
                    c2.metric("Mejor puesto", f"{result['best_rank']}º")
                    c3.metric("Peor puesto", f"{result['worst_rank']}º")
                    c4.metric("Resultados fijados", len(fixed))
                    ui_dataframe(_scenario_outcomes_frame(fixed), use_container_width=True, hide_index=True)
                    ui_caption("Los partidos sin definir quedan abiertos. El intervalo contempla desempates favorables y adversos sin inventar marcadores.")
                else:
                    ui_warning("No se encontró un escenario compatible. Revisá los resultados fijados.")
            else:
                ui_info("Elegí uno o más resultados. El resto de los partidos quedará abierto y el motor calculará el rango posible.")

    if scenario_tool == "Puntos y puesto final":
        full_games = [match for match in pending if match[0] in base or match[1] in base]
        ui_markdown("### ¿Con cuántos puntos puede clasificar?")
        ui_caption(
            "Esta parte recorre los totales finales que el equipo todavía puede alcanzar y muestra si con cada uno "
            "puede entrar entre los ocho, si todavía depende de otros resultados o si ya asegura la clasificación."
        )
        _render_point_ladder(team, base, rest, full_games, 8, f"{team} · puntos para clasificar")
        st.divider()
        ui_markdown("### ¿Con cuántos puntos suele terminar en un puesto específico?")
        ui_caption(
            "Elegí un puesto. La app simula el resto del torneo y mira sólo las corridas en las que el equipo termina allí. "
            "Así cada puntaje pesa según la frecuencia con la que aparece, en vez de tratar todos los extremos matemáticos como igual de probables."
        )
        target_rank = st.number_input("¿Qué puesto querés analizar?", min_value=1, max_value=len(base), value=8,
                                      step=1, key=f"scenario_target_rank_{team}")
        if st.button(f"Estimar puntos si termina {int(target_rank)}º", use_container_width=True,
                     key=f"scenario_find_rank_{team}"):
            simulations = 6000
            with st.spinner("Simulando el resto del torneo…"):
                simulated_rank, simulated_points = _sim_zone_rank_points(
                    base, rest, pending, team, simulations, 3825 + int(target_rank),
                    jugados=E.get("jugados") or [],
                    strength_base={name: row for zone in Z.values() for name, row in zone.items()},
                )
            rank_summary = _summarize_rank_condition(
                simulated_rank, simulated_points, int(target_rank), min_samples=100
            )
            if rank_summary["samples"]:
                median = float(rank_summary["median"])
                q25 = float(rank_summary["q25"])
                q75 = float(rank_summary["q75"])
                rank_probability = 100.0 * float(rank_summary["probability"])
                distribution = pd.DataFrame({
                    "Puntos finales": [row["final_points"] for row in rank_summary["distribution"]],
                    f"Frecuencia entre los casos {int(target_rank)}º (%)": [
                        round(100 * float(row["frequency"]), 1) for row in rank_summary["distribution"]
                    ],
                    "Simulaciones": [row["samples"] for row in rank_summary["distribution"]],
                })
                c1, c2, c3 = st.columns(3)
                c1.metric("Mediana estimada", _fmt_num_es(median))
                c2.metric("50% central", f"{_fmt_num_es(q25)}–{_fmt_num_es(q75)}")
                c3.metric(f"Chance estimada de terminar {int(target_rank)}º", f"{rank_probability:.1f}%")
                ui_dataframe(distribution, use_container_width=True, hide_index=True)
                ui_caption(
                    f"ESTIMACIÓN · {_fmt_entero_es(simulations)} simulaciones. El resumen usa "
                    f"**{_fmt_entero_es(rank_summary['samples'])} casos** en los que {team} terminó exactamente "
                    f"{int(target_rank)}º; no es la mediana de los puntajes matemáticamente posibles: pondera sólo "
                    "la frecuencia de esas corridas. El rango 50% central deja afuera los extremos menos frecuentes."
                )
                if not rank_summary["stable"]:
                    ui_warning(
                        f"Muestra condicionada chica: sólo {_fmt_entero_es(rank_summary['samples'])} de "
                        f"{_fmt_entero_es(simulations)} simulaciones terminaron con {team} {int(target_rank)}º. "
                        "La mediana y el rango pueden moverse si cambia la semilla; leelos como una orientación, "
                        "no como una estimación estable."
                    )
            else:
                ui_warning(
                    f"En {_fmt_entero_es(simulations)} simulaciones {team} no terminó {int(target_rank)}º. Eso no demuestra que sea imposible; "
                    "indica que el modelo no encontró ese puesto con frecuencia suficiente en esta muestra."
                )

        show_math = st.checkbox(
            "Mostrar también los extremos matemáticos (sin probabilidad)",
            value=False,
            key=f"scenario_target_rank_math_{team}_{int(target_rank)}",
            help="Esta vista responde qué es posible en algún escenario extremo. No debe leerse como un puntaje típico.",
        )
        if show_math:
            current = int(base[team].get("pts", 0))
            games_left = int(rest.get(team, 0))
            exact_totals = []
            first_solver_message = ""
            with st.spinner("Buscando extremos matemáticos…"):
                for final_points in reachable_point_totals(current, games_left):
                    proof = can_finish_exact_rank_by_points(
                        base, full_games, team, int(target_rank), final_points
                    )
                    first_solver_message = first_solver_message or str(proof.message or "")
                    if proof.feasible:
                        exact_totals.append(final_points)
            if exact_totals:
                ui_info(
                    f"Extremo matemático: {team} puede quedar exactamente {int(target_rank)}º por puntos desde "
                    f"**{min(exact_totals)}** hasta **{max(exact_totals)}** puntos en al menos un escenario. "
                    "Esto no mide probabilidad y puede incluir combinaciones muy poco frecuentes."
                )
                ui_dataframe(
                    pd.DataFrame({"Puntos matemáticamente posibles": exact_totals}),
                    use_container_width=True, hide_index=True,
                )
            elif "no está disponible" in first_solver_message.lower():
                ui_warning("El optimizador exacto no está disponible en este entorno.")
            else:
                ui_warning(
                    f"No encontré un escenario que deje a {team} exactamente {int(target_rank)}º por puntos sin depender de un desempate."
                )

    if scenario_tool == "Mejor y peor caso":
        scope_label = st.radio(
            "Ventana",
            ["Fecha oficial", "Fecha + postergados"],
            horizontal=True,
            key=f"scenario_extreme_scope_{team}",
        )
        scope = "official_round" if scope_label == "Fecha oficial" else "extended_window"
        _round, games = _scenario_window_games(pending, scope)
        relevant = [match for match in games if match[0] in base or match[1] in base]
        if not relevant:
            ui_info("No hay partidos para analizar en esa ventana.")
        elif st.button("Calcular mejor y peor caso concreto", type="primary", use_container_width=True,
                       key=f"scenario_extremes_{team}_{scope}"):
            with st.spinner("Buscando escenarios concretos…"):
                extremes = best_worst_window_scenarios(base, relevant, team)
            if not extremes.get("available"):
                ui_warning("El optimizador exacto no está disponible o no encontró escenarios compatibles.")
            else:
                best = extremes["best"]
                worst = extremes["worst"]
                c1, c2 = st.columns(2)
                with c1:
                    ui_markdown(f"#### Mejor caso: {best['rank']}º con {best['final_points']} puntos")
                    ui_dataframe(_scenario_outcomes_frame(best.get("outcomes")), use_container_width=True, hide_index=True)
                with c2:
                    ui_markdown(f"#### Peor caso: {worst['rank']}º con {worst['final_points']} puntos")
                    ui_dataframe(_scenario_outcomes_frame(worst.get("outcomes")), use_container_width=True, hide_index=True)
                ui_caption("Son combinaciones concretas que prueban los extremos del rango. No son necesariamente las únicas.")

    if scenario_tool == "Distribución":
        n = st.select_slider("Cantidad de simulaciones", options=[2000, 5000, 10000, 20000], value=5000,
                             key=f"scenario_distribution_n_{team}")
        if st.button("Calcular distribución estimada de posiciones", use_container_width=True,
                     key=f"scenario_distribution_{team}"):
            with st.spinner("Simulando el resto del torneo…"):
                positions = _sim_zone_pos(
                    base, rest, pending, team, int(n), seed=43, jugados=E.get("jugados") or [],
                    strength_base={name: row for zone in Z.values() for name, row in zone.items()},
                )
            counts = pd.Series(positions).value_counts().sort_index()
            frame = pd.DataFrame({"Puesto": counts.index.astype(int), "Probabilidad %": (100 * counts.values / int(n)).round(1)})
            st.bar_chart(frame.set_index("Puesto"))
            ui_dataframe(frame, use_container_width=True, hide_index=True)
            ui_caption("ESTIMACIÓN: usa el modelo de fuerza y localía de la aplicación. No reemplaza los rangos exactos por puntos.")

    if scenario_tool == "Clasificados y eliminados":
        table = liga_tabla_df(base)
        rows = []
        for _, row in table.iterrows():
            name = row["Equipo"]
            state = _liga_in_out(name, base, rest, 8)
            rows.append({
                "Pos": int(row["Pos"]),
                "Equipo": name,
                "PTS": int(row["PTS"]),
                "Techo": int(base[name]["pts"]) + 3 * int(rest.get(name, 0)),
                "Estado matemático": {"in": "Clasificado", "out": "Eliminado", "pelea": "En carrera"}.get(state, state),
            })
        ui_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=560)
        ui_caption("Esta vista adapta el panel de clasificados y eliminados del Mundial. Se calcula con el fixture y los puntos disponibles.")

def _render_cup_visual_dashboard(E, team, view):
    """Tablero visual de Copas: foto exacta + Monte Carlo + otra cancha."""
    objective = "Libertadores" if view == "Libertadores" else "Al menos Sudamericana"
    ctx = _cup_visual_context(E)
    annual = ctx.get("anual") or {}
    annual_order = [name for name in ctx.get("orden") or [] if name in annual]
    reduced_order = [name for name in ctx.get("reducida") or [] if name in annual]
    n_lib = int(ctx.get("n_lib") or 0)
    metrics = _cup_cut_metrics(ctx, team)

    ui_markdown(f"### {view} · tablero visual de la Tabla Anual")
    ui_caption(
        "La foto actual y los cupos de hoy son EXACTOS. El heatmap y la otra cancha son ESTIMADOS con 6.000 simulaciones. "
        "Los clasificados directos a Libertadores no consumen otro cupo de la Tabla Anual."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Posición Anual", f"{metrics['team_position']}º" if metrics.get("team_position") else "—")
    c2.metric("Puntos", metrics.get("team_points", 0))
    c3.metric(
        "Corte Libertadores hoy",
        metrics.get("lib_cut_points") if metrics.get("lib_cut_points") is not None else "—",
        help=(f"Hoy lo ocupa {display_team(metrics.get('lib_cut_team'))}." if metrics.get("lib_cut_team") else None),
    )
    c4.metric(
        "Corte Sudamericana hoy",
        metrics.get("sud_cut_points") if metrics.get("sud_cut_points") is not None else "—",
        help=(f"Hoy lo ocupa {display_team(metrics.get('sud_cut_team'))}." if metrics.get("sud_cut_team") else None),
    )

    if annual_order:
        ui_markdown(
            _html_tabla(
                cup_current_slots_spec(
                    annual,
                    annual_order,
                    reduced_order,
                    libertadores_slots=n_lib,
                    focus_team=team,
                )
            ),
            unsafe_allow_html=True,
        )

    ui_markdown("#### Qué pasa si gana, empata o pierde · EXACTO")
    ui_caption(
        "La misma matriz G/E/P del tablero de Playoffs, aplicada al corte real de la Tabla Anual. "
        "Verde/amarillo/rojo describen estados matemáticos, no probabilidades."
    )
    definition_visual = _cup_definition_visual_package(E, objective, team)
    if definition_visual.get("available"):
        definition_package = definition_visual.get("package") or {}
        definition_ctx = definition_visual.get("context") or {}
        if definition_package.get("resolved") and not definition_package.get("definition_needed", True):
            resolved_message = str(definition_package.get("message") or f"{team} ya tiene resuelto este objetivo.")
            ui_markdown(
                _html_tabla(
                    _resolved_objective_gep_spec(team, definition_ctx.get("label") or view, resolved_message)
                ),
                unsafe_allow_html=True,
            )
            if definition_package.get("via"):
                ui_caption(f"Vía resuelta: **{definition_package['via']}**.")
        else:
            definition_rows = list(definition_package.get("matrix") or [])
            solver_matrix_teams = []
            if definition_rows:
                definition_rows, solver_matrix_teams = _definition_fill_milp_matrix(
                    definition_rows, definition_ctx.get("base") or {}, E.get("rest") or {},
                    definition_visual.get("games") or [], definition_visual.get("pending") or [],
                    int(definition_ctx.get("cutoff") or 0),
                )
                ui_markdown(
                    _html_tabla(
                        _definition_general_matrix_spec(
                            definition_rows, team, definition_ctx.get("label") or view
                        )
                    ),
                    unsafe_allow_html=True,
                )
                ui_caption(
                    "★ = equipo elegido. G/E/P evalúa la próxima fecha oficial con el resto de los partidos compatibles abiertos."
                )
                if solver_matrix_teams:
                    ui_caption(
                        "La enumeración corta de otras canchas superó su límite; G/E/P se resolvió igualmente de forma EXACTA "
                        "con el solver MILP de temporada, sin Monte Carlo."
                    )
            else:
                ui_caption(
                    str((definition_package.get("report") or {}).get("reason") or definition_package.get("reason") or
                        "No hay una matriz G/E/P exacta disponible para la próxima fecha.")
                )
    else:
        ui_caption(str(definition_visual.get("reason") or "No hay una matriz G/E/P exacta disponible para este objetivo."))

    ui_markdown("#### Lectura editorial")
    if view == "Libertadores":
        ui_markdown(lpf_relato_libertadores_texto(
            E.get("zonas_lpf") or {}, E.get("rest") or {}, E.get("apertura") or {},
            E.get("camps") or ("", "", ""), E.get("intl") or ("", ""),
            E.get("copa_arg_vivos") or [], E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
        ))
    else:
        ui_markdown(lpf_relato_sudamericana_texto(
            E.get("zonas_lpf") or {}, E.get("rest") or {}, E.get("apertura") or {},
            E.get("camps") or ("", "", ""), E.get("intl") or ("", ""),
            E.get("copa_arg_vivos") or [], E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
        ))

    ui_markdown("#### Mapa de probabilidades de Copas · ESTIMADO")
    ui_caption(
        "La escala rojo→amarillo→verde recupera la lectura visual del Mundial. Cada celda conserva el porcentaje explícito: "
        "el color ayuda a leer, pero no representa una garantía matemática."
    )
    prob_cache_key = f"viz_cup_probability_{view}_{team}"
    if st.button(
        f"Calcular mapa de probabilidades · {_LPF_PUBLIC_MC_RUNS:,} simulaciones",
        key=f"viz_cup_probability_button_{view}_{team}",
        use_container_width=True,
    ):
        try:
            package = _cup_probability_package(E, objective, team)
            chance_payload = {
                "team": team,
                "objective": _lpf_service_objective(objective),
                "simulations": _LPF_PUBLIC_MC_RUNS,
                "seed": 23,
            }
            package["focus"] = _lpf_service_result("objective_chances", E, **chance_payload)
            st.session_state[prob_cache_key] = package
        except _LPFServiceContractError as exc:
            _record_lpf_service_fallback("objective_chances", exc)
            ui_warning("No pude calcular la chance destacada por el contrato público; el fallo quedó registrado en auditoría.")
        except Exception as exc:
            st.session_state.pop(prob_cache_key, None)
            ui_warning(f"No pude construir el mapa de probabilidades: {exc}")

    probability_package = st.session_state.get(prob_cache_key) or {}
    probability_rows = list(probability_package.get("rows") or [])
    focus_result = probability_package.get("focus") or {}
    if focus_result:
        if focus_result.get("resolved"):
            pct = float(focus_result.get("qualification_percentage", 100.0) or 100.0)
            st.image(
                placa_chances_mc_png(
                    team,
                    pct,
                    nota=f"OBJETIVO RESUELTO · {view}",
                    verdict_override="YA CLASIFICÓ" if view == "Libertadores" else "OBJETIVO CUMPLIDO",
                ),
                use_container_width=True,
            )
            ui_markdown(f"**{team}:** {focus_result.get('message') or 'objetivo ya resuelto.'}")
            if focus_result.get("via"):
                ui_caption(f"Vía: **{focus_result['via']}**. Esta marca es exacta; no sale de una simulación.")
        else:
            pct = float(focus_result.get("qualification_percentage", 0.0) or 0.0)
            st.image(
                placa_chances_mc_png(
                    team,
                    pct,
                    nota=f"ESTIMADO · {_LPF_PUBLIC_MC_RUNS:,} simulaciones · {view}",
                ),
                use_container_width=True,
            )
    if probability_rows:
        ui_markdown(
            _html_tabla(
                cup_probability_heatmap_spec(
                    probability_rows,
                    active_objective=objective,
                    focus_team=team,
                    simulations=int(probability_package.get("simulations", _LPF_PUBLIC_MC_RUNS)),
                )
            ),
            unsafe_allow_html=True,
        )
        if probability_package.get("headline"):
            ui_markdown(probability_package["headline"])
        ui_caption(probability_package.get("note") or "Estimación Monte Carlo de Copas.")
        with st.expander("Ver probabilidades en tabla", expanded=False):
            ui_dataframe(pd.DataFrame(probability_rows), use_container_width=True, hide_index=True)

    ui_markdown("#### ESTIMADO · la otra cancha")
    ui_caption(
        "Muestra qué partidos ajenos mueven más la chance del objetivo. La barra es diferencia en puntos porcentuales entre desenlaces, no probabilidad del resultado."
    )
    other_cache_key = f"viz_cup_other_{view}_{team}"
    if st.button(
        "Calcular partidos que más ayudan o perjudican",
        key=f"viz_cup_other_button_{view}_{team}",
        use_container_width=True,
    ):
        try:
            cup_objective = "libertadores" if view == "Libertadores" else "al_menos_sudamericana"
            text, frame, crosses = lpf_conviene_obj(
                team, cup_objective, ctx, E.get("pendientes") or [], E.get("jugados") or [], scope="official_round"
            )
            st.session_state[other_cache_key] = {
                "text": text or "",
                "rows": frame.to_dict("records") if isinstance(frame, pd.DataFrame) else [],
                "crosses": crosses.to_dict("records") if isinstance(crosses, pd.DataFrame) else [],
            }
        except Exception as exc:
            st.session_state.pop(other_cache_key, None)
            ui_warning(f"No pude calcular la otra cancha de Copas: {exc}")

    other = st.session_state.get(other_cache_key) or {}
    if other.get("text"):
        ui_markdown(other["text"])
    other_rows = list(other.get("rows") or [])
    if other_rows:
        frame = pd.DataFrame(other_rows)
        if {"Partido", "Diferencia"} <= set(frame.columns):
            impact = frame[["Partido", "Diferencia"]].copy()
            impact["Impacto (pp)"] = pd.to_numeric(
                impact["Diferencia"].astype("string").str.replace(" pp", "", regex=False).str.replace(",", ".", regex=False),
                errors="coerce",
            )
            impact = impact.dropna(subset=["Impacto (pp)"])
            if not impact.empty:
                st.bar_chart(impact.set_index("Partido")[["Impacto (pp)"]])
        with st.expander("Ver detalle de la otra cancha", expanded=False):
            ui_dataframe(frame, use_container_width=True, hide_index=True)
    crosses = list(other.get("crosses") or [])
    if crosses:
        with st.expander("Cruces futuros entre competidores", expanded=False):
            ui_dataframe(pd.DataFrame(crosses), use_container_width=True, hide_index=True)


def render_visualizations_workspace(E):
    """Laboratorio visual conectado al mismo motor que los informes y el chat."""
    ui_markdown("## Visualizaciones")
    ui_caption("Cada vista responde una pregunta concreta. Exacto y estimado aparecen separados.")
    Z = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    teams = sorted(E.get("equipos") or [])
    if not teams:
        ui_warning("Cargá la LPF primero.")
        return
    team = ui_selectbox("Equipo", teams, index=teams.index("River Plate") if "River Plate" in teams else 0, key="viz_team")
    lab = lpf_zona_de_equipo(team, Z)
    tab_team, tab_zone, tab_comp, tab_round, tab_other, tab_radar = st.tabs([
        "Equipo", "Zona", "Copas y descenso", "Próximo partido", "La otra cancha", "Últimas fechas"
    ])

    with tab_team:
        base = Z[lab]
        table = liga_tabla_df(base)
        current = int(base[team]["pts"])
        cutoff = int(table.iloc[7]["PTS"])
        ceiling = current + 3 * int(rest.get(team, 0))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Actual", current)
        c2.metric("Corte actual", cutoff, delta=current-cutoff)
        c3.metric("Puntos disponibles", 3 * int(rest.get(team, 0)))
        c4.metric("Techo", ceiling)
        chart = pd.DataFrame({
            "Referencia": ["Actual", "Corte actual", "Techo"],
            "Puntos": [current, cutoff, ceiling],
        }).set_index("Referencia")
        st.bar_chart(chart)
        ui_caption("El mínimo que asegura no se aproxima. Cuando el motor exacto está disponible, ‘Calcular escalera exacta’ muestra el menor puntaje que asegura la clasificación.")
        if st.button("Calcular escalera exacta", key="viz_ladder", use_container_width=True):
            _render_point_ladder(team, base, rest, pending, 8, f"{team} · puntos y clasificación")

    with tab_zone:
        base = Z[lab]
        zone_table = liga_tabla_df(base).copy()
        zone_table["Estado"] = np.where(zone_table["Pos"] <= 8, "Dentro", "Fuera")
        ui_dataframe(zone_table, use_container_width=True, hide_index=True, height=560)
        points_chart = zone_table[["Equipo", "PTS"]].set_index("Equipo")
        st.bar_chart(points_chart)
        ui_markdown(f"**Corte:** {zone_table.iloc[7]['Equipo']} con {int(zone_table.iloc[7]['PTS'])} puntos. "
                    f"Primero afuera: {zone_table.iloc[8]['Equipo']} con {int(zone_table.iloc[8]['PTS'])}.")

    with tab_comp:
        _comp_view = st.radio(
            "Panorama", ["Libertadores", "Sudamericana", "Descenso"], horizontal=True, key="viz_comp_view"
        )
        if _comp_view in ("Libertadores", "Sudamericana"):
            _render_cup_visual_dashboard(E, team, _comp_view)
        else:
            ui_markdown(lpf_relato_descenso_texto(
                Z, rest, E.get("apertura") or {}, st.session_state.get("PROMEDIOS") or {},
                E.get("n_anual", 1), E.get("n_prom", 1),
            ))

    with tab_round:
        annual = lpf_anual_base(Z, E.get("apertura") or {})
        _viz_preview_label = st.radio(
            "Alcance",
            ["Próximo partido real", "Día del próximo partido", "Fecha oficial específica", "Fecha + postergados"],
            horizontal=True,
            key="viz_preview_scope",
        )
        _viz_preview_scope = {
            "Próximo partido real": "next_team_match",
            "Día del próximo partido": "next_team_day",
            "Fecha oficial específica": "official_round",
            "Fecha + postergados": "extended_window",
        }[_viz_preview_label]
        _viz_rounds = sorted({f for _match, f in _lpf_fecha_de(pending).items() if f is not None})
        _viz_preview_round = None
        if _viz_preview_scope in ("official_round", "extended_window") and _viz_rounds:
            _viz_preview_round = st.selectbox(
                "Fecha oficial para la Previa", _viz_rounds, format_func=lambda value: f"Fecha {value}",
                key="viz_preview_round",
            )
        text, frame = lpf_previa_equipo_texto(
            team, Z, rest, pending, annual, st.session_state.get("PROMEDIOS") or {},
            fecha=_viz_preview_round, scope=_viz_preview_scope, objective=_lpf_objective_label(),
        )
        if text:
            ui_markdown(text)
        if frame is not None:
            ui_dataframe(frame, use_container_width=True, hide_index=True)
            zone_frame = frame[frame["Tabla"].str.contains("Playoffs")].copy()
            if not zone_frame.empty:
                zone_frame["Mejor"] = zone_frame["Mejor puesto"].str.replace("º", "", regex=False).astype(int)
                zone_frame["Peor"] = zone_frame["Peor puesto"].str.replace("º", "", regex=False).astype(int)
                zone_frame = zone_frame.set_index("Si River" if team == "River Plate" else f"Si {team}")[["Mejor", "Peor"]]
                st.bar_chart(zone_frame)
                ui_caption("En puestos, una barra menor es mejor. El intervalo abre los desempates futuros.")

    with tab_other:
        _other_c1, _other_c2 = st.columns([1, 1.4])
        with _other_c1:
            _sync_lpf_objective_widget("viz_other_objective")
            _viz_other_obj = st.radio(
                "Objetivo",
                _LPF_OBJECTIVE_UI_OPTIONS,
                key="viz_other_objective",
                on_change=_lpf_objective_widget_changed,
                args=("viz_other_objective",),
            )
        with _other_c2:
            _viz_other_label = st.radio(
                "Partidos a analizar",
                ["Día del próximo partido", "Fecha oficial específica", "Fecha + postergados"],
                horizontal=True,
                key="viz_other_scope",
            )
        _viz_other_scope = {
            "Día del próximo partido": "next_team_day",
            "Fecha oficial específica": "official_round",
            "Fecha + postergados": "extended_window",
        }[_viz_other_label]
        _viz_other_rounds = sorted({f for _match, f in _lpf_fecha_de(pending).items() if f is not None})
        _viz_other_round = None
        if _viz_other_scope in ("official_round", "extended_window") and _viz_other_rounds:
            _viz_other_round = st.selectbox(
                "Fecha oficial para la otra cancha", _viz_other_rounds,
                format_func=lambda value: f"Fecha {value}", key="viz_other_round",
            )
        if _viz_other_obj == "Playoffs":
            text, frame = lpf_otros_resultados_sim(
                team, Z, rest, pending, jugados=E.get("jugados") or [],
                scope=_viz_other_scope, fecha=_viz_other_round,
            )
            crosses = None
        else:
            _other_domain = "descenso" if _viz_other_obj == "Descenso" else "copas"
            _other_gate = _lpf_data_gate(E, _other_domain)
            if _other_gate:
                ui_warning(_other_gate[1])
                text, frame, crosses = None, None, None
            else:
                _other_ctx = _lpf_ctx(
                    Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                    E.get("intl") or ("", ""), st.session_state.get("PROMEDIOS") or {},
                    E.get("n_anual", 1), E.get("n_prom", 1),
                )
                _other_obj = {
                    "Libertadores": "libertadores",
                    "Al menos Sudamericana": "al_menos_sudamericana",
                    "Descenso": "descenso",
                }[_viz_other_obj]
                text, frame, crosses = lpf_conviene_obj(
                    team, _other_obj, _other_ctx, pending, E.get("jugados") or [],
                    scope=_viz_other_scope, fecha=_viz_other_round,
                )
        if text:
            ui_markdown(text)
        if frame is not None and not frame.empty:
            ui_dataframe(frame, use_container_width=True, hide_index=True)
            impact = frame[["Partido", "Diferencia"]].copy()
            impact["Impacto (pp)"] = pd.to_numeric(
                impact["Diferencia"].astype("string").str.replace(" pp", "", regex=False).str.replace(",", ".", regex=False),
                errors="coerce",
            )
            impact = impact.dropna(subset=["Impacto (pp)"])
            if not impact.empty:
                st.bar_chart(impact.set_index("Partido")[["Impacto (pp)"]])
            else:
                ui_caption("No hay valores numéricos de impacto disponibles para graficar.")
        if crosses is not None and not crosses.empty:
            ui_markdown("#### Cruces futuros entre competidores")
            ui_dataframe(crosses, use_container_width=True, hide_index=True)

    with tab_radar:
        render_definition_radar(E)


def render_guided_workspace(E):
    """Una sola puerta de entrada para no depender de memorizar comandos de chat."""
    ui_markdown("## Panel por equipo")
    ui_caption("Elegí un equipo y un objetivo una sola vez. Después recorré las vistas sin memorizar preguntas ni comandos del chat.")
    report = _lpf_refresh_quality(E)
    status = {"ok": "🟢 Datos listos", "warning": "🟡 Datos con advertencias", "blocked": "🔴 Hay cálculos bloqueados"}[report.level]
    ui_markdown(f"**{status}** · Elegí **Datos y auditoría** en la barra superior para ver el detalle")

    Z = E.get("zonas_lpf") or {}
    teams = sorted(E.get("equipos") or [])
    pending = E.get("pendientes") or []
    _guide_rounds = sorted({f for _match, f in _lpf_fecha_de(pending).items() if f is not None})
    if not teams:
        ui_warning("Primero cargá la LPF desde el panel lateral.")
        return
    c1, c2, c3 = st.columns([1.15, 1.15, 1.7])
    team = c1.selectbox("Equipo", teams, index=teams.index("River Plate") if "River Plate" in teams else 0, key="guide_team")
    _sync_lpf_objective_widget("guide_objective")
    objective = c2.selectbox(
        "Objetivo", _LPF_OBJECTIVE_UI_OPTIONS, key="guide_objective",
        on_change=_lpf_objective_widget_changed, args=("guide_objective",),
    )
    task = c3.selectbox("Vista", [
        "Resumen completo",
        "Situación general del equipo",
        "Panorama narrativo de la competencia",
        "Cómo puede terminar el próximo partido o la fecha",
        "Qué necesita para alcanzar el objetivo",
        "Qué resultados ajenos le convienen",
        "Escalera exacta: mínimo que asegura y caminos con menos",
        "Comparar con otro equipo",
        "Cómo viene su zona",
        "Radar de las últimas fechas",
        "Herramientas de escenarios adaptadas del Mundial",
    ], key="guide_task")
    scope = "next_team_match"
    preview_round = None
    other_scope = "next_team_day"
    other_round = None
    if task == "Cómo puede terminar el próximo partido o la fecha":
        scope_label = st.radio(
            "Alcance",
            ["Próximo partido real", "Día del próximo partido", "Fecha oficial específica", "Sólo postergados", "Fecha + postergados"],
            horizontal=True,
            key="guide_scope",
        )
        scope = {
            "Próximo partido real": "next_team_match",
            "Día del próximo partido": "next_team_day",
            "Fecha oficial específica": "official_round",
            "Sólo postergados": "postponed_only",
            "Fecha + postergados": "extended_window",
        }[scope_label]
        if scope in ("official_round", "extended_window") and _guide_rounds:
            preview_round = st.selectbox(
                "Fecha oficial para la Previa", _guide_rounds, format_func=lambda value: f"Fecha {value}",
                key="guide_preview_round",
            )
    if task == "Qué resultados ajenos le convienen":
        other_label = st.radio(
            "Partidos a analizar",
            ["Día del próximo partido", "Fecha oficial específica", "Fecha + postergados"],
            horizontal=True,
            key="guide_other_scope",
        )
        other_scope = {
            "Día del próximo partido": "next_team_day",
            "Fecha oficial específica": "official_round",
            "Fecha + postergados": "extended_window",
        }[other_label]
        if other_scope in ("official_round", "extended_window") and _guide_rounds:
            other_round = st.selectbox(
                "Fecha oficial para la otra cancha", _guide_rounds, format_func=lambda value: f"Fecha {value}",
                key="guide_other_round",
            )
    other = None
    if task == "Comparar con otro equipo":
        other = ui_selectbox("Segundo equipo", [x for x in teams if x != team], key="guide_other")

    ui_caption("Las consultas habituales están reunidas en este panel. Para preguntas excepcionales o redacción libre, usá **Mesa de redacción → Consultas y chat**.")
    rest = E.get("rest") or {}
    annual = lpf_anual_base(Z, E.get("apertura") or {})
    previous = st.session_state.get("PROMEDIOS") or {}
    lab = lpf_zona_de_equipo(team, Z)
    _needed_domain = "playoffs"
    if task == "Herramientas de escenarios adaptadas del Mundial":
        _needed_domain = "playoffs"
    elif objective in ("Libertadores", "Al menos Sudamericana") or task == "Comparar con otro equipo":
        _needed_domain = "copas" if objective in ("Libertadores", "Al menos Sudamericana") else "playoffs"
    elif objective == "Descenso":
        _needed_domain = "descenso"
    _gate = _lpf_data_gate(E, _needed_domain)
    if _gate and task not in ("Cómo viene su zona", "Panorama narrativo de la competencia", "Radar de las últimas fechas"):
        ui_warning(_gate[1])
        return

    if task == "Resumen completo":
        ui_markdown(ficha_liga_texto(team, Z[lab], rest, pending, LPF_ZONAS_PLAYOFF))
        ui_markdown("### Próximo partido")
        _preview_text, _preview_frame = lpf_previa_equipo_texto(
            team, Z, rest, pending, annual, previous, scope="next_team_match", objective=objective
        )
        if _preview_text:
            ui_markdown(_preview_text)
        if _preview_frame is not None:
            ui_dataframe(_preview_frame, use_container_width=True, hide_index=True)
        with st.expander(f"Qué necesita para {objective.lower()}", expanded=False):
            ui_markdown(_lpf_editorial_need_text(E, team, objective, lab))
        with st.expander("Cómo está la competencia", expanded=False):
            if objective == "Playoffs":
                ui_markdown(lpf_relato_zona_texto(Z, lab, rest))
            elif objective == "Libertadores":
                ui_markdown(lpf_relato_libertadores_texto(
                    Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                    E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                    E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
                ))
            elif objective == "Al menos Sudamericana":
                ui_markdown(lpf_relato_sudamericana_texto(
                    Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                    E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                    E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
                ))
            else:
                ui_markdown(lpf_relato_descenso_texto(
                    Z, rest, E.get("apertura") or {}, previous, E.get("n_anual", 1), E.get("n_prom", 1)
                ))
    elif task == "Situación general del equipo":
        ui_markdown(ficha_liga_texto(team, Z[lab], rest, pending, LPF_ZONAS_PLAYOFF))
    elif task == "Panorama narrativo de la competencia":
        if objective == "Playoffs":
            ui_markdown(lpf_relato_zona_texto(Z, lab, rest))
        elif objective == "Libertadores":
            ui_markdown(lpf_relato_libertadores_texto(
                Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
            ))
        elif objective == "Al menos Sudamericana":
            ui_markdown(lpf_relato_sudamericana_texto(
                Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""),
                E.get("intl") or ("", ""), E.get("copa_arg_vivos") or [],
                E.get("copa_arg_updated", ""), E.get("copa_arg_source", ""),
            ))
        else:
            ui_markdown(lpf_relato_descenso_texto(
                Z, rest, E.get("apertura") or {}, previous, E.get("n_anual", 1), E.get("n_prom", 1)
            ))
    elif task == "Cómo puede terminar el próximo partido o la fecha":
        text, frame = lpf_previa_equipo_texto(
            team, Z, rest, pending, annual, previous, fecha=preview_round, scope=scope, objective=objective
        )
        if text: ui_markdown(text)
        if frame is not None: ui_dataframe(frame, use_container_width=True, hide_index=True)
    elif task == "Qué necesita para alcanzar el objetivo":
        ui_markdown(_lpf_editorial_need_text(E, team, objective, lab))
        with st.expander("Resumen operativo · contrato público v1", expanded=False):
            try:
                ui_markdown(_lpf_service_need_text(E, team, objective, lab))
                ui_caption("Resumen JSON-safe usado por API y auditoría; el informe editorial completo es el bloque principal de arriba.")
            except _LPFServiceContractError as exc:
                _record_lpf_service_fallback("objective_need_service_summary", exc)
                ui_caption("El resumen del contrato público no está disponible; el informe editorial principal sigue siendo válido.")
    elif task == "Qué resultados ajenos le convienen":
        if objective == "Playoffs":
            text, frame = lpf_otros_resultados_sim(
                team, Z, rest, pending, jugados=E.get("jugados") or [], scope=other_scope, fecha=other_round
            )
            if text: ui_markdown(text)
            if frame is not None: ui_dataframe(frame, use_container_width=True, hide_index=True)
        else:
            ctx = _lpf_ctx(Z, rest, E.get("apertura") or {}, E.get("camps") or ("", "", ""), E.get("intl") or ("", ""), previous, E.get("n_anual", 1), E.get("n_prom", 1))
            obj = {"Libertadores": "libertadores", "Al menos Sudamericana": "al_menos_sudamericana", "Descenso": "descenso"}[objective]
            text, frame, crosses = lpf_conviene_obj(
                team, obj, ctx, pending, E.get("jugados") or [], scope=other_scope, fecha=other_round
            )
            if text: ui_markdown(text)
            if frame is not None: ui_dataframe(frame, use_container_width=True, hide_index=True)
            if crosses is not None: ui_dataframe(crosses, use_container_width=True, hide_index=True)
    elif task == "Escalera exacta: mínimo que asegura y caminos con menos":
        if objective != "Playoffs":
            ui_info("La escalera exacta está habilitada para playoffs. En copas, el mínimo que asegura sólo se muestra cuando fue comprobado; si no, figura como todavía no calculado.")
        _render_point_ladder(team, Z[lab], rest, pending, 8, f"{team} · clasificación a playoffs")
    elif task == "Comparar con otro equipo":
        base_all = {team_name: row for base in Z.values() for team_name, row in base.items()}
        ui_dataframe(liga_comparar_df(team, other, base_all, rest, LPF_ZONAS_PLAYOFF), use_container_width=True, hide_index=True)
    elif task == "Cómo viene su zona":
        ui_markdown(lpf_relato_zona_texto(Z, lab, rest))
        ui_dataframe(_rd_competition_table(Z[lab], rest, 8), use_container_width=True, hide_index=True, height=560)
    elif task == "Radar de las últimas fechas":
        render_definition_radar(E)
    else:
        render_scenarios_workspace(E, default_team=team, embedded=True)


# ─── CONFIG DEL LLM EN EL PANEL LATERAL ──────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.subheader("🤖 Asistente (LLM)")
    st.session_state.LLM_ON = st.toggle(
        "Interpretar preguntas con Claude", value=st.session_state.LLM_ON,
        help="Si lo activás, entiende preguntas más libres. Las cuentas siempre las hace el motor.")
    if st.session_state.LLM_ON:
        st.session_state.LLM_KEY = st.text_input(
            "Anthropic API key", value=st.session_state.LLM_KEY, type="password", placeholder="sk-ant-...")
        st.session_state.LLM_MODEL = st.text_input(
            "Modelo", value=st.session_state.LLM_MODEL,
            help="Ej.: claude-haiku-4-5 (rápido y barato), claude-sonnet-4-6, claude-opus-4-8.")
        if not str(st.session_state.LLM_KEY).strip():
            ui_caption("Sin key, uso el router por palabras clave.")
        if st.session_state.get("LLM_ERROR"):
            ui_warning(f"Último error del asistente: {st.session_state['LLM_ERROR']}")
            ui_caption("Si dice 'model'/'404', revisá el nombre del modelo. Si dice '401'/'authentication', es la API key. "
                       "El chat funciona igual por palabras clave (escribí «ayuda»).")
    if st.button("🧹 Limpiar conversación", use_container_width=True):
        st.session_state.chat = [{"role": "assistant", "blocks": [("md", BIENVENIDA)]}]
        st.rerun()


_WORKSPACES = [
    "🧭 Panel por equipo",
    "🎯 Escenarios",
    "🗞️ Mesa de redacción",
    "📊 Visualizaciones",
    "🧪 Datos y auditoría",
    "🎯 Puntos por objetivo",
]
if st.session_state.get("workspace_nav") == "💬 Chat libre":
    st.session_state["workspace_nav"] = "🗞️ Mesa de redacción"
elif st.session_state.get("workspace_nav") not in _WORKSPACES:
    st.session_state["workspace_nav"] = _WORKSPACES[0]


def _prom_totales_para_pisos(anual, Z):
    """Adaptador Streamlit para los totales puros usados por promedios."""
    return promedio_totales(anual, Z, st.session_state.get("PROMEDIOS") or {})


def _pisos_frame(pisos):
    """DataFrame legible a partir de una lista de objetivos."""
    filas = []
    for p in pisos:
        if not p.aplica:
            continue
        filas.append({
            "Objetivo": p.nombre.capitalize(),
            "Hoy": p.puntos_hoy,
            "Techo": p.techo,
            "Mínimo posible": p.minimo_posible if p.minimo_posible is not None else "—",
            "Mínimo que asegura": _piso_garantia_exacta(p) if _piso_garantia_exacta(p) is not None else "—",
            "Total seguro": _piso_referencia_conservadora(p) if _piso_referencia_conservadora(p) is not None else "—",
            "Tipo de dato": (
                "Mínimo exacto" if _piso_garantia_exacta(p) is not None
                else ("Total seguro" if _piso_referencia_conservadora(p) is not None else "—")
            ),
            "Lectura": p.lectura(),
        })
    return pd.DataFrame(filas)


def _lpf_service_floor_row(label, result, *, points=None, remaining=None, include_team=False, team=None, descent=False):
    """Fila editorial estable a partir de ``objective_points``/``relegation``."""
    result = result or {}
    team_name = str(team or (result.get("team") if isinstance(result.get("team"), str) else "") or "")
    resolved = bool(result.get("resolved"))
    current = result.get("puntos_hoy", points)
    ceiling = result.get("techo")
    if ceiling is None and current is not None and remaining is not None:
        ceiling = int(current) + 3 * int(remaining)
    guarantee = result.get("minimum_guarantee")
    conservative = result.get("conservative_reference")
    if resolved:
        guarantee = None
        conservative = None
        reading = result.get("message") or "Objetivo ya resuelto por otra vía."
        data_type = "Vía directa"
    else:
        reading = result.get("reading") or result.get("detalle") or ""
        data_type = "Mínimo exacto" if guarantee is not None else ("Total seguro" if conservative is not None else "—")
    row = {
        "Objetivo": label,
        "Hoy": current if current is not None else "—",
        "Techo": ceiling if ceiling is not None else "—",
        "Mínimo posible": result.get("minimum_possible") if result.get("minimum_possible") is not None else "—",
        "Mínimo que asegura": guarantee if guarantee is not None else "—",
        "Total seguro": conservative if conservative is not None else "—",
        "Tipo de dato": data_type,
        "Lectura": reading,
    }
    if include_team:
        row = {
            "Equipo": team_name,
            "PTS": current if current is not None else "—",
            "Restan": int(remaining or 0),
            "Techo": ceiling if ceiling is not None else "—",
            "Mínimo posible": row["Mínimo posible"],
            "Mínimo que asegura": row["Mínimo que asegura"],
            "Total seguro": row["Total seguro"],
            "Tipo de dato": row["Tipo de dato"],
            "Estado": (
                (
                    "Ya tiene Libertadores"
                    if str(result.get("status") or "") == "already_qualified_higher_competition"
                    else "Ya clasificado por otra vía"
                ) if resolved
                else (
                    {"in": "Salvado", "out": "En zona de baja", "pelea": "En riesgo"}
                    if descent else {"in": "Asegurado", "out": "Sin chances", "pelea": "En carrera"}
                ).get(str(result.get("estado") or ""), str(result.get("estado") or "—"))
            ),
        }
    return row


def _lpf_service_team_objectives(E, team, zone):
    """Cuatro objetivos del panel usando sólo operaciones públicas."""
    entries = []
    for label, code in (("Playoffs", "playoffs"), ("Libertadores", "libertadores"),
                        ("Al menos Sudamericana", "sudamericana")):
        payload = {"team": team, "objective": code}
        if code == "playoffs":
            payload["zone"] = zone
        result = _lpf_service_result("objective_points", E, **payload)
        entries.append({"key": code, "label": label, "result": result})
    relegation = _lpf_service_result("relegation", E, team=team)
    if isinstance(relegation.get("team"), dict):
        entries.append({"key": "descenso", "label": "No descender", "result": relegation["team"]})
    return entries


def _lpf_service_objective_table_rows(E, ordered_teams, *, objective=None, zone=None, descent=False):
    """Tabla masiva de puntos usando la operación pública ``competition_batch``."""
    queries = []
    for team in ordered_teams:
        if descent:
            query = {"id": team, "type": "descent_points", "team": team}
        else:
            query = {"id": team, "type": "objective_points", "team": team, "objective": objective}
            if objective == "playoffs":
                query["zone"] = zone
        queries.append(query)
    batch = _lpf_service_result("competition_batch", E, queries=queries)
    rows = []
    annual = E.get("anual_directo") or {}
    zones = E.get("zonas_lpf") or {}
    rest = E.get("rest") or {}
    for item in batch.get("queries") or []:
        team = str(item.get("id") or "")
        result = item.get("result") or {}
        base = (zones.get(zone) or {}) if objective == "playoffs" else annual
        points = int((base.get(team) or {}).get("pts", 0)) if team in base else None
        rows.append(_lpf_service_floor_row(
            "", result, points=points, remaining=rest.get(team, 0), include_team=True, team=team, descent=descent
        ))
    return rows


def render_pisos_workspace(E):
    """Puerta de entrada simple: los puntos necesarios para todos los objetivos de un equipo.

    Responde de una sola vez la pregunta más frecuente —«¿cuántos puntos necesita
    para clasificar / entrar a una copa / no descender?»— sin recordar comandos.
    """
    ui_markdown("## Puntos necesarios por objetivo")
    ui_caption(
        "Cuántos puntos necesita cada equipo. **Mínimo posible** = el menor total con el que todavía existe "
        "algún escenario favorable. **Mínimo que asegura** = el menor total comprobado que asegura el objetivo. "
        "**Total seguro** = un total que sabemos que alcanza antes de calcular el mínimo exacto. "
        "Puede pedir puntos de más: todavía no sabemos si es el menor total que asegura."
    )

    Z = E.get("zonas_lpf") or {}
    teams = sorted(E.get("equipos") or [])
    if not Z or not teams:
        ui_warning("Primero cargá la LPF desde el panel lateral.")
        return

    rest = E.get("rest") or {}
    pending = E.get("pendientes") or []
    apertura = E.get("apertura") or {}
    anual = lpf_anual_base(Z, apertura)
    P = lpf_plazas_copas(Z, apertura, E.get("camps") or ("", "", ""), E.get("intl") or ("", ""))
    reducida = P.get("reducida") or []
    n_lib = P.get("n_tabla_lib", 0)
    n_anual = int(E.get("n_anual", 1))
    n_prom = int(E.get("n_prom", 1))
    prom_totales = _prom_totales_para_pisos(anual, Z)

    modo = st.radio(
        "¿Qué querés ver?",
        ["Un equipo, todos sus objetivos", "Todos los equipos, un objetivo"],
        horizontal=True, key="pisos_modo",
    )

    if modo == "Un equipo, todos sus objetivos":
        idx = teams.index("River Plate") if "River Plate" in teams else 0
        team = st.selectbox("Equipo", teams, index=idx, key="pisos_team")
        lab = lpf_zona_de_equipo(team, Z)
        service_entries = None
        pisos = None
        try:
            service_entries = _lpf_service_team_objectives(E, team, lab)
        except _LPFServiceContractError as exc:
            _record_lpf_service_fallback("objective_points", exc)
            pisos = pisos_de_equipo(
                Z, anual, reducida, n_lib, rest, pending, team,
                n_anual=n_anual, prom_totales=prom_totales, n_prom=n_prom,
            )

        if service_entries is not None:
            rows = []
            for entry in service_entries:
                base_for_points = Z.get(lab, {}) if entry["key"] == "playoffs" else anual
                points = int((base_for_points.get(team) or {}).get("pts", 0)) if team in base_for_points else None
                rows.append(_lpf_service_floor_row(
                    entry["label"], entry["result"], points=points, remaining=rest.get(team, 0)
                ))
            frame = pd.DataFrame(rows)
        else:
            frame = _pisos_frame(pisos or [])

        if frame.empty:
            ui_info(f"{team} no tiene objetivos activos con los datos cargados.")
            return
        ui_dataframe(frame, use_container_width=True, hide_index=True)
        ui_caption("Esta vista ya consume el contrato público de servicios; Streamlit sólo transforma la respuesta JSON en tabla.")
        if service_entries is not None:
            has_cup = any(entry["key"] in {"libertadores", "sudamericana"} for entry in service_entries)
        else:
            has_cup = any(p.clave in {"libertadores", "sudamericana"} for p in (pisos or []))
        if has_cup:
            ui_caption(
                "En copas, los puntos cuantifican sólo la vía de **Tabla Anual**. "
                "Ganar el Clausura o la Copa Argentina puede dar una plaza por otra vía; "
                "si el equipo ya está clasificado directamente, se muestra como tal y no se le atribuye un mínimo de puntos."
            )
        max_left = max((int(rest.get(team, 0)), 0))
        if max_left > VENTANA_EXACTA:
            ui_caption(
                f"A {team} le quedan {max_left} partidos: todavía no se calcula el **mínimo que asegura**. "
                f"Por ahora se muestra un **total seguro**: si lo alcanza, asegura el objetivo. Puede pedir puntos de "
                f"más, porque todavía no sabemos si es el menor total que asegura. El cálculo exacto se activa con "
                f"{VENTANA_EXACTA} partidos restantes o menos."
            )

        # Escalera exacta: se lee del mismo resultado JSON cuando está disponible.
        if service_entries is not None:
            con_escalera = [entry for entry in service_entries if entry["result"].get("caminos")]
            if con_escalera:
                objetivo_esc = st.selectbox(
                    "Ver la escalera exacta de:", [entry["label"] for entry in con_escalera], key="pisos_escalera",
                )
                elegido = next(entry for entry in con_escalera if entry["label"] == objetivo_esc)
                filas_esc = []
                for pts, estado, ejemplo in elegido["result"].get("caminos") or []:
                    filas_esc.append({
                        "Puntos finales": pts,
                        "Situación": estado,
                        "Camino de ejemplo": ejemplo or ("No depende de otros resultados" if "arant" in estado else "—"),
                    })
                ui_markdown(f"**Escalera de {elegido['label'].lower()}** — del mínimo posible al mínimo que asegura:")
                ui_dataframe(pd.DataFrame(filas_esc), use_container_width=True, hide_index=True)
                ui_caption(
                    "«Clasificación condicionada» = alcanza con ese puntaje según cómo salgan otros partidos. "
                    "«Mínimo que asegura» = el menor total comprobado con el que entra sin depender de nadie ni de desempates."
                )
        else:
            con_escalera = [p for p in (pisos or []) if p.aplica and p.caminos]
            if con_escalera:
                objetivo_esc = st.selectbox(
                    "Ver la escalera exacta de:", [p.nombre.capitalize() for p in con_escalera], key="pisos_escalera",
                )
                elegido = next(p for p in con_escalera if p.nombre.capitalize() == objetivo_esc)
                filas_esc = []
                for pts, estado, ejemplo in elegido.caminos:
                    filas_esc.append({
                        "Puntos finales": pts, "Situación": estado,
                        "Camino de ejemplo": ejemplo or ("No depende de otros resultados" if "arant" in estado else "—"),
                    })
                ui_markdown(f"**Escalera de {elegido.nombre}** — del mínimo posible al mínimo que asegura:")
                ui_dataframe(pd.DataFrame(filas_esc), use_container_width=True, hide_index=True)

        any_prom = prom_totales is not None
        if not any_prom:
            ui_caption("Para sumar la exigencia por promedios, pegá la tabla de promedios en el panel lateral.")
    else:
        _old_cup_objective = st.session_state.get("pisos_obj_all")
        if _old_cup_objective == "Libertadores":
            st.session_state["pisos_obj_all"] = "Libertadores por Tabla Anual"
        elif _old_cup_objective == "Al menos Sudamericana":
            st.session_state["pisos_obj_all"] = "Al menos Sudamericana por Tabla Anual"
        objetivo = st.selectbox(
            "Objetivo",
            [
                "Playoffs (top 8 de zona)",
                "Libertadores por Tabla Anual",
                "Al menos Sudamericana por Tabla Anual",
                "No descender",
            ],
            key="pisos_obj_all",
        )
        try:
            if objetivo.startswith("Playoffs"):
                lab = st.selectbox("Zona", sorted(Z), key="pisos_zone")
                standings = _lpf_service_result("standings", E, objective="playoffs", zone=lab)
                orden = [row["team"] for row in standings.get("table") or []]
                filas = _lpf_service_objective_table_rows(E, orden, objective="playoffs", zone=lab)
                ui_dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True, height=520)
            elif objetivo == "No descender":
                if not anual:
                    ui_warning("Falta la Tabla Anual reconstruida para calcular el descenso.")
                    return
                standings = _lpf_service_result("standings", E, scope="annual")
                orden = [row["team"] for row in standings.get("table") or []]
                filas = _lpf_service_objective_table_rows(E, orden, descent=True)
                ui_dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True, height=520)
            else:
                if not anual:
                    ui_warning("Falta la Tabla Anual para calcular las copas.")
                    return
                code = "libertadores" if objetivo.startswith("Libertadores") else "sudamericana"
                standings = _lpf_service_result("standings", E, scope="annual")
                orden = [row["team"] for row in standings.get("table") or []]
                filas = _lpf_service_objective_table_rows(E, orden, objective=code)
                ui_dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True, height=520)
                ui_caption(
                    "Esta tabla calcula exclusivamente la ruta de **Tabla Anual**. "
                    "Los equipos con plaza directa aparecen separados; ganar Clausura o Copa Argentina puede abrir otra vía "
                    "que no se traduce en un mínimo de puntos de la Anual."
                )
            ui_caption("Tabla y pisos generados por `standings` + `competition_batch` del contrato público v1.")
        except _LPFServiceContractError as exc:
            _record_lpf_service_fallback("objective_table", exc)
            ui_warning(
                "No pude construir esta tabla por la frontera pública con la foto actual. "
                "Revisá Datos y auditoría; el error quedó registrado para diagnóstico."
            )

    ui_caption(
        f"El cálculo exacto se habilita por equipo cuando le quedan {VENTANA_EXACTA} partidos o menos. "
        "Antes de eso se informa un total seguro: si lo alcanza, asegura el objetivo. Puede ser más alto que el "
        "mínimo que asegura que se calculará después."
    )


def _go_to_workspace(workspace, scenario_tool=None):
    st.session_state["workspace_nav"] = workspace
    if scenario_tool is not None:
        st.session_state["scenario_tool_nav"] = scenario_tool


ui_markdown("### Accesos principales")
_main_cols = st.columns(len(_WORKSPACES))
for _col, _label in zip(_main_cols, _WORKSPACES):
    _col.button(
        _label,
        use_container_width=True,
        type="primary" if st.session_state["workspace_nav"] == _label else "secondary",
        key=f"workspace_button_{_label}",
        on_click=_go_to_workspace,
        args=(_label,),
    )

_SCENARIO_SHORTCUTS = [
    ("Gana / empata / pierde", "Gana / empata / pierde"),
    ("Qué pasa si…", "Qué pasa si…"),
    ("Puntos y puesto final", "Puntos y puesto final"),
    ("Mejor y peor caso", "Mejor y peor caso"),
    ("Distribución", "Distribución"),
    ("Clasificados / eliminados", "Clasificados y eliminados"),
]
ui_caption("Herramientas rápidas de Escenarios")
_scenario_cols = st.columns(len(_SCENARIO_SHORTCUTS))
for _col, (_button_label, _tool_label) in zip(_scenario_cols, _SCENARIO_SHORTCUTS):
    _col.button(
        _button_label,
        use_container_width=True,
        key=f"scenario_shortcut_{_tool_label}",
        on_click=_go_to_workspace,
        args=("🎯 Escenarios", _tool_label),
    )

_workspace = st.session_state["workspace_nav"]
if _workspace == "🎯 Puntos por objetivo":
    render_pisos_workspace(st.session_state.ESTADO)
    st.stop()
if _workspace == "🧭 Panel por equipo":
    render_guided_workspace(st.session_state.ESTADO)
    st.stop()
if _workspace == "🎯 Escenarios":
    render_scenarios_workspace(st.session_state.ESTADO)
    st.stop()
if _workspace == "🗞️ Mesa de redacción":
    render_newsroom(st.session_state.ESTADO)
    st.stop()
if _workspace == "📊 Visualizaciones":
    render_visualizations_workspace(st.session_state.ESTADO)
    st.stop()
if _workspace == "🧪 Datos y auditoría":
    render_data_audit(st.session_state.ESTADO)
    st.stop()
