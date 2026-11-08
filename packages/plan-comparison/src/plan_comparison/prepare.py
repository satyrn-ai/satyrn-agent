import ast
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from typed_packets import (
    ImportReference,
    Packet,
    PacketDecodeError,
    ValidationContext,
    build_index,
    decode_packet,
    validate_packet,
)
from typed_packets.contract import Produce
from typed_packets.paths import validate_file_access

from plan_comparison.contracts import (
    PacketExecution,
    Placement,
    WholeFileTarget,
)
from plan_comparison.manifest import (
    sha256_bytes,
    validate_packet_execution,
)
from plan_comparison.workspace import (
    FileSnapshot,
    WorkspaceError,
    WorkspaceSnapshot,
    restore_workspace,
    snapshot_workspace,
)


class PreparationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        diagnostics: tuple[object, ...] = (),
    ) -> None:
        self.code = code
        self.diagnostics = diagnostics
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PreparedPacket:
    packet: Packet
    execution: PacketExecution
    workspace: Path
    input_snapshot: WorkspaceSnapshot
    prepared_snapshot: WorkspaceSnapshot
    immutable_tests: tuple[FileSnapshot, ...]
    completed_slots: tuple[str, ...] = ()


def prepare_packet(
    packet_document: bytes,
    execution: PacketExecution,
    context: ValidationContext,
) -> PreparedPacket:
    try:
        packet_text = packet_document.decode("utf-8")
        packet = decode_packet(packet_text)
    except (UnicodeDecodeError, PacketDecodeError) as error:
        raise PreparationError(
            "packet_invalid", f"Packet could not be decoded: {error}"
        ) from error
    if sha256_bytes(packet_document) != execution.packet_sha256:
        raise PreparationError(
            "packet_hash_mismatch", "Packet bytes do not match the manifest hash."
        )
    if packet.packet_id != execution.packet_id:
        raise PreparationError(
            "packet_id_mismatch", "Packet ID does not match the manifest entry."
        )

    index = build_index(context)
    report = validate_packet(packet, context, index)
    if not report.ready:
        raise PreparationError(
            "packet_not_ready",
            f"Packet validation returned {report.status}.",
            report.diagnostics,
        )
    access_diagnostics = validate_file_access(packet, context.workspace, context)
    if access_diagnostics:
        raise PreparationError(
            "file_access_invalid",
            "Packet file-access validation failed.",
            access_diagnostics,
        )
    execution_diagnostics = validate_packet_execution(
        packet, execution, context.workspace
    )
    if execution_diagnostics:
        raise PreparationError(
            "execution_manifest_invalid",
            "Packet execution entry is invalid for this workspace.",
            execution_diagnostics,
        )
    if any(change.operation == "delete" for change in packet.file_changes):
        raise PreparationError(
            "delete_unsupported",
            "Packet file deletion is not supported by this preparation version.",
        )

    try:
        input_snapshot = snapshot_workspace(context.workspace)
    except WorkspaceError as error:
        raise PreparationError("workspace_snapshot_failed", str(error)) from error
    try:
        install_tests(packet, context.workspace)
        _create_declared_code_files(packet, execution, context.workspace)
        _prepare_modified_callables(packet, context.workspace)
        _apply_placements(packet, execution, context.workspace)
        prepared_snapshot = snapshot_workspace(context.workspace)
    except Exception as error:
        try:
            restore_workspace(context.workspace, input_snapshot)
        except WorkspaceError as restore_error:
            raise PreparationError(
                "restore_failed",
                "Preparation failed and workspace restore also failed: "
                f"{restore_error}",
            ) from error
        if isinstance(error, PreparationError):
            raise
        raise PreparationError("preparation_failed", str(error)) from error

    prepared_files = {file.path: file for file in prepared_snapshot.files}
    immutable_tests = tuple(
        prepared_files[test.path]
        for test in packet.tests
        if test.path in prepared_files
    )
    if len(immutable_tests) != len(packet.tests):
        try:
            restore_workspace(context.workspace, input_snapshot)
        except WorkspaceError as error:
            raise PreparationError("restore_failed", str(error)) from error
        raise PreparationError(
            "test_install_failed",
            "A declared test artifact is missing after preparation.",
        )
    return PreparedPacket(
        packet=packet,
        execution=execution,
        workspace=context.workspace,
        input_snapshot=input_snapshot,
        prepared_snapshot=prepared_snapshot,
        immutable_tests=immutable_tests,
    )


def _workspace_target(workspace: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(
        part in ("", ".", "..") for part in relative_path.split("/")
    ):
        raise PreparationError(
            "path_invalid", f"Noncanonical workspace path: {relative_path!r}"
        )
    target = workspace.joinpath(*pure.parts)
    current = workspace
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise PreparationError(
                "path_symlink", f"Workspace path contains a symlink: {relative_path}"
            )
    try:
        target.resolve(strict=False).relative_to(workspace.resolve())
    except ValueError as error:
        raise PreparationError(
            "path_escape", f"Workspace path escapes root: {relative_path}"
        ) from error
    return target


def install_tests(packet: Packet, workspace: Path) -> None:
    for test in packet.tests:
        target = _workspace_target(workspace, test.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(test.content, encoding="utf-8")


def _create_declared_code_files(
    packet: Packet,
    execution: PacketExecution,
    workspace: Path,
) -> None:
    test_paths = {test.path for test in packet.tests}
    whole_file_paths = {
        slot.path
        for slot in execution.slots
        if isinstance(slot.target, WholeFileTarget)
    }
    for change in packet.file_changes:
        if (
            change.operation != "create"
            or change.path in test_paths
            or change.path in whole_file_paths
        ):
            continue
        target = _workspace_target(workspace, change.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")


def _python_tree(source: bytes, path: str) -> ast.Module:
    try:
        return ast.parse(source, filename=path)
    except (SyntaxError, UnicodeDecodeError) as error:
        raise PreparationError(
            "source_parse_failed", f"Cannot prepare Python source {path}: {error}"
        ) from error


def _definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}

    def visit(statements: list[ast.stmt], prefix: str = "") -> None:
        for statement in statements:
            if isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                qualified_name = (
                    f"{prefix}.{statement.name}" if prefix else statement.name
                )
                definitions[qualified_name] = statement
                if isinstance(statement, ast.ClassDef):
                    visit(statement.body, qualified_name)
            elif isinstance(statement, ast.TypeAlias) and isinstance(
                statement.name, ast.Name
            ):
                definitions[statement.name.id] = statement

    visit(tree.body)
    return definitions


def _line_offsets(source: bytes) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _line_ending(source: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in source else b"\n"


def _function_stub(produced: Produce, indent: str, newline: str) -> str:
    lines = produced.declaration.splitlines()
    if not lines:
        raise PreparationError("declaration_empty", "Callable declaration is empty.")
    declaration_name = (
        lines[0].split("(", maxsplit=1)[0].removeprefix("async ").removeprefix("def ")
    )
    if declaration_name != produced.qualified_name.rsplit(".", maxsplit=1)[-1]:
        raise PreparationError(
            "declaration_name_mismatch",
            "Callable declaration name changed during preparation.",
        )
    body_indent = f"{indent}    "
    return newline.join(
        [
            *(f"{indent}{line}" for line in lines),
            f"{body_indent}raise NotImplementedError",
        ]
    )


def _render_produce(produced: Produce, indent: str, newline: str) -> str:
    lines = produced.declaration.splitlines()
    if not lines:
        raise PreparationError("declaration_empty", "Produced declaration is empty.")
    try:
        if produced.kind in ("function", "async_function"):
            parsed = ast.parse(f"{produced.declaration}{newline}    pass{newline}")
            definition = parsed.body[0]
            if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                raise PreparationError(
                    "declaration_kind", "Callable declaration is not a function."
                )
            if definition.name != produced.qualified_name.rsplit(".", maxsplit=1)[-1]:
                raise PreparationError(
                    "declaration_name_mismatch", "Callable name does not match packet."
                )
            return _function_stub(produced, indent, newline)
        if produced.kind == "class":
            parsed = ast.parse(f"{produced.declaration}{newline}    pass{newline}")
            definition = parsed.body[0]
            if not isinstance(definition, ast.ClassDef):
                raise PreparationError(
                    "declaration_kind", "Class declaration is not a class."
                )
            if definition.name != produced.qualified_name.rsplit(".", maxsplit=1)[-1]:
                raise PreparationError(
                    "declaration_name_mismatch", "Class name does not match packet."
                )
            return newline.join(
                [*(f"{indent}{line}" for line in lines), f"{indent}    pass"]
            )
        parsed = ast.parse(produced.declaration)
    except SyntaxError as error:
        raise PreparationError(
            "declaration_unsupported", f"Cannot prepare declaration: {error}"
        ) from error
    if not parsed.body:
        raise PreparationError(
            "declaration_empty", "Produced declaration has no syntax node."
        )
    return newline.join(f"{indent}{line}" for line in lines)


def _prepare_modified_callables(packet: Packet, workspace: Path) -> None:
    for produced in packet.produces:
        if produced.operation != "modify" or produced.kind not in (
            "function",
            "async_function",
        ):
            continue
        target = _workspace_target(workspace, produced.path)
        source = target.read_bytes()
        tree = _python_tree(source, produced.path)
        node = _definitions(tree).get(produced.qualified_name)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise PreparationError(
                "callable_target_missing",
                f"Modified callable {produced.qualified_name!r} is not present.",
            )
        expected = ast.parse(f"{produced.declaration}\n    pass\n").body[0]
        if not isinstance(expected, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise PreparationError(
                "declaration_kind", "Modified callable declaration is invalid."
            )
        if isinstance(expected, ast.AsyncFunctionDef) != isinstance(
            node, ast.AsyncFunctionDef
        ):
            raise PreparationError(
                "callable_kind_changed",
                "Cannot change sync/async kind during preparation.",
            )
        if node.end_lineno is None:
            raise PreparationError(
                "source_extent_missing", "Callable has no end source location."
            )
        offsets = _line_offsets(source)
        start = offsets[node.lineno - 1]
        end = offsets[node.end_lineno]
        indent_bytes = source[start : start + node.col_offset]
        indent = indent_bytes.decode("utf-8")
        newline_bytes = _line_ending(source)
        replacement = _function_stub(produced, indent, newline_bytes.decode("ascii"))
        replacement_bytes = replacement.encode("utf-8") + newline_bytes
        target.write_bytes(source[:start] + replacement_bytes + source[end:])


def _render_import(imported: ImportReference) -> str:
    module = imported.module
    if imported.name is None:
        line = f"import {module}"
        if imported.alias is not None:
            line += f" as {imported.alias}"
        return line
    line = f"from {module} import {imported.name}"
    if imported.alias is not None:
        line += f" as {imported.alias}"
    return line


def _already_imported(source: bytes, path: str, imported: ImportReference) -> bool:
    if not source:
        return False
    tree = _python_tree(source, path)
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            if imported.name is None and any(
                alias.name == imported.module and alias.asname == imported.alias
                for alias in statement.names
            ):
                return True
        elif isinstance(statement, ast.ImportFrom) and statement.level == 0:
            if statement.module != imported.module:
                continue
            if imported.name is None:
                return True
            if any(
                alias.name == imported.name and alias.asname == imported.alias
                for alias in statement.names
            ):
                return True
    return False


def _class_nodes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    classes: dict[str, ast.ClassDef] = {}

    def visit(statements: list[ast.stmt], prefix: str = "") -> None:
        for statement in statements:
            if isinstance(statement, ast.ClassDef):
                qualified_name = (
                    f"{prefix}.{statement.name}" if prefix else statement.name
                )
                classes[qualified_name] = statement
                visit(statement.body, qualified_name)

    visit(tree.body)
    return classes


def _anchor_offset(source: bytes, anchor: str, placement: Placement) -> int:
    encoded = anchor.encode("utf-8")
    matches = [match.start() for match in re.finditer(re.escape(encoded), source)]
    if len(matches) != 1:
        raise PreparationError(
            "placement_anchor_ambiguous",
            f"Anchor for {placement.placement_id!r} is not unique.",
        )
    match = matches[0]
    if placement.position == "before":
        return source.rfind(b"\n", 0, match) + 1
    if placement.position == "after":
        line_end = source.find(b"\n", match + len(encoded))
        return len(source) if line_end < 0 else line_end + 1
    raise PreparationError(
        "placement_anchor_operation", "Anchors require before or after placement."
    )


def _placement_offset(source: bytes, path: str, placement: Placement) -> int:
    if placement.target == "module":
        if placement.position == "start":
            return 0
        if placement.position == "end":
            return len(source)
        if placement.anchor is None:
            raise PreparationError(
                "placement_anchor_missing", "Anchored placement has no anchor."
            )
        return _anchor_offset(source, placement.anchor, placement)

    qualified_name = placement.target.removeprefix("class:")
    tree = _python_tree(source, path)
    node = _class_nodes(tree).get(qualified_name)
    if node is None or node.end_lineno is None:
        raise PreparationError(
            "placement_class_missing", f"Class {qualified_name!r} is not present."
        )
    offsets = _line_offsets(source)
    class_start = offsets[node.lineno - 1]
    class_end = offsets[node.end_lineno]
    if placement.position in ("before", "after"):
        if placement.anchor is None:
            raise PreparationError(
                "placement_anchor_missing", "Anchored placement has no anchor."
            )
        offset = _anchor_offset(source, placement.anchor, placement)
        if not class_start <= offset <= class_end:
            raise PreparationError(
                "placement_anchor_scope", "Class anchor is outside the target class."
            )
        return offset
    if not node.body or node.body[0].lineno == node.lineno:
        raise PreparationError(
            "placement_class_inline", "Inline class bodies are unsupported."
        )
    if placement.position == "start":
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and len(node.body) > 1
        ):
            first = node.body[1]
        return offsets[first.lineno - 1]
    if placement.position == "end":
        last = node.body[-1]
        if last.end_lineno is None:
            raise PreparationError(
                "placement_extent_missing", "Class member has no end location."
            )
        return offsets[last.end_lineno]
    raise PreparationError(
        "placement_position", f"Unsupported placement position {placement.position!r}."
    )


def _insert(source: bytes, offset: int, content: str) -> bytes:
    if not content:
        return source
    newline = _line_ending(source)
    encoded = (
        content.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", newline.decode())
        .encode("utf-8")
    )
    if not encoded.endswith(newline):
        encoded += newline
    prefix = source[:offset]
    suffix = source[offset:]
    if prefix and not prefix.endswith(b"\n"):
        prefix += newline
    return prefix + encoded + suffix


def _placement_content(
    packet: Packet,
    placement: Placement,
    source: bytes,
) -> str:
    newline = _line_ending(source).decode("ascii")
    if placement.kind == "imports":
        imports = [
            imported
            for imported in packet.imports
            if imported.path == placement.path
            and not _already_imported(source, placement.path, imported)
        ]
        return newline.join(_render_import(imported) for imported in imports)
    parent = (
        placement.target.removeprefix("class:") if placement.target != "module" else ""
    )
    declarations = [
        produced
        for produced in packet.produces
        if produced.path == placement.path
        and produced.operation == "create"
        and produced.qualified_name.rpartition(".")[0] == parent
    ]
    indent = ""
    if parent:
        tree = _python_tree(source, placement.path)
        class_node = _class_nodes(tree).get(parent)
        if class_node is None:
            raise PreparationError(
                "placement_class_missing", f"Class {parent!r} is not present."
            )
        indent = " " * (class_node.col_offset + 4)
    rendered = [_render_produce(produced, indent, newline) for produced in declarations]
    return f"{newline}{newline}".join(rendered)


def _apply_placements(
    packet: Packet, execution: PacketExecution, workspace: Path
) -> None:
    placements_by_path: dict[str, list[Placement]] = {}
    for placement in execution.placements:
        placements_by_path.setdefault(placement.path, []).append(placement)
    for path, placements in placements_by_path.items():
        target = _workspace_target(workspace, path)
        source = target.read_bytes() if target.exists() else b""
        for placement in placements:
            content = _placement_content(packet, placement, source)
            if not content:
                continue
            offset = _placement_offset(source, path, placement)
            source = _insert(source, offset, content)
        if path.endswith(".py"):
            _python_tree(source, path)
        target.write_bytes(source)

    test_paths = {test.path for test in packet.tests}
    for imported in packet.imports:
        if imported.path in test_paths:
            continue
        source_path = _workspace_target(workspace, imported.path)
        source = source_path.read_bytes()
        if _already_imported(source, imported.path, imported):
            continue
        if not any(
            placement.path == imported.path and placement.kind == "imports"
            for placement in execution.placements
        ):
            raise PreparationError(
                "import_placement_missing",
                f"Import for {imported.module!r} is not already present and has "
                "no placement.",
            )
