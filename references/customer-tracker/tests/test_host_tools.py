import hashlib
import json
import shutil
import subprocess

import pytest

from host_tools import build_manifests as build_manifests_module
from host_tools import export as export_module
from host_tools import leakage as leakage_module
from host_tools.grade import grade
from host_tools.style import diagnose


@pytest.mark.parametrize("task_id", ["E1", "E2", "E3", "H1", "H2", "H3"])
def test_export_creates_manifest_exact_workspace(task_id: str, tmp_path) -> None:
    destination = tmp_path / task_id
    export_module.export(task_id, destination)
    manifest = json.loads(export_module.MANIFEST.read_text())
    expected = {
        details["export_path"]: details["sha256"]
        for details in manifest["tasks"][task_id].values()
    }
    actual = {
        path.relative_to(destination).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in destination.rglob("*")
        if path.is_file()
    }

    assert actual == expected
    assert not any("evaluation" in path for path in actual)
    if task_id.startswith("H"):
        assert not any(
            path.endswith(("test_search.py", "test_follow_ups.py", "test_archive.py"))
            for path in actual
        )
        assert (destination / "app" / "manage.py").is_file()
    else:
        assert (destination / "complete" / "app" / "manage.py").is_file()


def test_export_rejects_existing_destination(tmp_path) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        export_module.export("E1", destination)


def test_export_rejects_traversal_in_manifest(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"tasks": {"H1": {"../secret": {"export_path": "safe", "sha256": "0"}}}}
        )
    )
    monkeypatch.setattr(export_module, "MANIFEST", manifest_path)

    with pytest.raises(ValueError, match="Unsafe manifest path"):
        export_module.export("H1", tmp_path / "workspace")


def test_export_rejects_symlink_source(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("protected")
    (source_root / "linked.txt").symlink_to(outside)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "tasks": {
                    "H1": {
                        "linked.txt": {
                            "export_path": "linked.txt",
                            "sha256": hashlib.sha256(b"protected").hexdigest(),
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setattr(export_module, "ROOT", source_root)
    monkeypatch.setattr(export_module, "MANIFEST", manifest_path)

    with pytest.raises(ValueError, match="Symlink source"):
        export_module.export("H1", tmp_path / "workspace")


def test_export_rejects_protected_solution_code_under_a_new_name(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    protected_source = (
        export_module.ROOT
        / "evaluation"
        / "H2"
        / "solution"
        / "app"
        / "crm"
        / "operations.py"
    )
    copied_source = source_root / "renamed_solution.py"
    copied_source.write_text(
        protected_source.read_text().replace(
            "def schedule_follow_up(", "def copied_schedule_follow_up("
        )
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "tasks": {
                    "H3": {
                        "renamed_solution.py": {
                            "export_path": "app/crm/renamed_solution.py",
                            "sha256": hashlib.sha256(
                                copied_source.read_bytes()
                            ).hexdigest(),
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setattr(export_module, "ROOT", source_root)
    monkeypatch.setattr(export_module, "MANIFEST", manifest_path)

    with pytest.raises(ValueError, match="Protected solution content"):
        export_module.export("H3", tmp_path / "workspace")


def test_manifest_rebuild_rejects_protected_code_added_to_heldout_start(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = export_module.ROOT
    policy_path = leakage_module.POLICY
    policy = json.loads(policy_path.read_text())
    isolated_root = tmp_path / "customer-tracker"
    for relative_path in policy["source_trees"]:
        source = source_root / relative_path
        destination = isolated_root / relative_path
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    destination_policy = isolated_root / "evaluation" / "protected_fingerprints.json"
    destination_policy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(policy_path, destination_policy)
    leaked_code = (
        source_root / "evaluation" / "H2" / "solution" / "app" / "crm" / "operations.py"
    )
    leak_target = isolated_root / "tasks" / "H3" / "start" / "app" / "crm" / "leaked.py"
    shutil.copy2(leaked_code, leak_target)
    monkeypatch.setattr(leakage_module, "ROOT", isolated_root)
    monkeypatch.setattr(leakage_module, "POLICY", destination_policy)
    monkeypatch.setattr(build_manifests_module, "ROOT", isolated_root)
    monkeypatch.setattr(
        build_manifests_module,
        "OUTPUT",
        isolated_root / "manifests" / "worker_files.json",
    )

    with pytest.raises(ValueError, match="pinned source trees changed"):
        build_manifests_module.build()


def test_manifest_task_ids_are_disjoint_and_complete() -> None:
    manifest = json.loads(export_module.MANIFEST.read_text())
    task_ids = set(manifest["tasks"])

    assert task_ids == {"E1", "E2", "E3", "H1", "H2", "H3"}
    assert not ({"E1", "E2", "E3"} & {"H1", "H2", "H3"})


@pytest.mark.parametrize("task_id", ["E1", "E2", "E3"])
def test_completed_example_snapshot_passes_in_subprocess(
    task_id: str, tmp_path
) -> None:
    source = export_module.ROOT / "examples" / task_id / "complete"
    workspace = tmp_path / task_id
    shutil.copytree(source, workspace)
    command = [
        "uv",
        "run",
        "--locked",
        "--project",
        str(export_module.ROOT),
        "pytest",
        "-c",
        str(workspace / "pytest.ini"),
        str(workspace / "app" / "tests"),
        "-q",
    ]
    result = subprocess.run(
        command,
        cwd=export_module.ROOT.parent.parent,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("task_id", "expected_failure"),
    [
        ("H1", "test_search_matches_case_insensitive_substrings_in_any_customer_field"),
        ("H2", "test_follow_up_status_handles_time_boundaries"),
        ("H3", "test_archive_is_idempotent_and_preserves_customer_and_history"),
    ],
)
def test_heldout_start_fails_its_intended_protected_behavior(
    task_id: str,
    expected_failure: str,
    tmp_path,
) -> None:
    workspace = tmp_path / task_id
    export_module.export(task_id, workspace)

    result = grade(task_id, workspace)

    assert result.returncode != 0
    assert expected_failure in result.stdout


def test_h3_start_contains_no_h2_workflow_implementation() -> None:
    h3_start = export_module.ROOT / "tasks" / "H3" / "start"
    forbidden = ("schedule_follow_up", "complete_follow_up", "follow_up_status")

    for path in h3_start.rglob("*.py"):
        contents = path.read_text()
        assert not any(name in contents for name in forbidden), path


def test_style_diagnostics_accept_good_fixture() -> None:
    workspace = export_module.ROOT / "evaluation" / "checker_fixtures" / "good"

    assert diagnose(workspace) == []


def test_style_diagnostics_flag_aliased_bad_fixture() -> None:
    workspace = export_module.ROOT / "evaluation" / "checker_fixtures" / "bad"

    findings = diagnose(workspace)

    assert {finding.rule for finding in findings} == {
        "DOMAIN_DJANGO_IMPORT",
        "CLASS_BASED_VIEW",
    }


def test_style_diagnostics_report_dynamic_route_as_inconclusive() -> None:
    workspace = export_module.ROOT / "evaluation" / "checker_fixtures" / "inconclusive"

    findings = diagnose(workspace)

    assert [finding.rule for finding in findings] == ["ROUTE_INCONCLUSIVE"]


def test_style_diagnostics_resolve_imported_as_view_assignment(tmp_path) -> None:
    crm = tmp_path / "app" / "crm"
    crm.mkdir(parents=True)
    (crm / "views.py").write_text(
        "from django.views.generic import ListView as CustomerListView\n\n"
        "customer_list = CustomerListView.as_view()\n"
    )
    (crm / "urls.py").write_text(
        "from django.urls import path as route\n"
        "from crm.views import customer_list as list_customers\n\n"
        'urlpatterns = [route("", list_customers)]\n'
    )

    findings = diagnose(tmp_path)

    assert [finding.rule for finding in findings] == ["CLASS_BASED_VIEW"]
    assert findings[0].path == "app/crm/views.py"


def test_style_diagnostics_report_cyclic_view_alias_as_inconclusive(tmp_path) -> None:
    crm = tmp_path / "app" / "crm"
    crm.mkdir(parents=True)
    (crm / "views.py").write_text("customer_list = other\nother = customer_list\n")
    (crm / "urls.py").write_text(
        "from django.urls import path\n"
        "from .views import customer_list\n\n"
        'urlpatterns = [path("", customer_list)]\n'
    )

    findings = diagnose(tmp_path)

    assert [finding.rule for finding in findings] == ["ROUTE_INCONCLUSIVE"]


@pytest.mark.parametrize("task_id", ["H1", "H2", "H3"])
def test_grade_runs_protected_tests_against_trusted_solution(
    task_id: str,
    tmp_path,
) -> None:
    workspace = tmp_path / task_id
    export_module.export(task_id, workspace)
    solution = export_module.ROOT / "evaluation" / task_id / "solution" / "app"
    shutil.copytree(solution, workspace / "app", dirs_exist_ok=True)

    result = grade(task_id, workspace)

    assert result.returncode == 0, result.stdout + result.stderr


def test_grade_uses_host_tests_not_worker_collection_settings(tmp_path) -> None:
    workspace = tmp_path / "H1"
    export_module.export("H1", workspace)
    solution = export_module.ROOT / "evaluation" / "H1" / "solution" / "app"
    shutil.copytree(solution, workspace / "app", dirs_exist_ok=True)
    shutil.rmtree(workspace / "app" / "tests")
    (workspace / "pytest.ini").write_text("[pytest]\naddopts = --collect-only\n")
    worker_tests = workspace / "app" / "tests"
    worker_tests.mkdir()
    (worker_tests / "conftest.py").write_text(
        "raise RuntimeError('worker-owned conftest was loaded')\n"
    )

    result = grade("H1", workspace)

    assert result.returncode == 0, result.stdout + result.stderr


def test_grade_runs_trusted_baseline_regressions_outside_worker_tree(
    tmp_path,
) -> None:
    workspace = tmp_path / "H1"
    export_module.export("H1", workspace)
    solution = export_module.ROOT / "evaluation" / "H1" / "solution" / "app"
    shutil.copytree(solution, workspace / "app", dirs_exist_ok=True)
    shutil.rmtree(workspace / "app" / "tests")
    operations = workspace / "app" / "crm" / "operations.py"
    operations.write_text(operations.read_text().replace('"email", "phone"', '"email"'))

    result = grade("H1", workspace)

    assert result.returncode != 0
    assert "test_update_contact_preserves_customer_fields" in result.stdout
