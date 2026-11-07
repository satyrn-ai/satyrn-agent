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
_OPERATIONS = {
    "draft",
    "verify",
    "select",
    "commit",
    "eval",
    "sample",
    "mode",
    "has_dflash",
    "verify_rows",
    "sampling_defaults",
}


def _integer_list(value: object) -> TypeIs[list[int]]:
    return isinstance(value, list) and all(type(item) is int for item in value)


def _string_list(value: object) -> TypeIs[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _real_list(value: object) -> TypeIs[list[float]]:
    return isinstance(value, list) and all(_real(item) for item in value)


def _real(value: object) -> TypeIs[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _allowed(value: Mapping[str, object], names: set[str]) -> bool:
    return set(value) <= names


def _sampling_overrides(value: object) -> TypeIs[SamplingOverrides]:
    if not is_string_key_mapping(value) or not _allowed(value, {"temperature", "top_k", "top_p", "min_p"}):
        return False
    for name in ("temperature", "top_p", "min_p"):
        if name not in value:
            continue
        item = value[name]
        if not _real(item):
            return False
        if (name == "temperature" and item < 0) or (name != "temperature" and not 0 <= item <= 1):
            return False
    if "top_k" not in value:
        return True
    top_k = value["top_k"]
    return type(top_k) is int and top_k >= 0


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


def _native_call(value: object) -> TypeIs[NativeCall]:  # noqa: PLR0911 - Validate each native-call field independently.
    fields = {"op", "tokens", "index", "error", "side_effect", "value", "values", "nonfinite", "status", "count"}
    if not is_string_key_mapping(value) or not _allowed(value, fields):
        return False
    operation = value.get("op")
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        return False
    if "tokens" in value and not _integer_list(value["tokens"]):
        return False
    if "index" in value and (type(value["index"]) is not int or value["index"] < 0):
        return False
    for name in ("value", "status", "count"):
        if name in value and type(value[name]) is not int:
            return False
    if "values" in value and not _real_list(value["values"]):
        return False
    if "nonfinite" in value and not isinstance(value["nonfinite"], bool):
        return False
    if (error := value.get("error")) is not None and not isinstance(error, str):
        return False
    return "side_effect" not in value or isinstance(value["side_effect"], bool)


def _native(value: object) -> TypeIs[Native]:  # noqa: PLR0911 - Each optional native field needs its own runtime proof.
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {
            "script",
            "calls",
            "stop_tokens",
            "has_dflash",
            "verify_rows",
            "missing",
            "sampling_defaults",
            "end_think_tokens",
        },
    ):
        return False
    calls = value.get("calls")
    if not _integer_list(value.get("script")) or not isinstance(calls, list):
        return False
    if not all(_native_call(call) for call in calls):
        return False
    if "stop_tokens" in value:
        stop_tokens = value["stop_tokens"]
        if not _integer_list(stop_tokens) or len(set(stop_tokens)) != len(stop_tokens):
            return False
    if "has_dflash" in value and not isinstance(value["has_dflash"], bool):
        return False
    if "verify_rows" in value and (type(value["verify_rows"]) is not int or value["verify_rows"] < 0):
        return False
    if "missing" in value:
        missing = value["missing"]
        if not _string_list(missing) or len(set(missing)) != len(missing):
            return False
    if "end_think_tokens" in value and not _integer_list(value["end_think_tokens"]):
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
    if not is_string_key_mapping(value) or not names <= set(value) or not _allowed(value, names | {"acceptance_rate"}):
        return False
    for name in names:
        item = value[name]
        if not isinstance(item, int) or isinstance(item, bool):
            return False
        if item < 0:
            return False
    return (rate := value.get("acceptance_rate")) is None or (_real(rate) and 0 <= rate <= 1)


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


def _event_expectation(value: object) -> bool:
    return (
        is_string_key_mapping(value)
        and set(value) == {"type", "payload"}
        and isinstance(value["type"], str)
        and is_string_key_mapping(value["payload"])
    )


def _native_call_expectation(value: object) -> bool:
    names = {"op", "anchor", "drafts", "maximum", "row", "rows", "token"}
    if not is_string_key_mapping(value) or not _allowed(value, names) or not isinstance(value.get("op"), str):
        return False
    if "drafts" in value and not _integer_list(value["drafts"]):
        return False
    for name in ("anchor", "maximum", "row", "rows", "token"):
        if name not in value:
            continue
        item = value[name]
        if type(item) is not int or item < 0:
            return False
    return True


def _expectation(value: object) -> TypeIs[Expectation]:  # noqa: PLR0911 - Validate each expected field independently.
    required = {"reason", "token_ids", "native_position", "rng", "metrics", "metadata", "event_types"}
    optional = {"sampling_defaults", "transcript", "events", "native_calls", "token_positions"}
    if not is_string_key_mapping(value) or not required <= set(value) or not _allowed(value, required | optional):
        return False
    if (reason := value["reason"]) is not None and not isinstance(reason, str):
        return False
    if not _integer_list(value["token_ids"]):
        return False
    if type(value["native_position"]) is not int or value["native_position"] < 0:
        return False
    if type(value["rng"]) is not int or value["rng"] < 0:
        return False
    if not _metrics(value["metrics"]) or not isinstance(value["metadata"], list):
        return False
    if "sampling_defaults" in value and not _sampling_defaults(value["sampling_defaults"]):
        return False
    for name in ("transcript", "token_positions"):
        if name in value and not _integer_list(value[name]):
            return False
    if "events" in value and (
        not isinstance(value["events"], list) or not all(_event_expectation(item) for item in value["events"])
    ):
        return False
    if "native_calls" in value and (
        not isinstance(value["native_calls"], list)
        or not all(_native_call_expectation(item) for item in value["native_calls"])
    ):
        return False
    return all(_metadata(item) for item in value["metadata"]) and _string_list(value["event_types"])


def _tool(value: object) -> bool:
    return (
        is_string_key_mapping(value)
        and set(value) == {"name", "description", "parameters"}
        and isinstance(value["name"], str)
        and isinstance(value["description"], str)
        and is_string_key_mapping(value["parameters"])
    )


def _round(value: object) -> TypeIs[Round]:  # noqa: PLR0911 - Validate each round field independently.
    if not is_string_key_mapping(value) or not _allowed(
        value,
        {
            "prompt",
            "mode",
            "max_tokens",
            "stop_sequences",
            "cancel_after_samples",
            "hook_error_at",
            "finish_at",
            "finish_reason",
            "cancel_after_accept",
            "tools",
            "expect",
        },
    ):
        return False
    if not isinstance(value.get("prompt"), str) or value.get("mode", "raw") not in {"raw", "chat"}:
        return False
    max_tokens = value.get("max_tokens")
    if type(max_tokens) is not int or max_tokens < 1:
        return False
    if "stop_sequences" in value and not _string_list(value["stop_sequences"]):
        return False
    if "cancel_after_samples" in value and (
        type(value["cancel_after_samples"]) is not int or value["cancel_after_samples"] < -3
    ):
        return False
    if "hook_error_at" in value and (type(value["hook_error_at"]) is not int or value["hook_error_at"] < 1):
        return False
    if "finish_at" in value and (type(value["finish_at"]) is not int or value["finish_at"] < 0):
        return False
    if "finish_reason" in value and not isinstance(value["finish_reason"], str):
        return False
    if "cancel_after_accept" in value and (
        type(value["cancel_after_accept"]) is not int or value["cancel_after_accept"] < 1
    ):
        return False
    if "tools" in value and (not isinstance(value["tools"], list) or not all(_tool(item) for item in value["tools"])):
        return False
    return _expectation(value.get("expect"))


def is_scenario(value: object) -> TypeIs[Mapping[str, object]]:  # noqa: PLR0911 - Each root field has an independent proof.
    """Prove the complete JSON scenario shape before typed conversion."""
    required = {"version", "id", "backend", "native", "config", "rounds", "expected_branches"}
    if (
        not is_string_key_mapping(value)
        or not _allowed(value, required | {"description", "snapshot_parity", "think", "raw_config"})
        or not required <= set(value)
    ):
        return False
    if type(value["version"]) is not int or value["version"] != 1:
        return False
    if not isinstance(value["id"], str) or not value["id"]:
        return False
    if "description" in value and not isinstance(value["description"], str):
        return False
    if "snapshot_parity" in value and not isinstance(value["snapshot_parity"], bool):
        return False
    if "think" in value and (type(value["think"]) is not int or value["think"] < 0):
        return False
    if "raw_config" in value and not is_string_key_mapping(value["raw_config"]):
        return False
    if value["backend"] not in {"metal", "cpu"} or not _native(value["native"]) or not _config(value["config"]):
        return False
    if (
        not isinstance(value["rounds"], list)
        or not value["rounds"]
        or not all(_round(item) for item in value["rounds"])
    ):
        return False
    branches = value["expected_branches"]
    return bool(branches) and _string_list(branches) and len(set(branches)) == len(branches)


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
                    if "op" in call:
                        operation = call["op"]
                        if not isinstance(operation, str) or operation not in _OPERATIONS:
                            return f"unknown op {operation}"
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
