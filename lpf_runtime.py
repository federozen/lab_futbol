"""Chequeo liviano de compatibilidad entre módulos desplegados.

No importa los módulos que verifica: lee sus marcadores desde disco. Así puede
avisar que un deploy quedó con archivos mezclados antes de que un ``from ... import``
termine en un NameError/AttributeError difícil de diagnosticar.
"""
from __future__ import annotations

import ast
from pathlib import Path

LPF_RUNTIME_API = 21

# Sólo módulos cuyo contrato cruza capas y cuya mezcla de versiones puede romper
# el arranque o la UI. El nivel se incrementa únicamente cuando cambia ese contrato.
CRITICAL_COMPONENTS = (
    'lpf_http.py',
    'competition_html_adapters.py',
    'lpf_models.py',
    'lpf_standings.py',
    'lpf_result_updates.py',
    'lpf_averages.py',
    'lpf_form.py',
    'lpf_simulation.py',
    'lpf_competitive_context.py',
    'lpf_conditionals.py',
    'lpf_editorial_definition.py',
    'lpf_relegation.py',
    'lpf_scenarios.py',
    'lpf_exact.py',
    'lpf_pisos.py',
    'lpf_state.py',
    'lpf_loading.py',
    'lpf_data_provider.py',
    'lpf_provider_adapters.py',
    'lpf_table_selection.py',
    'lpf_table_backup.py',
    'lpf_snapshot.py',
    'lpf_services.py',
    'lpf_schedule.py',
    'lpf_preview.py',
    'lpf_qualification.py',
)


def _read_runtime_api(path: Path) -> int | None:
    """Lee ``LPF_RUNTIME_API`` sin importar ni ejecutar el módulo."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        else:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "LPF_RUNTIME_API":
                try:
                    return int(ast.literal_eval(value))
                except (TypeError, ValueError, SyntaxError):
                    return None
    return None


def runtime_compatibility(base_dir: str | Path | None = None) -> dict[str, object]:
    """Devuelve un diagnóstico JSON-safe del conjunto de módulos desplegado."""
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
    mismatches: list[dict[str, object]] = []
    checked: list[dict[str, object]] = []
    for filename in CRITICAL_COMPONENTS:
        path = root / filename
        found = _read_runtime_api(path) if path.exists() else None
        row = {"file": filename, "expected": LPF_RUNTIME_API, "found": found}
        checked.append(row)
        if found != LPF_RUNTIME_API:
            mismatches.append(row)
    return {
        "ok": not mismatches,
        "runtime_api": LPF_RUNTIME_API,
        "checked": checked,
        "mismatches": mismatches,
    }


def runtime_error_message(report: dict[str, object]) -> str:
    """Texto breve para Streamlit cuando hay archivos desincronizados."""
    mismatches = report.get("mismatches") or []
    names = [str(row.get("file")) for row in mismatches if isinstance(row, dict)]
    if not names:
        return "Los módulos del motor no son compatibles entre sí."
    return (
        "El despliegue tiene archivos de versiones mezcladas. Actualizá juntos: "
        + ", ".join(names)
        + "."
    )
