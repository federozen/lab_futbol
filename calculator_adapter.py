from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from football_lab.models import Match, ProviderDataset
from football_lab.utils import parse_datetime, slug
from lpf_clubs import canon_club
from lpf_data_2026 import LPF_FIXTURE


class ExistingCalculatorProvider:
    """Adapta el fixture y los resultados incluidos en la Calculadora LPF.

    No requiere Opta ni red. Si existe un CSV de calendario con fechas reales,
    las incorpora; de lo contrario conserva la jornada como eje cronologico.
    """

    provider_name = "calculadora_lpf"

    def __init__(self, root: str | Path | None = None, *, schedule_path: str | Path | None = None):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self.results_path = self.root / "data" / "sample" / "calculadora_results_2026.csv"
        self.schedule_path = Path(schedule_path) if schedule_path else self.root / "data" / "sample" / "schedule_2026.csv"

    def _results(self) -> dict[tuple[str, str], tuple[int, int]]:
        out: dict[tuple[str, str], tuple[int, int]] = {}
        with self.results_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                home = canon_club(row["home_team"])
                away = canon_club(row["away_team"])
                out[(home, away)] = (int(row["home_score"]), int(row["away_score"]))
        return out

    def _schedule(self) -> dict[tuple[str, str], object]:
        if not self.schedule_path.exists():
            return {}
        out = {}
        with self.schedule_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                home = canon_club(row.get("home_team", ""))
                away = canon_club(row.get("away_team", ""))
                if home and away:
                    out[(home, away)] = parse_datetime(row.get("match_date"))
        return out

    def load(self) -> ProviderDataset:
        results = self._results()
        schedule = self._schedule()
        matches: list[Match] = []
        groups: dict[str, str] = {}

        for game in LPF_FIXTURE:
            home = canon_club(game["l"])
            away = canon_club(game["v"])
            round_no = int(game["f"])
            zone = game.get("zona")
            if zone:
                groups.setdefault(home, str(zone))
                groups.setdefault(away, str(zone))
            score = results.get((home, away))
            match_date = schedule.get((home, away))
            match_id = f"LPF-2026-C-{round_no:02d}-{slug(home)}-{slug(away)}"
            matches.append(
                Match(
                    match_id=match_id,
                    competition="Liga Profesional",
                    season="Clausura 2026",
                    round=round_no,
                    match_date=match_date,
                    home_team=home,
                    away_team=away,
                    home_score=score[0] if score else None,
                    away_score=score[1] if score else None,
                    status="finished" if score else "scheduled",
                    source="Calculadora LPF",
                )
            )

        dated = sum(1 for m in matches if m.match_date is not None)
        metadata = {
            "provider": self.provider_name,
            "sources": ["Calculadora LPF: fixture 2026", "Calculadora LPF: resultados incluidos"],
            "opta_required": False,
            "events_available": False,
            "players_available": False,
            "xg_available": False,
            "dates_available": bool(dated),
            "dated_matches": dated,
            "chronology_basis": "match_date" if dated == len(matches) else "round",
            "warning": (
                "La fuente base no conserva fecha exacta para todos los partidos. "
                "Cuando falta, el corte anti-leakage usa solo jornadas anteriores."
                if dated < len(matches) else ""
            ),
        }
        return ProviderDataset(tuple(matches), team_groups=groups, metadata=metadata)
