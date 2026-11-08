import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from host_tools.leakage import verify_protected_fingerprints

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_TESTS = {
    "H1": "test_search.py",
    "H2": "test_follow_ups.py",
    "H3": "test_archive.py",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def grade(task_id: str, workspace: Path) -> subprocess.CompletedProcess[str]:
    if task_id not in PROTECTED_TESTS:
        raise ValueError(f"No protected test package for {task_id}")
    verify_protected_fingerprints()
    evaluation = ROOT / "evaluation" / task_id
    test_file = evaluation / PROTECTED_TESTS[task_id]
    before = _digest(test_file)
    provenance = json.loads((evaluation / "provenance.json").read_text())
    expected = provenance["protected_tests"]["sha256"]
    if before != expected:
        raise ValueError("Protected test hash changed before grading")
    solution = evaluation / "solution"
    solution_before = _tree_digest(solution)
    expected_solution = provenance["protected_solution"]
    if solution_before != (
        expected_solution["sha256"],
        expected_solution["file_count"],
    ):
        raise ValueError("Protected solution hash changed before grading")
    baseline_tests = sorted((ROOT / "app" / "tests").glob("test_*.py"))
    baseline_before = {path: _digest(path) for path in baseline_tests}

    with tempfile.TemporaryDirectory(prefix=f"grade-{task_id}-") as temporary:
        temporary_root = Path(temporary)
        trial = temporary_root / "workspace"
        shutil.copytree(workspace, trial, symlinks=False)
        host_tests = temporary_root / "host-tests"
        host_tests.mkdir()
        for baseline_test in baseline_tests:
            shutil.copy2(baseline_test, host_tests / baseline_test.name)
        test_target = host_tests / "test_protected_task.py"
        test_target.write_bytes(test_file.read_bytes())
        config = temporary_root / "pytest.ini"
        config.write_text(
            "[pytest]\n"
            "DJANGO_SETTINGS_MODULE = config.settings\n"
            f"pythonpath = {trial / 'app'}\n"
        )
        command = [
            "uv",
            "run",
            "--locked",
            "--project",
            str(ROOT),
            "pytest",
            "-c",
            str(config),
            "--confcutdir",
            str(host_tests),
            "-p",
            "pytest_django.plugin",
            str(host_tests),
            "-q",
        ]
        environment = os.environ.copy()
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        result = subprocess.run(
            command,
            cwd=ROOT.parent.parent,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    if _digest(test_file) != before:
        raise RuntimeError("Protected test changed during grading")
    if _tree_digest(solution) != solution_before:
        raise RuntimeError("Protected solution changed during grading")
    if any(_digest(path) != digest for path, digest in baseline_before.items()):
        raise RuntimeError("Trusted baseline test changed during grading")
    return result
