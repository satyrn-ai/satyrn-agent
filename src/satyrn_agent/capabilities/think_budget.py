"""A disabled-by-default soft bias toward the closing think marker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from satyrn_agent.errors import ConfigurationError

if TYPE_CHECKING:
    from ds4py.engine.logits import LogitsView

    from satyrn_agent.config import ThinkBudgetConfig


class Tokenizer(Protocol):
    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]: ...


@dataclass(frozen=True, slots=True)
class ThinkBudgetHook:
    config: ThinkBudgetConfig
    end_think_token: int

    def __call__(self, view: LogitsView) -> None:
        if view.in_think and view.think_tokens >= self.config.max_tokens:
            view.bias(self.end_think_token, self.config.bias)


def resolve_end_think(engine: Tokenizer) -> int:
    """Resolve only the fixed marker, never arbitrary user content."""
    tokens = engine.tokenize("</think>", rendered=True)
    if len(tokens) != 1:
        raise ConfigurationError("</think> must resolve to exactly one token")
    return tokens[0]
