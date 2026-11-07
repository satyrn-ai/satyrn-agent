from typing import cast

import pytest
from ds4py._native.protocol import SessionHandle
from ds4py.engine.decode import Verdict
from ds4py.engine.logits import LogitsView

from satyrn_agent.dflash import DFlashStep
from tests.abnormal._decode_helpers import FakeDFlashNative, make_decode


def test_step_rejects_invalid_constructor_bounds() -> None:
    fixture = make_decode([])
    native = FakeDFlashNative(fixture.session)
    with pytest.raises(ValueError, match="draft_tokens"):
        DFlashStep(native, draft_tokens=-1)
    with pytest.raises(ValueError, match="verify_rows"):
        DFlashStep(native, verify_rows=0)


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
    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.session.sampled == [10, 11]
    assert fixture.transcript.tokens == (10, 11)
    assert fixture.ctx.reason == "tool_call_complete"
    assert native.verify_open is False


def test_terminal_reason_during_mismatch_restores_pending_rng() -> None:
    calls = 0

    def hook(view: LogitsView) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            fixture.ctx.finish("budget")

    fixture = make_decode([10, 99], logits_hooks=[hook])
    native = FakeDFlashNative(fixture.session, [11])

    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.transcript.tokens == (10,)
    assert fixture.ctx.rng.value == 2
    assert fixture.ctx.reason == "budget"


def test_cancellation_before_later_row_keeps_accepted_draft() -> None:
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls == 5

    fixture = make_decode([10, 11], cancelled=cancelled)
    native = FakeDFlashNative(fixture.session, [11, 12])

    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.transcript.tokens == (10, 11)
    assert fixture.session.sampled == [10, 11]
    assert fixture.ctx.reason == "interrupted"


def test_pre_finalized_context_is_a_noop() -> None:
    fixture = make_decode([])
    native = FakeDFlashNative(fixture.session)
    fixture.ctx.finish("done")

    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.ctx.reason == "done"
    assert native.calls == []


def test_cancellation_before_first_anchor_finishes_without_pending() -> None:
    fixture = make_decode([], cancelled=lambda: True)
    native = FakeDFlashNative(fixture.session)

    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.ctx.reason == "interrupted"
    assert fixture.transcript.tokens == ()
    assert native.calls == []
