"""Regresiones de integración estática entre Streamlit y los módulos extraídos."""
from __future__ import annotations

import ast
from pathlib import Path


MAIN = Path(__file__).resolve().parents[1] / "calculadora_futbol_argentino.py"


def _module_tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8"), filename=str(MAIN))


def test_refresh_quality_delega_revalidacion_completa_a_lpf_state():
    tree = _module_tree()
    refresh = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_lpf_refresh_quality"
    )
    called_names = {
        node.func.id
        for node in ast.walk(refresh)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "refresh_lpf_quality_state" in called_names
    assert "build_quality_report" not in called_names
    assert "add_source_issues" not in called_names


def test_refresh_lpf_quality_state_esta_importado_desde_lpf_state():
    tree = _module_tree()
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "lpf_state"
        for alias in node.names
    }
    assert "refresh_lpf_quality_state" in imports


def test_narrativa_de_pisos_usa_accesores_compatibles():
    tree = _module_tree()
    direct = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"garantia_exacta", "referencia_conservadora"}
    ]
    # Los únicos accesos directos quedan encapsulados en los dos helpers de compatibilidad.
    assert len(direct) == 2

    frame = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_pisos_frame"
    )
    called = {
        node.func.id
        for node in ast.walk(frame)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_piso_garantia_exacta" in called
    assert "_piso_referencia_conservadora" in called


def test_espn_fixture_delega_la_ventana_http_fuera_de_streamlit():
    tree = _module_tree()
    fixture = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "espn_fixture"
    )
    called = {
        node.func.id
        for node in ast.walk(fixture)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "fetch_espn_scoreboard_window" in called


def test_futbolargentino_fixture_delega_orquestacion_http_fuera_de_streamlit():
    tree = _module_tree()
    fixture = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "futbolargentino_fixture"
    )
    called = {
        node.func.id
        for node in ast.walk(fixture)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "fetch_futbolargentino_results_pages" in called
    assert not any(
        isinstance(node, ast.Import) and any(alias.name == "time" for alias in node.names)
        for node in ast.walk(fixture)
    )


def test_tables_with_fallback_delega_politica_fuera_de_streamlit():
    tree = _module_tree()
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lpf_tables_with_fallback"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "select_lpf_tables" in called
    assert "_validate_lpf_tables" not in called


def test_respaldo_de_tablas_delega_persistencia_fuera_de_streamlit():
    tree = _module_tree()
    save = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_save_lpf_snapshot"
    )
    load = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_lpf_snapshot"
    )
    save_calls = {
        node.func.id
        for node in ast.walk(save)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    load_calls = {
        node.func.id
        for node in ast.walk(load)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"build_table_backup", "write_table_backup"} <= save_calls
    assert "load_table_backup" in load_calls
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) and (
            any(alias.name in {"json", "pathlib"} for alias in node.names)
            if isinstance(node, ast.Import) else node.module in {"json", "pathlib"}
        )
        for node in ast.walk(save)
    )


def test_rd_apply_results_delega_mutacion_y_cambios_fuera_de_streamlit():
    tree = _module_tree()
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_rd_apply_results"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "apply_completed_results" in called
    assert "table_position_changes" in called
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_rd_update_stats"
        for node in tree.body
    )


def test_anual_y_plazas_delegan_logica_fuera_de_streamlit():
    tree = _module_tree()
    annual = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lpf_anual_base"
    )
    slots = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lpf_plazas_copas"
    )
    annual_calls = {
        node.func.id
        for node in ast.walk(annual)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    slot_calls = {
        node.func.id
        for node in ast.walk(slots)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_qualification_annual_base" in annual_calls
    assert "sum_opening_and_zones" not in annual_calls
    assert "validate_annual" not in annual_calls
    assert "allocate_cup_slots" in slot_calls
    assert "liga_tabla_df" not in slot_calls


def test_contexto_de_copas_delega_normalizacion_fuera_de_streamlit():
    tree = _module_tree()
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {
            "_lpf_fixed_lib_qualifiers",
            "_lpf_copa_arg_alive_for_annual",
            "_lpf_copa_snapshot",
        }
    }
    assert set(funcs) == {
        "_lpf_fixed_lib_qualifiers",
        "_lpf_copa_arg_alive_for_annual",
        "_lpf_copa_snapshot",
    }
    calls = {
        name: {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        for name, node in funcs.items()
    }
    assert "_qualification_fixed_libertadores_qualifiers" in calls["_lpf_fixed_lib_qualifiers"]
    assert "_qualification_copa_argentina_alive" in calls["_lpf_copa_arg_alive_for_annual"]
    assert "_qualification_copa_snapshot_label" in calls["_lpf_copa_snapshot"]
    for node in funcs.values():
        assert "liga_tabla_df" not in {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }


def test_forma_y_fuerza_delegan_modelo_fuera_de_streamlit():
    tree = _module_tree()
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_res_letra", "forma_equipo", "racha_equipo", "_fuerza_lpf"}
    }
    assert set(funcs) == {"_res_letra", "forma_equipo", "racha_equipo", "_fuerza_lpf"}
    calls = {
        name: {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        for name, node in funcs.items()
    }
    assert "_form_result_letter" in calls["_res_letra"]
    assert "_team_form" in calls["forma_equipo"]
    assert "_team_streak" in calls["racha_equipo"]
    assert "_estimate_team_strength" in calls["_fuerza_lpf"]
    assert "np.median" not in ast.unparse(funcs["_fuerza_lpf"])


def test_mesa_de_redaccion_embebe_chat_y_el_radar_reusa_motores_existentes():
    tree = _module_tree()
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"render_newsroom", "render_chat_workspace", "render_definition_radar"}
    }
    assert set(funcs) == {"render_newsroom", "render_chat_workspace", "render_definition_radar"}

    newsroom_calls = {
        node.func.id
        for node in ast.walk(funcs["render_newsroom"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "render_chat_workspace" in newsroom_calls

    radar_calls = {
        node.func.id
        for node in ast.walk(funcs["render_definition_radar"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"lpf_previa_equipo_texto", "_render_point_ladder", "_render_radar_estimated_visuals"} <= radar_calls


def test_puntos_por_objetivo_aclara_via_anual_y_muestra_clasificados_directos():
    source = MAIN.read_text(encoding="utf-8")
    assert '"Libertadores por Tabla Anual"' in source
    assert '"Al menos Sudamericana por Tabla Anual"' in source
    assert '"Ya clasificado por otra vía"' in source
    assert '"Ya tiene Libertadores"' in source


def _function(name: str) -> ast.FunctionDef:
    tree = _module_tree()
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _service_operations(fn: ast.FunctionDef) -> set[str]:
    operations: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_lpf_service_result" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            operations.add(first.value)
    return operations


def test_previa_streamlit_consume_operacion_publica_preview():
    assert "preview" in _service_operations(_function("lpf_previa_equipo_texto"))


def test_ultimas_fechas_consume_paquete_publico_definition():
    assert "definition" in _service_operations(_function("_lpf_definition_package"))


def test_puntos_y_descenso_consumen_frontera_publica():
    assert _service_operations(_function("_lpf_service_team_objectives")) == {
        "objective_points", "relegation"
    }
    source = MAIN.read_text(encoding="utf-8")
    assert "'competition_batch'" in ast.unparse(_function("_lpf_service_objective_table_rows"))
    assert "'standings'" in ast.unparse(_function("render_pisos_workspace"))
    assert "_lpf_service_need_text" in source


def test_chance_destacada_pasa_por_objective_chances_y_declara_excepciones():
    newsroom = ast.unparse(_function("render_newsroom"))
    assert "'objective_chances'" in newsroom
    source = MAIN.read_text(encoding="utf-8")
    assert "la tabla comparativa completa conserva" in source
    assert "La probabilidad de descenso conserva por ahora la ruta de simulación contextual" in source


def test_auditoria_expone_fallbacks_del_contrato_publico():
    audit = ast.unparse(_function("render_data_audit"))
    assert "_lpf_service_capabilities" in audit
    assert "LPF_PUBLIC_SERVICE_FALLBACKS" in audit
    assert "Contrato público usado por Streamlit" in MAIN.read_text(encoding="utf-8")
