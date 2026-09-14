from __future__ import annotations


def team_narrative(team: str, profile: dict, *, elo_average: float | None = None) -> str:
    form = profile.get("form", {})
    strength = profile.get("strength", {})
    p5 = form.get("points_last_5")
    m5 = form.get("matches_last_5") or 0
    ppg5 = form.get("points_per_match_5")
    ppg10 = form.get("points_per_match_10")
    pieces = []
    if p5 is not None and m5:
        pieces.append(f"{team} sumó {int(p5)} de {int(m5) * 3} puntos en sus últimos {int(m5)} partidos")
    if ppg5 is not None and ppg10 is not None:
        if ppg5 > ppg10 + 0.2:
            pieces.append("Su forma reciente está por encima de la ventana de diez partidos")
        elif ppg5 < ppg10 - 0.2:
            pieces.append("Su forma reciente está por debajo de la ventana de diez partidos")
    elo = strength.get("elo")
    if elo is not None and elo_average is not None:
        pieces.append("Su Elo está por encima del promedio del torneo" if elo > elo_average else "su Elo está por debajo del promedio del torneo")
    return ". ".join(pieces).strip() + ("." if pieces else "")
