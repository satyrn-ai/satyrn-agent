import threading
import time

import pytest
from ds4py.engine.events import ToolCalls
from ds4py.engine.tool_prompt import ToolDefinition

from satyrn_agent.config import SatyrnConfig
from tests.conftest import LiveSettings, assert_alignment, configured_session, observe_round, prepare_chat

pytestmark = pytest.mark.live


def test_max_tokens_and_natural_stop_alignment(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (_, session):
        prepare_chat(session, "Write a short answer and finish normally.")
        limited = observe_round(session, max_tokens=1, started=time.perf_counter())
        assert_alignment(session, limited)
        assert len(limited.token_ids) == 1
        assert limited.reason == "max_tokens"

    with configured_session(live_settings, config) as (_, session):
        prepare_chat(session, "Write a short answer and finish normally.")
        stopped = observe_round(session, max_tokens=96, started=time.perf_counter())
        assert_alignment(session, stopped)
        assert stopped.reason is not None


def test_tool_close_never_publishes_a_discarded_tail(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)
    definition = ToolDefinition(
        "get_weather",
        "Return weather for one city.",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )

    with configured_session(live_settings, config) as (_, session):
        session.start_chat(tools=[definition])
        session.append_user("Call the weather tool for Tokyo, then stop after the tool call.")
        observation = observe_round(session, max_tokens=64, started=time.perf_counter())
        assert_alignment(session, observation)

    assert observation.reason in {"tool_call_complete", "stop_token", "max_tokens"}
    if observation.reason == "tool_call_complete":
        assert any(isinstance(event, ToolCalls) for event in observation.events)


def test_stop_sequence_commits_only_the_prefix(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (_, session):
        prepare_chat(session, "Output exactly: alpha beta")
        observation = observe_round(
            session,
            max_tokens=48,
            stop_sequences=[b"beta"],
            started=time.perf_counter(),
        )
        assert_alignment(session, observation)

    assert observation.reason in {"stop_sequence", "stop_token", "max_tokens"}


def test_cancellation_preserves_alignment(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (_, session):
        prepare_chat(session, "Write a detailed explanation of token transactions.")
        timer = threading.Timer(0.05, session.cancel)
        timer.start()
        try:
            observation = observe_round(session, max_tokens=96, started=time.perf_counter())
        finally:
            timer.cancel()
        assert_alignment(session, observation)

    if observation.reason != "interrupted":
        pytest.skip(
            "the live cancellation timer fired outside a decode round; adjust the corpus timing for this machine"
        )
