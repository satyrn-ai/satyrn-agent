import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import cast

import ds4py
import pytest
from ds4py import Engine, EngineError, Session
from ds4py._native.protocol import Native
from ds4py.engine.decode import DecodeStep, PlainStep
from ds4py.engine.logits import LogitsView
from ds4py.engine.sampling import SamplingPolicy
from ds4py.engine.worker import Handles

import satyrn_agent.engine as engine_module
from satyrn_agent._native import NativeSampling
from satyrn_agent.config import DFlashMode, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.dflash import DFlashMetrics, DFlashStep
from satyrn_agent.engine import _select_step
from satyrn_agent.errors import DFlashError, DFlashUnavailable


class FakeNative:
    backend = "metal"
    restore_enabled = False


class PolicyNative:
    def __init__(self) -> None:
        self.missing: tuple[str, ...] = ()
        self.available = True
        self.rows = 8
        self.mode: int | None = None
        self.mode_error: Exception | None = None
        self.defaults = NativeSampling(0.6, 20, 0.95, 0.0)

    @property
    def missing_dflash(self) -> tuple[str, ...]:
        return self.missing

    def has_dflash(self, engine_raw: int) -> bool:
        return self.available

    def verify_rows(self, engine_raw: int) -> int:
        return self.rows

    def set_verify_mode(self, session_raw: int, mode: int) -> None:
        if self.mode_error is not None:
            raise self.mode_error
        self.mode = mode

    def draft(self, session_raw: int, anchor: int, maximum: int) -> list[int]:
        return []

    def verify(self, session_raw: int, anchor: int, drafts: Sequence[int]) -> None:
        pass

    def select(self, session_raw: int, row: int) -> None:
        pass

    def commit(self, session_raw: int, rows: int) -> None:
        pass

    def sampling_defaults(self, engine_raw: int) -> NativeSampling | None:
        return self.defaults


class FakeSession:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self.step: DecodeStep | None = None
        self.hooks: list[Callable[[LogitsView], None]] = []
        self.closed = 0

    def on_worker[T](self, fn: Callable[[Handles], T]) -> Future[T]:
        future: Future[T] = Future()
        future.set_result(fn(Handles(10, 20)))
        return future

    def set_decode_step(self, step: DecodeStep | None) -> None:
        self.step = step

    def add_logits_hook(self, hook: Callable[[LogitsView], None]) -> None:
        self.hooks.append(hook)

    def close(self) -> None:
        self.closed += 1


class FakeEngine:
    def __init__(self, native: Native) -> None:
        self.native = native
        self.sampling_defaults = SamplingPolicy(temperature=1.0, top_k=0, top_p=1.0, min_p=0.05, seed=11)
        self.fake_session = FakeSession(self)
        self.session_calls = 0
        self.close_calls = 0

    def session(self) -> Session:
        self.session_calls += 1
        if self.session_calls > 1:
            raise EngineError("one session per engine")
        return cast("Session", self.fake_session)

    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]:
        return [42]

    def close(self) -> None:
        self.close_calls += 1
        self.fake_session.close()


def test_off_avoids_capability_probes() -> None:
    native = PolicyNative()
    native.missing = ("ds4_engine_has_dflash",)

    step = _select_step(native, SatyrnConfig(dflash=DFlashMode.OFF), 10, 20, "metal")

    assert isinstance(step, PlainStep)


def test_auto_without_drafter_uses_plain_step() -> None:
    step = _select_step(PolicyNative(), SatyrnConfig(), 10, 20, "metal")

    assert isinstance(step, PlainStep)


def test_auto_with_missing_binding_uses_plain_step() -> None:
    native = PolicyNative()
    native.missing = ("ds4_session_verify",)
    config = SatyrnConfig(drafter_path=Path("draft.gguf"))

    step = _select_step(native, config, 10, 20, "metal")

    assert isinstance(step, PlainStep)


def test_auto_with_non_metal_backend_uses_plain_step() -> None:
    config = SatyrnConfig(drafter_path=Path("draft.gguf"))

    step = _select_step(PolicyNative(), config, 10, 20, "cpu")

    assert isinstance(step, PlainStep)


def test_auto_without_loaded_drafter_uses_plain_step() -> None:
    native = PolicyNative()
    native.available = False
    config = SatyrnConfig(drafter_path=Path("draft.gguf"))

    step = _select_step(native, config, 10, 20, "metal")

    assert isinstance(step, PlainStep)


def test_auto_with_zero_rows_uses_plain_step() -> None:
    native = PolicyNative()
    native.rows = 0
    config = SatyrnConfig(drafter_path=Path("draft.gguf"))

    step = _select_step(native, config, 10, 20, "metal")

    assert isinstance(step, PlainStep)


def test_on_without_drafter_is_rejected_by_policy_dispatch() -> None:
    config = SatyrnConfig()
    object.__setattr__(config, "dflash", DFlashMode.ON)

    with pytest.raises(DFlashUnavailable, match="configured drafter"):
        _select_step(PolicyNative(), config, 10, 20, "metal")


def test_on_missing_binding_names_requirement() -> None:
    native = PolicyNative()
    native.missing = ("ds4_session_verify",)
    config = SatyrnConfig(dflash=DFlashMode.ON, drafter_path=Path("draft.gguf"))

    with pytest.raises(DFlashUnavailable, match="ds4_session_verify"):
        _select_step(native, config, 10, 20, "metal")


def test_on_checks_backend_drafter_and_rows() -> None:
    config = SatyrnConfig(dflash=DFlashMode.ON, drafter_path=Path("draft.gguf"))
    with pytest.raises(DFlashUnavailable, match="Metal"):
        _select_step(PolicyNative(), config, 10, 20, "cpu")

    native = PolicyNative()
    native.available = False
    with pytest.raises(DFlashUnavailable, match="drafter"):
        _select_step(native, config, 10, 20, "metal")

    native = PolicyNative()
    native.rows = 0
    with pytest.raises(DFlashUnavailable, match="verify row"):
        _select_step(native, config, 10, 20, "metal")


def test_auto_does_not_hide_unexpected_setup_failure() -> None:
    native = PolicyNative()
    native.mode_error = DFlashError("set mode", "injected")
    config = SatyrnConfig(drafter_path=Path("draft.gguf"))

    with pytest.raises(DFlashError, match="injected"):
        _select_step(native, config, 10, 20, "metal")


def test_successful_on_returns_dflash_step() -> None:
    native = PolicyNative()
    config = SatyrnConfig(dflash=DFlashMode.ON, drafter_path=Path("draft.gguf"))

    step = _select_step(native, config, 10, 20, "metal")

    assert isinstance(step, DFlashStep)
    assert native.mode == 1


def test_open_configures_public_session_and_close_once(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = PolicyNative()
    fake_engine = FakeEngine(cast("Native", FakeNative()))
    captured: dict[str, object] = {}

    def fake_open(model: str | Path, **kwargs: object) -> Engine:
        captured["model"] = model
        captured.update(kwargs)
        return cast("Engine", fake_engine)

    monkeypatch.setattr(ds4py, "open", fake_open)
    monkeypatch.setattr(engine_module, "CtypesDFlashNative", lambda native: policy)
    config = SatyrnConfig(
        dflash=DFlashMode.ON,
        drafter_path=Path("draft.gguf"),
        draft_tokens=7,
        think_budget=ThinkBudgetConfig(max_tokens=10, bias=2.0),
    )

    with engine_module.open("target.gguf", config=config, seed=33) as wrapper:
        session = wrapper.session()
        assert session is fake_engine.fake_session
        assert isinstance(fake_engine.fake_session.step, DFlashStep)
        assert len(fake_engine.fake_session.hooks) == 1
        assert fake_engine.sampling_defaults == SamplingPolicy(0.6, 0.95, 0.0, 20, 33)
        assert wrapper.dflash_metrics == DFlashMetrics()
        with pytest.raises(EngineError, match="one session"):
            wrapper.session()

    assert captured["mtp_path"] == Path("draft.gguf")
    assert captured["mtp_draft_tokens"] == 7
    assert captured["seed"] == 33
    assert fake_engine.close_calls == 1
    assert fake_engine.fake_session.closed == 1
    wrapper.close()
    assert fake_engine.close_calls == 1


def test_closed_wrapper_rejects_session(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = PolicyNative()
    fake_engine = FakeEngine(cast("Native", FakeNative()))
    monkeypatch.setattr(ds4py, "open", lambda *args, **kwargs: cast("Engine", fake_engine))
    monkeypatch.setattr(engine_module, "CtypesDFlashNative", lambda native: policy)
    wrapper = engine_module.open("target.gguf")
    wrapper.close()

    with pytest.raises(EngineError, match="closed"):
        wrapper.session()


def test_plain_session_has_no_dflash_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = PolicyNative()
    fake_engine = FakeEngine(cast("Native", FakeNative()))
    monkeypatch.setattr(ds4py, "open", lambda *args, **kwargs: cast("Engine", fake_engine))
    monkeypatch.setattr(engine_module, "CtypesDFlashNative", lambda native: policy)

    wrapper = engine_module.open("target.gguf", native=cast("Native", FakeNative()), cancel=threading.Event())
    wrapper.session()

    assert isinstance(fake_engine.fake_session.step, PlainStep)
    assert fake_engine.fake_session.hooks == []
    assert wrapper.dflash_metrics is None
