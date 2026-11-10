import asyncio
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from typed_packets import Packet, SourceRoot, decode_packet

from plan_comparison.budget import MonotonicBudget
from plan_comparison.contracts import (
    Arm,
    BoundaryEvidence,
    BudgetLimits,
    BudgetTracker,
    HostGrade,
    PacketSource,
    PublicTaskInputs,
    RepairPolicy,
    Slot,
    TaskSeedPair,
    VisibleGateSpec,
    WorkerBoundary,
    WorkerCapabilities,
    WorkerReply,
)
from plan_comparison.gates import GatePolicy
from plan_comparison.manifest import decode_execution_manifest, sha256_bytes
from plan_comparison.records import RunStore
from plan_comparison.runner import ExperimentRunner, RunnerConfig, RunnerHarnessFault

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _fixture(tmp_path: Path) -> tuple[PublicTaskInputs, bytes, str]:
    workspace = tmp_path / "start"
    workspace.mkdir()
    (workspace / "tests").mkdir()
    (workspace / "ops.py").write_text("# Frozen starting module.\n")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Add one to an integer using the existing module.\n")
    test_content = (
        "from ops import add_one\n\n"
        "def test_add_one() -> None:\n"
        "    assert add_one(2) == 3\n"
    )
    packet = {
        "schema_version": 0,
        "packet_id": "add-one",
        "task": "Add a function that returns its input plus one.",
        "readable_files": ["ops.py"],
        "file_changes": [
            {"path": "ops.py", "operation": "modify"},
            {"path": "tests/test_ops.py", "operation": "create"},
        ],
        "consumes": [],
        "produces": [
            {
                "path": "ops.py",
                "qualified_name": "add_one",
                "operation": "create",
                "kind": "function",
                "declaration": "def add_one(value: int) -> int:",
            }
        ],
        "imports": [],
        "tests": [
            {
                "path": "tests/test_ops.py",
                "operation": "create",
                "content": test_content,
            }
        ],
        "gates": [
            {
                "argv": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "tests/test_ops.py",
                ],
                "cwd": ".",
                "before": {
                    "exit_code": "nonzero",
                    "reason": "The deterministic placeholder is incomplete.",
                },
                "after": {"exit_code": 0, "reason": "The function passes."},
            }
        ],
        "known_facts": [],
        "acceptance_criteria": ["The function returns the input plus one."],
        "preserved_behavior": [],
    }
    packet_document = json.dumps(packet).encode("utf-8")
    packet_path = tmp_path / "packet.json"
    packet_path.write_bytes(packet_document)
    manifest = {
        "manifest_version": 0,
        "task_id": "cpu-fixture",
        "plan_sha256": sha256_bytes(plan_path.read_bytes()),
        "packets": [
            {
                "packet_id": "add-one",
                "packet_sha256": sha256_bytes(packet_document),
                "slots": [
                    {
                        "slot_id": "add-one-body",
                        "path": "ops.py",
                        "kind": "callable_body",
                        "operation": "replace_body",
                        "target": {"kind": "callable", "qualified_name": "add_one"},
                        "extent": {"kind": "callable_body"},
                        "preimage_sha256": None,
                    }
                ],
                "placements": [
                    {
                        "placement_id": "add-one-declaration",
                        "path": "ops.py",
                        "kind": "declarations",
                        "target": "module",
                        "position": "end",
                        "anchor": None,
                        "preimage_sha256": None,
                    }
                ],
                "red_checks": [
                    {
                        "path": "tests/test_ops.py",
                        "test_node": "test_add_one",
                        "expected_exception": "NotImplementedError",
                        "marker": "test_add_one",
                    }
                ],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    inputs = PublicTaskInputs(
        task_id="cpu-fixture",
        workspace=workspace,
        plan_path=plan_path,
        manifest_path=manifest_path,
        packet_paths=(PacketSource(packet_id="add-one", path=packet_path),),
        allowed_read_paths=("ops.py",),
        worker_writable_paths=("ops.py", "tests/test_ops.py"),
        source_roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base=".",
            ),
        ),
    )
    return inputs, packet_document, test_content


class ScriptedWorker:
    def __init__(self, test_content: str, *, supports_pairing: bool = True) -> None:
        self.test_content = test_content
        self.supports_pairing = supports_pairing
        self.prose_responses = ["return value", "return value + 1"]
        self.compiled_responses = ["return value", "return value + 1"]
        self.prose_feedback: list[tuple[str, ...]] = []
        self.prose_write_paths: list[tuple[str, ...]] = []
        self.prose_read_paths: list[tuple[str, ...]] = []
        self.compiled_read_paths: list[tuple[str, ...]] = []
        self.prose_test_present: list[bool] = []
        self.compiled_feedback: list[tuple[str, ...]] = []
        self.boundary_restores = 0
        self.captured_boundaries: list[WorkerBoundary] = []
        self.restored_tokens: list[object] = []
        self.capability_calls = 0
        self.closed = False
        self.workspace_writes = 0

    def workspace_written(self) -> None:
        self.workspace_writes += 1

    async def capabilities(self, *, budget: BudgetTracker) -> WorkerCapabilities:
        self.capability_calls += 1
        supported = self.supports_pairing
        return WorkerCapabilities(
            native_checkpoint=supported,
            token_reuse=supported,
            actual_prefill_counts=supported,
            rng_restore=supported,
            host_history_restore=supported,
            binder_restore=supported,
            serial_tools=supported,
            safe_cancellation=supported,
            evidence=("scripted worker; synthetic evidence only",),
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
        evidence = BoundaryEvidence(
            model_id="scripted-model",
            model_revision="scripted",
            runtime_revision="scripted",
            tokenizer_revision="scripted",
            checkpoint_key="fake-boundary",
            token_count=0,
            rng_state_sha256="a" * 64,
            host_history_sha256="b" * 64,
            binder_provenance_sha256="c" * 64,
            native_sync_events=("synthetic",),
            reused_tokens=0,
            prefilled_tokens=0,
        )
        boundary = WorkerBoundary(opaque_token=object(), evidence=evidence)
        self.captured_boundaries.append(boundary)
        return boundary

    async def restore_boundary(
        self, boundary: WorkerBoundary, *, budget: BudgetTracker
    ) -> None:
        self.boundary_restores += 1
        self.restored_tokens.append(boundary.opaque_token)

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
        self.prose_feedback.append(visible_feedback)
        self.prose_write_paths.append(allowed_write_paths)
        self.prose_read_paths.append(allowed_read_paths)
        self.prose_test_present.append((workspace / "tests" / "test_ops.py").is_file())
        body = self.prose_responses.pop(0)
        self._meter(budget)
        (workspace / "ops.py").write_text(
            "# Frozen starting module.\n\n"
            "def add_one(value: int) -> int:\n"
            f"    {body}\n"
        )
        return WorkerReply(
            content="prose tools completed",
            budget=budget.snapshot(),
            boundary_evidence=None,
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
        self.compiled_feedback.append(visible_feedback)
        self.compiled_read_paths.append(allowed_read_paths)
        body = self.compiled_responses.pop(0)
        self._meter(budget)
        return WorkerReply(
            content=body,
            budget=budget.snapshot(),
            boundary_evidence=None,
        )

    async def edit_ancillary(self, **kwargs) -> WorkerReply:
        raise AssertionError("This fixture has no ancillary slots.")

    async def close(self, *, budget: BudgetTracker) -> None:
        self.closed = True

    @staticmethod
    def _meter(budget: BudgetTracker) -> None:
        budget.ensure_capacity()
        budget.record_model_call()
        budget.record_tokens(4)


class ScriptedTaskPort:
    def __init__(self, inputs: PublicTaskInputs, root: Path) -> None:
        self.inputs = inputs
        self.root = root
        self.created: list[Path] = []
        self.grades: list[HostGrade] = []

    def public_inputs(self, task_id: str) -> PublicTaskInputs:
        return self.inputs

    def create_workspace(self, task_id: str, arm: Arm, seed: int) -> Path:
        destination = self.root / f"{task_id}-{seed}-{arm}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.inputs.workspace, destination)
        self.created.append(destination)
        return destination

    def grade_protected(
        self, task_id: str, arm: Arm, seed: int, workspace: Path
    ) -> HostGrade:
        source = (workspace / "ops.py").read_text()
        grade = HostGrade(
            status="pass" if "return value + 1" in source else "fail",
            result_sha256=sha256_bytes(source.encode()),
            artifact_ref=f"host-only/{task_id}/{seed}/{arm}",
        )
        self.grades.append(grade)
        return grade


def _runner(tmp_path: Path, *, supports_pairing: bool = True):
    inputs, _, test_content = _fixture(tmp_path)
    worker = ScriptedWorker(test_content, supports_pairing=supports_pairing)
    task_port = ScriptedTaskPort(inputs, tmp_path / "workspaces")
    policy = GatePolicy(
        allowed_commands=(sys.executable,),
        environment=(
            ("PATH", __import__("os").environ.get("PATH", "")),
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
        ),
        timeout_seconds=30,
        output_limit_bytes=12000,
    )
    config = RunnerConfig(
        mode="cpu",
        budgets=BudgetLimits(wall_seconds=120, tokens=100, model_calls=20),
        p_repair_policy=RepairPolicy(
            max_retries=1, description="One continue-on-failure retry."
        ),
        c_retry_limit=1,
        gate_policy=policy,
    )
    runner = ExperimentRunner(config, RunStore(tmp_path / "records"))
    return inputs, runner, worker, task_port


def test_pair_runs_both_arms_with_monotonic_retries_and_persistent_records(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    result = asyncio.run(
        runner.run_pair(
            inputs,
            worker,
            task_port,
            seed=19,
            arm_order=("P", "C"),
        )
    )

    assert result.status == "completed"
    assert [arm.status for arm in result.arms] == ["passed", "passed"]
    assert [len(arm.attempts) for arm in result.arms] == [2, 2]
    assert (
        result.arms[0].attempts[0].budget.tokens
        < result.arms[0].attempts[1].budget.tokens
    )
    assert (
        result.arms[1].attempts[0].budget.tokens
        < result.arms[1].attempts[1].budget.tokens
    )
    assert worker.boundary_restores == 4
    assert worker.workspace_writes == 2
    assert worker.restored_tokens == [
        worker.captured_boundaries[0].opaque_token,
        worker.captured_boundaries[1].opaque_token,
        worker.captured_boundaries[0].opaque_token,
        worker.captured_boundaries[-1].opaque_token,
    ]
    assert [path.name for path in task_port.created] == [
        "cpu-fixture-19-P",
        "cpu-fixture-19-C",
    ]
    assert worker.closed
    assert len(task_port.grades) == 2
    assert "AssertionError" in " ".join(worker.prose_feedback[1])
    assert "AssertionError" in " ".join(worker.compiled_feedback[1])
    assert all("host-only" not in str(feedback) for feedback in worker.prose_feedback)
    assert all(
        "host-only" not in str(feedback) for feedback in worker.compiled_feedback
    )
    assert len(list((tmp_path / "records").glob("attempt-*.json"))) == 4
    assert len(list((tmp_path / "records").glob("pair-*.json"))) == 1
    stored_attempts = [
        json.loads(path.read_text())
        for path in sorted((tmp_path / "records").glob("attempt-*.json"))
    ]
    assert all(record["record_version"] == 0 for record in stored_attempts)
    assert {record["record"]["status"] for record in stored_attempts} == {
        "failed",
        "passed",
    }
    assert all(record["record"]["started_at"] for record in stored_attempts)
    assert all(record["record"]["completed_at"] for record in stored_attempts)


def test_prose_arm_receives_the_visible_test_but_cannot_write_it(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=5, arm_order=("P", "C"))
    )

    assert result.arms[0].status == "passed"
    assert worker.prose_test_present == [True, True]
    assert worker.prose_write_paths == [("ops.py",), ("ops.py",)]


def test_both_arms_may_read_the_visible_test(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=("P", "C"))
    )

    assert all("tests/test_ops.py" in paths for paths in worker.prose_read_paths)
    assert all("tests/test_ops.py" in paths for paths in worker.compiled_read_paths)


@pytest.mark.parametrize("arm", ["P", "C"])
@pytest.mark.parametrize("error_type", [RuntimeError, OSError, RunnerHarnessFault])
def test_harness_faults_keep_host_only_exception_details(
    tmp_path: Path, arm: Arm, error_type: type[Exception]
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    async def fail(**kwargs):
        raise error_type("host-only sentinel cause")

    if arm == "P":
        worker.execute_prose = fail
    else:
        worker.fill_body = fail
    order = (arm, "C" if arm == "P" else "P")
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=order)
    )

    attempt = result.arms[0].attempts[0]
    assert attempt.status == "harness_fault"
    assert attempt.harness_fault.exception_type == error_type.__name__
    assert attempt.harness_fault.message == "host-only sentinel cause"
    assert all("sentinel" not in item for item in attempt.visible_feedback)
    document = json.loads(
        (tmp_path / "records" / f"attempt-{attempt.attempt_id}.json").read_text()
    )
    assert document["record"]["harness_fault"] == {
        "exception_type": error_type.__name__,
        "message": "host-only sentinel cause",
    }


@pytest.mark.parametrize("arm", ["P", "C"])
@pytest.mark.parametrize("reason", ["max_tokens", "parser_error"])
def test_model_response_failures_retry_with_rollback_and_metering(
    tmp_path: Path, arm: Arm, reason: str
) -> None:
    from plan_comparison.contracts import ModelResponseFailure

    inputs, runner, worker, task_port = _runner(tmp_path)
    original = worker.execute_prose if arm == "P" else worker.fill_body
    calls = []

    async def fail_once(**kwargs):
        calls.append(kwargs["budget"].snapshot())
        if len(calls) == 1:
            worker._meter(kwargs["budget"])
            if arm == "P":
                (kwargs["workspace"] / "ops.py").write_text("failed partial write")
            raise ModelResponseFailure(reason)
        assert (
            "failed partial write" not in (kwargs["workspace"] / "ops.py").read_text()
        )
        return await original(**kwargs)

    if arm == "P":
        worker.execute_prose = fail_once
        worker.prose_responses = ["return value + 1"]
    else:
        worker.fill_body = fail_once
        worker.compiled_responses = ["return value + 1"]
    order = (arm, "C" if arm == "P" else "P")
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=order)
    )

    attempts = result.arms[0].attempts
    assert [attempt.status for attempt in attempts] == ["failed", "passed"]
    assert attempts[0].harness_fault is None
    assert reason in attempts[1].visible_feedback[0]
    assert len(attempts[1].visible_feedback[0]) <= runner.config.max_feedback_characters
    assert calls[1].tokens > calls[0].tokens
    assert calls[1].model_calls > calls[0].model_calls
    assert worker.boundary_restores >= 2


def test_shared_context_exhaustion_is_a_distinct_pair_failure(tmp_path: Path) -> None:
    from plan_comparison.contracts import ContextPreparationFailure

    inputs, runner, worker, task_port = _runner(tmp_path)

    async def fail(**kwargs):
        worker._meter(kwargs["budget"])
        raise ContextPreparationFailure("parser_error", 2)

    worker.capture_boundary = fail
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=("P", "C"))
    )
    assert result.status == "context_failed"
    assert result.registration_diagnostics[0].code == "runner.context_failed"
    assert "parser_error" in result.registration_diagnostics[0].message
    assert result.shared_budget.model_calls == 1
    assert not task_port.created


def test_shared_context_harness_fault_keeps_its_cause(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    async def fail(**kwargs):
        raise OSError("host-only context cause")

    worker.capture_boundary = fail
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=("P", "C"))
    )
    assert result.status == "harness_fault"
    assert result.harness_fault.exception_type == "OSError"
    assert result.harness_fault.message == "host-only context cause"
    assert not task_port.created


def test_packet_context_failure_restores_an_existing_boundary(tmp_path: Path) -> None:
    from plan_comparison.contracts import ModelResponseFailure

    inputs, runner, worker, task_port = _runner(tmp_path)
    original = worker.capture_boundary
    calls = 0

    async def fail_packet_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            worker._meter(kwargs["budget"])
            raise ModelResponseFailure("parser_error")
        return await original(**kwargs)

    worker.capture_boundary = fail_packet_once
    worker.compiled_responses = ["return value + 1"]
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=("C", "P"))
    )
    assert result.arms[0].status == "passed"
    assert worker.boundary_restores >= 3


@pytest.mark.parametrize("arm", ["P", "C"])
@pytest.mark.parametrize("limited_budget", [None, "calls", "tokens"])
def test_model_response_retries_are_bounded_by_attempts_and_budget(
    tmp_path: Path, arm: Arm, limited_budget: str | None
) -> None:
    from plan_comparison.contracts import ModelResponseFailure

    inputs, runner, worker, task_port = _runner(tmp_path)
    calls = 0
    if limited_budget:
        runner.config = replace(
            runner.config,
            budgets=BudgetLimits(
                wall_seconds=120,
                tokens=1 if limited_budget == "tokens" else 100,
                model_calls=1 if limited_budget == "calls" else 20,
            ),
        )

    async def fail(**kwargs):
        nonlocal calls
        calls += 1
        from plan_comparison.budget import BudgetExhausted

        try:
            worker._meter(kwargs["budget"])
        except BudgetExhausted:
            # DS4 retains the response failure after recording an overrun.
            pass
        if arm == "P":
            (kwargs["workspace"] / "ops.py").write_text("failed partial write")
        raise ModelResponseFailure("max_tokens")

    if arm == "P":
        worker.execute_prose = fail
    else:
        worker.fill_body = fail
    order = (arm, "C" if arm == "P" else "P")
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=8, arm_order=order)
    )
    assert result.arms[0].status == ("budget_exhausted" if limited_budget else "failed")
    assert calls == (1 if limited_budget else 2)
    assert result.arms[0].attempts[0].budget.model_calls == 1
    assert "failed partial write" not in (task_port.created[0] / "ops.py").read_text()


@pytest.mark.parametrize("arm", ["P", "C"])
def test_response_retry_restore_failure_keeps_host_cause(
    tmp_path: Path, arm: Arm
) -> None:
    from plan_comparison.contracts import ModelResponseFailure

    inputs, runner, worker, task_port = _runner(tmp_path)
    original_restore = worker.restore_boundary
    failed = False

    async def fail(**kwargs):
        nonlocal failed
        failed = True
        worker._meter(kwargs["budget"])
        raise ModelResponseFailure("parser_error")

    async def restore(boundary, *, budget):
        if failed:
            raise OSError("host-only restore cause")
        await original_restore(boundary, budget=budget)

    worker.restore_boundary = restore
    if arm == "P":
        worker.execute_prose = fail
    else:
        worker.fill_body = fail
    result = asyncio.run(
        runner.run_pair(
            inputs,
            worker,
            task_port,
            seed=8,
            arm_order=(arm, "C" if arm == "P" else "P"),
        )
    )
    attempt = result.arms[0].attempts[0]
    assert attempt.status == "harness_fault"
    assert attempt.harness_fault.exception_type == "OSError"
    assert attempt.harness_fault.message == "host-only restore cause"
    assert not attempt.visible_feedback


def test_compiled_arm_accepts_a_fenced_body_wrapped_in_prose(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    worker.compiled_responses = [
        "Here it is.\n\n```python\nreturn value + 1\n```\n\nThis adds one.\n"
    ]

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=6, arm_order=("P", "C"))
    )

    compiled = result.arms[1]
    assert compiled.status == "passed"
    assert compiled.attempts[-1].rejection_reason is None
    assert "Here it is" not in (task_port.created[1] / "ops.py").read_text()


def test_final_slot_rejection_is_recorded_on_its_attempt(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    worker.compiled_responses = ["Here is the body:", "Here it is again:"]

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=6, arm_order=("P", "C"))
    )

    compiled = result.arms[1]
    assert compiled.status == "failed"
    first, last = compiled.attempts
    assert first.rejection_reason.startswith("Slot rejected: ")
    assert last.rejection_reason.startswith("Slot rejected: ")
    assert last.visible_feedback == (first.rejection_reason,)


def test_exhausted_compiled_arm_is_graded_on_its_last_attempt(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    worker.compiled_responses = ["return value", "return value + 2"]

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=6, arm_order=("P", "C"))
    )

    compiled = result.arms[1]
    assert compiled.status == "failed"
    assert compiled.host_grade is not None
    assert "return value + 2" in (task_port.created[1] / "ops.py").read_text()


def test_budget_exhausted_compiled_arm_keeps_its_partial_work_for_grading(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    original_fill = worker.fill_body

    async def exhaust_after_fill(**kwargs) -> WorkerReply:
        reply = await original_fill(**kwargs)
        kwargs["budget"].record_tokens(1000)
        return replace(reply, budget=kwargs["budget"].snapshot())

    worker.fill_body = exhaust_after_fill
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=7, arm_order=("C", "P"))
    )

    compiled = result.arms[0]
    assert compiled.status == "budget_exhausted"
    assert compiled.host_grade is not None
    assert "def add_one" in (task_port.created[0] / "ops.py").read_text()


def test_cpu_sweep_schedules_pairs_and_persists_a_report(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    report = asyncio.run(
        runner.run_sweep(
            {inputs.task_id: inputs},
            lambda _inputs, _seed: worker,
            task_port,
            (TaskSeedPair(task_id=inputs.task_id, seed=19, arm_order=("P", "C")),),
            experiment_id="cpu-sweep",
        )
    )

    assert report.status == "completed"
    assert report.experiment_id == "cpu-sweep"
    assert len(report.pairs) == 1
    assert report.pairs[0].task_id == inputs.task_id
    assert report.pairs[0].arms[0].attempt_statuses == ("failed", "passed")
    assert list((tmp_path / "records").glob("report-*.json"))


def test_pair_blocks_when_worker_cannot_restore_the_full_boundary(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path, supports_pairing=False)

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=2, arm_order=("C", "P"))
    )

    assert result.status == "blocked"
    assert [arm.status for arm in result.arms] == ["blocked", "blocked"]
    assert task_port.created == []
    assert worker.closed
    assert result.capabilities is not None
    assert not result.capabilities.supports_paired_draws


def test_arm_order_is_frozen_and_honored(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=5, arm_order=("C", "P"))
    )

    assert result.status == "completed"
    assert [arm.arm for arm in result.arms] == ["C", "P"]
    assert [path.name for path in task_port.created] == [
        "cpu-fixture-5-C",
        "cpu-fixture-5-P",
    ]


def test_compiled_retry_limit_cannot_exceed_two(tmp_path: Path) -> None:
    _, runner, _, _ = _runner(tmp_path)

    with pytest.raises(ValueError, match="between zero and two"):
        replace(runner.config, c_retry_limit=3)


def test_deciding_run_is_blocked_without_frozen_registration(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    runner.config = replace(
        runner.config,
        mode="deciding",
        live_authorization_ref="synthetic-test-authorization",
        disposable_policy_ref="synthetic-disposable-policy",
    )

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=11, arm_order=("P", "C"))
    )

    assert result.status == "blocked"
    assert result.registration_diagnostics[0].code == "registration.missing"
    assert task_port.created == []
    assert worker.closed


def test_pilot_entrypoint_requires_a_live_authorization_reference(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    runner.config = replace(runner.config, mode="pilot")

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=7, arm_order=("P", "C"))
    )

    assert result.status == "blocked"
    assert (
        result.registration_diagnostics[0].code == "runner.live_authorization_missing"
    )
    assert result.live_authorization_ref is None
    assert worker.capability_calls == 0
    assert task_port.created == []


def test_capability_probe_requires_a_separate_authorization_reference(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, _ = _runner(tmp_path)

    with pytest.raises(RunnerHarnessFault, match="disposable-policy references"):
        asyncio.run(
            runner.check_capabilities(
                worker,
                task_id=inputs.task_id,
                plan=inputs.plan_path.read_text(),
                workspace=inputs.workspace,
                allowed_read_paths=inputs.allowed_read_paths,
            )
        )

    assert worker.capability_calls == 0
    record = asyncio.run(
        runner.check_capabilities(
            worker,
            task_id=inputs.task_id,
            plan=inputs.plan_path.read_text(),
            workspace=inputs.workspace,
            allowed_read_paths=inputs.allowed_read_paths,
            authorization_ref="synthetic-test-approval",
            disposable_policy_ref="synthetic-disposable-policy",
        )
    )
    assert record.status == "passed"
    assert record.capabilities is not None
    assert record.capabilities.runtime_kind == "scripted"
    assert record.initial_boundary == record.restored_boundary
    assert worker.capability_calls == 1
    assert len(list((tmp_path / "records").glob("capability-*.json"))) == 1


def test_packet_writes_outside_host_allowlist_block_before_worker_starts(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    inputs = replace(inputs, worker_writable_paths=("ops.py",))

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=13, arm_order=("P", "C"))
    )

    assert result.status == "harness_fault"
    assert result.registration_diagnostics[0].code == "runner.write_path_outside_policy"
    assert worker.capability_calls == 0
    assert task_port.created == []


def _h1_start_with_unproven_decorator(tmp_path: Path, held_out_root: Path) -> Path:
    workspace = tmp_path / "h1-start"
    shutil.copytree(held_out_root / "H1" / "start", workspace)
    domain = workspace / "app" / "crm" / "domain.py"
    domain.write_text(
        domain.read_text().replace(
            "from dataclasses import dataclass", "from crm.helpers import dataclass"
        )
    )
    return workspace


def test_inconclusive_held_out_packet_blocks_pair_before_capability_check(
    tmp_path: Path,
) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    held_out_root = REPOSITORY_ROOT / "references" / "customer-tracker" / "tasks"
    package_root = (
        REPOSITORY_ROOT
        / "packages"
        / "plan-comparison"
        / "experiments"
        / "reference-held-out"
        / "customer_tracker"
    )
    workspace = _h1_start_with_unproven_decorator(tmp_path, held_out_root)
    packet_path = package_root / "H1.packet.json"
    packet = json.loads(packet_path.read_text())
    inputs = PublicTaskInputs(
        task_id="H1",
        workspace=workspace,
        plan_path=package_root / "H1.plan.md",
        manifest_path=package_root / "H1.manifest.json",
        packet_paths=(
            PacketSource(
                packet_id="customer-tracker-h1-search-pagination",
                path=packet_path,
            ),
        ),
        allowed_read_paths=tuple(
            path.relative_to(workspace).as_posix()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        ),
        worker_writable_paths=tuple(
            change["path"] for change in packet["file_changes"]
        ),
        source_roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base="app",
            ),
        ),
    )
    task_port = ScriptedTaskPort(inputs, tmp_path / "workspaces")

    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=3, arm_order=("P", "C"))
    )

    assert result.status == "blocked"
    assert "resolve.decorated_definition" in {
        item.code for item in result.registration_diagnostics
    }
    assert worker.capability_calls == 0
    assert task_port.created == []


def test_sweep_persists_block_report_for_inconclusive_held_out_packet(
    tmp_path: Path,
) -> None:
    _, runner, worker, _ = _runner(tmp_path)
    held_out_root = REPOSITORY_ROOT / "references" / "customer-tracker" / "tasks"
    package_root = (
        REPOSITORY_ROOT
        / "packages"
        / "plan-comparison"
        / "experiments"
        / "reference-held-out"
        / "customer_tracker"
    )
    workspace = _h1_start_with_unproven_decorator(tmp_path, held_out_root)
    packet_path = package_root / "H1.packet.json"
    packet = json.loads(packet_path.read_text())
    inputs = PublicTaskInputs(
        task_id="H1",
        workspace=workspace,
        plan_path=package_root / "H1.plan.md",
        manifest_path=package_root / "H1.manifest.json",
        packet_paths=(
            PacketSource(
                packet_id="customer-tracker-h1-search-pagination",
                path=packet_path,
            ),
        ),
        allowed_read_paths=tuple(
            path.relative_to(workspace).as_posix()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        ),
        worker_writable_paths=tuple(
            change["path"] for change in packet["file_changes"]
        ),
        source_roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base="app",
            ),
        ),
    )
    task_port = ScriptedTaskPort(inputs, tmp_path / "workspaces")

    report = asyncio.run(
        runner.run_sweep(
            {"H1": inputs},
            lambda _inputs, _seed: pytest.fail("Worker factory must not run."),
            task_port,
            (TaskSeedPair(task_id="H1", seed=3, arm_order=("P", "C")),),
            experiment_id="blocked-heldout-check",
        )
    )

    assert report.status == "blocked"
    assert report.pairs == ()
    assert any(
        "resolve.decorated_definition" in item for item in report.preflight_diagnostics
    )
    assert worker.capability_calls == 0
    assert list((tmp_path / "records").glob("report-*.json"))


def test_interrupted_prose_worker_is_recorded_and_closed(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)

    async def interrupt(**kwargs) -> WorkerReply:
        raise asyncio.CancelledError

    worker.execute_prose = interrupt
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=3, arm_order=("P", "C"))
    )

    assert result.status == "interrupted"
    assert result.arms[0].status == "interrupted"
    assert result.arms[0].attempts[0].status == "interrupted"
    assert task_port.grades == []
    assert worker.closed


def test_failed_retry_restore_is_a_harness_fault(tmp_path: Path) -> None:
    inputs, runner, worker, task_port = _runner(tmp_path)
    original_restore = worker.restore_boundary

    async def fail_compiled_retry(boundary, *, budget) -> None:
        if worker.compiled_feedback:
            raise RuntimeError("synthetic restore failure")
        await original_restore(boundary, budget=budget)

    worker.restore_boundary = fail_compiled_retry
    result = asyncio.run(
        runner.run_pair(inputs, worker, task_port, seed=4, arm_order=("P", "C"))
    )

    assert result.status == "harness_fault"
    assert result.arms[0].status == "passed"
    assert result.arms[1].status == "harness_fault"
    assert [attempt.status for attempt in result.arms[1].attempts] == [
        "failed",
        "harness_fault",
    ]
    compiled_workspace = task_port.created[1]
    assert (compiled_workspace / "ops.py").read_text() == "# Frozen starting module.\n"
    assert not (compiled_workspace / "tests" / "test_ops.py").exists()


def test_exhausted_packet_retries_preserve_prior_packet_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "start"
    workspace.mkdir()
    (workspace / "tests").mkdir()
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Add two independent integer operations.\n")
    packet_sources: list[PacketSource] = []
    packet_documents: dict[str, tuple[bytes, Packet]] = {}
    packet_entries = []
    for name in ("alpha", "beta"):
        (workspace / f"{name}.py").write_text(f"# Original {name} module.\n")
        test_path = f"tests/test_{name}.py"
        test_content = (
            f"from {name} import {name}\n\n"
            f"def test_{name}() -> None:\n"
            f"    assert {name}() == 1\n"
        )
        packet = {
            "schema_version": 0,
            "packet_id": name,
            "task": f"Add the {name} operation.",
            "readable_files": [f"{name}.py"],
            "file_changes": [
                {"path": f"{name}.py", "operation": "modify"},
                {"path": test_path, "operation": "create"},
            ],
            "consumes": [],
            "produces": [
                {
                    "path": f"{name}.py",
                    "qualified_name": name,
                    "operation": "create",
                    "kind": "function",
                    "declaration": f"def {name}() -> int:",
                }
            ],
            "imports": [],
            "tests": [
                {"path": test_path, "operation": "create", "content": test_content}
            ],
            "gates": [
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-p",
                        "no:cacheprovider",
                        test_path,
                    ],
                    "cwd": ".",
                    "before": {"exit_code": "nonzero", "reason": "Placeholder."},
                    "after": {"exit_code": 0, "reason": "Operation passes."},
                }
            ],
            "known_facts": [],
            "acceptance_criteria": [f"{name} returns one."],
            "preserved_behavior": [],
        }
        document = json.dumps(packet).encode()
        packet_path = tmp_path / f"{name}.packet.json"
        packet_path.write_bytes(document)
        packet_sources.append(PacketSource(packet_id=name, path=packet_path))
        packet_documents[name] = (document, decode_packet(document.decode("utf-8")))
        packet_entries.append(
            {
                "packet_id": name,
                "packet_sha256": sha256_bytes(document),
                "slots": [
                    {
                        "slot_id": f"{name}-body",
                        "path": f"{name}.py",
                        "kind": "callable_body",
                        "operation": "replace_body",
                        "target": {"kind": "callable", "qualified_name": name},
                        "extent": {"kind": "callable_body"},
                        "preimage_sha256": None,
                    }
                ],
                "placements": [
                    {
                        "placement_id": f"{name}-declaration",
                        "path": f"{name}.py",
                        "kind": "declarations",
                        "target": "module",
                        "position": "end",
                        "anchor": None,
                        "preimage_sha256": None,
                    }
                ],
                "red_checks": [
                    {
                        "path": test_path,
                        "test_node": f"test_{name}",
                        "expected_exception": "NotImplementedError",
                        "marker": f"test_{name}",
                    }
                ],
            }
        )
    manifest_document = {
        "manifest_version": 0,
        "task_id": "two-packets",
        "plan_sha256": sha256_bytes(plan_path.read_bytes()),
        "packets": packet_entries,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_document))
    inputs = PublicTaskInputs(
        task_id="two-packets",
        workspace=workspace,
        plan_path=plan_path,
        manifest_path=manifest_path,
        packet_paths=tuple(packet_sources),
        allowed_read_paths=("alpha.py", "beta.py"),
        worker_writable_paths=(
            "alpha.py",
            "beta.py",
            "tests/test_alpha.py",
            "tests/test_beta.py",
        ),
        source_roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base=".",
            ),
        ),
    )
    manifest = decode_execution_manifest(manifest_path.read_text())
    loaded_packets = packet_documents
    worker = ScriptedWorker("def test_alpha() -> None:\n    assert True\n")
    worker.compiled_responses = ["return 1", "return 0", "return 0"]
    runner = ExperimentRunner(
        RunnerConfig(
            mode="cpu",
            budgets=BudgetLimits(wall_seconds=120, tokens=100, model_calls=20),
            p_repair_policy=RepairPolicy(max_retries=1, description="unused"),
            c_retry_limit=1,
            gate_policy=GatePolicy(
                allowed_commands=(sys.executable,),
                environment=(("PATH", os.environ.get("PATH", "")),),
                timeout_seconds=30,
                output_limit_bytes=12000,
            ),
        ),
        RunStore(tmp_path / "records"),
    )

    recovery_boundary = asyncio.run(
        worker.capture_boundary(
            task_id=inputs.task_id,
            plan=plan_path.read_text(),
            workspace=workspace,
            allowed_read_paths=inputs.allowed_read_paths,
            budget=MonotonicBudget(
                BudgetLimits(wall_seconds=120, tokens=100, model_calls=20)
            ),
        )
    )
    status, attempts = asyncio.run(
        runner._run_compiled_arm(
            inputs,
            manifest,
            loaded_packets,
            plan_path.read_text(),
            workspace,
            worker,
            MonotonicBudget(BudgetLimits(wall_seconds=120, tokens=100, model_calls=20)),
            recovery_boundary,
        )
    )

    assert status == "failed"
    assert [attempt.packet_id for attempt in attempts] == ["alpha", "beta", "beta"]
    assert (workspace / "alpha.py").read_text().endswith("    return 1\n")
    assert (workspace / "beta.py").read_text().endswith("    return 0\n")
    assert (workspace / "tests" / "test_alpha.py").exists()
    assert (workspace / "tests" / "test_beta.py").exists()
