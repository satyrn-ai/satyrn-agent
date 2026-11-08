import json
import shutil
from pathlib import Path

import pytest
from typed_packets import SourceRoot, ValidationContext

from plan_comparison.contracts import PacketExecution
from plan_comparison.manifest import decode_execution_manifest, sha256_bytes
from plan_comparison.prepare import PreparationError, prepare_packet
from plan_comparison.workspace import snapshot_workspace

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "plan-comparison"


def _e2_workspace(tmp_path: Path) -> tuple[Path, bytes, PacketExecution]:
    source = (
        REPOSITORY_ROOT
        / "references"
        / "customer-tracker"
        / "examples"
        / "E2"
        / "start"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(source, workspace)
    packet_path = (
        REPOSITORY_ROOT
        / "packages"
        / "typed-packets"
        / "examples"
        / "customer_tracker"
        / "E2.json"
    )
    packet_document = packet_path.read_bytes()
    manifest_path = PACKAGE_ROOT / "examples" / "customer_tracker" / "E2.manifest.json"
    manifest = decode_execution_manifest(manifest_path.read_text())
    return workspace, packet_document, manifest.packets[0]


def _context(workspace: Path) -> ValidationContext:
    return ValidationContext(
        workspace=workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base="app",
            ),
        ),
    )


def test_prepare_e2_installs_tests_and_creates_multifile_placeholders(
    tmp_path: Path,
) -> None:
    workspace, packet_document, execution = _e2_workspace(tmp_path)
    original = snapshot_workspace(workspace)

    prepared = prepare_packet(packet_document, execution, _context(workspace))

    domain = (workspace / "app" / "crm" / "domain.py").read_text()
    operations = (workspace / "app" / "crm" / "operations.py").read_text()
    installed_test = workspace / "app" / "tests" / "test_operations.py"
    assert "class RuleViolation(ValueError):" in domain
    assert "def validate_customer_name(" in domain
    assert "def validate_contact(" in domain
    assert domain.count("raise NotImplementedError") == 2
    assert "def create_customer(" in operations
    assert "raise NotImplementedError" in operations
    assert installed_test.read_text() == prepared.packet.tests[0].content
    assert prepared.input_snapshot == original
    assert {item.path for item in prepared.immutable_tests} == {
        "app/tests/test_operations.py"
    }


def test_prepare_rejects_stale_input_before_writing_tests(tmp_path: Path) -> None:
    source = (
        REPOSITORY_ROOT
        / "references"
        / "customer-tracker"
        / "examples"
        / "E1"
        / "start"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(source, workspace)
    packet_path = (
        REPOSITORY_ROOT
        / "packages"
        / "typed-packets"
        / "examples"
        / "customer_tracker"
        / "E1.json"
    )
    packet_document = packet_path.read_bytes()
    manifest_path = PACKAGE_ROOT / "examples" / "customer_tracker" / "E1.manifest.json"
    execution = decode_execution_manifest(manifest_path.read_text()).packets[0]
    model_path = workspace / "app" / "crm" / "models.py"
    model_path.write_text(
        model_path.read_text().replace("    pass", "    label = None")
    )
    before = snapshot_workspace(workspace)

    with pytest.raises(PreparationError) as error:
        prepare_packet(packet_document, execution, _context(workspace))

    assert error.value.code == "execution_manifest_invalid"
    assert snapshot_workspace(workspace) == before
    assert not (workspace / "app" / "tests" / "test_customer_model.py").exists()


def test_prepare_rolls_back_tests_when_a_placement_is_unsupported(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "app").mkdir(parents=True)
    (workspace / "tests").mkdir()
    source_path = workspace / "app" / "domain.py"
    source = b"class Target: pass\n"
    source_path.write_bytes(source)
    packet = {
        "schema_version": 0,
        "packet_id": "inline-class-method",
        "task": "Add a method to the target class.",
        "readable_files": ["app/domain.py"],
        "file_changes": [
            {"path": "app/domain.py", "operation": "modify"},
            {"path": "tests/test_domain.py", "operation": "create"},
        ],
        "consumes": [],
        "produces": [
            {
                "path": "app/domain.py",
                "qualified_name": "Target.action",
                "operation": "create",
                "kind": "function",
                "declaration": "def action() -> None:",
            }
        ],
        "imports": [],
        "tests": [
            {
                "path": "tests/test_domain.py",
                "operation": "create",
                "content": "def test_action() -> None:\n    assert True\n",
            }
        ],
        "gates": [
            {
                "argv": ["pytest", "tests/test_domain.py"],
                "cwd": ".",
                "before": {"exit_code": "nonzero", "reason": "Placeholder fails."},
                "after": {"exit_code": 0, "reason": "Method passes."},
            }
        ],
        "known_facts": [],
        "acceptance_criteria": ["The method is available."],
        "preserved_behavior": [],
    }
    packet_document = json.dumps(packet).encode()
    manifest_document = {
        "manifest_version": 0,
        "task_id": "inline-class",
        "plan_sha256": "a" * 64,
        "packets": [
            {
                "packet_id": "inline-class-method",
                "packet_sha256": sha256_bytes(packet_document),
                "slots": [
                    {
                        "slot_id": "method-body",
                        "path": "app/domain.py",
                        "kind": "callable_body",
                        "operation": "replace_body",
                        "target": {
                            "kind": "callable",
                            "qualified_name": "Target.action",
                        },
                        "extent": {"kind": "callable_body"},
                        "preimage_sha256": None,
                    }
                ],
                "placements": [
                    {
                        "placement_id": "method-declaration",
                        "path": "app/domain.py",
                        "kind": "declarations",
                        "target": "class:Target",
                        "position": "end",
                        "anchor": None,
                        "preimage_sha256": None,
                    }
                ],
                "red_checks": [
                    {
                        "path": "tests/test_domain.py",
                        "test_node": "test_action",
                        "expected_exception": "NotImplementedError",
                        "marker": "test_action",
                    }
                ],
            }
        ],
    }
    execution = decode_execution_manifest(json.dumps(manifest_document)).packets[0]
    before = snapshot_workspace(workspace)

    with pytest.raises(PreparationError) as error:
        prepare_packet(packet_document, execution, _context(workspace))

    assert error.value.code == "placement_class_inline"
    assert snapshot_workspace(workspace) == before
    assert not (workspace / "tests" / "test_domain.py").exists()
