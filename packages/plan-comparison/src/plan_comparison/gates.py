import os
import re
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Literal

from typed_packets.contract import Gate, GateExpectation

from plan_comparison.contracts import GateResult, RedCheck

type ExpectedExitCode = int | Literal["nonzero"]


class GateCleanupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GatePolicy:
    allowed_commands: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    timeout_seconds: float
    output_limit_bytes: int
    termination_grace_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.allowed_commands or any(not item for item in self.allowed_commands):
            raise ValueError("Gate policy requires nonempty allowlisted commands.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.termination_grace_seconds, bool)
            or not isinstance(self.termination_grace_seconds, (int, float))
            or not isfinite(self.timeout_seconds)
            or not isfinite(self.termination_grace_seconds)
            or self.timeout_seconds <= 0
            or self.termination_grace_seconds < 0
        ):
            raise ValueError("Gate time limits must be positive.")
        if (
            not isinstance(self.output_limit_bytes, int)
            or isinstance(self.output_limit_bytes, bool)
            or self.output_limit_bytes < 1
        ):
            raise ValueError("Gate output limit must be positive.")
        names = [name for name, _ in self.environment]
        if len(set(names)) != len(names) or any(not name for name in names):
            raise ValueError("Gate environment names must be nonempty and unique.")
        if any(
            not isinstance(name, str)
            or not isinstance(value, str)
            or "\x00" in name
            or "\x00" in value
            for name, value in self.environment
        ):
            raise ValueError(
                "Gate environment names and values must be NUL-free strings."
            )


def _failure(
    gate_id: str,
    status: Literal["error", "timed_out"],
    message: str,
    duration: float,
    *,
    timed_out: bool = False,
) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        status=status,
        exit_code=None,
        timed_out=timed_out,
        duration_seconds=duration,
        output_excerpt=message,
        output_truncated=False,
        verified_red_evidence=(),
    )


def _cwd(workspace: Path, relative: str) -> Path:
    if workspace.is_symlink():
        raise ValueError("Gate workspace root cannot be a symlink.")
    pure = PurePosixPath(relative)
    if relative != "." and (
        pure.is_absolute()
        or "\\" in relative
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ValueError("Gate cwd must be a canonical workspace-relative directory.")
    target = workspace if relative == "." else workspace.joinpath(*pure.parts)
    current = workspace
    if relative != ".":
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Gate cwd cannot contain symlinks.")
    try:
        target.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError("Gate cwd must exist inside the workspace.") from error
    if not target.is_dir():
        raise ValueError("Gate cwd must be a directory.")
    return target


def _append_bounded(output: bytearray, chunk: bytes, limit: int) -> bool:
    available = limit - len(output)
    if available > 0:
        output.extend(chunk[:available])
    return len(chunk) > available


def _terminate_process_group(
    process: subprocess.Popen[bytes], grace_seconds: float
) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return
    except PermissionError as error:
        _terminate_direct_process(process, grace_seconds)
        raise GateCleanupError(
            "Process-group termination is not permitted; gate cleanup is unverified."
        ) from error
    deadline = time.monotonic() + grace_seconds
    while True:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        except PermissionError as error:
            _terminate_direct_process(process, grace_seconds)
            raise GateCleanupError(
                "Process-group state cannot be verified; gate cleanup is unverified."
            ) from error
        if time.monotonic() >= deadline:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                _terminate_direct_process(process, grace_seconds)
                raise GateCleanupError(
                    "Process-group kill is not permitted; gate cleanup is unverified."
                ) from error
            break
        time.sleep(min(0.01, deadline - time.monotonic()))
    process.wait()


def _terminate_direct_process(
    process: subprocess.Popen[bytes], grace_seconds: float
) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _read_after_termination(
    process: subprocess.Popen[bytes], output: bytearray, limit: int
) -> bool:
    if process.stdout is None:
        return False
    truncated = False
    while True:
        try:
            chunk = os.read(process.stdout.fileno(), 65536)
        except BlockingIOError:
            break
        if not chunk:
            break
        truncated = _append_bounded(output, chunk, limit) or truncated
    return truncated


def _expected_exit(actual: int, expected: ExpectedExitCode) -> bool:
    return actual != 0 if expected == "nonzero" else actual == expected


def run_gate(
    workspace: Path,
    gate_id: str,
    gate: Gate,
    expectation: GateExpectation,
    policy: GatePolicy,
    red_checks: tuple[RedCheck, ...] = (),
) -> GateResult:
    started = time.monotonic()
    if not gate.argv:
        return _failure(gate_id, "error", "Gate command has no arguments.", 0.0)
    if gate.argv[0] not in policy.allowed_commands:
        return _failure(
            gate_id,
            "error",
            f"Command is not allowlisted: {gate.argv[0]}",
            0.0,
        )
    try:
        working_directory = _cwd(workspace, gate.cwd)
    except ValueError as error:
        return _failure(gate_id, "error", str(error), time.monotonic() - started)

    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    output = bytearray()
    truncated = False
    timed_out = False
    try:
        process = subprocess.Popen(
            gate.argv,
            cwd=working_directory,
            env=dict(policy.environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        stdout = process.stdout
        if stdout is None:
            raise OSError("Gate output pipe was not created.")
        os.set_blocking(stdout.fileno(), False)
        selector.register(stdout, selectors.EVENT_READ)
        deadline = started + policy.timeout_seconds
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    _terminate_process_group(process, policy.termination_grace_seconds)
                except GateCleanupError as error:
                    return _failure(
                        gate_id,
                        "error",
                        str(error),
                        time.monotonic() - started,
                        timed_out=True,
                    )
                truncated = (
                    _read_after_termination(process, output, policy.output_limit_bytes)
                    or truncated
                )
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                try:
                    chunk = os.read(stdout.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                truncated = (
                    _append_bounded(output, chunk, policy.output_limit_bytes)
                    or truncated
                )
        exit_code = process.wait()
    except (OSError, ValueError) as error:
        cleanup_message = ""
        if process is not None:
            try:
                _terminate_process_group(process, policy.termination_grace_seconds)
            except GateCleanupError as cleanup_error:
                cleanup_message = f"; {cleanup_error}"
        return _failure(
            gate_id,
            "error",
            f"Gate could not be completed: {error}{cleanup_message}",
            time.monotonic() - started,
        )
    except BaseException:
        if process is not None:
            try:
                _terminate_process_group(process, policy.termination_grace_seconds)
            except GateCleanupError:
                _terminate_direct_process(process, policy.termination_grace_seconds)
        raise
    finally:
        selector.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()

    duration = time.monotonic() - started
    if timed_out:
        result = GateResult(
            gate_id=gate_id,
            status="timed_out",
            exit_code=exit_code,
            timed_out=True,
            duration_seconds=duration,
            output_excerpt=output.decode("utf-8", errors="replace"),
            output_truncated=truncated,
            verified_red_evidence=(),
        )
    else:
        expected = expectation.exit_code
        exit_matches = _expected_exit(exit_code, expected)
        result = GateResult(
            gate_id=gate_id,
            status="passed" if exit_matches else "failed",
            exit_code=exit_code,
            timed_out=False,
            duration_seconds=duration,
            output_excerpt=output.decode("utf-8", errors="replace"),
            output_truncated=truncated,
            verified_red_evidence=(),
        )
    if red_checks:
        evidence = verify_red_evidence(result, red_checks, gate.cwd)
        if len(evidence) != len(red_checks):
            return replace(result, status="failed", verified_red_evidence=evidence)
        return replace(result, verified_red_evidence=evidence)
    return result


def verify_red_evidence(
    result: GateResult,
    checks: tuple[RedCheck, ...],
    cwd: str = ".",
) -> tuple[str, ...]:
    if (
        result.status != "passed"
        or result.exit_code in (None, 0)
        or result.timed_out
        or result.output_truncated
    ):
        return ()
    headings = list(
        re.finditer(r"(?m)^_{3,}\s*(?P<name>.*?)\s*_{3,}\s*$", result.output_excerpt)
    )
    summaries = list(
        re.finditer(
            r"(?m)^FAILED\s+(?P<node>\S+)",
            result.output_excerpt,
        )
    )
    evidence: list[str] = []
    for check in checks:
        test_name = check.test_node.rsplit(".", maxsplit=1)[-1]
        candidate_paths = _red_check_paths(check.path, cwd)
        matching_summaries = [
            summary
            for summary in summaries
            if _summary_matches(summary.group("node"), candidate_paths, test_name)
        ]
        matching_headings = [
            (index, heading)
            for index, heading in enumerate(headings)
            if test_name in heading.group("name")
        ]
        if len(matching_summaries) != 1 or len(matching_headings) != 1:
            continue
        for index, heading in matching_headings:
            end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(result.output_excerpt)
            )
            section = result.output_excerpt[heading.start() : end]
            if check.marker not in section:
                continue
            exception = re.search(
                rf"(?m)^\s*E\s+{re.escape(check.expected_exception)}(?::|\s*$)",
                section,
            )
            if exception is not None:
                evidence.append(
                    f"{check.path}::{check.test_node}:{check.expected_exception}:{check.marker}"
                )
                break
    return tuple(evidence)


def _red_check_paths(path: str, cwd: str) -> tuple[str, ...]:
    candidates = {path}
    if cwd != ".":
        try:
            candidates.add(
                PurePosixPath(path).relative_to(PurePosixPath(cwd)).as_posix()
            )
        except ValueError:
            pass
    return tuple(sorted(candidates))


def _summary_matches(
    node_id: str,
    candidate_paths: tuple[str, ...],
    test_name: str,
) -> bool:
    path, separator, reported_test = node_id.partition("::")
    if not separator:
        return False
    reported_test = reported_test.split("[", maxsplit=1)[0]
    if reported_test != test_name:
        return False
    parts = PurePosixPath(path).parts
    return any(
        parts[-len(PurePosixPath(candidate).parts) :] == PurePosixPath(candidate).parts
        for candidate in candidate_paths
    )
