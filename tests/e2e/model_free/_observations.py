"""Typed observations collected from public model-free rounds."""

from dataclasses import dataclass, field

from ds4py.engine.events import Event
from ds4py.engine.sampling import SamplingPolicy

from satyrn_agent.dflash import DFlashMetrics
from tests.conftest import SampleMetadata


@dataclass(slots=True)
class RoundResult:
    events: list[Event]
    transcript: tuple[int, ...]
    native_position: int
    rng: int
    token_ids: tuple[int, ...]
    reason: str | None
    error: Exception | None
    sampling: SamplingPolicy
    metrics: DFlashMetrics
    token_positions: list[int] = field(default_factory=list)
    metadata: list[SampleMetadata] = field(default_factory=list)
    native_calls: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ScenarioResult:
    rounds: list[RoundResult]
    reached_branches: set[str] = field(default_factory=set)


def failed_round(error: Exception, sampling: SamplingPolicy) -> RoundResult:
    return RoundResult(
        events=[],
        transcript=(),
        native_position=0,
        rng=1,
        token_ids=(),
        reason=f"{type(error).__name__}: {error}",
        error=error,
        sampling=sampling,
        metrics=DFlashMetrics(),
    )
