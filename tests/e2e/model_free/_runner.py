"""Execute validated scenarios through the real public Satyrn session flow."""

from dataclasses import asdict
from pathlib import Path

from ds4py import Session
from ds4py.engine.events import Stopped, Token

import satyrn_agent
from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.dflash import DFlashMetrics
from tests.conftest import MetadataRecorder, SampleMetadata
from tests.e2e.model_free._native import ScenarioFakeNative
from tests.e2e.model_free._observations import RoundResult, ScenarioResult
from tests.e2e.scenarios._generated.scenario_types import Expectation, Round, Scenario, ScenarioConfig


def _config(config: ScenarioConfig) -> SatyrnConfig:
    sampling = config.get("sampling", {})
    budget = config.get("think_budget")
    return SatyrnConfig(
        dflash=DFlashMode(config.get("dflash", "auto")),
        drafter_path=Path(path) if (path := config.get("drafter_path", "drafter.gguf")) is not None else None,
        draft_tokens=config.get("draft_tokens", 0),
        sampling=SamplingOverrides(
            temperature=sampling.get("temperature"),
            top_k=sampling.get("top_k"),
            top_p=sampling.get("top_p"),
            min_p=sampling.get("min_p"),
        ),
        think_budget=None
        if budget is None
        else ThinkBudgetConfig(max_tokens=budget["max_tokens"], bias=budget["bias"]),
    )


def _prepare(session: Session, round: Round) -> None:
    if round.get("mode", "raw") == "chat":
        if not session.transcript.chat:
            session.start_chat()
        session.append_user(round["prompt"])
    else:
        session.append_tokens([1], "user")


def _observe(
    session: Session,
    wrapper: satyrn_agent.SatyrnEngine,
    round: Round,
    recorder: MetadataRecorder,
) -> RoundResult:
    _prepare(session, round)
    events = list(
        session.run_round(
            max_tokens=round["max_tokens"],
            stop_sequences=[value.encode() for value in round.get("stop_sequences", [])],
        )
    )
    stopped = [event.reason for event in events if isinstance(event, Stopped)]
    return RoundResult(
        events=events,
        transcript=session.transcript.tokens,
        native_position=session.ctx_used,
        rng=session._rng.state.value,
        token_ids=tuple(event.id for event in events if isinstance(event, Token)),
        reason=stopped[-1] if stopped else None,
        metrics=wrapper.dflash_metrics or DFlashMetrics(),
        metadata=list(recorder.calls),
    )


def run_scenario(scenario: Scenario) -> ScenarioResult:
    native = ScenarioFakeNative(scenario["native"])
    recorder = MetadataRecorder()
    results: list[RoundResult] = []
    with satyrn_agent.open("scenario.gguf", config=_config(scenario["config"]), native=native, seed=1) as wrapper:
        session = wrapper.session()
        for round in scenario["rounds"]:
            native.cancel_after_samples = round.get("cancel_after_samples")
            results.append(_observe(session, wrapper, round, recorder))
            recorder.serial_count = len(recorder.calls)

    result = ScenarioResult(results)
    result.reached_branches.update(native.operations)
    if native.operations:
        result.reached_branches.add("anchor")
    if wrapper.dflash_metrics is None:
        result.reached_branches.add("plain-step")
    else:
        result.reached_branches.add("dflash-step")
    metrics = wrapper.dflash_metrics or DFlashMetrics()
    if metrics.drafts_offered == 0:
        result.reached_branches.add("zero-drafts")
    if metrics.drafts_accepted < metrics.drafts_offered:
        result.reached_branches.add("partial-acceptance")
    if metrics.drafts_offered > 0 and metrics.drafts_accepted == metrics.drafts_offered:
        result.reached_branches.add("full-acceptance")
    if metrics.replacement_anchors:
        result.reached_branches.add("replacement-anchor")
    if metrics.discarded_tails:
        result.reached_branches.add("discarded-tail")
    result.reached_branches.update(round.reason for round in results if round.reason is not None)
    return result


def _expected_metadata(expectation: Expectation) -> list[SampleMetadata]:
    return [
        SampleMetadata(item["position"], item["think_tokens"], tuple(item["sampled_tokens"]), item.get("parser_state"))
        for item in expectation["metadata"]
    ]


def assert_scenario(scenario: Scenario, result: ScenarioResult) -> None:
    assert len(result.rounds) == len(scenario["rounds"])
    for index, (expected_round, actual) in enumerate(zip(scenario["rounds"], result.rounds, strict=True)):
        expected = expected_round["expect"]
        prefix = f"{scenario['id']} round {index}"
        assert actual.token_ids == tuple(expected["token_ids"]), prefix
        assert actual.reason == expected["reason"], prefix
        assert actual.native_position == expected["native_position"], prefix
        assert actual.rng == expected["rng"], prefix
        assert asdict(actual.metrics) == expected["metrics"], prefix
        assert [type(event).__name__ for event in actual.events] == expected["event_types"], prefix
        assert actual.metadata == _expected_metadata(expected), prefix
    assert scenario["expected_branches"] <= result.reached_branches, (
        f"{scenario['id']} missed {scenario['expected_branches'] - result.reached_branches}"
    )
