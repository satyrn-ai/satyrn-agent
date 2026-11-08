import hashlib
import json
from pathlib import Path

from typed_packets.contract import (
    Diagnostic,
    DiagnosticOutcome,
    Packet,
    PacketDecodeError,
    ValidationReport,
    ValidationStatus,
    decode_packet,
    encode_packet,
)
from typed_packets.index import (
    ModuleRecord,
    SymbolIndex,
    ValidationContext,
    build_index,
)
from typed_packets.paths import validate_file_access
from typed_packets.resolve import (
    Resolution,
    resolve_import_reference,
    resolve_planned,
    resolve_symbol,
)


def _pointer(parent: str, component: str | int) -> str:
    escaped = str(component).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _diagnostic(
    code: str,
    outcome: DiagnosticOutcome,
    field: str,
    message: str,
    *,
    path: str | None = None,
    symbol: str | None = None,
    line: int | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        outcome=outcome,
        field=field,
        message=message,
        path=path,
        symbol=symbol,
        line=line,
    )


def _index_context_diagnostics(index: SymbolIndex) -> tuple[Diagnostic, ...]:
    return tuple(
        _diagnostic(
            issue.code,
            "invalid",
            "",
            f"Invalid source-root context: {issue.message}",
            path=issue.path,
            symbol=issue.root_id,
        )
        for issue in index.issues
        if issue.outcome == "invalid"
    )


def _report_status(diagnostics: tuple[Diagnostic, ...]) -> ValidationStatus:
    if any(item.outcome == "invalid" for item in diagnostics):
        return "invalid"
    if any(item.outcome == "inconclusive" for item in diagnostics):
        return "inconclusive"
    return "valid"


def _ordered_diagnostics(
    diagnostics: list[Diagnostic] | tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    return tuple(
        sorted(
            set(diagnostics),
            key=lambda item: (
                item.field,
                item.code,
                item.path or "",
                item.symbol or "",
                item.line or 0,
            ),
        )
    )


def _unverified_requirements(packet: Packet) -> tuple[str, ...]:
    requirements: list[str] = []
    for field, values in (
        ("known_facts", packet.known_facts),
        ("acceptance_criteria", packet.acceptance_criteria),
        ("preserved_behavior", packet.preserved_behavior),
    ):
        requirements.extend(
            f"{_pointer(f'/{field}', index)} (unverified): {value}"
            for index, value in enumerate(values)
        )
    return tuple(requirements)


def _input_fingerprint(document: str, index: SymbolIndex) -> str:
    payload = {
        "document": document,
        "context_fingerprint": index.context_fingerprint,
        "index_fingerprint": index.fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _report(
    diagnostics: list[Diagnostic],
    unverified: tuple[str, ...],
    fingerprint: str,
) -> ValidationReport:
    ordered = _ordered_diagnostics(diagnostics)
    return ValidationReport(
        status=_report_status(ordered),
        diagnostics=ordered,
        unverified_requirements=unverified,
        input_fingerprint=fingerprint,
    )


def _resolution_diagnostic(field: str, resolution: Resolution) -> Diagnostic:
    if resolution.outcome == "valid":
        raise ValueError("A valid resolution cannot produce a diagnostic.")
    return _diagnostic(
        resolution.code,
        resolution.outcome,
        field,
        resolution.message,
        path=resolution.path,
        symbol=resolution.symbol,
        line=resolution.definition.line if resolution.definition is not None else None,
    )


def _consume_field(index: int, resolution: Resolution) -> str:
    base = _pointer("/consumes", index)
    if resolution.code.startswith("resolve.signature"):
        return _pointer(base, "expected_signature")
    if resolution.code in {"resolve.unknown_root", "resolve.invalid_context"}:
        return _pointer(_pointer(base, "source"), "root_id")
    if resolution.code == "resolve.source_unavailable":
        return _pointer(_pointer(base, "source"), "path")
    return _pointer(base, "qualified_name")


def _import_field(index: int, resolution: Resolution, name: str | None) -> str:
    base = _pointer("/imports", index)
    if resolution.code in {
        "resolve.module_unavailable",
        "resolve.ambiguous_module",
        "resolve.planned_module_mapping",
        "resolve.planned_module_ambiguous",
    }:
        return _pointer(base, "module")
    return _pointer(base, "name") if name is not None else _pointer(base, "module")


def _root_path(index: SymbolIndex, root_id: str) -> Path | None:
    roots = [root for root in index.roots if root.root_id == root_id]
    return roots[0].path if len(roots) == 1 else None


def _module_for_produce(
    index: SymbolIndex,
    root_id: str,
    path: str,
) -> tuple[ModuleRecord | None, str | None]:
    roots = [root for root in index.roots if root.root_id == root_id]
    if len(roots) != 1:
        return None, "Produced source root is not configured."
    try:
        workspace_root = _root_path(index, "workspace")
        if workspace_root is None:
            return None, "Workspace source root is not configured."
        target = workspace_root.joinpath(*path.split("/"))
        relative_path = target.relative_to(roots[0].path).as_posix()
    except ValueError:
        return None, "Produced path is outside its project source root."
    matches = [
        module
        for module in index.modules
        if module.root_id == root_id and module.path == relative_path
    ]
    if len(matches) != 1:
        return None, "Current produced source is unavailable or ambiguous."
    return matches[0], None


def _produce_diagnostics(
    packet: Packet,
    context: ValidationContext,
    index: SymbolIndex,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    file_operations = {item.path: item.operation for item in packet.file_changes}
    for position, produce in enumerate(packet.produces):
        field = _pointer(_pointer("/produces", position), "path")
        planned = resolve_planned(index, packet, produce.path, produce.qualified_name)
        if planned.outcome != "valid":
            if planned.code == "resolve.planned_declaration_invalid":
                field = _pointer(_pointer("/produces", position), "declaration")
            elif planned.code == "resolve.planned_declaration":
                field = _pointer(_pointer("/produces", position), "qualified_name")
            diagnostics.append(_resolution_diagnostic(field, planned))
            continue

        if file_operations.get(produce.path) == "create":
            continue
        module, unavailable_message = _module_for_produce(
            index,
            planned.root_id or "",
            produce.path,
        )
        if module is None:
            diagnostics.append(
                _diagnostic(
                    "produce.source_unavailable",
                    "inconclusive",
                    field,
                    unavailable_message or "Current source is unavailable.",
                    path=produce.path,
                    symbol=produce.qualified_name,
                )
            )
            continue
        if module.parse_error is not None:
            diagnostics.append(
                _diagnostic(
                    "produce.source_unparseable",
                    "inconclusive",
                    field,
                    "Current source cannot be inspected to check the produced binding.",
                    path=produce.path,
                    symbol=produce.qualified_name,
                )
            )
            continue
        current = [
            definition
            for definition in module.definitions
            if definition.qualified_name == produce.qualified_name
        ]
        symbol_field = _pointer(_pointer("/produces", position), "qualified_name")
        if len(current) > 1 or any(item.conditional for item in current):
            diagnostics.append(
                _diagnostic(
                    "produce.current_ambiguous",
                    "inconclusive",
                    symbol_field,
                    "Current declarations do not establish one unconditional binding.",
                    path=module.path,
                    symbol=produce.qualified_name,
                    line=current[0].line if current else None,
                )
            )
            continue
        if produce.operation == "create":
            if current:
                diagnostics.append(
                    _diagnostic(
                        "produce.already_exists",
                        "invalid",
                        symbol_field,
                        "A produced create definition already has a current binding.",
                        path=module.path,
                        symbol=produce.qualified_name,
                        line=current[0].line,
                    )
                )
            elif (
                module.has_dynamic_getattr
                or module.has_dynamic_exports
                or module.has_wildcard_import
            ):
                diagnostics.append(
                    _diagnostic(
                        "produce.current_dynamic",
                        "inconclusive",
                        symbol_field,
                        "Dynamic or wildcard bindings prevent proving the name "
                        "is absent.",
                        path=module.path,
                        symbol=produce.qualified_name,
                    )
                )
        elif not current:
            diagnostics.append(
                _diagnostic(
                    "produce.missing",
                    "invalid",
                    symbol_field,
                    "A produced modify definition must exist in the current file.",
                    path=module.path,
                    symbol=produce.qualified_name,
                )
            )
        elif current[0].kind == "import":
            diagnostics.append(
                _diagnostic(
                    "produce.not_definition",
                    "invalid",
                    symbol_field,
                    "A produced modify target must be defined in the current file.",
                    path=module.path,
                    symbol=produce.qualified_name,
                    line=current[0].line,
                )
            )
    return diagnostics


def _validate_packet(
    packet: Packet,
    document: str,
    context: ValidationContext,
    index: SymbolIndex,
    *,
    verify_freshness: bool,
) -> ValidationReport:
    diagnostics: list[Diagnostic] = list(_index_context_diagnostics(index))
    if verify_freshness:
        fresh_index = build_index(context)
        diagnostics.extend(_index_context_diagnostics(fresh_index))
        if index.context_fingerprint != fresh_index.context_fingerprint:
            diagnostics.append(
                _diagnostic(
                    "index.context_mismatch",
                    "invalid",
                    "",
                    "Symbol index was built for a different source-root context.",
                )
            )
        elif index.fingerprint != fresh_index.fingerprint:
            diagnostics.append(
                _diagnostic(
                    "index.stale",
                    "inconclusive",
                    "",
                    "Source bytes changed after the symbol index was built.",
                )
            )

    diagnostics.extend(validate_file_access(packet, context.workspace, context))
    for position, consume in enumerate(packet.consumes):
        resolution = resolve_symbol(
            index,
            consume.source.root_id,
            consume.source.path,
            consume.qualified_name,
            consume.expected_signature,
        )
        if resolution.outcome != "valid":
            diagnostics.append(
                _resolution_diagnostic(_consume_field(position, resolution), resolution)
            )
    for position, imported in enumerate(packet.imports):
        resolution = resolve_import_reference(index, packet, imported)
        if resolution.outcome != "valid":
            diagnostics.append(
                _resolution_diagnostic(
                    _import_field(position, resolution, imported.name), resolution
                )
            )
    diagnostics.extend(_produce_diagnostics(packet, context, index))
    return _report(
        diagnostics,
        _unverified_requirements(packet),
        _input_fingerprint(document, index),
    )


def validate_packet(
    packet: Packet,
    context: ValidationContext,
    index: SymbolIndex,
) -> ValidationReport:
    try:
        document = encode_packet(packet)
        checked_packet = decode_packet(document)
    except PacketDecodeError as error:
        fresh_index = build_index(context)
        diagnostics = list(_index_context_diagnostics(fresh_index))
        diagnostics.append(
            _diagnostic(error.code, "invalid", error.field, error.message)
        )
        return _report(
            diagnostics,
            (),
            _input_fingerprint(repr(packet), fresh_index),
        )
    except (AttributeError, TypeError, ValueError) as error:
        fresh_index = build_index(context)
        diagnostics = list(_index_context_diagnostics(fresh_index))
        diagnostics.append(
            _diagnostic(
                "contract.packet_object",
                "invalid",
                "",
                f"Packet object cannot be encoded: {error}.",
            )
        )
        return _report(
            diagnostics,
            (),
            _input_fingerprint(repr(packet), fresh_index),
        )
    return _validate_packet(
        checked_packet,
        document,
        context,
        index,
        verify_freshness=True,
    )


def validate_document(
    document: str,
    context: ValidationContext,
) -> ValidationReport:
    index = build_index(context)
    try:
        packet = decode_packet(document)
    except PacketDecodeError as error:
        diagnostics = list(_index_context_diagnostics(index))
        diagnostics.append(
            _diagnostic(error.code, "invalid", error.field, error.message)
        )
        return _report(diagnostics, (), _input_fingerprint(document, index))
    canonical_document = encode_packet(packet)
    return _validate_packet(
        packet,
        canonical_document,
        context,
        index,
        verify_freshness=False,
    )
