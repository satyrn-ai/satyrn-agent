import time

import pytest

from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig
from tests.conftest import LiveSettings, assert_alignment, configured_session, observe_round, prepare_chat

pytestmark = pytest.mark.live


def drafter_config(settings: LiveSettings, mode: DFlashMode) -> SatyrnConfig:
    return SatyrnConfig(dflash=mode, drafter_path=settings.drafter)


def test_auto_on_off_and_consecutive_public_rounds(live_settings: LiveSettings) -> None:
    with configured_session(live_settings, drafter_config(live_settings, DFlashMode.AUTO)) as (auto, session):
        assert auto.dflash_metrics is not None
        for prompt in ("Say hello briefly.", "Say goodbye briefly."):
            prompt_tokens = prepare_chat(session, prompt)
            assert prompt_tokens > 0
            observation = observe_round(session, max_tokens=16, started=time.perf_counter())
            assert_alignment(session, observation)

    with configured_session(live_settings, drafter_config(live_settings, DFlashMode.ON)) as (on, session):
        assert on.dflash_metrics is not None
        prepare_chat(session, "Give a one-line status.")
        observation = observe_round(session, max_tokens=16, started=time.perf_counter())
        assert_alignment(session, observation)

    with configured_session(live_settings, drafter_config(live_settings, DFlashMode.OFF)) as (off, session):
        assert off.dflash_metrics is None
        prepare_chat(session, "Give a one-line status.")
        observation = observe_round(session, max_tokens=16, started=time.perf_counter())
        assert_alignment(session, observation)


def test_explicit_zero_sampling_overrides_survive_real_open(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        sampling=SamplingOverrides(temperature=0.0, top_k=0, top_p=0.0, min_p=0.0),
    )

    with configured_session(live_settings, config) as (_, session):
        defaults = session.engine.sampling_defaults
        assert defaults.temperature == 0.0
        assert defaults.top_k == 0
        assert defaults.top_p == 0.0
        assert defaults.min_p == 0.0
