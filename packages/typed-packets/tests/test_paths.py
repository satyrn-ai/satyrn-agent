import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.packet_factory import valid_packet
from typed_packets.contract import (
    FileChange,
    Packet,
    decode_packet,
)
from typed_packets.contract import (
    TestArtifact as PacketTestArtifact,
)
from typed_packets.paths import validate_file_access


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "domain.py").write_text("class Contact: ...\n")
    (tmp_path / "tests").mkdir()
    return tmp_path


def checked_packet() -> Packet:
    return decode_packet(json.dumps(valid_packet()))


def test_file_access_accepts_create_modify_and_existing_reads(
    workspace: Path,
) -> None:
    diagnostics = validate_file_access(checked_packet(), workspace)

    assert diagnostics == ()


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/tmp/escape.py", "C:/escape.py", "app\\domain.py", "app/*.py"],
)
def test_file_access_rejects_noncanonical_paths(workspace: Path, path: str) -> None:
    packet = replace(checked_packet(), readable_files=(path,), consumes=())

    diagnostics = validate_file_access(packet, workspace)

    assert diagnostics
    assert diagnostics[0].field == "/readable_files/0"


def test_file_access_rejects_symlink_components(workspace: Path) -> None:
    outside = workspace.parent / "outside.py"
    outside.write_text("value = 1\n")
    (workspace / "linked.py").symlink_to(outside)
    packet = replace(checked_packet(), readable_files=("linked.py",), consumes=())

    diagnostics = validate_file_access(packet, workspace)

    assert diagnostics
    assert diagnostics[0].code == "path.symlink"


def test_file_access_rejects_broken_symlink_components(workspace: Path) -> None:
    (workspace / "broken.py").symlink_to(workspace / "missing.py")
    packet = replace(checked_packet(), readable_files=("broken.py",), consumes=())

    diagnostics = validate_file_access(packet, workspace)

    assert diagnostics
    assert diagnostics[0].code == "path.symlink"


def test_file_access_rejects_create_target_that_already_exists(
    workspace: Path,
) -> None:
    (workspace / "tests" / "test_domain.py").write_text("# already here\n")

    diagnostics = validate_file_access(checked_packet(), workspace)

    assert any(item.code == "path.create_exists" for item in diagnostics)


def test_file_access_rejects_symlinked_create_parent(workspace: Path) -> None:
    outside = workspace / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    packet = checked_packet()
    path = "linked/new_test.py"
    packet = replace(
        packet,
        file_changes=(
            packet.file_changes[0],
            FileChange(path=path, operation="create"),
        ),
        tests=(PacketTestArtifact(path=path, operation="create", content=""),),
    )

    diagnostics = validate_file_access(packet, workspace)

    assert any(item.code == "path.symlink" for item in diagnostics)


def test_file_access_allows_missing_parent_directories_for_creates(
    workspace: Path,
) -> None:
    packet = checked_packet()
    new_path = "tests/new/nested/test_domain.py"
    packet = replace(
        packet,
        file_changes=(
            packet.file_changes[0],
            FileChange(path=new_path, operation="create"),
        ),
        tests=(PacketTestArtifact(path=new_path, operation="create", content=""),),
    )

    assert validate_file_access(packet, workspace) == ()


def test_file_access_rejects_directories_as_readable_files(workspace: Path) -> None:
    packet = replace(checked_packet(), readable_files=("app",), consumes=())

    diagnostics = validate_file_access(packet, workspace)

    assert any(item.code == "path.not_regular_file" for item in diagnostics)


def test_file_access_rejects_case_normalized_path_collisions(workspace: Path) -> None:
    packet = replace(
        checked_packet(),
        readable_files=("app/domain.py", "app/Domain.py"),
    )

    diagnostics = validate_file_access(packet, workspace)

    assert any(item.code == "path.case_collision" for item in diagnostics)


def test_file_access_rejects_file_ancestor_conflicts(workspace: Path) -> None:
    packet = checked_packet()
    nested_file = "app/domain.py/child.py"
    packet = replace(
        packet,
        file_changes=packet.file_changes
        + (FileChange(path=nested_file, operation="create"),),
    )

    diagnostics = validate_file_access(packet, workspace)

    assert any(item.code == "path.file_ancestor_conflict" for item in diagnostics)


def test_file_access_requires_gate_working_directory_to_be_a_directory(
    workspace: Path,
) -> None:
    packet = checked_packet()
    packet = replace(packet, gates=(replace(packet.gates[0], cwd="app/domain.py"),))

    diagnostics = validate_file_access(packet, workspace)

    assert any(item.code == "path.not_directory" for item in diagnostics)
