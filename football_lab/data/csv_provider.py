from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from football_lab.models import Match, ProviderDataset
from football_lab.utils import parse_datetime, slug
from lpf_clubs import canon_club


_REQUIRED = {"home_team", "away_team"}


def dataframe_to_dataset(df: pd.DataFrame, *, provider_name: str = "csv") -> ProviderDataset:
    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(sorted(missing)))
    matches: list[Match] = []
    groups: dict[str, str] = {}
    for idx, row in df.fillna("").iterrows():
        home = canon_club(str(row["home_team"]))
        away = canon_club(str(row["away_team"]))
        round_raw = row.get("round", "")
        try:
            round_no = int(round_raw) if str(round_raw).strip() else None
        except ValueError:
            round_no = None
        home_score = None if str(row.get("home_score", "")).strip() == "" else int(float(row.get("home_score")))
        away_score = None if str(row.get("away_score", "")).strip() == "" else int(float(row.get("away_score")))
        status = str(row.get("status") or ("finished" if home_score is not None and away_score is not None else "scheduled")).lower()
        date = parse_datetime(row.get("match_date"))
        mid = str(row.get("match_id") or f"CSV-{idx}-{slug(home)}-{slug(away)}")
        group_home = str(row.get("home_group") or "").strip()
        group_away = str(row.get("away_group") or "").strip()
        if group_home:
            groups[home] = group_home
        if group_away:
            groups[away] = group_away
        matches.append(Match(
            match_id=mid,
            competition=str(row.get("competition") or "Competencia"),
            season=str(row.get("season") or "Temporada"),
            round=round_no,
            match_date=date,
            home_team=home,
            away_team=away,
            home_score=home_score,
            away_score=away_score,
            status=status,
            source=provider_name,
        ))
    dated = sum(m.match_date is not None for m in matches)
    metadata: dict[str, Any] = {
        "provider": provider_name,
        "sources": [provider_name],
        "opta_required": False,
        "events_available": False,
        "players_available": False,
        "xg_available": False,
        "dates_available": bool(dated),
        "dated_matches": int(dated),
        "chronology_basis": "match_date" if dated == len(matches) else "round",
    }
    return ProviderDataset(tuple(matches), team_groups=groups, metadata=metadata)


class CSVProvider:
    provider_name = "csv"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> ProviderDataset:
        return dataframe_to_dataset(pd.read_csv(self.path), provider_name=self.path.name)

class DataFrameProvider:
    provider_name = "csv_subido"

    def __init__(self, dataframe: pd.DataFrame, name: str = "CSV subido"):
        self.dataframe = dataframe.copy()
        self.name = name

    def load(self) -> ProviderDataset:
        return dataframe_to_dataset(self.dataframe, provider_name=self.name)
