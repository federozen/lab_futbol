from __future__ import annotations

import pandas as pd
import streamlit as st

from football_lab.config import LabConfig
from football_lab.ui.charts import comparison_bars, elo_history_chart, form_trend_chart, radar_chart


def _fmt(value, decimals=2):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _unavailable(title: str, block: dict):
    if not block.get("available", False):
        st.info(f"{title}: {block.get('reason') or 'No disponible con la fuente actual.'}")


def _explainers():
    with st.expander("¿Qué significan Elo, Colley, PageRank y PPDA?"):
        st.markdown(
            "**Elo** reacciona en el tiempo a resultados y sorpresas.  "
            "**Colley** evalúa el historial global y a quién enfrentó cada equipo.  "
            "**PageRank** mira la red de quién le ganó a quién.  "
            "**PPDA** estima cuántos pases permite un equipo antes de una acción defensiva; menos PPDA suele asociarse con presión más agresiva."
        )


def home_page(service):
    quality = service.data_quality()
    st.title("Laboratorio de análisis del fútbol argentino")
    st.caption("V1 descriptiva y explicable. Funciona sin Opta y no inventa métricas que la fuente no entrega.")
    if quality.get("updated_at"):
        mode = "scraping web" if quality.get("live_results_ok") else ("snapshot" if quality.get("snapshot_used") else "respaldo local")
        stamp = pd.to_datetime(quality["updated_at"], errors="coerce", utc=True)
        when = stamp.tz_convert("America/Argentina/Buenos_Aires").strftime("%d/%m/%Y %H:%M ARG") if not pd.isna(stamp) else quality["updated_at"]
        st.caption(f"Último intento de actualización: {when} · modo efectivo: {mode}.")

    current_round = quality.get("current_round")
    expected_played = quality.get("expected_played_matches")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Fecha actual", current_round if current_round else "—")
    c2.metric("Terminados", quality["finished_matches"])
    c3.metric("Control esperado", expected_played if expected_played is not None else "—")
    c4.metric("Resultados fechados", quality.get("dated_finished_matches", 0))
    c5.metric("Equipos", quality["teams"])

    if quality["status"] == "blocked":
        if expected_played is not None and quality["finished_matches"] < expected_played:
            st.error(
                f"La actualización está incompleta: hay {quality['finished_matches']} resultados cargados y el control público "
                f"indica {expected_played}. Hasta completar los faltantes, no conviene usar forma ni rankings como foto de hoy."
            )
        else:
            st.error("La foto actual tiene un bloqueo de calidad. Abrí Calidad de datos para ver exactamente qué control no cierra.")
    elif quality["status"] == "warning":
        st.warning("La base es utilizable, pero tiene limitaciones de cobertura. Revisá Calidad de datos antes de interpretar variables dependientes de fechas/eventos.")
    else:
        st.success("La foto de resultados pasa los controles disponibles. Podés usar forma, rankings y comparación como estado actual.")

    with st.expander("Cómo usar el laboratorio", expanded=quality["status"] == "blocked"):
        st.markdown(
            "**1. Primero mirá este estado.** Para trabajo editorial, conviene que la cobertura de resultados no esté bloqueada.  \n"
            "**2. Partido:** elegí un próximo cruce para ver cómo llega cada equipo usando sólo información previa.  \n"
            "**3. Equipos:** perfil de un club, forma reciente, local/visitante y ratings.  \n"
            "**4. Comparador:** enfrentá dos equipos aunque no jueguen entre sí en la próxima fecha.  \n"
            "**5. Rankings:** Elo, Colley y PageRank.  \n"
            "**6. Calidad de datos:** muestra qué fuente respondió, cuántos partidos aportó y qué falta."
        )

    st.subheader("Próximos partidos")
    nxt = service.next_matches(8)
    if nxt:
        rows = []
        for m in nxt:
            stamp = pd.to_datetime(m.get("match_date"), errors="coerce")
            when = stamp.strftime("%d/%m %H:%M") if not pd.isna(stamp) else f"Fecha {m['round']}"
            rows.append({"Cuándo": when, "Fecha": m["round"], "Local": m["home_team"], "Visitante": m["away_team"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No hay próximos partidos identificados con la fuente actual.")

    rankings = service.get_rankings()["rankings"]
    top = sorted(rankings["elo"].items(), key=lambda kv: kv[1], reverse=True)[:5]
    st.subheader("Elo destacado")
    st.dataframe(pd.DataFrame([{"Equipo": t, "Elo": round(v, 1)} for t, v in top]), use_container_width=True, hide_index=True)


def team_page(service):
    st.title("Equipos")
    team = st.selectbox("Equipo", service.teams)
    payload = service.get_team_profile(team)
    p = payload["profile"]
    reality, form, strength = p["reality"], p["form"], p["strength"]
    st.subheader("Realidad actual")
    cols = st.columns(6)
    for col, (label, val) in zip(cols, [("Pos.", reality.get("position")), ("PTS", reality.get("points")), ("PJ", reality.get("played")), ("GF", reality.get("goals_for")), ("GC", reality.get("goals_against")), ("DG", reality.get("goal_difference"))]):
        col.metric(label, _fmt(val, 0))
    st.subheader("Forma")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Últimos 5", form.get("last_results", "—"))
    c2.metric("Pts últimos 5", _fmt(form.get("points_last_5"), 0))
    c3.metric("GF prom. 5", _fmt(form.get("goals_for_avg_5")))
    c4.metric("GC prom. 5", _fmt(form.get("goals_against_avg_5")))
    st.subheader("Fuerza")
    c1, c2, c3 = st.columns(3)
    c1.metric("Elo", _fmt(strength.get("elo"), 1))
    c2.metric("Colley", _fmt(strength.get("colley"), 3))
    c3.metric("PageRank", _fmt(strength.get("pagerank"), 4))
    st.subheader("Local / visitante")
    venue = p["venue"]
    st.dataframe(pd.DataFrame([
        {"Condición": "Local", **venue["home"]},
        {"Condición": "Visitante", **venue["away"]},
    ]), use_container_width=True, hide_index=True)
    if p.get("narrative"):
        st.success(p["narrative"])
    _unavailable("xG y calidad de remates", p["attack_quality"])
    _unavailable("Presión (PPDA)", p["pressing"])
    _unavailable("Pases y progresividad", p["passing"])
    _explainers()


def comparison_page(service):
    st.title("Comparador")
    c1, c2 = st.columns(2)
    team_a = c1.selectbox("Equipo A", service.teams, index=0)
    options_b = [t for t in service.teams if t != team_a]
    team_b = c2.selectbox("Equipo B", options_b, index=min(1, len(options_b)-1))
    data = service.compare_teams(team_a, team_b)["comparison"]
    a, b = data["team_a"], data["team_b"]
    rows = [
        ("Pts últimos 5", a["form"].get("points_last_5"), b["form"].get("points_last_5")),
        ("GF prom. 5", a["form"].get("goals_for_avg_5"), b["form"].get("goals_for_avg_5")),
        ("GC prom. 5", a["form"].get("goals_against_avg_5"), b["form"].get("goals_against_avg_5")),
        ("Elo", a["strength"].get("elo"), b["strength"].get("elo")),
        ("Colley", a["strength"].get("colley"), b["strength"].get("colley")),
        ("PageRank", a["strength"].get("pagerank"), b["strength"].get("pagerank")),
    ]
    st.dataframe(pd.DataFrame([{"Métrica": m, team_a: _fmt(x), team_b: _fmt(y)} for m, x, y in rows]), use_container_width=True, hide_index=True)
    st.plotly_chart(comparison_bars(team_a, team_b, a, b), use_container_width=True)
    with st.expander("Radar normalizado"):
        st.plotly_chart(radar_chart(team_a, team_b, a, b), use_container_width=True)
    st.success(data["narrative"])


def match_page(service):
    st.title("Partido")
    matches = service.next_matches(40)
    if not matches:
        st.info("No hay partidos pendientes en la fuente cargada.")
        return
    labels = {f"F{m['round']} · {m['home_team']} vs. {m['away_team']}": m["match_id"] for m in matches}
    label = st.selectbox("Partido próximo", list(labels))
    payload = service.get_match_features(labels[label])["features"]
    match = payload["metadata"]["match"]
    st.header(f"{match['home_team']} vs. {match['away_team']}")
    st.caption(f"Sólo se usan datos previos. Partidos históricos usados: {payload['metadata']['history_matches_used']} · corte: {payload['metadata']['chronology_basis']}.")
    h, a = payload["home"], payload["away"]
    st.subheader("Forma y fuerza")
    table = pd.DataFrame([
        {"Indicador": "Pts últimos 5", match["home_team"]: h["form"].get("points_last_5"), match["away_team"]: a["form"].get("points_last_5")},
        {"Indicador": "GF prom. 5", match["home_team"]: h["form"].get("goals_for_avg_5"), match["away_team"]: a["form"].get("goals_for_avg_5")},
        {"Indicador": "GC prom. 5", match["home_team"]: h["form"].get("goals_against_avg_5"), match["away_team"]: a["form"].get("goals_against_avg_5")},
        {"Indicador": "Elo", match["home_team"]: h["strength"].get("elo"), match["away_team"]: a["strength"].get("elo")},
        {"Indicador": "Colley", match["home_team"]: h["strength"].get("colley"), match["away_team"]: a["strength"].get("colley")},
        {"Indicador": "PageRank", match["home_team"]: h["strength"].get("pagerank"), match["away_team"]: a["strength"].get("pagerank")},
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.subheader("Ventajas relativas")
    narr = payload["narrative"]
    c1, c2 = st.columns(2)
    c1.write(f"**{match['home_team']}**: " + (", ".join(narr["home_advantages"]) or "sin ventaja clara en los indicadores disponibles"))
    c2.write(f"**{match['away_team']}**: " + (", ".join(narr["away_advantages"]) or "sin ventaja clara en los indicadores disponibles"))
    st.success(narr["conclusion"])
    _unavailable("Descanso y congestión del local", h["context"])
    _unavailable("Descanso y congestión del visitante", a["context"])
    _unavailable("xG", h["attack_quality"])


def form_page(service):
    st.title("Forma")
    team = st.selectbox("Equipo", service.teams, key="form_team")
    rows = [m.to_dict() for m in service.repository.team_history(team)]
    st.plotly_chart(form_trend_chart(rows, team), use_container_width=True)
    st.dataframe(pd.DataFrame(rows[-10:]), use_container_width=True, hide_index=True)


def rankings_page(service):
    st.title("Rankings")
    data = service.get_rankings()["rankings"]
    teams = service.teams
    df = pd.DataFrame([{ "Equipo": team, "Elo": data["elo"].get(team), "Pos. Elo": data["elo_rank"].get(team), "Colley": data["colley"].get(team), "Pos. Colley": data["colley_rank"].get(team), "PageRank": data["pagerank"].get(team), "Pos. PageRank": data["pagerank_rank"].get(team)} for team in teams]).sort_values("Pos. Elo")
    st.dataframe(df, use_container_width=True, hide_index=True)
    selected = st.multiselect("Evolución Elo", teams, default=teams[:2], max_selections=5)
    st.plotly_chart(elo_history_chart(data["elo_history"], selected), use_container_width=True)
    _explainers()


def style_page(service):
    st.title("Estilo de juego")
    st.write("Esta sección separa lo que la fuente realmente entrega de lo que requeriría eventos avanzados.")
    team = st.selectbox("Equipo", service.teams, key="style_team")
    p = service.get_team_profile(team)["profile"]
    for title, key in [("xG y remates", "attack_quality"), ("Pases y progresividad", "passing"), ("Defensa por eventos", "defense"), ("Presión (PPDA)", "pressing"), ("Pelota parada", "set_pieces"), ("Jugadores", "players")]:
        block = p[key]
        if block.get("available"):
            st.subheader(title); st.json(block)
        else:
            st.info(f"{title}: {block.get('reason')}")
    st.caption("No se usan goles, posesión u otras variables básicas como sustitutos falsos de xG, PPDA o datos de eventos.")


def laboratory_page(service):
    st.title("Laboratorio")
    st.caption("Los cambios son temporales y no modifican la configuración de producción.")
    k = st.slider("K de Elo", 8, 60, int(service.config.elo_k))
    home = st.slider("Ventaja de local Elo", 0, 120, int(service.config.elo_home_advantage))
    window = st.selectbox("Ventana principal de forma", [3, 5, 10], index=1)
    config = service.config.with_overrides(elo_k=float(k), elo_home_advantage=float(home), form_windows=tuple(sorted({3, 5, 10, int(window)})))
    temp = service.with_config(config)
    team = st.selectbox("Equipo para probar", temp.teams, key="lab_team")
    p = temp.get_team_profile(team)["profile"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Elo experimental", _fmt(p["strength"].get("elo"), 1))
    c2.metric(f"Pts últimos {window}", _fmt(p["form"].get(f"points_last_{window}"), 0))
    c3.metric("Posición Elo", _fmt(p["strength"].get("elo_rank"), 0))


def quality_page(service):
    st.title("Calidad de datos")
    q = service.data_quality()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Fecha actual", q.get("current_round") or "—")
    c2.metric("Fixture", q["expected_matches"])
    c3.metric("Resultados", q["finished_matches"])
    c4.metric("Pendientes", q["pending_matches"])
    c5.metric("Con fecha", q["dated_matches"])
    st.write("**Fuentes:** " + (" · ".join(q["sources"]) or "—"))
    st.write(f"**Base cronológica:** {q['chronology_basis']}")
    if q.get("updated_at"):
        stamp = pd.to_datetime(q["updated_at"], errors="coerce", utc=True)
        when = stamp.tz_convert("America/Argentina/Buenos_Aires").strftime("%d/%m/%Y %H:%M ARG") if not pd.isna(stamp) else q["updated_at"]
        st.write(f"**Último intento de actualización:** {when}")
    if q.get("expected_played_matches") is not None:
        st.write(f"**Partidos jugados según tabla de contraste:** {q['expected_played_matches']}")

    source_health = q.get("source_health") or {}
    if source_health:
        st.subheader("Qué aportó cada fuente en esta actualización")
        source_rows = []
        for source, values in source_health.items():
            source_rows.append({
                "Fuente": source,
                "Registros reconocidos": values.get("records", 0),
                "Resultados finales": values.get("finished", 0),
                "Partidos con fecha": values.get("dated", 0),
            })
        st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)

    for issue in q["issues"]:
        if issue["level"] == "blocked": st.error(issue["message"])
        elif issue["level"] == "warning": st.warning(issue["message"])
        else: st.info(issue["message"])
    st.subheader("Disponibilidad")
    st.dataframe(pd.DataFrame([{"Variable": k, "Disponible": "Sí" if v else "No"} for k, v in q["availability"].items()]), use_container_width=True, hide_index=True)
    st.code("La app nunca convierte una ausencia de eventos/xG/fechas en un cero. La marca como no disponible.", language=None)


PAGES = {
    "Inicio": home_page,
    "Equipos": team_page,
    "Comparador": comparison_page,
    "Partido": match_page,
    "Forma": form_page,
    "Rankings": rankings_page,
    "Estilo de juego": style_page,
    "Laboratorio": laboratory_page,
    "Calidad de datos": quality_page,
}


def render_page(name: str, service):
    PAGES[name](service)
