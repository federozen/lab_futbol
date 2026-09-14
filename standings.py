from __future__ import annotations

from football_lab.models import Match


def team_totals(team: str, matches: list[Match]) -> dict:
    pts = pj = gf = ga = 0
    for match in matches:
        if not match.finished or team not in (match.home_team, match.away_team):
            continue
        home = team == match.home_team
        team_g = int(match.home_score if home else match.away_score)
        opp_g = int(match.away_score if home else match.home_score)
        pj += 1; gf += team_g; ga += opp_g
        pts += 3 if team_g > opp_g else 1 if team_g == opp_g else 0
    return {"team": team, "played": pj, "points": pts, "goals_for": gf, "goals_against": ga, "goal_difference": gf - ga}


def standings(matches: list[Match], teams: list[str]) -> list[dict]:
    rows = [team_totals(team, matches) for team in teams]
    rows.sort(key=lambda row: (-row["points"], -row["goal_difference"], -row["goals_for"], row["team"]))
    for idx, row in enumerate(rows, 1):
        row["position"] = idx
    return rows
