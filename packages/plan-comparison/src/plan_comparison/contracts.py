from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from typed_packets import SourceRoot
from typed_packets.contract import Gate, GateExpectation

type Arm = Literal["P", "C"]
type SlotKind = Literal["callable_body", "ancillary"]
type SlotOperation = Literal[
    "replace_body",
    "replace",
    "insert_before",
    "insert_after",
    "create_file",
]
type RegistrationScalar = str | int | float | bool | None
type RegistrationSetting = tuple[str, RegistrationScalar]
type AttemptStatus = Literal[
    "passed",
    "failed",
    "harness_fault",
    "blocked",
    "budget_exhausted",
    "interrupted",
]
type ArmStatus = Literal[
    "passed",
    "failed",
    "harness_fault",
    "blocked",
    "budget_exhausted",
    "interrupted",
]
type GateStatus = Literal["passed", "failed", "timed_out", "error"]
type RegistrationDirection = Literal["at_least", "at_most"]
type PairStatus = Literal[
    "completed",
    "blocked",
    "harness_fault",
    "budget_exhausted",
    "interrupted",
    "context_failed",
]
type CapabilityCheckStatus = Literal["passed", "blocked", "failed"]
type RunMode = Literal["cpu", "pilot", "deciding"]


class ModelResponseFailure(RuntimeError):
    """A model response failed and may consume the configured repair retry."""

    def __init__(self, reason: str) -> None:
        if reason not in ("max_tokens", "parser_error"):
            raise ValueError(f"Not a retryable model response reason: {reason}")
        self.reason = reason
        super().__init__(f"Model response ended with {reason}.")


class ContextPreparationFailure(ModelResponseFailure):
    """Shared context could not be prepared within its bounded retries."""

    def __init__(self, reason: str, attempts: int) -> None:
        self.attempts = attempts
        super().__init__(reason)
        self.args = (
            f"Context preparation failed after {attempts} attempts: {reason}.",
        )


@dataclass(frozen=True, slots=True)
class ByteExtent:
    start_byte: int
    end_byte: int


@dataclass(frozen=True, slots=True)
class CallableBodyExtent:
    pass


@dataclass(frozen=True, slots=True)
class StructuralExtent:
    region: Literal["body", "definition"]


@dataclass(frozen=True, slots=True)
class WholeFileExtent:
    pass


@dataclass(frozen=True, slots=True)
class CallableBodyTarget:
    qualified_name: str


@dataclass(frozen=True, slots=True)
class StructuralTarget:
    qualified_name: str


@dataclass(frozen=True, slots=True)
class TextAnchorTarget:
    anchor: str


@dataclass(frozen=True, slots=True)
class WholeFileTarget:
    pass


type SlotTarget = (
    CallableBodyTarget | StructuralTarget | TextAnchorTarget | WholeFileTarget
)
type SlotExtent = ByteExtent | CallableBodyExtent | StructuralExtent | WholeFileExtent


@dataclass(frozen=True, slots=True)
class Slot:
    slot_id: str
    path: str
    kind: SlotKind
    operation: SlotOperation
    target: SlotTarget
    extent: SlotExtent
    preimage_sha256: str | None


@dataclass(frozen=True, slots=True)
class Placement:
    placement_id: str
    path: str
    kind: Literal["imports", "declarations"]
    target: str
    position: Literal["before", "after", "start", "end"]
    anchor: str | None
    preimage_sha256: str | None


@dataclass(frozen=True, slots=True)
class RedCheck:
    path: str
    test_node: str
    expected_exception: str
    marker: str


@dataclass(frozen=True, slots=True)
class PacketExecution:
    packet_id: str
    packet_sha256: str
    slots: tuple[Slot, ...]
    placements: tuple[Placement, ...]
    red_checks: tuple[RedCheck, ...]


@dataclass(frozen=True, slots=True)
class ExecutionManifest:
    manifest_version: Literal[0]
    task_id: str
    plan_sha256: str
    packets: tuple[PacketExecution, ...]


@dataclass(frozen=True, slots=True)
class ManifestDiagnostic:
    code: str
    field: str
    message: str
    outcome: Literal["invalid", "inconclusive"] = "invalid"
    path: str | None = None
    packet_id: str | None = None


@dataclass(frozen=True, slots=True)
class PacketSource:
    packet_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class ManifestInputs:
    task_id: str
    workspace: Path
    plan_path: Path
    packet_sources: tuple[PacketSource, ...]


@dataclass(frozen=True, slots=True)
class PacketDigest:
    packet_id: str
    packet_sha256: str


@dataclass(frozen=True, slots=True)
class RegistrationTask:
    task_id: str
    plan_sha256: str
    manifest_sha256: str
    packets: tuple[PacketDigest, ...]


@dataclass(frozen=True, slots=True)
class TaskSeedPair:
    task_id: str
    seed: int
    arm_order: tuple[Arm, Arm]


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    wall_seconds: int
    tokens: int
    model_calls: int


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    max_retries: int
    description: str


@dataclass(frozen=True, slots=True)
class ScoringProcedures:
    behavior: str
    style_mechanical: str
    style_human: str
    timing: str


@dataclass(frozen=True, slots=True)
class DecisionRule:
    metric: str
    direction: RegistrationDirection
    threshold: int | float
    unit: str


@dataclass(frozen=True, slots=True)
class Registration:
    registration_version: Literal[0]
    experiment_id: str
    model_id: str
    model_revision: str
    runtime_revision: str
    tokenizer_revision: str
    tasks: tuple[RegistrationTask, ...]
    task_seed_pairs: tuple[TaskSeedPair, ...]
    tool_policy_sha256: str
    sampler_settings: tuple[RegistrationSetting, ...]
    thinking_settings: tuple[RegistrationSetting, ...]
    budgets: BudgetLimits
    p_repair_policy: RepairPolicy
    c_retry_limit: int
    scoring: ScoringProcedures
    decision_rule: DecisionRule


@dataclass(frozen=True, slots=True)
class RegisteredTaskArtifacts:
    task_id: str
    plan_sha256: str
    manifest_sha256: str
    packets: tuple[PacketDigest, ...]


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    elapsed_seconds: float
    tokens: int
    model_calls: int


class BudgetTracker(Protocol):
    def snapshot(self) -> BudgetSnapshot: ...

    def ensure_capacity(self) -> None: ...

    def record_model_call(self) -> None: ...

    def record_tokens(self, count: int) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerCapabilities:
    native_checkpoint: bool
    token_reuse: bool
    actual_prefill_counts: bool
    rng_restore: bool
    host_history_restore: bool
    binder_restore: bool
    serial_tools: bool
    safe_cancellation: bool
    evidence: tuple[str, ...]
    runtime_kind: Literal["scripted", "live"] = "scripted"

    @property
    def supports_paired_draws(self) -> bool:
        return all(
            (
                self.native_checkpoint,
                self.token_reuse,
                self.actual_prefill_counts,
                self.rng_restore,
                self.host_history_restore,
                self.binder_restore,
                self.serial_tools,
                self.safe_cancellation,
            )
        )


@dataclass(frozen=True, slots=True)
class BoundaryEvidence:
    model_id: str
    model_revision: str
    runtime_revision: str
    tokenizer_revision: str
    checkpoint_key: str
    token_count: int
    rng_state_sha256: str
    host_history_sha256: str
    binder_provenance_sha256: str
    native_sync_events: tuple[str, ...]
    reused_tokens: int
    prefilled_tokens: int


@dataclass(frozen=True, slots=True)
class WorkerBoundary:
    opaque_token: object
    evidence: BoundaryEvidence


@dataclass(frozen=True, slots=True)
class WorkerReply:
    content: str
    budget: BudgetSnapshot
    boundary_evidence: BoundaryEvidence | None
    visible_gate_results: tuple["GateResult", ...] = ()


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: GateStatus
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    output_excerpt: str
    output_truncated: bool
    verified_red_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VisibleGateSpec:
    gate_id: str
    gate: Gate
    expectation: GateExpectation


class VisibleGateRunner(Protocol):
    async def run_gate(self, gate_id: str) -> GateResult: ...


@dataclass(frozen=True, slots=True)
class AttemptTiming:
    preparation_seconds: float
    generation_seconds: float
    gate_seconds: float
    repair_seconds: float
    end_to_end_seconds: float


@dataclass(frozen=True, slots=True)
class HarnessFault:
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    task_id: str
    arm: Arm
    packet_id: str
    attempt_number: int
    status: AttemptStatus
    started_at: str
    completed_at: str
    input_sha256: str
    code_delta_sha256: str | None
    gates: tuple[GateResult, ...]
    budget: BudgetSnapshot
    boundary_evidence: BoundaryEvidence | None
    visible_feedback: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    timing: AttemptTiming = AttemptTiming(0.0, 0.0, 0.0, 0.0, 0.0)
    harness_fault: HarnessFault | None = None


@dataclass(frozen=True, slots=True)
class HostGrade:
    status: Literal["pass", "fail", "error", "not_applicable"]
    result_sha256: str
    artifact_ref: str


@dataclass(frozen=True, slots=True)
class PublicTaskInputs:
    task_id: str
    workspace: Path
    plan_path: Path
    manifest_path: Path
    packet_paths: tuple[PacketSource, ...]
    allowed_read_paths: tuple[str, ...]
    worker_writable_paths: tuple[str, ...]
    source_roots: tuple[SourceRoot, ...]


@dataclass(frozen=True, slots=True)
class ArmResult:
    task_id: str
    arm: Arm
    status: ArmStatus
    workspace_sha256: str | None
    attempts: tuple[AttemptRecord, ...]
    host_grade: HostGrade | None
    duration_seconds: float = 0.0
    harness_fault: HarnessFault | None = None


@dataclass(frozen=True, slots=True)
class PairResult:
    pair_id: str
    task_id: str
    seed: int
    arm_order: tuple[Arm, Arm]
    status: PairStatus
    capabilities: WorkerCapabilities | None
    common_boundary: BoundaryEvidence | None
    shared_budget: BudgetSnapshot
    arms: tuple[ArmResult, ...]
    live_authorization_ref: str | None = None
    disposable_policy_ref: str | None = None
    registration_diagnostics: tuple[ManifestDiagnostic, ...] = ()
    harness_fault: HarnessFault | None = None


@dataclass(frozen=True, slots=True)
class CapabilityCheckRecord:
    capability_id: str
    task_id: str
    status: CapabilityCheckStatus
    live_authorization_ref: str
    disposable_policy_ref: str
    capabilities: WorkerCapabilities | None
    initial_boundary: BoundaryEvidence | None
    restored_boundary: BoundaryEvidence | None
    budget: BudgetSnapshot
    diagnostics: tuple[str, ...]


class WorkerPort(Protocol):
    def workspace_written(self) -> None:
        """Notify the worker after a successful host-applied workspace edit."""
        ...

    async def capabilities(self, *, budget: BudgetTracker) -> WorkerCapabilities: ...

    async def capture_boundary(
        self,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        budget: BudgetTracker,
    ) -> WorkerBoundary: ...

    async def restore_boundary(
        self, boundary: WorkerBoundary, *, budget: BudgetTracker
    ) -> None: ...

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
    ) -> WorkerReply: ...

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
    ) -> WorkerReply: ...

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
    ) -> WorkerReply: ...

    async def close(self, *, budget: BudgetTracker) -> None: ...


class ReferenceTaskPort(Protocol):
    def public_inputs(self, task_id: str) -> PublicTaskInputs: ...

    def create_workspace(self, task_id: str, arm: Arm, seed: int) -> Path: ...

    def grade_protected(
        self, task_id: str, arm: Arm, seed: int, workspace: Path
    ) -> HostGrade: ...
