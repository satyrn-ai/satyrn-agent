import asyncio
import copy
import hashlib
import json
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath
from typing import Protocol, cast
from uuid import uuid4

from ds4py.binding import MessageBinder, ModelMessagesTypeAdapter, SegmentProvenance
from ds4py.engine.events import Checkpointed, Interrupted, Stopped, Synced, Token
from ds4py.engine.worker import SyncJob
from ds4py.model import DS4Model, ResponseTerminalError
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings

from plan_comparison.adapters.think_budget import (
    THINKING_BUDGET_CLOSE,
    ThinkingBudgetHook,
)
from plan_comparison.budget import BudgetExhausted
from plan_comparison.contracts import (
    BoundaryEvidence,
    BudgetTracker,
    ContextPreparationFailure,
    GateResult,
    ModelResponseFailure,
    Slot,
    VisibleGateSpec,
    WorkerBoundary,
    WorkerCapabilities,
    WorkerPort,
    WorkerReply,
)
from plan_comparison.gates import GatePolicy, run_gate

_DS4_PY_COMMIT = "5c98c6ac86cafef56780c3bcbb87c3ecaef52aef"
_UNRESOLVED_CLEANUP_ISSUE = "https://github.com/rochecompaan/ds4-py/issues/20"


class WorkerAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class _ToolContext:
    workspace: Path
    readable_paths: frozenset[str]
    writable_paths: frozenset[str]
    gates: dict[str, VisibleGateSpec]
    gate_policy: GatePolicy
    budget: BudgetTracker
    max_file_read_bytes: int
    gate_results: list[GateResult]
    on_write: Callable[[], None] | None = None


class AgentRunResult(Protocol):
    output: object

    def all_messages(self) -> list[ModelMessage]: ...


class TranscriptSegmentPort(Protocol):
    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def kind(self) -> str: ...

    @property
    def meta(self) -> Mapping[str, object]: ...


class AgentPort(Protocol):
    async def run(
        self,
        prompt: str,
        *,
        deps: _ToolContext,
        message_history: list[ModelMessage] | None = None,
    ) -> AgentRunResult: ...


class ToolAgentPort(AgentPort, Protocol):
    def tool(
        self,
        *,
        sequential: bool = False,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]: ...


@dataclass(frozen=True, slots=True)
class _BoundaryState:
    checkpoint_key: str
    transcript_tokens: tuple[int, ...]
    message_history: tuple[ModelMessage, ...]
    binder_segments: tuple[SegmentProvenance, ...]
    rng_state: int
    session_id: str


@dataclass(frozen=True, slots=True)
class Ds4Agents:
    context: AgentPort
    prose: AgentPort
    compiled: AgentPort


class _PydanticModelProxy(Model):
    def __init__(self, model: DS4Model) -> None:
        super().__init__()
        self._inner = model

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def system(self) -> str:
        return self._inner.system

    def _instance_profile_defaults(self, profile: ModelProfile) -> ModelProfile:
        return self._inner._instance_profile_defaults(profile)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        return await self._inner.request(
            messages, model_settings, model_request_parameters
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[object] | None = None,
    ) -> AsyncGenerator[StreamedResponse, None]:
        async with self._inner.request_stream(
            messages,
            model_settings,
            model_request_parameters,
            run_context=run_context,
        ) as response:
            yield response


def build_restricted_agents(model: DS4Model, gate_policy: GatePolicy) -> Ds4Agents:
    model_proxy = _PydanticModelProxy(model)

    agent = cast(
        ToolAgentPort,
        Agent(
            model_proxy,
            output_type=str,
            deps_type=_ToolContext,
            instructions=(
                "Follow the current phase's user instructions. Use only the "
                "supplied file tools and visible test gates within that phase's "
                "allowlists. Never access protected evaluation material or use "
                "a shell. Read-only phases must not write files or run gates. "
                "For edit slots, return only the requested replacement content."
            ),
            max_concurrency=1,
        ),
    )

    def install_read_tool(agent: ToolAgentPort) -> None:
        @agent.tool(sequential=True)
        async def read_file(ctx: RunContext[_ToolContext], path: str) -> str:
            return _read_file_result(ctx.deps, path)

    def install_write_tools(agent: ToolAgentPort) -> None:
        @agent.tool(sequential=True)
        async def write_file(
            ctx: RunContext[_ToolContext], path: str, content: str
        ) -> str:
            return _write_file_result(ctx.deps, path, content)

        @agent.tool(sequential=True)
        async def run_visible_gate(ctx: RunContext[_ToolContext], gate_id: str) -> str:
            spec = ctx.deps.gates.get(gate_id)
            if spec is None:
                return f"error: visible gate is not allowlisted: {gate_id}"
            ctx.deps.budget.ensure_capacity()
            result = run_gate(
                ctx.deps.workspace,
                spec.gate_id,
                spec.gate,
                spec.expectation,
                ctx.deps.gate_policy,
            )
            ctx.deps.gate_results.append(result)
            ctx.deps.budget.ensure_capacity()
            return (
                f"gate={result.gate_id} status={result.status} "
                f"exit={result.exit_code}\n{result.output_excerpt}"
            )

    install_read_tool(agent)
    install_write_tools(agent)
    return Ds4Agents(
        context=agent,
        prose=agent,
        compiled=agent,
    )


def _read_file_result(context: _ToolContext, path: str) -> str:
    """Return the file, or a refusal the model can act on."""
    try:
        target = _workspace_file(context.workspace, path)
        if path not in context.readable_paths:
            raise ValueError(f"Read path is not allowlisted: {path}")
        if not target.is_file():
            raise FileNotFoundError(path)
        content = target.read_bytes()
        if len(content) > context.max_file_read_bytes:
            raise ValueError(f"Read exceeds configured limit: {path}")
        return content.decode("utf-8")
    except (OSError, ValueError) as error:
        return f"error: {type(error).__name__}: {error}"


def _write_file_result(context: _ToolContext, path: str, content: str) -> str:
    """Write the file, or return a refusal without touching the workspace."""
    try:
        target = _workspace_file(context.workspace, path)
        if path not in context.writable_paths:
            raise ValueError(f"Write path is not allowlisted: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as error:
        return f"error: {type(error).__name__}: {error}"
    if context.on_write is not None:
        context.on_write()
    return f"Wrote {path}."


def _workspace_file(workspace: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or "\\" in relative_path
        or any(part in ("", ".", "..") for part in relative_path.split("/"))
    ):
        raise ValueError("Tool path must be a canonical relative POSIX file path.")
    target = workspace.joinpath(*pure.parts)
    current = workspace
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Tool paths cannot contain symlinks.")
    try:
        target.resolve(strict=False).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError("Tool path escapes the worker workspace.") from error
    return target


class Ds4WorkerAdapter(WorkerPort):
    def __init__(
        self,
        *,
        model: DS4Model,
        agents: Ds4Agents,
        model_id: str,
        model_revision: str,
        runtime_revision: str,
        tokenizer_revision: str,
        gate_policy: GatePolicy,
        thinking_budget: int = 4096,
        think_until_first_write: bool = False,
        context_retry_limit: int = 2,
        max_file_read_bytes: int = 50_000,
        serial_tools: bool = True,
    ) -> None:
        if (
            not isinstance(thinking_budget, int)
            or isinstance(thinking_budget, bool)
            or thinking_budget < 0
        ):
            raise ValueError("thinking budget must be a non-negative integer")

        self.model = model
        self.session = model.session
        if not isinstance(think_until_first_write, bool):
            raise ValueError("think_until_first_write must be a boolean")
        self.think_until_first_write = think_until_first_write
        if (
            not isinstance(context_retry_limit, int)
            or isinstance(context_retry_limit, bool)
            or not 0 <= context_retry_limit <= 2
        ):
            raise ValueError(
                "context retry limit must be an integer between zero and two"
            )
        self.context_retry_limit = context_retry_limit
        self._context_failures: list[str] = []
        self._thinking_suppressed = False
        self.thinking_budget = thinking_budget
        if thinking_budget:
            engine = self.session.engine
            close_tokens = engine.tokenize(THINKING_BUDGET_CLOSE, rendered=True)
            self._thinking_budget_hook: ThinkingBudgetHook | None = ThinkingBudgetHook(
                budget_tokens=thinking_budget,
                closing_tokens=close_tokens,
                vocab_size=engine.info.vocab_size,
            )
            self.session.add_logits_hook(self._thinking_budget_hook)
        else:
            self._thinking_budget_hook = None
        if think_until_first_write:
            engine = self.session.engine
            immediate_close = ThinkingBudgetHook(
                budget_tokens=1,
                closing_tokens=engine.tokenize("</think>", rendered=True),
                vocab_size=engine.info.vocab_size,
                force_close=True,
            )
            self.session.add_logits_hook(
                lambda view: (
                    immediate_close(view) if self._thinking_suppressed else None
                )
            )
        self.binder: MessageBinder = model.binder
        self.agents = agents
        self.model_id = model_id
        self.model_revision = model_revision
        self.runtime_revision = runtime_revision
        self.tokenizer_revision = tokenizer_revision
        self.gate_policy = gate_policy
        self.max_file_read_bytes = max_file_read_bytes
        self.serial_tools = serial_tools
        self._message_history: list[ModelMessage] = []
        self._common_checkpoint_key: str | None = None
        self._branch_checkpoint_key: str | None = None
        self._session_owner_id = self.session.id
        self._last_sync_events: tuple[Synced, ...] = ()
        self._closed = False
        self._lock = asyncio.Lock()

    async def capabilities(self, *, budget: BudgetTracker) -> WorkerCapabilities:
        native_restore = bool(self.session.engine.native.restore_enabled)
        rng_state = self.session._rng.state
        has_prefill_count = "prefilled" in {field.name for field in fields(Synced)}
        evidence = (
            f"ds4-py pinned commit {_DS4_PY_COMMIT}",
            "serial tool calls configured by the restricted Pydantic AI agents",
            f"cancellation rewind semantics unresolved: {_UNRESOLVED_CLEANUP_ISSUE}",
        )
        return WorkerCapabilities(
            native_checkpoint=callable(self.session.checkpoint),
            token_reuse=native_restore,
            actual_prefill_counts=has_prefill_count,
            rng_restore=hasattr(rng_state, "value"),
            host_history_restore=callable(self.binder.restore),
            binder_restore=callable(self.binder.restore),
            serial_tools=self.serial_tools,
            safe_cancellation=False,
            evidence=evidence,
            runtime_kind="live",
        )

    async def capture_boundary(
        self,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        budget: BudgetTracker,
    ) -> WorkerBoundary:
        async with self._lock:
            self._ensure_open()
            if not self._message_history:
                scope = self._tool_context(
                    workspace,
                    allowed_read_paths,
                    (),
                    (),
                    budget,
                )
                prompt = (
                    f"Task id: {task_id}\nShared plan:\n{plan}\n"
                    + _paths_prompt(allowed_read_paths, ())
                    + "Read the shared task context and relevant source files, "
                    "then summarize established interfaces without proposing edits."
                )
                self._context_failures.clear()
                for attempt in range(self.context_retry_limit + 1):
                    budget.ensure_capacity()
                    try:
                        await self._run_agent(
                            self.agents.context, prompt, scope, budget
                        )
                        break
                    except ModelResponseFailure as error:
                        self._context_failures.append(error.reason)
                        self.session.truncate(0)
                        binder = MessageBinder(self.session)
                        binder.note_provider = self.binder.note_provider
                        self.binder = self.model.binder = binder
                        self._message_history.clear()
                        self._thinking_suppressed = False
                        budget.ensure_capacity()
                        if attempt == self.context_retry_limit:
                            raise ContextPreparationFailure(
                                error.reason, attempt + 1
                            ) from error
            return self._capture_boundary(budget)

    async def restore_boundary(
        self, boundary: WorkerBoundary, *, budget: BudgetTracker
    ) -> None:
        async with self._lock:
            self._ensure_open()
            if not isinstance(boundary.opaque_token, _BoundaryState):
                raise WorkerAdapterError(
                    "Boundary token was not created by this adapter."
                )
            state = boundary.opaque_token
            if state.session_id != self._session_owner_id:
                raise WorkerAdapterError("Boundary belongs to another DS4 session.")

            def restore() -> dict[str, object]:
                self.session.truncate(len(state.transcript_tokens))
                plan = self.session.plan(state.transcript_tokens)
                if not plan.fits or plan.kind == "rebuild":
                    raise WorkerAdapterError(
                        "Native session cannot restore this checkpoint without "
                        "a rebuild."
                    )
                sync_events = tuple(
                    self.session._job_events(SyncJob(state.transcript_tokens))
                )
                if any(
                    isinstance(event, Interrupted)
                    or (isinstance(event, Stopped) and event.reason == "interrupted")
                    for event in sync_events
                ):
                    raise WorkerAdapterError("Native sync was interrupted.")
                synced = next(
                    (event for event in sync_events if isinstance(event, Synced)), None
                )
                if synced is None or synced.pos != len(state.transcript_tokens):
                    raise WorkerAdapterError(
                        "Native sync did not reach the checkpoint boundary."
                    )
                if (
                    synced.plan.kind == "rebuild"
                    or synced.plan.reused != len(state.transcript_tokens)
                    or synced.plan.to_prefill != 0
                ):
                    raise WorkerAdapterError(
                        "Native restore did not reuse the complete captured prefix."
                    )
                if tuple(self.session.transcript.tokens) != state.transcript_tokens:
                    raise WorkerAdapterError(
                        "Host transcript differs after checkpoint sync."
                    )
                self.session._rng.state.value = state.rng_state
                self.binder.restore(
                    copy.deepcopy(state.message_history),
                    copy.deepcopy(state.binder_segments),
                )
                self._message_history = copy.deepcopy(list(state.message_history))
                self._last_sync_events = (synced,)
                branch_key = self._branch_checkpoint_key
                if branch_key is not None and branch_key != state.checkpoint_key:
                    if branch_key in self.session._checkpoint_tokens:
                        self.session.drop_checkpoint(branch_key)
                self._branch_checkpoint_key = (
                    None
                    if state.checkpoint_key == self._common_checkpoint_key
                    else state.checkpoint_key
                )
                return {
                    "checkpoint_key": state.checkpoint_key,
                    "token_count": len(state.transcript_tokens),
                    "sync_kind": synced.plan.kind,
                    "reused_tokens": synced.plan.reused,
                    "prefilled_tokens": synced.prefilled,
                }

            restore()
            self._thinking_suppressed = False
            budget.ensure_capacity()

    async def execute_prose(
        self,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        allowed_write_paths: tuple[str, ...],
        visible_gates: tuple[VisibleGateSpec, ...],
        visible_feedback: tuple[str, ...],
        budget: BudgetTracker,
    ) -> WorkerReply:
        async with self._lock:
            self._ensure_open()
            scope = self._tool_context(
                workspace,
                allowed_read_paths,
                allowed_write_paths,
                visible_gates,
                budget,
            )
            prompt = _worker_prompt(
                task_id, plan, visible_feedback, visible_gates=visible_gates
            ) + _paths_prompt(allowed_read_paths, allowed_write_paths)
            output, evidence = await self._run_agent(
                self.agents.prose, prompt, scope, budget
            )
            return WorkerReply(
                content=output,
                budget=budget.snapshot(),
                boundary_evidence=evidence,
                visible_gate_results=tuple(scope.gate_results),
            )

    async def fill_body(
        self,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        slot: Slot,
        signature_prefill: str,
        visible_feedback: tuple[str, ...],
        budget: BudgetTracker,
    ) -> WorkerReply:
        async with self._lock:
            self._ensure_open()
            scope = self._tool_context(workspace, allowed_read_paths, (), (), budget)
            prompt = (
                f"Task id: {task_id}\nPlan:\n{plan}\n"
                f"Slot id: {slot.slot_id}\nPath: {slot.path}\n"
                f"Fixed callable signature prefill:\n{signature_prefill}\n"
                "Return only the callable body, without a def line or "
                "surrounding file text.\n" + _feedback_prompt(visible_feedback)
            )
            output, evidence = await self._run_agent(
                self.agents.compiled, prompt, scope, budget
            )
            return WorkerReply(
                content=output,
                budget=budget.snapshot(),
                boundary_evidence=evidence,
            )

    async def edit_ancillary(
        self,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        slot: Slot,
        instruction: str,
        visible_feedback: tuple[str, ...],
        budget: BudgetTracker,
    ) -> WorkerReply:
        async with self._lock:
            self._ensure_open()
            scope = self._tool_context(workspace, allowed_read_paths, (), (), budget)
            prompt = (
                f"Task id: {task_id}\nPlan:\n{plan}\n"
                f"Packet instruction: {instruction}\n"
                f"Ancillary slot: {slot.slot_id}; path={slot.path}; "
                f"target={slot.target!r}; extent={slot.extent!r}\n"
                "Return only the replacement content for this exact slot.\n"
                + _feedback_prompt(visible_feedback)
            )
            output, evidence = await self._run_agent(
                self.agents.compiled, prompt, scope, budget
            )
            return WorkerReply(
                content=output,
                budget=budget.snapshot(),
                boundary_evidence=evidence,
            )

    async def close(self, *, budget: BudgetTracker) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if (
                self._common_checkpoint_key is not None
                and self._common_checkpoint_key in self.session._checkpoint_tokens
            ):
                self.session.drop_checkpoint(self._common_checkpoint_key)
            if (
                self._branch_checkpoint_key is not None
                and self._branch_checkpoint_key in self.session._checkpoint_tokens
            ):
                self.session.drop_checkpoint(self._branch_checkpoint_key)
            self.session.engine.close()

    async def _run_agent(
        self,
        agent: AgentPort,
        prompt: str,
        scope: _ToolContext,
        budget: BudgetTracker,
    ) -> tuple[str, BoundaryEvidence | None]:
        events: list[object] = []
        unsubscribe = self.session.on_event(
            lambda envelope: events.append(envelope.payload.get("event")),
            kinds=("Synced", "Prefill", "Token"),
        )
        pending_error: BaseException | None = None
        try:
            budget.ensure_capacity()
            try:
                result = await agent.run(
                    prompt,
                    deps=scope,
                    message_history=copy.deepcopy(self._message_history) or None,
                )
            except ResponseTerminalError as error:
                if error.reason not in ("max_tokens", "parser_error"):
                    raise
                raise ModelResponseFailure(error.reason) from error
        except BaseException as error:
            pending_error = error
            raise
        finally:
            unsubscribe()
            try:
                self._record_usage(events, budget)
            except BudgetExhausted:
                # Preserve the cause so callers roll failed transactions back.
                # Usage is already charged; capacity is checked after rollback.
                if pending_error is None:
                    raise
        output = result.output
        if not isinstance(output, str):
            raise WorkerAdapterError("Pydantic AI agent did not return text output.")
        self._message_history = copy.deepcopy(result.all_messages())
        if not self._last_sync_events:
            raise WorkerAdapterError(
                "No native synchronization telemetry was observed."
            )
        return output, None

    def _record_usage(self, events: list[object], budget: BudgetTracker) -> None:
        sync_events = tuple(event for event in events if isinstance(event, Synced))
        self._last_sync_events = sync_events
        tokens = sum(event.plan.reused + event.prefilled for event in sync_events)
        tokens += sum(isinstance(event, Token) for event in events)
        exhausted: BudgetExhausted | None = None
        for _ in sync_events:
            try:
                budget.record_model_call()
            except BudgetExhausted as error:
                exhausted = error
        try:
            budget.record_tokens(tokens)
        except BudgetExhausted as error:
            exhausted = error
        if exhausted is not None:
            raise exhausted

    def _capture_boundary(self, budget: BudgetTracker) -> WorkerBoundary:
        tokens = tuple(self.session.transcript.tokens)
        if self.session.ctx_used != len(tokens):
            events = tuple(self.session._job_events(SyncJob(tokens)))
            synced = next(
                (event for event in events if isinstance(event, Synced)), None
            )
            if synced is None or synced.pos != len(tokens):
                raise WorkerAdapterError(
                    "Could not sync the complete checkpoint prefix."
                )
            budget.record_tokens(synced.prefilled)
            self._last_sync_events += (synced,)
        key = f"{self.session.id}:{uuid4().hex}"
        checkpoint = self.session.checkpoint(key)
        if not isinstance(checkpoint, Checkpointed):
            raise WorkerAdapterError("DS4 did not return a checkpoint confirmation.")
        if checkpoint.tokens != len(tokens):
            raise WorkerAdapterError(
                "Checkpoint token count differs from the transcript."
            )
        if self._common_checkpoint_key is None:
            self._common_checkpoint_key = key
        else:
            if (
                self._branch_checkpoint_key is not None
                and self._branch_checkpoint_key in self.session._checkpoint_tokens
            ):
                self.session.drop_checkpoint(self._branch_checkpoint_key)
            self._branch_checkpoint_key = key
        tokens = tuple(self.session.transcript.tokens)
        segments = tuple(
            _segment_provenance(segment) for segment in self.session.transcript.segments
        )
        state = _BoundaryState(
            checkpoint_key=key,
            transcript_tokens=tokens,
            message_history=tuple(copy.deepcopy(self._message_history)),
            binder_segments=segments,
            rng_state=int(self.session._rng.state.value),
            session_id=self._session_owner_id,
        )
        native_events = (
            tuple(_sync_event_text(event) for event in self._last_sync_events)
            + tuple(f"ContextRetry:{reason}" for reason in self._context_failures)
            + (f"Checkpointed:{checkpoint.tokens}:{checkpoint.bytes}",)
        )
        evidence = BoundaryEvidence(
            model_id=self.model_id,
            model_revision=self.model_revision,
            runtime_revision=self.runtime_revision,
            tokenizer_revision=self.tokenizer_revision,
            checkpoint_key=key,
            token_count=checkpoint.tokens,
            rng_state_sha256=_sha256(str(state.rng_state).encode()),
            host_history_sha256=_sha256(_message_bytes(state.message_history)),
            binder_provenance_sha256=_sha256(_segment_bytes(state.binder_segments)),
            native_sync_events=native_events,
            reused_tokens=sum(event.plan.reused for event in self._last_sync_events),
            prefilled_tokens=sum(event.prefilled for event in self._last_sync_events),
        )
        return WorkerBoundary(opaque_token=state, evidence=evidence)

    def _tool_context(
        self,
        workspace: Path,
        readable_paths: tuple[str, ...],
        writable_paths: tuple[str, ...],
        gates: tuple[VisibleGateSpec, ...],
        budget: BudgetTracker,
    ) -> _ToolContext:
        return _ToolContext(
            workspace=workspace,
            readable_paths=frozenset(readable_paths),
            writable_paths=frozenset(writable_paths),
            gates={gate.gate_id: gate for gate in gates},
            gate_policy=self.gate_policy,
            budget=budget,
            max_file_read_bytes=self.max_file_read_bytes,
            gate_results=[],
            on_write=self.workspace_written,
        )

    def workspace_written(self) -> None:
        if self.think_until_first_write:
            self._thinking_suppressed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise WorkerAdapterError("DS4 worker adapter is closed.")


def _worker_prompt(
    task_id: str,
    plan: str,
    feedback: tuple[str, ...],
    *,
    visible_gates: tuple[VisibleGateSpec, ...],
) -> str:
    gate_text = "\n".join(gate.gate_id for gate in visible_gates)
    return (
        f"Task id: {task_id}\nPlan:\n{plan}\n"
        f"Visible gate IDs (the only allowed test commands):\n{gate_text}\n"
        + _feedback_prompt(feedback)
    )


def _paths_prompt(readable: tuple[str, ...], writable: tuple[str, ...]) -> str:
    text = "Readable files:\n" + "\n".join(sorted(readable)) + "\n"
    if writable:
        text += "Writable files:\n" + "\n".join(sorted(writable)) + "\n"
    return text


def _feedback_prompt(feedback: tuple[str, ...]) -> str:
    if not feedback:
        return ""
    return "Visible feedback from the previous attempt:\n" + "\n".join(feedback)


def _meta_text(metadata: object, key: str) -> str:
    if not isinstance(metadata, Mapping):
        return ""
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def _segment_provenance(segment: TranscriptSegmentPort) -> SegmentProvenance:
    metadata = segment.meta
    kind = segment.kind
    if kind == "note":
        subtype = _meta_text(metadata, "subtype")
        kind = f"system_note:{subtype}" if subtype else "system_note"
    text = metadata.get("text") if isinstance(metadata, Mapping) else None
    return SegmentProvenance(
        start=segment.start,
        end=segment.end,
        kind=kind,
        key=_meta_text(metadata, "key"),
        content_hash=_meta_text(metadata, "content_hash"),
        source=_meta_text(metadata, "source"),
        text=text if isinstance(text, str) else None,
    )


def _message_bytes(messages: tuple[ModelMessage, ...]) -> bytes:
    document = ModelMessagesTypeAdapter.dump_python(
        list(messages), mode="json", warnings=False
    )
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _segment_bytes(segments: tuple[SegmentProvenance, ...]) -> bytes:
    document = [
        {
            "start": item.start,
            "end": item.end,
            "kind": item.kind,
            "key": item.key,
            "content_hash": item.content_hash,
            "source": item.source,
            "text": item.text,
        }
        for item in segments
    ]
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sync_event_text(event: Synced) -> str:
    return (
        f"Synced:{event.plan.kind}:pos={event.pos}:reused={event.plan.reused}:"
        f"prefilled={event.prefilled}:checkpoint={event.plan.checkpoint}"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
