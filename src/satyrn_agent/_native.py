"""The only Satyrn module that touches ctypes and raw native handles."""

from __future__ import annotations

import ctypes as C
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

from ds4py.errors import MissingBinding

from .errors import DFlashError

_ERROR_BYTES = 256
_DFLASH_NAMES = (
    "ds4_engine_has_dflash",
    "ds4_engine_verify_rows",
    "ds4_session_set_verify_mode",
    "ds4_session_dflash_draft",
    "ds4_session_verify",
    "ds4_session_verify_select",
    "ds4_session_verify_commit",
)


class BindingSource(Protocol):
    def bind(self, name: str) -> Callable[..., Any]: ...


@dataclass(frozen=True, slots=True)
class NativeSampling:
    temperature: float
    top_k: int
    top_p: float
    min_p: float


class DFlashNative(Protocol):
    @property
    def missing_dflash(self) -> tuple[str, ...]: ...

    def has_dflash(self, engine_raw: int) -> bool: ...
    def verify_rows(self, engine_raw: int) -> int: ...
    def set_verify_mode(self, session_raw: int, mode: int) -> None: ...
    def draft(self, session_raw: int, anchor: int, maximum: int) -> list[int]: ...
    def verify(self, session_raw: int, anchor: int, drafts: Sequence[int]) -> None: ...
    def select(self, session_raw: int, row: int) -> None: ...
    def commit(self, session_raw: int, rows: int) -> None: ...
    def sampling_defaults(self, engine_raw: int) -> NativeSampling | None: ...


class CtypesDFlashNative:
    """Convert optional ds4 extension calls to checked Python values."""

    def __init__(self, native: BindingSource) -> None:
        self._native = native
        self._functions: dict[str, Callable[..., Any]] = {}

    def _bind(self, name: str) -> Callable[..., Any]:
        if name not in self._functions:
            self._functions[name] = self._native.bind(name)
        return self._functions[name]

    @property
    def missing_dflash(self) -> tuple[str, ...]:
        missing = []
        for name in _DFLASH_NAMES:
            try:
                self._bind(name)
            except MissingBinding:
                missing.append(name)
        return tuple(sorted(missing))

    def has_dflash(self, engine_raw: int) -> bool:
        return bool(self._bind("ds4_engine_has_dflash")(engine_raw))

    def verify_rows(self, engine_raw: int) -> int:
        rows = int(self._bind("ds4_engine_verify_rows")(engine_raw))
        if rows < 0:
            raise DFlashError("ds4_engine_verify_rows", f"negative row count {rows}")
        return rows

    def set_verify_mode(self, session_raw: int, mode: int) -> None:
        status = self._bind("ds4_session_set_verify_mode")(session_raw, mode)
        _check_status("ds4_session_set_verify_mode", status)

    def draft(self, session_raw: int, anchor: int, maximum: int) -> list[int]:
        output = (C.c_int * max(maximum, 1))()
        error = C.create_string_buffer(_ERROR_BYTES)
        count = int(
            self._bind("ds4_session_dflash_draft")(
                session_raw,
                anchor,
                maximum,
                output,
                error,
                len(error),
            )
        )
        if count == -1:
            _raise_native("ds4_session_dflash_draft", error)
        if not 0 <= count <= maximum:
            raise DFlashError("ds4_session_dflash_draft", f"invalid draft count {count} for maximum {maximum}")
        return [int(token) for token in output[:count]]

    def verify(self, session_raw: int, anchor: int, drafts: Sequence[int]) -> None:
        values = tuple(drafts)
        draft_buffer = (C.c_int * max(len(values), 1))(*values)
        error = C.create_string_buffer(_ERROR_BYTES)
        status = self._bind("ds4_session_verify")(
            session_raw,
            anchor,
            draft_buffer,
            len(values),
            error,
            len(error),
        )
        _check_status("ds4_session_verify", status, error)

    def select(self, session_raw: int, row: int) -> None:
        status = self._bind("ds4_session_verify_select")(session_raw, row)
        _check_status("ds4_session_verify_select", status)

    def commit(self, session_raw: int, rows: int) -> None:
        error = C.create_string_buffer(_ERROR_BYTES)
        status = self._bind("ds4_session_verify_commit")(session_raw, rows, error, len(error))
        _check_status("ds4_session_verify_commit", status, error)

    def sampling_defaults(self, engine_raw: int) -> NativeSampling | None:
        try:
            function = self._bind("ds4_engine_sampling_defaults")
        except MissingBinding:
            return None
        temperature, top_p, min_p = C.c_float(), C.c_float(), C.c_float()
        top_k = C.c_int()
        function(engine_raw, C.byref(temperature), C.byref(top_k), C.byref(top_p), C.byref(min_p))
        values = (temperature.value, top_p.value, min_p.value)
        if (
            top_k.value < 0
            or not all(math.isfinite(value) for value in values)
            or temperature.value < 0
            or not 0 <= top_p.value <= 1
            or not 0 <= min_p.value <= 1
        ):
            raise DFlashError("ds4_engine_sampling_defaults", "invalid sampling defaults")
        return NativeSampling(float(temperature.value), int(top_k.value), float(top_p.value), float(min_p.value))


def _message(error: C.Array[C.c_char]) -> str:
    return bytes(error.value).decode("utf-8", "replace") or "native operation failed"


def _raise_native(operation: str, error: C.Array[C.c_char]) -> None:
    raise DFlashError(operation, _message(error))


def _check_status(operation: str, status: int, error: C.Array[C.c_char] | None = None) -> None:
    if status == 0:
        return
    message = _message(error) if error is not None else f"native status {status}"
    raise DFlashError(operation, message)
