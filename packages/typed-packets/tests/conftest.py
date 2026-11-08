from pathlib import Path

import pytest

from typed_packets.index import SourceRoot, ValidationContext


@pytest.fixture
def source_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src" / "crm").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def source_context(source_workspace: Path) -> ValidationContext:
    return ValidationContext(
        workspace=source_workspace,
        roots=(
            SourceRoot(
                root_id="workspace",
                path=source_workspace,
                kind="project",
                import_base="src",
            ),
        ),
    )
