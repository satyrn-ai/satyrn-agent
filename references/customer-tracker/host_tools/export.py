import hashlib
import json
from pathlib import Path

from host_tools.leakage import (
    assert_no_protected_content,
    verify_protected_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "worker_files.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"..", "."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe manifest path: {value}")
    return path


def export(task_id: str, destination: Path) -> None:
    verify_protected_fingerprints()
    manifest = json.loads(MANIFEST.read_text())
    if task_id not in manifest["tasks"]:
        raise ValueError(f"Unknown task ID: {task_id}")
    if destination.exists():
        raise FileExistsError(destination)

    entries = manifest["tasks"][task_id]
    prepared: list[tuple[Path, Path, str]] = []
    expected: set[str] = set()
    for source_name, details in entries.items():
        source_relative = _safe_relative(source_name)
        output_relative = _safe_relative(details["export_path"])
        if (
            "evaluation" in source_relative.parts
            or source_relative.parts[0] == "host_tools"
        ):
            raise ValueError(f"Protected source in export manifest: {source_name}")
        source = ROOT / source_relative
        if any(
            part.is_symlink()
            for part in (source, *source.parents)
            if part != ROOT.parent
        ):
            raise ValueError(f"Symlink source: {source}")
        if not source.is_file() or _digest(source) != details["sha256"]:
            raise ValueError(f"Missing or changed source: {source_name}")
        target = destination / output_relative
        if output_relative.as_posix() in expected:
            raise ValueError(f"Duplicate export path: {output_relative}")
        prepared.append((source, target, details["sha256"]))
        expected.add(output_relative.as_posix())

    assert_no_protected_content([source for source, _, _ in prepared])
    destination.mkdir(parents=True)
    for source, target, expected_hash in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        if _digest(target) != expected_hash:
            raise ValueError(f"Copied hash mismatch: {target.relative_to(destination)}")

    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise ValueError(
            f"Export tree mismatch: extra={actual - expected}, missing={expected - actual}"
        )
