from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from football_lab.models import Match, ProviderDataset, TeamMatch


def to_team_match(match: Match, team: str) -> TeamMatch:
    if not match.finished:
        raise ValueError("El partido debe estar terminado")
    if team not in (match.home_team, match.away_team):
        raise ValueError("El equipo no participa del partido")
    home = team == match.home_team
    gf = int(match.home_score if home else match.away_score)
    ga = int(match.away_score if home else match.home_score)
    result = "G" if gf > ga else "E" if gf == ga else "P"
    points = 3 if result == "G" else 1 if result == "E" else 0
    return TeamMatch(
        match_id=match.match_id,
        team=team,
        opponent=match.away_team if home else match.home_team,
        venue="local" if home else "visitante",
        goals_for=gf,
        goals_against=ga,
        points=points,
        result=result,
        round=match.round,
        match_date=match.match_date,
    )


class MatchRepository:
    def __init__(self, dataset: ProviderDataset):
        self.dataset = dataset
        self._by_id = {m.match_id: m for m in dataset.matches}

    @property
    def teams(self) -> list[str]:
        return sorted({m.home_team for m in self.dataset.matches} | {m.away_team for m in self.dataset.matches})

    def get(self, match_id: str) -> Match:
        try:
            return self._by_id[match_id]
        except KeyError as exc:
            raise KeyError(f"Partido inexistente: {match_id}") from exc

    def all_matches(self) -> list[Match]:
        return list(self.dataset.matches)

    def finished(self) -> list[Match]:
        return [m for m in self.dataset.matches if m.finished]

    def scheduled(self) -> list[Match]:
        return [m for m in self.dataset.matches if not m.finished]

    def _strictly_before(self, historical: Match, target: Match) -> bool:
        if not historical.finished:
            return False
        if historical.match_id == target.match_id:
            return False
        if target.match_date is not None and historical.match_date is not None:
            return historical.match_date < target.match_date
        if target.round is not None and historical.round is not None:
            # Sin fecha exacta, no usamos ningun partido de la misma jornada.
            return historical.round < target.round
        return False

    def finished_before_match(self, target: Match) -> list[Match]:
        return [m for m in self.dataset.matches if self._strictly_before(m, target)]

    def finished_before_date(self, cutoff: datetime) -> list[Match]:
        return [m for m in self.dataset.matches if m.finished and m.match_date is not None and m.match_date < cutoff]

    def team_history(self, team: str, matches: list[Match] | None = None) -> list[TeamMatch]:
        source = matches if matches is not None else self.finished()
        rows = [to_team_match(m, team) for m in source if team in (m.home_team, m.away_team) and m.finished]
        # Si todas las fichas tienen fecha exacta, respetar cronología real. En una
        # cobertura mixta no se mandan partidos viejos sin timestamp al final: se usa
        # la jornada como eje conservador y la fecha sólo como desempate.
        if rows and all(row.match_date is not None for row in rows):
            return sorted(rows, key=lambda x: (x.match_date, x.round or 0, x.match_id))
        return sorted(rows, key=lambda x: (x.round or 0, x.match_date.isoformat() if x.match_date else "", x.match_id))

    def current_round_hint(self) -> int | None:
        finished_rounds = [m.round for m in self.finished() if m.round is not None]
        return max(finished_rounds) if finished_rounds else None

    def next_matches(self, limit: int = 10) -> list[Match]:
        current = self.current_round_hint() or 0
        now = datetime.now(timezone.utc)
        upcoming: list[Match] = []
        for match in self.scheduled():
            if match.status in {"cancelled"}:
                continue
            if match.status == "live":
                upcoming.append(match)
                continue
            if match.match_date is not None:
                stamp = match.match_date
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                # Una fuente que todavía marca "por jugar" un partido de ayer no
                # debe hacerlo aparecer como próximo. Se concede una ventana de
                # cuatro horas para encuentros recién iniciados/atrasados.
                if stamp >= now - timedelta(hours=4):
                    upcoming.append(match)
                continue
            # Sin fecha exacta usamos la jornada como fallback conservador. El viejo
            # código calculaba ``current`` pero no lo aplicaba, por eso un hueco de
            # Fecha 4 podía aparecer como próximo aun con resultados de Fecha 9.
            if match.round is None or match.round >= current:
                upcoming.append(match)

        far_future = datetime.max.replace(tzinfo=timezone.utc)
        return sorted(
            upcoming,
            key=lambda m: (
                m.match_date is None,
                (m.match_date.replace(tzinfo=timezone.utc) if m.match_date and m.match_date.tzinfo is None else m.match_date) or far_future,
                m.round if m.round is not None else 10_000,
                m.match_id,
            ),
        )[:limit]
