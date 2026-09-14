from datetime import datetime, timezone

import pandas as pd

from football_lab.data.csv_provider import DataFrameProvider
from football_lab.services.lab_service import LabService


def _service(rows):
    return LabService(DataFrameProvider(pd.DataFrame(rows), "test"))


def test_round_cutoff_excludes_target_same_round_and_future_when_dates_missing():
    rows = [
        {"match_id": "r1", "round": 1, "home_team": "River", "away_team": "Boca", "home_score": 2, "away_score": 0, "status": "finished"},
        {"match_id": "same-round-finished", "round": 2, "home_team": "River", "away_team": "Racing", "home_score": 5, "away_score": 0, "status": "finished"},
        {"match_id": "target", "round": 2, "home_team": "River", "away_team": "Independiente", "status": "scheduled"},
        {"match_id": "future", "round": 3, "home_team": "River", "away_team": "Velez", "home_score": 9, "away_score": 0, "status": "finished"},
    ]
    service = _service(rows)
    features = service.get_match_features("target")["features"]
    assert features["metadata"]["history_match_ids"] == ["r1"]
    assert features["home"]["form"]["goals_for_total"] == 2
    assert features["home"]["form"]["points_total"] == 3


def test_exact_date_cutoff_excludes_current_and_future():
    rows = [
        {"match_id": "past", "round": 1, "match_date": "2026-01-01T18:00:00+00:00", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 0, "status": "finished"},
        {"match_id": "target", "round": 1, "match_date": "2026-01-02T18:00:00+00:00", "home_team": "A", "away_team": "C", "status": "scheduled"},
        {"match_id": "future", "round": 1, "match_date": "2026-01-03T18:00:00+00:00", "home_team": "A", "away_team": "D", "home_score": 8, "away_score": 0, "status": "finished"},
    ]
    service = _service(rows)
    features = service.get_match_features("target")["features"]
    assert features["metadata"]["history_match_ids"] == ["past"]
    assert features["home"]["form"]["goals_for_total"] == 1


def test_rest_uses_only_previous_dated_match():
    rows = [
        {"match_id": "past", "round": 1, "match_date": "2026-01-01T18:00:00+00:00", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 0, "status": "finished"},
        {"match_id": "target", "round": 2, "match_date": "2026-01-05T18:00:00+00:00", "home_team": "A", "away_team": "C", "status": "scheduled"},
    ]
    service = _service(rows)
    features = service.get_match_features("target")["features"]
    assert features["home"]["context"]["days_rest"] == 4.0
