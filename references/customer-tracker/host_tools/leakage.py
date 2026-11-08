import ast
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "evaluation" / "protected_fingerprints.json"
TASK_IDS = ("H1", "H2", "H3")
PROTECTED_TESTS = {
    "H1": "test_search.py",
    "H2": "test_follow_ups.py",
    "H3": "test_archive.py",
}
FINGERPRINT_METHOD = (
    "SHA-256 of exact protected files and ast.dump() for top-level or nested "
    "function/class definitions after replacing the outer definition name; "
    "definitions already present in the frozen E3 baseline or that task's "
    "frozen start are explicitly shared."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in protected source tree: {path}")
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or path.suffix == ".pyc"
            or path.name == "db.sqlite3"
        ):
            continue
        files.append(path)
    return files


def _tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = _source_files(root)
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def _source_digest(path: Path) -> str:
    if path.is_dir():
        digest, _ = _tree_digest(path)
    elif path.is_file() and not path.is_symlink():
        digest = _sha256(path)
    else:
        raise ValueError(f"Missing protected source: {path}")
    return digest


def _policy_source_paths() -> list[Path]:
    paths = [Path("examples/E3/complete"), Path("app/tests")]
    for task_id in TASK_IDS:
        paths.extend(
            (
                Path("tasks") / task_id / "start",
                Path("evaluation") / task_id / "solution",
                Path("evaluation") / task_id / PROTECTED_TESTS[task_id],
            )
        )
    return paths


def _definition_fingerprints(root: Path) -> dict[str, dict[str, str]]:
    fingerprints: dict[str, dict[str, str]] = {}
    for path in sorted(root.rglob("*.py")):
        if path.is_symlink():
            raise ValueError(f"Symlink in protected source tree: {path}")
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(
                node,
                ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
            ):
                continue
            normalized = copy.deepcopy(node)
            normalized.name = "<definition>"
            fingerprint = hashlib.sha256(
                ast.dump(normalized, include_attributes=False).encode()
            ).hexdigest()
            fingerprints.setdefault(
                fingerprint,
                {
                    "path": path.relative_to(root).as_posix(),
                    "name": node.name,
                },
            )
    return fingerprints


def _protected_content() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    baseline = ROOT / "examples" / "E3" / "complete"
    baseline_file_hashes = {_sha256(path) for path in _source_files(baseline)}
    baseline_definitions = set(_definition_fingerprints(baseline / "app").keys())
    protected_files: list[dict[str, str]] = []
    protected_definitions: list[dict[str, str]] = []

    for task_id in TASK_IDS:
        start = ROOT / "tasks" / task_id / "start"
        solution = ROOT / "evaluation" / task_id / "solution"
        shared_file_hashes = baseline_file_hashes | {
            _sha256(path) for path in _source_files(start)
        }
        shared_definitions = baseline_definitions | set(
            _definition_fingerprints(start / "app").keys()
        )

        for path in _source_files(solution):
            fingerprint = _sha256(path)
            if fingerprint not in shared_file_hashes:
                protected_files.append(
                    {
                        "task_id": task_id,
                        "path": path.relative_to(solution).as_posix(),
                        "sha256": fingerprint,
                    }
                )

        for fingerprint, definition in _definition_fingerprints(
            solution / "app"
        ).items():
            if fingerprint not in shared_definitions:
                protected_definitions.append(
                    {
                        "task_id": task_id,
                        "path": definition["path"],
                        "name": definition["name"],
                        "sha256": fingerprint,
                    }
                )

    protected_files.sort(key=lambda item: (item["task_id"], item["path"]))
    protected_definitions.sort(
        key=lambda item: (item["task_id"], item["path"], item["name"])
    )
    return protected_files, protected_definitions


def build_fingerprint_policy() -> dict[str, object]:
    source_trees = {
        path.as_posix(): _source_digest(ROOT / path) for path in _policy_source_paths()
    }
    protected_files, protected_definitions = _protected_content()
    return {
        "fingerprint_method": FINGERPRINT_METHOD,
        "source_trees": source_trees,
        "protected_files": protected_files,
        "protected_definitions": protected_definitions,
    }


def verify_protected_fingerprints() -> None:
    try:
        expected = json.loads(POLICY.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Protected fingerprint policy is unavailable") from error
    actual = build_fingerprint_policy()
    if expected != actual:
        raise ValueError(
            "Protected fingerprint policy or its pinned source trees changed"
        )


def assert_no_protected_content(paths: list[Path]) -> None:
    policy = json.loads(POLICY.read_text())
    protected_file_hashes = {item["sha256"] for item in policy["protected_files"]}
    protected_definitions = {
        item["sha256"]: item for item in policy["protected_definitions"]
    }

    for path in paths:
        file_hash = _sha256(path)
        if file_hash in protected_file_hashes:
            raise ValueError(f"Protected solution content found in {path}")
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(
                node,
                ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
            ):
                continue
            normalized = copy.deepcopy(node)
            normalized.name = "<definition>"
            fingerprint = hashlib.sha256(
                ast.dump(normalized, include_attributes=False).encode()
            ).hexdigest()
            if match := protected_definitions.get(fingerprint):
                task_id = match["task_id"]
                name = match["name"]
                raise ValueError(
                    f"Protected solution content from {task_id} ({name}) "
                    f"found in {path}"
                )
