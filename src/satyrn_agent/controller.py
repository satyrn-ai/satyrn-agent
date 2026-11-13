"""Satyrn runtime controls, session state, and footer ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Never

from ds4py.engine.decode import PlainStep
from ds4py.tui_commands import CommandError

from .capabilities.think_budget import ThinkBudgetHook
from .config import DFlashMode, ThinkBudgetConfig
from .dflash import DFlashStep, Recorder
from .errors import DFlashUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable

    from ds4py import Session
    from ds4py.engine.decode import DecodeStep
    from ds4py.engine.lifecycle import SessionEvent
    from ds4py.tui_commands import SlashCommandRegistry

    from ._native import DFlashPolicyNative
    from .config import SatyrnConfig

_STATE_KEY = "satyrn.runtime"
_DFLASH_USAGE = "/dflash [auto|on|off]"
_THINK_USAGE = "/think-budget [<max_tokens> [bias]|off]"


@dataclass(slots=True)
class RuntimeState:
    requested: DFlashMode
    step: DecodeStep
    recorder: Recorder
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def select_step(  # noqa: PLR0913 - The native policy needs open, mode, metrics, and mutation context.
    native: DFlashPolicyNative,
    config: SatyrnConfig,
    engine_raw: int,
    session_raw: int,
    backend: str,
    *,
    requested: DFlashMode | None = None,
    recorder: Recorder | None = None,
    before_mode_change: Callable[[], None],
) -> DecodeStep:
    """Resolve one between-prompt policy without reinterpreting it later."""
    mode = config.dflash if requested is None else requested

    def set_verify(value: int) -> None:
        before_mode_change()
        native.set_verify_mode(session_raw, value)

    if mode is DFlashMode.OFF or config.drafter_path is None:
        if mode is DFlashMode.ON:
            raise DFlashUnavailable("DFlash requires a drafter path")
        if native.verify_mode_available:
            set_verify(0)
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
        if mode is DFlashMode.ON:
            raise DFlashUnavailable(reason)
        if native.verify_mode_available:
            set_verify(0)
        return PlainStep()
    step = DFlashStep(native, draft_tokens=config.draft_tokens, verify_rows=rows, recorder=recorder)
    set_verify(1)
    return step


class RuntimeController:
    """Own engine-lifetime policy; keep mutable mode and metrics in session state."""

    def __init__(  # noqa: PLR0913 - Controller composition mirrors the session/native boundary.
        self,
        session: Session,
        native: DFlashPolicyNative,
        config: SatyrnConfig,
        backend: str,
        *,
        interactive: bool,
        end_think_token: int,
    ) -> None:
        self._session = session
        self._native = native
        self._config = config
        self._backend = backend
        self._interactive = interactive
        self._closed = False
        self.think_hook = ThinkBudgetHook(config.think_budget, end_think_token)
        session.state(_STATE_KEY, lambda: RuntimeState(config.dflash, PlainStep(), Recorder()))
        self._unsubscribes: list[Callable[[], None]] = []
        if interactive:
            self._unsubscribes = [
                session.on_event(self._session_start, kinds={"session_start"}),
                session.on_event(self._run_end, kinds={"run_end"}),
            ]

    @property
    def state(self) -> RuntimeState:
        return self._session.state(
            _STATE_KEY,
            lambda: RuntimeState(self._config.dflash, PlainStep(), Recorder()),
        )

    def initialize(self) -> None:
        self._change(self._config.dflash, publish=False)

    def _set_verify_off(self) -> None:
        if self._native.verify_mode_available:
            self._session.on_worker(lambda handles: self._native.set_verify_mode(handles.session, 0)).result()

    def _change(self, requested: DFlashMode, *, publish: bool) -> None:
        state = self.state
        # This no-op replacement is the public idle/paused-round guard. No
        # native reconfiguration happens until it succeeds.
        self._session.set_decode_step(state.step)
        mutated = False

        def mark_mutation() -> None:
            nonlocal mutated
            mutated = True

        try:
            step = self._session.on_worker(
                lambda handles: select_step(
                    self._native,
                    self._config,
                    handles.engine,
                    handles.session,
                    self._backend,
                    requested=requested,
                    recorder=state.recorder,
                    before_mode_change=mark_mutation,
                )
            ).result()
            self._session.set_decode_step(step)
        except BaseException as error:
            if not mutated:
                raise
            self._fail_change(state, requested, error)
        state.requested = requested
        state.step = step
        if publish:
            self.publish_status()

    def _fail_change(self, state: RuntimeState, requested: DFlashMode, error: BaseException) -> Never:
        state.requested = requested
        state.step = PlainStep()
        cleanup_error: BaseException | None = None
        try:
            self._session.set_decode_step(state.step)
            self._set_verify_off()
        except BaseException as cleanup:  # noqa: BLE001 - Preserve the native failure and best-effort cleanup failure.
            cleanup_error = cleanup
        self.publish_status(resolved="off", error=cleanup_error is not None)
        if cleanup_error is not None:
            raise error from cleanup_error
        raise error

    def before_identity_change(self) -> None:
        state = self.state
        state.step = PlainStep()
        self._session.set_decode_step(state.step)
        self._set_verify_off()

    def after_identity_change(self) -> None:
        self._change(self._config.dflash, publish=True)

    def _session_start(self, event: SessionEvent) -> None:
        self.think_hook.set(self._config.think_budget)
        self.publish_status(resolved="off")

    def _run_end(self, event: SessionEvent) -> None:
        self.publish_status()

    def status_text(self, *, resolved: str | None = None, error: bool = False) -> str:
        state = self.state
        requested = state.requested.value
        actual = ("on" if isinstance(state.step, DFlashStep) else "off") if resolved is None else resolved
        mode = "error" if error else requested if requested == actual else f"{requested}/{actual}"
        metrics = state.recorder.snapshot()
        acceptance = (
            "accept — (0/0)"
            if metrics.drafts_offered == 0
            else f"accept {100 * metrics.drafts_accepted / metrics.drafts_offered:.1f}% "
            f"({metrics.drafts_accepted}/{metrics.drafts_offered})"
        )
        return f"dflash: {mode}, {acceptance}"

    def publish_status(self, *, resolved: str | None = None, error: bool = False) -> None:
        if self._interactive:
            self._session.emit("status", key="dflash", text=self.status_text(resolved=resolved, error=error))

    def set_dflash(self, *args: str) -> str:
        if len(args) > 1 or (args and args[0] not in {mode.value for mode in DFlashMode}):
            raise CommandError(f"usage: {_DFLASH_USAGE}")
        if not args:
            return self.status_text()
        self._change(DFlashMode(args[0]), publish=True)
        return self.status_text()

    def _think_text(self) -> str:
        setting = self.think_hook.snapshot()
        if setting is None:
            return "think budget off"
        return f"think budget {setting.max_tokens} tokens, bias {setting.bias}"

    def set_think_budget(self, *args: str) -> str:
        if not args:
            return self._think_text()
        if args == ("off",):
            self._session.set_decode_step(self.state.step)
            self.think_hook.set(None)
            return self._think_text()
        if len(args) not in {1, 2}:
            raise CommandError(f"usage: {_THINK_USAGE}")
        current = self.think_hook.snapshot()
        try:
            maximum = int(args[0])
            bias = (current.bias if current is not None else 2.0) if len(args) == 1 else float(args[1])
            setting = ThinkBudgetConfig(maximum, bias)
        except (TypeError, ValueError) as error:
            raise CommandError(f"usage: {_THINK_USAGE}") from error
        self._session.set_decode_step(self.state.step)
        self.think_hook.set(setting)
        return self._think_text()

    def configure_commands(self, registry: SlashCommandRegistry) -> None:
        registry.register("dflash", self.set_dflash, description="Set DFlash mode", usage=_DFLASH_USAGE)
        registry.register(
            "think-budget",
            self.set_think_budget,
            description="Set the soft think budget",
            usage=_THINK_USAGE,
        )
        self.publish_status()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.think_hook.set(None)
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
