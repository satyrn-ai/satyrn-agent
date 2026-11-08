import json
from dataclasses import replace
from pathlib import Path

import pytest

from plan_comparison.contracts import (
    ByteExtent,
    ExecutionManifest,
    ManifestInputs,
    PacketSource,
    Placement,
    TextAnchorTarget,
)
from plan_comparison.manifest import (
    ManifestDecodeError,
    decode_execution_manifest,
    sha256_bytes,
    validate_manifest_artifacts,
)


def packet_document() -> str:
    return json.dumps(
        {
            "schema_version": 0,
            "packet_id": "new-operation",
            "task": "Add a small operation.",
            "readable_files": ["src/operations.py"],
            "file_changes": [
                {"path": "src/operations.py", "operation": "modify"},
                {"path": "tests/test_operations.py", "operation": "create"},
            ],
            "consumes": [],
            "produces": [
                {
                    "path": "src/operations.py",
                    "qualified_name": "new_operation",
                    "operation": "create",
                    "kind": "function",
                    "declaration": "def new_operation() -> str:",
                }
            ],
            "imports": [],
            "tests": [
                {
                    "path": "tests/test_operations.py",
                    "operation": "create",
                    "content": (
                        "def test_new_operation() -> None:\n"
                        "    assert new_operation() == 'complete'\n"
                    ),
                }
            ],
            "gates": [
                {
                    "argv": ["pytest", "tests/test_operations.py"],
                    "cwd": ".",
                    "before": {"exit_code": "nonzero", "reason": "Not implemented."},
                    "after": {"exit_code": 0, "reason": "The operation passes."},
                }
            ],
            "known_facts": [],
            "acceptance_criteria": ["The operation returns its result."],
            "preserved_behavior": [],
        }
    )


def base_manifest(
    packet_text: str, plan_text: bytes, source: bytes
) -> dict[str, object]:
    return {
        "manifest_version": 0,
        "task_id": "public-fixture",
        "plan_sha256": sha256_bytes(plan_text),
        "packets": [
            {
                "packet_id": "new-operation",
                "packet_sha256": sha256_bytes(packet_text.encode()),
                "slots": [
                    {
                        "slot_id": "new-operation-body",
                        "path": "src/operations.py",
                        "kind": "callable_body",
                        "operation": "replace_body",
                        "target": {
                            "kind": "callable",
                            "qualified_name": "new_operation",
                        },
                        "extent": {"kind": "callable_body"},
                        "preimage_sha256": None,
                    }
                ],
                "placements": [
                    {
                        "placement_id": "new-operation-declaration",
                        "path": "src/operations.py",
                        "kind": "declarations",
                        "target": "module",
                        "position": "end",
                        "anchor": None,
                        "preimage_sha256": None,
                    }
                ],
                "red_checks": [
                    {
                        "path": "tests/test_operations.py",
                        "test_node": "test_new_operation",
                        "expected_exception": "NotImplementedError",
                        "marker": "test_new_operation",
                    }
                ],
            }
        ],
    }


def artifact_case(tmp_path: Path) -> tuple[ExecutionManifest, ManifestInputs]:
    packet_text = packet_document()
    plan_text = b"# Public fixture plan\n\nAdd the operation.\n"
    source = b"def helper() -> int:\n    return 1\n"
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "src" / "operations.py").write_bytes(source)
    plan_path = tmp_path / "plan.md"
    plan_path.write_bytes(plan_text)
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(packet_text)
    manifest = decode_execution_manifest(
        json.dumps(base_manifest(packet_text, plan_text, source))
    )
    inputs = ManifestInputs(
        task_id="public-fixture",
        workspace=workspace,
        plan_path=plan_path,
        packet_sources=(PacketSource(packet_id="new-operation", path=packet_path),),
    )
    return manifest, inputs


def test_execution_manifest_decodes_strict_frozen_contract(tmp_path: Path) -> None:
    manifest, _ = artifact_case(tmp_path)

    assert manifest.manifest_version == 0
    assert manifest.packets[0].slots[0].target.qualified_name == "new_operation"


@pytest.mark.parametrize(
    ("document", "field"),
    [
        ('{"manifest_version":0,"manifest_version":0}', "/manifest_version"),
        ('{"manifest_version":0,"unexpected":true}', "/unexpected"),
        ("{", ""),
        ('{"manifest_version":0,"x":NaN}', ""),
    ],
)
def test_execution_manifest_rejects_malformed_or_ambiguous_json(
    document: str, field: str
) -> None:
    with pytest.raises(ManifestDecodeError) as error:
        decode_execution_manifest(document)

    assert error.value.field == field


def test_execution_manifest_rejects_unknown_nested_fields() -> None:
    packet_text = packet_document()
    document = base_manifest(packet_text, b"plan", b"source")
    document["packets"][0]["slots"][0]["extra"] = True

    with pytest.raises(ManifestDecodeError) as error:
        decode_execution_manifest(json.dumps(document))

    assert error.value.code == "schema.unknown_field"


def test_execution_manifest_rejects_path_escape() -> None:
    packet_text = packet_document()
    document = base_manifest(packet_text, b"plan", b"source")
    document["packets"][0]["slots"][0]["path"] = "../outside.py"

    with pytest.raises(ManifestDecodeError) as error:
        decode_execution_manifest(json.dumps(document))

    assert error.value.code == "schema.path"


def test_execution_manifest_rejects_overlapping_ancillary_extents() -> None:
    packet_text = packet_document()
    document = base_manifest(packet_text, b"plan", b"source")
    first = document["packets"][0]["slots"][0]
    first.update(
        {
            "kind": "ancillary",
            "operation": "replace",
            "target": {"kind": "text_anchor", "anchor": "abcde"},
            "extent": {"kind": "bytes", "start_byte": 0, "end_byte": 5},
        }
    )
    second = first.copy()
    second.update(
        {
            "slot_id": "overlap",
            "target": {"kind": "text_anchor", "anchor": "abcde"},
            "extent": {"kind": "bytes", "start_byte": 0, "end_byte": 5},
        }
    )
    document["packets"][0]["slots"].append(second)

    with pytest.raises(ManifestDecodeError) as error:
        decode_execution_manifest(json.dumps(document))

    assert error.value.code == "manifest.overlapping_slots"


def test_workspace_validation_rejects_overlapping_distinct_text_anchors(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    source = b"abcdef\n"
    (inputs.workspace / "src" / "operations.py").write_bytes(source)
    first = replace(
        manifest.packets[0].slots[0],
        kind="ancillary",
        operation="replace",
        target=TextAnchorTarget("abcde"),
        extent=ByteExtent(0, 5),
        preimage_sha256=sha256_bytes(b"abcde"),
    )
    second = replace(
        first,
        slot_id="overlap",
        target=TextAnchorTarget("def"),
        extent=ByteExtent(0, 3),
        preimage_sha256=sha256_bytes(b"def"),
    )
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], slots=(first, second)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert "manifest.overlapping_slots" in {item.code for item in diagnostics}


def test_execution_manifest_accepts_distinct_planned_callable_bodies() -> None:
    packet_text = packet_document()
    document = base_manifest(packet_text, b"plan", b"source")
    second = document["packets"][0]["slots"][0].copy()
    second["slot_id"] = "other"
    second["target"] = {"kind": "callable", "qualified_name": "other_function"}
    document["packets"][0]["slots"].append(second)

    manifest = decode_execution_manifest(json.dumps(document))

    assert len(manifest.packets[0].slots) == 2


def test_manifest_artifact_validation_accepts_packet_access_and_hashes(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)

    assert validate_manifest_artifacts(manifest, inputs) == ()


def test_target_preimages_ignore_unrelated_changes_in_the_same_file(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    source_path = inputs.workspace / "src" / "operations.py"
    source_path.write_text(
        "# Earlier packet changed an unrelated region.\n" + source_path.read_text()
    )

    assert validate_manifest_artifacts(manifest, inputs) == ()


def test_manifest_artifact_validation_rejects_stale_plan_packet_and_preimage(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    inputs.plan_path.write_text("# Changed plan\n")
    inputs.packet_sources[0].path.write_text(
        inputs.packet_sources[0].path.read_text() + "\n"
    )
    source_path = inputs.workspace / "src" / "operations.py"
    source_path.write_text("def helper() -> int:\n    return 2\n")
    slot = replace(manifest.packets[0].slots[0], preimage_sha256="d" * 64)
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], slots=(slot,)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert {item.code for item in diagnostics} >= {
        "manifest.stale_plan",
        "manifest.stale_packet",
        "manifest.stale_preimage",
    }


def test_manifest_artifact_validation_rejects_test_file_slots(tmp_path: Path) -> None:
    manifest, inputs = artifact_case(tmp_path)
    packet_execution = replace(
        manifest.packets[0],
        slots=(replace(manifest.packets[0].slots[0], path="tests/test_operations.py"),),
    )
    manifest = replace(manifest, packets=(packet_execution,))

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert "manifest.host_test_slot" in {item.code for item in diagnostics}


def test_manifest_artifact_validation_rejects_undeclared_slot_path(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    slot = replace(manifest.packets[0].slots[0], path="src/other.py")
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], slots=(slot,)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert "manifest.slot_undeclared_path" in {item.code for item in diagnostics}


def test_manifest_artifact_validation_checks_placement_preimages(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    placement = Placement(
        placement_id="new-import",
        path="src/operations.py",
        kind="imports",
        target="module",
        position="before",
        anchor="def helper",
        preimage_sha256="d" * 64,
    )
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], placements=(placement,)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert any(
        item.code == "manifest.stale_preimage"
        and "/placements/0/preimage_sha256" in item.field
        for item in diagnostics
    )


def test_manifest_artifact_validation_rejects_ambiguous_text_anchor(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    source_path = inputs.workspace / "src" / "operations.py"
    source = b"value = 1\nvalue = 2\n"
    source_path.write_bytes(source)
    slot = replace(
        manifest.packets[0].slots[0],
        kind="ancillary",
        operation="replace",
        target=TextAnchorTarget("value"),
        extent=ByteExtent(0, 5),
        preimage_sha256=sha256_bytes(b"value"),
    )
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], slots=(slot,)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert "manifest.ambiguous_anchor" in {item.code for item in diagnostics}


def test_manifest_artifact_validation_rejects_unproduced_slot_target(
    tmp_path: Path,
) -> None:
    manifest, inputs = artifact_case(tmp_path)
    slot = replace(
        manifest.packets[0].slots[0],
        target=replace(manifest.packets[0].slots[0].target, qualified_name="unknown"),
    )
    manifest = replace(
        manifest,
        packets=(replace(manifest.packets[0], slots=(slot,)),),
    )

    diagnostics = validate_manifest_artifacts(manifest, inputs)

    assert "manifest.slot_target_undeclared" in {item.code for item in diagnostics}
