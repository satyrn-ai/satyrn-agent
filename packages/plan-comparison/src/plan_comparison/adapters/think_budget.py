from __future__ import annotations

from array import array
from collections.abc import Sequence
from math import inf
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ds4py.engine.logits import LogitsView


THINKING_BUDGET_CLOSE = (
    "\n\nConsidering the limited time by the user, I have to give the solution "
    "based on the thinking directly now.\n</think>"
)


class ThinkingBudgetHook:
    def __init__(
        self,
        *,
        budget_tokens: int,
        closing_tokens: Sequence[int],
        vocab_size: int,
    ) -> None:
        if (
            not isinstance(budget_tokens, int)
            or isinstance(budget_tokens, bool)
            or budget_tokens <= 0
        ):
            raise ValueError("thinking budget must be a positive integer")
        if (
            not isinstance(vocab_size, int)
            or isinstance(vocab_size, bool)
            or vocab_size <= 0
        ):
            raise ValueError("vocabulary size must be a positive integer")

        tokens = tuple(closing_tokens)
        if not tokens:
            raise ValueError("thinking budget close sequence must not be empty")
        if any(
            not isinstance(token, int)
            or isinstance(token, bool)
            or not 0 <= token < vocab_size
            for token in tokens
        ):
            raise ValueError("thinking budget close sequence has an invalid token")

        self.budget_tokens = budget_tokens
        self.closing_tokens = tokens
        self._mask = array("f", [-inf]) * vocab_size
        self._reply_origin: int | None = None
        self._accounted_tokens: tuple[int, ...] = ()
        self._thinking_checkpoints: list[tuple[int, bool | None, int]] = [(0, None, 0)]
        self._force_start: int | None = None
        self._force_prefix: tuple[int, ...] | None = None

    def __call__(self, view: LogitsView) -> None:
        sampled_tokens = view.sampled_tokens
        reply_origin = view.position - len(sampled_tokens)
        if reply_origin != self._reply_origin:
            self._reply_origin = reply_origin
            self._accounted_tokens = ()
            self._thinking_checkpoints = [(0, None, 0)]
            self._force_start = None
            self._force_prefix = None

        common_length = 0
        for known_token, sampled_token in zip(
            self._accounted_tokens, sampled_tokens, strict=False
        ):
            if known_token != sampled_token:
                break
            common_length += 1

        if common_length < len(self._accounted_tokens):
            self._accounted_tokens = self._accounted_tokens[:common_length]
            del self._thinking_checkpoints[common_length + 1 :]

        if len(sampled_tokens) == common_length:
            thinking_usage, previous_in_think, _ = self._thinking_checkpoints[
                common_length
            ]
            if previous_in_think is None:
                thinking_usage = view.think_tokens if view.in_think else 0
                self._thinking_checkpoints[common_length] = (
                    thinking_usage,
                    view.in_think,
                    view.think_tokens if view.in_think else 0,
                )
        else:
            thinking_usage, previous_in_think, previous_think_tokens = (
                self._thinking_checkpoints[common_length]
            )
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

        if not view.in_think:
            self._force_start = None
            self._force_prefix = None
            return
        if thinking_usage < self.budget_tokens:
            self._force_start = None
            self._force_prefix = None
            return

        if (
            self._force_start is None
            or self._force_prefix is None
            or sampled_tokens[: self._force_start] != self._force_prefix
        ):
            self._force_start = len(sampled_tokens)
            self._force_prefix = sampled_tokens

        token_offset = len(sampled_tokens) - self._force_start
        if token_offset >= len(self.closing_tokens):
            self._force_start = None
            self._force_prefix = None
            return

        token_id = self.closing_tokens[token_offset]
        self._mask[token_id] = 0.0
        try:
            view.set_logits(self._mask)
        finally:
            self._mask[token_id] = -inf
