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
