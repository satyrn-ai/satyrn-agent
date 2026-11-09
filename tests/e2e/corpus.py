"""Typed loading and reached-branch checks for the real-engine corpus."""

import json
import math
from pathlib import Path
from typing import NotRequired, TypeIs, cast

import pytest
from ds4py._json import is_string_key_mapping
from typing_extensions import TypedDict

from satyrn_agent.config import ThinkBudgetConfig
from satyrn_agent.errors import ConfigurationError

CORPUS_PATH = Path(__file__).with_name("corpus.json")


class ThinkBudgetCase(TypedDict, closed=True):
    max_tokens: int
    bias: float


class CorpusCase(TypedDict, closed=True):
    name: str
    prompt: str
    seed: int
    temperature: float
    max_tokens: int
    branches: list[str]
    ctx: NotRequired[int]
    expected_reason: NotRequired[str]
    think: NotRequired[int]
    think_budget: NotRequired[ThinkBudgetCase]
    stop_sequence: NotRequired[str]


class Corpus(TypedDict, closed=True):
    format_version: int
    target: dict[str, object]
    drafter: dict[str, object]
    cases: list[CorpusCase]


def _string_list(value: object) -> TypeIs[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _think_budget(value: object) -> TypeIs[ThinkBudgetCase]:
    if not is_string_key_mapping(value):
        return False
    try:
        ThinkBudgetConfig(**cast("ThinkBudgetCase", value))
    except TypeError, ConfigurationError:
        return False
    return True


def is_corpus_case(value: object) -> TypeIs[CorpusCase]:  # noqa: PLR0911 - Each field needs an independent runtime proof.
    """Prove all required and optional runtime case fields before indexing."""
    if not is_string_key_mapping(value):
        return False
    if not isinstance(value.get("name"), str) or not isinstance(value.get("prompt"), str):
        return False
    if type(value.get("seed")) is not int:
        return False
    temperature = value.get("temperature")
    if not isinstance(temperature, int | float) or isinstance(temperature, bool) or not math.isfinite(temperature):
        return False
    max_tokens = value.get("max_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        return False
    if not _string_list(value.get("branches")):
        return False
    if (ctx := value.get("ctx")) is not None and (type(ctx) is not int or ctx <= 0):
        return False
    if (reason := value.get("expected_reason")) is not None and not isinstance(reason, str):
        return False
    if (think := value.get("think")) is not None and type(think) is not int:
        return False
    if (budget := value.get("think_budget")) is not None and not _think_budget(budget):
        return False
    return (stop := value.get("stop_sequence")) is None or isinstance(stop, str)


def is_corpus(value: object) -> TypeIs[Corpus]:
    if not is_string_key_mapping(value) or value.get("format_version") != 1:
        return False
    if not is_string_key_mapping(value.get("target")) or not is_string_key_mapping(value.get("drafter")):
        return False
    cases = value.get("cases")
    return isinstance(cases, list) and all(is_corpus_case(case) for case in cases)


def load_corpus() -> Corpus:
    data: object = json.loads(CORPUS_PATH.read_text())
    if not is_corpus(data):
        raise ValueError(f"invalid live corpus: {CORPUS_PATH}")
    return data


def corpus_cases() -> dict[str, CorpusCase]:
    return {case["name"]: case for case in load_corpus()["cases"]}


def require_branches(case: CorpusCase, reached: set[str]) -> None:
    missing = set(case["branches"]) - reached
    if missing:
        pytest.fail(f"live corpus case {case['name']} missed {sorted(missing)}; adjust the corpus before acceptance")
