from __future__ import annotations

from statistics import mean

from football_lab.models import TeamMatch


def _stats(rows: list[TeamMatch]) -> dict:
    if not rows:
        return {"matches": 0, "goals_for_avg": None, "goals_against_avg": None, "points_per_match": None}
    return {
        "matches": len(rows),
        "goals_for_avg": float(mean(m.goals_for for m in rows)),
        "goals_against_avg": float(mean(m.goals_against for m in rows)),
        "points_per_match": float(mean(m.points for m in rows)),
    }


def venue_features(history: list[TeamMatch]) -> dict:
    home = _stats([m for m in history if m.venue == "local"])
    away = _stats([m for m in history if m.venue == "visitante"])
    home_advantage = None
    home_defensive_advantage = None
    if home["goals_for_avg"] is not None and away["goals_for_avg"] is not None:
        home_advantage = home["goals_for_avg"] - away["goals_for_avg"]
    if home["goals_against_avg"] is not None and away["goals_against_avg"] is not None:
        home_defensive_advantage = away["goals_against_avg"] - home["goals_against_avg"]
    return {
        "home": home,
        "away": away,
        "home_advantage": home_advantage,
        "home_defensive_advantage": home_defensive_advantage,
    }
