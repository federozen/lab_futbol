"""Pruebas de adaptadores de proveedor sin red ni Streamlit."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lpf_provider_adapters import (  # noqa: E402
    parse_espn_lpf_zones_payload,
    parse_espn_scoreboard_payloads,
    parse_espn_table_payload,
    parse_futbolargentino_annual_html,
    parse_futbolargentino_zones_html,
)

FIXTURES = Path(__file__).with_name("fixtures")


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_futbolargentino_html_se_adapta_a_zonas_y_anual():
    html = (FIXTURES / "futbolargentino_standings_sample.html").read_text(encoding="utf-8")
    zones = parse_futbolargentino_zones_html(html)
    annual = parse_futbolargentino_annual_html(html)

    assert set(zones) == {"A", "B"}
    assert len(zones["A"]) == len(zones["B"]) == 15
    assert len(annual) == 30
    # Casos reales donde el HTML del proveedor concatena/abrevia nombres.
    assert "Central Córdoba" in zones["A"]
    assert "Gimnasia de Mendoza" in zones["A"]
    assert "Argentinos Juniors" in zones["B"]
    assert "Estudiantes de Río Cuarto" in zones["B"]


def test_espn_standings_se_adapta_sin_estado_de_ui():
    payload = _json("espn_standings_sample.json")
    zones, error = parse_espn_lpf_zones_payload(payload, "arg.1")
    base, zones_text, table_error = parse_espn_table_payload(payload, "arg.1")

    assert error is None
    assert table_error is None
    assert set(zones) == {"A", "B"}
    assert len(zones["A"]) == len(zones["B"]) == 15
    assert len(base) == 30
    assert zones_text == "2 Playoffs"
    assert zones["A"]["Gimnasia de Mendoza"]["pj"] == 4


def test_espn_scoreboards_preservan_deduplicacion_estados_y_metadatos():
    payloads = _json("espn_scoreboards_sample.json")
    parsed = parse_espn_scoreboard_payloads(
        payloads,
        initial_event_meta={"keep": {"x": 1}},
        initial_schedule={"keep": "old"},
    )

    # El primer event_id gana: el duplicado posterior 9-9 no pisa el 2-1.
    assert parsed["played"] == [
        ("River Plate", "Barracas Central", 2, 1),
        ("Estudiantes de Río Cuarto", "Tigre", 0, 0),
    ]
    assert parsed["pending"] == [("Racing", "Gimnasia La Plata")]
    assert parsed["schedule"]["keep"] == "old"
    assert parsed["event_meta"]["keep"] == {"x": 1}
    assert parsed["event_meta"]["River Plate|||Barracas Central"]["round"] == 1
    assert parsed["day_map"][("River Plate", "Barracas Central")] == "2026-07-12"
    assert parsed["datetime_map"][("River Plate", "Barracas Central")] == "2026-07-12T20:00Z"
    # Postergados y cancelados no se transforman en falsos resultados/pendientes.
    assert ("Belgrano", "Rosario Central") not in parsed["pending"]
    assert ("Sarmiento", "Argentinos Juniors") not in parsed["pending"]


def test_adaptadores_no_dependen_de_streamlit_ni_requests():
    source = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lpf_provider_adapters.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "import requests" not in source
