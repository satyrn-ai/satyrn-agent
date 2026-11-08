import ast
import json
import keyword
import math
from dataclasses import dataclass
from typing import Literal, Never, cast

type Operation = Literal["create", "modify", "delete"]
type ProduceOperation = Literal["create", "modify"]
type ProduceKind = Literal["function", "async_function", "class", "type_alias"]
type ImportTarget = Literal["existing", "planned"]
type ExitCode = int | Literal["nonzero"]
type DiagnosticOutcome = Literal["invalid", "inconclusive"]
type ValidationStatus = Literal["valid", "invalid", "inconclusive"]


class PacketDecodeError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message
        super().__init__(self.__str__())

    def __str__(self) -> str:
        location = self.field or "/"
        return f"{self.code} at {location}: {self.message}"


@dataclass(frozen=True, slots=True)
class SourceReference:
    root_id: str
    path: str


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    operation: Operation


@dataclass(frozen=True, slots=True)
class Consume:
    source: SourceReference
    qualified_name: str
    expected_signature: str | None


@dataclass(frozen=True, slots=True)
class Produce:
    path: str
    qualified_name: str
    operation: ProduceOperation
    kind: ProduceKind
    declaration: str


@dataclass(frozen=True, slots=True)
class ImportReference:
    path: str
    module: str
    name: str | None
    alias: str | None
    target: ImportTarget


@dataclass(frozen=True, slots=True)
class TestArtifact:
    path: str
    operation: ProduceOperation
    content: str


@dataclass(frozen=True, slots=True)
class GateExpectation:
    exit_code: ExitCode
    reason: str


@dataclass(frozen=True, slots=True)
class Gate:
    argv: tuple[str, ...]
    cwd: str
    before: GateExpectation
    after: GateExpectation


@dataclass(frozen=True, slots=True)
class Packet:
    schema_version: Literal[0]
    packet_id: str
    task: str
    readable_files: tuple[str, ...]
    file_changes: tuple[FileChange, ...]
    consumes: tuple[Consume, ...]
    produces: tuple[Produce, ...]
    imports: tuple[ImportReference, ...]
    tests: tuple[TestArtifact, ...]
    gates: tuple[Gate, ...]
    known_facts: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    preserved_behavior: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    outcome: DiagnosticOutcome
    field: str
    message: str
    path: str | None = None
    symbol: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    status: ValidationStatus
    diagnostics: tuple[Diagnostic, ...]
    unverified_requirements: tuple[str, ...]
    input_fingerprint: str

    @property
    def ready(self) -> bool:
        return self.status == "valid"


@dataclass(frozen=True, slots=True)
class _JsonObject:
    pairs: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class _JsonConstant:
    value: str


def _pointer(parent: str, component: str | int) -> str:
    escaped = str(component).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _fail(field: str, code: str, message: str) -> Never:
    raise PacketDecodeError(field, code, message)


def _normalize_json(value: object, field: str = "") -> object:
    if isinstance(value, _JsonConstant):
        _fail(
            field,
            "json.non_finite",
            f"Non-finite number {value.value!r} is not allowed.",
        )
    if isinstance(value, _JsonObject):
        result: dict[str, object] = {}
        for key, item in value.pairs:
            key_field = _pointer(field, key)
            if key in result:
                _fail(key_field, "json.duplicate_key", "Duplicate object key.")
            result[key] = _normalize_json(item, key_field)
        return result
    if isinstance(value, list):
        return [
            _normalize_json(item, _pointer(field, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, float) and not math.isfinite(value):
        _fail(field, "json.non_finite", "Non-finite numbers are not allowed.")
    return value


def _object(
    value: object,
    field: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail(field, "contract.type", "Expected a JSON object.")
    value = cast(dict[str, object], value)
    allowed = set(required) | set(optional)
    unknown = sorted(set(value) - allowed)
    if unknown:
        name = unknown[0]
        _fail(_pointer(field, name), "contract.unknown_field", "Unknown field.")
    for name in required:
        if name not in value:
            _fail(
                _pointer(field, name),
                "contract.missing_field",
                "Required field is missing.",
            )
    return value


def _array(value: object, field: str, *, nonempty: bool = False) -> list[object]:
    if not isinstance(value, list):
        _fail(field, "contract.type", "Expected a JSON array.")
    value = cast(list[object], value)
    if nonempty and not value:
        _fail(field, "contract.empty_array", "Array must not be empty.")
    return value


def _string(value: object, field: str, *, nonblank: bool = True) -> str:
    if not isinstance(value, str):
        _fail(field, "contract.type", "Expected a string.")
    if nonblank and not value.strip():
        _fail(field, "contract.blank_string", "String must not be blank.")
    return value


def _enum[T: str](value: object, field: str, allowed: tuple[T, ...]) -> T:
    text = _string(value, field)
    if text not in allowed:
        _fail(field, "contract.enum", f"Expected one of: {', '.join(allowed)}.")
    return cast(T, text)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(field, "contract.type", "Expected an integer.")
    return value


def _identifier(value: object, field: str) -> str:
    text = _string(value, field)
    if not text.isidentifier() or keyword.iskeyword(text):
        _fail(field, "contract.identifier", "Expected a Python identifier.")
    return text


def _qualified_name(value: object, field: str) -> str:
    text = _string(value, field)
    components = text.split(".")
    if any(not item.isidentifier() or keyword.iskeyword(item) for item in components):
        _fail(field, "contract.qualified_name", "Expected a dotted Python name.")
    return text


def _module_name(value: object, field: str) -> str:
    text = _string(value, field)
    components = text.split(".")
    if any(not item.isidentifier() or keyword.iskeyword(item) for item in components):
        _fail(field, "contract.module_name", "Expected an absolute dotted module name.")
    return text


def _parse_declaration(
    declaration: str, kind: str, qualified_name: str, field: str
) -> None:
    source = declaration
    if kind in {"function", "async_function", "class"}:
        if not declaration.rstrip().endswith(":"):
            _fail(
                field,
                "contract.declaration",
                "Expected a declaration header ending in ':'.",
            )
        source = f"{declaration}\n    pass\n"
    try:
        module = ast.parse(source, mode="exec", type_comments=True)
    except (SyntaxError, ValueError) as error:
        detail = error.msg if isinstance(error, SyntaxError) else str(error)
        _fail(
            field,
            "contract.declaration",
            f"Invalid Python declaration: {detail}.",
        )
    if len(module.body) != 1:
        _fail(field, "contract.declaration", "Expected exactly one Python declaration.")
    node = module.body[0]
    expected_name = qualified_name.rsplit(".", maxsplit=1)[-1]
    valid = False
    match kind, node:
        case "function", ast.FunctionDef():
            valid = node.name == expected_name and not node.decorator_list
        case "async_function", ast.AsyncFunctionDef():
            valid = node.name == expected_name and not node.decorator_list
        case "class", ast.ClassDef():
            valid = node.name == expected_name and not node.decorator_list
        case "type_alias", ast.TypeAlias(name=ast.Name(id=name)):
            valid = name == expected_name
        case _:
            valid = False
    if not valid:
        _fail(
            field,
            "contract.declaration",
            "Declaration name or kind does not match the entry.",
        )


def _parse_expectation(value: object, field: str) -> GateExpectation:
    item = _object(value, field, ("exit_code", "reason"))
    raw_code = item["exit_code"]
    if raw_code == "nonzero":
        exit_code: ExitCode = "nonzero"
    else:
        exit_code = _integer(raw_code, _pointer(field, "exit_code"))
    return GateExpectation(
        exit_code=exit_code,
        reason=_string(item["reason"], _pointer(field, "reason")),
    )


def decode_packet(document: str) -> Packet:
    if not isinstance(document, str):
        _fail("", "json.type", "Packet document must be text.")
    try:
        raw = json.loads(
            document,
            object_pairs_hook=lambda pairs: _JsonObject(tuple(pairs)),
            parse_constant=_JsonConstant,
        )
    except json.JSONDecodeError as error:
        _fail(
            "",
            "json.syntax",
            f"Invalid JSON at line {error.lineno}, column {error.colno}.",
        )
    raw = _normalize_json(raw)
    data = _object(
        raw,
        "",
        (
            "schema_version",
            "packet_id",
            "task",
            "readable_files",
            "file_changes",
            "consumes",
            "produces",
            "imports",
            "tests",
            "gates",
            "known_facts",
            "acceptance_criteria",
            "preserved_behavior",
        ),
    )
    schema_version = _integer(data["schema_version"], "/schema_version")
    if schema_version != 0:
        _fail(
            "/schema_version", "contract.version", "Only schema version 0 is supported."
        )

    readable_files = tuple(
        _string(item, _pointer("/readable_files", index))
        for index, item in enumerate(_array(data["readable_files"], "/readable_files"))
    )
    file_changes_list: list[FileChange] = []
    for index, raw_change in enumerate(
        _array(data["file_changes"], "/file_changes", nonempty=True)
    ):
        field = _pointer("/file_changes", index)
        change = _object(raw_change, field, ("path", "operation"))
        operation = _enum(
            change["operation"],
            _pointer(field, "operation"),
            ("create", "modify", "delete"),
        )
        file_changes_list.append(
            FileChange(
                path=_string(change["path"], _pointer(field, "path")),
                operation=operation,
            )
        )
    _reject_duplicate_paths(
        tuple(
            (change.path, _pointer("/file_changes", index) + "/path")
            for index, change in enumerate(file_changes_list)
        ),
        "file_changes",
    )
    file_changes = tuple(file_changes_list)

    consumes_list: list[Consume] = []
    for index, raw_consume in enumerate(_array(data["consumes"], "/consumes")):
        field = _pointer("/consumes", index)
        consume = _object(
            raw_consume,
            field,
            ("source", "qualified_name", "expected_signature"),
        )
        raw_source = _object(
            consume["source"],
            _pointer(field, "source"),
            ("root_id", "path"),
        )
        source = SourceReference(
            root_id=_string(
                raw_source["root_id"], _pointer(_pointer(field, "source"), "root_id")
            ),
            path=_string(
                raw_source["path"], _pointer(_pointer(field, "source"), "path")
            ),
        )
        signature = consume["expected_signature"]
        if signature is not None:
            signature = _string(signature, _pointer(field, "expected_signature"))
        consumes_list.append(
            Consume(
                source=source,
                qualified_name=_qualified_name(
                    consume["qualified_name"], _pointer(field, "qualified_name")
                ),
                expected_signature=signature,
            )
        )
    consumes = tuple(consumes_list)

    produces_list: list[Produce] = []
    for index, raw_produce in enumerate(_array(data["produces"], "/produces")):
        field = _pointer("/produces", index)
        produce = _object(
            raw_produce,
            field,
            ("path", "qualified_name", "operation", "kind", "declaration"),
        )
        qualified_name = _qualified_name(
            produce["qualified_name"], _pointer(field, "qualified_name")
        )
        kind = _enum(
            produce["kind"],
            _pointer(field, "kind"),
            ("function", "async_function", "class", "type_alias"),
        )
        declaration = _string(produce["declaration"], _pointer(field, "declaration"))
        _parse_declaration(
            declaration, kind, qualified_name, _pointer(field, "declaration")
        )
        produces_list.append(
            Produce(
                path=_string(produce["path"], _pointer(field, "path")),
                qualified_name=qualified_name,
                operation=_enum(
                    produce["operation"],
                    _pointer(field, "operation"),
                    ("create", "modify"),
                ),
                kind=kind,
                declaration=declaration,
            )
        )
    produces = tuple(produces_list)

    imports_list: list[ImportReference] = []
    for index, raw_import in enumerate(_array(data["imports"], "/imports")):
        field = _pointer("/imports", index)
        imported = _object(
            raw_import,
            field,
            ("path", "module", "name", "alias", "target"),
        )
        name = imported["name"]
        alias = imported["alias"]
        imports_list.append(
            ImportReference(
                path=_string(imported["path"], _pointer(field, "path")),
                module=_module_name(imported["module"], _pointer(field, "module")),
                name=(
                    None if name is None else _identifier(name, _pointer(field, "name"))
                ),
                alias=(
                    None
                    if alias is None
                    else _identifier(alias, _pointer(field, "alias"))
                ),
                target=_enum(
                    imported["target"],
                    _pointer(field, "target"),
                    ("existing", "planned"),
                ),
            )
        )
    imports = tuple(imports_list)

    tests_list: list[TestArtifact] = []
    for index, raw_test in enumerate(_array(data["tests"], "/tests", nonempty=True)):
        field = _pointer("/tests", index)
        test = _object(raw_test, field, ("path", "operation", "content"))
        path = _string(test["path"], _pointer(field, "path"))
        content = _string(test["content"], _pointer(field, "content"), nonblank=False)
        try:
            ast.parse(content, filename=path, type_comments=True)
        except (SyntaxError, ValueError) as error:
            detail = error.msg if isinstance(error, SyntaxError) else str(error)
            _fail(
                _pointer(field, "content"),
                "contract.test_syntax",
                f"Invalid Python test source: {detail}.",
            )
        tests_list.append(
            TestArtifact(
                path=path,
                operation=_enum(
                    test["operation"],
                    _pointer(field, "operation"),
                    ("create", "modify"),
                ),
                content=content,
            )
        )
    tests = tuple(tests_list)

    gates_list: list[Gate] = []
    for index, raw_gate in enumerate(_array(data["gates"], "/gates", nonempty=True)):
        field = _pointer("/gates", index)
        gate = _object(raw_gate, field, ("argv", "cwd", "before", "after"))
        argv = tuple(
            _string(item, _pointer(_pointer(field, "argv"), arg_index))
            for arg_index, item in enumerate(
                _array(gate["argv"], _pointer(field, "argv"), nonempty=True)
            )
        )
        gates_list.append(
            Gate(
                argv=argv,
                cwd=_string(gate["cwd"], _pointer(field, "cwd")),
                before=_parse_expectation(gate["before"], _pointer(field, "before")),
                after=_parse_expectation(gate["after"], _pointer(field, "after")),
            )
        )
    gates = tuple(gates_list)

    known_facts = tuple(
        _string(item, _pointer("/known_facts", index), nonblank=False)
        for index, item in enumerate(_array(data["known_facts"], "/known_facts"))
    )
    acceptance_criteria = tuple(
        _string(item, _pointer("/acceptance_criteria", index))
        for index, item in enumerate(
            _array(data["acceptance_criteria"], "/acceptance_criteria", nonempty=True)
        )
    )
    preserved_behavior = tuple(
        _string(item, _pointer("/preserved_behavior", index))
        for index, item in enumerate(
            _array(data["preserved_behavior"], "/preserved_behavior")
        )
    )
    packet = Packet(
        schema_version=0,
        packet_id=_string(data["packet_id"], "/packet_id"),
        task=_string(data["task"], "/task"),
        readable_files=readable_files,
        file_changes=file_changes,
        consumes=consumes,
        produces=produces,
        imports=imports,
        tests=tests,
        gates=gates,
        known_facts=known_facts,
        acceptance_criteria=acceptance_criteria,
        preserved_behavior=preserved_behavior,
    )
    _validate_declaration_access(packet)
    return packet


def _reject_duplicate_paths(entries: tuple[tuple[str, str], ...], label: str) -> None:
    seen: set[str] = set()
    for path, field in entries:
        if path in seen:
            _fail(field, f"contract.duplicate_{label}", "Duplicate path declaration.")
        seen.add(path)


def _validate_declaration_access(packet: Packet) -> None:
    changes = {change.path: change.operation for change in packet.file_changes}
    _reject_duplicate_paths(
        tuple(
            (path, _pointer("/readable_files", index))
            for index, path in enumerate(packet.readable_files)
        ),
        "readable_file",
    )
    _reject_duplicate_paths(
        tuple(
            (test.path, _pointer(_pointer("/tests", index), "path"))
            for index, test in enumerate(packet.tests)
        ),
        "test_artifact",
    )

    for index, produce in enumerate(packet.produces):
        field = _pointer("/produces", index)
        file_operation = changes.get(produce.path)
        allowed_file_operations = (
            {"create", "modify"} if produce.operation == "create" else {"modify"}
        )
        if file_operation not in allowed_file_operations:
            _fail(
                _pointer(field, "path"),
                "contract.produce_access",
                "Produced definitions must match a create or modify file change.",
            )
    for index, test in enumerate(packet.tests):
        field = _pointer("/tests", index)
        if changes.get(test.path) != test.operation:
            _fail(
                _pointer(field, "path"),
                "contract.test_access",
                "Test artifacts must match a create or modify file change.",
            )
    for index, imported in enumerate(packet.imports):
        if imported.path not in set(packet.readable_files) | set(changes):
            _fail(
                _pointer(_pointer("/imports", index), "path"),
                "contract.import_access",
                "Importing files must be declared readable or writable.",
            )

    seen_symbols: set[tuple[str, str]] = set()
    for index, produce in enumerate(packet.produces):
        key = produce.path, produce.qualified_name
        if key in seen_symbols:
            _fail(
                _pointer(_pointer("/produces", index), "qualified_name"),
                "contract.duplicate_produce",
                "A produced symbol may be declared only once per file.",
            )
        seen_symbols.add(key)

    consumed: set[tuple[str, str, str]] = set()
    for index, item in enumerate(packet.consumes):
        key = item.source.root_id, item.source.path, item.qualified_name
        if key in consumed:
            _fail(
                _pointer(_pointer("/consumes", index), "qualified_name"),
                "contract.duplicate_consume",
                "A consumed symbol may be declared only once.",
            )
        consumed.add(key)

    seen_imports: set[tuple[str, str, str | None, str | None, str]] = set()
    seen_import_bindings: set[tuple[str, str]] = set()
    for index, item in enumerate(packet.imports):
        key = item.path, item.module, item.name, item.alias, item.target
        if key in seen_imports:
            _fail(
                _pointer(_pointer("/imports", index), "module"),
                "contract.duplicate_import",
                "An import declaration may appear only once.",
            )
        seen_imports.add(key)
        local_name = item.alias or item.name or item.module.split(".", maxsplit=1)[0]
        binding = item.path, local_name
        if binding in seen_import_bindings:
            _fail(
                _pointer(_pointer("/imports", index), "alias"),
                "contract.import_binding_conflict",
                "Multiple import declarations bind the same local name.",
            )
        seen_import_bindings.add(binding)


def _packet_as_dict(packet: Packet) -> dict[str, object]:
    return {
        "schema_version": packet.schema_version,
        "packet_id": packet.packet_id,
        "task": packet.task,
        "readable_files": list(packet.readable_files),
        "file_changes": [
            {"path": item.path, "operation": item.operation}
            for item in packet.file_changes
        ],
        "consumes": [
            {
                "source": {"root_id": item.source.root_id, "path": item.source.path},
                "qualified_name": item.qualified_name,
                "expected_signature": item.expected_signature,
            }
            for item in packet.consumes
        ],
        "produces": [
            {
                "path": item.path,
                "qualified_name": item.qualified_name,
                "operation": item.operation,
                "kind": item.kind,
                "declaration": item.declaration,
            }
            for item in packet.produces
        ],
        "imports": [
            {
                "path": item.path,
                "module": item.module,
                "name": item.name,
                "alias": item.alias,
                "target": item.target,
            }
            for item in packet.imports
        ],
        "tests": [
            {"path": item.path, "operation": item.operation, "content": item.content}
            for item in packet.tests
        ],
        "gates": [
            {
                "argv": list(item.argv),
                "cwd": item.cwd,
                "before": {
                    "exit_code": item.before.exit_code,
                    "reason": item.before.reason,
                },
                "after": {
                    "exit_code": item.after.exit_code,
                    "reason": item.after.reason,
                },
            }
            for item in packet.gates
        ],
        "known_facts": list(packet.known_facts),
        "acceptance_criteria": list(packet.acceptance_criteria),
        "preserved_behavior": list(packet.preserved_behavior),
    }


def encode_packet(packet: Packet) -> str:
    return json.dumps(
        _packet_as_dict(packet),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
