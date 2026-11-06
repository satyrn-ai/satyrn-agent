import ctypes as C
from collections.abc import Callable
from typing import Any

import pytest
from ds4py.errors import MissingBinding

from satyrn_agent._native import CtypesDFlashNative, NativeSampling
from satyrn_agent.errors import DFlashError

DFLASH_NAMES = {
    "ds4_engine_has_dflash",
    "ds4_engine_verify_rows",
    "ds4_session_set_verify_mode",
    "ds4_session_dflash_draft",
    "ds4_session_verify",
    "ds4_session_verify_select",
    "ds4_session_verify_commit",
}


class FakeBindings:
    def __init__(self) -> None:
        self.functions: dict[str, Callable[..., Any]] = {}

    def bind(self, name: str) -> Callable[..., Any]:
        try:
            return self.functions[name]
        except KeyError:
            raise MissingBinding(name) from None


def test_missing_dflash_symbols_are_optional_and_named() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_engine_has_dflash"] = lambda raw: False

    native = CtypesDFlashNative(bindings)

    assert native.missing_dflash == tuple(sorted(DFLASH_NAMES - {"ds4_engine_has_dflash"}))
    assert native.sampling_defaults(1) is None


def test_engine_probes_convert_bool_and_counts() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_engine_has_dflash"] = lambda raw: 1
    bindings.functions["ds4_engine_verify_rows"] = lambda raw: 8
    native = CtypesDFlashNative(bindings)

    assert native.has_dflash(11) is True
    assert native.verify_rows(11) == 8


def test_negative_verify_rows_are_rejected() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_engine_verify_rows"] = lambda raw: -1
    native = CtypesDFlashNative(bindings)

    with pytest.raises(DFlashError, match="negative row count"):
        native.verify_rows(11)


def test_verify_mode_rejects_invalid_python_mode() -> None:
    native = CtypesDFlashNative(FakeBindings())

    with pytest.raises(ValueError, match="verify mode"):
        native.set_verify_mode(1, 2)


def test_verify_mode_converts_native_status() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_session_set_verify_mode"] = lambda raw, mode: 1
    native = CtypesDFlashNative(bindings)

    with pytest.raises(DFlashError, match=r"ds4_session_set_verify_mode.*status 1"):
        native.set_verify_mode(1, 1)


def test_draft_returns_plain_tokens_inside_requested_bound() -> None:
    bindings = FakeBindings()

    def draft(raw: int, anchor: int, maximum: int, out: Any, err: Any, errlen: int) -> int:
        assert maximum == 2
        out[0] = 42
        out[1] = 43
        return 2

    bindings.functions["ds4_session_dflash_draft"] = draft
    native = CtypesDFlashNative(bindings)

    result = native.draft(1, 40, 2)
    assert result == [42, 43]
    assert all(type(token) is int for token in result)


def test_zero_drafts_uses_a_valid_bounded_buffer() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_session_dflash_draft"] = lambda raw, anchor, maximum, out, err, errlen: 0
    native = CtypesDFlashNative(bindings)

    assert native.draft(1, 40, 0) == []


@pytest.mark.parametrize("count", [-2, 2])
def test_draft_rejects_invalid_native_counts(count: int) -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_session_dflash_draft"] = lambda raw, anchor, maximum, out, err, errlen: count
    native = CtypesDFlashNative(bindings)

    with pytest.raises(DFlashError, match="invalid draft count"):
        native.draft(1, 40, 1)


def test_draft_rejects_negative_maximum_before_native_call() -> None:
    native = CtypesDFlashNative(FakeBindings())

    with pytest.raises(ValueError, match="maximum"):
        native.draft(1, 40, -1)


def test_draft_minus_one_uses_native_error_message() -> None:
    bindings = FakeBindings()

    def draft(raw: int, anchor: int, maximum: int, out: Any, err: Any, errlen: int) -> int:
        C.memmove(err, b"draft failed", 12)
        return -1

    bindings.functions["ds4_session_dflash_draft"] = draft
    native = CtypesDFlashNative(bindings)

    with pytest.raises(DFlashError, match="draft failed"):
        native.draft(1, 40, 1)


def test_verify_marshals_draft_array() -> None:
    bindings = FakeBindings()
    seen: list[int] = []

    def verify(raw: int, anchor: int, drafts: Any, count: int, err: Any, errlen: int) -> int:
        seen.extend(drafts[:count])
        return 0

    bindings.functions["ds4_session_verify"] = verify
    native = CtypesDFlashNative(bindings)

    native.verify(1, 40, [41, 42])
    assert seen == [41, 42]
    native.verify(1, 40, [])


def test_select_and_commit_convert_status_and_native_message() -> None:
    bindings = FakeBindings()
    bindings.functions["ds4_session_verify_select"] = lambda raw, row: 0

    def commit(raw: int, rows: int, err: Any, errlen: int) -> int:
        C.memmove(err, b"commit exploded", 15)
        return 1

    bindings.functions["ds4_session_verify_commit"] = commit
    native = CtypesDFlashNative(bindings)

    native.select(1, 0)
    with pytest.raises(DFlashError, match="ds4_session_verify_commit: commit exploded") as caught:
        native.commit(1, 1)
    assert caught.value.operation == "ds4_session_verify_commit"


def test_commit_rejects_non_positive_rows_before_native_call() -> None:
    native = CtypesDFlashNative(FakeBindings())

    with pytest.raises(ValueError, match="rows"):
        native.commit(1, 0)


def test_sampling_defaults_return_immutable_python_values() -> None:
    bindings = FakeBindings()

    def defaults(raw: int, temperature: Any, top_k: Any, top_p: Any, min_p: Any) -> None:
        C.cast(temperature, C.POINTER(C.c_float))[0] = 0.6
        C.cast(top_k, C.POINTER(C.c_int))[0] = 20
        C.cast(top_p, C.POINTER(C.c_float))[0] = 0.95
        C.cast(min_p, C.POINTER(C.c_float))[0] = 0.0

    bindings.functions["ds4_engine_sampling_defaults"] = defaults
    native = CtypesDFlashNative(bindings)

    result = native.sampling_defaults(1)
    assert isinstance(result, NativeSampling)
    assert result.temperature == pytest.approx(0.6)
    assert result.top_k == 20
    assert result.top_p == pytest.approx(0.95)
    assert result.min_p == 0.0


def test_sampling_defaults_reject_invalid_native_values() -> None:
    bindings = FakeBindings()

    def defaults(raw: int, temperature: Any, top_k: Any, top_p: Any, min_p: Any) -> None:
        C.cast(temperature, C.POINTER(C.c_float))[0] = float("nan")

    bindings.functions["ds4_engine_sampling_defaults"] = defaults
    native = CtypesDFlashNative(bindings)

    with pytest.raises(DFlashError, match="invalid sampling defaults"):
        native.sampling_defaults(1)
