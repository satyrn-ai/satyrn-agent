import json
from pathlib import Path

import pytest

from typed_packets.index import SourceRoot, ValidationContext
from typed_packets.validate import validate_document

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
CUSTOMER_TRACKER_EXAMPLES = (
    ("E1", "examples/customer_tracker/E1.json"),
    ("E2", "examples/customer_tracker/E2.json"),
    ("E3", "examples/customer_tracker/E3.json"),
)


def snapshot(workspace: Path) -> tuple[tuple[str, bytes], ...]:
    files = (
        (path.relative_to(workspace).as_posix(), path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    return tuple(sorted(files))


@pytest.mark.parametrize(("example", "packet_path"), CUSTOMER_TRACKER_EXAMPLES)
def test_customer_tracker_packets_validate_against_their_public_starts(
    example: str,
    packet_path: str,
) -> None:
    workspace = (
        REPOSITORY_ROOT
        / "references"
        / "customer-tracker"
        / "examples"
        / example
        / "start"
    )
    document = (PACKAGE_ROOT / packet_path).read_text()
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
    before = snapshot(workspace)

    report = validate_document(document, context)

    assert report.status == "valid", report.diagnostics
    assert report.ready
    assert report.unverified_requirements
    assert snapshot(workspace) == before


def test_e2_packet_spans_multiple_files() -> None:
    packet = json.loads(
        (PACKAGE_ROOT / "examples/customer_tracker/E2.json").read_text()
    )

    assert len(packet["file_changes"]) >= 3


def test_plain_python_packet_validates_without_django() -> None:
    workspace = PACKAGE_ROOT / "tests" / "fixtures" / "plain_python"
    document = (PACKAGE_ROOT / "examples/plain_python.json").read_text()
    context = ValidationContext(
        workspace=workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=workspace,
                kind="project",
                import_base="src",
            ),
        ),
    )
    before = snapshot(workspace)

    report = validate_document(document, context)

    assert report.status == "valid", report.diagnostics
    assert report.ready
    assert snapshot(workspace) == before
