import os
import re
import stat
from pathlib import Path

from typed_packets.contract import Diagnostic, Packet
from typed_packets.index import ValidationContext

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_GLOB_CHARACTERS = frozenset("*?[]{}")


def _pointer(parent: str, component: str | int) -> str:
    escaped = str(component).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _diagnostic(
    code: str,
    field: str,
    message: str,
    *,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        outcome="invalid",
        field=field,
        message=message,
        path=path,
    )


def _canonical_components(
    value: str,
    field: str,
    *,
    allow_dot: bool = False,
) -> tuple[str, ...] | Diagnostic:
    if not value:
        return _diagnostic("path.empty", field, "Path must not be empty.", path=value)
    if value == "." and allow_dot:
        return ()
    if "\\" in value:
        return _diagnostic(
            "path.backslash", field, "Use POSIX path separators.", path=value
        )
    if value.startswith("/") or _WINDOWS_DRIVE.match(value):
        return _diagnostic(
            "path.absolute", field, "Path must be workspace-relative.", path=value
        )
    if any(character in _GLOB_CHARACTERS for character in value):
        return _diagnostic(
            "path.glob", field, "Glob characters are not allowed.", path=value
        )
    components = tuple(value.split("/"))
    if any(not component for component in components):
        return _diagnostic(
            "path.empty_component",
            field,
            "Path components must not be empty.",
            path=value,
        )
    if any(component in {".", ".."} for component in components):
        return _diagnostic(
            "path.dot_component",
            field,
            "Dot path components are not allowed.",
            path=value,
        )
    if "\x00" in value:
        return _diagnostic(
            "path.nul", field, "NUL is not allowed in paths.", path=value
        )
    return components


def _inspect_path(
    root: Path,
    components: tuple[str, ...],
    field: str,
    raw_path: str,
) -> tuple[Path | None, bool, os.stat_result | None, Diagnostic | None]:
    current = root
    if not components:
        try:
            return root, True, root.stat(), None
        except OSError as error:
            return (
                None,
                False,
                None,
                _diagnostic(
                    "path.workspace",
                    field,
                    f"Cannot inspect workspace: {error}.",
                    path=raw_path,
                ),
            )
    for index, component in enumerate(components):
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return current, False, None, None
        except OSError as error:
            return (
                None,
                False,
                None,
                _diagnostic(
                    "path.unavailable",
                    field,
                    f"Cannot inspect path: {error}.",
                    path=raw_path,
                ),
            )
        if stat.S_ISLNK(metadata.st_mode):
            return (
                None,
                False,
                None,
                _diagnostic(
                    "path.symlink",
                    field,
                    "Symlink path components are not allowed.",
                    path=raw_path,
                ),
            )
        if index < len(components) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return (
                None,
                False,
                None,
                _diagnostic(
                    "path.ancestor_not_directory",
                    field,
                    "Every existing parent component must be a directory.",
                    path=raw_path,
                ),
            )
    try:
        current.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return (
            None,
            False,
            None,
            _diagnostic(
                "path.outside_workspace",
                field,
                "Path is not contained in the workspace.",
                path=raw_path,
            ),
        )
    return current, True, metadata, None


def _validate_access_path(
    root: Path,
    raw_path: str,
    field: str,
    access: str,
    *,
    allow_dot: bool = False,
) -> tuple[Diagnostic, ...]:
    components = _canonical_components(raw_path, field, allow_dot=allow_dot)
    if isinstance(components, Diagnostic):
        return (components,)
    target, exists, metadata, error = _inspect_path(root, components, field, raw_path)
    if error is not None:
        return (error,)
    if target is None:
        return ()
    if access == "read":
        if not exists:
            return (
                _diagnostic(
                    "path.missing",
                    field,
                    "Readable file does not exist.",
                    path=raw_path,
                ),
            )
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            return (
                _diagnostic(
                    "path.not_regular_file",
                    field,
                    "Expected an existing regular file.",
                    path=raw_path,
                ),
            )
    elif access == "create":
        if exists:
            return (
                _diagnostic(
                    "path.create_exists",
                    field,
                    "Create target already exists.",
                    path=raw_path,
                ),
            )
    elif access in {"modify", "delete"}:
        if not exists:
            return (
                _diagnostic(
                    "path.missing",
                    field,
                    f"{access.capitalize()} target does not exist.",
                    path=raw_path,
                ),
            )
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            return (
                _diagnostic(
                    "path.not_regular_file",
                    field,
                    "Expected an existing regular file.",
                    path=raw_path,
                ),
            )
    elif access == "directory":
        if not exists or metadata is None or not stat.S_ISDIR(metadata.st_mode):
            return (
                _diagnostic(
                    "path.not_directory",
                    field,
                    "Gate working directory must exist as a directory.",
                    path=raw_path,
                ),
            )
    return ()


def _file_path_entries(packet: Packet) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    entries.extend(
        (path, _pointer("/readable_files", index))
        for index, path in enumerate(packet.readable_files)
    )
    entries.extend(
        (item.path, _pointer(_pointer("/file_changes", index), "path"))
        for index, item in enumerate(packet.file_changes)
    )
    entries.extend(
        (
            item.source.path,
            _pointer(_pointer(_pointer("/consumes", index), "source"), "path"),
        )
        for index, item in enumerate(packet.consumes)
        if item.source.root_id == "workspace"
    )
    entries.extend(
        (item.path, _pointer(_pointer("/produces", index), "path"))
        for index, item in enumerate(packet.produces)
    )
    entries.extend(
        (item.path, _pointer(_pointer("/imports", index), "path"))
        for index, item in enumerate(packet.imports)
    )
    entries.extend(
        (item.path, _pointer(_pointer("/tests", index), "path"))
        for index, item in enumerate(packet.tests)
    )
    return tuple(entries)


def _declaration_collisions(packet: Packet) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    entries = _file_path_entries(packet)
    seen_case: dict[str, tuple[str, str]] = {}
    unique_paths: dict[str, str] = {}
    for path, field in entries:
        canonical = _canonical_components(path, field)
        if isinstance(canonical, Diagnostic):
            continue
        folded = path.casefold()
        previous = seen_case.get(folded)
        if previous is not None and previous[0] != path:
            diagnostics.append(
                _diagnostic(
                    "path.case_collision",
                    field,
                    f"Path collides by case with {previous[0]!r}.",
                    path=path,
                )
            )
        else:
            seen_case[folded] = path, field
        unique_paths.setdefault(path, field)

    path_items = tuple(unique_paths.items())
    for path, field in path_items:
        components = path.split("/")
        for other, _ in path_items:
            other_components = other.split("/")
            if (
                len(components) < len(other_components)
                and other_components[: len(components)] == components
            ):
                diagnostics.append(
                    _diagnostic(
                        "path.file_ancestor_conflict",
                        field,
                        f"A declared file path {path!r} is an ancestor of {other!r}.",
                        path=path,
                    )
                )
                break
    return tuple(diagnostics)


def validate_file_access(
    packet: Packet,
    workspace: Path,
    context: ValidationContext | None = None,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    try:
        root = workspace.resolve(strict=True)
    except OSError as error:
        return (
            _diagnostic("path.workspace", "", f"Workspace is unavailable: {error}."),
        )
    if not root.is_dir():
        return (_diagnostic("path.workspace", "", "Workspace must be a directory."),)

    for index, path in enumerate(packet.readable_files):
        diagnostics.extend(
            _validate_access_path(
                root, path, _pointer("/readable_files", index), "read"
            )
        )
    for index, change in enumerate(packet.file_changes):
        diagnostics.extend(
            _validate_access_path(
                root,
                change.path,
                _pointer(_pointer("/file_changes", index), "path"),
                change.operation,
            )
        )
    for index, item in enumerate(packet.consumes):
        field = _pointer(_pointer(_pointer("/consumes", index), "source"), "path")
        components = _canonical_components(item.source.path, field)
        if isinstance(components, Diagnostic):
            diagnostics.append(components)
            continue
        source_root = None
        if context is not None:
            source_root = next(
                (
                    root_record
                    for root_record in context.roots
                    if root_record.root_id == item.source.root_id
                ),
                None,
            )
            if source_root is None:
                diagnostics.append(
                    _diagnostic(
                        "path.consume_root_unconfigured",
                        _pointer(
                            _pointer(_pointer("/consumes", index), "source"),
                            "root_id",
                        ),
                        "Consumed source root is not configured.",
                        path=item.source.path,
                    )
                )
                continue
            if source_root.kind in {"dependency", "stub"}:
                continue
        if item.source.root_id != "workspace" and source_root is None:
            diagnostics.append(
                _diagnostic(
                    "path.consume_root_unconfigured",
                    _pointer(
                        _pointer(_pointer("/consumes", index), "source"), "root_id"
                    ),
                    "Non-workspace source roots require explicit configuration.",
                    path=item.source.path,
                )
            )
            continue
        source_path = item.source.path
        if source_root is not None:
            try:
                root_path = source_root.path.resolve(strict=True)
                source_path = (
                    root_path.joinpath(*components).relative_to(root).as_posix()
                )
            except (OSError, ValueError):
                diagnostics.append(
                    _diagnostic(
                        "path.consume_outside_workspace",
                        field,
                        "Project source must resolve within the workspace.",
                        path=item.source.path,
                    )
                )
                continue
            diagnostics.extend(_validate_access_path(root, source_path, field, "read"))
        if source_path not in packet.readable_files:
            diagnostics.append(
                _diagnostic(
                    "path.consume_not_readable",
                    field,
                    "Workspace symbols must be consumed from an explicitly "
                    "readable file.",
                    path=item.source.path,
                )
            )
    for index, item in enumerate(packet.produces):
        field = _pointer(_pointer("/produces", index), "path")
        components = _canonical_components(item.path, field)
        if isinstance(components, Diagnostic):
            diagnostics.append(components)
    for index, item in enumerate(packet.imports):
        field = _pointer(_pointer("/imports", index), "path")
        components = _canonical_components(item.path, field)
        if isinstance(components, Diagnostic):
            diagnostics.append(components)
    for index, item in enumerate(packet.tests):
        field = _pointer(_pointer("/tests", index), "path")
        components = _canonical_components(item.path, field)
        if isinstance(components, Diagnostic):
            diagnostics.append(components)
    for index, gate in enumerate(packet.gates):
        field = _pointer(_pointer("/gates", index), "cwd")
        diagnostics.extend(
            _validate_access_path(root, gate.cwd, field, "directory", allow_dot=True)
        )

    changes = {change.path: change.operation for change in packet.file_changes}
    for index, path in enumerate(packet.readable_files):
        if changes.get(path) == "create":
            diagnostics.append(
                _diagnostic(
                    "path.create_readable",
                    _pointer("/readable_files", index),
                    "A create target cannot also be declared as currently readable.",
                    path=path,
                )
            )
    for index, item in enumerate(packet.consumes):
        if (
            item.source.root_id == "workspace"
            and changes.get(item.source.path) == "create"
            and item.source.path not in packet.readable_files
        ):
            diagnostics.append(
                _diagnostic(
                    "path.consume_created",
                    _pointer(_pointer("/consumes", index), "source/path"),
                    "Existing symbols cannot be consumed from a file "
                    "declared for creation.",
                    path=item.source.path,
                )
            )

    diagnostics.extend(_declaration_collisions(packet))
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.field,
                item.code,
                item.path or "",
                item.symbol or "",
                item.line or 0,
            ),
        )
    )
