from dataclasses import dataclass
from typing import Literal

from plan_comparison.contracts import (
    Arm,
    ArmResult,
    DecisionRule,
    PairResult,
)

type BehaviorStatus = Literal["pass", "fail", "error", "not_applicable", "not_scored"]
type ReportStatus = Literal["completed", "blocked", "harness_fault"]


@dataclass(frozen=True, slots=True)
class StyleEvidence:
    task_id: str
    seed: int
    arm: Arm
    score: float | None
    findings: tuple[str, ...]
    source_ref: str


@dataclass(frozen=True, slots=True)
class ArmSummary:
    arm: Arm
    workflow_status: str
    behavior_status: BehaviorStatus
    elapsed_seconds: float
    preparation_seconds: float
    generation_seconds: float
    gate_seconds: float
    repair_seconds: float
    tokens: int
    model_calls: int
    retries: int
    attempt_statuses: tuple[str, ...]
    checkpoint_keys: tuple[str, ...]
    native_sync_events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairSummary:
    pair_id: str
    task_id: str
    seed: int
    status: str
    arm_order: tuple[Arm, Arm]
    p_minus_c_elapsed_seconds: float | None
    arms: tuple[ArmSummary, ...]
    registration_diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionSummary:
    rule: DecisionRule
    observed_value: float | None
    outcome: Literal["met", "not_met", "not_scored"]


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    report_version: Literal[0]
    experiment_id: str
    status: ReportStatus
    registration_sha256: str | None
    pairs: tuple[PairSummary, ...]
    mechanical_style: tuple[StyleEvidence, ...]
    human_style: tuple[StyleEvidence, ...]
    decision: DecisionSummary | None
    preflight_diagnostics: tuple[str, ...]
    claims_limit: str


def build_report(
    pairs: tuple[PairResult, ...],
    *,
    experiment_id: str,
    mechanical_style: tuple[StyleEvidence, ...] = (),
    human_style: tuple[StyleEvidence, ...] = (),
    decision_rule: DecisionRule | None = None,
    decision_value: float | None = None,
    status: ReportStatus | None = None,
    registration_sha256: str | None = None,
    preflight_diagnostics: tuple[str, ...] = (),
) -> ExperimentReport:
    pair_ids = [pair.pair_id for pair in pairs]
    if len(set(pair_ids)) != len(pair_ids):
        raise ValueError("Report input contains duplicate pair IDs.")
    if any(
        item.source_ref.startswith("protected:")
        for item in mechanical_style + human_style
    ):
        raise ValueError(
            "Style evidence references must not expose protected source paths."
        )
    summaries = tuple(_pair_summary(pair) for pair in pairs)
    decision = (
        _decision_summary(decision_rule, decision_value)
        if decision_rule is not None
        else None
    )
    if status is None:
        if any(pair.status == "harness_fault" for pair in pairs):
            status = "harness_fault"
        elif preflight_diagnostics or any(pair.status == "blocked" for pair in pairs):
            status = "blocked"
        else:
            status = "completed"
    return ExperimentReport(
        report_version=0,
        experiment_id=experiment_id,
        status=status,
        registration_sha256=registration_sha256,
        pairs=summaries,
        mechanical_style=mechanical_style,
        human_style=human_style,
        decision=decision,
        preflight_diagnostics=preflight_diagnostics,
        claims_limit=(
            "Three task families support only a limited comparison, not broad "
            "statistical claims. Style measurements and human judgments are "
            "reported separately."
        ),
    )


def _pair_summary(pair: PairResult) -> PairSummary:
    arm_summaries = tuple(_arm_summary(arm) for arm in pair.arms)
    p_result = next((arm for arm in pair.arms if arm.arm == "P"), None)
    c_result = next((arm for arm in pair.arms if arm.arm == "C"), None)
    elapsed_delta = (
        p_result.duration_seconds - c_result.duration_seconds
        if p_result is not None and c_result is not None
        else None
    )
    return PairSummary(
        pair_id=pair.pair_id,
        task_id=pair.task_id,
        seed=pair.seed,
        status=pair.status,
        arm_order=pair.arm_order,
        p_minus_c_elapsed_seconds=elapsed_delta,
        arms=arm_summaries,
        registration_diagnostics=tuple(
            f"{item.code}:{item.field}:{item.message}"
            for item in pair.registration_diagnostics
        ),
    )


def _arm_summary(arm: ArmResult) -> ArmSummary:
    by_packet: dict[str, int] = {}
    for attempt in arm.attempts:
        if attempt.attempt_number > 0:
            by_packet[attempt.packet_id] = max(
                by_packet.get(attempt.packet_id, 0), attempt.attempt_number
            )
    checkpoint_keys = tuple(
        dict.fromkeys(
            attempt.boundary_evidence.checkpoint_key
            for attempt in arm.attempts
            if attempt.boundary_evidence is not None
        )
    )
    sync_events = tuple(
        event
        for attempt in arm.attempts
        if attempt.boundary_evidence is not None
        for event in attempt.boundary_evidence.native_sync_events
    )
    return ArmSummary(
        arm=arm.arm,
        workflow_status=arm.status,
        behavior_status=arm.host_grade.status if arm.host_grade else "not_scored",
        elapsed_seconds=arm.duration_seconds,
        preparation_seconds=sum(
            item.timing.preparation_seconds for item in arm.attempts
        ),
        generation_seconds=sum(item.timing.generation_seconds for item in arm.attempts),
        gate_seconds=sum(item.timing.gate_seconds for item in arm.attempts),
        repair_seconds=sum(item.timing.repair_seconds for item in arm.attempts),
        tokens=arm.attempts[-1].budget.tokens if arm.attempts else 0,
        model_calls=arm.attempts[-1].budget.model_calls if arm.attempts else 0,
        retries=sum(max(0, attempts - 1) for attempts in by_packet.values()),
        attempt_statuses=tuple(item.status for item in arm.attempts),
        checkpoint_keys=checkpoint_keys,
        native_sync_events=sync_events,
    )


def _decision_summary(
    rule: DecisionRule, observed_value: float | None
) -> DecisionSummary:
    if observed_value is None:
        outcome: Literal["met", "not_met", "not_scored"] = "not_scored"
    elif rule.direction == "at_least":
        outcome = "met" if observed_value >= rule.threshold else "not_met"
    else:
        outcome = "met" if observed_value <= rule.threshold else "not_met"
    return DecisionSummary(rule=rule, observed_value=observed_value, outcome=outcome)
