"""Regresiones del chequeo de compatibilidad de despliegue."""
from __future__ import annotations

from pathlib import Path

from lpf_runtime import CRITICAL_COMPONENTS, LPF_RUNTIME_API, runtime_compatibility, runtime_error_message


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "calculadora_futbol_argentino.py"


def test_runtime_actual_esta_sincronizado():
    report = runtime_compatibility(ROOT)
    assert report["ok"] is True
    assert report["mismatches"] == []
    assert len(report["checked"]) == len(CRITICAL_COMPONENTS)


def test_runtime_detecta_modulo_viejo_sin_importarlo(tmp_path):
    for filename in CRITICAL_COMPONENTS:
        (tmp_path / filename).write_text(f"LPF_RUNTIME_API = {LPF_RUNTIME_API}\n", encoding="utf-8")
    (tmp_path / "lpf_pisos.py").write_text("# copia vieja sin marcador\n", encoding="utf-8")

    report = runtime_compatibility(tmp_path)
    assert report["ok"] is False
    assert report["mismatches"] == [
        {"file": "lpf_pisos.py", "expected": LPF_RUNTIME_API, "found": None}
    ]
    assert "lpf_pisos.py" in runtime_error_message(report)


def test_main_chequea_runtime_antes_de_importar_modulos_sensibles():
    text = MAIN.read_text(encoding="utf-8")
    check_pos = text.index("_RUNTIME_REPORT = runtime_compatibility()")
    required_pos = text.index("if LPF_RUNTIME_API != _REQUIRED_RUNTIME_API:")
    stop_pos = text.index("st.stop()")
    pisos_import_pos = text.index("from lpf_pisos import")
    http_import_pos = text.index("from lpf_http import")
    schedule_import_pos = text.index("from lpf_schedule import")
    result_updates_import_pos = text.index("from lpf_result_updates import")
    qualification_import_pos = text.index("from lpf_qualification import")
    form_import_pos = text.index("from lpf_form import")
    simulation_import_pos = text.index("from lpf_simulation import")
    competitive_context_import_pos = text.index("from lpf_competitive_context import")
    assert check_pos < required_pos < stop_pos < pisos_import_pos
    assert check_pos < required_pos < stop_pos < http_import_pos
    assert check_pos < required_pos < stop_pos < schedule_import_pos
    assert check_pos < required_pos < stop_pos < result_updates_import_pos
    assert check_pos < required_pos < stop_pos < qualification_import_pos
    assert check_pos < required_pos < stop_pos < form_import_pos
    assert check_pos < required_pos < stop_pos < simulation_import_pos
    assert check_pos < required_pos < stop_pos < competitive_context_import_pos
    assert "_REQUIRED_RUNTIME_API = 21" in text
    assert 'Motor de cálculo · v{__version__}' in text
