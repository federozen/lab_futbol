from __future__ import annotations


def ranking_features(team: str, rankings: dict[str, dict]) -> dict:
    return {
        "elo": rankings.get("elo", {}).get(team),
        "colley": rankings.get("colley", {}).get(team),
        "pagerank": rankings.get("pagerank", {}).get(team),
        "elo_rank": rankings.get("elo_rank", {}).get(team),
        "colley_rank": rankings.get("colley_rank", {}).get(team),
        "pagerank_rank": rankings.get("pagerank_rank", {}).get(team),
    }
