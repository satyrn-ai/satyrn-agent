import json
import sys
from pathlib import Path

from tests.packet_factory import valid_packet
from typed_packets.contract import decode_packet
from typed_packets.index import SourceRoot, ValidationContext, build_index
from typed_packets.validate import validate_document, validate_packet


def workspace_context(workspace: Path) -> ValidationContext:
    (workspace / "app").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "app" / "domain.py").write_text("class Contact:\n    pass\n")
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


def test_validate_packet_returns_ready_report_with_unverified_prose(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)
    document = json.dumps(valid_packet())
    packet = decode_packet(document)

    report = validate_packet(packet, context, build_index(context))

    assert report.status == "valid"
    assert report.ready
    assert report.diagnostics == ()
    assert report.input_fingerprint
    assert any("unverified" in item for item in report.unverified_requirements)


def test_validate_document_converts_decode_errors_to_invalid_reports(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)

    report = validate_document('{"schema_version": 0}', context)

    assert report.status == "invalid"
    assert not report.ready
    assert report.diagnostics[0].field == "/packet_id"
    assert report.diagnostics[0].code == "contract.missing_field"


def test_validate_reports_have_deterministic_order_and_fingerprints(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)
    document = json.dumps(valid_packet())

    first = validate_document(document, context)
    second = validate_document(document, context)

    assert first.diagnostics == second.diagnostics
    assert first.input_fingerprint == second.input_fingerprint


def test_validate_packet_uses_invalid_over_inconclusive_precedence(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)
    packet_data = valid_packet()
    packet_data["consumes"][0]["qualified_name"] = "MissingContact"
    packet_data["imports"] = [
        {
            "path": "app/domain.py",
            "module": "unavailable.module",
            "name": "Thing",
            "alias": None,
            "target": "existing",
        }
    ]
    packet = decode_packet(json.dumps(packet_data))

    report = validate_packet(packet, context, build_index(context))

    assert report.status == "invalid"
    assert not report.ready
    assert [item.field for item in report.diagnostics] == [
        "/consumes/0/qualified_name",
        "/imports/0/module",
    ]
    assert report.diagnostics[1].outcome == "inconclusive"


def test_validate_packet_rejects_stale_and_mismatched_indexes(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)
    packet = decode_packet(json.dumps(valid_packet()))
    index = build_index(context)
    (tmp_path / "app" / "domain.py").write_text(
        "class Contact:\n    pass\n\nvalue = 1\n"
    )

    stale = validate_packet(packet, context, index)

    assert stale.status == "inconclusive"
    assert not stale.ready
    assert any(item.code == "index.stale" for item in stale.diagnostics)

    other_context = ValidationContext(
        workspace=tmp_path,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=tmp_path,
                kind="project",
                import_base="tests",
            ),
        ),
    )
    mismatched = validate_packet(packet, other_context, build_index(context))

    assert mismatched.status == "invalid"
    assert not mismatched.ready
    assert any(item.code == "index.context_mismatch" for item in mismatched.diagnostics)


def test_validate_packet_maps_nested_project_reads_to_workspace_paths(
    tmp_path: Path,
) -> None:
    package = tmp_path / "app" / "crm"
    package.mkdir(parents=True)
    source = package / "domain.py"
    source.write_text("class Contact:\n    pass\n")
    (tmp_path / "tests").mkdir()
    context = ValidationContext(
        workspace=tmp_path,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=tmp_path,
                kind="project",
                import_base="tests",
            ),
            SourceRoot(root_id="crm", path=package, kind="project"),
        ),
    )
    packet_data = valid_packet()
    packet_data["readable_files"] = ["app/crm/domain.py"]
    packet_data["file_changes"][0]["path"] = "app/crm/domain.py"
    packet_data["produces"][0]["path"] = "app/crm/domain.py"
    packet_data["consumes"][0]["source"] = {
        "root_id": "crm",
        "path": "domain.py",
    }
    packet_data["tests"][0]["path"] = "tests/test_domain.py"
    packet_data["file_changes"][1]["path"] = "tests/test_domain.py"
    packet = decode_packet(json.dumps(packet_data))

    report = validate_packet(packet, context, build_index(context))

    assert report.status == "valid"


def test_validate_packet_rejects_existing_create_and_missing_modify_symbols(
    tmp_path: Path,
) -> None:
    context = workspace_context(tmp_path)
    create_data = valid_packet()
    create_data["produces"][0]["qualified_name"] = "Contact"
    create_data["produces"][0]["declaration"] = "def Contact() -> int:"
    create_report = validate_packet(
        decode_packet(json.dumps(create_data)), context, build_index(context)
    )

    modify_data = valid_packet()
    modify_data["produces"][0]["operation"] = "modify"
    modify_report = validate_packet(
        decode_packet(json.dumps(modify_data)), context, build_index(context)
    )

    assert create_report.status == "invalid"
    assert any(
        item.code == "produce.already_exists" for item in create_report.diagnostics
    )
    assert modify_report.status == "invalid"
    assert any(item.code == "produce.missing" for item in modify_report.diagnostics)


def test_validation_never_imports_source_or_runs_gates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = workspace_context(tmp_path)
    import_sentinel = tmp_path / "imported"
    gate_sentinel = tmp_path / "gate-ran"
    source = tmp_path / "app" / "effects.py"
    source.write_text(
        f"open({str(import_sentinel)!r}, 'w').write('imported')\nmarker = 1\n"
    )
    packet_data = {
        "schema_version": 0,
        "packet_id": "read-only-boundary",
        "task": "Validate a static source and gate declaration.",
        "readable_files": ["app/effects.py"],
        "file_changes": [{"path": "tests/test_probe.py", "operation": "create"}],
        "consumes": [],
        "produces": [],
        "imports": [
            {
                "path": "tests/test_probe.py",
                "module": "effects",
                "name": "marker",
                "alias": None,
                "target": "existing",
            }
        ],
        "tests": [
            {
                "path": "tests/test_probe.py",
                "operation": "create",
                "content": "def test_probe() -> None:\n    pass\n",
            }
        ],
        "gates": [
            {
                "argv": [
                    "python",
                    "-c",
                    f"open({str(gate_sentinel)!r}, 'w').write('ran')",
                ],
                "cwd": ".",
                "before": {"exit_code": "nonzero", "reason": "Test is new."},
                "after": {"exit_code": 0, "reason": "Test passes."},
            }
        ],
        "known_facts": [],
        "acceptance_criteria": ["The validator remains read-only."],
        "preserved_behavior": [],
    }
    before = tuple(
        sorted(
            (path.relative_to(tmp_path).as_posix(), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    report = validate_document(json.dumps(packet_data), context)

    after = tuple(
        sorted(
            (path.relative_to(tmp_path).as_posix(), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    )
    assert report.status == "valid"
    assert not import_sentinel.exists()
    assert not gate_sentinel.exists()
    assert after == before
