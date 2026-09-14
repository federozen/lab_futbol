from __future__ import annotations

from football_lab.config import LabConfig
from football_lab.feature_engineering.defense import defense_features
from football_lab.feature_engineering.form import form_features
from football_lab.feature_engineering.passing import passing_features
from football_lab.feature_engineering.players import player_features
from football_lab.feature_engineering.pressing import ppda_features
from football_lab.feature_engineering.rankings import ranking_features
from football_lab.feature_engineering.rest import rest_features
from football_lab.feature_engineering.set_pieces import set_piece_features
from football_lab.feature_engineering.venue import venue_features
from football_lab.feature_engineering.xg import xg_features
from football_lab.models import Match
from football_lab.rankings.service import all_rankings
from football_lab.repositories import MatchRepository
from football_lab.standings import standings, team_totals
from football_lab.utils import numeric_difference


class FeatureEngineer:
    def __init__(self, repository: MatchRepository, config: LabConfig | None = None):
        self.repository = repository
        self.dataset = repository.dataset
        self.config = config or LabConfig()

    def _events_for_history(self, history: list[Match]):
        ids = {m.match_id for m in history}
        return [e for e in self.dataset.events if e.match_id in ids]

    def _reality(self, team: str, history: list[Match]) -> dict:
        totals = team_totals(team, history)
        group = self.dataset.team_groups.get(team)
        group_teams = [t for t, g in self.dataset.team_groups.items() if g == group] if group else self.repository.teams
        table = standings(history, group_teams)
        row = next((r for r in table if r["team"] == team), None)
        return {**totals, "position": row.get("position") if row else None, "group": group}

    def team_features(self, team: str, history: list[Match], *, target: Match | None = None, rankings: dict | None = None) -> dict:
        team_history = self.repository.team_history(team, history)
        rankings = rankings or all_rankings(history, self.repository.teams, self.config)
        events = self._events_for_history(history)
        return {
            "reality": self._reality(team, history),
            "form": form_features(team_history, self.config.form_windows),
            "venue": venue_features(team_history),
            "strength": ranking_features(team, rankings),
            "context": (
                rest_features(team_history, target, self.config.congestion_windows)
                if target is not None else {
                    "available": False,
                    "reason": "El descanso necesita un partido objetivo con fecha exacta.",
                    "days_rest": None,
                }
            ),
            "attack_quality": xg_features(events, team),
            "passing": passing_features(events, team, progressive_threshold=self.config.progressive_pass_min_advance),
            "defense": defense_features(events, team),
            "pressing": ppda_features(events, team, max_x=self.config.ppda_max_x),
            "set_pieces": set_piece_features(events, team),
            "players": player_features(self.dataset.players, events, team),
        }

    @staticmethod
    def _differences(home: dict, away: dict) -> dict:
        candidates = {
            "points_last_5_diff": (home["form"].get("points_last_5"), away["form"].get("points_last_5")),
            "points_per_match_5_diff": (home["form"].get("points_per_match_5"), away["form"].get("points_per_match_5")),
            "goals_for_avg_5_diff": (home["form"].get("goals_for_avg_5"), away["form"].get("goals_for_avg_5")),
            "goals_against_avg_5_diff": (home["form"].get("goals_against_avg_5"), away["form"].get("goals_against_avg_5")),
            "elo_diff": (home["strength"].get("elo"), away["strength"].get("elo")),
            "colley_diff": (home["strength"].get("colley"), away["strength"].get("colley")),
            "pagerank_diff": (home["strength"].get("pagerank"), away["strength"].get("pagerank")),
            "rest_diff": (home["context"].get("days_rest"), away["context"].get("days_rest")),
            "xg_diff": (home["attack_quality"].get("total_xg"), away["attack_quality"].get("total_xg")),
        }
        return {key: numeric_difference(a, b) for key, (a, b) in candidates.items()}

    def for_match(self, match_id: str) -> dict:
        target = self.repository.get(match_id)
        history = self.repository.finished_before_match(target)
        rankings = all_rankings(history, self.repository.teams, self.config)
        home = self.team_features(target.home_team, history, target=target, rankings=rankings)
        away = self.team_features(target.away_team, history, target=target, rankings=rankings)
        return {
            "home": home,
            "away": away,
            "differences": self._differences(home, away),
            "metadata": {
                "match": target.to_dict(),
                "history_matches_used": len(history),
                "history_match_ids": [m.match_id for m in history],
                "max_round_used": max((m.round or 0 for m in history), default=0),
                "chronology_basis": self.dataset.metadata.get("chronology_basis", "unknown"),
                "leakage_guard": "strict_before_target",
                "source": self.dataset.metadata.get("provider", ""),
            },
        }
