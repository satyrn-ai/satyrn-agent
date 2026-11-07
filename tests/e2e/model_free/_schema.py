"""Validate and convert scenario JSON into generated TypedDict values."""

import json
import math
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TypeIs, cast

from ds4py._json import is_string_key_mapping

from tests.e2e.scenarios._generated.scenario_types import (
    Expectation,
    Metrics,
    Native,
    NativeCall,
    Round,
    SamplingDefaults,
    SamplingOverrides,
    Scenario,
    ScenarioConfig,
)

SCENARIO_ROOT = Path(__file__).parents[1] / "scenarios"
_OPERATIONS = {"draft", "verify", "select", "commit", "eval"}


def _integer_list(value: object) -> TypeIs[list[int]]:
    return isinstance(value, list) and all(type(item) is int for item in value)


def _string_list(value: object) -> TypeIs[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _real(value: object) -> TypeIs[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _allowed(value: Mapping[str, object], names: set[str]) -> bool:
    return set(value) <= names


def _sampling_overrides(value: object) -> TypeIs[SamplingOverrides]:
    if not is_string_key_mapping(value) or not _allowed(value, {"temperature", "top_k", "top_p", "min_p"}):
        return False
    for name in ("temperature", "top_p", "min_p"):
        item = value.get(name)
        if item is not None and not _real(item):
            return False
    top_k = value.get("top_k")
    return top_k is None or type(top_k) is int


def _sampling_defaults(value: object) -> TypeIs[SamplingDefaults]:
    if not is_string_key_mapping(value) or set(value) != {"temperature", "top_k", "top_p", "min_p"}:
        return False
    return _sampling_overrides(value)


def _think_budget(value: object) -> bool:
    return (
        is_string_key_mapping(value)
        and set(value) == {"max_tokens", "bias"}
        and type(value["max_tokens"]) is int
        and value["max_tokens"] >= 1
        and _real(value["bias"])
        and value["bias"] > 0
    )


def _native_call(value: object) -> TypeIs[NativeCall]:
    if not is_string_key_mapping(value) or not _allowed(value, {"op", "tokens", "error", "side_effect"}):
        return False
    if value.get("op") not in _OPERATIONS:
        return False
    if "tokens" in value and not _integer_list(value["tokens"]):
        return False
    if (error := value.get("error")) is not None and not isinstance(error, str):
        return False
    return "side_effect" not in value or isinstance(value["side_effect"], bool)


def _native(value: object) -> TypeIs[Native]:  # noqa: PLR0911 - Each optional native field needs its own runtime proof.
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {"script", "calls", "stop_tokens", "has_dflash", "verify_rows", "missing", "sampling_defaults"},
    ):
        return False
    calls = value.get("calls")
    if not _integer_list(value.get("script")) or not isinstance(calls, list):
        return False
    if not all(_native_call(call) for call in calls):
        return False
    if "stop_tokens" in value and not _integer_list(value["stop_tokens"]):
        return False
    if "has_dflash" in value and not isinstance(value["has_dflash"], bool):
        return False
    if "verify_rows" in value and (type(value["verify_rows"]) is not int or value["verify_rows"] < 0):
        return False
    if "missing" in value and not _string_list(value["missing"]):
        return False
    return (defaults := value.get("sampling_defaults")) is None or _sampling_defaults(defaults)


def _config(value: object) -> TypeIs[ScenarioConfig]:
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {"dflash", "drafter_path", "draft_tokens", "sampling", "think_budget"},
    ):
        return False
    if value.get("dflash", "auto") not in {"auto", "on", "off"}:
        return False
    if (path := value.get("drafter_path", "drafter.gguf")) is not None and not isinstance(path, str):
        return False
    if "draft_tokens" in value and (type(value["draft_tokens"]) is not int or value["draft_tokens"] < 0):
        return False
    if "sampling" in value and not _sampling_overrides(value["sampling"]):
        return False
    return (budget := value.get("think_budget")) is None or _think_budget(budget)


def _metrics(value: object) -> TypeIs[Metrics]:
    names = {"committed_blocks", "drafts_offered", "drafts_accepted", "replacement_anchors", "discarded_tails"}
    return (
        is_string_key_mapping(value)
        and set(value) == names
        and all(type(item) is int and item >= 0 for item in value.values())
    )


def _metadata(value: object) -> bool:
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {"position", "think_tokens", "sampled_tokens", "parser_state"},
    ):
        return False
    position = value.get("position")
    if type(position) is not int or position < 0:
        return False
    think_tokens = value.get("think_tokens")
    if type(think_tokens) is not int or think_tokens < 0:
        return False
    if not _integer_list(value.get("sampled_tokens")):
        return False
    state = value.get("parser_state")
    return state is None or isinstance(state, str)


def _expectation(value: object) -> TypeIs[Expectation]:
    required = {"reason", "token_ids", "native_position", "rng", "metrics", "metadata", "event_types"}
    if not is_string_key_mapping(value) or set(value) != required:
        return False
    if not isinstance(value["reason"], str) or not _integer_list(value["token_ids"]):
        return False
    if type(value["native_position"]) is not int or value["native_position"] < 0:
        return False
    if type(value["rng"]) is not int or value["rng"] < 0:
        return False
    if not _metrics(value["metrics"]) or not isinstance(value["metadata"], list):
        return False
    return all(_metadata(item) for item in value["metadata"]) and _string_list(value["event_types"])


def _round(value: object) -> TypeIs[Round]:
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {"prompt", "max_tokens", "stop_sequences", "cancel_after_samples", "expect"},
    ):
        return False
    if not isinstance(value.get("prompt"), str):
        return False
    max_tokens = value.get("max_tokens")
    if type(max_tokens) is not int or max_tokens < 1:
        return False
    if "stop_sequences" in value and not _string_list(value["stop_sequences"]):
        return False
    if "cancel_after_samples" in value and (
        type(value["cancel_after_samples"]) is not int or value["cancel_after_samples"] < 0
    ):
        return False
    return _expectation(value.get("expect"))


def is_scenario(value: object) -> TypeIs[Mapping[str, object]]:
    """Prove the complete JSON scenario shape before typed conversion."""
    required = {"version", "id", "backend", "native", "config", "rounds", "expected_branches"}
    if (
        not is_string_key_mapping(value)
        or not _allowed(value, required | {"description"})
        or not required <= set(value)
    ):
        return False
    if value["version"] != 1 or not isinstance(value["id"], str) or not value["id"]:
        return False
    if "description" in value and not isinstance(value["description"], str):
        return False
    if value["backend"] != "metal" or not _native(value["native"]) or not _config(value["config"]):
        return False
    if (
        not isinstance(value["rounds"], list)
        or not value["rounds"]
        or not all(_round(item) for item in value["rounds"])
    ):
        return False
    return _string_list(value["expected_branches"]) and len(set(value["expected_branches"])) == len(
        value["expected_branches"]
    )


def _validation_error(value: object) -> str | None:  # noqa: PLR0911, PLR0912 - Prefer precise field-specific validation errors.
    if not is_string_key_mapping(value):
        return "scenario must be an object"
    if "id" not in value:
        return "id is required"
    if "rounds" in value:
        rounds = value["rounds"]
        if isinstance(rounds, list):
            for item in rounds:
                if is_string_key_mapping(item) and "max_tokens" in item and type(item["max_tokens"]) is not int:
                    return "max_tokens must be an integer"
    if "native" in value:
        native = value["native"]
        if is_string_key_mapping(native):
            calls = native.get("calls")
            if not isinstance(calls, list):
                return "native calls must be a list"
            for call in calls:
                if is_string_key_mapping(call):
                    if "op" in call and call["op"] not in _OPERATIONS:
                        return f"unknown op {call['op']}"
                    if "tokens" in call and not _integer_list(call["tokens"]):
                        return "tokens must be an integer list"
    return None if is_scenario(value) else "scenario does not match schema version 1"


def load_scenario(path: Path) -> Scenario:
    document: object = json.loads(path.read_text())
    if (error := _validation_error(document)) is not None:
        raise ValueError(f"{path}: {error}")
    if not is_scenario(document):
        raise AssertionError("validated scenario must retain its shape")
    converted = dict(document)
    native_value = document["native"]
    if not _native(native_value):
        raise AssertionError("validated native config must retain its shape")
    native = dict(native_value)
    if "stop_tokens" in native:
        assert _integer_list(native["stop_tokens"])
        native["stop_tokens"] = set(native["stop_tokens"])
    if "missing" in native:
        assert _string_list(native["missing"])
        native["missing"] = set(native["missing"])
    converted["native"] = native
    assert _string_list(document["expected_branches"])
    converted["expected_branches"] = set(document["expected_branches"])
    # The JSON shape and all nested fields were validated above; sets are the
    # only values that differ between JSON arrays and generated TypedDicts.
    return cast("Scenario", converted)


def load_scenarios(paths: Iterable[Path]) -> list[Scenario]:
    scenarios = [load_scenario(path) for path in paths]
    identifiers = [scenario["id"] for scenario in scenarios]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate scenario id")
    return scenarios


def iter_scenarios() -> Iterator[Scenario]:
    yield from load_scenarios(sorted(SCENARIO_ROOT.glob("*.json")))
