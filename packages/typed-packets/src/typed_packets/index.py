import ast
import hashlib
import io
import json
import keyword
import os
import re
import stat
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

type RootKind = Literal["project", "dependency", "stub"]
type IssueOutcome = Literal["invalid", "inconclusive"]
type DefinitionKind = Literal[
    "function", "async_function", "class", "type_alias", "assignment", "import"
]
type ParameterKind = Literal[
    "positional_only",
    "positional_or_keyword",
    "var_positional",
    "keyword_only",
    "var_keyword",
]


@dataclass(frozen=True, slots=True)
class SourceRoot:
    root_id: str
    path: Path
    kind: RootKind
    import_base: str = "."
    module_prefix: str | None = None
    suffixes: tuple[str, ...] = (".py",)


@dataclass(frozen=True, slots=True)
class ValidationContext:
    workspace: Path
    roots: tuple[SourceRoot, ...]


@dataclass(frozen=True, slots=True)
class IndexIssue:
    code: str
    outcome: IssueOutcome
    message: str
    root_id: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: ParameterKind
    annotation: str | None
    default: str | None


@dataclass(frozen=True, slots=True)
class CallableSignature:
    is_async: bool
    parameters: tuple[Parameter, ...]
    returns: str | None
    type_parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportBinding:
    local_name: str | None
    module_name: str | None
    imported_name: str | None
    level: int
    wildcard: bool
    line: int
    conditional: bool


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    qualified_name: str
    kind: DefinitionKind
    line: int
    signature: CallableSignature | None = None
    conditional: bool = False
    decorated: bool = False
    bases: tuple[str, ...] = ()
    alias_expression: str | None = None
    import_binding: ImportBinding | None = None


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    module_name: str | None
    root_id: str
    path: str
    sha256: str | None
    definitions: tuple[DefinitionRecord, ...]
    imports: tuple[ImportBinding, ...]
    is_package: bool
    implicit_namespace: bool = False
    parse_error: str | None = None
    has_dynamic_getattr: bool = False
    has_dynamic_exports: bool = False
    has_wildcard_import: bool = False
    explicit_exports: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class IndexedRoot:
    root_id: str
    path: Path
    kind: RootKind
    import_base: str
    module_prefix: str | None
    suffixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceHash:
    root_id: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SymbolIndex:
    roots: tuple[IndexedRoot, ...]
    modules: tuple[ModuleRecord, ...]
    source_hashes: tuple[SourceHash, ...]
    issues: tuple[IndexIssue, ...]
    parser_version: tuple[int, int]
    context_fingerprint: str
    fingerprint: str


_CLASS_INTERFACE_PRESERVING = frozenset(("dataclasses.dataclass",))
_FUNCTION_INTERFACE_PRESERVING = frozenset(("django.db.transaction.atomic",))


def _import_targets(module: ast.Module) -> dict[str, str]:
    """Map names bound by unconditional top-level imports to their dotted targets."""
    targets: dict[str, str] = {}
    for statement in module.body:
        match statement:
            case ast.ImportFrom(module=str(source), level=0, names=names):
                for alias in names:
                    targets[alias.asname or alias.name] = f"{source}.{alias.name}"
            case ast.Import(names=names):
                for alias in names:
                    if alias.asname or "." not in alias.name:
                        targets[alias.asname or alias.name] = alias.name
    for statement in module.body:
        match statement:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                targets.pop(name, None)
            case ast.Assign(targets=assigned):
                for target in assigned:
                    if isinstance(target, ast.Name):
                        targets.pop(target.id, None)
    return targets


class _ModuleCollector:
    def __init__(self) -> None:
        self.import_targets: dict[str, str] = {}
        self.definitions: list[DefinitionRecord] = []
        self.imports: list[ImportBinding] = []
        self.has_dynamic_getattr = False
        self.has_dynamic_exports = False
        self.has_wildcard_import = False
        self.explicit_exports: tuple[str, ...] | None = None

    def collect(self, module: ast.Module) -> None:
        self.import_targets = _import_targets(module)
        self._collect_statements(module.body, "", False, module_scope=True)

    def _is_decorated(
        self, decorators: list[ast.expr], preserving: frozenset[str]
    ) -> bool:
        """Report decorators that are not proven to preserve the declared interface."""
        return not all(self._decorator_target(d) in preserving for d in decorators)

    def _decorator_target(self, decorator: ast.expr) -> str | None:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        match target:
            case ast.Name(id=name):
                return self.import_targets.get(name)
            case ast.Attribute(value=ast.Name(id=name), attr=attribute):
                bound = self.import_targets.get(name)
                return f"{bound}.{attribute}" if bound else None
        return None

    def _record(
        self,
        qualified_name: str,
        kind: DefinitionKind,
        node: ast.AST,
        conditional: bool,
        *,
        signature: CallableSignature | None = None,
        decorated: bool = False,
        bases: tuple[str, ...] = (),
        alias_expression: str | None = None,
        import_binding: ImportBinding | None = None,
    ) -> None:
        self.definitions.append(
            DefinitionRecord(
                qualified_name=qualified_name,
                kind=kind,
                line=getattr(node, "lineno", 1),
                signature=signature,
                conditional=conditional,
                decorated=decorated,
                bases=bases,
                alias_expression=alias_expression,
                import_binding=import_binding,
            )
        )

    def _collect_statements(
        self,
        statements: list[ast.stmt],
        prefix: str,
        conditional: bool,
        *,
        module_scope: bool,
    ) -> None:
        for statement in statements:
            match statement:
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    qualified_name = _qualified(prefix, statement.name)
                    kind: DefinitionKind = (
                        "async_function"
                        if isinstance(statement, ast.AsyncFunctionDef)
                        else "function"
                    )
                    self._record(
                        qualified_name,
                        kind,
                        statement,
                        conditional,
                        signature=_callable_signature(statement),
                        decorated=self._is_decorated(
                            statement.decorator_list, _FUNCTION_INTERFACE_PRESERVING
                        ),
                    )
                    if module_scope and statement.name == "__getattr__":
                        self.has_dynamic_getattr = True
                case ast.ClassDef():
                    class_name = _qualified(prefix, statement.name)
                    bases = tuple(_ast_value(base) for base in statement.bases)
                    self._record(
                        class_name,
                        "class",
                        statement,
                        conditional,
                        decorated=self._is_decorated(
                            statement.decorator_list, _CLASS_INTERFACE_PRESERVING
                        ),
                        bases=bases,
                    )
                    self._collect_statements(
                        statement.body,
                        class_name,
                        conditional,
                        module_scope=False,
                    )
                case ast.TypeAlias():
                    if isinstance(statement.name, ast.Name):
                        self._record(
                            _qualified(prefix, statement.name.id),
                            "type_alias",
                            statement,
                            conditional,
                            alias_expression=_ast_value(statement.value),
                        )
                case ast.Assign():
                    names = _assignment_names(statement.targets)
                    for name in names:
                        self._record(
                            _qualified(prefix, name),
                            "assignment",
                            statement,
                            conditional,
                        )
                    if module_scope and "__getattr__" in names:
                        self.has_dynamic_getattr = True
                    if module_scope and "__all__" in names:
                        self._set_exports(statement.value)
                case ast.AnnAssign():
                    if statement.value is not None:
                        names = _assignment_names((statement.target,))
                        for name in names:
                            self._record(
                                _qualified(prefix, name),
                                "assignment",
                                statement,
                                conditional,
                            )
                        if module_scope and "__getattr__" in names:
                            self.has_dynamic_getattr = True
                        if module_scope and "__all__" in names:
                            self._set_exports(statement.value)
                case ast.AugAssign():
                    names = _assignment_names((statement.target,))
                    for name in names:
                        self._record(
                            _qualified(prefix, name),
                            "assignment",
                            statement,
                            conditional,
                        )
                    if module_scope and "__getattr__" in names:
                        self.has_dynamic_getattr = True
                    if module_scope and "__all__" in names:
                        self.has_dynamic_exports = True
                        self.explicit_exports = None
                case ast.Import():
                    self._collect_import(statement, prefix, conditional)
                case ast.ImportFrom():
                    self._collect_import_from(statement, prefix, conditional)
                case ast.If():
                    self._collect_statements(
                        statement.body, prefix, True, module_scope=module_scope
                    )
                    self._collect_statements(
                        statement.orelse, prefix, True, module_scope=module_scope
                    )
                case ast.Try() | ast.TryStar():
                    branches = [statement.body, statement.orelse, statement.finalbody]
                    branches.extend(handler.body for handler in statement.handlers)
                    for branch in branches:
                        self._collect_statements(
                            branch, prefix, True, module_scope=module_scope
                        )
                case (
                    ast.For()
                    | ast.AsyncFor()
                    | ast.While()
                    | ast.With()
                    | ast.AsyncWith()
                ):
                    self._collect_statements(
                        statement.body, prefix, True, module_scope=module_scope
                    )
                    self._collect_statements(
                        getattr(statement, "orelse", []),
                        prefix,
                        True,
                        module_scope=module_scope,
                    )
                case ast.Match():
                    for case in statement.cases:
                        self._collect_statements(
                            case.body, prefix, True, module_scope=module_scope
                        )
                case _:
                    continue

    def _collect_import(
        self, statement: ast.Import, prefix: str, conditional: bool
    ) -> None:
        for alias in statement.names:
            if alias.asname is None:
                local_name = alias.name.split(".", maxsplit=1)[0]
                module_name = local_name
            else:
                local_name = alias.asname
                module_name = alias.name
            binding = ImportBinding(
                local_name=local_name,
                module_name=module_name,
                imported_name=None,
                level=0,
                wildcard=False,
                line=statement.lineno,
                conditional=conditional,
            )
            self.imports.append(binding)
            self._record(
                _qualified(prefix, local_name),
                "import",
                statement,
                conditional,
                import_binding=binding,
            )

    def _collect_import_from(
        self, statement: ast.ImportFrom, prefix: str, conditional: bool
    ) -> None:
        for alias in statement.names:
            wildcard = alias.name == "*"
            local_name = None if wildcard else (alias.asname or alias.name)
            binding = ImportBinding(
                local_name=local_name,
                module_name=statement.module,
                imported_name=None if wildcard else alias.name,
                level=statement.level,
                wildcard=wildcard,
                line=statement.lineno,
                conditional=conditional,
            )
            self.imports.append(binding)
            if wildcard:
                self.has_wildcard_import = True
            else:
                assert local_name is not None
                self._record(
                    _qualified(prefix, local_name),
                    "import",
                    statement,
                    conditional,
                    import_binding=binding,
                )

    def _set_exports(self, value: ast.expr | None) -> None:
        if isinstance(value, (ast.List, ast.Tuple)):
            exports: list[str] = []
            for item in value.elts:
                if not isinstance(item, ast.Constant) or not isinstance(
                    item.value, str
                ):
                    break
                exports.append(item.value)
            else:
                self.explicit_exports = tuple(exports)
                return
        self.has_dynamic_exports = True
        self.explicit_exports = None


def _qualified(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def _ast_value(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _assignment_names(
    targets: tuple[ast.expr, ...] | list[ast.expr],
) -> tuple[str, ...]:
    names: list[str] = []
    for target in targets:
        match target:
            case ast.Name(id=name):
                names.append(name)
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                names.extend(_assignment_names(elements))
            case ast.Starred(value=value):
                names.extend(_assignment_names((value,)))
    return tuple(names)


def _callable_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> CallableSignature:
    arguments = node.args
    positional = (*arguments.posonlyargs, *arguments.args)
    positional_default_start = len(positional) - len(arguments.defaults)
    parameters: list[Parameter] = []
    for index, argument in enumerate(positional):
        default_node = (
            arguments.defaults[index - positional_default_start]
            if index >= positional_default_start
            else None
        )
        kind: ParameterKind = (
            "positional_only"
            if index < len(arguments.posonlyargs)
            else "positional_or_keyword"
        )
        parameters.append(
            Parameter(
                name=argument.arg,
                kind=kind,
                annotation=(
                    _ast_value(argument.annotation)
                    if argument.annotation is not None
                    else None
                ),
                default=_ast_value(default_node) if default_node is not None else None,
            )
        )
    if arguments.vararg is not None:
        parameters.append(
            Parameter(
                name=arguments.vararg.arg,
                kind="var_positional",
                annotation=(
                    _ast_value(arguments.vararg.annotation)
                    if arguments.vararg.annotation is not None
                    else None
                ),
                default=None,
            )
        )
    for argument, default_node in zip(
        arguments.kwonlyargs, arguments.kw_defaults, strict=True
    ):
        parameters.append(
            Parameter(
                name=argument.arg,
                kind="keyword_only",
                annotation=(
                    _ast_value(argument.annotation)
                    if argument.annotation is not None
                    else None
                ),
                default=_ast_value(default_node) if default_node is not None else None,
            )
        )
    if arguments.kwarg is not None:
        parameters.append(
            Parameter(
                name=arguments.kwarg.arg,
                kind="var_keyword",
                annotation=(
                    _ast_value(arguments.kwarg.annotation)
                    if arguments.kwarg.annotation is not None
                    else None
                ),
                default=None,
            )
        )
    return CallableSignature(
        is_async=isinstance(node, ast.AsyncFunctionDef),
        parameters=tuple(parameters),
        returns=_ast_value(node.returns) if node.returns is not None else None,
        type_parameters=tuple(_ast_value(item) for item in node.type_params),
    )


def parse_signature_header(source: str) -> tuple[str, CallableSignature] | None:
    if not source.rstrip().endswith(":"):
        return None
    try:
        module = ast.parse(f"{source}\n    pass\n", type_comments=True)
    except (SyntaxError, ValueError):
        return None
    if len(module.body) != 1:
        return None
    node = module.body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if node.decorator_list:
        return None
    return node.name, _callable_signature(node)


def _module_name(
    relative_path: PurePosixPath, module_prefix: str | None
) -> tuple[str | None, bool]:
    is_package = relative_path.name in {"__init__.py", "__init__.pyi"}
    if is_package:
        parts = relative_path.parent.parts
    else:
        parts = (*relative_path.parent.parts, relative_path.stem)
    prefix_parts = tuple(module_prefix.split(".")) if module_prefix else ()
    full_parts = (*prefix_parts, *parts)
    if not full_parts:
        return None, is_package
    return ".".join(full_parts), is_package


def _module_name_for_directory(
    relative_path: PurePosixPath, module_prefix: str | None
) -> str | None:
    prefix_parts = tuple(module_prefix.split(".")) if module_prefix else ()
    parts = (*prefix_parts, *relative_path.parts)
    return ".".join(parts) if parts else None


def _valid_relative_path(value: str) -> bool:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
    ):
        return False
    if any(character in value for character in "*?[]{}"):
        return False
    if value == ".":
        return True
    return all(component not in {"", ".", ".."} for component in value.split("/"))


def _valid_module_name(value: str | None) -> bool:
    return value is None or all(
        component.isidentifier() and not keyword.iskeyword(component)
        for component in value.split(".")
    )


def _issue(
    code: str,
    outcome: IssueOutcome,
    message: str,
    *,
    root_id: str | None = None,
    path: str | None = None,
) -> IndexIssue:
    return IndexIssue(code, outcome, message, root_id, path)


def _validated_roots(
    context: ValidationContext,
) -> tuple[Path | None, tuple[IndexedRoot, ...], tuple[IndexIssue, ...]]:
    issues: list[IndexIssue] = []
    try:
        workspace = context.workspace.resolve(strict=True)
    except OSError as error:
        return (
            None,
            (),
            (
                _issue(
                    "context.workspace_unavailable",
                    "invalid",
                    f"Workspace directory is unavailable: {error}.",
                ),
            ),
        )
    if not workspace.is_dir():
        return (
            None,
            (),
            (
                _issue(
                    "context.workspace_invalid",
                    "invalid",
                    "Workspace must be a directory.",
                ),
            ),
        )

    seen_ids: set[str] = set()
    valid_roots: list[IndexedRoot] = []
    workspace_roots = [root for root in context.roots if root.root_id == "workspace"]
    if not workspace_roots:
        issues.append(
            _issue(
                "context.missing_workspace_root",
                "invalid",
                "A source root with ID 'workspace' is required.",
            )
        )

    for root in context.roots:
        if root.root_id in seen_ids:
            issues.append(
                _issue(
                    "context.duplicate_root_id",
                    "invalid",
                    f"Root ID {root.root_id!r} is duplicated.",
                    root_id=root.root_id,
                )
            )
            continue
        seen_ids.add(root.root_id)
        if not root.root_id.strip():
            issues.append(
                _issue(
                    "context.invalid_root_id", "invalid", "Root ID must not be blank."
                )
            )
            continue
        if root.path.is_symlink():
            issues.append(
                _issue(
                    "context.root_symlink",
                    "invalid",
                    "Source roots cannot be symlinks.",
                    root_id=root.root_id,
                )
            )
            continue
        try:
            root_path = root.path.resolve(strict=True)
        except OSError as error:
            issues.append(
                _issue(
                    "context.root_unavailable",
                    "invalid",
                    f"Source root is unavailable: {error}.",
                    root_id=root.root_id,
                )
            )
            continue
        if not root_path.is_dir():
            issues.append(
                _issue(
                    "context.root_not_directory",
                    "invalid",
                    "Source root must be a directory.",
                    root_id=root.root_id,
                )
            )
            continue
        if root.kind == "project":
            try:
                root_path.relative_to(workspace)
            except ValueError:
                issues.append(
                    _issue(
                        "context.project_outside_workspace",
                        "invalid",
                        "Project roots must be within the workspace.",
                        root_id=root.root_id,
                    )
                )
                continue
        if root.root_id == "workspace" and (
            root_path != workspace or root.kind != "project"
        ):
            issues.append(
                _issue(
                    "context.workspace_root_mismatch",
                    "invalid",
                    "Workspace root must be a project root at the workspace directory.",
                    root_id=root.root_id,
                )
            )
            continue
        if root.kind not in {"project", "dependency", "stub"}:
            issues.append(
                _issue(
                    "context.invalid_root_kind",
                    "invalid",
                    "Root kind must be project, dependency, or stub.",
                    root_id=root.root_id,
                )
            )
            continue
        if not _valid_relative_path(root.import_base):
            issues.append(
                _issue(
                    "context.invalid_import_base",
                    "invalid",
                    "Import base must be a canonical relative path.",
                    root_id=root.root_id,
                    path=root.import_base,
                )
            )
            continue
        if not _valid_module_name(root.module_prefix):
            issues.append(
                _issue(
                    "context.invalid_module_prefix",
                    "invalid",
                    "Module prefix must be an absolute dotted Python name.",
                    root_id=root.root_id,
                )
            )
            continue
        if not root.suffixes or any(
            suffix not in {".py", ".pyi"} for suffix in root.suffixes
        ):
            issues.append(
                _issue(
                    "context.invalid_suffixes",
                    "invalid",
                    "Only .py and explicitly configured .pyi suffixes are supported.",
                    root_id=root.root_id,
                )
            )
            continue
        valid_roots.append(
            IndexedRoot(
                root_id=root.root_id,
                path=root_path,
                kind=root.kind,
                import_base=root.import_base,
                module_prefix=root.module_prefix,
                suffixes=tuple(sorted(set(root.suffixes))),
            )
        )

    return workspace, tuple(valid_roots), tuple(issues)


def _root_mapping_data(root: IndexedRoot) -> dict[str, object]:
    return {
        "root_id": root.root_id,
        "path": root.path.as_posix(),
        "kind": root.kind,
        "import_base": root.import_base,
        "module_prefix": root.module_prefix,
        "suffixes": list(root.suffixes),
    }


def _context_fingerprint(
    context: ValidationContext,
    workspace: Path | None,
    roots: tuple[IndexedRoot, ...],
    version: tuple[int, int],
) -> str:
    configured_roots = [
        {
            "root_id": root.root_id,
            "path": Path(root.path).as_posix(),
            "kind": root.kind,
            "import_base": root.import_base,
            "module_prefix": root.module_prefix,
            "suffixes": list(root.suffixes),
        }
        for root in context.roots
    ]
    configured_roots.sort(
        key=lambda root: (
            str(root["root_id"]),
            str(root["path"]),
            str(root["kind"]),
        )
    )
    payload = {
        "workspace": workspace.as_posix() if workspace is not None else None,
        "roots": [_root_mapping_data(root) for root in roots],
        "configured_roots": configured_roots,
        "parser_version": version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint(
    context_fingerprint: str, source_hashes: tuple[SourceHash, ...]
) -> str:
    digest = hashlib.sha256(context_fingerprint.encode())
    for source in source_hashes:
        digest.update(source.root_id.encode())
        digest.update(b"\0")
        digest.update(source.path.encode())
        digest.update(b"\0")
        digest.update(source.sha256.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_source(path: Path) -> tuple[bytes, str]:
    content = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
    return content, content.decode(encoding)


def _module_record(
    root: IndexedRoot,
    path: Path,
    relative_path: str,
    module_name: str | None,
    is_package: bool,
    content: bytes,
    source: str,
) -> tuple[ModuleRecord, IndexIssue | None]:
    fingerprint = hashlib.sha256(content).hexdigest()
    try:
        parsed = ast.parse(source, filename=path.as_posix(), type_comments=True)
    except (SyntaxError, ValueError) as error:
        message = error.msg if isinstance(error, SyntaxError) else str(error)
        return (
            ModuleRecord(
                module_name=module_name,
                root_id=root.root_id,
                path=relative_path,
                sha256=fingerprint,
                definitions=(),
                imports=(),
                is_package=is_package,
                parse_error=message,
            ),
            _issue(
                "index.parse_error",
                "inconclusive",
                f"Source cannot be parsed: {message}.",
                root_id=root.root_id,
                path=relative_path,
            ),
        )
    collector = _ModuleCollector()
    collector.collect(parsed)
    return (
        ModuleRecord(
            module_name=module_name,
            root_id=root.root_id,
            path=relative_path,
            sha256=fingerprint,
            definitions=tuple(collector.definitions),
            imports=tuple(collector.imports),
            is_package=is_package,
            has_dynamic_getattr=collector.has_dynamic_getattr,
            has_dynamic_exports=collector.has_dynamic_exports,
            has_wildcard_import=collector.has_wildcard_import,
            explicit_exports=collector.explicit_exports,
        ),
        None,
    )


def _index_root(
    root: IndexedRoot,
) -> tuple[tuple[ModuleRecord, ...], tuple[SourceHash, ...], tuple[IndexIssue, ...]]:
    base = root.path
    components = () if root.import_base == "." else tuple(root.import_base.split("/"))
    for component in components:
        base = base / component
        try:
            base_metadata = base.lstat()
        except OSError as error:
            return (
                (),
                (),
                (
                    _issue(
                        "index.import_base_unavailable",
                        "invalid",
                        f"Import base is unavailable: {error}.",
                        root_id=root.root_id,
                        path=root.import_base,
                    ),
                ),
            )
        if stat.S_ISLNK(base_metadata.st_mode) or not stat.S_ISDIR(
            base_metadata.st_mode
        ):
            return (
                (),
                (),
                (
                    _issue(
                        "index.import_base_invalid",
                        "invalid",
                        "Import base components must be real directories.",
                        root_id=root.root_id,
                        path=root.import_base,
                    ),
                ),
            )

    modules: list[ModuleRecord] = []
    source_hashes: list[SourceHash] = []
    issues: list[IndexIssue] = []
    visited_directories: list[Path] = []

    def on_error(error: OSError) -> None:
        issues.append(
            _issue(
                "index.source_unavailable",
                "inconclusive",
                f"Cannot inspect source directory: {error}.",
                root_id=root.root_id,
                path=Path(error.filename).as_posix() if error.filename else None,
            )
        )

    for directory, directory_names, file_names in os.walk(
        base, topdown=True, followlinks=False, onerror=on_error
    ):
        current = Path(directory)
        visited_directories.append(current)
        directory_names[:] = sorted(
            name for name in directory_names if not (current / name).is_symlink()
        )
        for name in sorted(file_names):
            source_path = current / name
            if source_path.suffix not in root.suffixes:
                continue
            relative_path = source_path.relative_to(root.path).as_posix()
            try:
                metadata = source_path.lstat()
            except OSError as error:
                issues.append(
                    _issue(
                        "index.source_unavailable",
                        "inconclusive",
                        f"Cannot inspect source file: {error}.",
                        root_id=root.root_id,
                        path=relative_path,
                    )
                )
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                issues.append(
                    _issue(
                        "index.source_not_regular",
                        "inconclusive",
                        "Source must be a regular, non-symlink file.",
                        root_id=root.root_id,
                        path=relative_path,
                    )
                )
                continue
            try:
                content, source = _read_source(source_path)
            except (OSError, SyntaxError, UnicodeError) as error:
                issues.append(
                    _issue(
                        "index.source_unavailable",
                        "inconclusive",
                        f"Cannot read source file: {error}.",
                        root_id=root.root_id,
                        path=relative_path,
                    )
                )
                continue
            module_name, is_package = _module_name(
                PurePosixPath(source_path.relative_to(base).as_posix()),
                root.module_prefix,
            )
            record, parse_issue = _module_record(
                root,
                source_path,
                relative_path,
                module_name,
                is_package,
                content,
                source,
            )
            modules.append(record)
            source_hashes.append(
                SourceHash(
                    root_id=root.root_id,
                    path=relative_path,
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
            if parse_issue is not None:
                issues.append(parse_issue)

    explicit_names = {
        (module.root_id, module.module_name)
        for module in modules
        if module.is_package and module.module_name is not None
    }
    for directory in visited_directories:
        relative_directory = PurePosixPath(directory.relative_to(base).as_posix())
        if str(relative_directory) == ".":
            relative_directory = PurePosixPath()
        module_name = _module_name_for_directory(relative_directory, root.module_prefix)
        if module_name is None or (root.root_id, module_name) in explicit_names:
            continue
        relative_path = directory.relative_to(root.path).as_posix()
        modules.append(
            ModuleRecord(
                module_name=module_name,
                root_id=root.root_id,
                path=relative_path,
                sha256=None,
                definitions=(),
                imports=(),
                is_package=True,
                implicit_namespace=True,
            )
        )

    return tuple(modules), tuple(source_hashes), tuple(issues)


def build_index(context: ValidationContext) -> SymbolIndex:
    workspace, roots, root_issues = _validated_roots(context)
    parser_version = sys.version_info.major, sys.version_info.minor
    context_fingerprint = _context_fingerprint(
        context, workspace, roots, parser_version
    )
    modules: list[ModuleRecord] = []
    source_hashes: list[SourceHash] = []
    issues = list(root_issues)
    for root in roots:
        root_modules, root_hashes, root_issues = _index_root(root)
        modules.extend(root_modules)
        source_hashes.extend(root_hashes)
        issues.extend(root_issues)
    ordered_hashes = tuple(
        sorted(source_hashes, key=lambda item: (item.root_id, item.path))
    )
    ordered_modules = tuple(
        sorted(
            modules,
            key=lambda item: (
                item.root_id,
                item.module_name or "",
                item.path,
            ),
        )
    )
    ordered_issues = tuple(
        sorted(
            issues,
            key=lambda item: (
                item.root_id or "",
                item.path or "",
                item.code,
                item.message,
            ),
        )
    )
    return SymbolIndex(
        roots=roots,
        modules=ordered_modules,
        source_hashes=ordered_hashes,
        issues=ordered_issues,
        parser_version=parser_version,
        context_fingerprint=context_fingerprint,
        fingerprint=_fingerprint(context_fingerprint, ordered_hashes),
    )
