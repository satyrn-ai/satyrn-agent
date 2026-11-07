"""Parse the external JSON-shaped config into Satyrn's frozen domain values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs, cast

from .config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from .errors import ConfigurationError

if TYPE_CHECKING:
    from ._generated.config import ConfigDocument, SamplingOverridesDocument, ThinkBudgetDocument

_CONFIG_FIELDS = {"dflash", "drafter_path", "draft_tokens", "sampling", "think_budget"}
_SAMPLING_FIELDS = {"temperature", "top_k", "top_p", "min_p"}
_DFLASH_MODES = {"auto", "on", "off"}


def _mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _real(value: object, name: str) -> TypeIs[float]:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError(f"{name} must be a real number")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ConfigurationError(f"{name} must be finite") from error
    if not finite:
        raise ConfigurationError(f"{name} must be finite")
    return True


def _integer(value: object, name: str, minimum: int) -> TypeIs[int]:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return True


def _sampling(value: object) -> TypeIs[SamplingOverridesDocument]:
    if not _mapping(value):
        raise TypeError("sampling must be an object")
    if unknown := set(value) - _SAMPLING_FIELDS:
        raise ConfigurationError(f"unknown sampling fields: {', '.join(sorted(unknown))}")
    for name in ("temperature", "top_p", "min_p"):
        if name not in value:
            continue
        item = value[name]
        _real(item, name)
        item = cast("float", item)
        if name == "temperature" and item < 0:
            raise ConfigurationError("temperature must be non-negative")
        if name != "temperature" and not 0 <= item <= 1:
            raise ConfigurationError(f"{name} must be between 0 and 1")
    if "top_k" in value:
        _integer(value["top_k"], "top_k", 0)
    return True


def _think_budget(value: object) -> TypeIs[ThinkBudgetDocument]:
    if not _mapping(value):
        raise TypeError("think_budget must be an object")
    if set(value) != {"max_tokens", "bias"}:
        raise ConfigurationError("think_budget requires max_tokens and bias")
    _integer(value["max_tokens"], "max_tokens", 1)
    bias = value["bias"]
    _real(bias, "bias")
    if cast("float", bias) <= 0:
        raise ConfigurationError("bias must be positive")
    return True


def _document(value: object) -> TypeIs[ConfigDocument]:
    if not _mapping(value):
        raise TypeError("config must be an object")
    if unknown := set(value) - _CONFIG_FIELDS:
        raise ConfigurationError(f"unknown config fields: {', '.join(sorted(unknown))}")
    if "dflash" in value:
        mode = value["dflash"]
        if not isinstance(mode, str):
            raise TypeError("dflash must be a string")
        if mode not in _DFLASH_MODES:
            raise ConfigurationError("dflash must be auto, on, or off")
    path = value.get("drafter_path")
    if path is not None and not isinstance(path, str):
        raise TypeError("drafter_path must be a string or None")
    if value.get("dflash") == "on" and (path is None or path == ""):
        raise ConfigurationError("drafter_path is required and must be non-empty when dflash is on")
    if "draft_tokens" in value:
        _integer(value["draft_tokens"], "draft_tokens", 0)
    if "sampling" in value:
        _sampling(value["sampling"])
    if (budget := value.get("think_budget")) is not None:
        _think_budget(budget)
    return True


def config_from_dict(data: object) -> SatyrnConfig:
    """Validate an external JSON-shaped mapping before creating domain values."""
    _document(data)
    data = cast("ConfigDocument", data)
    path = data.get("drafter_path")
    budget = data.get("think_budget")
    return SatyrnConfig(
        dflash=DFlashMode(data.get("dflash", "auto")),
        drafter_path=Path(path) if path is not None else None,
        draft_tokens=data.get("draft_tokens", 0),
        sampling=SamplingOverrides(**data.get("sampling", {})),
        think_budget=None if budget is None else ThinkBudgetConfig(**budget),
    )
