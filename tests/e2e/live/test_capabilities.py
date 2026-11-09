import time

import pytest

from satyrn_agent.config import SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from tests.conftest import (
    LiveSettings,
    MetadataRecorder,
    assert_alignment,
    configured_session,
    observe_round,
    prepare_chat,
)
from tests.e2e.corpus import corpus_cases, load_corpus, require_branches

pytestmark = pytest.mark.live


def test_native_qwen_sampling_defaults(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (_, session):
        defaults = session.engine.sampling_defaults
        actual = {
            "temperature": defaults.temperature,
            "top_k": defaults.top_k,
            "top_p": defaults.top_p,
            "min_p": defaults.min_p,
        }
        assert actual == load_corpus()["target"]["sampling_defaults"]


def test_soft_think_budget_changes_real_decode_without_injection(live_settings: LiveSettings) -> None:
    case = corpus_cases()["think-budget"]
    baseline_config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        sampling=SamplingOverrides(temperature=case["temperature"]),
    )
    budget_config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        sampling=SamplingOverrides(temperature=case["temperature"]),
        think_budget=ThinkBudgetConfig(**case["think_budget"]),
    )
    recorder = MetadataRecorder()

    with configured_session(live_settings, baseline_config, seed=case["seed"]) as (_, session):
        prepare_chat(session, case["prompt"])
        baseline = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, baseline)

    with configured_session(live_settings, budget_config, seed=case["seed"]) as (_, session):
        prepare_chat(session, case["prompt"])
        session.add_logits_hook(recorder)
        budgeted = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, budgeted)

    assert budgeted.token_ids != baseline.token_ids
    assert len(recorder.calls) >= len(budgeted.token_ids)
    require_branches(case, {"think-budget-every-row", "soft-bias-without-injection"})
