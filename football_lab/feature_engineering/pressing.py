from __future__ import annotations

from football_lab.models import Event


_DEF = {"tackle", "entrada", "interception", "intercepcion", "challenge", "duel", "duelo"}


def ppda_features(events: list[Event], team: str, *, max_x: float = 60.0) -> dict:
    if not events:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay eventos para PPDA."}
    opp_passes = 0
    defensive_actions = 0
    for event in events:
        x = event.location[0] if event.location else None
        if event.team != team and event.type.lower() in {"pass", "pase"} and (x is None or x <= max_x):
            opp_passes += 1
        if event.team == team and event.type.lower() in _DEF and (x is None or x <= max_x):
            defensive_actions += 1
    if defensive_actions == 0:
        return {"available": False, "reason": "No hay suficientes acciones defensivas en la zona definida para PPDA."}
    return {
        "available": True,
        "ppda": opp_passes / defensive_actions,
        "passes_allowed": opp_passes,
        "defensive_actions": defensive_actions,
        "zone_max_x": max_x,
        "interpretation": "Menor PPDA indica menos pases rivales permitidos antes de una accion defensiva.",
    }
