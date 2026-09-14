from __future__ import annotations

from football_lab.models import Event


_SET = {"corner", "free kick", "tiro libre", "penalty", "penal", "set piece", "pelota parada"}


def set_piece_features(events: list[Event], team: str) -> dict:
    own = [e for e in events if e.team == team and str(e.play_pattern or "").lower() in _SET and e.type.lower() in {"shot", "remate"}]
    against = [e for e in events if e.team != team and str(e.play_pattern or "").lower() in _SET and e.type.lower() in {"shot", "remate"}]
    if not own and not against:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay detalle de pelota parada."}
    own_xg = sum(float(e.xg or 0.0) for e in own)
    ag_xg = sum(float(e.xg or 0.0) for e in against)
    goals = sum(str(e.outcome or "").lower() in {"goal", "gol"} for e in own)
    against_goals = sum(str(e.outcome or "").lower() in {"goal", "gol"} for e in against)
    return {
        "available": True,
        "set_piece_xg": own_xg,
        "set_piece_goals": goals,
        "set_piece_shots": len(own),
        "set_piece_conversion": goals / len(own) if own else None,
        "set_piece_xg_against": ag_xg,
        "set_piece_goals_against": against_goals,
    }
