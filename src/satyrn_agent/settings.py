"""Resolve project and downstream CLI settings before native open."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

from .config_io import config_from_dict
from .errors import ConfigurationError

if TYPE_CHECKING:
    from ds4py.agent_composition import EngineOpenOptions

    from .config import SatyrnConfig


def _mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


class SettingsDocument(dict[str, object]):
    """A JSON-shaped mapping that retains its diagnostic source path."""

    def __init__(self, values: Mapping[str, object], source: Path) -> None:
        super().__init__(values)
        self.source = source


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return number


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dflash", choices=("auto", "on", "off"))
    parser.add_argument("--drafter", type=Path)
    parser.add_argument("--draft-tokens", type=_non_negative_int)
    parser.add_argument("--think-budget", type=_positive_int)
    parser.add_argument("--think-bias", type=float)
    parser.add_argument("--no-think-budget", action="store_true")


def _project_values(project_dir: Path) -> tuple[dict[str, object], Path]:
    source = project_dir / "pyproject.toml"
    try:
        with source.open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError:
        return {}, source
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"{source}: {error}") from error
    tool = document.get("tool", {})
    if not _mapping(tool):
        raise ConfigurationError(f"{source}: tool must be a table")
    values = tool.get("satyrn", {})
    if not _mapping(values):
        raise ConfigurationError(f"{source}: tool.satyrn must be a table")
    return dict(values), source


def _resolve_path(value: object, project_dir: Path) -> object:
    if not isinstance(value, str):
        return value
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else project_dir / path)


def resolve_settings(args: argparse.Namespace, project_dir: Path) -> SettingsDocument:
    """Merge only Satyrn-owned CLI values over the invocation project file."""
    project_dir = project_dir.resolve()
    values, source = _project_values(project_dir)
    if "drafter_path" in values:
        values["drafter_path"] = _resolve_path(values["drafter_path"], project_dir)
    if args.dflash is not None:
        values["dflash"] = args.dflash
    if args.drafter is not None:
        values["drafter_path"] = _resolve_path(str(args.drafter), project_dir)
    if args.draft_tokens is not None:
        values["draft_tokens"] = args.draft_tokens

    if args.no_think_budget and (args.think_budget is not None or args.think_bias is not None):
        raise ConfigurationError("--no-think-budget conflicts with positive think-budget flags")
    project_budget = values.get("think_budget")
    if project_budget is not None and not _mapping(project_budget):
        raise TypeError(f"{source}: think_budget must be an object")
    if project_budget is not None and set(project_budget) != {"max_tokens", "bias"}:
        raise ConfigurationError(f"{source}: think_budget requires max_tokens and bias")
    if args.no_think_budget:
        values.pop("think_budget", None)
    elif args.think_budget is not None:
        bias = project_budget["bias"] if _mapping(project_budget) else 2.0
        values["think_budget"] = {"max_tokens": args.think_budget, "bias": bias}
    if args.think_bias is not None:
        budget = values.get("think_budget")
        if not _mapping(budget):
            raise ConfigurationError("--think-bias requires an effective think budget")
        values["think_budget"] = {**budget, "bias": args.think_bias}
    return SettingsDocument(values, source)


def resolve_config(options: EngineOpenOptions, extension_config: object) -> SatyrnConfig:
    """Add typed generic sampling values and validate the final merged document."""
    if not _mapping(extension_config):
        raise TypeError("Satyrn extension config must be a mapping")
    values = dict(extension_config)
    raw_sampling = values.get("sampling", {})
    if _mapping(raw_sampling):
        sampling = dict(raw_sampling)
        for name in ("temperature", "top_k", "top_p", "min_p"):
            value = getattr(options, name)
            if value is not None:
                sampling[name] = value
        values["sampling"] = sampling
    try:
        return config_from_dict(values)
    except (ConfigurationError, TypeError) as error:
        source = extension_config.source if isinstance(extension_config, SettingsDocument) else None
        if source is None:
            raise
        raise type(error)(f"{source}: {error}") from error
