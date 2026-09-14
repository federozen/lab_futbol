"""Regresiones editoriales de la interfaz y narrativas LPF."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "calculadora_futbol_argentino.py").read_text(encoding="utf-8")
PISOS = (ROOT / "lpf_pisos.py").read_text(encoding="utf-8")
NARRATIVES = (ROOT / "lpf_competition_narratives.py").read_text(encoding="utf-8")
SCENARIOS = (ROOT / "lpf_scenarios.py").read_text(encoding="utf-8")


def test_interfaz_usa_tres_conceptos_editoriales_distintos():
    assert "🎯 Puntos por objetivo" in MAIN
    assert "Mínimo posible" in MAIN
    assert "Total seguro" in MAIN
    assert "Mínimo que asegura" in MAIN
    assert "Garantía exacta" not in MAIN
    assert "Referencia conservadora" not in MAIN
    assert "Puntaje que asegura" not in MAIN
    assert "Seguro (conservador)" not in MAIN
    assert "puntaje seguro (conservador)" not in MAIN.lower()
    assert "piso seguro" not in MAIN.lower()
    assert "piso ajustado" not in MAIN.lower()
    assert "Garantía matemática" not in SCENARIOS
    assert "Garantía exacta" not in SCENARIOS
    assert "Mínimo que asegura" in SCENARIOS
    assert "mínimo que garantiza" not in MAIN.lower()


def test_cota_no_aparece_en_interfaz_ni_narrativas_principales():
    for source in (MAIN, PISOS, NARRATIVES, SCENARIOS):
        assert re.search(r"\bcota\b", source, flags=re.IGNORECASE) is None


def test_ventana_exacta_no_vuelve_a_seis_fechas():
    assert "VENTANA_EXACTA = 8" in PISOS
    assert "if pend and gx <= VENTANA_EXACTA:" in MAIN
    assert "if pend and gx <= 6:" not in MAIN
    assert "remaining.get(team, 0))) <= VENTANA_EXACTA" in NARRATIVES
    assert "remaining.get(team, 0))) <= 6" not in NARRATIVES


def test_promedios_no_etiquetan_piso_techo_en_tabla_visible():
    assert '"Mínimo final": round(d["piso"], 3)' in MAIN
    assert '"Máximo final": round(d["techo"], 3)' in MAIN
    assert '"Piso": round(d["piso"], 3)' not in MAIN


def test_narrativa_explica_que_maximos_individuales_no_son_simultaneos():
    assert "Eso no significa que todos puedan hacerlo al mismo tiempo" in MAIN
    assert "máximos individuales son incompatibles entre sí" in MAIN
    assert "por eso no suma esos máximos individuales como si pudieran darse todos juntos" in MAIN


def test_total_seguro_explica_que_puede_no_ser_el_minimo():
    assert "Todavía no sabemos si" in MAIN
    assert "es el menor total que asegura" in MAIN
    assert "Puede que alcance con menos" in MAIN or "Puede alcanzar con menos" in MAIN


def test_escenarios_usa_nombre_claro_para_puntos_y_puesto_final():
    assert '"Puntos y puesto final"' in MAIN
    assert MAIN.count('"Puntaje y puesto"') == 1  # sólo migración de sesión vieja
    assert 'st.session_state.get("scenario_tool_nav") == "Puntaje y puesto"' in MAIN
    assert "¿Con cuántos puntos puede clasificar?" in MAIN
    assert "¿Con cuántos puntos suele terminar en un puesto específico?" in MAIN
    assert "¿Qué puesto querés analizar?" in MAIN


def test_busqueda_de_puesto_separa_estimacion_de_extremos_matematicos():
    assert "_sim_zone_rank_points" in MAIN
    assert "Mediana estimada" in MAIN
    assert "50% central" in MAIN
    assert "no es la mediana de los puntajes matemáticamente posibles" in MAIN
    assert "Mostrar también los extremos matemáticos (sin probabilidad)" in MAIN
    assert "can_finish_exact_rank_by_points" in MAIN
    assert "Esto no mide probabilidad" in MAIN
    assert "Mejor puesto con esos puntos" not in MAIN
    assert "Peor puesto con esos puntos" not in MAIN
    assert '"¿Puede ser ese puesto?": "Sí"' not in MAIN

def test_accesos_principales_deja_puntos_por_objetivo_al_final():
    block = re.search(r"_WORKSPACES = \[(.*?)\]", MAIN, flags=re.DOTALL)
    assert block is not None
    labels = re.findall(r'"([^"\n]+)"', block.group(1))
    assert labels[-1] == "🎯 Puntos por objetivo"
    assert labels[0] == "🧭 Panel por equipo"



def test_chat_libre_se_integra_en_mesa_de_redaccion():
    block = re.search(r"_WORKSPACES = \[(.*?)\]", MAIN, flags=re.DOTALL)
    assert block is not None
    labels = re.findall(r'"([^"\n]+)"', block.group(1))
    assert "💬 Chat libre" not in labels
    assert "🗞️ Mesa de redacción" in labels
    assert '"Consultas y chat"' in MAIN
    assert "render_chat_workspace(E)" in MAIN
    assert 'st.session_state.get("workspace_nav") == "💬 Chat libre"' in MAIN
    assert 'st.session_state["workspace_nav"] = "🗞️ Mesa de redacción"' in MAIN
    assert 'key="newsroom_chat_sim_toggle"' in MAIN


def test_ultimas_fechas_muestra_tablero_y_condicionales():
    assert '"Últimas fechas"' in MAIN
    assert "Últimas fechas · tablero de definición" in MAIN
    assert "Zona de pelea" in MAIN
    assert "Matriz de la fecha · todos los equipos que quieras seguir" in MAIN
    assert "Semáforo compacto" in MAIN
    assert "Matriz de rival clave" in MAIN
    assert "Árbol reducido del camino" in MAIN
    assert "Reloj de definición" in MAIN
    assert "¿Por qué? · explicar gana / empata / pierde" in MAIN
    assert "Abrir escalera exacta de puntos" in MAIN
    assert "lpf_otros_resultados_sim(" in MAIN
    assert "lpf_previa_equipo_texto(" in MAIN


def test_monte_carlo_publicable_usa_6000_y_no_rotulos_viejos():
    assert "_LPF_PUBLIC_MC_RUNS = 6000" in MAIN
    assert "n=_LPF_PUBLIC_MC_RUNS" in MAIN
    assert "Estimación por simulación (6.000 torneos)" in MAIN
    assert "Calcular ahora (6.000 simulaciones)" in MAIN
    assert "4.000 torneos" not in MAIN
    assert "8.000 temporadas" not in MAIN


def test_playoffs_distingue_pj_partidos_por_jugar_y_puntos_totales():
    tree = ast.parse(MAIN)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "lpf_playoffs_texto")
    segment = ast.get_source_segment(MAIN, fn) or ""
    assert "puntos totales en {pj} PJ" in segment
    assert "{gx} partidos por jugar" in segment
    assert 'L.append("### Partidos por jugar")' in segment
    assert 'L.append(f"- {rival}")' in segment
    assert "### Partidos pendientes" not in segment


def test_previa_por_equipo_expone_alcances_y_fecha_especifica():
    assert '"Alcance de la Previa"' in MAIN
    assert '["Próximo partido real", "Fecha oficial específica", "Fecha + postergados"]' in MAIN
    assert '"Fecha oficial específica": "official_round"' in MAIN
    assert '"Fecha + postergados": "extended_window"' in MAIN
    assert '"Fecha oficial para la Previa"' in MAIN
    assert "fecha=_preview_round" in MAIN
    assert "scope=_preview_scope" in MAIN


def test_probabilidades_playoffs_no_descartan_interzonales_reales():
    tree = ast.parse(MAIN)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "liga_probabilidades_df")
    segment = ast.get_source_segment(MAIN, fn) or ""
    assert "if a in idx or b in idx" in segment
    assert "sa = float(s.get(a, 1.0))" in segment
    assert "sb = float(s.get(b, 1.0))" in segment
    assert "if a in idx and b in idx" not in segment


def test_objetivo_activo_se_comparte_entre_chat_panel_redaccion_y_visualizaciones():
    assert '_LPF_OBJECTIVE_UI_OPTIONS = ("Playoffs", "Libertadores", "Al menos Sudamericana", "Descenso")' in MAIN
    assert '_sync_lpf_objective_widget("chat_guide_objective")' in MAIN
    assert '_sync_lpf_objective_widget("rd_report_objective")' in MAIN
    assert '_sync_lpf_objective_widget("viz_other_objective")' in MAIN
    assert '_sync_lpf_objective_widget("guide_objective")' in MAIN
    assert MAIN.count('on_change=_lpf_objective_widget_changed') >= 4
    assert 'El objetivo se conserva también en Panel por equipo, Visualizaciones y seguimientos del chat.' in MAIN


def test_explorador_no_fuerza_playoffs_en_atajos_genericos():
    tree = ast.parse(MAIN)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_chat_catalog")
    segment = ast.get_source_segment(MAIN, fn) or ""
    assert 'active_objective = _lpf_objective_label()' in segment
    assert 'need_prompt = _lpf_objective_prompt(team, "necesita")' in segment
    assert 'conviene_prompt = _lpf_objective_prompt(team, "conviene")' in segment
    assert '(f"Qué necesita · {active_objective}"' in segment
    assert '(f"Qué le conviene · {active_objective}"' in segment
    # Los accesos de la categoría Playoffs siguen siendo explícitos, pero el bloque
    # "Más usadas" ya no debe clavar el objetivo por su cuenta.
    more_used = segment.split('"⭐ Más usadas": [', 1)[1].split('],', 1)[0]
    assert 'para los playoffs' not in more_used


def test_parser_explicito_actualiza_la_memoria_por_un_unico_helper():
    tree = ast.parse(MAIN)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_objetivo_lpf")
    segment = ast.get_source_segment(MAIN, fn) or ""
    assert 'return _remember_lpf_objective(explicit)' in segment
    assert 'st.session_state["LPF_LAST_OBJECTIVE"] = explicit' not in segment


def test_previa_y_otra_cancha_comparten_fecha_oficial_especifica_en_todas_las_vistas():
    assert 'def _lpf_round_from_query(q):' in MAIN
    assert 'fecha=_lpf_round_from_query(q)' in MAIN
    assert 'scope=_lpf_scope_from_query(q, default="next_team_match")' in MAIN
    assert '"Fecha oficial para la Previa"' in MAIN
    assert '"Fecha oficial para la otra cancha"' in MAIN
    assert 'fecha=_viz_preview_round' in MAIN
    assert 'scope=_viz_other_scope, fecha=_viz_other_round' in MAIN
    assert 'fecha=preview_round, scope=scope, objective=objective' in MAIN
    assert 'scope=other_scope, fecha=other_round' in MAIN


def test_otra_cancha_no_recomienda_si_objetivo_ya_esta_cumplido_o_no_hay_riesgo():
    tree = ast.parse(MAIN)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "lpf_conviene_obj")
    segment = ast.get_source_segment(MAIN, fn) or ""
    assert 'equipo not in ctx["reducida"]' in segment
    assert 'ya tiene una plaza directa de Libertadores' in segment
    assert 'no corresponde recomendar una ‘otra cancha’' in segment
    assert 'risk, _ = _lpf_riesgo_descenso(equipo, ctx)' in segment
    assert 'no está hoy en la zona de riesgo usada por esta herramienta' in segment
    assert 'No publico una recomendación de otra cancha' in segment
