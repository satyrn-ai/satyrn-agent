"""Parse the external JSON-shaped config into Satyrn's frozen domain values."""

from __future__ import annotations

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


def _sampling(value: object) -> TypeIs[SamplingOverridesDocument]:
    if not _mapping(value):
        raise TypeError("sampling must be an object")
    if unknown := set(value) - _SAMPLING_FIELDS:
        raise ConfigurationError(f"unknown sampling fields: {', '.join(sorted(unknown))}")
    for name, item in value.items():
        if item is None:
            raise TypeError(f"{name} must not be null")
    return True


def _think_budget(value: object) -> TypeIs[ThinkBudgetDocument]:
    if not _mapping(value):
        raise TypeError("think_budget must be an object")
    if set(value) != {"max_tokens", "bias"}:
        raise ConfigurationError("think_budget requires max_tokens and bias")
    return True


def _document(value: object) -> ConfigDocument:
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
    if "sampling" in value:
        _sampling(value["sampling"])
    if (budget := value.get("think_budget")) is not None:
        _think_budget(budget)
    return cast("ConfigDocument", value)


def config_from_dict(data: object) -> SatyrnConfig:
    """Validate an external JSON-shaped mapping before creating domain values."""
    data = _document(data)
    path = data.get("drafter_path")
    budget = data.get("think_budget")
    return SatyrnConfig(
        dflash=DFlashMode(data.get("dflash", "auto")),
        drafter_path=Path(path) if path is not None else None,
        draft_tokens=data.get("draft_tokens", 0),
        sampling=SamplingOverrides(**data.get("sampling", {})),
        think_budget=None if budget is None else ThinkBudgetConfig(**budget),
    )
