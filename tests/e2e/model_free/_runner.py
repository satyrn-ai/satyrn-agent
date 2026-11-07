"""Execute validated scenarios through the real public Satyrn session flow."""

import threading
from dataclasses import asdict
from pathlib import Path

from ds4py import EngineError, Session, WorkerPoisonedError
from ds4py.engine.events import Interrupted, Stopped, Token
from ds4py.engine.logits import LogitsView

import satyrn_agent
from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.dflash import DFlashMetrics
from satyrn_agent.errors import DFlashError
from tests.conftest import MetadataRecorder, SampleMetadata
from tests.e2e.model_free._native import ScenarioFakeNative
from tests.e2e.model_free._observations import RoundResult, ScenarioResult
from tests.e2e.scenarios._generated.scenario_types import Expectation, Round, Scenario, ScenarioConfig

SUPPORTED_BRANCHES = {
    "anchor",
    "commit",
    "dflash-step",
    "discarded-tail",
    "draft",
    "engine-error",
    "eval",
    "full-acceptance",
    "interrupted",
    "max_tokens",
    "metadata",
    "native-error",
    "partial-acceptance",
    "plain-step",
    "poison",
    "replacement-anchor",
    "select",
    "stop_sequence",
    "stop_token",
    "verify",
    "zero-drafts",
}


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


def _position(session: Session, native: ScenarioFakeNative) -> int:
    try:
        return session.ctx_used
    except WorkerPoisonedError:
        return max((len(fake._tokens) for fake in native.sessions.values()), default=0)


def _observe(
    session: Session,
    wrapper: satyrn_agent.SatyrnEngine,
    native: ScenarioFakeNative,
    round: Round,
    recorder: MetadataRecorder,
) -> RoundResult:
    error: Exception | None = None
    events = []
    try:
        if round.get("cancel_after_samples") == -3 and native.cancel_event is not None:
            native.cancel_event.set()
        _prepare(session, round)
        for event in session.run_round(
            max_tokens=round["max_tokens"],
            stop_sequences=[value.encode() for value in round.get("stop_sequences", [])],
        ):
            events.extend([event])
    except Exception as caught:  # noqa: BLE001 - Preserve a failed scenario as a typed observation.
        error = caught
    stopped = [event.reason for event in events if isinstance(event, Stopped)]
    reason = stopped[-1] if stopped else None
    if error is not None:
        reason = f"{type(error).__name__}: {error}"
    return RoundResult(
        events=events,
        transcript=session.transcript.tokens,
        native_position=_position(session, native),
        rng=session._rng.state.value,
        token_ids=tuple(event.id for event in events if isinstance(event, Token)),
        reason=reason,
        error=error,
        metrics=wrapper.dflash_metrics or DFlashMetrics(),
        metadata=list(recorder.calls),
    )


def run_scenario(scenario: Scenario) -> ScenarioResult:  # noqa: C901, PLR0912 - Keep branch reporting in one dispatch.
    native = ScenarioFakeNative(scenario["native"])
    cancel_event = threading.Event()
    native.cancel_event = cancel_event
    recorder = MetadataRecorder()
    results: list[RoundResult] = []
    with satyrn_agent.open(
        "scenario.gguf",
        config=_config(scenario["config"]),
        native=native,
        seed=1,
        cancel=cancel_event,
    ) as wrapper:
        session = wrapper.session()
        hook_error_at: int | None = None
        hook_calls = 0

        def hook(view: LogitsView) -> None:
            nonlocal hook_calls
            hook_calls += 1
            recorder(view)
            if hook_error_at == hook_calls:
                raise RuntimeError("hook injected")

        session.add_logits_hook(hook)
        for round in scenario["rounds"]:
            native.cancel_after_samples = round.get("cancel_after_samples")
            hook_error_at = round.get("hook_error_at")
            results.append(_observe(session, wrapper, native, round, recorder))
            recorder.serial_count = len(recorder.calls)

    result = ScenarioResult(results)
    result.reached_branches.update(native.operations)
    if native.operations:
        result.reached_branches.add("anchor")
    if wrapper.dflash_metrics is None:
        result.reached_branches.add("plain-step")
    else:
        result.reached_branches.add("dflash-step")
    if recorder.calls:
        result.reached_branches.add("metadata")
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
    if any(isinstance(event, Interrupted) for round in results for event in round.events):
        result.reached_branches.add("interrupted")
    if any(isinstance(round.error, WorkerPoisonedError) for round in results):
        result.reached_branches.add("poison")
    if any(isinstance(round.error, DFlashError) for round in results):
        result.reached_branches.add("native-error")
    if any(isinstance(round.error, EngineError) for round in results):
        result.reached_branches.add("engine-error")
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
        assert asdict(actual.metrics) == {
            name: value for name, value in expected["metrics"].items() if name != "acceptance_rate"
        }, prefix
        if "acceptance_rate" in expected["metrics"]:
            assert actual.metrics.acceptance_rate == expected["metrics"]["acceptance_rate"], prefix
        assert [type(event).__name__ for event in actual.events] == expected["event_types"], prefix
        if expected["metadata"]:
            assert actual.metadata == _expected_metadata(expected), prefix
    assert scenario["expected_branches"] <= result.reached_branches, (
        f"{scenario['id']} missed {scenario['expected_branches'] - result.reached_branches}"
    )
