from __future__ import annotations

from football_lab.models import Event


_DEFENSIVE = {"duel", "duelo", "interception", "intercepcion", "recovery", "recuperacion", "tackle", "entrada"}


def defense_features(events: list[Event], team: str) -> dict:
    rows = [e for e in events if e.team == team and e.type.lower() in _DEFENSIVE]
    if not rows:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay eventos defensivos."}
    counts = {}
    for event in rows:
        key = event.type.lower()
        counts[key] = counts.get(key, 0) + 1
    return {
        "available": True,
        "actions_total": len(rows),
        "by_type": counts,
        "interpretation": "Describe intensidad/comportamiento; mas acciones no implica automaticamente mejor defensa.",
    }
