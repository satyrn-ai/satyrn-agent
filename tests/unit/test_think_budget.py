from collections.abc import Sequence
from typing import Any, cast

import pytest
from ds4py._native.protocol import SessionHandle
from ds4py.engine.logits import LogitsView

from satyrn_agent.capabilities.think_budget import ThinkBudgetHook, resolve_end_think
from satyrn_agent.config import ThinkBudgetConfig
from satyrn_agent.errors import ConfigurationError


class FakeLogitsSession:
    def __init__(self) -> None:
        self.copies = 0
        self.values: list[float] = []

    def copy_logits(self, out: Any) -> None:
        self.copies += 1
        for index in range(len(out)):
            out[index] = float(index)

    def set_logits(self, values: Sequence[float]) -> None:
        self.values = list(values)


class FakeEngine:
    def __init__(self, tokens: list[int]) -> None:
        self.tokens = tokens
        self.calls: list[tuple[str, bool]] = []

    def tokenize(self, text: str, *, rendered: bool = False) -> list[int]:
        self.calls.append((text, rendered))
        return self.tokens


def make_view(session: FakeLogitsSession, *, in_think: bool, think_tokens: int) -> LogitsView:
    view = LogitsView(cast("SessionHandle", session), 4)
    view._update(
        position=think_tokens,
        in_think=in_think,
        think_tokens=think_tokens,
        parser_state="think" if in_think else None,
        sampled_tokens=(),
    )
    return view


def test_hook_does_nothing_outside_think_or_below_threshold() -> None:
    session = FakeLogitsSession()
    hook = ThinkBudgetHook(ThinkBudgetConfig(max_tokens=3, bias=2.0), 2)

    hook(make_view(session, in_think=False, think_tokens=3))
    hook(make_view(session, in_think=True, think_tokens=2))

    assert session.copies == 0
    assert session.values == []


def test_hook_biases_end_think_at_and_after_threshold() -> None:
    session = FakeLogitsSession()
    hook = ThinkBudgetHook(ThinkBudgetConfig(max_tokens=3, bias=2.0), 2)

    hook(make_view(session, in_think=True, think_tokens=3))
    assert session.values == [0.0, 1.0, 4.0, 3.0]

    hook(make_view(session, in_think=True, think_tokens=4))
    assert session.copies == 2
    assert session.values == [0.0, 1.0, 4.0, 3.0]


def test_resolve_end_think_requires_one_rendered_token() -> None:
    engine = FakeEngine([42])

    assert resolve_end_think(engine) == 42
    assert engine.calls == [("</think>", True)]


@pytest.mark.parametrize("tokens", [[], [1, 2]])
def test_resolve_end_think_rejects_ambiguous_markers(tokens: list[int]) -> None:
    with pytest.raises(ConfigurationError, match="exactly one token"):
        resolve_end_think(FakeEngine(tokens))
