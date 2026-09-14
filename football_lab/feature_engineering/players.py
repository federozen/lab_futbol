from __future__ import annotations


def player_features(players, events, team: str) -> dict:
    team_players = [p for p in players if p.team == team]
    if not team_players:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay datos de jugadores/alineaciones."}
    return {
        "available": True,
        "players_loaded": len(team_players),
        "starting_xi_strength": None,
        "note": "La arquitectura esta preparada, pero no se asignan pesos arbitrarios a un once sin una metodologia validada.",
    }
