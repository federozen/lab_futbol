from pathlib import Path


def test_definition_radar_exposes_exact_conditionals_and_activation_window():
    source = Path("calculadora_futbol_argentino.py").read_text(encoding="utf-8")
    assert "Qué tiene que pasar esta fecha · EXACTO" in source
    assert "Visualizaciones → Últimas fechas → Condicionales de un equipo" in source
    assert "A partir de 4 partidos restantes" in source
    assert "Frecuencia combinatoria, NO probabilidad" in source
    assert "next_round_conditionals(base, rest, juegos, team, 8" in source


def test_definition_radar_keeps_estimated_other_results_separate():
    source = Path("calculadora_futbol_argentino.py").read_text(encoding="utf-8")
    assert "impacto Monte Carlo sigue separado como ESTIMADO" in source
    assert "ESTIMADO · diferencia entre el mejor y el peor desenlace" in source


def test_definition_radar_exposes_editorial_visual_suite_and_objectives():
    source = Path("calculadora_futbol_argentino.py").read_text(encoding="utf-8")
    for label in (
        "Zona de pelea",
        "Matriz de la fecha · todos los equipos que quieras seguir",
        "Semáforo compacto",
        "Matriz de rival clave",
        "Árbol reducido del camino",
        "Reloj de definición",
        "¿Por qué? · explicar gana / empata / pierde",
        "¿Por qué? · explicar un equipo de la matriz",
    ):
        assert label in source
    assert "Libertadores por Tabla Anual" in source
    assert "Al menos Sudamericana por Tabla Anual" in source
    assert "st.multiselect" in source


def test_definition_radar_does_not_present_new_visuals_as_probability():
    source = Path("calculadora_futbol_argentino.py").read_text(encoding="utf-8")
    assert "no usan probabilidades" in source
    assert "Los demás partidos de la fecha quedan abiertos y se enumeran exactamente" in source
