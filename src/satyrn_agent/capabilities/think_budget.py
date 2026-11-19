"""A stable think hook with optional soft or forced closing behavior."""

from __future__ import annotations

import threading
from array import array
from math import inf
from typing import TYPE_CHECKING, Protocol

from satyrn_agent.config import ThinkCloseMode
from satyrn_agent.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ds4py.engine.logits import LogitsView

    from satyrn_agent.config import ThinkBudgetConfig

THINKING_BUDGET_CLOSE = (
    "\n\nConsidering the limited time by the user, I have to give the solution "
    "based on the thinking directly now.\n</think>"
)


class Tokenizer(Protocol):
    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]: ...


class ThinkBudgetHook:
    """One stable worker hook whose immutable setting can be replaced."""

    def __init__(
        self,
        config: ThinkBudgetConfig | None,
        end_think_token: int,
        closing_tokens: Sequence[int],
        vocab_size: int,
    ) -> None:
        if not isinstance(vocab_size, int) or isinstance(vocab_size, bool) or vocab_size <= 0:
            raise ValueError("vocabulary size must be a positive integer")
        tokens = tuple(closing_tokens)
        if not tokens:
            raise ValueError("thinking budget close sequence must not be empty")
        if any(isinstance(token, bool) or not 0 <= token < vocab_size for token in tokens):
            raise ValueError("thinking budget close sequence has an invalid token")
        self._config = config
        self._suppressed = False
        self._end_think_token = end_think_token
        self._closing_tokens = tokens
        self._mask = array("f", [-inf]) * vocab_size
        self._lock = threading.Lock()
        self._reply_origin: int | None = None
        self._accounted_tokens: tuple[int, ...] = ()
        self._thinking_checkpoints: list[tuple[int, bool | None, int]] = [(0, None, 0)]
        self._force_start: int | None = None
        self._force_prefix: tuple[int, ...] | None = None

    def set(self, config: ThinkBudgetConfig | None) -> None:
        with self._lock:
            self._config = config

    def snapshot(self) -> ThinkBudgetConfig | None:
        with self._lock:
            return self._config

    def start_run(self) -> None:
        with self._lock:
            self._suppressed = False

    def suppress_thinking(self) -> None:
        with self._lock:
            self._suppressed = True

    def _snapshot(self) -> tuple[ThinkBudgetConfig | None, bool]:
        with self._lock:
            return self._config, self._suppressed

    def _reset_force(self) -> None:
        self._force_start = None
        self._force_prefix = None

    def _thinking_usage(self, view: LogitsView) -> int:
        sampled_tokens = view.sampled_tokens
        reply_origin = view.position - len(sampled_tokens)
        if reply_origin != self._reply_origin:
            self._reply_origin = reply_origin
            self._accounted_tokens = ()
            self._thinking_checkpoints = [(0, None, 0)]
            self._reset_force()

        common_length = 0
        for known_token, sampled_token in zip(self._accounted_tokens, sampled_tokens, strict=False):
            if known_token != sampled_token:
                break
            common_length += 1

        if common_length < len(self._accounted_tokens):
            self._accounted_tokens = self._accounted_tokens[:common_length]
            del self._thinking_checkpoints[common_length + 1 :]

        if len(sampled_tokens) == common_length:
            thinking_usage, previous_in_think, _ = self._thinking_checkpoints[common_length]
            if previous_in_think is None:
                thinking_usage = view.think_tokens if view.in_think else 0
                self._thinking_checkpoints[common_length] = (
                    thinking_usage,
                    view.in_think,
                    view.think_tokens if view.in_think else 0,
                )
        else:
            thinking_usage, previous_in_think, previous_think_tokens = self._thinking_checkpoints[common_length]
            if view.in_think:
                if previous_in_think is None:
                    thinking_usage = view.think_tokens
                elif previous_in_think:
                    thinking_usage += max(view.think_tokens - previous_think_tokens, 0)
                else:
                    thinking_usage += view.think_tokens

            self._accounted_tokens = sampled_tokens
            self._thinking_checkpoints.extend(
                [
                    (
                        thinking_usage,
                        view.in_think,
                        view.think_tokens if view.in_think else 0,
                    )
                ]
                * (len(sampled_tokens) - common_length)
            )
        return thinking_usage

    def _force(self, view: LogitsView, closing_tokens: tuple[int, ...]) -> None:
        sampled_tokens = view.sampled_tokens
        if (
            self._force_start is None
            or self._force_prefix is None
            or sampled_tokens[: self._force_start] != self._force_prefix
        ):
            self._force_start = len(sampled_tokens)
            self._force_prefix = sampled_tokens

        token_offset = len(sampled_tokens) - self._force_start
        if token_offset >= len(closing_tokens):
            self._reset_force()
            return

        token_id = closing_tokens[token_offset]
        self._mask[token_id] = 0.0
        try:
            view.set_logits(self._mask)
        finally:
            self._mask[token_id] = -inf

    def __call__(self, view: LogitsView) -> None:
        config, suppressed = self._snapshot()
        closing_tokens: tuple[int, ...] | None = None
        if config is not None:
            if suppressed and config.until_first_write:
                if view.in_think:
                    closing_tokens = (self._end_think_token,)
            elif config.close is ThinkCloseMode.BIAS:
                if view.in_think and view.think_tokens >= config.max_tokens:
                    view.bias(self._end_think_token, config.bias)
            elif self._thinking_usage(view) >= config.max_tokens and view.in_think:
                closing_tokens = self._closing_tokens
        if closing_tokens is None:
            self._reset_force()
        else:
            self._force(view, closing_tokens)


def resolve_end_think(engine: Tokenizer) -> int:
    """Resolve only the fixed marker, never arbitrary user content."""
    tokens = engine.tokenize("</think>", rendered=True)
    if len(tokens) != 1:
        raise ConfigurationError("</think> must resolve to exactly one token")
    return tokens[0]
