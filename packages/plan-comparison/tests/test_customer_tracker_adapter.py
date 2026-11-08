import json
import subprocess
from pathlib import Path

import pytest

from plan_comparison.adapters.customer_tracker import (
    CustomerTrackerTaskAdapter,
    ReferenceAdapterError,
    TaskArtifactBundle,
    public_customer_tracker_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_public_task_adapter_uses_only_the_visible_start_tree(tmp_path: Path) -> None:
    reference_project = REPOSITORY_ROOT / "references" / "customer-tracker"
    plan_root = REPOSITORY_ROOT / "packages" / "plan-comparison"
    adapter = CustomerTrackerTaskAdapter(
        reference_project=reference_project,
        artifact_root=tmp_path / "item3",
        task_artifacts=public_customer_tracker_artifacts(REPOSITORY_ROOT, plan_root),
        exporter=lambda task_id, destination: pytest.fail(
            f"Public task {task_id} must use its visible example start directly."
        ),
    )

    inputs = adapter.public_inputs("E1")
    workspace = adapter.create_workspace("E1", "P", 1)

    assert (workspace / "task.md").is_file()
    assert (workspace / "app" / "crm" / "models.py").is_file()
    assert "task.md" in inputs.allowed_read_paths
    assert "app/crm/models.py" in inputs.worker_writable_paths
    assert not (workspace / "evaluation").exists()
    assert not any("provenance" in path for path in inputs.allowed_read_paths)


def test_held_out_export_filters_host_provenance_and_grading_output(
    tmp_path: Path,
) -> None:
    reference_project = tmp_path / "reference"
    reference_project.mkdir()
    task_document = tmp_path / "H1.plan.md"
    task_document.write_text("Frozen visible plan.\n")
    manifest_path = tmp_path / "H1.manifest.json"
    manifest_path.write_text("{}\n")
    packet_path = tmp_path / "H1.packet.json"
    packet_path.write_text("{}\n")
    bundle = TaskArtifactBundle(
        plan_path=task_document,
        manifest_path=manifest_path,
        packet_sources=(),
        worker_writable_paths=("app/crm/models.py",),
        start_workspace=None,
    )

    def export_visible_task(task_id: str, destination: Path) -> None:
        assert task_id == "H1"
        destination.mkdir(parents=True)
        (destination / "app" / "crm").mkdir(parents=True)
        (destination / "app" / "crm" / "models.py").write_text("class Customer: pass\n")
        (destination / "task.md").write_text("Visible held-out task.\n")
        (destination / "pytest.ini").write_text("[pytest]\n")
        (destination / "provenance.json").write_text(
            '{"protected_fingerprint":"host-secret"}\n'
        )

    def fake_grade(task_id: str, workspace: Path) -> subprocess.CompletedProcess[str]:
        assert task_id == "H1"
        assert (workspace / "app" / "crm" / "models.py").is_file()
        return subprocess.CompletedProcess(
            args=("host-grader",),
            returncode=1,
            stdout="PROTECTED_FAILURE_DETAIL: host-secret",
            stderr="",
        )

    artifact_root = tmp_path / "item3"
    adapter = CustomerTrackerTaskAdapter(
        reference_project=reference_project,
        artifact_root=artifact_root,
        task_artifacts={"H1": bundle},
        exporter=export_visible_task,
        grader=fake_grade,
        host_output_limit_bytes=32,
    )

    inputs = adapter.public_inputs("H1")
    workspace = adapter.create_workspace("H1", "C", 9)
    host_grade = adapter.grade_protected("H1", "C", 9, workspace)

    assert host_grade.status == "fail"
    assert host_grade.artifact_ref.startswith(str(artifact_root / "grades"))
    assert "provenance.json" not in inputs.allowed_read_paths
    assert "host-secret" not in " ".join(inputs.allowed_read_paths)
    assert not (workspace / "provenance.json").exists()
    assert Path(host_grade.artifact_ref).is_file()
    persisted_grade = json.loads(Path(host_grade.artifact_ref).read_text())
    assert persisted_grade["output_truncated"] is True
    assert "host-secret" not in persisted_grade["stdout_excerpt"]


def test_held_out_export_rejects_unexpected_solution_tree(tmp_path: Path) -> None:
    reference_project = tmp_path / "reference"
    reference_project.mkdir()
    bundle = TaskArtifactBundle(
        plan_path=tmp_path / "plan.md",
        manifest_path=tmp_path / "manifest.json",
        packet_sources=(),
        worker_writable_paths=(),
    )

    def export_with_extra(task_id: str, destination: Path) -> None:
        destination.mkdir(parents=True)
        (destination / "complete").mkdir()
        (destination / "complete" / "solution.py").write_text("secret")

    adapter = CustomerTrackerTaskAdapter(
        reference_project=reference_project,
        artifact_root=tmp_path / "item3",
        task_artifacts={"H1": bundle},
        exporter=export_with_extra,
    )

    with pytest.raises(ReferenceAdapterError, match="not worker-visible"):
        adapter.public_inputs("H1")


def test_public_task_host_grade_is_explicitly_not_applicable(tmp_path: Path) -> None:
    reference_project = REPOSITORY_ROOT / "references" / "customer-tracker"
    plan_root = REPOSITORY_ROOT / "packages" / "plan-comparison"
    adapter = CustomerTrackerTaskAdapter(
        reference_project=reference_project,
        artifact_root=tmp_path / "item3",
        task_artifacts=public_customer_tracker_artifacts(REPOSITORY_ROOT, plan_root),
    )
    workspace = adapter.public_inputs("E1").workspace

    grade = adapter.grade_protected("E1", "P", 0, workspace)

    assert grade.status == "not_applicable"
    assert grade.artifact_ref == "not-applicable"
