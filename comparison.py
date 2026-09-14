from __future__ import annotations


def comparison_narrative(team_a: str, team_b: str, comparison: dict) -> str:
    diff = comparison.get("differences", {})
    parts = []
    form = diff.get("points_last_5_diff")
    elo = diff.get("elo_diff")
    if form is not None and abs(form) >= 2:
        leader = team_a if form > 0 else team_b
        parts.append(f"{leader} llega con más puntos en la ventana reciente")
    if elo is not None and abs(elo) >= 20:
        leader = team_a if elo > 0 else team_b
        parts.append(f"{leader} tiene una ventaja de {abs(elo):.0f} puntos Elo")
    if not parts:
        return "Los indicadores disponibles no muestran una diferencia amplia entre ambos. Son señales descriptivas, no una relación causal."
    return ". ".join(parts) + ". Son señales descriptivas: ninguna variable, por sí sola, demuestra causalidad."
