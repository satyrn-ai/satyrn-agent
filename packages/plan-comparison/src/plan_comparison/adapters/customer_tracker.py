import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from typed_packets import SourceRoot
from typed_packets.contract import Gate, GateExpectation

from plan_comparison.contracts import (
    Arm,
    HostGrade,
    PacketSource,
    PublicTaskInputs,
)
from plan_comparison.gates import GatePolicy, run_gate
from plan_comparison.workspace import (
    WorkspaceError,
    snapshot_workspace,
    workspace_sha256,
)

type ExportTask = Callable[[str, Path], None]
type GradeTask = Callable[[str, Path], subprocess.CompletedProcess[str]]

_HELD_OUT_TASKS = frozenset(("H1", "H2", "H3"))
_EXPORT_SCRIPT = (
    "from pathlib import Path; import sys; "
    "from host_tools.export import export; export(sys.argv[1], Path(sys.argv[2]))"
)
_GRADE_SCRIPT = (
    "import json, sys; from pathlib import Path; "
    "from host_tools.grade import grade; "
    "result = grade(sys.argv[1], Path(sys.argv[2])); "
    "print(json.dumps({'returncode': result.returncode, "
    "'stdout': result.stdout, 'stderr': result.stderr}))"
)


class ReferenceAdapterError(RuntimeError):
    pass


def _bounded_text(value: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    excerpt = encoded[:maximum_bytes].decode("utf-8", errors="ignore")
    return excerpt, len(encoded) > maximum_bytes


@dataclass(frozen=True, slots=True)
class TaskArtifactBundle:
    plan_path: Path
    manifest_path: Path
    packet_sources: tuple[PacketSource, ...]
    worker_writable_paths: tuple[str, ...]
    import_base: str = "app"
    start_workspace: Path | None = None
    task_document: Path | None = None
    dependency_roots: tuple[SourceRoot, ...] = ()


def public_customer_tracker_artifacts(
    repository_root: Path,
    plan_package_root: Path,
) -> dict[str, TaskArtifactBundle]:
    reference = repository_root / "references" / "customer-tracker"
    packets = (
        repository_root / "packages" / "typed-packets" / "examples" / "customer_tracker"
    )
    example_root = plan_package_root / "examples" / "customer_tracker"
    return {
        "E1": TaskArtifactBundle(
            plan_path=example_root / "E1.plan.md",
            manifest_path=example_root / "E1.manifest.json",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e1-model-slice",
                    path=packets / "E1.json",
                ),
            ),
            worker_writable_paths=(
                "app/crm/models.py",
                "app/tests/test_customer_model.py",
            ),
            start_workspace=reference / "examples" / "E1" / "start",
            task_document=reference / "examples" / "E1" / "task.md",
        ),
        "E2": TaskArtifactBundle(
            plan_path=example_root / "E2.plan.md",
            manifest_path=example_root / "E2.manifest.json",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e2-rules-and-create",
                    path=packets / "E2.json",
                ),
            ),
            worker_writable_paths=(
                "app/crm/domain.py",
                "app/crm/operations.py",
                "app/tests/test_operations.py",
            ),
            start_workspace=reference / "examples" / "E2" / "start",
            task_document=reference / "examples" / "E2" / "task.md",
        ),
        "E3": TaskArtifactBundle(
            plan_path=example_root / "E3.plan.md",
            manifest_path=example_root / "E3.manifest.json",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e3-contact-validation",
                    path=example_root / "E3.packet.json",
                ),
            ),
            worker_writable_paths=(
                "app/crm/operations.py",
                "app/tests/test_contact_update_contract.py",
            ),
            start_workspace=reference / "examples" / "E3" / "start",
            task_document=reference / "examples" / "E3" / "task.md",
        ),
    }


def held_out_customer_tracker_artifacts(
    repository_root: Path,
    plan_package_root: Path,
    *,
    django_source_root: Path,
) -> dict[str, TaskArtifactBundle]:
    artifact_root = (
        plan_package_root / "experiments" / "reference-held-out" / "customer_tracker"
    )
    django_root = SourceRoot(
        root_id="django",
        path=django_source_root,
        kind="dependency",
        import_base=".",
        module_prefix="django",
    )
    worker_paths = {
        "H1": (
            "app/crm/queries.py",
            "app/crm/views.py",
            "app/crm/templates/crm/customer_list.html",
            "app/tests/test_search_pagination.py",
        ),
        "H2": (
            "app/crm/domain.py",
            "app/crm/forms.py",
            "app/crm/operations.py",
            "app/crm/queries.py",
            "app/crm/views.py",
            "app/crm/templates/crm/customer_detail.html",
            "app/crm/templates/crm/follow_up_form.html",
            "app/tests/test_follow_up_workflow.py",
        ),
        "H3": (
            "app/crm/operations.py",
            "app/crm/views.py",
            "app/crm/templates/crm/customer_list.html",
            "app/crm/templates/crm/customer_detail.html",
            "app/tests/test_archive_workflow.py",
        ),
    }
    packet_ids = {
        "H1": "customer-tracker-h1-search-pagination",
        "H2": "customer-tracker-h2-follow-up-workflow",
        "H3": "customer-tracker-h3-archive-workflow",
    }
    return {
        task_id: TaskArtifactBundle(
            plan_path=artifact_root / f"{task_id}.plan.md",
            manifest_path=artifact_root / f"{task_id}.manifest.json",
            packet_sources=(
                PacketSource(
                    packet_id=packet_ids[task_id],
                    path=artifact_root / f"{task_id}.packet.json",
                ),
            ),
            worker_writable_paths=paths,
            dependency_roots=(django_root,),
        )
        for task_id, paths in worker_paths.items()
    }


class CustomerTrackerTaskAdapter:
    def __init__(
        self,
        *,
        reference_project: Path,
        artifact_root: Path,
        task_artifacts: dict[str, TaskArtifactBundle],
        exporter: ExportTask | None = None,
        grader: GradeTask | None = None,
        host_tool_timeout_seconds: float = 300,
        host_output_limit_bytes: int = 100_000,
    ) -> None:
        self.reference_project = reference_project
        self.artifact_root = artifact_root
        self.task_artifacts = task_artifacts
        self.exporter = exporter or self._export_allowlisted_task
        self.grader = grader or self._run_protected_grader
        self.host_tool_timeout_seconds = host_tool_timeout_seconds
        self.host_output_limit_bytes = host_output_limit_bytes
        self._start_workspaces: dict[str, Path] = {}
        self._start_hashes: dict[str, str] = {}

    def public_inputs(self, task_id: str) -> PublicTaskInputs:
        artifacts = self.task_artifacts.get(task_id)
        if artifacts is None:
            raise ReferenceAdapterError(f"Task is not registered: {task_id}")
        workspace = self._start_workspaces.get(task_id)
        if workspace is None:
            workspace = self._prepare_start_workspace(task_id, artifacts)
        try:
            snapshot = snapshot_workspace(workspace)
        except WorkspaceError as error:
            raise ReferenceAdapterError(f"Worker start is not safe: {error}") from error
        workspace_hash = workspace_sha256(snapshot)
        prior_hash = self._start_hashes.setdefault(task_id, workspace_hash)
        if prior_hash != workspace_hash:
            raise ReferenceAdapterError("Frozen exported start workspace changed.")
        self._start_workspaces[task_id] = workspace
        readable_paths = tuple(file.path for file in snapshot.files)
        workspace_root = SourceRoot(
            root_id="workspace",
            path=workspace,
            kind="project",
            import_base=artifacts.import_base,
        )
        roots = (workspace_root, *artifacts.dependency_roots)
        if any(root.root_id == "workspace" for root in artifacts.dependency_roots):
            raise ReferenceAdapterError("Dependency roots cannot redefine workspace.")
        return PublicTaskInputs(
            task_id=task_id,
            workspace=workspace,
            plan_path=artifacts.plan_path,
            manifest_path=artifacts.manifest_path,
            packet_paths=artifacts.packet_sources,
            allowed_read_paths=readable_paths,
            worker_writable_paths=artifacts.worker_writable_paths,
            source_roots=roots,
        )

    def create_workspace(self, task_id: str, arm: Arm, seed: int) -> Path:
        start = self._start_workspaces.get(task_id)
        if start is None:
            raise ReferenceAdapterError(
                "public_inputs must freeze the task start first."
            )
        destination = (
            self.artifact_root / "workspaces" / f"{task_id}-{seed}-{arm}-{uuid4().hex}"
        )
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(start, destination, symlinks=False)
        try:
            snapshot = snapshot_workspace(destination)
        except WorkspaceError as error:
            raise ReferenceAdapterError(
                f"Worker workspace is not safe: {error}"
            ) from error
        if workspace_sha256(snapshot) != self._start_hashes[task_id]:
            raise ReferenceAdapterError("Arm workspace differs from its frozen start.")
        return destination

    def grade_protected(
        self,
        task_id: str,
        arm: Arm,
        seed: int,
        workspace: Path,
    ) -> HostGrade:
        if task_id not in _HELD_OUT_TASKS:
            return HostGrade(
                status="not_applicable",
                result_sha256=hashlib.sha256(b"not applicable").hexdigest(),
                artifact_ref="not-applicable",
            )
        try:
            result = self.grader(task_id, workspace)
            status = "pass" if result.returncode == 0 else "fail"
            raw_result = json.dumps(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            result_hash = hashlib.sha256(raw_result).hexdigest()
            stdout_excerpt, stdout_truncated = _bounded_text(
                result.stdout, self.host_output_limit_bytes
            )
            stderr_excerpt, stderr_truncated = _bounded_text(
                result.stderr, self.host_output_limit_bytes
            )
            encoded = json.dumps(
                {
                    "task_id": task_id,
                    "arm": arm,
                    "seed": seed,
                    "returncode": result.returncode,
                    "stdout_excerpt": stdout_excerpt,
                    "stderr_excerpt": stderr_excerpt,
                    "output_truncated": stdout_truncated or stderr_truncated,
                    "result_sha256": result_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        except Exception as error:
            status = "error"
            encoded = json.dumps(
                {
                    "task_id": task_id,
                    "arm": arm,
                    "seed": seed,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            result_hash = hashlib.sha256(encoded).hexdigest()
        artifact_dir = self.artifact_root / "grades"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{task_id}-{seed}-{arm}-{uuid4().hex}.json"
        artifact_path.write_bytes(encoded)
        return HostGrade(
            status=status,
            result_sha256=result_hash,
            artifact_ref=artifact_path.as_posix(),
        )

    def _prepare_start_workspace(
        self, task_id: str, artifacts: TaskArtifactBundle
    ) -> Path:
        if artifacts.start_workspace is not None:
            source = artifacts.start_workspace
        else:
            exported = self.artifact_root / "exports" / f"{task_id}-{uuid4().hex}"
            exported.parent.mkdir(parents=True, exist_ok=True)
            self.exporter(task_id, exported)
            source = self._filter_worker_export(task_id, exported)
        try:
            snapshot_workspace(source)
        except WorkspaceError as error:
            raise ReferenceAdapterError(
                f"Exported start is not safe: {error}"
            ) from error
        destination = self.artifact_root / "worker-starts" / f"{task_id}-{uuid4().hex}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=False)
        if artifacts.task_document is not None:
            task_path = destination / "task.md"
            if not task_path.exists():
                shutil.copyfile(artifacts.task_document, task_path)
        return destination

    def _filter_worker_export(self, task_id: str, exported: Path) -> Path:
        destination = (
            self.artifact_root / "filtered-starts" / f"{task_id}-{uuid4().hex}"
        )
        destination.mkdir(parents=True)
        for source in sorted(exported.rglob("*")):
            relative = source.relative_to(exported)
            if relative.as_posix() == "provenance.json":
                continue
            if relative.parts[0] not in {"app", "pytest.ini", "task.md"}:
                raise ReferenceAdapterError(
                    f"Unexpected host export path is not worker-visible: {relative}"
                )
            target = destination / relative
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        return destination

    def _export_allowlisted_task(self, task_id: str, destination: Path) -> None:
        command = [
            sys.executable,
            "-c",
            _EXPORT_SCRIPT,
            task_id,
            str(destination),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.reference_project,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.host_tool_timeout_seconds,
                env=self._host_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReferenceAdapterError(f"Host export failed: {error}") from error
        if result.returncode != 0:
            raise ReferenceAdapterError(
                f"Host export failed with exit {result.returncode}: "
                f"{result.stderr[-2000:]}"
            )

    def _run_protected_grader(
        self, task_id: str, workspace: Path
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-c",
            _GRADE_SCRIPT,
            task_id,
            str(workspace),
        ]
        try:
            policy = GatePolicy(
                allowed_commands=(sys.executable,),
                environment=tuple(sorted(self._host_environment().items())),
                timeout_seconds=self.host_tool_timeout_seconds,
                output_limit_bytes=self.host_output_limit_bytes,
            )
            gate = Gate(
                argv=tuple(command),
                cwd=".",
                before=GateExpectation(exit_code=0, reason="Host grader completed."),
                after=GateExpectation(exit_code=0, reason="Host grader completed."),
            )
            result = run_gate(
                self.reference_project,
                f"protected-grade:{task_id}",
                gate,
                gate.after,
                policy,
            )
        except (OSError, ValueError) as error:
            raise ReferenceAdapterError(f"Protected grader failed: {error}") from error
        if result.status != "passed" or result.output_truncated or result.timed_out:
            raise ReferenceAdapterError(
                f"Protected grader host command failed: {result.output_excerpt[-2000:]}"
            )
        report = json.loads(result.output_excerpt)
        return subprocess.CompletedProcess(
            args=command,
            returncode=int(report["returncode"]),
            stdout=str(report["stdout"]),
            stderr=str(report["stderr"]),
        )

    @staticmethod
    def _host_environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("UV_PROJECT_ENVIRONMENT", None)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment
