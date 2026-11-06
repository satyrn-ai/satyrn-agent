import hashlib
import os
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from ds4py import Session
from ds4py._native.protocol import Snapshot
from ds4py.engine.decode import PlainStep
from ds4py.engine.events import Event, Stopped, Token
from ds4py.engine.sampling import SamplingPolicy

import satyrn_agent
from satyrn_agent.config import SatyrnConfig
from satyrn_agent.dflash import DFlashStep
from satyrn_agent.engine import SatyrnEngine


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


def _verify_identity(path: Path, variable: str) -> None:
    expected = os.environ.get(variable)
    if expected is None:
        pytest.skip(f"{variable} is required to pin the real GGUF identity")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        pytest.fail(f"{path} SHA-256 is {actual}, expected {expected}")


@pytest.fixture(scope="session")
def live_settings() -> LiveSettings:
    source = os.environ.get("SATYRN_TEST_DS4_SRC")
    settings = LiveSettings(
        model=_required("SATYRN_TEST_MODEL"),
        drafter=_required("SATYRN_TEST_DRAFTER"),
        lib=_required("SATYRN_TEST_LIB"),
        source=Path(source).resolve() if source is not None else None,
    )
    _verify_identity(settings.model, "SATYRN_TEST_MODEL_SHA256")
    _verify_identity(settings.drafter, "SATYRN_TEST_DRAFTER_SHA256")
    return settings


@contextmanager
def configured_session(
    settings: LiveSettings,
    config: SatyrnConfig,
    *,
    seed: int = 1,
) -> Generator[tuple[SatyrnEngine, Session]]:
    with satyrn_agent.open(
        settings.model,
        config=config,
        lib=settings.lib,
        seed=seed,
    ) as wrapper:
        yield wrapper, wrapper.session()


def observe_round(
    session: Session,
    *,
    max_tokens: int,
    sampling: SamplingPolicy | None = None,
    stop_sequences: Sequence[bytes] = (),
    started: float,
) -> RoundObservation:
    import time

    events = list(session.run_round(max_tokens=max_tokens, sampling=sampling, stop_sequences=stop_sequences))
    return RoundObservation(
        events=events,
        transcript=session.transcript.tokens,
        native_position=session.ctx_used,
        rng=session._rng.state.value,
        wall_seconds=time.perf_counter() - started,
    )


def assert_alignment(session: Session, observation: RoundObservation) -> None:
    generated = observation.token_ids
    assistant = tuple(
        token
        for segment in session.transcript.segments
        if segment.kind == "assistant"
        for token in observation.transcript[segment.start : segment.end]
    )
    assert assistant == generated
    assert observation.native_position == len(observation.transcript)


def prepare_chat(session: Session, prompt: str) -> int:
    session.start_chat()
    session.append_user(prompt)
    return len(session.transcript.tokens)


def restore_snapshot(session: Session, prompt_tokens: int, snapshot: Snapshot, rng: int, step: DFlashStep) -> None:
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
) -> tuple[RoundObservation, RoundObservation, int]:
    import time

    if not isinstance(wrapper._step, DFlashStep):
        pytest.fail("the parity fixture requires a configured DFlashStep")
    step = wrapper._step
    prompt_tokens = prepare_chat(session, prompt)
    snapshot = session._worker.call(lambda engine, native: native.save_snapshot()).result()
    rng = session._rng.state.value
    session.set_decode_step(PlainStep())
    started = time.perf_counter()
    try:
        serial = observe_round(session, max_tokens=max_tokens, sampling=sampling, started=started)
        assert_alignment(session, serial)
        restore_snapshot(session, prompt_tokens, snapshot, rng, step)
        started = time.perf_counter()
        speculative = observe_round(session, max_tokens=max_tokens, sampling=sampling, started=started)
        assert_alignment(session, speculative)
    finally:
        snapshot.close()
    return serial, speculative, prompt_tokens
