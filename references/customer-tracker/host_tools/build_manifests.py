import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "manifests" / "worker_files.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> None:
    from host_tools.leakage import (
        assert_no_protected_content,
        verify_protected_fingerprints,
    )

    verify_protected_fingerprints()
    tasks: dict[str, dict[str, dict[str, str]]] = {}
    for kind, task_ids in (
        ("examples", ("E1", "E2", "E3")),
        ("tasks", ("H1", "H2", "H3")),
    ):
        for task_id in task_ids:
            base = ROOT / kind / task_id
            files = [base / "task.md", base / "provenance.json"]
            snapshot = base / "start"
            files.extend(sorted(path for path in snapshot.rglob("*") if path.is_file()))
            if kind == "examples":
                completed = base / "complete"
                files.extend(
                    sorted(path for path in completed.rglob("*") if path.is_file())
                )
            assert_no_protected_content(files)
            entries = {}
            for path in sorted(set(files)):
                current = path
                while current != ROOT:
                    if current.is_symlink():
                        raise ValueError(f"Symlink in worker source path: {current}")
                    current = current.parent
                if (
                    path.is_symlink()
                    or "evaluation" in path.parts
                    or "__pycache__" in path.parts
                    or ".pytest_cache" in path.parts
                    or path.suffix == ".pyc"
                    or path.name == "db.sqlite3"
                ):
                    raise ValueError(f"Unsafe worker file: {path}")
                relative = path.relative_to(ROOT).as_posix()
                export_path = (
                    path.relative_to(snapshot).as_posix()
                    if kind == "tasks" and path.is_relative_to(snapshot)
                    else path.relative_to(base).as_posix()
                )
                entries[relative] = {"export_path": export_path, "sha256": sha256(path)}
            tasks[task_id] = entries
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"tasks": tasks}, indent=2) + "\n")


if __name__ == "__main__":
    if __package__ in {None, ""}:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    build()
