from pathlib import Path

from plan_comparison.contracts import (
    ArmResult,
    AttemptRecord,
    AttemptTiming,
    BoundaryEvidence,
    BudgetSnapshot,
    DecisionRule,
    GateResult,
    HostGrade,
    PairResult,
)
from plan_comparison.records import RunStore
from plan_comparison.reports import StyleEvidence, build_report


def _attempt(
    attempt_id: str,
    arm: str,
    attempt_number: int,
    status: str,
    *,
    tokens: int,
    elapsed: float,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=attempt_id,
        task_id="H1",
        arm=arm,
        packet_id="search",
        attempt_number=attempt_number,
        status=status,
        started_at=f"2026-11-08T10:00:0{attempt_number}+00:00",
        completed_at=f"2026-11-08T10:00:1{attempt_number}+00:00",
        input_sha256="a" * 64,
        code_delta_sha256="b" * 64,
        gates=(
            GateResult(
                gate_id="visible-tests",
                status="failed" if status == "failed" else "passed",
                exit_code=1 if status == "failed" else 0,
                timed_out=False,
                duration_seconds=0.25,
                output_excerpt="visible failure",
                output_truncated=False,
                verified_red_evidence=(),
            ),
        ),
        budget=BudgetSnapshot(
            elapsed_seconds=elapsed,
            tokens=tokens,
            model_calls=attempt_number,
        ),
        boundary_evidence=BoundaryEvidence(
            model_id="scripted",
            model_revision="revision",
            runtime_revision="runtime",
            tokenizer_revision="tokenizer",
            checkpoint_key=f"checkpoint-{attempt_number}",
            token_count=12,
            rng_state_sha256="c" * 64,
            host_history_sha256="d" * 64,
            binder_provenance_sha256="e" * 64,
            native_sync_events=(f"sync-{attempt_number}",),
            reused_tokens=4,
            prefilled_tokens=8,
        ),
        visible_feedback=(),
        artifact_refs=(),
        timing=AttemptTiming(
            preparation_seconds=0.1 if attempt_number == 1 else 0.0,
            generation_seconds=0.5,
            gate_seconds=0.25,
            repair_seconds=0.0 if attempt_number == 1 else 0.75,
            end_to_end_seconds=0.85 if attempt_number == 1 else 1.5,
        ),
    )


def test_report_retains_nonpasses_timings_checkpoints_and_separate_style() -> None:
    prose_attempts = (_attempt("p-1", "P", 1, "passed", tokens=10, elapsed=2.0),)
    compiled_attempts = (
        _attempt("c-1", "C", 1, "failed", tokens=12, elapsed=2.0),
        _attempt("c-2", "C", 2, "passed", tokens=20, elapsed=3.0),
    )
    pair = PairResult(
        pair_id="pair-1",
        task_id="H1",
        seed=7,
        arm_order=("P", "C"),
        status="completed",
        capabilities=None,
        common_boundary=None,
        shared_budget=BudgetSnapshot(elapsed_seconds=0.1, tokens=0, model_calls=0),
        arms=(
            ArmResult(
                task_id="H1",
                arm="P",
                status="passed",
                workspace_sha256="f" * 64,
                attempts=prose_attempts,
                host_grade=HostGrade("pass", "a" * 64, "grade/p"),
                duration_seconds=2.0,
            ),
            ArmResult(
                task_id="H1",
                arm="C",
                status="failed",
                workspace_sha256="e" * 64,
                attempts=compiled_attempts,
                host_grade=HostGrade("fail", "b" * 64, "grade/c"),
                duration_seconds=3.0,
            ),
        ),
    )
    mechanical = StyleEvidence(
        task_id="H1",
        seed=7,
        arm="P",
        score=0.8,
        findings=("ruff-clean",),
        source_ref="style/mechanical/p",
    )
    human = StyleEvidence(
        task_id="H1",
        seed=7,
        arm="C",
        score=0.6,
        findings=("reviewed",),
        source_ref="style/human/c",
    )
    rule = DecisionRule(
        metric="paired_behavior_pass_rate",
        direction="at_least",
        threshold=0.75,
        unit="fraction",
    )

    report = build_report(
        (pair,),
        experiment_id="experiment-1",
        mechanical_style=(mechanical,),
        human_style=(human,),
        decision_rule=rule,
        decision_value=0.5,
    )

    summary = report.pairs[0]
    assert len(report.pairs) == 1
    assert summary.arms[1].behavior_status == "fail"
    assert summary.arms[1].attempt_statuses == ("failed", "passed")
    assert summary.arms[1].retries == 1
    assert summary.arms[1].tokens == 20
    assert summary.arms[1].preparation_seconds == 0.1
    assert summary.arms[1].repair_seconds == 0.75
    assert summary.arms[1].checkpoint_keys == ("checkpoint-1", "checkpoint-2")
    assert summary.p_minus_c_elapsed_seconds == -1.0
    assert report.mechanical_style == (mechanical,)
    assert report.human_style == (human,)
    assert report.decision is not None
    assert report.decision.outcome == "not_met"
    assert "limited comparison" in report.claims_limit


def test_report_store_persists_versioned_summary(tmp_path: Path) -> None:
    report = build_report((), experiment_id="pilot-1")

    path = RunStore(tmp_path / "records").write_report("report-1", report)

    document = Path(path).read_text()
    assert '"record_kind":"report"' in document
    assert '"report_version":0' in document
    assert '"pairs":[]' in document


def test_context_failure_cannot_produce_a_completed_report() -> None:
    pair = PairResult(
        pair_id="context-failure",
        task_id="H3",
        seed=2,
        arm_order=("P", "C"),
        status="context_failed",
        capabilities=None,
        common_boundary=None,
        shared_budget=BudgetSnapshot(elapsed_seconds=60, tokens=100, model_calls=3),
        arms=(),
    )
    report = build_report((pair,), experiment_id="context-failure")
    assert report.status == "blocked"
