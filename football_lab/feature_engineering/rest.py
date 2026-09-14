from __future__ import annotations

from datetime import timedelta

from football_lab.models import Match, TeamMatch


def rest_features(history: list[TeamMatch], target: Match, windows: tuple[int, ...] = (7, 14, 21)) -> dict:
    if target.match_date is None:
        return {
            "available": False,
            "reason": "No disponible con la fuente actual: falta la fecha exacta del partido.",
            "days_rest": None,
            **{f"matches_in_last_{d}_days": None for d in windows},
        }
    dated = [m for m in history if m.match_date is not None and m.match_date < target.match_date]
    if not dated:
        return {
            "available": False,
            "reason": "No hay un partido previo fechado para calcular descanso.",
            "days_rest": None,
            **{f"matches_in_last_{d}_days": 0 for d in windows},
        }
    previous = max(dated, key=lambda m: m.match_date)
    days_rest = (target.match_date - previous.match_date).total_seconds() / 86400.0
    out = {"available": True, "reason": "", "days_rest": float(days_rest)}
    for d in windows:
        threshold = target.match_date - timedelta(days=d)
        out[f"matches_in_last_{d}_days"] = sum(1 for m in dated if m.match_date >= threshold)
    return out
