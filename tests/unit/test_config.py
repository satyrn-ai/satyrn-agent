from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig


def test_config_defaults_are_immutable_and_slotted() -> None:
    config = SatyrnConfig()

    assert config.dflash is DFlashMode.AUTO
    assert config.drafter_path is None
    assert config.draft_tokens == 0
    assert config.sampling == SamplingOverrides()
    assert config.think_budget is None
    assert not hasattr(config, "__dict__")
    with pytest.raises(FrozenInstanceError):
        config.__setattr__("draft_tokens", 7)


def test_explicit_zero_sampling_overrides_are_values() -> None:
    overrides = SamplingOverrides(temperature=0.0, top_k=0, top_p=0.0, min_p=0.0)

    assert overrides.temperature == 0.0
    assert overrides.top_k == 0
    assert overrides.top_p == 0.0
    assert overrides.min_p == 0.0


@pytest.mark.parametrize("field", ["temperature", "top_k", "top_p", "min_p"])
def test_sampling_rejects_boolean_numbers(field: str) -> None:
    with pytest.raises(TypeError, match=field):
        SamplingOverrides(**{field: True})


@pytest.mark.parametrize("value", [-1, True])
def test_draft_tokens_reject_negative_and_boolean(value: int | bool) -> None:
    with pytest.raises((TypeError, ValueError), match="draft_tokens"):
        SatyrnConfig(draft_tokens=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_temperature_rejects_non_finite_and_negative(value: float) -> None:
    with pytest.raises(ValueError, match="temperature"):
        SamplingOverrides(temperature=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01])
def test_top_p_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError, match="top_p"):
        SamplingOverrides(top_p=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01])
def test_min_p_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError, match="min_p"):
        SamplingOverrides(min_p=value)


def test_top_k_rejects_negative() -> None:
    with pytest.raises(ValueError, match="top_k"):
        SamplingOverrides(top_k=-1)


@pytest.mark.parametrize("value", [0, -1, True])
def test_think_budget_rejects_non_positive_or_boolean_tokens(value: int | bool) -> None:
    with pytest.raises((TypeError, ValueError), match="max_tokens"):
        ThinkBudgetConfig(max_tokens=value, bias=1.0)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True])
def test_think_budget_rejects_non_positive_non_finite_or_boolean_bias(value: float | bool) -> None:
    with pytest.raises((TypeError, ValueError), match="bias"):
        ThinkBudgetConfig(max_tokens=10, bias=value)


def test_config_rejects_wrong_enum_and_path_types() -> None:
    with pytest.raises(ValueError, match="DFlashMode"):
        SatyrnConfig(dflash=cast("DFlashMode", object()))
    with pytest.raises(TypeError, match="drafter_path"):
        SatyrnConfig(drafter_path=cast("Path", object()))


def test_on_requires_drafter_before_native_open() -> None:
    with pytest.raises(ValueError, match="drafter_path"):
        SatyrnConfig(dflash=DFlashMode.ON)

    config = SatyrnConfig(dflash=DFlashMode.ON, drafter_path=Path("drafter.gguf"))
    assert config.drafter_path == Path("drafter.gguf")
