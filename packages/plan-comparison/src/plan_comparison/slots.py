import ast
import re
import textwrap
from dataclasses import replace
from pathlib import PurePosixPath

from typed_packets import Packet
from typed_packets.contract import Produce

from plan_comparison.contracts import (
    ByteExtent,
    CallableBodyExtent,
    CallableBodyTarget,
    Slot,
    StructuralExtent,
    StructuralTarget,
    TextAnchorTarget,
    WholeFileExtent,
    WholeFileTarget,
)
from plan_comparison.manifest import sha256_bytes, slot_preimage_bytes
from plan_comparison.prepare import (
    PreparedPacket,
    _definitions,
    _line_ending,
    _line_offsets,
    _workspace_target,
)
from plan_comparison.workspace import (
    FileSnapshot,
    WorkspaceError,
    WorkspaceSnapshot,
    restore_workspace,
    snapshot_workspace,
)


class SlotEditError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def apply_slot_edit(
    prepared: PreparedPacket,
    slot_id: str,
    content: str,
) -> PreparedPacket:
    slot = next(
        (item for item in prepared.execution.slots if item.slot_id == slot_id), None
    )
    if slot is None:
        raise SlotEditError("slot_unknown", f"Slot {slot_id!r} is not in this packet.")
    if slot_id in prepared.completed_slots:
        raise SlotEditError(
            "slot_completed", f"Slot {slot_id!r} has already been filled."
        )
    try:
        before = snapshot_workspace(prepared.workspace)
    except WorkspaceError as error:
        raise SlotEditError("workspace_snapshot_failed", str(error)) from error
    if before != prepared.prepared_snapshot:
        raise SlotEditError(
            "workspace_changed",
            "Workspace changed outside the approved packet edits.",
        )
    _verify_immutable_tests(prepared.immutable_tests, before)
    _verify_slot_preimage(prepared, slot)
    try:
        _apply_edit(prepared, slot, content)
        after = snapshot_workspace(prepared.workspace)
        _verify_only_slot_path_changed(before, after, slot.path)
        _verify_immutable_tests(prepared.immutable_tests, after)
    except Exception as error:
        try:
            restore_workspace(prepared.workspace, before)
        except WorkspaceError as restore_error:
            raise SlotEditError(
                "restore_failed",
                "Slot edit failed and its transaction could not be restored: "
                f"{restore_error}",
            ) from error
        if isinstance(error, SlotEditError):
            raise
        raise SlotEditError("slot_edit_failed", str(error)) from error
    return replace(
        prepared,
        prepared_snapshot=after,
        completed_slots=prepared.completed_slots + (slot_id,),
    )


def _snapshot_files(snapshot: WorkspaceSnapshot) -> dict[str, FileSnapshot]:
    return {item.path: item for item in snapshot.files}


def _verify_immutable_tests(
    immutable_tests: tuple[FileSnapshot, ...], snapshot: WorkspaceSnapshot
) -> None:
    files = _snapshot_files(snapshot)
    for expected in immutable_tests:
        if files.get(expected.path) != expected:
            raise SlotEditError(
                "host_test_modified",
                f"Host-installed visible test changed: {expected.path}",
            )


def _verify_slot_preimage(prepared: PreparedPacket, slot: Slot) -> None:
    original = _snapshot_files(prepared.input_snapshot).get(slot.path)
    preimage = slot_preimage_bytes(
        prepared.packet, slot, original.content if original is not None else None
    )
    actual_hash = sha256_bytes(preimage) if preimage is not None else None
    if actual_hash != slot.preimage_sha256:
        raise SlotEditError(
            "stale_preimage",
            f"Slot {slot.slot_id!r} target preimage does not match the "
            "packet-start workspace.",
        )


def _verify_only_slot_path_changed(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    path: str,
) -> None:
    before_files = _snapshot_files(before)
    after_files = _snapshot_files(after)
    for file_path in set(before_files) | set(after_files):
        if file_path != path and before_files.get(file_path) != after_files.get(
            file_path
        ):
            raise SlotEditError(
                "locked_file_changed",
                f"Edit changed a file outside its slot: {file_path}",
            )
    allowed_directories = {
        parent.as_posix()
        for parent in PurePosixPath(path).parents
        if parent != PurePosixPath(".")
    }
    before_directories = {item.path: item for item in before.directories}
    after_directories = {item.path: item for item in after.directories}
    for directory in set(before_directories) | set(after_directories):
        if directory in allowed_directories:
            if directory in before_directories and before_directories[
                directory
            ] != after_directories.get(directory):
                raise SlotEditError(
                    "locked_directory_changed", f"Parent directory changed: {directory}"
                )
            continue
        if before_directories.get(directory) != after_directories.get(directory):
            raise SlotEditError(
                "locked_directory_changed",
                f"Edit changed a directory outside its slot: {directory}",
            )


def _apply_edit(prepared: PreparedPacket, slot: Slot, content: str) -> None:
    target = _workspace_target(prepared.workspace, slot.path)
    if isinstance(slot.target, WholeFileTarget):
        if not isinstance(slot.extent, WholeFileExtent) or target.exists():
            raise SlotEditError(
                "whole_file_target", "Whole-file creation target is not empty."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        if slot.path.endswith(".py"):
            _parse_edit_source(encoded, slot.path)
        target.write_bytes(encoded)
        return
    if not target.is_file():
        raise SlotEditError(
            "slot_target_missing", f"Slot target does not exist: {slot.path}"
        )
    source = target.read_bytes()
    if isinstance(slot.target, CallableBodyTarget):
        if not isinstance(slot.extent, CallableBodyExtent):
            raise SlotEditError(
                "slot_extent", "Callable slots require callable-body extents."
            )
        updated = _replace_callable_body(prepared.packet, slot, source, content)
    elif isinstance(slot.target, StructuralTarget):
        if not isinstance(slot.extent, StructuralExtent):
            raise SlotEditError(
                "slot_extent", "Structural slots require structural extents."
            )
        updated = _replace_structural_region(prepared.packet, slot, source, content)
    elif isinstance(slot.target, TextAnchorTarget):
        if not isinstance(slot.extent, ByteExtent):
            raise SlotEditError(
                "slot_extent", "Text-anchor slots require byte extents."
            )
        updated = _replace_text_anchor(slot, source, content)
    else:
        raise SlotEditError("slot_target", "Unsupported slot target.")
    if slot.path.endswith(".py"):
        _parse_edit_source(updated, slot.path)
    target.write_bytes(updated)


def _parse_edit_source(source: bytes, path: str) -> ast.Module:
    try:
        return ast.parse(source, filename=path)
    except (SyntaxError, UnicodeDecodeError) as error:
        raise SlotEditError(
            "slot_syntax", f"Edited Python source is invalid: {error}"
        ) from error


def _function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[object, ...]:
    return (
        type(node),
        node.name,
        ast.dump(node.args, include_attributes=False),
        ast.dump(node.returns, include_attributes=False) if node.returns else None,
        tuple(
            ast.dump(parameter, include_attributes=False)
            for parameter in node.type_params
        ),
    )


def _expected_function_signature(produced: Produce) -> tuple[object, ...]:
    try:
        tree = ast.parse(f"{produced.declaration}\n    pass\n")
    except SyntaxError as error:
        raise SlotEditError("declaration_invalid", str(error)) from error
    node = tree.body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise SlotEditError(
            "declaration_kind", "Callable target has a non-function declaration."
        )
    return _function_signature(node)


def _indented_body(content: str, indent: bytes, newline: bytes) -> bytes:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise SlotEditError(
            "slot_body_empty", "Callable and structural body edits cannot be empty."
        )
    first_line = next(line for line in normalized.splitlines() if line.strip())
    if first_line[:1].isspace():
        raise SlotEditError(
            "slot_body_indentation",
            "Body content must be unindented relative to the selected slot.",
        )
    try:
        wrapped = "def __packet_slot__():\n" + textwrap.indent(normalized, "    ")
        ast.parse(wrapped)
    except SyntaxError as error:
        raise SlotEditError(
            "slot_body_syntax", f"Body content is not valid Python: {error}"
        ) from error
    pieces = normalized.split("\n")
    encoded_lines = [indent + line.encode("utf-8") if line else b"" for line in pieces]
    body = newline.join(encoded_lines)
    return body if body.endswith(newline) else body + newline


def _body_extent(
    source: bytes,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> tuple[int, int, bytes]:
    if not node.body or node.end_lineno is None:
        raise SlotEditError("slot_body_missing", "Target has no concrete body to edit.")
    first = node.body[0]
    last = node.body[-1]
    if first.lineno == node.lineno or last.end_lineno is None:
        raise SlotEditError(
            "slot_body_inline", "Inline compound statements are unsupported."
        )
    offsets = _line_offsets(source)
    start = offsets[first.lineno - 1]
    end = offsets[last.end_lineno]
    line = source[offsets[first.lineno - 1] : offsets[first.lineno]]
    indent = line[: len(line) - len(line.lstrip(b" \t"))]
    return start, end, indent


def _replace_callable_body(
    packet: Packet,
    slot: Slot,
    source: bytes,
    content: str,
) -> bytes:
    if not isinstance(slot.target, CallableBodyTarget):
        raise SlotEditError("slot_target", "Callable edit has a non-callable target.")
    tree = _parse_edit_source(source, slot.path)
    node = _definitions(tree).get(slot.target.qualified_name)
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise SlotEditError(
            "callable_missing", f"Callable {slot.target.qualified_name!r} is missing."
        )
    produced = next(
        (
            item
            for item in packet.produces
            if item.path == slot.path
            and item.qualified_name == slot.target.qualified_name
        ),
        None,
    )
    if produced is None:
        raise SlotEditError(
            "callable_unplanned", "Callable target is not a packet production."
        )
    if _function_signature(node) != _expected_function_signature(produced):
        raise SlotEditError(
            "signature_changed",
            "Prepared callable signature differs from the frozen declaration.",
        )
    first_line = next(line.strip() for line in content.splitlines() if line.strip())
    declared_name = produced.qualified_name.rsplit(".", maxsplit=1)[-1]
    if re.match(rf"(?:async\s+)?def\s+{re.escape(declared_name)}\s*\(", first_line):
        raise SlotEditError(
            "callable_signature_returned",
            "Worker returned a signature instead of a body.",
        )
    start, end, indent = _body_extent(source, node)
    body = _indented_body(content, indent, _line_ending(source))
    return source[:start] + body + source[end:]


def _replace_structural_region(
    packet: Packet,
    slot: Slot,
    source: bytes,
    content: str,
) -> bytes:
    if not isinstance(slot.target, StructuralTarget) or not isinstance(
        slot.extent, StructuralExtent
    ):
        raise SlotEditError(
            "slot_target", "Structural edit has an incompatible target or extent."
        )
    tree = _parse_edit_source(source, slot.path)
    node = _definitions(tree).get(slot.target.qualified_name)
    if isinstance(node, ast.ClassDef) and slot.extent.region == "body":
        start, end, indent = _body_extent(source, node)
        body = _indented_body(content, indent, _line_ending(source))
        return source[:start] + body + source[end:]
    if isinstance(node, ast.TypeAlias) and slot.extent.region == "definition":
        try:
            replacement = ast.parse(content)
        except SyntaxError as error:
            raise SlotEditError(
                "alias_syntax", f"Type alias edit is invalid: {error}"
            ) from error
        if len(replacement.body) != 1 or not isinstance(
            replacement.body[0], ast.TypeAlias
        ):
            raise SlotEditError(
                "alias_target",
                "Alias slot must contain exactly one type alias statement.",
            )
        replacement_node = replacement.body[0]
        if (
            not isinstance(replacement_node.name, ast.Name)
            or replacement_node.name.id != node.name.id
        ):
            raise SlotEditError(
                "alias_name_changed", "Alias name is locked by the packet declaration."
            )
        if node.end_lineno is None:
            raise SlotEditError(
                "alias_extent_missing", "Type alias has no source extent."
            )
        offsets = _line_offsets(source)
        start = offsets[node.lineno - 1]
        end = offsets[node.end_lineno]
        return (
            source[:start]
            + content.encode("utf-8")
            + _line_ending(source)
            + source[end:]
        )
    raise SlotEditError(
        "structural_target_unsupported",
        "Structural edits must target a class body or a type-alias definition.",
    )


def _replace_text_anchor(slot: Slot, source: bytes, content: str) -> bytes:
    if not isinstance(slot.target, TextAnchorTarget) or not isinstance(
        slot.extent, ByteExtent
    ):
        raise SlotEditError(
            "slot_target", "Text-anchor edit has an incompatible target or extent."
        )
    anchor = slot.target.anchor.encode("utf-8")
    matches = [match.start() for match in re.finditer(re.escape(anchor), source)]
    if len(matches) != 1:
        raise SlotEditError(
            "anchor_ambiguous", f"Anchor must occur exactly once; found {len(matches)}."
        )
    start = matches[0]
    end = start + len(anchor)
    if slot.operation == "replace":
        if slot.extent.end_byte - slot.extent.start_byte != len(anchor):
            raise SlotEditError(
                "anchor_extent_mismatch",
                "Anchor replacement extent has the wrong length.",
            )
        return source[:start] + content.encode("utf-8") + source[end:]
    if slot.operation == "insert_before":
        if slot.extent.start_byte != slot.extent.end_byte:
            raise SlotEditError(
                "anchor_extent_mismatch", "Before-anchor extent must be zero-width."
            )
        return source[:start] + content.encode("utf-8") + source[start:]
    if slot.operation == "insert_after":
        if slot.extent.start_byte != slot.extent.end_byte:
            raise SlotEditError(
                "anchor_extent_mismatch", "After-anchor extent must be zero-width."
            )
        return source[:end] + content.encode("utf-8") + source[end:]
    raise SlotEditError(
        "slot_operation", f"Unsupported text-anchor operation: {slot.operation}"
    )
