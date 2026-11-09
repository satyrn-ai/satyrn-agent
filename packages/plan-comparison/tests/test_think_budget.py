from importlib import import_module
from importlib.util import find_spec

import pytest

_CLOSE = (
    "\n\nConsidering the limited time by the user, I have to give the solution "
    "based on the thinking directly now.\n</think>"
)


def _thinking_budget_hook_type():
    module_name = "plan_comparison.adapters.think_budget"
    assert find_spec(module_name) is not None, "thinking-budget hook is missing"
    module = import_module(module_name)
    return module.ThinkingBudgetHook


class _FakeLogitsView:
    def __init__(
        self,
        *,
        position: int,
        in_think: bool,
        think_tokens: int,
        sampled_tokens: tuple[int, ...],
        vocab_size: int = 32,
    ) -> None:
        self.vocab_size = vocab_size
        self.logits: tuple[float, ...] | None = None
        self.set_count = 0
        self.update(
            position=position,
            in_think=in_think,
            think_tokens=think_tokens,
            sampled_tokens=sampled_tokens,
        )

    def update(
        self,
        *,
        position: int,
        in_think: bool,
        think_tokens: int,
        sampled_tokens: tuple[int, ...],
    ) -> None:
        self.position = position
        self.in_think = in_think
        self.think_tokens = think_tokens
        self.sampled_tokens = sampled_tokens

    def set_logits(self, logits) -> None:
        self.logits = tuple(logits)
        self.set_count += 1


def _selected_token(view: _FakeLogitsView) -> int:
    assert view.logits is not None
    selected = [
        index for index, value in enumerate(view.logits) if value != float("-inf")
    ]
    assert len(selected) == 1
    return selected[0]


def test_budget_hook_leaves_sampling_untouched_until_the_limit() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12, 13), vocab_size=32)
    view = _FakeLogitsView(
        position=101,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21,),
    )

    hook(view)
    assert view.set_count == 0

    view.update(
        position=102,
        in_think=True,
        think_tokens=2,
        sampled_tokens=(21, 22),
    )
    hook(view)

    assert _selected_token(view) == 11


def test_budget_hook_counts_thinking_across_blocks() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12), vocab_size=32)
    view = _FakeLogitsView(
        position=101,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21,),
    )
    hook(view)
    assert view.set_count == 0

    view.update(
        position=102,
        in_think=False,
        think_tokens=0,
        sampled_tokens=(21, 30),
    )
    hook(view)
    view.update(
        position=103,
        in_think=True,
        think_tokens=0,
        sampled_tokens=(21, 30, 31),
    )
    hook(view)
    view.update(
        position=104,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21, 30, 31, 22),
    )
    hook(view)

    assert _selected_token(view) == 11


def test_budget_hook_forces_one_token_at_a_time_from_staged_history() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12, 13), vocab_size=32)
    view = _FakeLogitsView(
        position=102,
        in_think=True,
        think_tokens=2,
        sampled_tokens=(21, 22),
    )

    hook(view)
    first = _selected_token(view)
    hook(view)
    repeated = _selected_token(view)

    view.update(
        position=103,
        in_think=True,
        think_tokens=3,
        sampled_tokens=(21, 22, first),
    )
    hook(view)
    second = _selected_token(view)
    view.update(
        position=104,
        in_think=True,
        think_tokens=4,
        sampled_tokens=(21, 22, first, second),
    )
    hook(view)

    assert (first, repeated, second, _selected_token(view)) == (11, 11, 12, 13)


@pytest.mark.parametrize(
    ("in_think", "think_tokens"),
    [(False, 0), (False, 2), (True, 1)],
)
def test_budget_hook_does_not_close_nonthinking_or_early_closed_replies(
    in_think: bool, think_tokens: int
) -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12), vocab_size=32)
    view = _FakeLogitsView(
        position=102,
        in_think=in_think,
        think_tokens=think_tokens,
        sampled_tokens=(21, 22),
    )

    hook(view)

    assert view.set_count == 0


def test_budget_hook_starts_a_fresh_budget_for_the_next_reply() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12), vocab_size=32)
    first_reply = _FakeLogitsView(
        position=102,
        in_think=True,
        think_tokens=2,
        sampled_tokens=(21, 22),
    )
    hook(first_reply)
    assert _selected_token(first_reply) == 11

    next_reply = _FakeLogitsView(
        position=250,
        in_think=True,
        think_tokens=2,
        sampled_tokens=(),
    )
    hook(next_reply)

    assert _selected_token(next_reply) == 11


def test_budget_hook_resets_cumulative_usage_after_multiple_blocks() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=2, closing_tokens=(11, 12), vocab_size=32)
    view = _FakeLogitsView(
        position=101,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21,),
    )
    hook(view)
    view.update(
        position=102,
        in_think=False,
        think_tokens=0,
        sampled_tokens=(21, 30),
    )
    hook(view)
    view.update(
        position=103,
        in_think=True,
        think_tokens=0,
        sampled_tokens=(21, 30, 31),
    )
    hook(view)
    view.update(
        position=104,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21, 30, 31, 22),
    )
    hook(view)
    assert _selected_token(view) == 11

    next_reply = _FakeLogitsView(
        position=201,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(),
    )
    hook(next_reply)

    assert next_reply.set_count == 0


def test_budget_hook_rewinds_accounting_with_discarded_staged_tokens() -> None:
    hook_type = _thinking_budget_hook_type()
    hook = hook_type(budget_tokens=3, closing_tokens=(11, 12), vocab_size=32)
    view = _FakeLogitsView(
        position=101,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21,),
    )
    hook(view)
    view.update(
        position=102,
        in_think=False,
        think_tokens=0,
        sampled_tokens=(21, 30),
    )
    hook(view)
    view.update(
        position=103,
        in_think=True,
        think_tokens=0,
        sampled_tokens=(21, 30, 31),
    )
    hook(view)
    view.update(
        position=104,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21, 30, 31, 22),
    )
    hook(view)
    assert view.set_count == 0

    view.update(
        position=105,
        in_think=True,
        think_tokens=2,
        sampled_tokens=(21, 30, 31, 22, 23),
    )
    hook(view)
    assert _selected_token(view) == 11
    set_count_at_threshold = view.set_count

    view.update(
        position=103,
        in_think=True,
        think_tokens=0,
        sampled_tokens=(21, 30, 31),
    )
    hook(view)
    view.update(
        position=104,
        in_think=True,
        think_tokens=1,
        sampled_tokens=(21, 30, 31, 24),
    )
    hook(view)

    assert view.set_count == set_count_at_threshold


@pytest.mark.parametrize(
    ("budget_tokens", "closing_tokens", "vocab_size"),
    [
        (0, (11,), 32),
        (-1, (11,), 32),
        (True, (11,), 32),
        (2, (), 32),
        (2, (32,), 32),
        (2, (11,), 0),
    ],
)
def test_budget_hook_rejects_invalid_policy_inputs(
    budget_tokens: int,
    closing_tokens: tuple[int, ...],
    vocab_size: int,
) -> None:
    hook_type = _thinking_budget_hook_type()

    with pytest.raises(ValueError):
        hook_type(
            budget_tokens=budget_tokens,
            closing_tokens=closing_tokens,
            vocab_size=vocab_size,
        )


def test_fake_engine_forces_the_rendered_close_after_the_budget() -> None:
    pytest.importorskip("ds4py")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative, reply
    from ds4py.engine.events import Stopped, Token

    hook_type = _thinking_budget_hook_type()
    with ds4py.open(
        "fake.gguf",
        ctx=1024,
        think=ThinkMode.HIGH,
        native=FakeNative(script=reply(b"xy")),
    ) as engine:
        session = engine.session()
        session.start_chat()
        closing_tokens = engine.tokenize(_CLOSE, rendered=True)
        session.add_logits_hook(
            hook_type(
                budget_tokens=2,
                closing_tokens=closing_tokens,
                vocab_size=engine.info.vocab_size,
            )
        )

        events = list(session.run_round())
        output = [event.id for event in events if isinstance(event, Token)]

        assert output == engine.tokenize("xy") + closing_tokens
        assert events[-1] == Stopped("stop_token")


def test_fake_engine_does_not_insert_a_close_when_thinking_is_disabled() -> None:
    pytest.importorskip("ds4py")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative, reply
    from ds4py.engine.events import Token

    hook_type = _thinking_budget_hook_type()
    with ds4py.open(
        "fake.gguf",
        ctx=1024,
        think=ThinkMode.NONE,
        native=FakeNative(script=reply(b"ok")),
    ) as engine:
        session = engine.session()
        session.start_chat()
        session.add_logits_hook(
            hook_type(
                budget_tokens=1,
                closing_tokens=engine.tokenize(_CLOSE, rendered=True),
                vocab_size=engine.info.vocab_size,
            )
        )

        events = list(session.run_round())
        output = [event.id for event in events if isinstance(event, Token)]

        assert output == engine.tokenize("ok")


def test_fake_engine_resets_the_budget_for_each_assistant_reply() -> None:
    pytest.importorskip("ds4py")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative, reply
    from ds4py.engine.events import Token

    hook_type = _thinking_budget_hook_type()
    with ds4py.open(
        "fake.gguf",
        ctx=1024,
        think=ThinkMode.HIGH,
        native=FakeNative(script=reply(b"x")),
    ) as engine:
        session = engine.session()
        session.start_chat()
        closing_tokens = engine.tokenize(_CLOSE, rendered=True)
        session.add_logits_hook(
            hook_type(
                budget_tokens=1,
                closing_tokens=closing_tokens,
                vocab_size=engine.info.vocab_size,
            )
        )

        first = [event.id for event in session.run_round() if isinstance(event, Token)]
        session.append_user("next reply")
        second = [event.id for event in session.run_round() if isinstance(event, Token)]

        assert first == engine.tokenize("x") + closing_tokens
        assert second == engine.tokenize("x") + closing_tokens


@pytest.mark.parametrize(
    ("budget_tokens", "thinking_blocks"),
    [
        (3, "a</think><think>b"),
        (4, "ab</think>answer text<think>c"),
        (3, "a</think>answer<think></think>more answer<think>"),
    ],
)
def test_fake_engine_shares_the_budget_across_reopened_thinking_blocks(
    budget_tokens: int, thinking_blocks: str
) -> None:
    pytest.importorskip("ds4py")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FAKE_EOS, FakeNative
    from ds4py.engine.events import Token

    hook_type = _thinking_budget_hook_type()
    scripted_tokens: list[int] = []

    def script(_prompt, generated):
        if len(generated) < len(scripted_tokens):
            return scripted_tokens[len(generated)]
        return FAKE_EOS

    with ds4py.open(
        "fake.gguf",
        ctx=1024,
        think=ThinkMode.HIGH,
        native=FakeNative(script=script),
    ) as engine:
        session = engine.session()
        session.start_chat()
        first_blocks = engine.tokenize(thinking_blocks, rendered=True)
        closing_tokens = engine.tokenize(_CLOSE, rendered=True)
        scripted_tokens.extend(first_blocks)
        session.add_logits_hook(
            hook_type(
                budget_tokens=budget_tokens,
                closing_tokens=closing_tokens,
                vocab_size=engine.info.vocab_size,
            )
        )

        events = list(session.run_round())
        output = [event.id for event in events if isinstance(event, Token)]

        assert output == first_blocks + closing_tokens
