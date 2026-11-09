import threading
import time

import pytest
from ds4py import ThinkMode
from ds4py.engine.events import ReserveReached, ToolCalls
from ds4py.engine.logits import LogitsView
from ds4py.engine.prompt import PromptBuilder
from ds4py.engine.tool_prompt import ToolDefinition

from tests.conftest import (
    LiveSettings,
    MetadataRecorder,
    assert_alignment,
    configured_session,
    observe_round,
    prepare_chat,
)
from tests.e2e.corpus import corpus_cases, corpus_config, require_branches

pytestmark = pytest.mark.live


def test_max_tokens_and_natural_stop_alignment(live_settings: LiveSettings) -> None:
    case = corpus_cases()["limit-and-stop"]
    config = corpus_config(live_settings, case)
    reached: set[str] = set()

    with configured_session(live_settings, config, seed=case["seed"]) as (_, session):
        prepare_chat(session, case["prompt"])
        limited = observe_round(session, max_tokens=1, started=time.perf_counter())
        assert_alignment(session, limited)
        assert len(limited.token_ids) == 1
        assert limited.reason == "max_tokens"
        reached.update({"ordinary-anchor-eval", "max-tokens"})

    with configured_session(live_settings, config, seed=case["seed"]) as (_, session):
        prepare_chat(session, case["prompt"])
        stopped = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, stopped)
        if stopped.reason == "stop_token":
            reached.add("stop-token")

    assert stopped.reason == case["expected_reason"]
    require_branches(case, reached)


def test_tool_close_never_publishes_a_discarded_tail(live_settings: LiveSettings) -> None:
    case = corpus_cases()["tool-close"]
    config = corpus_config(live_settings, case)
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
    recorder = MetadataRecorder()

    with configured_session(live_settings, config, seed=case["seed"]) as (wrapper, session):
        session.start_chat(tools=[definition])
        session.append_user(case["prompt"])
        session.add_logits_hook(recorder)
        observation = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, observation)
        metrics = wrapper.dflash_metrics

    reached = set()
    if observation.reason == "tool_call_complete":
        assert any(isinstance(event, ToolCalls) for event in observation.events)
        reached.add("tool-close-terminal-verdict")
    if any(call.parser_state is not None for call in recorder.calls):
        reached.add("tentative-parser-state")
    if metrics is not None and metrics.discarded_tails > 0:
        reached.add("discarded-tail")
    assert observation.reason == case["expected_reason"]
    require_branches(case, reached)


def test_stop_sequence_commits_only_the_prefix(live_settings: LiveSettings) -> None:
    case = corpus_cases()["stop-sequence"]
    config = corpus_config(live_settings, case)

    with configured_session(
        live_settings,
        config,
        seed=case["seed"],
        think=case.get("think", ThinkMode.HIGH),
    ) as (_, session):
        prepare_chat(session, case["prompt"])
        observation = observe_round(
            session,
            max_tokens=case["max_tokens"],
            stop_sequences=[case["stop_sequence"].encode()],
            started=time.perf_counter(),
        )
        assert_alignment(session, observation)

    assert observation.reason == case["expected_reason"]
    require_branches(case, {"deferred-stop-publication", "accepted-prefix-commit"})


def test_context_reserve_commits_only_the_anchor(live_settings: LiveSettings) -> None:
    case = corpus_cases()["context-anchor"]
    config = corpus_config(live_settings, case)

    with configured_session(
        live_settings,
        config,
        seed=case["seed"],
        ctx=case.get("ctx", 100_000),
    ) as (wrapper, session):
        prompt_tokens = prepare_chat(session, case["prompt"])
        assistant_prefix = PromptBuilder(session.engine).assistant_prefix(session.transcript.tokens)
        assert prompt_tokens + len(assistant_prefix) == case["ctx"] - 1, (
            "ctx must leave one native row after the assistant prefix; "
            f"got {prompt_tokens} prompt tokens and {len(assistant_prefix)} prefix tokens"
        )
        observation = observe_round(
            session,
            max_tokens=case["max_tokens"],
            started=time.perf_counter(),
            resume_once_with_zero_reserve=True,
        )
        assert_alignment(session, observation)
        metrics = wrapper.dflash_metrics

    assert metrics is not None and metrics.committed_blocks == 1
    assert metrics.drafts_offered == 0
    assert observation.token_ids
    assert observation.reason == case["expected_reason"]
    require_branches(case, {"ordinary-anchor-eval", "accepted-prefix-commit"})


def test_parser_error_is_required(live_settings: LiveSettings) -> None:
    case = corpus_cases()["parser-error"]
    config = corpus_config(live_settings, case)
    definition = ToolDefinition("broken", "Exercise malformed tool syntax.", {"type": "object"})

    with configured_session(
        live_settings,
        config,
        seed=case["seed"],
        think=case.get("think", ThinkMode.HIGH),
    ) as (_, session):
        session.start_chat(tools=[definition])
        session.append_user(case["prompt"])
        observation = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, observation)

    reached = {"accepted-prefix-commit"} if observation.token_ids else set()
    if observation.reason == "parser_error":
        reached.add("parser-error")
    assert observation.reason == case["expected_reason"]
    require_branches(case, reached)


def test_context_reserve_is_required(live_settings: LiveSettings) -> None:
    case = corpus_cases()["context-reserve"]
    config = corpus_config(live_settings, case)
    prompt = f"{case['prompt']} " + "token transaction " * 1500

    with configured_session(live_settings, config, seed=case["seed"], ctx=case.get("ctx", 4096)) as (_, session):
        prompt_tokens = prepare_chat(session, prompt)
        # Greedy generation reaches EOS at native position 3435; 3400 forces the reserve first.
        assert prompt_tokens < case["ctx"], "the context-reserve prompt must fit before generation"
        observation = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, observation)

    reached = {"context-reserve"} if any(isinstance(event, ReserveReached) for event in observation.events) else set()
    if observation.token_ids:
        reached.add("accepted-prefix-commit")
    assert observation.reason == case["expected_reason"]
    require_branches(case, reached)


def test_cancellation_is_required_and_preserves_alignment(live_settings: LiveSettings) -> None:
    case = corpus_cases()["cancellation"]
    config = corpus_config(live_settings, case)

    cancel = threading.Event()
    sample_calls = 0
    fired_during_verify = False

    def cancel_during_verify(_: LogitsView) -> None:
        nonlocal sample_calls, fired_during_verify
        sample_calls += 1
        if sample_calls == 2:
            fired_during_verify = True
            cancel.set()

    with configured_session(live_settings, config, seed=case["seed"], cancel=cancel) as (_, session):
        prepare_chat(session, case["prompt"])
        session.add_logits_hook(cancel_during_verify)
        observation = observe_round(session, max_tokens=case["max_tokens"], started=time.perf_counter())
        assert_alignment(session, observation)

    reached = set()
    if observation.reason == "interrupted" and fired_during_verify:
        reached.add("cancellation-with-verify-open")
    if observation.token_ids:
        reached.add("accepted-prefix-commit")
    assert observation.reason == case["expected_reason"]
    require_branches(case, reached)
