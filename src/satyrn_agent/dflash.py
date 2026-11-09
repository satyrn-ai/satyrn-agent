"""Host-driven DFlash decode on ds4-py's native worker."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ds4py.engine.decode import Verdict
from ds4py.errors import EngineError
from typing_extensions import sentinel

_BONUS = sentinel("_BONUS")

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


@dataclass(slots=True)
class _PendingAnchor:
    token: int
    before_rng: int


@dataclass(slots=True)
class _BlockState:
    anchor: int
    drafts: tuple[int, ...] = ()
    accepted_drafts: int = 0


@dataclass(slots=True)
class _RowOutcome:
    pending: _PendingAnchor | None = None
    replacement: bool = False
    stop: _PendingAnchor | None = None
    interrupted: bool = False


class DFlashStep:
    hooks_every_sample = True

    def __init__(self, native: DFlashNative, *, draft_tokens: int = 0, verify_rows: int = 8) -> None:
        self._native = native
        self._maximum = verify_rows - 1 if draft_tokens == 0 else min(draft_tokens, verify_rows - 1)
        self._metrics = _MetricsRecorder()

    @property
    def metrics(self) -> DFlashMetrics:
        return self._metrics.snapshot()

    def run(self, session: SessionHandle, ctx: DecodeContext) -> None:
        pending: _PendingAnchor | None = None
        while not ctx.finalized and not ctx.cancelled():
            block_start_rng = ctx.rng.value
            pending = self._anchor(session, ctx) if pending is None else pending
            if ctx.is_stop(pending.token):
                ctx.accept(pending.token)
                return

            block = _BlockState(pending.token)
            ctx.begin_staging()
            verdict = ctx.stage(block.anchor, ctx.accept(block.anchor))
            if verdict is Verdict.STOP_AFTER and ctx.reason != "context_reserve":
                self._publish_block(session, ctx, block, commit_rows=None)
                return
            if ctx.cancelled():
                self._publish_block(session, ctx, block, commit_rows=None)
                ctx.finish("interrupted")
                return

            try:
                block.drafts = tuple(self._native.draft(session.raw, block.anchor, self._maximum))
                self._native.verify(session.raw, block.anchor, block.drafts)
            except BaseException as error:  # noqa: BLE001 - Native graph failure can invalidate the checkpoint.
                ctx.discard()
                ctx.rng.value = block_start_rng
                ctx.poison(error)
            try:
                outcome = self._scan_rows(session, ctx, block)
            except BaseException:
                self._publish_block(session, ctx, block, commit_rows=1 + block.accepted_drafts, replacement=False)
                raise
            pending = outcome.pending
            self._publish_block(
                session,
                ctx,
                block,
                commit_rows=1 + block.accepted_drafts,
                replacement=outcome.replacement,
            )
            if outcome.stop is not None:
                ctx.accept(outcome.stop.token)
                return
            if outcome.interrupted:
                if pending is not None:
                    ctx.rng.value = pending.before_rng
                ctx.finish("interrupted")
                return

            if ctx.reason is not None:
                if pending is not None:
                    ctx.rng.value = pending.before_rng
                return

        if ctx.cancelled() and pending is not None:
            ctx.rng.value = pending.before_rng
            ctx.finish("interrupted")

    def _publish_block(
        self,
        session: SessionHandle,
        ctx: DecodeContext,
        block: _BlockState,
        *,
        commit_rows: int | None,
        replacement: bool = False,
    ) -> None:
        try:
            if commit_rows is None:
                session.eval(block.anchor)
            else:
                self._native.commit(session.raw, commit_rows)
            ctx.publish()
        except BaseException as error:  # noqa: BLE001 - Never publish after uncertain native work.
            ctx.poison(error)
        committing = commit_rows is not None
        self._metrics.committed(
            len(block.drafts) if committing else 0,
            block.accepted_drafts,
            replacement=replacement,
            discarded=len(block.drafts) - block.accepted_drafts if committing else 0,
        )

    def _anchor(self, session: SessionHandle, ctx: DecodeContext) -> _PendingAnchor:
        before = ctx.rng.value
        ctx.before_sample()
        policy = ctx.sampling()
        token = session.sample(policy.temperature, policy.top_k, policy.top_p, policy.min_p, ctx.rng)
        if token < 0:
            raise EngineError("cannot sample DFlash anchor: the session state is not valid; sync first")
        return _PendingAnchor(token, before)

    def _scan_rows(
        self,
        session: SessionHandle,
        ctx: DecodeContext,
        block: _BlockState,
    ) -> _RowOutcome:
        row = 0
        while True:
            draft = block.drafts[row] if row < len(block.drafts) else _BONUS
            if ctx.cancelled():
                return _RowOutcome(interrupted=True)
            self._native.select(session.raw, row)
            candidate = self._anchor(session, ctx)
            if ctx.is_stop(candidate.token):
                return _RowOutcome(stop=candidate)
            if ctx.cancelled():
                return _RowOutcome(candidate, interrupted=True)
            if draft is _BONUS or candidate.token != draft:
                return _RowOutcome(candidate, replacement=draft is not _BONUS)
            verdict = ctx.stage(candidate.token, ctx.accept(candidate.token))
            block.accepted_drafts += 1
            if verdict is Verdict.STOP_AFTER or ctx.reason is not None:
                return _RowOutcome()
            row += 1
