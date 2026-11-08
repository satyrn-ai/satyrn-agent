"""Open and configure one downstream ds4-py engine/session pair."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import ds4py
from ds4py import EngineError, ThinkMode
from ds4py.engine.decode import PlainStep

from ._native import CtypesDFlashNative
from .capabilities.sampling import merge_sampling
from .capabilities.think_budget import ThinkBudgetHook, resolve_end_think
from .config import DFlashMode, SatyrnConfig
from .dflash import DFlashMetrics, DFlashStep
from .errors import DFlashUnavailable

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from ds4py import Engine, Session
    from ds4py._native.protocol import Native
    from ds4py.engine.decode import DecodeStep
    from ds4py.engine.sampling import SamplingPolicy

    from ._native import DFlashNative


def _select_step(
    native: DFlashNative,
    config: SatyrnConfig,
    engine_raw: int,
    session_raw: int,
    backend: str,
) -> DecodeStep:
    """Resolve auto/on/off once; never reinterpret policy during a round."""
    if config.dflash is DFlashMode.OFF or config.drafter_path is None:
        return PlainStep()
    reason: str | None = None
    rows = 0
    if missing := native.missing_dflash:
        reason = f"DFlash bindings are missing: {', '.join(missing)}"
    elif backend != "metal":
        reason = f"DFlash requires Metal, not {backend}"
    elif not native.has_dflash(engine_raw):
        reason = "DFlash requires a loaded drafter"
    else:
        rows = native.verify_rows(engine_raw)
        if rows == 0:
            reason = "DFlash requires at least one verify row"
    if reason is not None:
        if config.dflash is DFlashMode.ON:
            raise DFlashUnavailable(reason)
        return PlainStep()
    native.set_verify_mode(session_raw, 1)
    return DFlashStep(native, draft_tokens=config.draft_tokens, verify_rows=rows)


class SatyrnEngine:
    """Thin engine-factory wrapper; the configured session is ds4-py's own."""

    def __init__(self, engine: Engine, config: SatyrnConfig, seed: int | None) -> None:
        self._engine = engine
        self._config = config
        self._seed = seed
        self._session: Session | None = None
        self._step: DecodeStep | None = None
        self._closed = False

    def session(self) -> Session:
        if self._closed:
            raise EngineError("engine is closed")
        if self._session is not None:
            raise EngineError("one session per engine")
        session = self._engine.session()
        self._session = session
        try:
            native = CtypesDFlashNative(self._engine.native)
            defaults = session.on_worker(lambda handles: native.sampling_defaults(handles.engine)).result()
            self._engine.sampling_defaults = merge_sampling(
                self._engine.sampling_defaults,
                defaults,
                self._config.sampling,
                self._seed,
            )
            if self._config.think_budget is not None:
                session.add_logits_hook(ThinkBudgetHook(self._config.think_budget, resolve_end_think(self._engine)))
            self._step = session.on_worker(
                lambda handles: _select_step(
                    native, self._config, handles.engine, handles.session, self._engine.native.backend
                )
            ).result()
            session.set_decode_step(self._step)
        except BaseException as error:
            try:
                self.close()
            except BaseException as close_error:  # noqa: BLE001 - Preserve the original setup failure.
                error.add_note(
                    f"Satyrn engine close failed after session setup error: {type(close_error).__name__}: {close_error}"
                )
            raise
        return session

    @property
    def decode_step(self) -> DecodeStep | None:
        return self._step

    @property
    def sampling_defaults(self) -> SamplingPolicy:
        return self._engine.sampling_defaults

    @property
    def dflash_metrics(self) -> DFlashMetrics | None:
        if isinstance(self._step, DFlashStep):
            return self._step.metrics
        return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._engine.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open(  # noqa: PLR0913 - Mirror ds4-py's native-open options without hiding their contracts.
    model: str | Path = "ds4flash.gguf",
    *,
    config: SatyrnConfig | None = None,
    ctx: int = 100_000,
    backend: str | None = None,
    think: int = ThinkMode.HIGH,
    seed: int | None = None,
    threads: int = 0,
    lib: str | Path | None = None,
    native: Native | None = None,
    cancel: threading.Event | None = None,
) -> SatyrnEngine:
    """Open ds4-py with Satyrn's explicit drafter and decode configuration."""
    resolved = SatyrnConfig() if config is None else config
    engine = ds4py.open(
        model,
        ctx=ctx,
        backend=backend,
        think=think,
        seed=seed,
        threads=threads,
        mtp_path=resolved.drafter_path,
        mtp_draft_tokens=resolved.draft_tokens,
        lib=lib,
        native=native,
        cancel=cancel,
    )
    return SatyrnEngine(engine, resolved, seed)
