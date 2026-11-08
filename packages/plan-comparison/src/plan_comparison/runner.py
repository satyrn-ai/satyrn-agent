import asyncio
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from typed_packets import (
    Packet,
    PacketDecodeError,
    ValidationContext,
    build_index,
    decode_packet,
    validate_packet,
)
from typed_packets.contract import Gate

from plan_comparison.budget import BudgetExhausted, MonotonicBudget
from plan_comparison.contracts import (
    Arm,
    ArmResult,
    AttemptRecord,
    AttemptTiming,
    BoundaryEvidence,
    BudgetLimits,
    BudgetSnapshot,
    CallableBodyTarget,
    CapabilityCheckRecord,
    ExecutionManifest,
    GateResult,
    HostGrade,
    ManifestDiagnostic,
    ManifestInputs,
    PacketDigest,
    PairResult,
    PublicTaskInputs,
    RedCheck,
    ReferenceTaskPort,
    RegisteredTaskArtifacts,
    Registration,
    RepairPolicy,
    RunMode,
    TaskSeedPair,
    VisibleGateSpec,
    WorkerBoundary,
    WorkerCapabilities,
    WorkerPort,
    WorkerReply,
)
from plan_comparison.gates import GatePolicy, run_gate
from plan_comparison.manifest import (
    ManifestDecodeError,
    decode_execution_manifest,
    decode_registration,
    sha256_bytes,
    validate_manifest_artifacts,
    validate_packet_execution,
    validate_registration_artifacts,
)
from plan_comparison.prepare import (
    PreparationError,
    install_tests,
    prepare_packet,
)
from plan_comparison.records import RecordStoreError, RunStore
from plan_comparison.reports import ExperimentReport, StyleEvidence, build_report
from plan_comparison.slots import SlotEditError, apply_slot_edit
from plan_comparison.workspace import (
    WorkspaceError,
    WorkspaceSnapshot,
    restore_workspace,
    snapshot_workspace,
    workspace_sha256,
)


class RunnerHarnessFault(RuntimeError):
    pass


type ArmRunStatus = Literal[
    "passed", "failed", "harness_fault", "budget_exhausted", "interrupted"
]


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    mode: RunMode
    budgets: BudgetLimits
    p_repair_policy: RepairPolicy
    c_retry_limit: int
    gate_policy: GatePolicy
    max_feedback_characters: int = 12000
    live_authorization_ref: str | None = None
    disposable_policy_ref: str | None = None

    def __post_init__(self) -> None:
        if self.c_retry_limit < 0 or self.c_retry_limit > 2:
            raise ValueError("Compiled retry limit must be between zero and two.")
        if self.p_repair_policy.max_retries < 0:
            raise ValueError("Prose retry limit cannot be negative.")
        if self.max_feedback_characters < 1:
            raise ValueError("Feedback character bound must be positive.")


class ExperimentRunner:
    def __init__(self, config: RunnerConfig, store: RunStore) -> None:
        self.config = config
        self.store = store

    async def check_capabilities(
        self,
        worker: WorkerPort,
        *,
        task_id: str,
        plan: str,
        workspace: Path,
        allowed_read_paths: tuple[str, ...],
        authorization_ref: str | None = None,
        disposable_policy_ref: str | None = None,
        budget: MonotonicBudget | None = None,
    ) -> CapabilityCheckRecord:
        if (
            authorization_ref is None
            or not authorization_ref.strip()
            or disposable_policy_ref is None
            or not disposable_policy_ref.strip()
        ):
            raise RunnerHarnessFault(
                "Model-backed capability checks require live and "
                "disposable-policy references."
            )
        ledger = budget or MonotonicBudget(self.config.budgets)
        capability: WorkerCapabilities | None = None
        initial: WorkerBoundary | None = None
        restored: WorkerBoundary | None = None
        diagnostics: list[str] = []
        status: Literal["passed", "blocked", "failed"] = "failed"
        try:
            ledger.ensure_capacity()
            capability = await worker.capabilities(budget=ledger)
            unsupported = _unsupported_capabilities(capability)
            if unsupported:
                status = "blocked"
                diagnostics.extend(unsupported)
            else:
                initial = await worker.capture_boundary(
                    task_id=task_id,
                    plan=plan,
                    workspace=workspace,
                    allowed_read_paths=allowed_read_paths,
                    budget=ledger,
                )
                boundary_problems = _boundary_evidence_problems(initial, None)
                if boundary_problems:
                    diagnostics.extend(boundary_problems)
                    status = "failed"
                else:
                    await worker.restore_boundary(initial, budget=ledger)
                    restored = await worker.capture_boundary(
                        task_id=task_id,
                        plan=plan,
                        workspace=workspace,
                        allowed_read_paths=allowed_read_paths,
                        budget=ledger,
                    )
                    if not _same_boundary_state(initial.evidence, restored.evidence):
                        diagnostics.append(
                            "Boundary state hashes differ after native restore."
                        )
                        status = "failed"
                    else:
                        status = "passed"
                ledger.ensure_capacity()
        except BudgetExhausted as error:
            diagnostics.append(str(error))
            status = "failed"
        except asyncio.CancelledError:
            diagnostics.append("Capability transaction was interrupted.")
            status = "failed"
        except Exception as error:
            diagnostics.append(f"Capability transaction failed: {error}")
            status = "failed"
        record = CapabilityCheckRecord(
            capability_id=uuid.uuid4().hex,
            task_id=task_id,
            status=status,
            live_authorization_ref=authorization_ref,
            disposable_policy_ref=disposable_policy_ref,
            capabilities=capability,
            initial_boundary=initial.evidence if initial else None,
            restored_boundary=restored.evidence if restored else None,
            budget=ledger.snapshot(),
            diagnostics=tuple(diagnostics),
        )
        try:
            self.store.write_capability(record)
        except RecordStoreError as error:
            raise RunnerHarnessFault(
                f"Capability record persistence failed: {error}"
            ) from error
        return record

    async def run_sweep(
        self,
        inputs_by_task: Mapping[str, PublicTaskInputs],
        worker_factory: Callable[[PublicTaskInputs, int], WorkerPort],
        task_port: ReferenceTaskPort,
        schedule: tuple[TaskSeedPair, ...],
        *,
        experiment_id: str,
        registration_document: bytes | None = None,
        mechanical_style: tuple[StyleEvidence, ...] = (),
        human_style: tuple[StyleEvidence, ...] = (),
        decision_value: float | None = None,
    ) -> ExperimentReport:
        diagnostics: list[ManifestDiagnostic] = []
        registration: Registration | None = None
        registration_sha256: str | None = None
        if self.config.mode in ("pilot", "deciding") and (
            self.config.live_authorization_ref is None
            or not self.config.live_authorization_ref.strip()
            or self.config.disposable_policy_ref is None
            or not self.config.disposable_policy_ref.strip()
        ):
            diagnostics.append(
                self._diagnostic(
                    "runner.live_authorization_missing",
                    "Live sweeps require live and disposable-policy references.",
                    field="/live_authorization_ref",
                )
            )
        if not schedule:
            diagnostics.append(
                self._diagnostic(
                    "runner.empty_schedule",
                    "Sweep schedule must contain at least one task/seed pair.",
                    field="/schedule",
                )
            )
        scheduled_keys = [(item.task_id, item.seed) for item in schedule]
        if len(set(scheduled_keys)) != len(scheduled_keys):
            diagnostics.append(
                self._diagnostic(
                    "runner.duplicate_schedule_pair",
                    "Sweep schedule contains a duplicate task/seed pair.",
                    field="/schedule",
                )
            )
        if self.config.mode == "pilot" and any(
            item.task_id not in {"E1", "E2", "E3"} for item in schedule
        ):
            diagnostics.append(
                self._diagnostic(
                    "runner.pilot_task_scope",
                    "Public pilot schedules may contain only E1-E3.",
                    field="/schedule",
                )
            )
        if self.config.mode == "deciding":
            if registration_document is None:
                diagnostics.append(
                    self._diagnostic(
                        "registration.missing",
                        "Deciding sweeps require a complete frozen registration.",
                        field="/registration",
                    )
                )
            else:
                try:
                    registration = decode_registration(
                        registration_document.decode("utf-8")
                    )
                    registration_sha256 = sha256_bytes(registration_document)
                except (UnicodeDecodeError, ManifestDecodeError) as error:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.invalid",
                            str(error),
                            field="/registration",
                        )
                    )
            if registration is not None:
                if experiment_id != registration.experiment_id:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.experiment_id",
                            "Sweep experiment ID differs from the frozen registration.",
                            field="/experiment_id",
                        )
                    )
                if schedule != registration.task_seed_pairs:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.schedule_mismatch",
                            "Deciding schedule must exactly match registered "
                            "task/seed/arm order.",
                            field="/schedule",
                        )
                    )
                if registration.budgets != self.config.budgets:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.budget_mismatch",
                            "Runner budgets differ from the frozen registration.",
                            field="/budgets",
                        )
                    )
                if registration.p_repair_policy != self.config.p_repair_policy:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.p_repair_mismatch",
                            "Prose repair policy differs from the frozen registration.",
                            field="/p_repair_policy",
                        )
                    )
                if registration.c_retry_limit != self.config.c_retry_limit:
                    diagnostics.append(
                        self._diagnostic(
                            "registration.c_retry_mismatch",
                            "Compiled retry limit differs from the frozen "
                            "registration.",
                            field="/c_retry_limit",
                        )
                    )
        task_ids = tuple(dict.fromkeys(item.task_id for item in schedule))
        prepared_inputs: dict[str, PublicTaskInputs] = {}
        actuals: list[RegisteredTaskArtifacts] = []
        for task_id in task_ids:
            inputs = inputs_by_task.get(task_id)
            if inputs is None:
                diagnostics.append(
                    self._diagnostic(
                        "runner.task_inputs_missing",
                        f"No trusted task inputs are configured for {task_id}.",
                        field="/inputs",
                    )
                )
                continue
            if inputs.task_id != task_id:
                diagnostics.append(
                    self._diagnostic(
                        "runner.task_inputs_mismatch",
                        f"Task input key {task_id!r} contains ID {inputs.task_id!r}.",
                        field="/inputs",
                    )
                )
                continue
            prepared_inputs[task_id] = inputs
            task_diagnostics, task_artifacts = self._sweep_task_preflight(inputs)
            diagnostics.extend(task_diagnostics)
            if task_artifacts is not None:
                actuals.append(task_artifacts)
        if self.config.mode == "deciding" and registration is not None:
            diagnostics.extend(
                validate_registration_artifacts(registration, tuple(actuals))
            )
        if diagnostics:
            report = build_report(
                (),
                experiment_id=experiment_id,
                mechanical_style=mechanical_style,
                human_style=human_style,
                decision_rule=registration.decision_rule if registration else None,
                status="blocked",
                registration_sha256=registration_sha256,
                preflight_diagnostics=tuple(
                    f"{item.code}:{item.field}:{item.message}" for item in diagnostics
                ),
            )
            self._persist_report(report)
            return report

        pairs: list[PairResult] = []
        for pair in schedule:
            inputs = prepared_inputs[pair.task_id]
            try:
                worker = worker_factory(inputs, pair.seed)
            except Exception as error:
                diagnostics.append(
                    self._diagnostic(
                        "runner.worker_factory",
                        str(error),
                        field=f"/schedule/{pair.task_id}/{pair.seed}",
                    )
                )
                break
            result = await self.run_pair(
                inputs,
                worker,
                task_port,
                seed=pair.seed,
                arm_order=pair.arm_order,
                registration=registration,
                registered_artifacts=tuple(actuals),
            )
            pairs.append(result)
            if result.status in ("blocked", "harness_fault", "interrupted"):
                break
        if diagnostics:
            report_status: Literal["completed", "blocked", "harness_fault"] = (
                "harness_fault"
            )
        else:
            report_status = None
        report = build_report(
            tuple(pairs),
            experiment_id=experiment_id,
            mechanical_style=mechanical_style,
            human_style=human_style,
            decision_rule=registration.decision_rule if registration else None,
            decision_value=decision_value if not diagnostics else None,
            status=report_status,
            registration_sha256=registration_sha256,
            preflight_diagnostics=tuple(
                f"{item.code}:{item.field}:{item.message}" for item in diagnostics
            ),
        )
        self._persist_report(report)
        return report

    def _sweep_task_preflight(
        self, inputs: PublicTaskInputs
    ) -> tuple[tuple[ManifestDiagnostic, ...], RegisteredTaskArtifacts | None]:
        diagnostics: list[ManifestDiagnostic] = []
        try:
            plan_bytes = inputs.plan_path.read_bytes()
            manifest_bytes = inputs.manifest_path.read_bytes()
            manifest = decode_execution_manifest(manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ManifestDecodeError) as error:
            return (
                (
                    self._diagnostic(
                        "runner.task_artifact",
                        str(error),
                        field=f"/inputs/{inputs.task_id}",
                    ),
                ),
                None,
            )
        packet_sources = tuple(inputs.packet_paths)
        manifest_inputs = ManifestInputs(
            task_id=inputs.task_id,
            workspace=inputs.workspace,
            plan_path=inputs.plan_path,
            packet_sources=packet_sources,
        )
        diagnostics.extend(
            validate_manifest_artifacts(
                manifest, manifest_inputs, validate_workspace=False
            )
        )
        try:
            snapshot_workspace(inputs.workspace)
            packets = self._load_packets(inputs, manifest)
        except (
            OSError,
            UnicodeDecodeError,
            PacketDecodeError,
            WorkspaceError,
        ) as error:
            diagnostics.append(
                self._diagnostic(
                    "runner.task_workspace",
                    str(error),
                    field=f"/inputs/{inputs.task_id}/workspace",
                )
            )
            return tuple(diagnostics), None
        diagnostics.extend(_task_access_diagnostics(inputs, manifest, packets))
        if manifest.packets:
            context = ValidationContext(
                workspace=inputs.workspace,
                roots=inputs.source_roots,
            )
            packet = packets[manifest.packets[0].packet_id][1]
            report = validate_packet(packet, context, build_index(context))
            if not report.ready:
                diagnostics.extend(
                    ManifestDiagnostic(
                        code=item.code,
                        field=f"/packets/0{item.field}",
                        message=item.message,
                        outcome=item.outcome,
                        path=item.path,
                        packet_id=manifest.packets[0].packet_id,
                    )
                    for item in report.diagnostics
                )
            diagnostics.extend(
                validate_packet_execution(packet, manifest.packets[0], inputs.workspace)
            )
        if diagnostics:
            return tuple(diagnostics), None
        packet_hashes = tuple(
            PacketDigest(packet_id=item.packet_id, packet_sha256=item.packet_sha256)
            for item in manifest.packets
        )
        return (), RegisteredTaskArtifacts(
            task_id=inputs.task_id,
            plan_sha256=sha256_bytes(plan_bytes),
            manifest_sha256=sha256_bytes(manifest_bytes),
            packets=packet_hashes,
        )

    def preflight_task_inputs(
        self, inputs: PublicTaskInputs
    ) -> tuple[ManifestDiagnostic, ...]:
        diagnostics, _ = self._sweep_task_preflight(inputs)
        return diagnostics

    def _persist_report(self, report: ExperimentReport) -> None:
        try:
            self.store.write_report(uuid.uuid4().hex, report)
        except RecordStoreError as error:
            raise RunnerHarnessFault(
                f"Report record persistence failed: {error}"
            ) from error

    async def run_pair(
        self,
        inputs: PublicTaskInputs,
        worker: WorkerPort,
        task_port: ReferenceTaskPort,
        *,
        seed: int,
        arm_order: tuple[Arm, Arm] = ("P", "C"),
        registration: Registration | None = None,
        registered_artifacts: tuple[RegisteredTaskArtifacts, ...] = (),
    ) -> PairResult:
        if self.config.mode in ("pilot", "deciding") and (
            self.config.live_authorization_ref is None
            or not self.config.live_authorization_ref.strip()
            or self.config.disposable_policy_ref is None
            or not self.config.disposable_policy_ref.strip()
        ):
            return self._empty_pair(
                inputs.task_id,
                seed,
                uuid.uuid4().hex,
                arm_order,
                "blocked",
                BudgetSnapshot(elapsed_seconds=0.0, tokens=0, model_calls=0),
                diagnostic=self._diagnostic(
                    "runner.live_authorization_missing",
                    "Pilot and deciding runs require live and "
                    "disposable-policy references.",
                    field="/live_authorization_ref",
                ),
            )
        if self.config.mode == "pilot" and inputs.task_id not in {"E1", "E2", "E3"}:
            return self._empty_pair(
                inputs.task_id,
                seed,
                uuid.uuid4().hex,
                arm_order,
                "blocked",
                BudgetSnapshot(elapsed_seconds=0.0, tokens=0, model_calls=0),
                diagnostic=self._diagnostic(
                    "runner.pilot_task_scope",
                    "Public pilot runs may use only E1-E3 task slices.",
                    field="/task_id",
                ),
            )
        pair_id = uuid.uuid4().hex
        shared_budget = MonotonicBudget(self.config.budgets)
        try:
            result = await self._run_pair(
                inputs,
                worker,
                task_port,
                pair_id=pair_id,
                seed=seed,
                arm_order=arm_order,
                shared_budget=shared_budget,
                registration=registration,
                registered_artifacts=registered_artifacts,
            )
        except asyncio.CancelledError:
            result = self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "interrupted",
                shared_budget.snapshot(),
            )
        except Exception as error:
            result = self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                diagnostic=self._diagnostic(
                    "runner.failure", str(error), field="/runner"
                ),
            )
        try:
            await worker.close(budget=shared_budget)
        except Exception as error:
            result = replace(
                result,
                status="harness_fault",
                registration_diagnostics=result.registration_diagnostics
                + (self._diagnostic("worker.close", str(error), field="/worker"),),
            )
        try:
            self.store.write_pair(result)
        except RecordStoreError as error:
            return replace(
                result,
                status="harness_fault",
                registration_diagnostics=result.registration_diagnostics
                + (
                    self._diagnostic(
                        "record.persist_pair", str(error), field="/records"
                    ),
                ),
            )
        return result

    async def _run_pair(
        self,
        inputs: PublicTaskInputs,
        worker: WorkerPort,
        task_port: ReferenceTaskPort,
        *,
        pair_id: str,
        seed: int,
        arm_order: tuple[Arm, Arm],
        shared_budget: MonotonicBudget,
        registration: Registration | None,
        registered_artifacts: tuple[RegisteredTaskArtifacts, ...],
    ) -> PairResult:
        if len(arm_order) != 2 or set(arm_order) != {"P", "C"}:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "blocked",
                shared_budget.snapshot(),
                diagnostic=self._diagnostic(
                    "runner.arm_order",
                    "Both arms must appear exactly once.",
                    field="/arm_order",
                ),
            )
        try:
            plan_bytes = inputs.plan_path.read_bytes()
            manifest_bytes = inputs.manifest_path.read_bytes()
            plan = plan_bytes.decode("utf-8")
            manifest = decode_execution_manifest(manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ManifestDecodeError) as error:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                diagnostic=self._diagnostic(
                    "runner.input_invalid", str(error), field="/inputs"
                ),
            )
        if manifest.task_id != inputs.task_id:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                diagnostic=self._diagnostic(
                    "runner.task_mismatch",
                    "Manifest and task adapter IDs differ.",
                    field="/task_id",
                ),
            )
        packet_inputs = tuple(inputs.packet_paths)
        manifest_inputs = ManifestInputs(
            task_id=inputs.task_id,
            workspace=inputs.workspace,
            plan_path=inputs.plan_path,
            packet_sources=packet_inputs,
        )
        diagnostics = list(
            validate_manifest_artifacts(
                manifest, manifest_inputs, validate_workspace=False
            )
        )
        if not diagnostics:
            try:
                on_disk = decode_execution_manifest(manifest_bytes.decode("utf-8"))
                if on_disk != manifest:
                    diagnostics.append(
                        self._diagnostic(
                            "runner.manifest_changed",
                            "Loaded manifest differs from its frozen artifact.",
                            field="/manifest",
                        )
                    )
            except ManifestDecodeError as error:
                diagnostics.append(
                    self._diagnostic(
                        "runner.manifest_invalid", str(error), field="/manifest"
                    )
                )
        if self.config.mode == "deciding":
            diagnostics.extend(
                self._registration_diagnostics(
                    inputs,
                    manifest,
                    plan_bytes,
                    manifest_bytes,
                    registration,
                    registered_artifacts,
                    seed,
                    arm_order,
                )
            )
        if diagnostics:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "blocked" if self.config.mode == "deciding" else "harness_fault",
                shared_budget.snapshot(),
                diagnostics=tuple(diagnostics),
            )
        try:
            initial_snapshot = snapshot_workspace(inputs.workspace)
            packets = self._load_packets(inputs, manifest)
        except (
            WorkspaceError,
            OSError,
            UnicodeDecodeError,
            PacketDecodeError,
        ) as error:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                diagnostic=self._diagnostic(
                    "runner.packet_load", str(error), field="/packets"
                ),
            )
        access_diagnostics = _task_access_diagnostics(inputs, manifest, packets)
        if access_diagnostics:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                diagnostics=access_diagnostics,
            )
        readiness = _packet_readiness_diagnostics(inputs, manifest, packets)
        if readiness:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "blocked",
                shared_budget.snapshot(),
                diagnostics=readiness,
            )
        capabilities: WorkerCapabilities | None = None
        boundary: WorkerBoundary | None = None
        try:
            shared_budget.ensure_capacity()
            capabilities = await worker.capabilities(budget=shared_budget)
            if (
                self.config.mode == "cpu" and capabilities.runtime_kind != "scripted"
            ) or (self.config.mode != "cpu" and capabilities.runtime_kind != "live"):
                blocked_arms = tuple(
                    self._empty_arm(inputs.task_id, arm, "blocked") for arm in arm_order
                )
                return PairResult(
                    pair_id=pair_id,
                    task_id=inputs.task_id,
                    seed=seed,
                    arm_order=arm_order,
                    status="blocked",
                    capabilities=capabilities,
                    common_boundary=None,
                    shared_budget=shared_budget.snapshot(),
                    arms=blocked_arms,
                    live_authorization_ref=self.config.live_authorization_ref,
                    disposable_policy_ref=self.config.disposable_policy_ref,
                    registration_diagnostics=(
                        self._diagnostic(
                            "runner.runtime_mode_mismatch",
                            "Worker runtime kind does not match the run mode.",
                            field="/mode",
                        ),
                    ),
                )
            if not capabilities.supports_paired_draws or not any(
                evidence.strip() for evidence in capabilities.evidence
            ):
                blocked_arms = tuple(
                    self._empty_arm(inputs.task_id, arm, "blocked") for arm in arm_order
                )
                return PairResult(
                    pair_id=pair_id,
                    task_id=inputs.task_id,
                    seed=seed,
                    arm_order=arm_order,
                    status="blocked",
                    capabilities=capabilities,
                    common_boundary=None,
                    shared_budget=shared_budget.snapshot(),
                    arms=blocked_arms,
                    live_authorization_ref=self.config.live_authorization_ref,
                    disposable_policy_ref=self.config.disposable_policy_ref,
                )
            boundary = await worker.capture_boundary(
                task_id=inputs.task_id,
                plan=plan,
                workspace=inputs.workspace,
                allowed_read_paths=inputs.allowed_read_paths,
                budget=shared_budget,
            )
            boundary_problems = _boundary_evidence_problems(boundary, registration)
            if boundary_problems:
                return self._empty_pair(
                    inputs.task_id,
                    seed,
                    pair_id,
                    arm_order,
                    "blocked",
                    shared_budget.snapshot(),
                    capabilities=capabilities,
                    boundary=boundary,
                    diagnostics=tuple(
                        self._diagnostic(
                            "runner.boundary_evidence",
                            message,
                            field="/boundary",
                        )
                        for message in boundary_problems
                    ),
                )
            shared_budget.ensure_capacity()
        except BudgetExhausted as error:
            blocked_arms = tuple(
                self._empty_arm(inputs.task_id, arm, "budget_exhausted")
                for arm in arm_order
            )
            return PairResult(
                pair_id=pair_id,
                task_id=inputs.task_id,
                seed=seed,
                arm_order=arm_order,
                status="budget_exhausted",
                capabilities=capabilities,
                common_boundary=boundary.evidence if boundary else None,
                shared_budget=shared_budget.snapshot(),
                arms=blocked_arms,
                live_authorization_ref=self.config.live_authorization_ref,
                disposable_policy_ref=self.config.disposable_policy_ref,
                registration_diagnostics=(
                    self._diagnostic(
                        "runner.shared_budget", str(error), field="/budget"
                    ),
                ),
            )
        except asyncio.CancelledError:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "interrupted",
                shared_budget.snapshot(),
                capabilities=capabilities,
                boundary=boundary,
            )
        except Exception as error:
            return self._empty_pair(
                inputs.task_id,
                seed,
                pair_id,
                arm_order,
                "harness_fault",
                shared_budget.snapshot(),
                capabilities=capabilities,
                boundary=boundary,
                diagnostic=self._diagnostic(
                    "runner.common_boundary", str(error), field="/boundary"
                ),
            )

        assert capabilities is not None
        assert boundary is not None
        base_hash = workspace_sha256(initial_snapshot)
        arms: list[ArmResult] = []
        for arm in arm_order:
            try:
                arm_result = await self._run_arm(
                    inputs,
                    manifest,
                    packets,
                    plan,
                    seed,
                    arm,
                    boundary,
                    base_hash,
                    worker,
                    task_port,
                )
            except asyncio.CancelledError:
                arm_result = self._empty_arm(inputs.task_id, arm, "interrupted")
            arms.append(arm_result)
            if arm_result.status in ("harness_fault", "interrupted"):
                break
        statuses = {arm.status for arm in arms}
        if "harness_fault" in statuses:
            pair_status = "harness_fault"
        elif "interrupted" in statuses:
            pair_status = "interrupted"
        elif "budget_exhausted" in statuses:
            pair_status = "budget_exhausted"
        else:
            pair_status = "completed"
        return PairResult(
            pair_id=pair_id,
            task_id=inputs.task_id,
            seed=seed,
            arm_order=arm_order,
            status=pair_status,
            capabilities=capabilities,
            common_boundary=boundary.evidence,
            shared_budget=shared_budget.snapshot(),
            arms=tuple(arms),
            live_authorization_ref=self.config.live_authorization_ref,
            disposable_policy_ref=self.config.disposable_policy_ref,
        )

    def _registration_diagnostics(
        self,
        inputs: PublicTaskInputs,
        manifest: ExecutionManifest,
        plan_bytes: bytes,
        manifest_bytes: bytes,
        registration: Registration | None,
        registered_artifacts: tuple[RegisteredTaskArtifacts, ...],
        seed: int,
        arm_order: tuple[Arm, Arm],
    ) -> tuple[ManifestDiagnostic, ...]:
        if registration is None:
            return (
                self._diagnostic(
                    "registration.missing",
                    "Deciding execution requires a complete frozen registration.",
                    field="/registration",
                ),
            )
        diagnostics = list(
            validate_registration_artifacts(registration, registered_artifacts)
        )
        if registration.budgets != self.config.budgets:
            diagnostics.append(
                self._diagnostic(
                    "registration.budget_mismatch",
                    "Runner budgets differ from the frozen registration.",
                    field="/budgets",
                )
            )
        if registration.p_repair_policy != self.config.p_repair_policy:
            diagnostics.append(
                self._diagnostic(
                    "registration.p_repair_mismatch",
                    "Prose repair policy differs from the frozen registration.",
                    field="/p_repair_policy",
                )
            )
        if registration.c_retry_limit != self.config.c_retry_limit:
            diagnostics.append(
                self._diagnostic(
                    "registration.c_retry_mismatch",
                    "Compiled retry limit differs from the frozen registration.",
                    field="/c_retry_limit",
                )
            )
        registered_task = next(
            (task for task in registration.tasks if task.task_id == inputs.task_id),
            None,
        )
        if registered_task is None:
            diagnostics.append(
                self._diagnostic(
                    "registration.task_missing",
                    f"Task {inputs.task_id!r} is absent from the registration.",
                    field="/tasks",
                )
            )
        else:
            current_packets = tuple(
                PacketDigest(packet_id=item.packet_id, packet_sha256=item.packet_sha256)
                for item in manifest.packets
            )
            if (
                registered_task.plan_sha256 != sha256_bytes(plan_bytes)
                or registered_task.manifest_sha256 != sha256_bytes(manifest_bytes)
                or registered_task.packets != current_packets
            ):
                diagnostics.append(
                    self._diagnostic(
                        "registration.current_task_hash_mismatch",
                        "Current plan, manifest, or packet hashes differ from "
                        "registration.",
                        field="/tasks",
                    )
                )
        pair = next(
            (
                item
                for item in registration.task_seed_pairs
                if item.task_id == inputs.task_id and item.seed == seed
            ),
            None,
        )
        if pair is None:
            diagnostics.append(
                self._diagnostic(
                    "registration.seed_missing",
                    "Task/seed pair is not registered.",
                    field="/task_seed_pairs",
                )
            )
        elif pair.arm_order != arm_order:
            diagnostics.append(
                self._diagnostic(
                    "registration.arm_order_mismatch",
                    "Arm order differs from the frozen registration.",
                    field="/task_seed_pairs",
                )
            )
        return tuple(diagnostics)

    def _load_packets(
        self, inputs: PublicTaskInputs, manifest: ExecutionManifest
    ) -> dict[str, tuple[bytes, Packet]]:
        sources = {source.packet_id: source for source in inputs.packet_paths}
        result: dict[str, tuple[bytes, Packet]] = {}
        for entry in manifest.packets:
            source = sources[entry.packet_id]
            document = source.path.read_bytes()
            packet = decode_packet(document.decode("utf-8"))
            result[entry.packet_id] = (document, packet)
        return result

    async def _run_arm(
        self,
        inputs: PublicTaskInputs,
        manifest: ExecutionManifest,
        packets: dict[str, tuple[bytes, Packet]],
        plan: str,
        seed: int,
        arm: Arm,
        common_boundary: WorkerBoundary,
        expected_workspace_hash: str,
        worker: WorkerPort,
        task_port: ReferenceTaskPort,
    ) -> ArmResult:
        arm_started = time.monotonic()
        workspace = task_port.create_workspace(inputs.task_id, arm, seed)
        if _is_within(self.store.root, workspace):
            return self._empty_arm(inputs.task_id, arm, "harness_fault")
        try:
            start_snapshot = snapshot_workspace(workspace)
        except WorkspaceError:
            return self._empty_arm(inputs.task_id, arm, "harness_fault")
        if workspace_sha256(start_snapshot) != expected_workspace_hash:
            return self._empty_arm(inputs.task_id, arm, "harness_fault")
        budget = MonotonicBudget(self.config.budgets)
        try:
            await worker.restore_boundary(common_boundary, budget=budget)
            budget.ensure_capacity()
            if arm == "P":
                status, attempts = await self._run_prose_arm(
                    inputs,
                    manifest,
                    packets,
                    plan,
                    common_boundary.evidence,
                    workspace,
                    worker,
                    budget,
                )
            else:
                status, attempts = await self._run_compiled_arm(
                    inputs,
                    manifest,
                    packets,
                    plan,
                    workspace,
                    worker,
                    budget,
                )
        except BudgetExhausted:
            status, attempts = "budget_exhausted", ()
        except asyncio.CancelledError:
            status, attempts = "interrupted", ()
        except Exception:
            status, attempts = "harness_fault", ()
        return self._arm_result(
            inputs.task_id,
            arm,
            status,
            workspace,
            attempts,
            task_port,
            seed,
            duration_seconds=time.monotonic() - arm_started,
        )

    async def _run_prose_arm(
        self,
        inputs: PublicTaskInputs,
        manifest: ExecutionManifest,
        packets: dict[str, tuple[bytes, Packet]],
        plan: str,
        common_boundary: BoundaryEvidence,
        workspace: Path,
        worker: WorkerPort,
        budget: MonotonicBudget,
    ) -> tuple[ArmRunStatus, tuple[AttemptRecord, ...]]:
        declared_write_paths = {
            change.path
            for _, packet in packets.values()
            for change in packet.file_changes
        }
        test_paths = {
            test.path for _, packet in packets.values() for test in packet.tests
        }
        allowed_write_paths = tuple(
            sorted(
                (declared_write_paths - test_paths) & set(inputs.worker_writable_paths)
            )
        )
        try:
            for _, packet in packets.values():
                install_tests(packet, workspace)
        except (PreparationError, OSError):
            return "harness_fault", ()
        attempts: list[AttemptRecord] = []
        feedback: tuple[str, ...] = ()
        for attempt_number in range(1, self.config.p_repair_policy.max_retries + 2):
            started_at = _timestamp()
            attempt_started = time.monotonic()
            before = snapshot_workspace(workspace)
            input_hash = _input_hash(plan.encode("utf-8"), before)
            before_reply = budget.snapshot()
            gates: tuple[GateResult, ...] = ()
            status: Literal[
                "passed", "failed", "harness_fault", "budget_exhausted", "interrupted"
            ]
            error_feedback: tuple[str, ...] = ()
            visible_results: tuple[GateResult, ...] = ()
            round_boundary: WorkerBoundary | None = None
            generation_seconds = 0.0
            try:
                budget.ensure_capacity()
                generation_started = time.monotonic()
                reply = await worker.execute_prose(
                    task_id=inputs.task_id,
                    plan=plan,
                    workspace=workspace,
                    allowed_read_paths=inputs.allowed_read_paths,
                    allowed_write_paths=allowed_write_paths,
                    visible_gates=self._visible_gates(inputs.task_id, packets),
                    visible_feedback=feedback,
                    budget=budget,
                )
                generation_seconds = max(
                    0.0,
                    time.monotonic()
                    - generation_started
                    - sum(
                        result.duration_seconds for result in reply.visible_gate_results
                    ),
                )
                _verify_metered_reply(budget, reply, before_reply)
                round_boundary = await worker.capture_boundary(
                    task_id=inputs.task_id,
                    plan=plan,
                    workspace=workspace,
                    allowed_read_paths=inputs.allowed_read_paths,
                    budget=budget,
                )
                visible_results = reply.visible_gate_results
                expected_gate_ids = {
                    spec.gate_id
                    for spec in self._visible_gates(inputs.task_id, packets)
                }
                if any(
                    result.gate_id not in expected_gate_ids
                    for result in visible_results
                ):
                    raise RunnerHarnessFault(
                        "Worker returned a result for an unconfigured visible gate."
                    )
                after_worker = snapshot_workspace(workspace)
                _verify_allowed_changes(before, after_worker, set(allowed_write_paths))
                gates = self._run_packet_gates(
                    inputs.task_id,
                    packets,
                    workspace,
                    stage="after",
                    red_checks=(),
                )
                all_gates = visible_results + gates
                status = _gate_status(gates)
                if any(
                    result.status in ("error", "timed_out")
                    for result in visible_results
                ):
                    status = "harness_fault"
                error_feedback = _gate_feedback(
                    all_gates, self.config.max_feedback_characters
                )
                budget.ensure_capacity()
            except BudgetExhausted:
                status = "budget_exhausted"
            except asyncio.CancelledError:
                status = "interrupted"
                restore_workspace(workspace, before)
            except RunnerHarnessFault:
                status = "harness_fault"
                try:
                    restore_workspace(workspace, before)
                except WorkspaceError:
                    pass
            except (WorkspaceError, OSError):
                status = "harness_fault"
                try:
                    restore_workspace(workspace, before)
                except WorkspaceError:
                    pass
            except Exception as error:
                status = "harness_fault"
                error_feedback = (f"Worker or gate harness error: {error}",)
            try:
                after = snapshot_workspace(workspace)
            except WorkspaceError:
                after = before
                status = "harness_fault"
            attempt = self._attempt_record(
                inputs.task_id,
                "P",
                "prose",
                attempt_number,
                status,
                started_at,
                input_hash,
                before,
                after,
                visible_results + gates,
                budget.snapshot(),
                round_boundary.evidence
                if round_boundary is not None
                else common_boundary,
                feedback,
                timing=AttemptTiming(
                    preparation_seconds=0.0,
                    generation_seconds=generation_seconds,
                    gate_seconds=sum(
                        result.duration_seconds for result in gates + visible_results
                    ),
                    repair_seconds=(
                        time.monotonic() - attempt_started
                        if attempt_number > 1
                        else 0.0
                    ),
                    end_to_end_seconds=time.monotonic() - attempt_started,
                ),
            )
            self._persist_attempt(attempt)
            attempts.append(attempt)
            if status == "passed":
                return "passed", tuple(attempts)
            if status != "failed":
                return status, tuple(attempts)
            feedback = error_feedback
        return "failed", tuple(attempts)

    async def _run_compiled_arm(
        self,
        inputs: PublicTaskInputs,
        manifest: ExecutionManifest,
        packets: dict[str, tuple[bytes, Packet]],
        plan: str,
        workspace: Path,
        worker: WorkerPort,
        budget: MonotonicBudget,
    ) -> tuple[ArmRunStatus, tuple[AttemptRecord, ...]]:
        attempts: list[AttemptRecord] = []
        context = ValidationContext(
            workspace=workspace,
            roots=tuple(
                replace(root, path=workspace) if root.root_id == "workspace" else root
                for root in inputs.source_roots
            ),
        )
        for execution in manifest.packets:
            packet_document, packet = packets[execution.packet_id]
            packet_started = time.monotonic()
            preparation_started = time.monotonic()
            packet_start = snapshot_workspace(workspace)
            try:
                prepared = prepare_packet(packet_document, execution, context)
            except PreparationError as error:
                preparation_seconds = time.monotonic() - preparation_started
                record = self._preparation_fault_record(
                    inputs.task_id,
                    execution.packet_id,
                    packet_start,
                    budget,
                    str(error),
                    timing=AttemptTiming(
                        preparation_seconds=preparation_seconds,
                        generation_seconds=0.0,
                        gate_seconds=0.0,
                        repair_seconds=0.0,
                        end_to_end_seconds=time.monotonic() - packet_started,
                    ),
                )
                self._persist_attempt(record)
                attempts.append(record)
                restore_workspace(workspace, packet_start)
                return "harness_fault", tuple(attempts)
            preparation_seconds = time.monotonic() - preparation_started
            red_gate_started = time.monotonic()
            red_gates = self._run_packet_gates(
                inputs.task_id,
                {execution.packet_id: packets[execution.packet_id]},
                workspace,
                stage="before",
                red_checks=execution.red_checks,
            )
            red_gate_seconds = time.monotonic() - red_gate_started
            if not red_gates or any(result.status != "passed" for result in red_gates):
                record = self._preparation_fault_record(
                    inputs.task_id,
                    execution.packet_id,
                    packet_start,
                    budget,
                    "Prepared packet did not demonstrate the declared red behavior.",
                    gates=red_gates,
                    timing=AttemptTiming(
                        preparation_seconds=preparation_seconds,
                        generation_seconds=0.0,
                        gate_seconds=red_gate_seconds,
                        repair_seconds=0.0,
                        end_to_end_seconds=time.monotonic() - packet_started,
                    ),
                )
                self._persist_attempt(record)
                attempts.append(record)
                restore_workspace(workspace, packet_start)
                return "harness_fault", tuple(attempts)
            try:
                budget.ensure_capacity()
                packet_boundary = await worker.capture_boundary(
                    task_id=inputs.task_id,
                    plan=plan,
                    workspace=workspace,
                    allowed_read_paths=inputs.allowed_read_paths,
                    budget=budget,
                )
            except BudgetExhausted:
                restore_workspace(workspace, packet_start)
                return "budget_exhausted", tuple(attempts)
            except asyncio.CancelledError:
                restore_workspace(workspace, packet_start)
                return "interrupted", tuple(attempts)
            except Exception as error:
                record = self._preparation_fault_record(
                    inputs.task_id,
                    execution.packet_id,
                    packet_start,
                    budget,
                    f"Could not capture packet boundary: {error}",
                    gates=red_gates,
                    timing=AttemptTiming(
                        preparation_seconds=preparation_seconds,
                        generation_seconds=0.0,
                        gate_seconds=red_gate_seconds,
                        repair_seconds=0.0,
                        end_to_end_seconds=time.monotonic() - packet_started,
                    ),
                )
                self._persist_attempt(record)
                attempts.append(record)
                restore_workspace(workspace, packet_start)
                return "harness_fault", tuple(attempts)
            prepared_baseline = prepared.prepared_snapshot
            feedback: tuple[str, ...] = ()
            retries = self.config.c_retry_limit
            for attempt_number in range(1, retries + 2):
                repair_started = time.monotonic()
                if attempt_number > 1:
                    try:
                        restore_workspace(workspace, prepared_baseline)
                        await worker.restore_boundary(packet_boundary, budget=budget)
                        budget.ensure_capacity()
                    except Exception as error:
                        record = self._preparation_fault_record(
                            inputs.task_id,
                            execution.packet_id,
                            packet_start,
                            budget,
                            f"Could not restore retry boundary: {error}",
                        )
                        self._persist_attempt(record)
                        attempts.append(record)
                        restore_workspace(workspace, packet_start)
                        return "harness_fault", tuple(attempts)
                started_at = _timestamp()
                before = snapshot_workspace(workspace)
                input_hash = _input_hash(packet_document, before)
                current = replace(
                    prepared, prepared_snapshot=before, completed_slots=()
                )
                attempt_gates: tuple[GateResult, ...] = ()
                status: Literal[
                    "passed",
                    "failed",
                    "harness_fault",
                    "budget_exhausted",
                    "interrupted",
                ]
                error_feedback: tuple[str, ...] = ()
                boundary_evidence = packet_boundary.evidence
                generation_seconds = 0.0
                try:
                    for slot in execution.slots:
                        budget.ensure_capacity()
                        before_reply = budget.snapshot()
                        if slot.kind == "callable_body":
                            if not isinstance(slot.target, CallableBodyTarget):
                                raise RunnerHarnessFault(
                                    "Callable-body slot has a non-callable target."
                                )
                            produced = next(
                                item
                                for item in packet.produces
                                if item.path == slot.path
                                and item.qualified_name == slot.target.qualified_name
                            )
                            generation_started = time.monotonic()
                            reply = await worker.fill_body(
                                task_id=inputs.task_id,
                                plan=plan,
                                workspace=workspace,
                                allowed_read_paths=inputs.allowed_read_paths,
                                slot=slot,
                                signature_prefill=produced.declaration,
                                visible_feedback=feedback,
                                budget=budget,
                            )
                        else:
                            generation_started = time.monotonic()
                            reply = await worker.edit_ancillary(
                                task_id=inputs.task_id,
                                plan=plan,
                                workspace=workspace,
                                allowed_read_paths=inputs.allowed_read_paths,
                                slot=slot,
                                instruction=packet.task,
                                visible_feedback=feedback,
                                budget=budget,
                            )
                        generation_seconds += time.monotonic() - generation_started
                        _verify_metered_reply(budget, reply, before_reply)
                        boundary_evidence = reply.boundary_evidence or boundary_evidence
                        current = apply_slot_edit(current, slot.slot_id, reply.content)
                    attempt_gates = self._run_packet_gates(
                        inputs.task_id,
                        {execution.packet_id: packets[execution.packet_id]},
                        workspace,
                        stage="after",
                        red_checks=(),
                    )
                    status = _gate_status(attempt_gates)
                    error_feedback = _gate_feedback(
                        attempt_gates, self.config.max_feedback_characters
                    )
                    budget.ensure_capacity()
                except BudgetExhausted:
                    status = "budget_exhausted"
                except asyncio.CancelledError:
                    status = "interrupted"
                except SlotEditError as error:
                    status = "failed"
                    error_feedback = (f"Slot rejected: {error}",)
                except Exception as error:
                    status = "harness_fault"
                    error_feedback = (f"Harness failure: {error}",)
                after = snapshot_workspace(workspace)
                attempt = self._attempt_record(
                    inputs.task_id,
                    "C",
                    execution.packet_id,
                    attempt_number,
                    status,
                    started_at,
                    input_hash,
                    before,
                    after,
                    (red_gates if attempt_number == 1 else ()) + attempt_gates,
                    budget.snapshot(),
                    boundary_evidence,
                    feedback,
                    timing=AttemptTiming(
                        preparation_seconds=(
                            preparation_seconds if attempt_number == 1 else 0.0
                        ),
                        generation_seconds=generation_seconds,
                        gate_seconds=sum(
                            result.duration_seconds
                            for result in (
                                (red_gates if attempt_number == 1 else ())
                                + attempt_gates
                            )
                        ),
                        repair_seconds=(
                            time.monotonic() - repair_started
                            if attempt_number > 1
                            else 0.0
                        ),
                        end_to_end_seconds=(
                            time.monotonic() - packet_started
                            if attempt_number == 1
                            else time.monotonic() - repair_started
                        ),
                    ),
                )
                self._persist_attempt(attempt)
                attempts.append(attempt)
                if status == "passed":
                    prepared = current
                    break
                if status == "budget_exhausted":
                    return status, tuple(attempts)
                if status != "failed":
                    restore_workspace(workspace, packet_start)
                    return status, tuple(attempts)
                feedback = error_feedback
                # Keep the last attempt: prose arms are graded on partial work too.
                if attempt_number > retries:
                    return "failed", tuple(attempts)
            else:
                return "failed", tuple(attempts)
        return "passed", tuple(attempts)

    def _run_packet_gates(
        self,
        task_id: str,
        packets: dict[str, tuple[bytes, Packet]],
        workspace: Path,
        *,
        stage: Literal["before", "after"],
        red_checks: tuple[RedCheck, ...],
    ) -> tuple[GateResult, ...]:
        results: list[GateResult] = []
        for packet_id, (_, packet) in packets.items():
            assigned: set[int] = set()
            for gate_index, gate in enumerate(packet.gates):
                checks = (
                    tuple(
                        check
                        for check in red_checks
                        if _gate_matches_check(gate, check.path)
                    )
                    if stage == "before"
                    else ()
                )
                assigned.update(
                    index for index, check in enumerate(red_checks) if check in checks
                )
                expectation = gate.before if stage == "before" else gate.after
                result = run_gate(
                    workspace,
                    f"{task_id}:{packet_id}:{gate_index}:{stage}",
                    gate,
                    expectation,
                    self.config.gate_policy,
                    checks,
                )
                results.append(result)
            if stage == "before" and len(assigned) != len(red_checks):
                results.append(
                    GateResult(
                        gate_id=f"{task_id}:{packet_id}:red-check-unrouted",
                        status="error",
                        exit_code=None,
                        timed_out=False,
                        duration_seconds=0.0,
                        output_excerpt=(
                            "A red check does not map to exactly one visible gate."
                        ),
                        output_truncated=False,
                        verified_red_evidence=(),
                    )
                )
        return tuple(results)

    def _visible_gates(
        self,
        task_id: str,
        packets: dict[str, tuple[bytes, Packet]],
    ) -> tuple[VisibleGateSpec, ...]:
        return tuple(
            VisibleGateSpec(
                gate_id=f"{task_id}:{packet_id}:{index}:after",
                gate=gate,
                expectation=gate.after,
            )
            for packet_id, (_, packet) in packets.items()
            for index, gate in enumerate(packet.gates)
        )

    def _preparation_fault_record(
        self,
        task_id: str,
        packet_id: str,
        before: WorkspaceSnapshot,
        budget: MonotonicBudget,
        message: str,
        *,
        gates: tuple[GateResult, ...] = (),
        timing: AttemptTiming | None = None,
    ) -> AttemptRecord:
        now = _timestamp()
        digest = workspace_sha256(before)
        return AttemptRecord(
            attempt_id=uuid.uuid4().hex,
            task_id=task_id,
            arm="C",
            packet_id=packet_id,
            attempt_number=0,
            status="harness_fault",
            started_at=now,
            completed_at=now,
            input_sha256=digest,
            code_delta_sha256=None,
            gates=gates,
            budget=budget.snapshot(),
            boundary_evidence=None,
            visible_feedback=(message[: self.config.max_feedback_characters],),
            artifact_refs=(),
            timing=timing or AttemptTiming(0.0, 0.0, 0.0, 0.0, 0.0),
        )

    def _attempt_record(
        self,
        task_id: str,
        arm: Arm,
        packet_id: str,
        attempt_number: int,
        status: Literal[
            "passed", "failed", "harness_fault", "budget_exhausted", "interrupted"
        ],
        started_at: str,
        input_sha256: str,
        before: WorkspaceSnapshot,
        after: WorkspaceSnapshot,
        gates: tuple[GateResult, ...],
        budget: BudgetSnapshot,
        boundary: BoundaryEvidence | None,
        feedback: tuple[str, ...],
        timing: AttemptTiming | None = None,
    ) -> AttemptRecord:
        return AttemptRecord(
            attempt_id=uuid.uuid4().hex,
            task_id=task_id,
            arm=arm,
            packet_id=packet_id,
            attempt_number=attempt_number,
            status=status,
            started_at=started_at,
            completed_at=_timestamp(),
            input_sha256=input_sha256,
            code_delta_sha256=_delta_hash(before, after),
            gates=gates,
            budget=budget,
            boundary_evidence=boundary,
            visible_feedback=feedback,
            artifact_refs=(),
            timing=timing or AttemptTiming(0.0, 0.0, 0.0, 0.0, 0.0),
        )

    def _persist_attempt(self, attempt: AttemptRecord) -> None:
        try:
            self.store.write_attempt(attempt)
        except RecordStoreError as error:
            raise RunnerHarnessFault(
                f"Attempt record persistence failed: {error}"
            ) from error

    def _arm_result(
        self,
        task_id: str,
        arm: Arm,
        status: Literal[
            "passed", "failed", "harness_fault", "budget_exhausted", "interrupted"
        ],
        workspace: Path,
        attempts: tuple[AttemptRecord, ...],
        task_port: ReferenceTaskPort,
        seed: int,
        *,
        duration_seconds: float,
    ) -> ArmResult:
        try:
            snapshot = snapshot_workspace(workspace)
            digest = workspace_sha256(snapshot)
        except WorkspaceError:
            return ArmResult(
                task_id=task_id,
                arm=arm,
                status="harness_fault",
                workspace_sha256=None,
                attempts=attempts,
                host_grade=None,
                duration_seconds=duration_seconds,
            )
        grade: HostGrade | None = None
        if status in ("passed", "failed", "budget_exhausted"):
            try:
                grade = task_port.grade_protected(task_id, arm, seed, workspace)
            except Exception:
                status = "harness_fault"
        return ArmResult(
            task_id=task_id,
            arm=arm,
            status=status,
            workspace_sha256=digest,
            attempts=attempts,
            host_grade=grade,
            duration_seconds=duration_seconds,
        )

    def _empty_arm(
        self,
        task_id: str,
        arm: Arm,
        status: Literal["blocked", "harness_fault", "budget_exhausted", "interrupted"],
    ) -> ArmResult:
        return ArmResult(
            task_id=task_id,
            arm=arm,
            status=status,
            workspace_sha256=None,
            attempts=(),
            host_grade=None,
        )

    def _empty_pair(
        self,
        task_id: str,
        seed: int,
        pair_id: str,
        arm_order: tuple[Arm, Arm],
        status: Literal["blocked", "harness_fault", "budget_exhausted", "interrupted"],
        budget: BudgetSnapshot,
        *,
        capabilities: WorkerCapabilities | None = None,
        boundary: WorkerBoundary | None = None,
        diagnostic: ManifestDiagnostic | None = None,
        diagnostics: tuple[ManifestDiagnostic, ...] = (),
    ) -> PairResult:
        if diagnostic is not None:
            diagnostics = diagnostics + (diagnostic,)
        return PairResult(
            pair_id=pair_id,
            task_id=task_id,
            seed=seed,
            arm_order=arm_order,
            status=status,
            capabilities=capabilities,
            common_boundary=boundary.evidence if boundary else None,
            shared_budget=budget,
            arms=tuple(self._empty_arm(task_id, arm, status) for arm in arm_order),
            live_authorization_ref=self.config.live_authorization_ref,
            disposable_policy_ref=self.config.disposable_policy_ref,
            registration_diagnostics=diagnostics,
        )

    def _diagnostic(self, code: str, message: str, *, field: str) -> ManifestDiagnostic:
        return ManifestDiagnostic(code=code, field=field, message=message)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _boundary_evidence_problems(
    boundary: WorkerBoundary,
    registration: Registration | None,
) -> tuple[str, ...]:
    evidence = boundary.evidence
    problems: list[str] = []
    if boundary.opaque_token is None:
        problems.append("Worker returned no opaque boundary token.")
    if not all(
        value.strip()
        for value in (
            evidence.model_id,
            evidence.model_revision,
            evidence.runtime_revision,
            evidence.tokenizer_revision,
            evidence.checkpoint_key,
        )
    ):
        problems.append("Boundary is missing a model/runtime/checkpoint identity.")
    if (
        evidence.token_count < 0
        or evidence.reused_tokens < 0
        or evidence.prefilled_tokens < 0
    ):
        problems.append("Boundary token telemetry cannot be negative.")
    if not evidence.native_sync_events or any(
        not event.strip() for event in evidence.native_sync_events
    ):
        problems.append("Boundary has no native synchronization evidence.")
    for label, digest in (
        ("RNG", evidence.rng_state_sha256),
        ("host history", evidence.host_history_sha256),
        ("binder provenance", evidence.binder_provenance_sha256),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            problems.append(f"Boundary {label} digest is missing or malformed.")
    if registration is not None:
        expected = (
            registration.model_id,
            registration.model_revision,
            registration.runtime_revision,
            registration.tokenizer_revision,
        )
        actual = (
            evidence.model_id,
            evidence.model_revision,
            evidence.runtime_revision,
            evidence.tokenizer_revision,
        )
        if actual != expected:
            problems.append(
                "Boundary model/runtime/tokenizer revisions differ from registration."
            )
    return tuple(problems)


def _unsupported_capabilities(
    capabilities: WorkerCapabilities,
) -> tuple[str, ...]:
    requirements = (
        ("native_checkpoint", capabilities.native_checkpoint),
        ("token_reuse", capabilities.token_reuse),
        ("actual_prefill_counts", capabilities.actual_prefill_counts),
        ("rng_restore", capabilities.rng_restore),
        ("host_history_restore", capabilities.host_history_restore),
        ("binder_restore", capabilities.binder_restore),
        ("serial_tools", capabilities.serial_tools),
        ("safe_cancellation", capabilities.safe_cancellation),
    )
    missing = tuple(name for name, supported in requirements if not supported)
    if not any(item.strip() for item in capabilities.evidence):
        missing += ("capability evidence",)
    return missing


def _same_boundary_state(before: BoundaryEvidence, after: BoundaryEvidence) -> bool:
    return (
        before.model_id,
        before.model_revision,
        before.runtime_revision,
        before.tokenizer_revision,
        before.token_count,
        before.rng_state_sha256,
        before.host_history_sha256,
        before.binder_provenance_sha256,
    ) == (
        after.model_id,
        after.model_revision,
        after.runtime_revision,
        after.tokenizer_revision,
        after.token_count,
        after.rng_state_sha256,
        after.host_history_sha256,
        after.binder_provenance_sha256,
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _input_hash(document: bytes, snapshot: WorkspaceSnapshot) -> str:
    digest = hashlib.sha256()
    digest.update(document)
    digest.update(workspace_sha256(snapshot).encode("ascii"))
    return digest.hexdigest()


def _delta_hash(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> str | None:
    before_files = {item.path: item for item in before.files}
    after_files = {item.path: item for item in after.files}
    changes: list[tuple[str, str | None, str | None]] = []
    for path in sorted(set(before_files) | set(after_files)):
        old = before_files.get(path)
        new = after_files.get(path)
        if old == new:
            continue
        old_hash = sha256_bytes(old.content) if old is not None else None
        new_hash = sha256_bytes(new.content) if new is not None else None
        changes.append((path, old_hash, new_hash))
    if not changes:
        return None
    encoded = json.dumps(changes, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def _verify_metered_reply(
    budget: MonotonicBudget,
    reply: WorkerReply,
    before: BudgetSnapshot | None = None,
) -> None:
    current = budget.snapshot()
    if (
        reply.budget.tokens != current.tokens
        or reply.budget.model_calls != current.model_calls
    ):
        raise RunnerHarnessFault(
            "Worker reply counters do not match the monotonic budget ledger."
        )
    if before is not None and current.model_calls <= before.model_calls:
        raise RunnerHarnessFault(
            "Worker operation completed without recording a model call."
        )


def _gate_status(
    gates: tuple[GateResult, ...],
) -> Literal["passed", "failed", "harness_fault"]:
    if any(result.status in ("error", "timed_out") for result in gates):
        return "harness_fault"
    if not gates or any(result.status != "passed" for result in gates):
        return "failed"
    return "passed"


def _gate_feedback(gates: tuple[GateResult, ...], maximum: int) -> tuple[str, ...]:
    return tuple(
        f"{gate.gate_id}: exit={gate.exit_code}; {gate.output_excerpt[:maximum]}"
        for gate in gates
        if gate.status != "passed"
    )


def _verify_allowed_changes(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    allowed_paths: set[str],
) -> None:
    before_files = {item.path: item for item in before.files}
    after_files = {item.path: item for item in after.files}
    changed = {
        path
        for path in set(before_files) | set(after_files)
        if before_files.get(path) != after_files.get(path)
    }
    undeclared = changed - allowed_paths
    if undeclared:
        raise RunnerHarnessFault(
            f"Prose arm changed undeclared paths: {', '.join(sorted(undeclared))}"
        )
    allowed_directories = {
        parent.as_posix()
        for path in allowed_paths
        for parent in Path(path).parents
        if parent.as_posix() != "."
    }
    before_directories = {item.path: item for item in before.directories}
    after_directories = {item.path: item for item in after.directories}
    changed_directories = {
        path
        for path in set(before_directories) | set(after_directories)
        if before_directories.get(path) != after_directories.get(path)
    }
    if changed_directories - allowed_directories:
        raise RunnerHarnessFault(
            "Prose arm changed undeclared directories: "
            + ", ".join(sorted(changed_directories - allowed_directories))
        )


def _gate_matches_check(gate: Gate, check_path: str) -> bool:
    cwd = gate.cwd
    candidates = {check_path}
    if cwd != ".":
        try:
            candidates.add(Path(check_path).relative_to(cwd).as_posix())
        except ValueError:
            pass
    return any(argument in candidates for argument in gate.argv[1:])


def _packet_readiness_diagnostics(
    inputs: PublicTaskInputs,
    manifest: ExecutionManifest,
    packets: dict[str, tuple[bytes, Packet]],
) -> tuple[ManifestDiagnostic, ...]:
    context = ValidationContext(
        workspace=inputs.workspace,
        roots=inputs.source_roots,
    )
    index = build_index(context)
    diagnostics: list[ManifestDiagnostic] = []
    for packet_index, entry in enumerate(manifest.packets):
        packet = packets[entry.packet_id][1]
        report = validate_packet(packet, context, index)
        if report.ready:
            continue
        if not report.diagnostics:
            diagnostics.append(
                ManifestDiagnostic(
                    code="runner.packet_not_ready",
                    field=f"/packets/{packet_index}",
                    message=f"Packet validation returned {report.status}.",
                    outcome="inconclusive",
                    packet_id=entry.packet_id,
                )
            )
        for item in report.diagnostics:
            diagnostics.append(
                ManifestDiagnostic(
                    code=item.code,
                    field=f"/packets/{packet_index}{item.field}",
                    message=item.message,
                    outcome=item.outcome,
                    path=item.path,
                    packet_id=entry.packet_id,
                )
            )
    return tuple(
        sorted(diagnostics, key=lambda item: (item.field, item.code, item.path or ""))
    )


def _task_access_diagnostics(
    inputs: PublicTaskInputs,
    manifest: ExecutionManifest,
    packets: dict[str, tuple[bytes, Packet]],
) -> tuple[ManifestDiagnostic, ...]:
    allowed_reads = set(inputs.allowed_read_paths)
    allowed_writes = set(inputs.worker_writable_paths)
    if len(allowed_reads) != len(inputs.allowed_read_paths):
        return (
            ManifestDiagnostic(
                code="runner.duplicate_read_allowlist",
                field="/allowed_read_paths",
                message="Host read allowlist contains duplicate paths.",
            ),
        )
    if len(allowed_writes) != len(inputs.worker_writable_paths):
        return (
            ManifestDiagnostic(
                code="runner.duplicate_write_allowlist",
                field="/worker_writable_paths",
                message="Host write allowlist contains duplicate paths.",
            ),
        )
    diagnostics: list[ManifestDiagnostic] = []
    for packet_index, entry in enumerate(manifest.packets):
        packet = packets[entry.packet_id][1]
        missing_reads = set(packet.readable_files) - allowed_reads
        if missing_reads:
            diagnostics.append(
                ManifestDiagnostic(
                    code="runner.read_path_outside_policy",
                    field=f"/packets/{packet_index}/readable_files",
                    message=(
                        "Packet reads paths outside the host allowlist: "
                        + ", ".join(sorted(missing_reads))
                    ),
                )
            )
        declared_writes = {change.path for change in packet.file_changes}
        outside_writes = declared_writes - allowed_writes
        if outside_writes:
            diagnostics.append(
                ManifestDiagnostic(
                    code="runner.write_path_outside_policy",
                    field=f"/packets/{packet_index}/file_changes",
                    message=(
                        "Packet writes paths outside the host allowlist: "
                        + ", ".join(sorted(outside_writes))
                    ),
                )
            )
        slot_paths = {slot.path for slot in entry.slots}
        outside_slots = slot_paths - allowed_writes
        if outside_slots:
            diagnostics.append(
                ManifestDiagnostic(
                    code="runner.slot_path_outside_policy",
                    field=f"/packets/{packet_index}/slots",
                    message=(
                        "Compiled slots exceed the host write allowlist: "
                        + ", ".join(sorted(outside_slots))
                    ),
                )
            )
    return tuple(
        sorted(diagnostics, key=lambda item: (item.field, item.code, item.message))
    )
