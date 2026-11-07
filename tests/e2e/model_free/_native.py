"""Deterministic optional bindings over ds4-py's real fake worker/session."""

import ctypes as C
import threading
from collections.abc import Sequence
from typing import Any, override

from ds4py._native.fake import FakeEngine, FakeNative, FakeSession
from ds4py._native.fake_chat import VOCAB_SIZE
from ds4py._native.protocol import EngineInfo

from satyrn_agent.errors import DFlashError
from tests.e2e.scenarios._generated.scenario_types import Native, NativeCall, SamplingDefaults


class ScenarioFakeNative(FakeNative):
    backend = "metal"

    def __init__(self, config: Native) -> None:
        self.config = config
        self.sessions: dict[int, FakeSession] = {}
        self.responses = {name: [call for call in config["calls"] if call["op"] == name] for name in _OPERATIONS}
        self.last_anchor = 0
        self.last_drafts: list[int] = []
        self.operations: list[str] = []
        self.sample_count = 0
        self.cancel_after_samples: int | None = None
        self.cancel_event: threading.Event | None = None
        super().__init__(
            script=self._next_token,
            absent=self.config.get("missing", set()),
            info=EngineInfo("scenario", 0, "qwen", False, False, True, False, 0, 7, VOCAB_SIZE),
        )
        self.bindings.update(
            {
                "ds4_engine_has_dflash": self._has_dflash,
                "ds4_engine_verify_rows": self._verify_rows,
                "ds4_session_set_verify_mode": self._set_verify_mode,
                "ds4_session_dflash_draft": self._draft,
                "ds4_session_verify": self._verify,
                "ds4_session_verify_select": self._select,
                "ds4_session_verify_commit": self._commit,
                "ds4_engine_sampling_defaults": self._sampling_defaults,
            }
        )

    @override
    def open_engine(self, config: object) -> ScenarioFakeEngine:
        return ScenarioFakeEngine(self)

    def _next_token(self, prompt: Sequence[int], generated: Sequence[int]) -> int:
        script = self.config["script"]
        index = self.sample_count
        self.sample_count += 1
        if self.cancel_after_samples == index and self.cancel_event is not None:
            self.cancel_event.set()
        return script[index] if index < len(script) else 0

    def session(self, raw: int) -> FakeSession:
        return self.sessions[raw]

    def _response(self, operation: str) -> NativeCall | None:
        responses = self.responses[operation]
        return responses.pop(0) if responses else None

    def _has_dflash(self, raw: int) -> bool:
        return self.config.get("has_dflash", True)

    def _verify_rows(self, raw: int) -> int:
        return self.config.get("verify_rows", 8)

    def _set_verify_mode(self, raw: int, mode: int) -> int:
        return 0

    def _draft(self, raw: int, anchor: int, maximum: int, output: Any, error: Any, error_length: int) -> int:
        call = self._response("draft")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_dflash_draft", message)
        self.operations.append("draft")
        tokens = [] if call is None else call.get("tokens", [])[:maximum]
        self.last_anchor = anchor
        self.last_drafts = list(tokens)
        for index, token in enumerate(tokens):
            output[index] = token
        return len(tokens)

    def _verify(self, raw: int, anchor: int, drafts: Any, count: int, error: Any, error_length: int) -> int:
        self.operations.append("verify")
        call = self._response("verify")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify", message)
        self.last_anchor = anchor
        self.last_drafts = list(drafts[:count])
        return 0

    def _select(self, raw: int, row: int) -> int:
        self.operations.append("select")
        self.session(raw)._logits = None
        call = self._response("select")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify_select", message)
        return 0

    def _commit(self, raw: int, rows: int, error: Any, error_length: int) -> int:
        self.operations.append("commit")
        call = self._response("commit")
        session = self.session(raw)
        side_effect = call is not None and call.get("side_effect", False)
        if call is None or call.get("error") is None or side_effect:
            session._tokens.extend([self.last_anchor, *self.last_drafts][:rows])
            session._logits = None
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify_commit", message)
        return 0

    def _sampling_defaults(self, raw: int, temperature: Any, top_k: Any, top_p: Any, min_p: Any) -> None:
        defaults = self.config.get("sampling_defaults")
        if defaults is None:
            values: SamplingDefaults = {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "min_p": 0.05}
        else:
            values = defaults
        C.cast(temperature, C.POINTER(C.c_float))[0] = values["temperature"]
        C.cast(top_k, C.POINTER(C.c_int))[0] = values["top_k"]
        C.cast(top_p, C.POINTER(C.c_float))[0] = values["top_p"]
        C.cast(min_p, C.POINTER(C.c_float))[0] = values["min_p"]


class ScenarioFakeEngine(FakeEngine):
    def __init__(self, native: ScenarioFakeNative) -> None:
        super().__init__(native)
        self.scenario_native = native

    @override
    def create_session(self, ctx: int) -> FakeSession:
        session = super().create_session(ctx)
        self.scenario_native.sessions[session.raw] = session
        return session

    @override
    def is_stop(self, token: int) -> bool:
        return token in self.scenario_native.config.get("stop_tokens", set()) or super().is_stop(token)

    @override
    def is_stop_for_think_mode(self, token: int, mode: int) -> bool:
        return token in self.scenario_native.config.get("stop_tokens", set()) or super().is_stop_for_think_mode(
            token, mode
        )


_OPERATIONS = ("draft", "verify", "select", "commit", "eval")
