from datetime import datetime, timezone
from pathlib import Path

from football_lab.data.scraping_provider import (
    PublicScrapingProvider,
    discover_lpf_schedule_links,
    parse_lpf_schedule_article_html,
)


def test_schedule_parser_reads_official_lpf_date_and_time():
    html = """
    <article>
      <h2>Fecha 10</h2>
      <p>Viernes 18 de septiembre</p>
      <p>18.00 Central Córdoba – Defensa y Justicia (Zona A) (ESPN Premium)</p>
      <p>21.15 Racing – Sarmiento (Zona B) (TNT Sports)</p>
      <h2>Últimas noticias</h2>
      <p>18.00 River – Huracán</p>
    </article>
    """
    rows = parse_lpf_schedule_article_html(html)
    assert len(rows) == 2
    assert rows[0]["home"] == "Central Córdoba"
    assert rows[0]["away"] == "Defensa y Justicia"
    assert rows[0]["round"] == 10
    assert rows[0]["scheduled_at"].startswith("2026-09-18T18:00:00")


def test_schedule_link_discovery_accepts_wordpress_query_permalink():
    html = """
    <a href="/?p=86406">Agenda de la 8 a la 11</a>
    <a href="/notas/proyeccion/x/">Agenda: fechas 8 a 11 - Proyección</a>
    <a href="/notas/primera/2026/09/10/se-mueve-la-novena/">Se mueve la novena</a>
    """
    links = discover_lpf_schedule_links(html, base_url="https://www.ligaprofesional.ar/notas/primera/")
    assert links == ["https://www.ligaprofesional.ar/?p=86406"]


def test_public_scraping_provider_merges_live_result_and_official_schedule(tmp_path: Path):
    futbol_html = """
    <html><body>
      <h3>Fecha 1</h3>
      <div>Jueves, 23 Julio 2026</div>
      <div>Belgrano</div><div>7:30 PM</div><div>2 - 1</div><div>Rosario</div><div>Jugado</div>
    </body></html>
    """
    listing_html = '<a href="/?p=86406">Agenda de la 8 a la 11</a>'
    schedule_html = """
    <article>
      <h2>Fecha 10</h2>
      <p>Domingo 20 de septiembre</p>
      <p>19.00 River – Huracán (Zona B) (ESPN Premium)</p>
    </article>
    """

    def fake_get(url, *, referer="", timeout=8):
        if "futbolargentino.com/primera-division/clausura/tabla" in url:
            raise RuntimeError("tabla fuera de prueba")
        if "futbolargentino.com" in url:
            return futbol_html, url
        if url == "https://www.ligaprofesional.ar/?p=86406":
            return schedule_html, url
        if "ligaprofesional.ar/notas/primera" in url:
            return listing_html, url
        raise RuntimeError(url)

    # El provider espera la base incluida debajo del root. Copiamos sólo el CSV que usa.
    (tmp_path / "data" / "sample").mkdir(parents=True)
    source_csv = Path(__file__).resolve().parents[1] / "data" / "sample" / "calculadora_results_2026.csv"
    (tmp_path / "data" / "sample" / "calculadora_results_2026.csv").write_text(
        source_csv.read_text(encoding="utf-8"), encoding="utf-8"
    )

    provider = PublicScrapingProvider(
        tmp_path,
        html_getter=fake_get,
        now=lambda: datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
    )
    dataset = provider.load()
    belgrano = next(m for m in dataset.matches if m.home_team == "Belgrano" and m.away_team == "Rosario Central" and m.round == 1)
    assert belgrano.finished
    assert (belgrano.home_score, belgrano.away_score) == (2, 1)
    assert belgrano.match_date is not None

    river = next(m for m in dataset.matches if m.home_team == "River Plate" and m.away_team == "Huracán" and m.round == 10)
    assert river.match_date is not None
    assert river.match_date.isoformat().startswith("2026-09-20T19:00:00")
    assert dataset.metadata["live_fetch_ok"] is True
    assert (tmp_path / "data" / "live" / "lpf_web_snapshot.json").exists()


def test_schedule_parser_preserves_lines_separated_by_br():
    html = """
    <article>
      <p>
        Agenda de la 8 a la 11<br/>
        Fecha 9<br/>
        Viernes 11 de septiembre<br/>
        17.00 Newell’s – Vélez (Zona A) (ESPN Premium)<br/>
        19.15 Defensa y Justicia – Gimnasia (Mza.) (Zona A) (TNT Sports)<br/>
        21.30 Boca – Central Córdoba (Zona A) (ESPN Premium)<br/>
        Fecha 10<br/>
        Viernes 18 de septiembre<br/>
        18.00 Central Córdoba – Defensa y Justicia (Zona A) (TNT Sports)
      </p>
    </article>
    """
    rows = parse_lpf_schedule_article_html(html)
    pairs = {(row["round"], row["home"], row["away"]): row for row in rows}
    assert (9, "Newell's Old Boys", "Vélez Sarsfield") in pairs
    assert (9, "Boca Juniors", "Central Córdoba") in pairs
    assert pairs[(9, "Boca Juniors", "Central Córdoba")]["scheduled_at"].startswith(
        "2026-09-11T21:30:00"
    )
    assert (10, "Central Córdoba", "Defensa y Justicia") in pairs


def test_tyc_parser_reads_historical_results_and_current_fixture():
    from football_lab.data.scraping_provider import parse_tyc_fixture_results_html

    html = """
    <article>
      <h2>El fixture del Torneo Clausura 2026: cruces y fechas</h2>
      <h4>Fecha 9</h4>
      <h4>Viernes 11 de septiembre</h4>
      <ul>
        <li>Newell’s 1-1 Vélez</li>
        <li>Defensa y Justicia 2-0 Gimnasia (Mza.)</li>
        <li>Boca 3-1 Central Córdoba</li>
      </ul>
      <p>Lunes 14 de septiembre</p>
      <ul>
        <li>19.00 Deportivo Riestra – Lanús (Zona A)</li>
        <li>19.00 Banfield – Barracas Central (Zona B)</li>
        <li>21.15 Instituto – Estudiantes (Río Cuarto) (Interzonal)</li>
      </ul>
      <h2>Resultados del Torneo Clausura 2026</h2>
      <h4>Fecha 1</h4>
      <p>Jueves 23 de julio</p>
      <ul>
        <li>Belgrano 2-1 Rosario Central</li>
        <li>Sarmiento 2-3 Argentinos</li>
        <li>Defensa y Justicia 1-1 Aldosivi</li>
      </ul>
      <p>Domingo 26 de julio</p>
      <ul><li>Deportivo Riestra 3-0 Boca</li></ul>
    </article>
    """
    rows = parse_tyc_fixture_results_html(html)
    keyed = {(r["round"], r["home"], r["away"]): r for r in rows}

    belgrano = keyed[(1, "Belgrano", "Rosario Central")]
    assert belgrano["status"] == "played"
    assert (belgrano["home_score"], belgrano["away_score"]) == (2, 1)
    # Resultado sin hora exacta: fin de día para no filtrar información a otro
    # partido de esa misma jornada/día.
    assert belgrano["scheduled_at"].startswith("2026-07-23T23:59:00")

    boca = keyed[(9, "Boca Juniors", "Central Córdoba")]
    assert boca["status"] == "played"
    assert (boca["home_score"], boca["away_score"]) == (3, 1)
    assert boca["scheduled_at"].startswith("2026-09-11T23:59:00")

    instituto = keyed[(9, "Instituto", "Estudiantes de Río Cuarto")]
    assert instituto["status"] == "scheduled"
    assert instituto["scheduled_at"].startswith("2026-09-14T21:15:00")


def test_bootstrap_keeps_fecha_9_usable_when_all_web_sources_fail():
    root = Path(__file__).resolve().parents[1]

    def fail_get(url, *, referer="", timeout=8):
        raise RuntimeError("sin red")

    provider = PublicScrapingProvider(
        root,
        html_getter=fail_get,
        now=lambda: datetime(2026, 9, 14, 19, 0, tzinfo=timezone.utc),
    )
    dataset = provider.load()
    finished = [m for m in dataset.matches if m.finished]
    dated_finished = [m for m in finished if m.match_date is not None]
    assert len(finished) == 132
    assert len(dated_finished) == 132
    assert dataset.metadata["current_round"] == 9
    assert dataset.metadata["bootstrap_finished_matches"] == 132

    riestra_lanus = next(
        m for m in dataset.matches
        if m.round == 9 and m.home_team == "Deportivo Riestra" and m.away_team == "Lanús"
    )
    assert not riestra_lanus.finished
    assert riestra_lanus.match_date is not None
    assert riestra_lanus.match_date.isoformat().startswith("2026-09-14T19:00:00")


def test_recent_bootstrap_is_warning_not_block_when_network_is_down():
    from football_lab.services.data_quality_service import data_quality_report

    root = Path(__file__).resolve().parents[1]

    def fail_get(url, *, referer="", timeout=8):
        raise RuntimeError("sin red")

    dataset = PublicScrapingProvider(
        root,
        html_getter=fail_get,
        now=lambda: datetime(2026, 9, 14, 19, 0, tzinfo=timezone.utc),
    ).load()
    quality = data_quality_report(dataset)
    assert quality["finished_matches"] == 132
    assert quality["dated_finished_matches"] == 132
    assert quality["status"] == "warning"
    assert not any(issue["level"] == "blocked" for issue in quality["issues"])
