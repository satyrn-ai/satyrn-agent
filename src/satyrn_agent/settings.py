"""Resolve project and downstream CLI settings before native open."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import validate_integer, validate_think_bias
from .config_io import config_from_dict, is_mapping, validate_think_budget_document
from .errors import ConfigurationError, MissingDrafterPath

if TYPE_CHECKING:
    from ds4py.agent_composition import EngineOpenOptions

    from .config import SatyrnConfig


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """A JSON-shaped mapping and the project file used for diagnostics."""

    values: dict[str, object]
    source: Path


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
    parser.add_argument("--drafter")
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
    if not is_mapping(tool):
        raise ConfigurationError(f"{source}: tool must be a table")
    values = tool.get("satyrn", {})
    if not is_mapping(values):
        raise ConfigurationError(f"{source}: tool.satyrn must be a table")
    return dict(values), source


def _resolve_path(value: object, project_dir: Path) -> object:
    if not isinstance(value, str):
        return value
    if not value.strip():
        return ""
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else project_dir / path)


def _merge_think_budget(args: argparse.Namespace, values: dict[str, object], source: Path) -> None:
    if args.no_think_budget and (args.think_budget is not None or args.think_bias is not None):
        raise ConfigurationError("--no-think-budget conflicts with positive think-budget flags")
    if args.think_budget is not None:
        validate_integer(args.think_budget, "max_tokens", minimum=1)
    project_budget = values.get("think_budget")
    if project_budget is not None:
        try:
            validate_think_budget_document(project_budget)
        except (ConfigurationError, TypeError) as error:
            raise ConfigurationError(f"{source}: {error}") from error
    if args.no_think_budget:
        values.pop("think_budget", None)
    elif args.think_budget is not None:
        bias = project_budget["bias"] if is_mapping(project_budget) else 2.0
        values["think_budget"] = {"max_tokens": args.think_budget, "bias": bias}
    if args.think_bias is not None:
        budget = values.get("think_budget")
        if not is_mapping(budget):
            raise ConfigurationError("--think-bias requires an effective think budget")
        validate_think_bias(args.think_bias)
        values["think_budget"] = {**budget, "bias": args.think_bias}


def resolve_settings(args: argparse.Namespace, project_dir: Path) -> ResolvedSettings:
    """Merge and validate Satyrn-owned project and CLI values."""
    project_dir = project_dir.resolve()
    project_values, source = _project_values(project_dir)
    values = dict(project_values)
    if "drafter_path" in values:
        values["drafter_path"] = _resolve_path(values["drafter_path"], project_dir)
    if args.dflash is not None:
        values["dflash"] = args.dflash
    if args.drafter is not None:
        values["drafter_path"] = _resolve_path(args.drafter, project_dir)
    if args.draft_tokens is not None:
        values["draft_tokens"] = args.draft_tokens

    _merge_think_budget(args, values, source)
    satyrn_values = dict(values)
    satyrn_values.pop("sampling", None)
    try:
        config_from_dict(satyrn_values)
    except (ConfigurationError, TypeError) as error:
        missing_cli_drafter = (
            isinstance(error, MissingDrafterPath)
            and (project_values.get("dflash") != "on" or args.dflash not in {None, "on"})
            and "drafter_path" not in project_values
            and (
                (args.drafter is not None and not args.drafter.strip())
                or (args.dflash == "on" and args.drafter is None)
            )
        )
        if missing_cli_drafter:
            raise
        raise ConfigurationError(f"{source}: {error}") from error
    return ResolvedSettings(values, source)


def resolve_config(options: EngineOpenOptions, extension_config: object) -> SatyrnConfig:
    """Add typed generic sampling values and validate the final merged document."""
    if isinstance(extension_config, ResolvedSettings):
        values = dict(extension_config.values)
        source: Path | None = extension_config.source
    elif is_mapping(extension_config):
        values = dict(extension_config)
        source = None
    else:
        raise TypeError("Satyrn extension config must be a mapping")
    generic_values: dict[str, object] = {}
    for name in ("temperature", "top_k", "top_p", "min_p"):
        value = getattr(options, name)
        if value is not None:
            generic_values[name] = value
    generic = config_from_dict({"sampling": generic_values}).sampling
    raw_sampling = values.get("sampling", {})
    if is_mapping(raw_sampling):
        sampling = dict(raw_sampling)
        for name in ("temperature", "top_k", "top_p", "min_p"):
            value = getattr(generic, name)
            if value is not None:
                sampling[name] = value
        values["sampling"] = sampling
    try:
        return config_from_dict(values)
    except (ConfigurationError, TypeError) as error:
        if source is None:
            raise
        raise ConfigurationError(f"{source}: {error}") from error
