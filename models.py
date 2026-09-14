from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Match:
    match_id: str
    competition: str
    season: str
    round: int | None
    match_date: datetime | None
    home_team: str
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    status: str = "scheduled"
    source: str = ""

    @property
    def finished(self) -> bool:
        return self.status == "finished" and self.home_score is not None and self.away_score is not None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["match_date"] = self.match_date.isoformat() if self.match_date else None
        return out


@dataclass(frozen=True)
class TeamMatch:
    match_id: str
    team: str
    opponent: str
    venue: str
    goals_for: int
    goals_against: int
    points: int
    result: str
    round: int | None = None
    match_date: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["match_date"] = self.match_date.isoformat() if self.match_date else None
        return out


@dataclass(frozen=True)
class Event:
    match_id: str
    team: str
    player: str | None
    type: str
    minute: float | None = None
    location: tuple[float, float] | None = None
    end_location: tuple[float, float] | None = None
    xg: float | None = None
    outcome: str | None = None
    play_pattern: str | None = None


@dataclass(frozen=True)
class Player:
    player_id: str
    player_name: str
    team: str
    position: str | None = None


@dataclass(frozen=True)
class ProviderDataset:
    matches: tuple[Match, ...]
    events: tuple[Event, ...] = ()
    players: tuple[Player, ...] = ()
    team_groups: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "reason": self.reason}


@dataclass(frozen=True)
class ModelInput:
    elo_diff: float | None
    points_last_5_diff: float | None
    xg_diff: float | None
    rest_diff: float | None
    home_advantage: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
