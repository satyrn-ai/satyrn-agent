import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    content: bytes
    mode: int


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    path: str
    mode: int


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    files: tuple[FileSnapshot, ...]
    directories: tuple[DirectorySnapshot, ...]


def _workspace_root(root: Path) -> Path:
    if root.is_symlink():
        raise WorkspaceError("Workspace root must not be a symlink.")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise WorkspaceError(f"Workspace root is unavailable: {error}") from error
    if not resolved.is_dir():
        raise WorkspaceError("Workspace root must be a directory.")
    return resolved


def snapshot_workspace(root: Path) -> WorkspaceSnapshot:
    workspace = _workspace_root(root)
    files: list[FileSnapshot] = []
    directories: list[DirectorySnapshot] = []
    pending = [workspace]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise WorkspaceError(f"Cannot inspect {directory}: {error}") from error
        for child in children:
            try:
                metadata = child.lstat()
            except OSError as error:
                raise WorkspaceError(f"Cannot inspect {child}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise WorkspaceError(
                    f"Symlinks are not allowed in a workspace: {child}"
                )
            relative = child.relative_to(workspace).as_posix()
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(DirectorySnapshot(path=relative, mode=mode))
                pending.append(child)
            elif stat.S_ISREG(metadata.st_mode):
                try:
                    content = child.read_bytes()
                except OSError as error:
                    raise WorkspaceError(f"Cannot read {child}: {error}") from error
                files.append(FileSnapshot(path=relative, content=content, mode=mode))
            else:
                raise WorkspaceError(
                    f"Unsupported filesystem entry in workspace: {child}"
                )
    return WorkspaceSnapshot(
        files=tuple(sorted(files, key=lambda item: item.path)),
        directories=tuple(sorted(directories, key=lambda item: item.path)),
    )


def workspace_sha256(snapshot: WorkspaceSnapshot) -> str:
    digest = hashlib.sha256()
    for directory in snapshot.directories:
        encoded_path = directory.path.encode("utf-8")
        digest.update(b"d")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(directory.mode.to_bytes(4, "big"))
    for file in snapshot.files:
        encoded_path = file.path.encode("utf-8")
        digest.update(b"f")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(file.mode.to_bytes(4, "big"))
        digest.update(hashlib.sha256(file.content).digest())
    return digest.hexdigest()


def restore_workspace(root: Path, snapshot: WorkspaceSnapshot) -> None:
    workspace = _workspace_root(root)
    current = snapshot_workspace(workspace)
    original_files = {item.path: item for item in snapshot.files}
    original_directories = {item.path: item for item in snapshot.directories}
    current_files = {item.path: item for item in current.files}
    current_directories = {item.path: item for item in current.directories}

    for relative_path in sorted(set(current_files) - set(original_files), reverse=True):
        _safe_workspace_path(workspace, relative_path).unlink()

    for relative_path in sorted(
        original_directories, key=lambda value: value.count("/")
    ):
        target = _safe_workspace_path(workspace, relative_path)
        if target.exists() and not target.is_dir():
            target.unlink()
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(original_directories[relative_path].mode)

    for relative_path, file in original_files.items():
        target = _safe_workspace_path(workspace, relative_path)
        if target.exists() and target.is_dir():
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.content)
        target.chmod(file.mode)

    for relative_path in sorted(
        set(current_directories) - set(original_directories),
        key=lambda value: value.count("/"),
        reverse=True,
    ):
        target = _safe_workspace_path(workspace, relative_path)
        if target.exists():
            target.rmdir()

    restored = snapshot_workspace(workspace)
    if restored != snapshot:
        raise WorkspaceError(
            "Workspace restore did not reproduce the original snapshot."
        )


def _safe_workspace_path(workspace: Path, relative_path: str) -> Path:
    parts = relative_path.split("/")
    if not relative_path or any(part in ("", ".", "..") for part in parts):
        raise WorkspaceError(f"Noncanonical snapshot path: {relative_path!r}")
    target = workspace.joinpath(*parts)
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise WorkspaceError(
                f"Symlink appeared during workspace restore: {current}"
            )
    try:
        target.resolve(strict=False).relative_to(workspace.resolve())
    except ValueError as error:
        raise WorkspaceError(
            f"Snapshot path escapes the workspace: {relative_path}"
        ) from error
    return target
