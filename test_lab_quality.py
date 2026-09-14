import pandas as pd

from football_lab.data.csv_provider import DataFrameProvider
from football_lab.services.lab_service import LabService


def test_missing_dates_are_warning_not_fake_zero():
    df = pd.DataFrame([
        {"match_id": "m1", "round": 1, "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 0, "status": "finished"},
        {"match_id": "m2", "round": 2, "home_team": "A", "away_team": "B", "status": "scheduled"},
    ])
    service = LabService(DataFrameProvider(df))
    quality = service.data_quality()
    assert quality["status"] == "warning"
    assert quality["dated_matches"] == 0
    features = service.get_match_features("m2")["features"]
    assert features["home"]["context"]["days_rest"] is None
    assert features["home"]["context"]["available"] is False
