import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from plan_comparison.contracts import AttemptRecord, CapabilityCheckRecord, PairResult
from plan_comparison.reports import ExperimentReport

type RecordKind = Literal["attempt", "capability", "pair", "report"]
type RunRecord = AttemptRecord | CapabilityCheckRecord | PairResult | ExperimentReport

_RECORD_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


class RecordStoreError(RuntimeError):
    pass


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write_attempt(self, attempt: AttemptRecord) -> str:
        return self._write("attempt", attempt.attempt_id, attempt)

    def write_pair(self, pair: PairResult) -> str:
        return self._write("pair", pair.pair_id, pair)

    def write_capability(self, record: CapabilityCheckRecord) -> str:
        return self._write("capability", record.capability_id, record)

    def write_report(self, report_id: str, report: ExperimentReport) -> str:
        return self._write("report", report_id, report)

    def _write(self, kind: RecordKind, record_id: str, record: RunRecord) -> str:
        if _RECORD_ID.fullmatch(record_id) is None:
            raise RecordStoreError("Record ID must be a filesystem-safe token.")
        self._prepare_root()
        path = self.root / f"{kind}-{record_id}.json"
        document = json.dumps(
            {
                "record_version": 0,
                "record_kind": kind,
                "record": asdict(record),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(document)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as error:
            raise RecordStoreError(f"Record already exists: {path.name}") from error
        except OSError as error:
            raise RecordStoreError(
                f"Could not persist {kind} record: {error}"
            ) from error
        return path.as_posix()

    def _prepare_root(self) -> None:
        absolute = self.root.absolute()
        for component in (absolute, *absolute.parents):
            if component.is_symlink():
                raise RecordStoreError(
                    f"Record store path cannot contain symlinks: {component}"
                )
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RecordStoreError(f"Could not create record store: {error}") from error
        if not self.root.is_dir():
            raise RecordStoreError("Record store root is not a directory.")
