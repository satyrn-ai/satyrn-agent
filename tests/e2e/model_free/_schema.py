"""Validate scenario JSON with its schema and convert collection fields."""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from jsonschema.protocols import Validator
from referencing import Registry, Resource

from tests.e2e.scenarios._generated.scenario_types import Scenario

SCENARIO_ROOT = Path(__file__).parents[1] / "scenarios"
SCHEMA_PATH = Path(__file__).parents[1] / "schema" / "scenario.schema.json"
CONFIG_SCHEMA_PATH = Path(__file__).parents[3] / "schemas" / "satyrn-config.schema.json"


def _validator() -> Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    schema["$id"] = SCHEMA_PATH.as_uri()
    config = Resource.from_contents(json.loads(CONFIG_SCHEMA_PATH.read_text()))
    registry = Registry().with_resource(CONFIG_SCHEMA_PATH.as_uri(), config)
    return Draft202012Validator(schema, registry=registry)


def load_scenario(path: Path) -> Scenario:
    document: object = json.loads(path.read_text())
    if (error := best_match(_validator().iter_errors(document))) is not None:
        location = ".".join(str(item) for item in error.absolute_path) or "scenario"
        raise ValueError(f"{path}: scenario does not match schema version 1: {location}: {error.message}")
    validated = cast("Scenario", document)
    converted = dict(validated)
    native = validated["native"].copy()
    if "stop_tokens" in native:
        native["stop_tokens"] = set(native["stop_tokens"])
    if "missing" in native:
        native["missing"] = set(native["missing"])
    converted["native"] = native
    converted["expected_branches"] = set(validated["expected_branches"])
    return cast("Scenario", converted)


def load_scenarios(paths: Iterable[Path]) -> list[Scenario]:
    scenarios = [load_scenario(path) for path in paths]
    identifiers = [scenario["id"] for scenario in scenarios]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate scenario id")
    return scenarios


def iter_scenarios() -> Iterator[Scenario]:
    yield from load_scenarios(sorted(SCENARIO_ROOT.glob("*.json")))
