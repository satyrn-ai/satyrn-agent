from pathlib import Path

import pytest

from satyrn_agent import config_from_dict
from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig


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
        ({"unknown": 1}, ValueError, "unknown"),
        ({"dflash": True}, ValueError, "dflash"),
        ({"drafter_path": 1}, TypeError, "drafter_path"),
        ({"draft_tokens": True}, TypeError, "draft_tokens"),
        ({"draft_tokens": -1}, ValueError, "draft_tokens"),
        ({"sampling": None}, TypeError, "sampling"),
        ({"sampling": {"unknown": 1}}, ValueError, "unknown sampling"),
        ({"sampling": {"temperature": -1}}, ValueError, "non-negative"),
        ({"think_budget": []}, TypeError, "think_budget"),
        ({"think_budget": {}}, ValueError, "max_tokens"),
        ({"sampling": {"temperature": None}}, TypeError, "temperature"),
        ({"sampling": {"top_k": True}}, TypeError, "top_k"),
        ({"sampling": {"temperature": float("nan")}}, ValueError, "finite"),
        ({"sampling": {"top_p": 1.1}}, ValueError, "top_p"),
        ({"sampling": {"min_p": -0.1}}, ValueError, "min_p"),
        ({"think_budget": {"max_tokens": True, "bias": 1}}, TypeError, "max_tokens"),
        ({"think_budget": {"max_tokens": 0, "bias": 1}}, ValueError, "max_tokens"),
        ({"think_budget": {"max_tokens": 1, "bias": 0}}, ValueError, "bias"),
        ({"think_budget": {"max_tokens": 1, "bias": float("inf")}}, ValueError, "bias"),
        ({"dflash": "on"}, ValueError, "drafter_path"),
        ({"dflash": "on", "drafter_path": None}, ValueError, "drafter_path"),
    ],
)
def test_external_config_rejects_invalid_values(
    document: object,
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        config_from_dict(document)
