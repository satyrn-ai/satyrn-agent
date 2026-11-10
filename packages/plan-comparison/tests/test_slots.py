import json
import shutil
from pathlib import Path

import pytest
from typed_packets import SourceRoot, ValidationContext

from plan_comparison.contracts import PacketExecution
from plan_comparison.manifest import decode_execution_manifest, sha256_bytes
from plan_comparison.prepare import prepare_packet
from plan_comparison.slots import SlotEditError, apply_slot_edit, apply_slot_reply
from plan_comparison.workspace import snapshot_workspace

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _e2_prepared(tmp_path: Path):
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
    manifest_path = (
        REPOSITORY_ROOT
        / "packages"
        / "plan-comparison"
        / "examples"
        / "customer_tracker"
        / "E2.manifest.json"
    )
    execution: PacketExecution = decode_execution_manifest(
        manifest_path.read_text()
    ).packets[0]
    context = ValidationContext(
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
    return prepare_packet(packet_document, execution, context)


def _template_packet() -> tuple[bytes, dict[str, object], bytes]:
    source = b"<ul>\n  <li>old</li>\n</ul>\n"
    anchor = b"<li>old</li>"
    start = source.index(anchor)
    packet = {
        "schema_version": 0,
        "packet_id": "template-pagination",
        "task": "Change the visible template item label.",
        "readable_files": ["templates/list.html"],
        "file_changes": [
            {"path": "templates/list.html", "operation": "modify"},
            {"path": "tests/test_template.py", "operation": "create"},
        ],
        "consumes": [],
        "produces": [],
        "imports": [],
        "tests": [
            {
                "path": "tests/test_template.py",
                "operation": "create",
                "content": "def test_template_label() -> None:\n    assert True\n",
            }
        ],
        "gates": [
            {
                "argv": ["pytest", "tests/test_template.py"],
                "cwd": ".",
                "before": {
                    "exit_code": "nonzero",
                    "reason": "The template is incomplete.",
                },
                "after": {"exit_code": 0, "reason": "The template is correct."},
            }
        ],
        "known_facts": [],
        "acceptance_criteria": ["The visible item uses the requested label."],
        "preserved_behavior": [],
    }
    packet_document = json.dumps(packet).encode()
    manifest = {
        "manifest_version": 0,
        "task_id": "template",
        "plan_sha256": "a" * 64,
        "packets": [
            {
                "packet_id": "template-pagination",
                "packet_sha256": sha256_bytes(packet_document),
                "slots": [
                    {
                        "slot_id": "template-item",
                        "path": "templates/list.html",
                        "kind": "ancillary",
                        "operation": "replace",
                        "target": {"kind": "text_anchor", "anchor": anchor.decode()},
                        "extent": {
                            "kind": "bytes",
                            "start_byte": start,
                            "end_byte": start + len(anchor),
                        },
                        "preimage_sha256": sha256_bytes(anchor),
                    },
                    {
                        "slot_id": "before-list-close",
                        "path": "templates/list.html",
                        "kind": "ancillary",
                        "operation": "insert_before",
                        "target": {"kind": "text_anchor", "anchor": "</ul>"},
                        "extent": {
                            "kind": "bytes",
                            "start_byte": source.index(b"</ul>"),
                            "end_byte": source.index(b"</ul>"),
                        },
                        "preimage_sha256": sha256_bytes(b"</ul>"),
                    },
                ],
                "placements": [],
                "red_checks": [
                    {
                        "path": "tests/test_template.py",
                        "test_node": "test_template_label",
                        "expected_exception": "AssertionError",
                        "marker": "test_template_label",
                    }
                ],
            }
        ],
    }
    return packet_document, manifest, source


def test_slot_edits_preserve_signatures_and_immutable_tests(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)
    workspace = prepared.workspace
    installed_test = workspace / "app" / "tests" / "test_operations.py"
    test_bytes = installed_test.read_bytes()

    prepared = apply_slot_edit(
        prepared,
        "rule-violation-class",
        "message = 'invalid input'\n",
    )
    prepared = apply_slot_edit(
        prepared,
        "customer-name-rule",
        "if not first_name or not last_name:\n    raise RuleViolation('required')\n",
    )

    domain = (workspace / "app" / "crm" / "domain.py").read_text()
    assert "class RuleViolation(ValueError):\n    message = 'invalid input'" in domain
    assert "def validate_customer_name(" in domain
    assert "raise RuleViolation('required')" in domain
    assert installed_test.read_bytes() == test_bytes
    assert prepared.completed_slots == ("rule-violation-class", "customer-name-rule")


def _reply_with_prose(*blocks: str) -> str:
    fenced = "\n\n".join(f"```python\n{block}```" for block in blocks)
    return f"Understood — here is the body.\n\n{fenced}\n\nIt validates input.\n"


NAME_RULE_BODY = "if not first_name or not last_name:\n    raise RuleViolation('required')\n"


def test_slot_reply_uses_the_only_fenced_block_in_prose(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)

    prepared = apply_slot_reply(
        prepared, "customer-name-rule", _reply_with_prose(NAME_RULE_BODY)
    )

    domain = (prepared.workspace / "app" / "crm" / "domain.py").read_text()
    assert "raise RuleViolation('required')" in domain
    assert "Understood" not in domain
    assert prepared.completed_slots == ("customer-name-rule",)


def test_slot_reply_applies_a_valid_body_containing_fences_unchanged(
    tmp_path: Path,
) -> None:
    prepared = _e2_prepared(tmp_path)
    body = 'example = """\n```\nsample\n```\n"""\nraise RuleViolation(example)\n'

    prepared = apply_slot_reply(prepared, "customer-name-rule", body)

    domain = (prepared.workspace / "app" / "crm" / "domain.py").read_text()
    assert 'example = """' in domain
    assert "raise RuleViolation(example)" in domain


def test_slot_reply_rejects_more_than_one_fenced_block(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)
    before = prepared.prepared_snapshot

    with pytest.raises(SlotEditError) as error:
        apply_slot_reply(
            prepared,
            "customer-name-rule",
            _reply_with_prose(NAME_RULE_BODY, "return None\n"),
        )

    assert error.value.code == "slot_body_syntax"
    assert snapshot_workspace(prepared.workspace) == before


def test_slot_reply_still_checks_the_unwrapped_body(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)
    before = prepared.prepared_snapshot

    with pytest.raises(SlotEditError) as error:
        apply_slot_reply(
            prepared,
            "customer-name-rule",
            _reply_with_prose(
                "def validate_customer_name(first_name, last_name):\n    return None\n"
            ),
        )

    assert error.value.code == "callable_signature_returned"
    assert snapshot_workspace(prepared.workspace) == before


def test_slot_rejects_full_signature_and_restores_transaction(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)
    before = prepared.prepared_snapshot

    with pytest.raises(SlotEditError) as error:
        apply_slot_edit(
            prepared,
            "customer-name-rule",
            "def validate_customer_name(first_name, last_name):\n    return None\n",
        )

    assert error.value.code == "callable_signature_returned"
    assert snapshot_workspace(prepared.workspace) == before


def test_slot_rejects_changes_to_host_installed_tests(tmp_path: Path) -> None:
    prepared = _e2_prepared(tmp_path)
    test_path = prepared.workspace / "app" / "tests" / "test_operations.py"
    test_path.write_text("def test_changed() -> None:\n    pass\n")

    with pytest.raises(SlotEditError) as error:
        apply_slot_edit(prepared, "customer-name-rule", "pass\n")

    assert error.value.code == "workspace_changed"


def test_text_anchor_slot_edits_a_template_without_touching_other_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "templates").mkdir(parents=True)
    (workspace / "tests").mkdir()
    packet_document, manifest_document, source = _template_packet()
    template = workspace / "templates" / "list.html"
    template.write_bytes(source)
    execution = decode_execution_manifest(json.dumps(manifest_document)).packets[0]
    context = ValidationContext(
        workspace=workspace,
        roots=(SourceRoot(root_id="workspace", path=workspace, kind="project"),),
    )
    prepared = prepare_packet(packet_document, execution, context)

    prepared = apply_slot_edit(prepared, "template-item", "<li>longer new item</li>")
    prepared = apply_slot_edit(
        prepared, "before-list-close", "<!-- pagination marker -->\n"
    )

    assert template.read_bytes() == (
        b"<ul>\n  <li>longer new item</li>\n<!-- pagination marker -->\n</ul>\n"
    )
    assert (
        workspace / "tests" / "test_template.py"
    ).read_text() == prepared.packet.tests[0].content
