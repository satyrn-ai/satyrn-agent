import time

import pytest

from satyrn_agent.config import SatyrnConfig, ThinkBudgetConfig
from tests.conftest import LiveSettings, assert_alignment, configured_session, observe_round, prepare_chat

pytestmark = pytest.mark.live


def test_native_qwen_sampling_defaults(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (_, session):
        defaults = session.engine.sampling_defaults
        assert defaults.temperature == pytest.approx(0.6)
        assert defaults.top_k == 20
        assert defaults.top_p == pytest.approx(0.95)
        assert defaults.min_p == 0.0


def test_soft_think_budget_changes_real_decode_without_injection(live_settings: LiveSettings) -> None:
    baseline_config = SatyrnConfig(drafter_path=live_settings.drafter)
    budget_config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        think_budget=ThinkBudgetConfig(max_tokens=2, bias=5.0),
    )
    prompt = "Think briefly about why native commit must precede token publication."

    with configured_session(live_settings, baseline_config, seed=11) as (_, session):
        prepare_chat(session, prompt)
        baseline = observe_round(session, max_tokens=64, started=time.perf_counter())
        assert_alignment(session, baseline)

    with configured_session(live_settings, budget_config, seed=11) as (_, session):
        prepare_chat(session, prompt)
        budgeted = observe_round(session, max_tokens=64, started=time.perf_counter())
        assert_alignment(session, budgeted)

    assert budgeted.token_ids != baseline.token_ids
