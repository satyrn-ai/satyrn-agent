from typing import cast

import pytest
from ds4py._native.protocol import SessionHandle
from ds4py.engine.logits import LogitsView

from satyrn_agent.dflash import DFlashStep
from satyrn_agent.errors import DFlashError
from tests.abnormal._decode_helpers import DecodeFixture, FakeDFlashNative, make_decode


def run(fixture: DecodeFixture, native: FakeDFlashNative) -> None:
    DFlashStep(native).run(cast("SessionHandle", fixture.session), fixture.ctx)


@pytest.mark.parametrize("operation", ["draft", "verify"])
def test_unadvanced_setup_failure_discards_overlay_and_restores_rng(operation: str) -> None:
    poisoned: list[BaseException] = []
    fixture = make_decode([10], poisoned=poisoned)
    native = FakeDFlashNative(fixture.session, [11])
    error = DFlashError(operation, "injected")
    if operation == "draft":
        native.draft_error = error
    else:
        native.verify_error = error

    with pytest.raises(DFlashError, match="injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert fixture.transcript.tokens == ()
    assert fixture.events == []
    assert fixture.ctx.staging is False
    assert fixture.ctx.rng.value == 1
    assert poisoned == []


def test_select_failure_closes_verify_and_publishes_valid_prefix() -> None:
    poisoned: list[BaseException] = []
    fixture = make_decode([10], poisoned=poisoned)
    native = FakeDFlashNative(fixture.session, [11])
    error = DFlashError("select", "injected")
    native.select_error = error

    with pytest.raises(DFlashError, match="injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert fixture.transcript.tokens == (10,)
    assert fixture.session.position == 1
    assert native.verify_open is False
    assert poisoned == []


def test_sample_failure_closes_verify_and_reraises_original() -> None:
    fixture = make_decode([10])
    native = FakeDFlashNative(fixture.session, [11])
    error = RuntimeError("sample injected")
    fixture.session.sample_error = error
    fixture.session.sample_error_at = 2

    with pytest.raises(RuntimeError, match="sample injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert fixture.transcript.tokens == (10,)
    assert native.verify_open is False


def test_hook_failure_commits_prefix_then_reraises_without_poison() -> None:
    poisoned: list[BaseException] = []
    error = RuntimeError("hook injected")
    calls = 0

    def hook(view: LogitsView) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error

    fixture = make_decode([10], logits_hooks=[hook], poisoned=poisoned)
    native = FakeDFlashNative(fixture.session, [11])

    with pytest.raises(RuntimeError, match="hook injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert fixture.transcript.tokens == (10,)
    assert fixture.session.position == 1
    assert native.verify_open is False
    assert poisoned == []


def test_commit_side_effect_then_failure_poisons_without_publication() -> None:
    poisoned: list[BaseException] = []
    fixture = make_decode([10, 11], max_tokens=2, poisoned=poisoned)
    native = FakeDFlashNative(fixture.session, [11])
    error = DFlashError("commit", "injected")
    native.commit_error = error
    native.commit_side_effect = True

    with pytest.raises(DFlashError, match="injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert poisoned == [error]
    assert fixture.session.position == 2
    assert fixture.transcript.tokens == ()
    assert fixture.events == []


def test_cleanup_failure_chains_hook_error_and_poisons_cleanup() -> None:
    poisoned: list[BaseException] = []
    hook_error = RuntimeError("hook injected")
    cleanup_error = DFlashError("cleanup", "injected")
    calls = 0

    def hook(view: LogitsView) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise hook_error

    fixture = make_decode([10], logits_hooks=[hook], poisoned=poisoned)
    native = FakeDFlashNative(fixture.session, [11])
    native.commit_error = cleanup_error

    with pytest.raises(DFlashError, match="cleanup") as caught:
        run(fixture, native)

    assert caught.value is cleanup_error
    assert caught.value.__context__ is hook_error
    assert poisoned == [cleanup_error]
    assert fixture.transcript.tokens == ()
    assert fixture.events == []


def test_eval_failure_poisons_and_does_not_publish() -> None:
    poisoned: list[BaseException] = []
    fixture = make_decode([10], max_tokens=1, poisoned=poisoned)
    native = FakeDFlashNative(fixture.session)
    error = RuntimeError("eval injected")
    fixture.session.eval_error = error

    with pytest.raises(RuntimeError, match="eval injected") as caught:
        run(fixture, native)

    assert caught.value is error
    assert poisoned == [error]
    assert fixture.transcript.tokens == ()
    assert fixture.events == []
