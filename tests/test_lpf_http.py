"""Pruebas del transporte HTTP aislado, siempre con requests simulado."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lpf_http  # noqa: E402


class _Response:
    def __init__(self, *, status=200, url="https://final.test/x", text="x" * 600, payload=None):
        self.status_code = status
        self.url = url
        self.text = text
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload


def test_fetch_html_solo_transporta_y_devuelve_url_final(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(url="https://final.test/tabla")

    monkeypatch.setattr(lpf_http.requests, "get", fake_get)
    text, final_url = lpf_http.fetch_html(
        "https://source.test/tabla", referer="https://source.test/", retries=0
    )
    assert len(text) == 600
    assert final_url == "https://final.test/tabla"
    assert calls[0][1]["headers"]["Referer"] == "https://source.test/"


def test_fetch_espn_json_no_parsea_el_payload(monkeypatch):
    payload = {"events": [{"id": "raw"}]}
    monkeypatch.setattr(
        lpf_http.requests,
        "get",
        lambda *args, **kwargs: _Response(payload=payload),
    )
    assert lpf_http.fetch_espn_json(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/arg.1/scoreboard",
        retries=0,
    ) == payload


def test_lpf_http_no_depende_de_streamlit():
    source = open(lpf_http.__file__, encoding="utf-8").read()
    assert "import streamlit" not in source
