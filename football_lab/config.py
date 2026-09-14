from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class LabConfig:
    form_windows: tuple[int, ...] = (3, 5, 10)
    elo_initial_rating: float = 1500.0
    elo_k: float = 24.0
    elo_home_advantage: float = 55.0
    congestion_windows: tuple[int, ...] = (7, 14, 21)
    progressive_pass_min_advance: float = 10.0
    ppda_max_x: float = 60.0
    pagerank_goal_diff_weight: float = 0.15
    pagerank_draw_weight: float = 0.5

    def with_overrides(self, **kwargs) -> "LabConfig":
        return replace(self, **kwargs)
