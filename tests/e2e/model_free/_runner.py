"""Execute validated scenarios through the real public Satyrn session flow."""

import math
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ds4py import EngineError, Session, ThinkMode, WorkerPoisonedError
from ds4py._json import is_string_key_mapping
from ds4py._native.protocol import SessionHandle
from ds4py.engine.decode import DecodeContext, DecodeStep, PlainStep, Verdict
from ds4py.engine.events import Event, Interrupted, Stopped, Token
from ds4py.engine.logits import LogitsView
from ds4py.engine.sampling import SamplingPolicy
from ds4py.engine.tool_prompt import ToolDefinition

import satyrn_agent
from satyrn_agent.config import DFlashMode, SamplingOverrides, SatyrnConfig, ThinkBudgetConfig
from satyrn_agent.dflash import DFlashMetrics, DFlashStep
from satyrn_agent.errors import ConfigurationError, DFlashError, DFlashUnavailable
from tests.conftest import (
    MetadataRecorder,
    RoundObservation,
    SampleMetadata,
    normalized_events,
    serial_then_speculative,
)
from tests.e2e.model_free._native import ScenarioFakeNative
from tests.e2e.model_free._observations import RoundResult, ScenarioResult
from tests.e2e.scenarios._generated.scenario_types import ConfigDocument, Expectation, Round, Scenario

SUPPORTED_BRANCHES = {
    "anchor",
    "budget",
    "commit",
    "config-error",
    "dflash-step",
    "discarded-tail",
    "done",
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
    "policy-error",
    "poison",
    "replacement-anchor",
    "row",
    "select",
    "stop_sequence",
    "stop_token",
    "verify",
    "zero-drafts",
}


def _config(config: ConfigDocument) -> SatyrnConfig:
    return satyrn_agent.config_from_dict(config)


def _raw_value(value: object) -> object:
    if value == "nonfinite":
        return float("nan")
    if value == "large-int":
        return 10**1000
    if isinstance(value, Mapping):
        return {key: _raw_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_raw_value(item) for item in value]
    return value


def _raw_config(raw: Mapping[str, object]) -> SatyrnConfig:
    converted = _raw_value(raw)
    if not is_string_key_mapping(converted):
        raise TypeError("raw_config must be a mapping")
    values = dict[str, Any](converted)
    if isinstance(values.get("dflash"), str) and values["dflash"] in {"auto", "on", "off"}:
        values["dflash"] = DFlashMode(values["dflash"])
    if isinstance(values.get("drafter_path"), str):
        values["drafter_path"] = Path(values["drafter_path"])
    if isinstance(values.get("sampling"), Mapping):
        values["sampling"] = SamplingOverrides(**values["sampling"])
    if isinstance(values.get("think_budget"), Mapping):
        values["think_budget"] = ThinkBudgetConfig(**values["think_budget"])
    return SatyrnConfig(**values)


def _prepare(session: Session, round: Round) -> None:
    if round.get("mode", "raw") == "chat":
        if not session.transcript.chat:
            session.start_chat(
                tools=[
                    ToolDefinition(tool["name"], tool["description"], tool["parameters"])
                    for tool in round.get("tools", [])
                ]
            )
        session.append_user(round["prompt"])
    else:
        session.append_tokens([1], "user")


def _from_snapshot(
    observation: RoundObservation,
    session: Session,
    metadata: Sequence[SampleMetadata],
    metrics: DFlashMetrics,
) -> RoundResult:
    return RoundResult(
        events=observation.events,
        transcript=observation.transcript,
        native_position=observation.native_position,
        rng=observation.rng,
        token_ids=observation.token_ids,
        token_positions=[],
        reason=observation.reason,
        error=None,
        sampling=session.engine.sampling_defaults,
        metrics=metrics,
        metadata=list(metadata),
        native_calls=[],
    )


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
    call_start = len(native.call_log)
    error: Exception | None = None
    events = []
    token_positions = []
    try:
        if round.get("cancel_after_samples") == -3 and native.cancel_event is not None:
            native.cancel_event.set()
        _prepare(session, round)
        for event in session.run_round(
            max_tokens=round["max_tokens"],
            stop_sequences=[value.encode() for value in round.get("stop_sequences", [])],
        ):
            events.extend([event])
            if isinstance(event, Token):
                token_positions.append(max((len(fake._tokens) for fake in native.sessions.values()), default=0))
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
        token_positions=token_positions,
        reason=reason,
        error=error,
        sampling=session.engine.sampling_defaults,
        metrics=wrapper.dflash_metrics or DFlashMetrics(),
        metadata=list(recorder.calls),
        native_calls=native.call_log[call_start:],
    )


class ScenarioStep:
    """Inject scenario-declared context faults without replacing DFlashStep."""

    def __init__(
        self,
        inner: DecodeStep,
        native: ScenarioFakeNative,
        finish_at: int | None,
        finish_reason: str | None,
        cancel_after_accept: int | None,
    ) -> None:
        self.inner = inner
        self.native = native
        self.finish_at = finish_at
        self.finish_reason = finish_reason
        self.cancel_after_accept = cancel_after_accept
        self.hooks_every_sample = inner.hooks_every_sample

    def run(self, session: SessionHandle, ctx: DecodeContext) -> None:
        if self.finish_at == 0 and self.finish_reason is not None:
            ctx.finish(self.finish_reason)
        original_stage = ctx.stage
        staged = 0

        def stage(token: int, verdict: Verdict | None = None) -> Verdict:
            nonlocal staged
            staged += 1
            result = original_stage(token, verdict)
            if self.cancel_after_accept == staged and self.native.cancel_event is not None:
                self.native.cancel_event.set()
            return result

        ctx.__dict__["stage"] = stage
        calls = 0

        def finish_hook(view: LogitsView) -> None:
            nonlocal calls
            calls += 1
            if self.finish_at == calls and self.finish_reason is not None:
                ctx.finish(self.finish_reason)

        ctx._job = replace(ctx._job, logits_hooks=(*ctx._job.logits_hooks, finish_hook))
        self.inner.run(session, ctx)


def run_scenario(scenario: Scenario) -> ScenarioResult:  # noqa: C901, PLR0912 - Keep branch reporting in one dispatch.
    try:
        config = _raw_config(scenario["raw_config"]) if "raw_config" in scenario else _config(scenario["config"])
    except Exception as error:  # noqa: BLE001 - Preserve setup failure as a scenario observation.
        return ScenarioResult(
            [
                RoundResult(
                    events=[],
                    transcript=(),
                    native_position=0,
                    rng=1,
                    token_ids=(),
                    token_positions=[],
                    reason=f"{type(error).__name__}: {error}",
                    error=error,
                    sampling=SamplingPolicy(),
                    metrics=DFlashMetrics(),
                    metadata=[],
                    native_calls=[],
                )
            ],
            reached_branches={"config-error" if "raw_config" in scenario else "policy-error"},
        )
    native = ScenarioFakeNative(scenario["native"], scenario["backend"])
    cancel_event = threading.Event()
    native.cancel_event = cancel_event
    recorder = MetadataRecorder()
    results: list[RoundResult] = []
    with satyrn_agent.open(
        "scenario.gguf",
        config=config,
        native=native,
        seed=1,
        think=scenario.get("think", ThinkMode.HIGH),
        cancel=cancel_event,
    ) as wrapper:
        try:
            session = wrapper.session()
        except Exception as error:  # noqa: BLE001 - Preserve setup failure as a scenario observation.
            results.append(
                RoundResult(
                    events=[],
                    transcript=(),
                    native_position=0,
                    rng=1,
                    token_ids=(),
                    token_positions=[],
                    reason=f"{type(error).__name__}: {error}",
                    error=error,
                    sampling=wrapper._engine.sampling_defaults,
                    metrics=DFlashMetrics(),
                    metadata=[],
                    native_calls=[],
                )
            )
        else:
            hook_error_at: int | None = None
            hook_calls = 0

            def hook(view: LogitsView) -> None:
                nonlocal hook_calls
                hook_calls += 1
                recorder(view)
                if hook_error_at == hook_calls:
                    raise RuntimeError("hook injected")

            if not scenario.get("snapshot_parity", False) and any(
                round["expect"]["metadata"]
                or round.get("hook_error_at") is not None
                or round.get("finish_at") is not None
                or round.get("finish_reason") is not None
                or round.get("cancel_after_accept")
                for round in scenario["rounds"]
            ):
                session.add_logits_hook(hook)
            if scenario.get("snapshot_parity", False):
                round = scenario["rounds"][0]
                serial, speculative, _ = serial_then_speculative(
                    wrapper,
                    session,
                    round["prompt"],
                    max_tokens=round["max_tokens"],
                    sampling=session.engine.sampling_defaults,
                    recorder=recorder,
                    scripted_native=native,
                )
                assert speculative.token_ids == serial.token_ids
                assert speculative.reason == serial.reason
                assert speculative.rng == serial.rng
                assert normalized_events(speculative.events) == normalized_events(serial.events)
                assert recorder.speculative == recorder.serial
                results.append(_from_snapshot(serial, session, recorder.serial, DFlashMetrics()))
                results.append(
                    _from_snapshot(
                        speculative,
                        session,
                        recorder.speculative,
                        wrapper.dflash_metrics or DFlashMetrics(),
                    )
                )
            else:
                for round in scenario["rounds"]:
                    native.cancel_after_samples = round.get("cancel_after_samples")
                    hook_error_at = round.get("hook_error_at")
                    if wrapper._step is not None and (
                        round.get("finish_at") is not None
                        or round.get("finish_reason") is not None
                        or round.get("cancel_after_accept") is not None
                    ):
                        session.set_decode_step(
                            ScenarioStep(
                                wrapper._step,
                                native,
                                round.get("finish_at"),
                                round.get("finish_reason"),
                                round.get("cancel_after_accept"),
                            )
                        )
                    metadata_start = len(recorder.calls)
                    observed = _observe(session, wrapper, native, round, recorder)
                    observed.metadata = observed.metadata[metadata_start:]
                    results.append(observed)
                    recorder.serial_count = len(recorder.calls)

    result = ScenarioResult(results)
    result.reached_branches.update(native.operations)
    if native.operations:
        result.reached_branches.add("anchor")
    if isinstance(wrapper._step, PlainStep):
        result.reached_branches.add("plain-step")
    elif isinstance(wrapper._step, DFlashStep):
        result.reached_branches.add("dflash-step")
    if recorder.calls:
        result.reached_branches.add("metadata")
    metrics = wrapper.dflash_metrics or DFlashMetrics()
    if any(count == 0 for count in native.draft_results):
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
    if any(isinstance(round.error, DFlashUnavailable | ConfigurationError) for round in results):
        result.reached_branches.add("policy-error")
    if any(isinstance(round.error, EngineError) for round in results):
        result.reached_branches.add("engine-error")
    return result


def _expected_metadata(expectation: Expectation) -> list[SampleMetadata]:
    return [
        SampleMetadata(item["position"], item["think_tokens"], tuple(item["sampled_tokens"]), item.get("parser_state"))
        for item in expectation["metadata"]
    ]


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return list(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _normalized_events(events: list[Event]) -> list[dict[str, object]]:
    return [{"type": event_type, "payload": _json_value(payload)} for event_type, payload in normalized_events(events)]


def assert_scenario(scenario: Scenario, result: ScenarioResult) -> None:
    assert len(result.rounds) == len(scenario["rounds"])
    for index, (expected_round, actual) in enumerate(zip(scenario["rounds"], result.rounds, strict=True)):
        expected = expected_round["expect"]
        prefix = f"{scenario['id']} round {index}"
        assert actual.token_ids == tuple(expected["token_ids"]), prefix
        assert actual.reason == expected["reason"], prefix
        assert actual.native_position == expected["native_position"], prefix
        assert actual.rng == expected["rng"], prefix
        if "sampling_defaults" in expected:
            expected_sampling = expected["sampling_defaults"]
            assert actual.sampling.top_k == expected_sampling["top_k"], prefix
            assert math.isclose(actual.sampling.temperature, expected_sampling["temperature"]), prefix
            assert math.isclose(actual.sampling.top_p, expected_sampling["top_p"]), prefix
            assert math.isclose(actual.sampling.min_p, expected_sampling["min_p"], rel_tol=1e-6), prefix
        assert asdict(actual.metrics) == {
            name: value for name, value in expected["metrics"].items() if name != "acceptance_rate"
        }, prefix
        if "acceptance_rate" in expected["metrics"]:
            assert actual.metrics.acceptance_rate == expected["metrics"]["acceptance_rate"], prefix
        assert [type(event).__name__ for event in actual.events] == expected["event_types"], prefix
        if "transcript" in expected:
            assert actual.transcript == tuple(expected["transcript"]), prefix
        if "events" in expected:
            assert _normalized_events(actual.events) == expected["events"], prefix
        if "native_calls" in expected:
            assert actual.native_calls == expected["native_calls"], prefix
        if "token_positions" in expected:
            assert actual.token_positions == expected["token_positions"], prefix
        assert actual.metadata == _expected_metadata(expected), prefix
    observed_branches = result.reached_branches & SUPPORTED_BRANCHES
    assert scenario["expected_branches"] == observed_branches, (
        f"{scenario['id']} expected {scenario['expected_branches']} but observed {observed_branches}"
    )
