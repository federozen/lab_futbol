from __future__ import annotations

from football_lab.models import Event


def xg_features(events: list[Event], team: str) -> dict:
    shots = [e for e in events if e.team == team and e.type.lower() in {"shot", "remate"}]
    opp_shots = [e for e in events if e.team != team and e.type.lower() in {"shot", "remate"}]
    if not shots and not opp_shots:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay eventos/xG."}
    shot_xg = [float(e.xg) for e in shots if e.xg is not None]
    opp_xg = [float(e.xg) for e in opp_shots if e.xg is not None]
    if not shot_xg and not opp_xg:
        return {"available": False, "reason": "Hay eventos, pero la fuente no entrega xG."}
    total_xg = sum(shot_xg)
    xga = sum(opp_xg)
    goals = sum(1 for e in shots if str(e.outcome or "").lower() in {"goal", "gol"})
    on_target = sum(1 for e in shots if str(e.outcome or "").lower() in {"goal", "gol", "saved", "atajadio", "atajados", "on target"})
    return {
        "available": True,
        "shots": len(shots),
        "shots_on_target": on_target,
        "total_xg": total_xg,
        "avg_xg_per_shot": (total_xg / len(shots)) if shots else None,
        "goals": goals,
        "xg_overperformance": goals - total_xg,
        "shot_conversion_rate": (goals / len(shots)) if shots else None,
        "xg_against": xga,
        "xg_difference": total_xg - xga,
    }
