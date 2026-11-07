from pathlib import Path
from types import MappingProxyType

import pytest

import satyrn_agent
from satyrn_agent import config_from_dict
from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.errors import ConfigurationError
from tests.e2e.model_free._runner import run_scenario
from tests.e2e.scenarios._generated.scenario_types import Scenario


def test_external_defaults_convert_to_domain_config() -> None:
    assert config_from_dict({}) == SatyrnConfig()


def test_external_partial_sampling_keeps_missing_top_k() -> None:
    config = config_from_dict({"sampling": {"temperature": 0.5}})

    assert config.sampling.temperature == 0.5
    assert config.sampling.top_k is None


def test_external_full_config_converts_modes_paths_and_values() -> None:
    config = config_from_dict(
        {
            "dflash": "on",
            "drafter_path": "drafter.gguf",
            "draft_tokens": 7,
            "sampling": {"temperature": 0.0, "top_k": 0, "top_p": 0.0, "min_p": 0.0},
            "think_budget": {"max_tokens": 20, "bias": 2.5},
        }
    )

    assert config == SatyrnConfig(
        dflash=DFlashMode.ON,
        drafter_path=Path("drafter.gguf"),
        draft_tokens=7,
        sampling=SamplingOverrides(temperature=0.0, top_k=0, top_p=0.0, min_p=0.0),
        think_budget=ThinkBudgetConfig(max_tokens=20, bias=2.5),
    )


@pytest.mark.parametrize(
    ("document", "error", "match"),
    [
        ([], TypeError, "object"),
        ({"unknown": 1}, ConfigurationError, "unknown"),
        ({"dflash": True}, TypeError, "dflash"),
        ({"dflash": "bogus"}, ConfigurationError, "dflash"),
        ({"drafter_path": 1}, TypeError, "drafter_path"),
        ({"draft_tokens": True}, TypeError, "draft_tokens"),
        ({"draft_tokens": -1}, ConfigurationError, "draft_tokens"),
        ({"sampling": None}, TypeError, "sampling"),
        ({"sampling": {"unknown": 1}}, ConfigurationError, "unknown sampling"),
        ({"sampling": {"temperature": -1}}, ConfigurationError, "non-negative"),
        ({"think_budget": []}, TypeError, "think_budget"),
        ({"think_budget": {}}, ConfigurationError, "max_tokens"),
        ({"sampling": {"temperature": None}}, TypeError, "temperature"),
        ({"sampling": {"top_k": True}}, TypeError, "top_k"),
        ({"sampling": {"temperature": float("nan")}}, ConfigurationError, "finite"),
        ({"sampling": {"top_p": 1.1}}, ConfigurationError, "top_p"),
        ({"sampling": {"min_p": -0.1}}, ConfigurationError, "min_p"),
        ({"think_budget": {"max_tokens": True, "bias": 1}}, TypeError, "max_tokens"),
        ({"think_budget": {"max_tokens": 0, "bias": 1}}, ConfigurationError, "max_tokens"),
        ({"think_budget": {"max_tokens": 1, "bias": 0}}, ConfigurationError, "bias"),
        ({"think_budget": {"max_tokens": 1, "bias": float("inf")}}, ConfigurationError, "bias"),
        ({"dflash": "on"}, ConfigurationError, "drafter_path"),
        ({"dflash": "on", "drafter_path": ""}, ConfigurationError, "non-empty"),
        ({"sampling": {"temperature": True}}, TypeError, "temperature"),
        ({"sampling": {"temperature": 10**1000}}, ConfigurationError, "finite"),
        ({"draft_tokens": 1.5}, TypeError, "draft_tokens"),
        ({"sampling": {"top_k": 1.0}}, TypeError, "top_k"),
        ({1: "x"}, TypeError, "object"),
        ({"dflash": "on", "drafter_path": None}, ConfigurationError, "drafter_path"),
    ],
)
def test_external_config_rejects_invalid_values(
    document: object,
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        config_from_dict(document)


def test_external_config_accepts_read_only_mappings() -> None:
    config = config_from_dict(MappingProxyType({"dflash": "off"}))

    assert config.dflash is DFlashMode.OFF


def test_invalid_external_config_never_opens_native(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("native open must not be called")

    monkeypatch.setattr(satyrn_agent, "open", forbidden_open)
    scenario = Scenario(
        version=1,
        id="invalid-external-config",
        backend="metal",
        native={"script": [], "calls": []},
        config={"dflash": "on", "drafter_path": ""},
        rounds=[],
        expected_branches={"policy-error"},
    )

    result = run_scenario(scenario)

    assert isinstance(result.rounds[0].error, ConfigurationError)
