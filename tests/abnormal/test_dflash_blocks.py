from typing import cast

import pytest
from ds4py._native.protocol import SessionHandle
from ds4py.engine.events import Event, Token

from satyrn_agent.dflash import DFlashStep
from tests.abnormal._decode_helpers import FakeDFlashNative, make_decode


def test_anchor_stop_has_no_native_movement_or_staged_event() -> None:
    fixture = make_decode([99], stops={99})
    native = FakeDFlashNative(fixture.session, [10])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.ctx.reason == "stop_token"
    assert fixture.transcript.tokens == ()
    assert fixture.events == []
    assert fixture.session.position == 0
    assert native.calls == []


def test_terminal_anchor_uses_one_eval_without_drafting() -> None:
    fixture = make_decode([10], max_tokens=1)
    native = FakeDFlashNative(fixture.session, [11])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.session.evaluated == [10]
    assert fixture.transcript.tokens == (10,)
    assert native.calls == []
    assert step.metrics.committed_blocks == 1
    assert step.metrics.drafts_offered == 0


def test_zero_drafts_still_verifies_anchor_and_carries_bonus() -> None:
    fixture = make_decode([10, 11], max_tokens=2)
    native = FakeDFlashNative(fixture.session, [])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert [call for call in native.calls if call[0] == "verify"] == [("verify", 10)]
    assert [call for call in native.calls if call[0] == "commit"] == [("commit", 1)]
    assert fixture.session.evaluated == [11]
    assert fixture.transcript.tokens == (10, 11)
    assert step.metrics.committed_blocks == 2


def test_full_acceptance_carries_bonus_without_duplicate_sampling() -> None:
    fixture = make_decode([10, 11, 12], max_tokens=3)
    native = FakeDFlashNative(fixture.session, [11])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.session.sampled == [10, 11, 12]
    assert fixture.transcript.tokens == (10, 11, 12)
    assert step.metrics.replacement_anchors == 0
    assert step.metrics.drafts_accepted == 1


@pytest.mark.parametrize(
    ("drafts", "samples", "expected"),
    [
        ([11], [10, 99], (10, 99)),
        ([11, 12], [10, 11, 99], (10, 11, 99)),
    ],
)
def test_mismatch_keeps_only_accepted_prefix_and_replacement(
    drafts: list[int], samples: list[int], expected: tuple[int, ...]
) -> None:
    fixture = make_decode(samples, max_tokens=len(expected))
    native = FakeDFlashNative(fixture.session, drafts)
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert fixture.transcript.tokens == expected
    assert fixture.session.position == len(expected)
    assert step.metrics.replacement_anchors == 1


def test_every_token_event_follows_its_native_commit() -> None:
    fixture = make_decode([10, 11], max_tokens=2)
    native = FakeDFlashNative(fixture.session, [11])
    step = DFlashStep(native)
    published: list[tuple[Event, int]] = []
    fixture.ctx._emit = lambda event: published.append((event, fixture.session.position))

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert [(type(event), position) for event, position in published] == [(Token, 2), (Token, 2)]
    assert [event.id for event, _ in published if isinstance(event, Token)] == [10, 11]


def test_stop_row_commits_prefix_once_before_finishing() -> None:
    fixture = make_decode([10, 99], stops={99}, max_tokens=3)
    native = FakeDFlashNative(fixture.session, [11])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert [call for call in native.calls if call[0] == "commit"] == [("commit", 1)]
    assert fixture.transcript.tokens == (10,)
    assert fixture.events[0] == Token(10, b"<10>")
    assert fixture.ctx.reason == "stop_token"
    assert native.verify_open is False
