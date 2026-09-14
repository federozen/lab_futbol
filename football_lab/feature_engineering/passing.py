from __future__ import annotations

from football_lab.models import Event


def passing_features(events: list[Event], team: str, *, progressive_threshold: float = 10.0) -> dict:
    passes = [e for e in events if e.team == team and e.type.lower() in {"pass", "pase"}]
    if not passes:
        return {"available": False, "reason": "No disponible con la fuente actual: no hay eventos de pases."}
    completed = [e for e in passes if str(e.outcome or "").lower() in {"complete", "completed", "exitoso", "success"}]
    advances = []
    progressive = 0
    for event in passes:
        if event.location and event.end_location:
            advance = event.end_location[0] - event.location[0]
            advances.append(advance)
            progressive += advance >= progressive_threshold
    return {
        "available": True,
        "passes": len(passes),
        "pass_accuracy": len(completed) / len(passes),
        "avg_forward_advance": (sum(advances) / len(advances)) if advances else None,
        "progressive_passes": progressive if advances else None,
        "definition_note": f"Pase progresivo: avance horizontal >= {progressive_threshold:g} unidades tras normalizar direccion.",
    }
