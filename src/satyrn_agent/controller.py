"""Satyrn runtime controls, session state, and footer ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Never

from ds4py.engine.decode import PlainStep
from ds4py.tui_commands import CommandError
from pydantic_ai.messages import FunctionToolResultEvent, ToolReturnPart

from .capabilities.think_budget import ThinkBudgetHook
from .config import DFlashMode, ThinkBudgetConfig, ThinkCloseMode
from .dflash import DFlashStep, Recorder
from .errors import DFlashUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ds4py import Session
    from ds4py.engine.decode import DecodeStep
    from ds4py.engine.lifecycle import SessionEvent
    from ds4py.tui_commands import SlashCommandRegistry

    from ._native import DFlashPolicyNative
    from .config import SatyrnConfig

_STATE_KEY = "satyrn.runtime"
_DFLASH_USAGE = "/dflash [auto|on|off]"
_THINK_USAGE = "/think-budget [<max_tokens> [bias]|off|close <bias|force>|until-first-write <on|off>]"


@dataclass(slots=True)
class RuntimeState:
    requested: DFlashMode
    step: DecodeStep
    recorder: Recorder
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def _verify_off(native: DFlashPolicyNative) -> int | None:
    return 0 if native.verify_mode_available else None


def _parse_think_budget(
    current: ThinkBudgetConfig | None,
    args: tuple[str, ...],
) -> ThinkBudgetConfig | None:
    match args:
        case ("off",):
            return None
        case ("close", mode):
            if current is None:
                raise CommandError(f"usage: {_THINK_USAGE}")
            try:
                close = ThinkCloseMode(mode)
            except ValueError as error:
                raise CommandError(f"usage: {_THINK_USAGE}") from error
            return replace(current, close=close)
        case ("until-first-write", enabled):
            if current is None or enabled not in {"on", "off"}:
                raise CommandError(f"usage: {_THINK_USAGE}")
            return replace(current, until_first_write=enabled == "on")
        case (("close" | "until-first-write"),):
            raise CommandError(f"usage: {_THINK_USAGE}")
        case _ if len(args) not in {1, 2}:
            raise CommandError(f"usage: {_THINK_USAGE}")
    try:
        maximum = int(args[0])
        bias = (current.bias if current is not None else 2.0) if len(args) == 1 else float(args[1])
        return ThinkBudgetConfig(maximum, bias) if current is None else replace(current, max_tokens=maximum, bias=bias)
    except (TypeError, ValueError) as error:
        raise CommandError(f"usage: {_THINK_USAGE}") from error


def select_step(  # noqa: PLR0913 - The policy needs native handles, configuration, and request context.
    native: DFlashPolicyNative,
    config: SatyrnConfig,
    engine_raw: int,
    backend: str,
    *,
    requested: DFlashMode | None = None,
    recorder: Recorder | None = None,
) -> tuple[DecodeStep, int | None]:
    """Resolve one between-prompt policy without mutating native state."""
    mode = config.dflash if requested is None else requested
    verify_off = _verify_off(native)

    if mode is DFlashMode.OFF or config.drafter_path is None:
        if mode is DFlashMode.ON:
            raise DFlashUnavailable("DFlash requires a drafter path")
        return PlainStep(), verify_off
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
        return PlainStep(), verify_off
    step = DFlashStep(native, draft_tokens=config.draft_tokens, verify_rows=rows, recorder=recorder)
    return step, 1


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
        closing_tokens: Sequence[int],
        vocab_size: int,
    ) -> None:
        self._session = session
        self._native = native
        self._config = config
        self._backend = backend
        self._interactive = interactive
        self._closed = False
        self.think_hook = ThinkBudgetHook(config.think_budget, end_think_token, closing_tokens, vocab_size)
        self._live_state = session.state(_STATE_KEY, lambda: RuntimeState(config.dflash, PlainStep(), Recorder()))
        self._resolved = False
        self._unsubscribes: list[Callable[[], None]] = [
            session.on_event(self._run_start, kinds={"run_start"}),
            session.on_event(self._agent_event, kinds={"agent_event"}),
        ]
        if interactive:
            self._unsubscribes.extend(
                [
                    session.on_event(self._session_start, kinds={"session_start"}),
                    session.on_event(self._run_end, kinds={"run_end"}),
                ]
            )

    @property
    def state(self) -> RuntimeState:
        self._live_state = self._session.state(
            _STATE_KEY,
            lambda: RuntimeState(self._config.dflash, PlainStep(), Recorder()),
        )
        return self._live_state

    @property
    def resolved_step(self) -> DecodeStep | None:
        """Return the last applied step without reopening a closed session."""
        return self._live_state.step if self._resolved else None

    def initialize(self) -> None:
        self._change(self._config.dflash, publish=False)

    def _install(self, state: RuntimeState, step: DecodeStep, verify: int | None) -> None:
        # The initial idle guard proves decode setters succeed before mutation.
        # These synchronous calls have no generation or await boundary between them.
        self._live_state = state
        self._session.set_decode_step(step)
        self._resolved = True
        if verify is not None:
            self._session.on_worker(lambda handles: self._native.set_verify_mode(handles.session, verify)).result()

    def _install_plain(self, state: RuntimeState) -> None:
        state.step = PlainStep()
        self._install(state, state.step, _verify_off(self._native))

    def _change(self, requested: DFlashMode, *, publish: bool) -> None:
        state = self.state
        # This no-op replacement is the public idle/paused-round guard. No
        # native reconfiguration happens until it succeeds.
        self._session.set_decode_step(state.step)
        step, verify = self._session.on_worker(
            lambda handles: select_step(
                self._native,
                self._config,
                handles.engine,
                self._backend,
                requested=requested,
                recorder=state.recorder,
            )
        ).result()
        try:
            self._install(state, step, verify)
        except BaseException as error:  # noqa: BLE001 - Roll back before propagating native or cancellation failures.
            self._fail_change(state, requested, error)
        state.requested = requested
        state.step = step
        if publish:
            self.publish_status()

    def _fail_change(self, state: RuntimeState, requested: DFlashMode, error: BaseException) -> Never:
        state.requested = requested
        cleanup_error: BaseException | None = None
        try:
            self._install_plain(state)
        except BaseException as cleanup:  # noqa: BLE001 - Preserve the native failure and best-effort cleanup failure.
            cleanup_error = cleanup
        self.publish_status(resolved="off", error=cleanup_error is not None)
        if cleanup_error is not None:
            raise error from cleanup_error
        raise error

    def before_identity_change(self) -> None:
        self._install_plain(self.state)

    def after_identity_change(self) -> None:
        self._change(self._config.dflash, publish=True)

    def _run_start(self, event: SessionEvent) -> None:
        self.think_hook.start_run()

    def _agent_event(self, event: SessionEvent) -> None:
        inner = event.payload.get("event")
        if not isinstance(inner, FunctionToolResultEvent):
            return
        part = inner.part
        if (
            isinstance(part, ToolReturnPart)
            and part.outcome == "success"
            and part.tool_name in {"write_file", "edit_file"}
        ):
            self.think_hook.suppress_thinking()

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
        first_write = "on" if setting.until_first_write else "off"
        return (
            f"think budget {setting.max_tokens} tokens, bias {setting.bias}, "
            f"close {setting.close}, until first write {first_write}"
        )

    def set_think_budget(self, *args: str) -> str:
        if not args:
            return self._think_text()
        setting = _parse_think_budget(self.think_hook.snapshot(), args)
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
