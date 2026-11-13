"""A disabled-by-default soft bias toward the closing think marker."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from satyrn_agent.errors import ConfigurationError

if TYPE_CHECKING:
    from ds4py.engine.logits import LogitsView

    from satyrn_agent.config import ThinkBudgetConfig


class Tokenizer(Protocol):
    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]: ...


class ThinkBudgetHook:
    """One stable worker hook whose immutable setting can be replaced."""

    def __init__(self, config: ThinkBudgetConfig | None, end_think_token: int) -> None:
        self._config = config
        self._end_think_token = end_think_token
        self._lock = threading.Lock()

    def set(self, config: ThinkBudgetConfig | None) -> None:
        with self._lock:
            self._config = config

    def snapshot(self) -> ThinkBudgetConfig | None:
        with self._lock:
            return self._config

    def __call__(self, view: LogitsView) -> None:
        config = self.snapshot()
        if config is not None and view.in_think and view.think_tokens >= config.max_tokens:
            view.bias(self._end_think_token, config.bias)


def resolve_end_think(engine: Tokenizer) -> int:
    """Resolve only the fixed marker, never arbitrary user content."""
    tokens = engine.tokenize("</think>", rendered=True)
    if len(tokens) != 1:
        raise ConfigurationError("</think> must resolve to exactly one token")
    return tokens[0]
