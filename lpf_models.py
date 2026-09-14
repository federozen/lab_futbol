"""Modelos de dominio y auditoría para la calculadora LPF.

El objetivo de este módulo es desacoplar el cálculo de la redacción y de Streamlit.
Todos los renderizadores deberían consumir estos objetos o sus ``to_dict``.
"""
from __future__ import annotations

LPF_RUNTIME_API = 21


from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from lpf_version import __version__

ResultKind = Literal["exact", "safe_guarantee", "estimate", "partial"]
DataLevel = Literal["ok", "warning", "blocked"]


@dataclass(frozen=True)
class AuditIssue:
    code: str
    message: str
    level: DataLevel = "warning"
    domain: str = "general"
    teams: tuple[str, ...] = ()
    suggestion: str = ""


@dataclass
class AuditMetadata:
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    data_updated_at: str | None = None
    competition: str = "LPF 2026"
    calculation_version: str = field(default_factory=lambda: __version__)
    rules_version: str = "LPF-2026"
    seed: int | None = None
    simulations: int | None = None
    data_status: DataLevel = "ok"
    limitations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchRecord:
    match_id: str
    round_number: int
    home: str
    away: str
    kind: str = "zone"
    zone: str | None = None
    status: str = "scheduled"
    home_goals: int | None = None
    away_goals: int | None = None
    inferred: bool = False
    original_round: int | None = None
    source: str = "fixture"


@dataclass
class PointLadderRow:
    final_points: int
    status: str
    can_qualify: bool
    can_fail: bool
    guaranteed: bool
    example: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ObjectiveAnalysis:
    team: str
    objective: str
    current_points: int
    current_rank: int | None
    games_left: int
    points_available: int
    ceiling: int
    current_cutoff: int | None = None
    minimum_possible: int | None = None
    projected_cutoff: tuple[int, int] | None = None
    safe_guarantee: int | None = None
    guarantee_is_exact: bool = False
    controls_destiny: bool | None = None
    needs_help: bool | None = None
    ladder: list[PointLadderRow] = field(default_factory=list)
    audit: AuditMetadata = field(default_factory=AuditMetadata)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchResultScenario:
    result: str
    points_after: int
    best_rank: int | None
    worst_rank: int | None
    best_rank_without_tiebreak: int | None = None
    controls_destiny_after: bool | None = None
    can_enter_target: bool = False
    can_leave_target: bool = False
    can_clinch: bool = False
    can_be_eliminated: bool = False
    explanation: str = ""
    witness: list[str] = field(default_factory=list)


@dataclass
class RoundPreview:
    team: str
    round_number: int | None
    scope: str
    own_match: dict[str, Any] | None
    result_scenarios: list[MatchResultScenario]
    other_matches: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    audit: AuditMetadata = field(default_factory=AuditMetadata)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualityReport:
    level: DataLevel
    issues: list[AuditIssue]
    details: list[str] = field(default_factory=list)
    authoritative_annual: dict[str, dict[str, int]] = field(default_factory=dict)
    opening_snapshot: dict[str, dict[str, int]] = field(default_factory=dict)
    match_records: list[MatchRecord] = field(default_factory=list)

    @property
    def blocked_domains(self) -> set[str]:
        return {i.domain for i in self.issues if i.level == "blocked"}

    def messages(self, domain: str | None = None) -> list[str]:
        return [
            issue.message
            for issue in self.issues
            if domain is None or issue.domain in (domain, "general")
        ]
