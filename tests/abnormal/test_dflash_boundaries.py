from collections.abc import Callable
from typing import cast

import pytest
from _decode_helpers import DecodeFixture, FakeDFlashNative, make_decode
from ds4py._native.protocol import SessionHandle
from ds4py.engine.decode import Verdict

from satyrn_agent.dflash import DFlashStep


def cancel_at(true_calls: set[int]) -> Callable[[], bool]:
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls in true_calls

    return cancelled


def run(fixture: DecodeFixture, native: FakeDFlashNative) -> DFlashStep:
    step = DFlashStep(native)
    step.run(cast("SessionHandle", fixture.session), fixture.ctx)
    return step


def test_stop_row_publishes_prefix_and_retains_stop_sample_rng() -> None:
    fixture = make_decode([10, 99], stops={99}, max_tokens=4)
    native = FakeDFlashNative(fixture.session, [11])

    run(fixture, native)

    assert fixture.transcript.tokens == (10,)
    assert fixture.ctx.reason == "stop_token"
    assert fixture.ctx.rng.value == 3


def test_max_tokens_prevents_any_later_row_sample() -> None:
    fixture = make_decode([10, 11, 12], max_tokens=2)
    native = FakeDFlashNative(fixture.session, [11, 12])

    run(fixture, native)

    assert fixture.session.sampled == [10, 11]
    assert fixture.transcript.tokens == (10, 11)
    assert fixture.ctx.reason == "max_tokens"


def test_cancellation_after_anchor_uses_eval_and_never_opens_verify() -> None:
    fixture = make_decode([10], cancelled=cancel_at({2}))
    native = FakeDFlashNative(fixture.session, [11])

    step = run(fixture, native)

    assert fixture.session.evaluated == [10]
    assert fixture.transcript.tokens == (10,)
    assert fixture.ctx.reason == "interrupted"
    assert native.calls == []
    assert step.metrics.committed_blocks == 1


def test_cancellation_before_first_row_commits_anchor_prefix() -> None:
    fixture = make_decode([10], cancelled=cancel_at({3}))
    native = FakeDFlashNative(fixture.session, [11])

    run(fixture, native)

    assert [call for call in native.calls if call[0] == "commit"] == [("commit", 1)]
    assert fixture.transcript.tokens == (10,)
    assert fixture.session.sampled == [10]
    assert fixture.ctx.reason == "interrupted"
    assert native.verify_open is False


def test_cancellation_before_later_row_keeps_accepted_draft() -> None:
    fixture = make_decode([10, 11], cancelled=cancel_at({5}))
    native = FakeDFlashNative(fixture.session, [11, 12])

    run(fixture, native)

    assert [call for call in native.calls if call[0] == "commit"] == [("commit", 2)]
    assert fixture.transcript.tokens == (10, 11)
    assert fixture.session.sampled == [10, 11]
    assert fixture.ctx.reason == "interrupted"


@pytest.mark.parametrize(
    ("drafts", "samples", "expected_tokens", "expected_rng", "cancel_call"),
    [
        ([11], [10, 99], (10,), 2, 4),
        ([11], [10, 11, 12], (10, 11), 3, 6),
    ],
)
def test_cancellation_after_unused_candidate_restores_its_rng(
    drafts: list[int], samples: list[int], expected_tokens: tuple[int, ...], expected_rng: int, cancel_call: int
) -> None:
    fixture = make_decode(samples, cancelled=cancel_at({cancel_call}))
    native = FakeDFlashNative(fixture.session, drafts)

    run(fixture, native)

    assert fixture.transcript.tokens == expected_tokens
    assert fixture.ctx.rng.value == expected_rng
    assert fixture.ctx.reason == "interrupted"


def test_staged_terminal_verdict_prevents_later_row_sampling() -> None:
    fixture = make_decode([10, 11, 12], max_tokens=4)
    native = FakeDFlashNative(fixture.session, [11, 12])
    original_stage = fixture.ctx.stage

    def finish_on_draft(token: int, verdict: Verdict | None = None) -> Verdict:
        result = original_stage(token, verdict)
        if token == 11:
            fixture.ctx.finish("tool_call_complete")
        return result

    fixture.ctx.__dict__["stage"] = finish_on_draft

    run(fixture, native)

    assert fixture.session.sampled == [10, 11]
    assert fixture.transcript.tokens == (10, 11)
    assert fixture.ctx.reason == "tool_call_complete"
    assert native.verify_open is False
