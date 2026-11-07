"""Typed observations collected from public model-free rounds."""

from dataclasses import dataclass, field

from ds4py.engine.events import Event

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
    metrics: DFlashMetrics
    metadata: list[SampleMetadata]


@dataclass(slots=True)
class ScenarioResult:
    rounds: list[RoundResult]
    reached_branches: set[str] = field(default_factory=set)

    @property
    def events(self) -> list[Event]:
        return [event for result in self.rounds for event in result.events]

    @property
    def transcript(self) -> tuple[int, ...]:
        return self.rounds[-1].transcript

    @property
    def native_position(self) -> int:
        return self.rounds[-1].native_position

    @property
    def rng(self) -> int:
        return self.rounds[-1].rng

    @property
    def metrics(self) -> DFlashMetrics:
        return self.rounds[-1].metrics

    @property
    def metadata(self) -> list[SampleMetadata]:
        return [item for result in self.rounds for item in result.metadata]
