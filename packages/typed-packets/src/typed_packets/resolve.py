import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from typed_packets.contract import ImportReference, Packet, Produce
from typed_packets.index import (
    CallableSignature,
    DefinitionRecord,
    ImportBinding,
    IndexedRoot,
    ModuleRecord,
    SymbolIndex,
    _module_name,
    parse_signature_header,
)

type ResolutionOutcome = Literal["valid", "invalid", "inconclusive"]


@dataclass(frozen=True, slots=True)
class Resolution:
    outcome: ResolutionOutcome
    code: str
    message: str
    root_id: str | None = None
    path: str | None = None
    symbol: str | None = None
    definition: DefinitionRecord | None = None
    module_name: str | None = None


def _result(
    outcome: ResolutionOutcome,
    code: str,
    message: str,
    *,
    root_id: str | None = None,
    path: str | None = None,
    symbol: str | None = None,
    definition: DefinitionRecord | None = None,
    module_name: str | None = None,
) -> Resolution:
    return Resolution(
        outcome=outcome,
        code=code,
        message=message,
        root_id=root_id,
        path=path,
        symbol=symbol,
        definition=definition,
        module_name=module_name,
    )


def _context_is_invalid(index: SymbolIndex) -> bool:
    return any(issue.outcome == "invalid" for issue in index.issues)


def _expected_signature(
    expected: str | None, qualified_name: str
) -> tuple[CallableSignature | None, Resolution | None]:
    if expected is None:
        return None, None
    parsed = parse_signature_header(expected)
    if parsed is None:
        return None, _result(
            "invalid",
            "resolve.signature_syntax",
            "Expected signature must be a Python function header.",
            symbol=qualified_name,
        )
    name, signature = parsed
    expected_name = qualified_name.rsplit(".", maxsplit=1)[-1]
    if name != expected_name:
        return None, _result(
            "invalid",
            "resolve.signature_name",
            "Expected signature function name must match the referenced symbol.",
            symbol=qualified_name,
        )
    return signature, None


def _root(index: SymbolIndex, root_id: str) -> IndexedRoot | None:
    roots = [root for root in index.roots if root.root_id == root_id]
    return roots[0] if len(roots) == 1 else None


def _source_module(
    index: SymbolIndex, root_id: str, path: str
) -> tuple[ModuleRecord | None, Resolution | None]:
    if _context_is_invalid(index):
        return None, _result(
            "invalid",
            "resolve.invalid_context",
            "Source root configuration is invalid.",
            root_id=root_id,
            path=path,
        )
    if _root(index, root_id) is None:
        return None, _result(
            "invalid",
            "resolve.unknown_root",
            "Source root is not configured.",
            root_id=root_id,
            path=path,
        )
    candidates = [
        module
        for module in index.modules
        if module.root_id == root_id and module.path == path
    ]
    if not candidates:
        return None, _result(
            "inconclusive",
            "resolve.source_unavailable",
            "Source file is not available in the static index.",
            root_id=root_id,
            path=path,
        )
    if len(candidates) != 1:
        return None, _result(
            "inconclusive",
            "resolve.ambiguous_source",
            "Source path has multiple indexed providers.",
            root_id=root_id,
            path=path,
        )
    return candidates[0], None


def resolve_symbol(
    index: SymbolIndex,
    root_id: str,
    path: str,
    qualified_name: str,
    expected_signature: str | None = None,
) -> Resolution:
    expected, error = _expected_signature(expected_signature, qualified_name)
    if error is not None:
        return error
    module, error = _source_module(index, root_id, path)
    if error is not None:
        return error
    assert module is not None
    return _resolve_in_module(
        index,
        module,
        qualified_name,
        expected,
        frozenset(),
    )


def resolve_module_symbol(
    index: SymbolIndex,
    module_name: str,
    qualified_name: str,
    expected_signature: str | None = None,
) -> Resolution:
    expected, error = _expected_signature(expected_signature, qualified_name)
    if error is not None:
        return error
    if _context_is_invalid(index):
        return _result(
            "invalid",
            "resolve.invalid_context",
            "Source root configuration is invalid.",
            symbol=qualified_name,
            module_name=module_name,
        )
    return _resolve_by_module_name(
        index,
        module_name,
        qualified_name,
        expected,
        frozenset(),
    )


def resolve_import_reference(
    index: SymbolIndex,
    packet: Packet,
    reference: ImportReference,
) -> Resolution:
    if reference.target == "existing":
        return resolve_module_symbol(
            index,
            reference.module,
            reference.name or "",
        )
    if reference.target != "planned":
        return _result(
            "invalid",
            "resolve.import_target",
            "Import target must be existing or planned.",
            path=reference.path,
            symbol=reference.name,
            module_name=reference.module,
        )

    matching: list[tuple[Produce, IndexedRoot, str]] = []
    unresolved: list[Produce] = []
    for produce in packet.produces:
        if reference.name is not None and produce.qualified_name != reference.name:
            continue
        root, module_name, error = _planned_module_name(index, produce.path)
        if error is not None:
            unresolved.append(produce)
        elif root is not None and module_name == reference.module:
            matching.append((produce, root, module_name))
    if reference.name is not None and unresolved:
        return _result(
            "inconclusive",
            "resolve.planned_module_mapping",
            "A matching planned symbol has an unresolved project module mapping.",
            path=reference.path,
            symbol=reference.name,
            module_name=reference.module,
        )
    if not matching:
        if unresolved:
            return _result(
                "inconclusive",
                "resolve.planned_module_mapping",
                "Planned import could not be mapped to a project module.",
                path=reference.path,
                symbol=reference.name,
                module_name=reference.module,
            )
        return _result(
            "invalid",
            "resolve.planned_import_missing",
            "Planned imports must match an explicit produced declaration.",
            path=reference.path,
            symbol=reference.name,
            module_name=reference.module,
        )

    planned_modules = {
        (root.root_id, produce.path, module_name)
        for produce, root, module_name in matching
    }
    if len(planned_modules) != 1:
        return _result(
            "inconclusive",
            "resolve.planned_module_ambiguous",
            "Planned import has multiple produced module mappings.",
            path=reference.path,
            symbol=reference.name,
            module_name=reference.module,
        )
    produce, root, _ = matching[0]
    resolution = resolve_planned(
        index,
        packet,
        produce.path,
        produce.qualified_name,
    )
    if resolution.outcome != "valid" or reference.name is not None:
        return resolution
    return _result(
        "valid",
        "resolve.planned_module_proven",
        "Module is explicitly declared by a planned produced binding.",
        root_id=resolution.root_id,
        path=produce.path,
        module_name=reference.module,
    )


def _resolve_by_module_name(
    index: SymbolIndex,
    module_name: str,
    qualified_name: str,
    expected: CallableSignature | None,
    visited: frozenset[tuple[str, str, str]],
) -> Resolution:
    providers = [
        module for module in index.modules if module.module_name == module_name
    ]
    if not providers:
        return _result(
            "inconclusive",
            "resolve.module_unavailable",
            "Module has no provider in the configured source roots.",
            symbol=qualified_name,
            module_name=module_name,
        )
    if len(providers) != 1:
        return _result(
            "inconclusive",
            "resolve.ambiguous_module",
            "Multiple configured roots provide this module.",
            symbol=qualified_name,
            module_name=module_name,
        )
    return _resolve_in_module(
        index,
        providers[0],
        qualified_name,
        expected,
        visited,
    )


def _resolve_in_module(
    index: SymbolIndex,
    module: ModuleRecord,
    qualified_name: str,
    expected: CallableSignature | None,
    visited: frozenset[tuple[str, str, str]],
) -> Resolution:
    if module.parse_error is not None:
        return _result(
            "inconclusive",
            "resolve.parse_error",
            "Module source could not be parsed.",
            root_id=module.root_id,
            path=module.path,
            symbol=qualified_name,
            module_name=module.module_name,
        )
    if not qualified_name:
        if module.module_name is None:
            return _result(
                "inconclusive",
                "resolve.unmapped_module",
                "Module has no unambiguous import name.",
                root_id=module.root_id,
                path=module.path,
            )
        return _result(
            "valid",
            "resolve.module_proven",
            "Module is explicitly mapped by a configured source root.",
            root_id=module.root_id,
            path=module.path,
            module_name=module.module_name,
        )
    key = module.root_id, module.module_name or f"@{module.path}", qualified_name
    if key in visited:
        return _result(
            "inconclusive",
            "resolve.import_cycle",
            "Reference resolution encountered an import cycle.",
            root_id=module.root_id,
            path=module.path,
            symbol=qualified_name,
            module_name=module.module_name,
        )
    visited = visited | {key}

    components = qualified_name.split(".")
    for count in range(len(components), 0, -1):
        candidate_name = ".".join(components[:count])
        candidates = [
            definition
            for definition in module.definitions
            if definition.qualified_name == candidate_name
        ]
        if not candidates:
            continue
        if len(candidates) != 1:
            return _result(
                "inconclusive",
                "resolve.competing_definitions",
                "Multiple declarations compete for this binding.",
                root_id=module.root_id,
                path=module.path,
                symbol=qualified_name,
                module_name=module.module_name,
            )
        definition = candidates[0]
        if definition.conditional:
            return _result(
                "inconclusive",
                "resolve.conditional_definition",
                "Binding is declared only under a conditional branch.",
                root_id=module.root_id,
                path=module.path,
                symbol=qualified_name,
                definition=definition,
                module_name=module.module_name,
            )
        remainder = ".".join(components[count:])
        if definition.kind == "import":
            binding = definition.import_binding
            assert binding is not None
            if binding.conditional:
                return _result(
                    "inconclusive",
                    "resolve.conditional_import",
                    "Import binding is declared only under a conditional branch.",
                    root_id=module.root_id,
                    path=module.path,
                    symbol=qualified_name,
                    definition=definition,
                    module_name=module.module_name,
                )
            return _resolve_import_binding(
                index,
                module,
                binding,
                remainder,
                expected,
                visited,
            )
        if remainder:
            if definition.kind == "class":
                if definition.decorated or _class_has_dynamic_getattr(
                    module, definition.qualified_name
                ):
                    return _result(
                        "inconclusive",
                        "resolve.dynamic_class",
                        "Class attributes may be generated or changed dynamically.",
                        root_id=module.root_id,
                        path=module.path,
                        symbol=qualified_name,
                        definition=definition,
                        module_name=module.module_name,
                    )
                if definition.bases:
                    return _result(
                        "inconclusive",
                        "resolve.inherited_attribute",
                        "Inherited attributes are not inferred.",
                        root_id=module.root_id,
                        path=module.path,
                        symbol=qualified_name,
                        definition=definition,
                        module_name=module.module_name,
                    )
                return _result(
                    "invalid",
                    "resolve.binding_absent",
                    "Class has no direct declaration for this attribute.",
                    root_id=module.root_id,
                    path=module.path,
                    symbol=qualified_name,
                    module_name=module.module_name,
                )
            return _result(
                "inconclusive",
                "resolve.attribute_unproven",
                "Attributes of non-class bindings are not inferred.",
                root_id=module.root_id,
                path=module.path,
                symbol=qualified_name,
                definition=definition,
                module_name=module.module_name,
            )
        if definition.decorated or _has_decorated_enclosing_class(
            module, definition.qualified_name
        ):
            return _result(
                "inconclusive",
                "resolve.decorated_definition",
                "Decorators may change the declared interface.",
                root_id=module.root_id,
                path=module.path,
                symbol=qualified_name,
                definition=definition,
                module_name=module.module_name,
            )
        if expected is not None and definition.signature != expected:
            return _result(
                "invalid",
                "resolve.signature_mismatch",
                "Existing callable signature does not match the expected signature.",
                root_id=module.root_id,
                path=module.path,
                symbol=qualified_name,
                definition=definition,
                module_name=module.module_name,
            )
        return _result(
            "valid",
            "resolve.proven",
            "Binding is statically declared.",
            root_id=module.root_id,
            path=module.path,
            symbol=qualified_name,
            definition=definition,
            module_name=module.module_name,
        )

    if module.module_name is not None:
        for count in range(len(components), 0, -1):
            child_module_name = f"{module.module_name}.{'.'.join(components[:count])}"
            providers = [
                child
                for child in index.modules
                if child.module_name == child_module_name
            ]
            if not providers:
                continue
            if count == len(components):
                return _resolve_by_module_name(
                    index,
                    child_module_name,
                    "",
                    expected,
                    visited,
                )
            return _resolve_by_module_name(
                index,
                child_module_name,
                ".".join(components[count:]),
                expected,
                visited,
            )

    if (
        module.has_dynamic_getattr
        or module.has_dynamic_exports
        or module.has_wildcard_import
    ):
        return _result(
            "inconclusive",
            "resolve.dynamic_exports",
            "Dynamic or wildcard exports may provide this binding.",
            root_id=module.root_id,
            path=module.path,
            symbol=qualified_name,
            module_name=module.module_name,
        )
    return _result(
        "invalid",
        "resolve.binding_absent",
        "A fully inspected module has no declaration for this binding.",
        root_id=module.root_id,
        path=module.path,
        symbol=qualified_name,
        module_name=module.module_name,
    )


def _class_has_dynamic_getattr(module: ModuleRecord, qualified_name: str) -> bool:
    return any(
        definition.qualified_name == f"{qualified_name}.__getattr__"
        for definition in module.definitions
    )


def _has_decorated_enclosing_class(module: ModuleRecord, qualified_name: str) -> bool:
    components = qualified_name.split(".")
    for count in range(len(components) - 1, 0, -1):
        prefix = ".".join(components[:count])
        if any(
            definition.qualified_name == prefix
            and definition.kind == "class"
            and definition.decorated
            for definition in module.definitions
        ):
            return True
    return False


def _relative_module_name(
    module: ModuleRecord, binding: ImportBinding
) -> tuple[str | None, Resolution | None]:
    if binding.level == 0:
        return binding.module_name or "", None
    if module.module_name is None:
        return None, _result(
            "inconclusive",
            "resolve.relative_import_unmapped",
            "Relative import source has no mapped module name.",
            root_id=module.root_id,
            path=module.path,
            module_name=module.module_name,
        )
    package_name = (
        module.module_name
        if module.is_package
        else module.module_name.rpartition(".")[0]
    )
    package_parts = tuple(part for part in package_name.split(".") if part)
    levels_up = binding.level - 1
    if levels_up >= len(package_parts):
        return None, _result(
            "invalid",
            "resolve.relative_import_root",
            "Relative import climbs beyond the mapped package root.",
            root_id=module.root_id,
            path=module.path,
            module_name=module.module_name,
        )
    parent = package_parts[: len(package_parts) - levels_up]
    module_parts = tuple(binding.module_name.split(".")) if binding.module_name else ()
    return ".".join((*parent, *module_parts)), None


def _resolve_import_binding(
    index: SymbolIndex,
    source: ModuleRecord,
    binding: ImportBinding,
    remainder: str,
    expected: CallableSignature | None,
    visited: frozenset[tuple[str, str, str]],
) -> Resolution:
    target_module, error = _relative_module_name(source, binding)
    if error is not None:
        return error
    assert target_module is not None
    if binding.imported_name is None:
        target_name = remainder
    else:
        target_name = binding.imported_name
        if remainder:
            target_name = f"{target_name}.{remainder}"
    if target_name:
        result = _resolve_by_module_name(
            index,
            target_module,
            target_name,
            expected,
            visited,
        )
        if result.outcome != "invalid" or binding.imported_name is None:
            return result
        child_module = f"{target_module}.{target_name}"
        if any(module.module_name == child_module for module in index.modules):
            return _resolve_by_module_name(
                index,
                child_module,
                "",
                expected,
                visited,
            )
        return result
    return _resolve_by_module_name(
        index,
        target_module,
        "",
        expected,
        visited,
    )


def _planned_module_name(
    index: SymbolIndex, path: str
) -> tuple[IndexedRoot | None, str | None, str | None]:
    workspace_root = _root(index, "workspace")
    if workspace_root is None:
        return None, None, "Workspace source root is not configured."
    pure_path = PurePosixPath(path)
    if (
        pure_path.is_absolute()
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        return None, None, "Planned path is not a canonical relative path."
    target = workspace_root.path.joinpath(*pure_path.parts)
    mappings: list[tuple[IndexedRoot, str]] = []
    for root in index.roots:
        if root.kind != "project":
            continue
        try:
            relative = target.relative_to(root.path)
        except ValueError:
            continue
        base_parts = (
            () if root.import_base == "." else tuple(root.import_base.split("/"))
        )
        relative_parts = relative.parts
        if relative_parts[: len(base_parts)] != base_parts:
            continue
        source_parts = relative_parts[len(base_parts) :]
        if not source_parts:
            continue
        source_path = PurePosixPath(*source_parts)
        if source_path.suffix not in root.suffixes:
            continue
        module_name, _ = _module_name(source_path, root.module_prefix)
        if module_name is not None:
            mappings.append((root, module_name))
    if not mappings:
        return None, None, "Planned path is outside configured project import roots."
    if len(mappings) != 1:
        return None, None, "Planned path has ambiguous project module mappings."
    return mappings[0][0], mappings[0][1], None


def _planned_definition(produce: Produce) -> DefinitionRecord | None:
    if produce.kind in {"function", "async_function"}:
        parsed = parse_signature_header(produce.declaration)
        if parsed is None:
            return None
        name, signature = parsed
        return (
            DefinitionRecord(
                qualified_name=produce.qualified_name,
                kind=produce.kind,
                line=1,
                signature=signature,
            )
            if name == produce.qualified_name.rsplit(".", maxsplit=1)[-1]
            else None
        )
    source = produce.declaration
    if produce.kind == "class":
        source = f"{source}\n    pass\n"
    try:
        module = ast.parse(source, type_comments=True)
    except (SyntaxError, ValueError):
        return None
    if len(module.body) != 1:
        return None
    node = module.body[0]
    if produce.kind == "class" and isinstance(node, ast.ClassDef):
        return DefinitionRecord(
            qualified_name=produce.qualified_name,
            kind="class",
            line=1,
            bases=tuple(
                ast.dump(base, include_attributes=False) for base in node.bases
            ),
        )
    if produce.kind == "type_alias" and isinstance(node, ast.TypeAlias):
        if not isinstance(node.name, ast.Name):
            return None
        return DefinitionRecord(
            qualified_name=produce.qualified_name,
            kind="type_alias",
            line=1,
            alias_expression=ast.dump(node.value, include_attributes=False),
        )
    return None


def resolve_planned(
    index: SymbolIndex,
    packet: Packet,
    path: str,
    qualified_name: str,
) -> Resolution:
    if _context_is_invalid(index):
        return _result(
            "invalid",
            "resolve.invalid_context",
            "Source root configuration is invalid.",
            path=path,
            symbol=qualified_name,
        )
    matches = [
        produce
        for produce in packet.produces
        if produce.path == path and produce.qualified_name == qualified_name
    ]
    if len(matches) != 1:
        outcome: ResolutionOutcome = "invalid" if not matches else "inconclusive"
        return _result(
            outcome,
            "resolve.planned_declaration",
            "Planned symbol must have exactly one produced declaration.",
            path=path,
            symbol=qualified_name,
        )
    produce = matches[0]
    root, module_name, error = _planned_module_name(index, path)
    if error is not None:
        return _result(
            "inconclusive",
            "resolve.planned_module_mapping",
            error,
            path=path,
            symbol=qualified_name,
        )
    assert root is not None and module_name is not None
    workspace_root = _root(index, "workspace")
    assert workspace_root is not None
    target_path = workspace_root.path.joinpath(*PurePosixPath(path).parts)
    try:
        relative_path = target_path.relative_to(root.path).as_posix()
    except ValueError:
        return _result(
            "inconclusive",
            "resolve.planned_module_mapping",
            "Planned path is outside its selected project root.",
            path=path,
            symbol=qualified_name,
        )
    competing = [
        module
        for module in index.modules
        if module.module_name == module_name
        and not (
            module.root_id == root.root_id
            and (
                module.path == relative_path
                or (
                    module.implicit_namespace
                    and module.path == str(PurePosixPath(relative_path).parent)
                )
            )
        )
    ]
    if competing:
        return _result(
            "inconclusive",
            "resolve.planned_module_ambiguous",
            "Planned module has competing configured providers.",
            root_id=root.root_id,
            path=path,
            symbol=qualified_name,
            module_name=module_name,
        )
    definition = _planned_definition(produce)
    if definition is None:
        return _result(
            "invalid",
            "resolve.planned_declaration_invalid",
            "Produced declaration could not be parsed as its declared kind.",
            root_id=root.root_id,
            path=path,
            symbol=qualified_name,
            module_name=module_name,
        )
    return _result(
        "valid",
        "resolve.planned_proven",
        "Binding is explicitly declared as planned by this packet.",
        root_id=root.root_id,
        path=path,
        symbol=qualified_name,
        definition=definition,
        module_name=module_name,
    )
