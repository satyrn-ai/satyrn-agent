"""Immutable public configuration for the Satyrn engine factory."""

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .errors import ConfigurationError


class DFlashMode(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


def _integer(value: int, name: str, *, minimum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")


def _finite(value: float, name: str) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError(f"{name} must be a real number")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ConfigurationError(f"{name} must be finite") from error
    if not finite:
        raise ConfigurationError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class ThinkBudgetConfig:
    max_tokens: int
    bias: float

    def __post_init__(self) -> None:
        _integer(self.max_tokens, "max_tokens", minimum=1)
        _finite(self.bias, "bias")
        if self.bias <= 0:
            raise ConfigurationError("bias must be positive")


@dataclass(frozen=True, slots=True)
class SamplingOverrides:
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    min_p: float | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None:
            _finite(self.temperature, "temperature")
            if self.temperature < 0:
                raise ConfigurationError("temperature must be non-negative")
        if self.top_k is not None:
            _integer(self.top_k, "top_k", minimum=0)
        for name, value in (("top_p", self.top_p), ("min_p", self.min_p)):
            if value is None:
                continue
            _finite(value, name)
            if not 0 <= value <= 1:
                raise ConfigurationError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SatyrnConfig:
    dflash: DFlashMode = DFlashMode.AUTO
    drafter_path: Path | None = None
    draft_tokens: int = 0
    sampling: SamplingOverrides = SamplingOverrides()
    think_budget: ThinkBudgetConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dflash, DFlashMode):
            raise ConfigurationError("dflash must be a DFlashMode")
        _integer(self.draft_tokens, "draft_tokens", minimum=0)
        if self.drafter_path is not None and not isinstance(self.drafter_path, Path):
            raise TypeError("drafter_path must be a Path or None")
        if self.dflash is DFlashMode.ON and self.drafter_path is None:
            raise ConfigurationError("drafter_path is required when dflash is on")
