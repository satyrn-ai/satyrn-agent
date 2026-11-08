from pathlib import Path

import pytest

from plan_comparison.workspace import (
    WorkspaceError,
    restore_workspace,
    snapshot_workspace,
    workspace_sha256,
)


def test_snapshot_restore_recovers_exact_files_directories_and_modes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "nested" / "kept").mkdir(parents=True)
    original = workspace / "app.py"
    original.write_text("value = 1\n")
    retained = workspace / "nested" / "kept" / "data.txt"
    retained.write_bytes(b"original")
    retained.chmod(0o751)
    before = snapshot_workspace(workspace)

    original.write_text("value = 2\n")
    retained.unlink()
    (workspace / "nested" / "new" / "deeper").mkdir(parents=True)
    (workspace / "nested" / "new" / "deeper" / "created.txt").write_text("new")

    restore_workspace(workspace, before)

    assert snapshot_workspace(workspace) == before
    assert original.read_text() == "value = 1\n"
    assert retained.stat().st_mode & 0o777 == 0o751
    assert not (workspace / "nested" / "new").exists()


def test_snapshot_refuses_symlinks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (workspace / "linked.txt").symlink_to(outside)

    with pytest.raises(WorkspaceError, match="Symlinks"):
        snapshot_workspace(workspace)


def test_restore_refuses_untrusted_symlink_without_modifying_other_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = workspace / "original.txt"
    file_path.write_text("keep")
    before = snapshot_workspace(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    (workspace / "unexpected-link").symlink_to(outside)

    with pytest.raises(WorkspaceError, match="Symlinks"):
        restore_workspace(workspace, before)

    assert file_path.read_text() == "keep"
    assert outside.read_text() == "untouched"


def test_workspace_digest_includes_file_content_and_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = workspace / "script.py"
    file_path.write_text("pass\n")
    first = workspace_sha256(snapshot_workspace(workspace))

    file_path.chmod(0o751)
    second = workspace_sha256(snapshot_workspace(workspace))
    file_path.write_text("raise SystemExit\n")
    third = workspace_sha256(snapshot_workspace(workspace))

    assert len({first, second, third}) == 3
