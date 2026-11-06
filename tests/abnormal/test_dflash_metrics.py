from typing import cast

import pytest
from _decode_helpers import FakeDFlashNative, make_decode
from ds4py._native.protocol import SessionHandle

from satyrn_agent.dflash import DFlashMetrics, DFlashStep
from satyrn_agent.errors import DFlashError


def test_empty_metrics_have_zero_acceptance_rate() -> None:
    fixture = make_decode([])
    native = FakeDFlashNative(fixture.session)
    step = DFlashStep(native)

    assert step.metrics == DFlashMetrics()
    assert step.metrics.acceptance_rate == 0.0
    assert step.hooks_every_sample is True


def test_metrics_advance_after_full_draft_commit() -> None:
    fixture = make_decode([10, 11], max_tokens=2)
    native = FakeDFlashNative(fixture.session, [11])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert step.metrics == DFlashMetrics(
        committed_blocks=1,
        drafts_offered=1,
        drafts_accepted=1,
        replacement_anchors=0,
        discarded_tails=0,
    )
    assert step.metrics.acceptance_rate == 1.0
    assert fixture.transcript.tokens == (10, 11)
    assert fixture.session.position == 2


def test_failed_commit_does_not_advance_metrics_or_publish() -> None:
    fixture = make_decode([10, 11], max_tokens=2)
    native = FakeDFlashNative(fixture.session, [11])
    native.commit_error = DFlashError("commit", "injected")
    step = DFlashStep(native)

    with pytest.raises(DFlashError, match="injected"):
        step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert step.metrics == DFlashMetrics()
    assert fixture.transcript.tokens == ()
    assert fixture.events == []


def test_mismatch_records_replacement_and_discarded_tail() -> None:
    fixture = make_decode([10, 11, 99], max_tokens=3)
    native = FakeDFlashNative(fixture.session, [11, 12])
    step = DFlashStep(native)

    step.run(cast("SessionHandle", fixture.session), fixture.ctx)

    assert step.metrics == DFlashMetrics(
        committed_blocks=2,
        drafts_offered=2,
        drafts_accepted=1,
        replacement_anchors=1,
        discarded_tails=1,
    )
    assert step.metrics.acceptance_rate == 0.5
    assert fixture.transcript.tokens == (10, 11, 99)
    assert fixture.session.position == 3
