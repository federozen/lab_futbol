from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from football_lab.models import Match


@dataclass(frozen=True)
class EloSnapshot:
    ratings: dict[str, float]
    history: list[dict]


class EloEngine:
    def __init__(self, *, initial_rating: float = 1500.0, k: float = 24.0, home_advantage: float = 55.0):
        self.initial_rating = float(initial_rating)
        self.k = float(k)
        self.home_advantage = float(home_advantage)

    @staticmethod
    def expected(rating_a: float, rating_b: float) -> float:
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    @staticmethod
    def actual(home_score: int, away_score: int) -> tuple[float, float]:
        if home_score > away_score:
            return 1.0, 0.0
        if home_score < away_score:
            return 0.0, 1.0
        return 0.5, 0.5

    @staticmethod
    def _group_key(match: Match, *, use_dates: bool):
        # No mezclar dos ejes cronológicos: si falta la fecha de al menos un resultado,
        # todo el cálculo usa jornadas. Así un partido viejo sin timestamp nunca queda
        # artificialmente después de uno reciente que sí fue fechado por scraping.
        if use_dates and match.match_date is not None:
            return (0, match.match_date)
        return (0, int(match.round or 0))

    def calculate(self, matches: list[Match], teams: list[str] | None = None) -> EloSnapshot:
        finished = [m for m in matches if m.finished]
        team_list = sorted(set(teams or []) | {m.home_team for m in finished} | {m.away_team for m in finished})
        ratings = {t: self.initial_rating for t in team_list}
        history: list[dict] = []
        groups: dict[object, list[Match]] = defaultdict(list)
        use_dates = bool(finished) and all(match.match_date is not None for match in finished)
        for match in finished:
            groups[self._group_key(match, use_dates=use_dates)].append(match)

        for key in sorted(groups):
            delta = defaultdict(float)
            before = ratings.copy()
            for match in sorted(groups[key], key=lambda m: m.match_id):
                rh = before.get(match.home_team, self.initial_rating)
                ra = before.get(match.away_team, self.initial_rating)
                expected_home = self.expected(rh + self.home_advantage, ra)
                actual_home, actual_away = self.actual(int(match.home_score), int(match.away_score))
                change_home = self.k * (actual_home - expected_home)
                delta[match.home_team] += change_home
                delta[match.away_team] -= change_home
                history.append({
                    "match_id": match.match_id,
                    "round": match.round,
                    "match_date": match.match_date.isoformat() if match.match_date else None,
                    "home_team": match.home_team,
                    "away_team": match.away_team,
                    "home_before": rh,
                    "away_before": ra,
                    "home_expected": expected_home,
                    "home_change": change_home,
                    "home_after": None,
                    "away_after": None,
                    "group_key": str(key[1]),
                })
            for team, value in delta.items():
                ratings[team] = before.get(team, self.initial_rating) + value
            for item in history:
                if item["group_key"] == str(key[1]) and item["home_after"] is None:
                    item["home_after"] = ratings[item["home_team"]]
                    item["away_after"] = ratings[item["away_team"]]
        return EloSnapshot(ratings=ratings, history=history)
