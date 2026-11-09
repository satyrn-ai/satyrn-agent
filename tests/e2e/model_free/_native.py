"""Deterministic optional bindings over ds4-py's real fake worker/session."""

from __future__ import annotations

import ctypes as C
import threading
from collections.abc import Sequence
from typing import Any, override

from ds4py._native.fake import FakeEngine, FakeNative, FakeSession
from ds4py._native.fake_chat import VOCAB_SIZE
from ds4py._native.protocol import EngineInfo

from satyrn_agent.errors import DFlashError
from tests.e2e.scenarios._generated.scenario_types import Native, NativeCall

_OPERATIONS = (
    "draft",
    "verify",
    "select",
    "commit",
    "eval",
    "sample",
    "mode",
    "has_dflash",
    "verify_rows",
    "sampling_defaults",
)


class ScenarioFakeNative(FakeNative):
    backend = "metal"

    def __init__(self, config: Native, backend: str = "metal") -> None:
        self.config = config
        self.backend = backend
        self.sessions: dict[int, FakeSession] = {}
        self.responses = {name: [call for call in config["calls"] if call["op"] == name] for name in _OPERATIONS}
        self.last_anchor = 0
        self.last_drafts: list[int] = []
        self.operations: list[str] = []
        self.call_log: list[dict[str, object]] = []
        self.draft_results: list[int] = []
        self.verify_open = False
        self.sample_count = 0
        self.current_token = 0
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
        call = self._response("sample", index)
        if call is not None and (message := call.get("error")) is not None:
            raise RuntimeError(message)
        self.current_token = script[index] if index < len(script) else 0
        return self.current_token

    def session(self, raw: int) -> FakeSession:
        return self.sessions[raw]

    def reset_script(self) -> None:
        self.sample_count = 0
        self.current_token = 0
        self.last_anchor = 0
        self.last_drafts = []
        self.responses = {name: [call for call in self.config["calls"] if call["op"] == name] for name in _OPERATIONS}

    def _response(self, operation: str, index: int | None = None) -> NativeCall | None:
        responses = self.responses[operation]
        if not responses:
            return None
        if index is not None and responses[0].get("index", 0) != index:
            return None
        return responses.pop(0)

    def _has_dflash(self, raw: int) -> bool:
        call = self._response("has_dflash")
        return bool(call["value"]) if call is not None and "value" in call else self.config.get("has_dflash", True)

    def _verify_rows(self, raw: int) -> int:
        call = self._response("verify_rows")
        return call["value"] if call is not None and "value" in call else self.config.get("verify_rows", 8)

    def _set_verify_mode(self, raw: int, mode: int) -> int:
        call = self._response("mode")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_set_verify_mode", message)
        return 0

    def _draft(self, raw: int, anchor: int, maximum: int, output: Any, error: Any, error_length: int) -> int:
        call = self._response("draft")
        if call is not None and (message := call.get("error")) is not None:
            encoded = message.encode()
            C.memmove(error, encoded, len(encoded) + 1)
            return -1
        self.operations.append("draft")
        tokens = [] if call is None else call.get("tokens", [])[:maximum]
        self.call_log.append({"op": "draft", "anchor": anchor, "maximum": maximum})
        self.draft_results.append(len(tokens))
        self.last_anchor = anchor
        self.last_drafts = list(tokens)
        for index, token in enumerate(tokens):
            output[index] = token
        return call["count"] if call is not None and "count" in call else len(tokens)

    def _verify(self, raw: int, anchor: int, drafts: Any, count: int, error: Any, error_length: int) -> int:
        self.operations.append("verify")
        call = self._response("verify")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify", message)
        self.last_anchor = anchor
        self.last_drafts = list(drafts[:count])
        self.call_log.append({"op": "verify", "anchor": anchor, "drafts": self.last_drafts.copy()})
        self.verify_open = True
        return call["status"] if call is not None and "status" in call else 0

    def _select(self, raw: int, row: int) -> int:
        self.operations.append("select")
        self.call_log.append({"op": "select", "row": row})
        if self.cancel_after_samples == -1 and self.cancel_event is not None:
            self.cancel_event.set()
        self.session(raw)._logits = None
        call = self._response("select")
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify_select", message)
        return call["status"] if call is not None and "status" in call else 0

    def _eval(self, token: int) -> None:
        self.operations.append("eval")
        self.call_log.append({"op": "eval", "token": token})
        call = self._response("eval")
        if call is not None and (message := call.get("error")) is not None:
            raise RuntimeError(message)

    def _commit(self, raw: int, rows: int, error: Any, error_length: int) -> int:
        self.operations.append("commit")
        self.call_log.append({"op": "commit", "rows": rows})
        if self.cancel_after_samples == -2 and self.cancel_event is not None:
            self.cancel_event.set()
        call = self._response("commit")
        session = self.session(raw)
        side_effect = call is not None and call.get("side_effect", False)
        if call is None or call.get("error") is None or side_effect:
            session._tokens.extend([self.last_anchor, *self.last_drafts][:rows])
            session._logits = None
        if call is not None and (message := call.get("error")) is not None:
            raise DFlashError("ds4_session_verify_commit", message)
        self.verify_open = False
        return call["status"] if call is not None and "status" in call else 0

    def _sampling_defaults(self, raw: int, temperature: Any, top_k: Any, top_p: Any, min_p: Any) -> None:
        defaults = self.config.get("sampling_defaults")
        call = self._response("sampling_defaults")
        if call is not None:
            raw_values = call.get("values", [1.0, 0.0, 1.0, 0.0])
            values = {
                "temperature": raw_values[0],
                "top_k": raw_values[1],
                "top_p": raw_values[2],
                "min_p": raw_values[3],
            }
            if call.get("nonfinite", False):
                values["temperature"] = float("nan")
        elif defaults is None:
            values = {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "min_p": 0.05}
        else:
            values = defaults
        C.cast(temperature, C.POINTER(C.c_float))[0] = values["temperature"]
        C.cast(top_k, C.POINTER(C.c_int))[0] = values["top_k"]
        C.cast(top_p, C.POINTER(C.c_float))[0] = values["top_p"]
        C.cast(min_p, C.POINTER(C.c_float))[0] = values["min_p"]


class ScenarioFakeSession(FakeSession):
    def __init__(self, engine: ScenarioFakeEngine, ctx: int) -> None:
        super().__init__(engine, ctx)
        self.scenario_native = engine.scenario_native

    @override
    def sample(self, temperature: float, top_k: int, top_p: float, min_p: float, rng: C.c_uint64) -> int:
        result = super().sample(temperature, top_k, top_p, min_p, rng)
        self.scenario_native.operations.append("row" if self.scenario_native.verify_open else "anchor")
        return self.scenario_native.current_token if self.scenario_native.current_token < 0 else result

    @override
    def eval(self, token: int) -> None:
        self.scenario_native._eval(token)
        super().eval(token)


class ScenarioFakeEngine(FakeEngine):
    def __init__(self, native: ScenarioFakeNative) -> None:
        super().__init__(native)
        self.scenario_native = native

    @override
    def create_session(self, ctx: int) -> FakeSession:
        session = ScenarioFakeSession(self, ctx)
        self._sessions.add(session)
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

    @override
    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]:
        if rendered and text == "</think>":
            return self.scenario_native.config.get("end_think_tokens", [258])
        return super().tokenize(text, rendered=rendered)
