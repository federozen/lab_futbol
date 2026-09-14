from football_lab.data.calculator_adapter import ExistingCalculatorProvider
from football_lab.services.lab_service import LabService


def test_existing_calculator_provider_loads_offline_base():
    dataset = ExistingCalculatorProvider().load()
    assert len(dataset.matches) == 240
    assert sum(m.finished for m in dataset.matches) == 49
    assert len({m.home_team for m in dataset.matches} | {m.away_team for m in dataset.matches}) == 30
    assert dataset.metadata["opta_required"] is False
    assert dataset.metadata["chronology_basis"] == "round"


def test_service_is_json_safe_and_has_rankings():
    service = LabService(ExistingCalculatorProvider())
    profile = service.get_team_profile("River Plate")
    assert profile["service_version"] == "1"
    assert isinstance(profile["profile"]["strength"]["elo"], float)
    assert profile["profile"]["attack_quality"]["available"] is False


def test_next_matches_does_not_resurface_old_undated_round_gap():
    from football_lab.models import Match, ProviderDataset
    from football_lab.repositories import MatchRepository

    matches = (
        Match("f8-done", "Liga Profesional", "Clausura 2026", 8, None, "River Plate", "Racing", 1, 0, "finished", "test"),
        Match("f4-gap", "Liga Profesional", "Clausura 2026", 4, None, "Boca Juniors", "Vélez Sarsfield", None, None, "scheduled", "test"),
        Match("f8-pending", "Liga Profesional", "Clausura 2026", 8, None, "Banfield", "Belgrano", None, None, "scheduled", "test"),
        Match("f9-pending", "Liga Profesional", "Clausura 2026", 9, None, "Tigre", "Rosario Central", None, None, "scheduled", "test"),
    )
    repo = MatchRepository(ProviderDataset(matches))
    ids = [match.match_id for match in repo.next_matches(10)]
    assert "f4-gap" not in ids
    assert ids == ["f8-pending", "f9-pending"]
