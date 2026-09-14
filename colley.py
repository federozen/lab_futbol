from __future__ import annotations

import numpy as np

from football_lab.models import Match


def colley_ratings(matches: list[Match], *, teams: list[str] | None = None) -> dict[str, float]:
    finished = [m for m in matches if m.finished]
    team_list = sorted(set(teams or []) | {m.home_team for m in finished} | {m.away_team for m in finished})
    if not team_list:
        return {}
    index = {team: i for i, team in enumerate(team_list)}
    n = len(team_list)
    c = np.eye(n) * 2.0
    wins = np.zeros(n)
    losses = np.zeros(n)
    for match in finished:
        i, j = index[match.home_team], index[match.away_team]
        c[i, i] += 1
        c[j, j] += 1
        c[i, j] -= 1
        c[j, i] -= 1
        if match.home_score > match.away_score:
            wins[i] += 1; losses[j] += 1
        elif match.home_score < match.away_score:
            wins[j] += 1; losses[i] += 1
    b = 1.0 + (wins - losses) / 2.0
    ratings = np.linalg.solve(c, b)
    return {team: float(ratings[index[team]]) for team in team_list}
