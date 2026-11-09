from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Collection, Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

if TYPE_CHECKING:
    import threading

    from tests.e2e.model_free._native import ScenarioFakeNative

import pytest
from ds4py import Session, ThinkMode
from ds4py._native.protocol import Snapshot
from ds4py.engine.decode import PlainStep
from ds4py.engine.events import Event, Prefill, ReserveReached, Stopped, Token
from ds4py.engine.logits import LogitsView
from ds4py.engine.sampling import SamplingPolicy
from ds4py.engine.tool_prompt import ToolDefinition
from ds4py.engine.transcript import TranscriptView
from inline_snapshot import external_file

import satyrn_agent
from satyrn_agent.config import SatyrnConfig
from satyrn_agent.dflash import DFlashMetrics, DFlashStep
from satyrn_agent.engine import SatyrnEngine
from tests.e2e.corpus import is_expected_metrics, load_corpus


@dataclass(frozen=True, slots=True)
class LiveSettings:
    model: Path
    drafter: Path
    lib: Path
    source: Path | None


@dataclass(slots=True)
class RoundObservation:
    events: list[Event]
    transcript: tuple[int, ...]
    native_position: int
    rng: int
    wall_seconds: float
    assistant_start: int
    assistant_tokens: tuple[int, ...]

    @property
    def token_ids(self) -> tuple[int, ...]:
        return tuple(event.id for event in self.events if isinstance(event, Token))

    @property
    def reason(self) -> str | None:
        stopped = [event.reason for event in self.events if isinstance(event, Stopped)]
        return stopped[-1] if stopped else None


def _required(name: str) -> Path:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is required for the real patched-engine gate")
    return Path(value).expanduser().resolve()


def _verify_identity(path: Path, kind: Literal["target", "drafter"]) -> None:
    corpus = load_corpus()
    identity = corpus["target"] if kind == "target" else corpus["drafter"]
    expected = identity["sha256"]
    if not isinstance(expected, str):
        pytest.skip(f"approved {kind} SHA-256 and quantization must be pinned in tests/e2e/corpus.json")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        pytest.fail(f"{path} SHA-256 is {actual}, expected approved {expected}")


@pytest.fixture(scope="session")
def live_settings() -> LiveSettings:
    source = os.environ.get("SATYRN_TEST_DS4_SRC")
    settings = LiveSettings(
        model=_required("SATYRN_TEST_MODEL"),
        drafter=_required("SATYRN_TEST_DRAFTER"),
        lib=_required("SATYRN_TEST_LIB"),
        source=Path(source).resolve() if source is not None else None,
    )
    _verify_identity(settings.model, "target")
    _verify_identity(settings.drafter, "drafter")
    return settings


@contextmanager
def configured_session(
    settings: LiveSettings,
    config: SatyrnConfig,
    *,
    seed: int = 1,
    ctx: int = 100_000,
    think: int = ThinkMode.HIGH,
    cancel: threading.Event | None = None,
) -> Generator[tuple[SatyrnEngine, Session]]:
    with satyrn_agent.open(
        settings.model,
        config=config,
        ctx=ctx,
        lib=settings.lib,
        seed=seed,
        think=think,
        cancel=cancel,
    ) as wrapper:
        yield wrapper, wrapper.session()


@dataclass(frozen=True, slots=True)
class SampleMetadata:
    position: int
    think_tokens: int
    sampled_tokens: tuple[int, ...]
    parser_state: str | None


class MetadataRecorder:
    def __init__(self) -> None:
        self.calls: list[SampleMetadata] = []
        self.serial_count: int | None = None

    def __call__(self, view: LogitsView) -> None:
        self.calls.append(SampleMetadata(view.position, view.think_tokens, view.sampled_tokens, view.parser_state))

    @property
    def serial(self) -> tuple[SampleMetadata, ...]:
        if self.serial_count is None:
            return ()
        return tuple(self.calls[: self.serial_count])

    @property
    def speculative(self) -> tuple[SampleMetadata, ...]:
        if self.serial_count is None:
            return ()
        return tuple(self.calls[self.serial_count :])


def _assistant_tokens(transcript: TranscriptView) -> tuple[int, ...]:
    tokens = transcript.tokens
    return tuple(
        token
        for segment in transcript.segments
        if segment.kind == "assistant"
        for token in tokens[segment.start : segment.end]
    )


def _event_value(value: object) -> object:
    # ToolCall.args is a MappingProxyType; dataclasses.asdict() fails on its deep copy.
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _event_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _event_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_event_value(item) for item in value)
    if isinstance(value, list):
        return [_event_value(item) for item in value]
    return value


def normalized_events(events: Iterable[Event]) -> list[tuple[str, dict[str, object]]]:
    normalized = []
    for event in events:
        if isinstance(event, ReserveReached):
            normalized.append(("ReserveReached", dict[str, object](needed=event.needed)))
            continue
        payload = {field.name: _event_value(getattr(event, field.name)) for field in fields(event)}
        if isinstance(event, Prefill):
            payload["tps"] = 0.0  # Wall clock only; serial and speculative prefill times differ.
        normalized.append((type(event).__name__, payload))
    return normalized


@overload
def assert_output(output: str, expected_path: Path) -> None: ...


@overload
def assert_output(output: Mapping[str, object], expected_path: Path) -> None: ...


def assert_output(output: object, expected_path: Path) -> None:
    """Compare text or a JSON mapping with an external inline-snapshot file.

    Mapping output is valid only when ``expected_path`` has a ``.json`` suffix.
    """
    if expected_path.suffix == ".json" and not isinstance(output, str):
        assert output == external_file(expected_path)
        return
    if not isinstance(output, str):
        pytest.fail(f"expected text output for {expected_path}, got {type(output).__name__}")
    assert output.replace("\r\n", "\n") == external_file(expected_path)


def assert_metrics(metrics: DFlashMetrics, expected_path: Path) -> None:
    expected: object = json.loads(expected_path.read_text())
    if not is_expected_metrics(expected):
        pytest.fail(f"invalid metric snapshot: {expected_path}")
    assert_output(asdict(metrics), expected_path)


def observe_round(
    session: Session,
    *,
    max_tokens: int,
    sampling: SamplingPolicy | None = None,
    stop_sequences: Sequence[bytes] = (),
    started: float,
    resume_once_with_zero_reserve: bool = False,
) -> RoundObservation:
    import time

    assistant_start = len(_assistant_tokens(session.transcript))
    events = []
    resumed = False
    for event in session.run_round(max_tokens=max_tokens, sampling=sampling, stop_sequences=stop_sequences):
        if isinstance(event, ReserveReached):
            if resume_once_with_zero_reserve and not resumed:
                event.resume(0)
                resumed = True
            else:
                event.fail()
        events.append(event)
    return RoundObservation(
        events=events,
        transcript=session.transcript.tokens,
        native_position=session.ctx_used,
        rng=session._rng.state.value,
        wall_seconds=time.perf_counter() - started,
        assistant_start=assistant_start,
        assistant_tokens=_assistant_tokens(session.transcript),
    )


def assert_alignment(
    session: Session,
    observation: RoundObservation,
) -> None:
    generated = observation.token_ids
    assert observation.assistant_tokens[observation.assistant_start :] == generated
    segments = session.transcript.segments
    unevaluated_eos = segments[-1].end - segments[-1].start if segments and segments[-1].kind == "eos" else 0
    assert observation.native_position == len(observation.transcript) - unevaluated_eos


def prepare_chat(session: Session, prompt: str, *, tools: Collection[ToolDefinition] = ()) -> int:
    if session.transcript.chat and tools:
        raise ValueError("tools must be supplied before the chat is started")
    if not session.transcript.chat:
        session.start_chat(tools=tools)
    session.append_user(prompt)
    return len(session.transcript.tokens)


def restore_snapshot(
    session: Session,
    prompt_tokens: int,
    snapshot: Snapshot,
    rng: int,
    step: DFlashStep,
    scripted_native: ScenarioFakeNative | None = None,
) -> None:
    if scripted_native is not None:
        scripted_native.reset_script()
    session.truncate(prompt_tokens)
    session._worker.call(lambda engine, native: native.load_snapshot(snapshot)).result()
    session._rng.state.value = rng
    session.set_decode_step(step)


def serial_then_speculative(
    wrapper: SatyrnEngine,
    session: Session,
    prompt: str,
    *,
    max_tokens: int,
    sampling: SamplingPolicy,
    tools: Collection[ToolDefinition] = (),
    recorder: MetadataRecorder | None = None,
    scripted_native: ScenarioFakeNative | None = None,
) -> tuple[RoundObservation, RoundObservation, int]:
    import time

    if not isinstance(wrapper.decode_step, DFlashStep):
        pytest.fail("the parity fixture requires a configured DFlashStep")
    step = wrapper.decode_step
    prompt_tokens = prepare_chat(session, prompt, tools=tools)
    session._worker.call(lambda engine, native: native.sync(session.transcript.tokens)).result()
    if recorder is not None:
        session.add_logits_hook(recorder)
    snapshot = session._worker.call(lambda engine, native: native.save_snapshot()).result()
    rng = session._rng.state.value
    session.set_decode_step(PlainStep())
    started = time.perf_counter()
    try:
        serial = observe_round(session, max_tokens=max_tokens, sampling=sampling, started=started)
        assert_alignment(session, serial)
        if recorder is not None:
            recorder.serial_count = len(recorder.calls)
        restore_snapshot(session, prompt_tokens, snapshot, rng, step, scripted_native)
        started = time.perf_counter()
        speculative = observe_round(session, max_tokens=max_tokens, sampling=sampling, started=started)
        assert_alignment(session, speculative)
    finally:
        snapshot.close()
    return serial, speculative, prompt_tokens
