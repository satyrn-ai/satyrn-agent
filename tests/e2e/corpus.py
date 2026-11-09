"""Typed loading and reached-branch checks for the real-engine corpus."""

import json
import math
from pathlib import Path
from typing import NotRequired, Protocol, TypeIs, cast

import pytest
from ds4py._json import is_string_key_mapping
from ds4py.engine.sampling import SamplingPolicy
from typing_extensions import TypedDict

from satyrn_agent.config import SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.dflash import DFlashMetrics
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
    draft_tokens: NotRequired[int]
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


def _optional_int(value: object, minimum: int) -> bool:
    return value is None or (type(value) is int and value >= minimum)


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
    if not _optional_int(value.get("ctx"), 1) or not _optional_int(value.get("draft_tokens"), 1):
        return False
    if (reason := value.get("expected_reason")) is not None and not isinstance(reason, str):
        return False
    if not _optional_int(value.get("think"), 0):
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


class DrafterSettings(Protocol):
    @property
    def drafter(self) -> Path: ...


def corpus_config(settings: DrafterSettings, case: CorpusCase) -> SatyrnConfig:
    return SatyrnConfig(
        drafter_path=settings.drafter,
        draft_tokens=case.get("draft_tokens", 0),
        sampling=SamplingOverrides(temperature=case["temperature"]),
    )


def corpus_sampling(case: CorpusCase) -> SamplingPolicy:
    defaults = load_corpus()["target"]["sampling_defaults"]
    if not is_string_key_mapping(defaults):
        raise ValueError("invalid native sampling defaults in live corpus")
    top_k = defaults["top_k"]
    top_p = defaults["top_p"]
    min_p = defaults["min_p"]
    if type(top_k) is not int or not isinstance(top_p, int | float) or not isinstance(min_p, int | float):
        raise ValueError("invalid native sampling defaults in live corpus")
    greedy = case["temperature"] == 0
    return SamplingPolicy(
        temperature=case["temperature"],
        top_k=0 if greedy else top_k,
        top_p=1.0 if greedy else float(top_p),
        min_p=float(min_p),
        seed=case["seed"],
    )


def metric_branches(metrics: DFlashMetrics) -> set[str]:
    reached = set()
    if metrics.committed_blocks > 0:
        reached.update({"anchor", "native-commit-publication"})
    if metrics.drafts_accepted > 0:
        reached.add("matching-draft")
    if metrics.drafts_offered > 0 and metrics.drafts_accepted == metrics.drafts_offered:
        reached.add("full-acceptance")
    if 0 < metrics.drafts_accepted < metrics.drafts_offered:
        reached.add("partial-acceptance")
    if metrics.replacement_anchors > 0:
        reached.add("mismatch-replacement")
    return reached


def require_branches(case: CorpusCase, reached: set[str]) -> None:
    missing = set(case["branches"]) - reached
    if missing:
        pytest.fail(f"live corpus case {case['name']} missed {sorted(missing)}; adjust the corpus before acceptance")
