"""Host-driven DFlash decode on ds4-py's native worker."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from ds4py.engine.decode import Verdict
from ds4py.errors import EngineError

if TYPE_CHECKING:
    from ds4py._native.protocol import SessionHandle
    from ds4py.engine.decode import DecodeContext

    from ._native import DFlashNative


@dataclass(frozen=True, slots=True)
class DFlashMetrics:
    committed_blocks: int = 0
    drafts_offered: int = 0
    drafts_accepted: int = 0
    replacement_anchors: int = 0
    discarded_tails: int = 0

    @property
    def acceptance_rate(self) -> float:
        if self.drafts_offered == 0:
            return 0.0
        return self.drafts_accepted / self.drafts_offered


class _MetricsRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = DFlashMetrics()

    def snapshot(self) -> DFlashMetrics:
        with self._lock:
            return self._snapshot

    def committed(self, offered: int, accepted: int, *, replacement: bool, discarded: int) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = DFlashMetrics(
                committed_blocks=current.committed_blocks + 1,
                drafts_offered=current.drafts_offered + offered,
                drafts_accepted=current.drafts_accepted + accepted,
                replacement_anchors=current.replacement_anchors + int(replacement),
                discarded_tails=current.discarded_tails + discarded,
            )


class _Phase(Enum):
    IDLE = auto()
    STAGING = auto()
    VERIFY_OPEN = auto()


@dataclass(slots=True)
class _PendingAnchor:
    token: int
    before_rng: int
    after_rng: int


@dataclass(slots=True)
class _BlockState:
    anchor: int
    phase: _Phase = _Phase.STAGING
    drafts: tuple[int, ...] = ()
    accepted_drafts: int = 0


@dataclass(slots=True)
class _RowOutcome:
    pending: _PendingAnchor | None = None
    replacement: bool = False
    stop: _PendingAnchor | None = None


class DFlashStep:
    hooks_every_sample = True

    def __init__(self, native: DFlashNative, *, draft_tokens: int = 0, verify_rows: int = 8) -> None:
        if draft_tokens < 0:
            raise ValueError("draft_tokens must be non-negative")
        if verify_rows <= 0:
            raise ValueError("verify_rows must be positive")
        self._native = native
        self._maximum = verify_rows - 1 if draft_tokens == 0 else min(draft_tokens, verify_rows - 1)
        self._metrics = _MetricsRecorder()

    @property
    def metrics(self) -> DFlashMetrics:
        return self._metrics.snapshot()

    def run(self, session: SessionHandle, ctx: DecodeContext) -> None:
        pending: _PendingAnchor | None = None
        while not ctx.finalized and not ctx.cancelled():
            pending = self._anchor(session, ctx) if pending is None else pending
            if ctx.is_stop(pending.token):
                ctx.accept(pending.token)
                return

            block = _BlockState(pending.token)
            ctx.begin_staging()
            verdict = ctx.stage(block.anchor, ctx.accept(block.anchor))
            if verdict is Verdict.STOP_AFTER:
                session.eval(block.anchor)
                ctx.publish()
                self._metrics.committed(0, 0, replacement=False, discarded=0)
                return

            block.drafts = tuple(self._native.draft(session.raw, block.anchor, self._maximum))
            self._native.verify(session.raw, block.anchor, block.drafts)
            block.phase = _Phase.VERIFY_OPEN
            outcome = self._scan_rows(session, ctx, block)
            pending = outcome.pending
            self._commit_and_publish(session, ctx, block, replacement=outcome.replacement)
            if outcome.stop is not None:
                ctx.accept(outcome.stop.token)
                return

            if ctx.reason is not None:
                if pending is not None:
                    ctx.rng.value = pending.before_rng
                return

        if pending is not None and ctx.cancelled() and not ctx.finalized:
            ctx.rng.value = pending.before_rng

    def _anchor(self, session: SessionHandle, ctx: DecodeContext) -> _PendingAnchor:
        before = ctx.rng.value
        ctx.before_sample()
        policy = ctx.sampling()
        token = session.sample(policy.temperature, policy.top_k, policy.top_p, policy.min_p, ctx.rng)
        if token < 0:
            raise EngineError("cannot sample DFlash anchor: the session state is not valid; sync first")
        return _PendingAnchor(token, before, ctx.rng.value)

    def _sample_row(self, session: SessionHandle, ctx: DecodeContext) -> _PendingAnchor:
        candidate = self._anchor(session, ctx)
        if candidate.token < 0:
            raise EngineError("cannot sample DFlash verify row")
        return candidate

    def _scan_rows(
        self,
        session: SessionHandle,
        ctx: DecodeContext,
        block: _BlockState,
    ) -> _RowOutcome:
        for row, draft in enumerate((*block.drafts, None)):
            self._native.select(session.raw, row)
            candidate = self._sample_row(session, ctx)
            if ctx.is_stop(candidate.token):
                return _RowOutcome(stop=candidate)
            if draft is None or candidate.token != draft:
                return _RowOutcome(candidate, replacement=draft is not None)
            verdict = ctx.stage(candidate.token, ctx.accept(candidate.token))
            block.accepted_drafts += 1
            if verdict is Verdict.STOP_AFTER:
                return _RowOutcome()
        return _RowOutcome()

    def _commit_and_publish(
        self,
        session: SessionHandle,
        ctx: DecodeContext,
        block: _BlockState,
        *,
        replacement: bool,
    ) -> None:
        self._native.commit(session.raw, 1 + block.accepted_drafts)
        block.phase = _Phase.IDLE
        ctx.publish()
        self._metrics.committed(
            len(block.drafts),
            block.accepted_drafts,
            replacement=replacement,
            discarded=len(block.drafts) - block.accepted_drafts,
        )
