from pathlib import Path

import pytest

from typed_packets.contract import Packet, decode_packet
from typed_packets.index import SourceRoot, ValidationContext, build_index
from typed_packets.resolve import (
    resolve_import_reference,
    resolve_module_symbol,
    resolve_planned,
    resolve_symbol,
)


def test_resolver_follows_relative_reexports_and_compares_signatures(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "api.py").write_text(
        "from .domain import Contact as PublicContact\n"
        "from .facade import contact_label\n"
    )
    (source_workspace / "src" / "crm" / "facade.py").write_text(
        "from .domain import format_contact as contact_label\n"
    )
    (source_workspace / "src" / "crm" / "domain.py").write_text(
        "class Contact:\n    pass\n"
        "def format_contact(name: str, *, terse: bool = False) -> str:\n"
        "    return name\n"
    )
    index = build_index(source_context)

    contact = resolve_symbol(index, "workspace", "src/crm/api.py", "PublicContact")
    signature = resolve_symbol(
        index,
        "workspace",
        "src/crm/api.py",
        "contact_label",
        expected_signature=("def contact_label( name:str, *,terse:bool=False)->str:"),
    )
    mismatch = resolve_symbol(
        index,
        "workspace",
        "src/crm/api.py",
        "contact_label",
        expected_signature="def contact_label(name: str) -> str:",
    )

    assert contact.outcome == "valid"
    assert contact.definition is not None
    assert contact.definition.qualified_name == "Contact"
    assert signature.outcome == "valid"
    assert mismatch.outcome == "invalid"


@pytest.mark.parametrize(
    "expected_signature",
    [
        "def serve(item: object, /, *, strict: bool = False) -> int:",
        "def serve(item: str, *, strict: bool = False) -> int:",
        "def serve(item: str, /, *, strict: bool = True) -> int:",
        "def serve(item: str, /, *, strict: bool = False) -> str:",
        "async def serve(item: str, /, *, strict: bool = False) -> int:",
    ],
)
def test_resolver_detects_structural_signature_changes(
    source_workspace: Path,
    source_context: ValidationContext,
    expected_signature: str,
) -> None:
    source = source_workspace / "src" / "crm" / "service.py"
    source.write_text(
        "def serve(item: str, /, *, strict: bool = False) -> int:\n    return 1\n"
    )

    result = resolve_symbol(
        build_index(source_context),
        "workspace",
        "src/crm/service.py",
        "serve",
        expected_signature=expected_signature,
    )

    assert result.outcome == "invalid"


def test_resolver_supports_module_imports_and_namespace_submodules(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "api.py").write_text(
        "import crm.domain as domain_module\n"
        "import crm.domain\n"
        "from . import domain as relative_domain\n"
    )
    (source_workspace / "src" / "crm" / "domain.py").write_text(
        "class Contact:\n    pass\n"
    )
    index = build_index(source_context)

    module = resolve_symbol(index, "workspace", "src/crm/api.py", "domain_module")
    direct = resolve_symbol(
        index, "workspace", "src/crm/api.py", "domain_module.Contact"
    )
    dotted = resolve_symbol(index, "workspace", "src/crm/api.py", "crm.domain.Contact")
    relative = resolve_symbol(
        index, "workspace", "src/crm/api.py", "relative_domain.Contact"
    )

    assert module.outcome == "valid"
    assert module.module_name == "crm.domain"
    assert direct.outcome == "valid"
    assert dotted.outcome == "valid"
    assert relative.outcome == "valid"


def test_resolver_proves_symbols_in_an_unmapped_package_initializer(
    source_workspace: Path,
) -> None:
    source = source_workspace / "__init__.py"
    source.write_text("RootValue = 1\n")
    context = ValidationContext(
        workspace=source_workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=source_workspace,
                kind="project",
            ),
        ),
    )

    result = resolve_symbol(
        build_index(context), "workspace", "__init__.py", "RootValue"
    )

    assert result.outcome == "valid"


def test_resolver_proves_direct_symbols_without_following_unrelated_cycles(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "a.py").write_text(
        "from .b import absent\ndef direct() -> None:\n    pass\n"
    )
    (source_workspace / "src" / "crm" / "b.py").write_text("from .a import absent\n")
    index = build_index(source_context)

    direct = resolve_symbol(index, "workspace", "src/crm/a.py", "direct")
    cycle = resolve_symbol(index, "workspace", "src/crm/a.py", "absent")

    assert direct.outcome == "valid"
    assert cycle.outcome == "inconclusive"


def test_resolver_distinguishes_definite_absence_and_dynamic_exports(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "static.py").write_text("value = 1\n")
    (source_workspace / "src" / "crm" / "dynamic.py").write_text(
        "def __getattr__(name: str):\n    return None\n"
    )
    (source_workspace / "src" / "crm" / "assigned_dynamic.py").write_text(
        "__getattr__ = dynamic_lookup\n"
    )
    index = build_index(source_context)

    absent = resolve_symbol(index, "workspace", "src/crm/static.py", "missing")
    dynamic = resolve_symbol(index, "workspace", "src/crm/dynamic.py", "missing")
    assigned_dynamic = resolve_symbol(
        index, "workspace", "src/crm/assigned_dynamic.py", "missing"
    )
    unavailable = resolve_symbol(index, "workspace", "src/crm/missing.py", "anything")

    assert absent.outcome == "invalid"
    assert dynamic.outcome == "inconclusive"
    assert assigned_dynamic.outcome == "inconclusive"
    assert unavailable.outcome == "inconclusive"


def test_resolver_does_not_treat_annotation_only_names_as_bound(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "annotations.py").write_text(
        "annotated_only: int\n"
    )

    result = resolve_symbol(
        build_index(source_context),
        "workspace",
        "src/crm/annotations.py",
        "annotated_only",
    )

    assert result.outcome == "invalid"


def test_resolver_keeps_decorated_and_inherited_interfaces_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "interfaces.py").write_text(
        "@decorate\n"
        "def decorated(value: int) -> str:\n    return str(value)\n"
        "class Derived(Base):\n    pass\n"
        "class Plain:\n    pass\n"
        "if TYPE_CHECKING:\n"
        "    def conditional() -> None:\n        pass\n"
        "def outer() -> None:\n"
        "    def inner() -> None:\n        pass\n"
    )
    index = build_index(source_context)

    decorated = resolve_symbol(index, "workspace", "src/crm/interfaces.py", "decorated")
    inherited = resolve_symbol(
        index, "workspace", "src/crm/interfaces.py", "Derived.inherited"
    )
    absent = resolve_symbol(index, "workspace", "src/crm/interfaces.py", "Plain.absent")
    conditional = resolve_symbol(
        index, "workspace", "src/crm/interfaces.py", "conditional"
    )
    local = resolve_symbol(index, "workspace", "src/crm/interfaces.py", "inner")

    assert decorated.outcome == "inconclusive"
    assert inherited.outcome == "inconclusive"
    assert absent.outcome == "invalid"
    assert conditional.outcome == "inconclusive"
    assert local.outcome == "invalid"


@pytest.mark.parametrize(
    "source",
    [
        "from dataclasses import dataclass\n@dataclass(frozen=True)\n",
        "from dataclasses import dataclass as dc\n@dc\n",
        "import dataclasses\n@dataclasses.dataclass(slots=True)\n",
        "import dataclasses as dcs\n@dcs.dataclass\n",
    ],
)
def test_resolver_trusts_a_standard_library_dataclass_decorator(
    source_workspace: Path,
    source_context: ValidationContext,
    source: str,
) -> None:
    (source_workspace / "src" / "crm" / "values.py").write_text(
        source + "class Page:\n    number: int\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(index, "workspace", "src/crm/values.py", "Page")

    assert result.outcome == "valid"


@pytest.mark.parametrize(
    "source",
    [
        "from crm.helpers import dataclass\n@dataclass\n",
        "@dataclass\n",
        "from dataclasses import dataclass\n"
        "def dataclass(cls):\n    return object\n"
        "@dataclass\n",
        "from dataclasses import dataclass\n@dataclass\n@wrap\n",
        "if FLAG:\n    from dataclasses import dataclass\n@dataclass\n",
    ],
)
def test_resolver_keeps_other_class_decorators_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
    source: str,
) -> None:
    (source_workspace / "src" / "crm" / "values.py").write_text(
        source + "class Page:\n    number: int\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(index, "workspace", "src/crm/values.py", "Page")

    assert result.outcome == "inconclusive"


@pytest.mark.parametrize(
    "source",
    [
        "from django.db import transaction\n@transaction.atomic\n",
        "from django.db import transaction as tx\n@tx.atomic(using='default')\n",
        "from django.db.transaction import atomic\n@atomic\n",
    ],
)
def test_resolver_trusts_django_atomic_on_a_function(
    source_workspace: Path,
    source_context: ValidationContext,
    source: str,
) -> None:
    (source_workspace / "src" / "crm" / "writes.py").write_text(
        source + "def save(value: int) -> int:\n    return value\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(
        index,
        "workspace",
        "src/crm/writes.py",
        "save",
        expected_signature="def save(value: int) -> int:",
    )

    assert result.outcome == "valid"


@pytest.mark.parametrize(
    "source",
    [
        "@transaction.atomic\n",
        "from helpers import transaction\n@transaction.atomic\n",
        "from django.db import transaction\n@transaction.other\n",
    ],
)
def test_resolver_keeps_unproven_atomic_lookalikes_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
    source: str,
) -> None:
    (source_workspace / "src" / "crm" / "writes.py").write_text(
        source + "def save(value: int) -> int:\n    return value\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(index, "workspace", "src/crm/writes.py", "save")

    assert result.outcome == "inconclusive"


def test_resolver_keeps_a_class_decorated_with_atomic_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "writes.py").write_text(
        "from django.db import transaction\n"
        "@transaction.atomic\n"
        "class Save:\n    pass\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(index, "workspace", "src/crm/writes.py", "Save")

    assert result.outcome == "inconclusive"


def test_resolver_keeps_functions_decorated_as_dataclass_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "values.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "def build(value: int) -> int:\n    return value\n"
    )
    index = build_index(source_context)

    result = resolve_symbol(index, "workspace", "src/crm/values.py", "build")

    assert result.outcome == "inconclusive"


def test_resolver_keeps_wildcard_imports_uncertain_but_ignores_unrelated_imports(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "wildcard.py").write_text(
        "from .other import *\n"
    )
    (source_workspace / "src" / "crm" / "other.py").write_text("value = 1\n")
    (source_workspace / "src" / "crm" / "unrelated.py").write_text(
        "import missing_dependency\ndef proven() -> None:\n    pass\n"
    )
    index = build_index(source_context)

    wildcard = resolve_symbol(index, "workspace", "src/crm/wildcard.py", "anything")
    direct = resolve_symbol(index, "workspace", "src/crm/unrelated.py", "proven")

    assert wildcard.outcome == "inconclusive"
    assert direct.outcome == "valid"


def test_resolver_marks_competing_definitions_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "competing.py").write_text(
        "def target() -> None:\n    pass\ndef target() -> None:\n    pass\n"
    )

    result = resolve_symbol(
        build_index(source_context),
        "workspace",
        "src/crm/competing.py",
        "target",
    )

    assert result.outcome == "inconclusive"


def test_resolver_uses_explicit_stub_roots_without_runtime_probing(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    stubs = source_workspace.parent / "stubs"
    (stubs / "native").mkdir(parents=True)
    (stubs / "native" / "api.pyi").write_text(
        "def native_call(value: int) -> str: ...\n"
    )
    context = ValidationContext(
        workspace=source_workspace,
        roots=source_context.roots
        + (
            SourceRoot(
                root_id="native-stubs",
                path=stubs,
                kind="stub",
                suffixes=(".pyi",),
            ),
        ),
    )

    result = resolve_module_symbol(
        build_index(context),
        "native.api",
        "native_call",
        "def native_call(value: int) -> str:",
    )

    assert result.outcome == "valid"


def test_resolver_treats_unparsed_modules_as_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "broken.py").write_text("def broken(:\n")

    result = resolve_symbol(
        build_index(source_context),
        "workspace",
        "src/crm/broken.py",
        "broken",
    )

    assert result.outcome == "inconclusive"


def test_resolver_marks_ambiguous_module_providers_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "dependency"
    (dependency / "crm").mkdir(parents=True)
    (source_workspace / "src" / "crm" / "api.py").write_text("value = 1\n")
    (dependency / "crm" / "api.py").write_text("value = 2\n")
    dependency_root = SourceRoot(
        root_id="dependency",
        path=dependency,
        kind="dependency",
    )
    context = ValidationContext(
        workspace=source_workspace,
        roots=source_context.roots + (dependency_root,),
    )

    result = resolve_module_symbol(build_index(context), "crm.api", "value")

    assert result.outcome == "inconclusive"


def test_resolver_separates_planned_declarations_from_existing_symbols(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    packet: Packet = decode_packet(
        """{
            "schema_version": 0,
            "packet_id": "new-module",
            "task": "Create a module.",
            "readable_files": [],
            "file_changes": [
                {"path": "src/crm/new.py", "operation": "create"},
                {"path": "tests/test_new.py", "operation": "create"}
            ],
            "consumes": [],
            "produces": [{
                "path": "src/crm/new.py",
                "qualified_name": "new_value",
                "operation": "create",
                "kind": "function",
                "declaration": "def new_value() -> int:"
            }],
            "imports": [{
                "path": "tests/test_new.py",
                "module": "new",
                "name": "new_value",
                "alias": "new_value",
                "target": "planned"
            }, {
                "path": "tests/test_new.py",
                "module": "domain",
                "name": "Contact",
                "alias": "ExistingContact",
                "target": "existing"
            }],
            "tests": [{
                "path": "tests/test_new.py",
                "operation": "create",
                "content": ""
            }],
            "gates": [{
                "argv": ["pytest"],
                "cwd": ".",
                "before": {"exit_code": "nonzero", "reason": "fails"},
                "after": {"exit_code": 0, "reason": "passes"}
            }],
            "known_facts": [],
            "acceptance_criteria": ["Value exists."],
            "preserved_behavior": []
        }"""
    )
    (source_workspace / "tests").mkdir()
    (source_workspace / "root_src").mkdir()
    (source_workspace / "src" / "crm" / "domain.py").write_text(
        "class Contact:\n    pass\n"
    )
    context = ValidationContext(
        workspace=source_workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=source_workspace,
                kind="project",
                import_base="root_src",
            ),
            SourceRoot(
                root_id="crm-project",
                path=source_workspace / "src" / "crm",
                kind="project",
            ),
        ),
    )
    index = build_index(context)

    planned = resolve_planned(index, packet, "src/crm/new.py", "new_value")
    planned_import = resolve_import_reference(index, packet, packet.imports[0])
    existing_import = resolve_import_reference(index, packet, packet.imports[1])
    current = resolve_symbol(index, "workspace", "src/crm/new.py", "new_value")

    assert planned.outcome == "valid"
    assert planned_import.outcome == "valid"
    assert existing_import.outcome == "valid"
    assert planned.root_id == "crm-project"
    assert planned.module_name == "new"
    assert current.outcome == "inconclusive"
    assert not (source_workspace / "src" / "crm" / "new.py").exists()
