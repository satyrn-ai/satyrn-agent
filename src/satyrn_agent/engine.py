"""Open and configure one downstream ds4-py engine/session pair."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import ds4py
from ds4py import EngineError, ThinkMode

from ._native import CtypesDFlashNative
from .capabilities.sampling import merge_sampling
from .capabilities.think_budget import resolve_end_think
from .config import SatyrnConfig
from .controller import RuntimeController
from .dflash import DFlashMetrics, DFlashStep

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from ds4py import Engine, Session
    from ds4py._native.protocol import Native
    from ds4py.engine.decode import DecodeStep
    from ds4py.engine.sampling import SamplingPolicy


class SatyrnEngine:
    """Thin engine-factory wrapper; the configured session is ds4-py's own."""

    def __init__(self, engine: Engine, config: SatyrnConfig, seed: int | None, *, interactive: bool = False) -> None:
        self._engine = engine
        self._config = config
        self._seed = seed
        self._interactive = interactive
        self._session: Session | None = None
        self._step: DecodeStep | None = None
        self._controller: RuntimeController | None = None
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
            self._controller = RuntimeController(
                session,
                native,
                self._config,
                self._engine.native.backend,
                interactive=self._interactive,
                end_think_token=resolve_end_think(self._engine),
            )
            session.add_logits_hook(self._controller.think_hook)
            self._controller.initialize()
            self._step = self._controller.state.step
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
    def controller(self) -> RuntimeController:
        if self._controller is None:
            raise EngineError("session is not configured")
        return self._controller

    @property
    def decode_step(self) -> DecodeStep | None:
        return self._step if self._closed or self._controller is None else self._controller.state.step

    @property
    def sampling_defaults(self) -> SamplingPolicy:
        return self._engine.sampling_defaults

    @property
    def dflash_metrics(self) -> DFlashMetrics | None:
        step = self.decode_step
        if isinstance(step, DFlashStep):
            return step.metrics
        return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._controller is not None:
                self._controller.close()
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
    interactive: bool = False,
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
    return SatyrnEngine(engine, resolved, seed, interactive=interactive)
