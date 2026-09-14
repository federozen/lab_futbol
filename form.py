from __future__ import annotations

from statistics import mean, pstdev

from football_lab.models import TeamMatch


def _safe_mean(values):
    return float(mean(values)) if values else None


def _safe_std(values):
    return float(pstdev(values)) if len(values) >= 2 else (0.0 if len(values) == 1 else None)


def form_features(history: list[TeamMatch], windows: tuple[int, ...] = (3, 5, 10)) -> dict:
    out: dict[str, object] = {
        "matches_available": len(history),
        "last_results": "".join(m.result for m in history[-5:]) or "—",
    }
    for window in windows:
        sample = history[-window:]
        gf = [m.goals_for for m in sample]
        ga = [m.goals_against for m in sample]
        pts = [m.points for m in sample]
        wins = sum(m.result == "G" for m in sample)
        unbeaten = sum(m.result != "P" for m in sample)
        suffix = str(window)
        out.update({
            f"matches_last_{suffix}": len(sample),
            f"goals_for_avg_{suffix}": _safe_mean(gf),
            f"goals_against_avg_{suffix}": _safe_mean(ga),
            f"goal_difference_avg_{suffix}": _safe_mean([a - b for a, b in zip(gf, ga)]),
            f"points_last_{suffix}": int(sum(pts)),
            f"points_per_match_{suffix}": _safe_mean(pts),
            f"wins_last_{suffix}": int(wins),
            f"win_pct_last_{suffix}": (wins / len(sample)) if sample else None,
            f"unbeaten_pct_last_{suffix}": (unbeaten / len(sample)) if sample else None,
            f"goals_std_{suffix}": _safe_std(gf),
            f"points_std_{suffix}": _safe_std(pts),
            f"consistency_{suffix}": (1.0 / (1.0 + _safe_std(pts))) if sample else None,
        })
    if len(history) >= 1:
        out["goals_for_total"] = sum(m.goals_for for m in history)
        out["goals_against_total"] = sum(m.goals_against for m in history)
        out["points_total"] = sum(m.points for m in history)
        out["played_total"] = len(history)
        out["goal_difference_total"] = out["goals_for_total"] - out["goals_against_total"]
    else:
        out.update({"goals_for_total": 0, "goals_against_total": 0, "points_total": 0, "played_total": 0, "goal_difference_total": 0})
    return out
