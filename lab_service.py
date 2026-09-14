from __future__ import annotations

from datetime import datetime
from statistics import mean

from football_lab.config import LabConfig
from football_lab.data.base import DataProvider
from football_lab.feature_engineering.form import form_features
from football_lab.feature_engineering.pipeline import FeatureEngineer
from football_lab.narratives.comparison import comparison_narrative
from football_lab.narratives.match import match_narrative
from football_lab.narratives.team import team_narrative
from football_lab.rankings.service import all_rankings
from football_lab.repositories import MatchRepository
from football_lab.services.data_quality_service import data_quality_report
from football_lab.standings import standings
from football_lab.utils import json_safe


class LabService:
    """Frontera estable y JSON-safe para Streamlit, una API futura o procesos batch."""

    service_version = "1"

    def __init__(self, provider: DataProvider, config: LabConfig | None = None, *, dataset=None):
        self.provider = provider
        self.config = config or LabConfig()
        self.dataset = dataset if dataset is not None else provider.load()
        self.repository = MatchRepository(self.dataset)
        self.engineer = FeatureEngineer(self.repository, self.config)

    @property
    def teams(self) -> list[str]:
        return self.repository.teams

    def _history(self, date: datetime | None = None):
        if date is None:
            return self.repository.finished()
        return self.repository.finished_before_date(date)

    def get_team_profile(self, team_id: str, date: datetime | None = None) -> dict:
        history = self._history(date)
        rankings = all_rankings(history, self.teams, self.config)
        profile = self.engineer.team_features(team_id, history, rankings=rankings)
        elo_values = list(rankings.get("elo", {}).values())
        profile["narrative"] = team_narrative(team_id, profile, elo_average=mean(elo_values) if elo_values else None)
        return json_safe({"service_version": self.service_version, "team": team_id, "profile": profile})

    def get_match_features(self, match_id: str) -> dict:
        result = self.engineer.for_match(match_id)
        match = result["metadata"]["match"]
        result["narrative"] = match_narrative(match["home_team"], match["away_team"], result)
        return json_safe({"service_version": self.service_version, "features": result})

    def compare_teams(self, team_a: str, team_b: str, date: datetime | None = None) -> dict:
        history = self._history(date)
        rankings = all_rankings(history, self.teams, self.config)
        a = self.engineer.team_features(team_a, history, rankings=rankings)
        b = self.engineer.team_features(team_b, history, rankings=rankings)
        differences = FeatureEngineer._differences(a, b)
        result = {"team_a": {"team": team_a, **a}, "team_b": {"team": team_b, **b}, "differences": differences}
        result["narrative"] = comparison_narrative(team_a, team_b, result)
        return json_safe({"service_version": self.service_version, "comparison": result})

    def get_rankings(self, date: datetime | None = None) -> dict:
        history = self._history(date)
        result = all_rankings(history, self.teams, self.config)
        return json_safe({"service_version": self.service_version, "rankings": result})

    def get_team_form(self, team_id: str, date: datetime | None = None, window: int = 5) -> dict:
        history = self.repository.team_history(team_id, self._history(date))
        values = form_features(history, tuple(sorted(set(self.config.form_windows + (int(window),)))))
        return json_safe({"service_version": self.service_version, "team": team_id, "window": window, "form": values})

    def get_current_standings(self) -> dict:
        history = self.repository.finished()
        groups = sorted(set(self.dataset.team_groups.values()))
        if groups:
            out = {}
            for group in groups:
                teams = [t for t, g in self.dataset.team_groups.items() if g == group]
                out[group] = standings(history, teams)
            return json_safe(out)
        return json_safe({"general": standings(history, self.teams)})

    def data_quality(self) -> dict:
        return json_safe(data_quality_report(self.dataset))

    def next_matches(self, limit: int = 12) -> list[dict]:
        return [m.to_dict() for m in self.repository.next_matches(limit)]

    def with_config(self, config: LabConfig) -> "LabService":
        # El laboratorio no debe volver a hacer scraping sólo por mover un slider.
        return LabService(self.provider, config=config, dataset=self.dataset)
