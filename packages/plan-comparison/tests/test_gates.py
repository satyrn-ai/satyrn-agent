import os
import sys
import textwrap
import time
from pathlib import Path

import pytest
from typed_packets.contract import Gate, GateExpectation

from plan_comparison.contracts import RedCheck
from plan_comparison.gates import GatePolicy, run_gate


def _policy(*, timeout: float = 2.0, output_limit: int = 1024) -> GatePolicy:
    return GatePolicy(
        allowed_commands=(sys.executable,),
        environment=(
            ("PATH", os.environ.get("PATH", "")),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        timeout_seconds=timeout,
        output_limit_bytes=output_limit,
        termination_grace_seconds=0.1,
    )


def _gate(*arguments: str, cwd: str = ".") -> Gate:
    return Gate(
        argv=(sys.executable, *arguments),
        cwd=cwd,
        before=GateExpectation(exit_code="nonzero", reason="Expected red failure."),
        after=GateExpectation(exit_code=0, reason="Expected green pass."),
    )


def _red_check() -> RedCheck:
    return RedCheck(
        path="tests/test_operations.py",
        test_node="test_invalid_input_fails",
        expected_exception="NotImplementedError",
        marker="test_invalid_input_fails",
    )


def test_gate_runs_allowlisted_argument_array_in_workspace(tmp_path: Path) -> None:
    gate = _gate("-c", "print('visible output')")

    result = run_gate(tmp_path, "smoke", gate, gate.after, _policy())

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.output_excerpt == "visible output\n"


def test_gate_rejects_non_allowlisted_command(tmp_path: Path) -> None:
    gate = Gate(
        argv=("/usr/bin/true",),
        cwd=".",
        before=GateExpectation(exit_code="nonzero", reason="red"),
        after=GateExpectation(exit_code=0, reason="green"),
    )

    result = run_gate(tmp_path, "blocked", gate, gate.after, _policy())

    assert result.status == "error"
    assert "not allowlisted" in result.output_excerpt


def test_gate_rejects_symlinked_working_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    gate = _gate("-c", "pass", cwd="linked")

    result = run_gate(workspace, "unsafe-cwd", gate, gate.after, _policy())

    assert result.status == "error"
    assert "symlinks" in result.output_excerpt


def test_gate_bounds_captured_output(tmp_path: Path) -> None:
    gate = _gate("-c", "print('x' * 10000)")

    result = run_gate(
        tmp_path,
        "large-output",
        gate,
        gate.after,
        _policy(output_limit=64),
    )

    assert result.status == "passed"
    assert result.output_truncated
    assert len(result.output_excerpt.encode()) == 64


def test_gate_timeout_kills_the_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "late-child-output.txt"
    script = (
        "import time; time.sleep(0.5); "
        f"open({str(marker)!r}, 'w', encoding='utf-8').write('survived')"
    )
    gate = _gate("-c", script)

    result = run_gate(
        tmp_path,
        "timeout",
        gate,
        gate.before,
        _policy(timeout=0.25),
    )
    time.sleep(0.6)

    assert result.status in ("timed_out", "error")
    assert result.timed_out
    assert not marker.exists()


def test_red_evidence_requires_the_named_test_and_expected_exception(
    tmp_path: Path,
) -> None:
    output = textwrap.dedent(
        """
        __________________ test_invalid_input_fails __________________
        E   NotImplementedError: unfinished callable
        FAILED tests/test_operations.py::test_invalid_input_fails - NotImplementedError
        """
    )
    script = f"import sys; print({output!r}); sys.exit(1)"
    gate = _gate("-c", script)

    result = run_gate(
        tmp_path,
        "expected-red",
        gate,
        gate.before,
        _policy(),
        (_red_check(),),
    )

    assert result.status == "passed"
    assert len(result.verified_red_evidence) == 1


@pytest.mark.parametrize(
    "output",
    [
        (
            "ERROR collecting tests/test_operations.py\n"
            "E NotImplementedError: import failed\n"
        ),
        "________ test_invalid_input_fails ________\nE TypeError: wrong failure\n",
        "________ test_other_case ________\nE NotImplementedError: unrelated failure\n",
    ],
)
def test_wrong_or_collection_failures_do_not_satisfy_red_check(
    tmp_path: Path, output: str
) -> None:
    gate = _gate("-c", f"import sys; print({output!r}); sys.exit(1)")

    result = run_gate(
        tmp_path,
        "wrong-red",
        gate,
        gate.before,
        _policy(),
        (_red_check(),),
    )

    assert result.status == "failed"
    assert result.verified_red_evidence == ()


def test_truncated_output_cannot_prove_red_evidence(tmp_path: Path) -> None:
    output = (
        "________ test_invalid_input_fails ________\n"
        "E   NotImplementedError: expected\n" + "x" * 1000
    )
    gate = _gate("-c", f"import sys; print({output!r}); sys.exit(1)")

    result = run_gate(
        tmp_path,
        "truncated-red",
        gate,
        gate.before,
        _policy(output_limit=64),
        (_red_check(),),
    )

    assert result.output_truncated
    assert result.status == "failed"
    assert result.verified_red_evidence == ()
