import json
from pathlib import Path

import pytest

from plan_comparison.budget import BudgetExhausted, MonotonicBudget
from plan_comparison.contracts import (
    ArmResult,
    AttemptRecord,
    BudgetLimits,
    BudgetSnapshot,
    PairResult,
)
from plan_comparison.records import RecordStoreError, RunStore


def test_budget_counters_remain_monotonic_after_exhaustion() -> None:
    budget = MonotonicBudget(BudgetLimits(wall_seconds=10, tokens=5, model_calls=2))
    budget.record_model_call()
    budget.record_tokens(3)
    before = budget.snapshot()

    with pytest.raises(BudgetExhausted):
        budget.record_tokens(3)

    after = budget.snapshot()
    assert after.tokens == 6
    assert after.model_calls == before.model_calls
    with pytest.raises(BudgetExhausted):
        budget.ensure_capacity()


def test_run_store_persists_versioned_pair_and_attempt_records(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "host-records")
    budget = BudgetSnapshot(elapsed_seconds=0.25, tokens=4, model_calls=1)
    attempt_record = AttemptRecord(
        attempt_id="attempt-001",
        task_id="H1",
        arm="C",
        packet_id="packet-1",
        attempt_number=1,
        status="failed",
        started_at="2026-11-08T10:00:00+00:00",
        completed_at="2026-11-08T10:00:01+00:00",
        input_sha256="a" * 64,
        code_delta_sha256="b" * 64,
        gates=(),
        budget=budget,
        boundary_evidence=None,
        visible_feedback=("Expected assertion failed.",),
        artifact_refs=(),
    )
    first_ref = store.write_attempt(attempt_record)
    pair = PairResult(
        pair_id="pair-001",
        task_id="H1",
        seed=3,
        arm_order=("P", "C"),
        status="completed",
        capabilities=None,
        common_boundary=None,
        shared_budget=budget,
        arms=(
            ArmResult(
                task_id="H1",
                arm="P",
                status="passed",
                workspace_sha256="c" * 64,
                attempts=(),
                host_grade=None,
            ),
            ArmResult(
                task_id="H1",
                arm="C",
                status="failed",
                workspace_sha256="d" * 64,
                attempts=(attempt_record,),
                host_grade=None,
            ),
        ),
    )
    pair_ref = store.write_pair(pair)

    attempt_document = json.loads(Path(first_ref).read_text())
    pair_document = json.loads(Path(pair_ref).read_text())
    assert attempt_document["record_version"] == 0
    assert attempt_document["record"]["status"] == "failed"
    assert pair_document["record_kind"] == "pair"
    assert (
        pair_document["record"]["arms"][1]["attempts"][0]["attempt_id"] == "attempt-001"
    )
    with pytest.raises(RecordStoreError, match="already exists"):
        store.write_attempt(attempt_record)
