from __future__ import annotations

from football_lab.config import LabConfig
from football_lab.models import Match
from football_lab.rankings.colley import colley_ratings
from football_lab.rankings.elo import EloEngine
from football_lab.rankings.pagerank import pagerank_ratings


def _rank(values: dict[str, float]) -> dict[str, int]:
    return {team: idx for idx, (team, _) in enumerate(sorted(values.items(), key=lambda kv: kv[1], reverse=True), 1)}


def all_rankings(matches: list[Match], teams: list[str], config: LabConfig) -> dict[str, dict]:
    elo_snapshot = EloEngine(
        initial_rating=config.elo_initial_rating,
        k=config.elo_k,
        home_advantage=config.elo_home_advantage,
    ).calculate(matches, teams=teams)
    colley = colley_ratings(matches, teams=teams)
    pagerank = pagerank_ratings(
        matches,
        teams=teams,
        goal_diff_weight=config.pagerank_goal_diff_weight,
        draw_weight=config.pagerank_draw_weight,
    )
    return {
        "elo": elo_snapshot.ratings,
        "colley": colley,
        "pagerank": pagerank,
        "elo_rank": _rank(elo_snapshot.ratings),
        "colley_rank": _rank(colley),
        "pagerank_rank": _rank(pagerank),
        "elo_history": elo_snapshot.history,
    }
