from __future__ import annotations

import networkx as nx

from football_lab.models import Match


def pagerank_ratings(
    matches: list[Match],
    *,
    teams: list[str] | None = None,
    goal_diff_weight: float = 0.15,
    draw_weight: float = 0.5,
) -> dict[str, float]:
    finished = [m for m in matches if m.finished]
    nodes = sorted(set(teams or []) | {m.home_team for m in finished} | {m.away_team for m in finished})
    if not nodes:
        return {}
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)

    def add_edge(source: str, target: str, weight: float):
        current = float(graph.get_edge_data(source, target, {}).get("weight", 0.0))
        graph.add_edge(source, target, weight=current + weight)

    for match in finished:
        diff = abs(int(match.home_score) - int(match.away_score))
        if match.home_score > match.away_score:
            add_edge(match.away_team, match.home_team, 1.0 + goal_diff_weight * diff)
        elif match.home_score < match.away_score:
            add_edge(match.home_team, match.away_team, 1.0 + goal_diff_weight * diff)
        else:
            add_edge(match.home_team, match.away_team, draw_weight)
            add_edge(match.away_team, match.home_team, draw_weight)
    if graph.number_of_edges() == 0:
        uniform = 1.0 / len(nodes)
        return {node: uniform for node in nodes}
    values = nx.pagerank(graph, weight="weight")
    return {team: float(values.get(team, 0.0)) for team in nodes}
