from pathlib import Path

from typed_packets.index import (
    DefinitionRecord,
    ModuleRecord,
    SourceRoot,
    SymbolIndex,
    ValidationContext,
    build_index,
)


def module_named(index: SymbolIndex, name: str) -> ModuleRecord:
    return next(module for module in index.modules if module.module_name == name)


def definition_named(module: ModuleRecord, name: str) -> DefinitionRecord:
    return next(
        definition
        for definition in module.definitions
        if definition.qualified_name == name
    )


def test_index_maps_modules_and_records_structural_signatures(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    source = source_workspace / "src" / "crm" / "domain.py"
    source.write_text(
        "def format_contact(name: str, *, terse: bool = False) -> str:\n"
        "    return name\n"
    )

    index = build_index(source_context)
    module = module_named(index, "crm.domain")
    definition = definition_named(module, "format_contact")

    assert module.root_id == "workspace"
    assert module.path == "src/crm/domain.py"
    assert definition.signature is not None
    assert definition.signature.is_async is False
    assert [parameter.name for parameter in definition.signature.parameters] == [
        "name",
        "terse",
    ]
    assert definition.signature.parameters[1].kind == "keyword_only"
    assert definition.signature.parameters[1].default is not None


def test_index_fingerprints_source_bytes_but_normalizes_signature_formatting(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    source = source_workspace / "src" / "crm" / "domain.py"
    source.write_text("def format_contact(name: str) -> str:\n    return name\n")
    first_index = build_index(source_context)
    first_signature = definition_named(
        module_named(first_index, "crm.domain"), "format_contact"
    ).signature
    source.write_text(
        "# formatting changed\ndef format_contact( name:str )->str:\n    return name\n"
    )

    second_index = build_index(source_context)
    second_signature = definition_named(
        module_named(second_index, "crm.domain"), "format_contact"
    ).signature

    assert first_index.fingerprint != second_index.fingerprint
    assert first_signature == second_signature


def test_index_records_class_methods_and_semantic_type_aliases(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    source = source_workspace / "src" / "crm" / "domain.py"
    source.write_text(
        "type ContactId = int\n"
        "class Contact:\n"
        "    async def label(self, prefix: str = '') -> str:\n"
        "        return prefix\n"
    )

    index = build_index(source_context)
    module = module_named(index, "crm.domain")
    alias = definition_named(module, "ContactId")
    method = definition_named(module, "Contact.label")

    assert alias.kind == "type_alias"
    assert method.kind == "async_function"
    assert method.signature is not None and method.signature.is_async


def test_index_does_not_execute_source_or_follow_directory_symlinks(
    source_workspace: Path,
    source_context: ValidationContext,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "imported"
    source = source_workspace / "src" / "crm" / "effects.py"
    source.write_text(f"open({str(sentinel)!r}, 'w').write('executed')\n")
    external = tmp_path / "external"
    external.mkdir()
    (external / "hidden.py").write_text("value = 1\n")
    (source_workspace / "src" / "linked").symlink_to(external, target_is_directory=True)

    index = build_index(source_context)

    assert not sentinel.exists()
    assert all(
        module.module_name is None or "linked" not in module.module_name
        for module in index.modules
    )


def test_index_rejects_symlinks_inside_import_base(
    source_workspace: Path,
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    (external / "src").mkdir(parents=True)
    (external / "src" / "outside.py").write_text("value = 1\n")
    (source_workspace / "linked").symlink_to(external, target_is_directory=True)
    context = ValidationContext(
        workspace=source_workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=source_workspace,
                kind="project",
                import_base="linked/src",
            ),
        ),
    )

    index = build_index(context)

    assert any(issue.code == "index.import_base_invalid" for issue in index.issues)
    assert not any(module.module_name == "outside" for module in index.modules)


def test_index_reports_parse_errors_as_inconclusive(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    (source_workspace / "src" / "crm" / "broken.py").write_text("def broken(:\n")

    index = build_index(source_context)

    assert any(
        issue.code == "index.parse_error" and issue.outcome == "inconclusive"
        for issue in index.issues
    )


def test_index_rejects_duplicate_root_ids_and_outside_project_roots(
    source_workspace: Path,
    source_context: ValidationContext,
    tmp_path: Path,
) -> None:
    duplicate = SourceRoot(
        root_id="workspace",
        path=source_workspace,
        kind="project",
        import_base="src",
    )
    outside = source_workspace.parent / "outside"
    outside.mkdir()
    external_project = SourceRoot(
        root_id="external-project",
        path=outside,
        kind="project",
    )

    index = build_index(
        ValidationContext(
            workspace=source_workspace,
            roots=source_context.roots + (duplicate, external_project),
        )
    )

    assert any(issue.code == "context.duplicate_root_id" for issue in index.issues)
    assert any(
        issue.code == "context.project_outside_workspace" for issue in index.issues
    )


def test_index_rejects_symlink_source_roots(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    linked_root = source_workspace / "linked-root"
    linked_root.symlink_to(source_workspace / "src", target_is_directory=True)
    context = ValidationContext(
        workspace=source_workspace,
        roots=source_context.roots
        + (
            SourceRoot(
                root_id="linked-project",
                path=linked_root,
                kind="project",
            ),
        ),
    )

    index = build_index(context)

    assert any(issue.code == "context.root_symlink" for issue in index.issues)
    assert "linked-project" not in {root.root_id for root in index.roots}


def test_index_fingerprint_includes_invalid_root_mappings(
    source_workspace: Path,
    tmp_path: Path,
) -> None:
    outside_one = tmp_path / "outside-one"
    outside_two = tmp_path / "outside-two"
    outside_one.mkdir()
    outside_two.mkdir()
    workspace_root = SourceRoot(
        root_id="workspace",
        path=source_workspace,
        kind="project",
        import_base="src",
    )

    first = build_index(
        ValidationContext(
            workspace=source_workspace,
            roots=(
                workspace_root,
                SourceRoot("invalid-project", outside_one, "project"),
            ),
        )
    )
    second = build_index(
        ValidationContext(
            workspace=source_workspace,
            roots=(
                workspace_root,
                SourceRoot("invalid-project", outside_two, "project"),
            ),
        )
    )

    assert first.context_fingerprint != second.context_fingerprint


def test_index_includes_only_explicitly_configured_stub_suffixes(
    source_workspace: Path,
    source_context: ValidationContext,
) -> None:
    stub = source_workspace.parent / "stubs"
    (stub / "crm").mkdir(parents=True)
    (stub / "crm" / "native.pyi").write_text(
        "def native_call(value: int) -> str: ...\n"
    )
    (source_workspace / "src" / "crm" / "ignored.py").write_text("value = 1\n")
    context = ValidationContext(
        workspace=source_workspace,
        roots=source_context.roots
        + (
            SourceRoot(
                root_id="native-stubs",
                path=stub,
                kind="stub",
                suffixes=(".pyi",),
            ),
        ),
    )

    index = build_index(context)

    assert {module.module_name for module in index.modules} == {
        "crm",
        "crm.ignored",
        "crm.native",
    }
