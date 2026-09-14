from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def comparison_bars(team_a: str, team_b: str, a: dict, b: dict):
    rows = []
    specs = [
        ("Pts ult. 5", a["form"].get("points_last_5"), b["form"].get("points_last_5")),
        ("GF prom. ult. 5", a["form"].get("goals_for_avg_5"), b["form"].get("goals_for_avg_5")),
        ("Elo / 100", (a["strength"].get("elo") or 0) / 100, (b["strength"].get("elo") or 0) / 100),
    ]
    for metric, va, vb in specs:
        if va is not None and vb is not None:
            rows += [{"Metrica": metric, "Equipo": team_a, "Valor": va}, {"Metrica": metric, "Equipo": team_b, "Valor": vb}]
    if not rows:
        return go.Figure()
    return px.bar(pd.DataFrame(rows), x="Valor", y="Metrica", color="Equipo", barmode="group", orientation="h")


def radar_chart(team_a: str, team_b: str, a: dict, b: dict):
    raw = [
        ("Forma", a["form"].get("points_per_match_5"), b["form"].get("points_per_match_5")),
        ("Ataque", a["form"].get("goals_for_avg_5"), b["form"].get("goals_for_avg_5")),
        ("Defensa", a["form"].get("goals_against_avg_5"), b["form"].get("goals_against_avg_5")),
        ("Elo", a["strength"].get("elo"), b["strength"].get("elo")),
    ]
    labels, av, bv = [], [], []
    for label, x, y in raw:
        if x is None or y is None:
            continue
        labels.append(label)
        if label == "Defensa":
            high = max(float(x), float(y), 0.01)
            av.append(1.0 - float(x) / (high + 0.01))
            bv.append(1.0 - float(y) / (high + 0.01))
        else:
            high = max(float(x), float(y), 0.01)
            av.append(float(x) / high)
            bv.append(float(y) / high)
    fig = go.Figure()
    if labels:
        fig.add_trace(go.Scatterpolar(r=av + [av[0]], theta=labels + [labels[0]], fill="toself", name=team_a))
        fig.add_trace(go.Scatterpolar(r=bv + [bv[0]], theta=labels + [labels[0]], fill="toself", name=team_b))
        fig.update_layout(polar=dict(radialaxis=dict(visible=False, range=[0, 1.05])), showlegend=True)
    return fig


def elo_history_chart(history: list[dict], selected_teams: list[str] | None = None):
    rows = []
    selected = set(selected_teams or [])
    for item in history:
        if not selected or item["home_team"] in selected:
            rows.append({"Eje": item.get("match_date") or f"F{item.get('round')}", "Equipo": item["home_team"], "Elo": item["home_after"]})
        if not selected or item["away_team"] in selected:
            rows.append({"Eje": item.get("match_date") or f"F{item.get('round')}", "Equipo": item["away_team"], "Elo": item["away_after"]})
    if not rows:
        return go.Figure()
    df = pd.DataFrame(rows)
    return px.line(df, x="Eje", y="Elo", color="Equipo", markers=True)


def form_trend_chart(history_rows: list[dict], team: str):
    if not history_rows:
        return go.Figure()
    rows = []
    points = []
    goals = []
    for idx, item in enumerate(history_rows, 1):
        points.append(item["points"])
        goals.append(item["goals_for"])
        sample_p = points[-5:]
        sample_g = goals[-5:]
        rows.append({
            "Partido": item.get("round") or idx,
            "Pts prom. 5": sum(sample_p) / len(sample_p),
            "Goles prom. 5": sum(sample_g) / len(sample_g),
        })
    df = pd.DataFrame(rows)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Partido"], y=df["Pts prom. 5"], mode="lines+markers", name="Pts prom. 5"))
    fig.add_trace(go.Scatter(x=df["Partido"], y=df["Goles prom. 5"], mode="lines+markers", name="Goles prom. 5"))
    fig.update_layout(title=f"Evolucion reciente de {team}", xaxis_title="Fecha/jornada")
    return fig
