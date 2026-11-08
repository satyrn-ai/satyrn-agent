import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> tuple[str, int]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        if (
            path.is_symlink()
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            raise ValueError(f"Generated or symlinked file in frozen tree: {path}")
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def refresh() -> None:
    e3_hash, e3_count = tree_digest(ROOT / "examples" / "E3" / "complete")
    for task_id in ("E1", "E2", "E3"):
        base = ROOT / "examples" / task_id
        provenance_path = base / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["task_file_sha256"] = sha256(base / "task.md")
        for snapshot_name in ("start", "complete"):
            snapshot_hash, count = tree_digest(base / snapshot_name)
            provenance["snapshots"][snapshot_name] = {
                "sha256": snapshot_hash,
                "file_count": count,
            }
        provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")

    for task_id in ("H1", "H2", "H3"):
        base = ROOT / "tasks" / task_id
        provenance_path = base / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        start_hash, start_count = tree_digest(base / "start")
        provenance["task_file_sha256"] = sha256(base / "task.md")
        provenance["baseline"]["sha256"] = e3_hash
        provenance["baseline"]["file_count"] = e3_count
        provenance["start"] = {"sha256": start_hash, "file_count": start_count}
        provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")

        evaluation = ROOT / "evaluation" / task_id
        evaluation_provenance_path = evaluation / "provenance.json"
        evaluation_provenance = json.loads(evaluation_provenance_path.read_text())
        solution_hash, solution_count = tree_digest(evaluation / "solution")
        test_name = {
            "H1": "test_search.py",
            "H2": "test_follow_ups.py",
            "H3": "test_archive.py",
        }[task_id]
        evaluation_provenance["protected_solution"] = {
            "path": "solution",
            "sha256": solution_hash,
            "file_count": solution_count,
        }
        evaluation_provenance["protected_tests"]["sha256"] = sha256(
            evaluation / test_name
        )
        evaluation_provenance_path.write_text(
            json.dumps(evaluation_provenance, indent=2) + "\n"
        )


if __name__ == "__main__":
    refresh()
