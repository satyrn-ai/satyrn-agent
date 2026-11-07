import pytest

from tests.e2e.model_free._runner import SUPPORTED_BRANCHES, assert_scenario, run_scenario
from tests.e2e.model_free._schema import iter_scenarios
from tests.e2e.scenarios._generated.scenario_types import Scenario


@pytest.mark.parametrize("scenario", list(iter_scenarios()), ids=lambda scenario: scenario["id"])
def test_model_free_scenario(scenario: Scenario) -> None:
    result = run_scenario(scenario)

    assert_scenario(scenario, result)


def test_every_supported_branch_has_a_scenario() -> None:
    scenarios = list(iter_scenarios())
    observed = set().union(*(run_scenario(scenario).reached_branches for scenario in scenarios))
    declared = set().union(*(scenario["expected_branches"] for scenario in scenarios))

    assert observed >= SUPPORTED_BRANCHES
    assert declared >= SUPPORTED_BRANCHES
