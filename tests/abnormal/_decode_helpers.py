import ctypes as C
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from ds4py._native.protocol import EngineHandle, EngineInfo, SessionHandle
from ds4py.engine.decode import DecodeContext, GenerateJob
from ds4py.engine.events import Event
from ds4py.engine.logits import LogitsView
from ds4py.engine.sampling import Rng, SamplingPolicy
from ds4py.engine.transcript import Transcript

from satyrn_agent._native import NativeSampling


class FakeEngine:
    raw = 10

    def __init__(self, stops: set[int] | None = None) -> None:
        self.stops = stops or set()

    def info(self) -> EngineInfo:
        return EngineInfo("fake", 0, "qwen", False, False, True, False, 0, 0, 128)

    def token_text(self, token: int) -> bytes:
        return f"<{token}>".encode()

    def is_stop(self, token: int) -> bool:
        return token in self.stops

    def is_stop_for_think_mode(self, token: int, mode: int) -> bool:
        return token in self.stops


class FakeSession:
    raw = 20

    def __init__(self, samples: Sequence[int]) -> None:
        self.samples = list(samples)
        self.sampled: list[int] = []
        self.evaluated: list[int] = []
        self.position = 0
        self.sampling_calls: list[tuple[float, int, float, float]] = []
        self.eval_error: Exception | None = None
        self.sample_error: Exception | None = None
        self.sample_error_at = 1

    def pos(self) -> int:
        return self.position

    def eval(self, token: int) -> None:
        if self.eval_error is not None:
            raise self.eval_error
        self.evaluated.append(token)
        self.position += 1

    def sample(self, temperature: float, top_k: int, top_p: float, min_p: float, rng: C.c_uint64) -> int:
        self.sampling_calls.append((temperature, top_k, top_p, min_p))
        if self.sample_error is not None and len(self.sampling_calls) == self.sample_error_at:
            raise self.sample_error
        token = self.samples.pop(0)
        self.sampled.append(token)
        rng.value += 1
        return token


class FakeDFlashNative:
    def __init__(self, session: FakeSession, drafts: Sequence[int] = ()) -> None:
        self.session = session
        self.drafts = list(drafts)
        self.verify_open = False
        self.calls: list[tuple[str, int]] = []
        self.commit_error: Exception | None = None
        self.commit_side_effect = False
        self.draft_error: Exception | None = None
        self.verify_error: Exception | None = None
        self.select_error: Exception | None = None

    @property
    def missing_dflash(self) -> tuple[str, ...]:
        return ()

    def has_dflash(self, engine_raw: int) -> bool:
        return True

    def verify_rows(self, engine_raw: int) -> int:
        return 8

    def set_verify_mode(self, session_raw: int, mode: int) -> None:
        self.calls.append(("mode", mode))

    def draft(self, session_raw: int, anchor: int, maximum: int) -> list[int]:
        self.calls.append(("draft", anchor))
        if self.draft_error is not None:
            raise self.draft_error
        return self.drafts[:maximum]

    def verify(self, session_raw: int, anchor: int, drafts: Sequence[int]) -> None:
        self.calls.append(("verify", anchor))
        if self.verify_error is not None:
            raise self.verify_error
        self.verify_open = True

    def select(self, session_raw: int, row: int) -> None:
        self.calls.append(("select", row))
        if self.select_error is not None:
            raise self.select_error

    def commit(self, session_raw: int, rows: int) -> None:
        self.calls.append(("commit", rows))
        if self.commit_error is not None:
            if self.commit_side_effect:
                self.session.position += rows
                self.verify_open = False
            raise self.commit_error
        self.session.position += rows
        self.verify_open = False

    def sampling_defaults(self, engine_raw: int) -> NativeSampling | None:
        return None


@dataclass
class DecodeFixture:
    ctx: DecodeContext
    engine: FakeEngine
    session: FakeSession
    transcript: Transcript
    events: list[Event]


def make_decode(
    samples: Sequence[int],
    *,
    stops: set[int] | None = None,
    max_tokens: int = 50,
    cancelled: Callable[[], bool] = lambda: False,
    logits_hooks: Sequence[Callable[[LogitsView], None]] = (),
    poisoned: list[BaseException] | None = None,
) -> DecodeFixture:
    engine = FakeEngine(stops)
    session = FakeSession(samples)
    transcript = Transcript()
    events: list[Event] = []
    rng = Rng(1)
    job = GenerateJob(
        sampling=SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=1),
        rng=rng,
        max_tokens=max_tokens,
        transcript=transcript,
        logits_hooks=tuple(logits_hooks),
    )
    ctx = DecodeContext(
        cast("EngineHandle", engine),
        job,
        limit=max_tokens,
        limit_reason="max_tokens",
        cancelled=cancelled,
        emit=events.append,
        session=cast("SessionHandle", session),
        poison=None if poisoned is None else poisoned.append,
    )
    return DecodeFixture(ctx, engine, session, transcript, events)
