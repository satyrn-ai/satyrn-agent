"""Optional DS4 adapter checks; all cases use the upstream FakeNative engine."""

import asyncio
from dataclasses import replace
from inspect import signature

import pytest

pytestmark = pytest.mark.ds4_runtime


def _fake_adapter(
    *,
    thinking_budget: int | None = None,
    think_until_first_write: bool = False,
    tool_repeat_guard: bool = False,
    rethink_after_failure: bool = False,
    response: bytes = b"done",
    family: str = "deepseek4",
    context_retry_limit: int = 2,
    thinking: bool = False,
):
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative, reply
    from ds4py.engine.sampling import SamplingPolicy
    from ds4py.model import DS4Model

    from plan_comparison.adapters.ds4 import (
        Ds4WorkerAdapter,
        build_restricted_agents,
    )
    from plan_comparison.gates import GatePolicy

    native = FakeNative(script=reply(response))
    native._info = replace(native._info, family=family, is_qwen4=family == "qwen")
    engine = ds4py.open(
        "fake.gguf",
        ctx=8192,
        think=ThinkMode.LOW if thinking else ThinkMode.NONE,
        native=native,
    )
    model = DS4Model(engine.session(), sampling=SamplingPolicy(seed=1))
    gate_policy = GatePolicy(
        allowed_commands=("pytest",),
        environment=(),
        timeout_seconds=1,
        output_limit_bytes=128,
    )
    options = (
        {"thinking_budget": thinking_budget} if thinking_budget is not None else {}
    )
    try:
        adapter = Ds4WorkerAdapter(
            model=model,
            agents=build_restricted_agents(model, gate_policy),
            model_id="fake-ds4",
            model_revision="fake-revision",
            runtime_revision="fake-runtime",
            tokenizer_revision="fake-tokenizer",
            gate_policy=gate_policy,
            think_until_first_write=think_until_first_write,
            tool_repeat_guard=tool_repeat_guard,
            rethink_after_failure=rethink_after_failure,
            context_retry_limit=context_retry_limit,
            **options,
        )
    except BaseException:
        engine.close()
        raise
    return engine, adapter


def test_adapter_registers_a_default_thinking_budget_hook() -> None:
    engine, adapter = _fake_adapter()
    try:
        assert len(adapter.session._logits_hooks) == 1
    finally:
        engine.close()


def test_phase_changes_reuse_the_shared_prefix_and_keep_its_checkpoint(
    tmp_path,
) -> None:
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import (
        BudgetLimits,
        CallableBodyExtent,
        CallableBodyTarget,
        Slot,
    )

    engine, adapter = _fake_adapter()
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )
    slot = Slot(
        slot_id="body",
        path="app.py",
        kind="callable_body",
        operation="replace_body",
        target=CallableBodyTarget("f"),
        extent=CallableBodyExtent(),
        preimage_sha256=None,
    )

    async def exercise():
        boundary = await adapter.capture_boundary(
            task_id="fake",
            plan="Implement f.",
            workspace=tmp_path,
            allowed_read_paths=(),
            budget=budget,
        )
        await adapter.execute_prose(
            task_id="fake",
            plan="Implement f.",
            workspace=tmp_path,
            allowed_read_paths=(),
            allowed_write_paths=("app.py",),
            visible_gates=(),
            visible_feedback=(),
            budget=budget,
        )
        assert adapter._last_sync_events[0].plan.kind in ("extend", "restore")
        assert adapter._last_sync_events[0].plan.reused >= boundary.evidence.token_count
        assert boundary.evidence.checkpoint_key in adapter.session._checkpoint_tokens
        await adapter.restore_boundary(boundary, budget=budget)
        await adapter.fill_body(
            task_id="fake",
            plan="Implement f.",
            workspace=tmp_path,
            allowed_read_paths=(),
            slot=slot,
            signature_prefill="def f():",
            visible_feedback=(),
            budget=budget,
        )
        assert adapter._last_sync_events[0].plan.kind in ("extend", "restore")
        assert adapter._last_sync_events[0].plan.reused >= boundary.evidence.token_count
        assert boundary.evidence.checkpoint_key in adapter.session._checkpoint_tokens

    try:
        asyncio.run(exercise())
    finally:
        engine.close()


def test_adapter_can_explicitly_disable_the_thinking_budget() -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import Ds4WorkerAdapter

    assert "thinking_budget" in signature(Ds4WorkerAdapter).parameters
    engine, adapter = _fake_adapter(thinking_budget=0)
    try:
        assert not adapter.session._logits_hooks
    finally:
        engine.close()


@pytest.mark.parametrize("thinking_budget", [-1, True, 1.5])
def test_adapter_rejects_invalid_thinking_budgets(thinking_budget) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import Ds4WorkerAdapter

    assert "thinking_budget" in signature(Ds4WorkerAdapter).parameters
    with pytest.raises(ValueError, match="thinking budget"):
        engine, _adapter = _fake_adapter(thinking_budget=thinking_budget)
        engine.close()


def test_pydantic_agents_build_over_a_fake_ds4_model_and_block_cleanup_claims() -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative
    from ds4py.engine.sampling import SamplingPolicy
    from ds4py.model import DS4Model

    from plan_comparison.adapters.ds4 import (
        Ds4WorkerAdapter,
        build_restricted_agents,
    )
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits
    from plan_comparison.gates import GatePolicy

    engine = ds4py.open(
        "fake.gguf", ctx=8192, think=ThinkMode.NONE, native=FakeNative()
    )
    model = DS4Model(engine.session(), sampling=SamplingPolicy(seed=1))
    gate_policy = GatePolicy(
        allowed_commands=("pytest",),
        environment=(),
        timeout_seconds=1,
        output_limit_bytes=128,
    )
    agents = build_restricted_agents(model, gate_policy)
    adapter = Ds4WorkerAdapter(
        model=model,
        agents=agents,
        model_id="fake-ds4",
        model_revision="fake-revision",
        runtime_revision="fake-runtime",
        tokenizer_revision="fake-tokenizer",
        gate_policy=gate_policy,
    )

    capabilities = asyncio.run(
        adapter.capabilities(
            budget=MonotonicBudget(
                BudgetLimits(wall_seconds=10, tokens=100, model_calls=10)
            )
        )
    )

    assert not capabilities.supports_paired_draws
    assert not capabilities.safe_cancellation
    assert any("issues/20" in evidence for evidence in capabilities.evidence)
    asyncio.run(
        adapter.close(
            budget=MonotonicBudget(
                BudgetLimits(wall_seconds=10, tokens=100, model_calls=10)
            )
        )
    )


def test_fake_boundary_round_trip_restores_rng_and_binder_state() -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative
    from ds4py.engine.sampling import SamplingPolicy
    from ds4py.engine.worker import SyncJob
    from ds4py.model import DS4Model

    from plan_comparison.adapters.ds4 import (
        Ds4WorkerAdapter,
        build_restricted_agents,
    )
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits
    from plan_comparison.gates import GatePolicy

    engine = ds4py.open(
        "fake.gguf", ctx=8192, think=ThinkMode.NONE, native=FakeNative()
    )
    model = DS4Model(engine.session(), sampling=SamplingPolicy(seed=5))
    policy = GatePolicy(
        allowed_commands=("pytest",),
        environment=(),
        timeout_seconds=1,
        output_limit_bytes=128,
    )
    adapter = Ds4WorkerAdapter(
        model=model,
        agents=build_restricted_agents(model, policy),
        model_id="fake-ds4",
        model_revision="fake-revision",
        runtime_revision="fake-runtime",
        tokenizer_revision="fake-tokenizer",
        gate_policy=policy,
    )
    adapter.session._transcript.append(
        [1, 2], "note", {"text": "synthetic shared context"}
    )
    sync_events = tuple(
        adapter.session._job_events(SyncJob(adapter.session.transcript.tokens))
    )
    assert sync_events
    initial_rng = int(adapter.session._rng.state.value)
    initial_tokens = tuple(adapter.session.transcript.tokens)
    boundary = adapter._capture_boundary(
        MonotonicBudget(BudgetLimits(wall_seconds=10, tokens=100, model_calls=10))
    )
    adapter.session._rng.state.value = initial_rng + 1

    asyncio.run(
        adapter.restore_boundary(
            boundary,
            budget=MonotonicBudget(
                BudgetLimits(wall_seconds=10, tokens=100, model_calls=10)
            ),
        )
    )

    assert int(adapter.session._rng.state.value) == initial_rng
    assert tuple(adapter.session.transcript.tokens) == initial_tokens
    asyncio.run(
        adapter.close(
            budget=MonotonicBudget(
                BudgetLimits(wall_seconds=10, tokens=100, model_calls=10)
            )
        )
    )


def _tool_context(tmp_path, readable, writable):
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _ToolContext
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits
    from plan_comparison.gates import GatePolicy

    return _ToolContext(
        workspace=tmp_path,
        readable_paths=frozenset(readable),
        writable_paths=frozenset(writable),
        gates={},
        gate_policy=GatePolicy(
            allowed_commands=("pytest",),
            environment=(),
            timeout_seconds=1,
            output_limit_bytes=128,
        ),
        budget=MonotonicBudget(
            BudgetLimits(wall_seconds=10, tokens=100, model_calls=10)
        ),
        max_file_read_bytes=64,
        gate_results=[],
    )


def test_thinking_until_first_write_is_optional_and_resets_on_restore(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    for enabled in (False, True):
        engine, adapter = _fake_adapter(think_until_first_write=enabled)
        budget = MonotonicBudget(
            BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
        )
        try:
            boundary = asyncio.run(
                adapter.capture_boundary(
                    task_id="fake",
                    plan="Implement f.",
                    workspace=tmp_path,
                    allowed_read_paths=(),
                    budget=budget,
                )
            )
            context = adapter._tool_context(tmp_path, (), ("ok.py",), (), budget)
            assert _write_file_result(context, "refused.py", "x").startswith("error:")
            assert not adapter._thinking_suppressed
            assert _write_file_result(context, "ok.py", "x") == "Wrote ok.py."
            assert adapter._thinking_suppressed is enabled
            asyncio.run(adapter.restore_boundary(boundary, budget=budget))
            assert not adapter._thinking_suppressed
        finally:
            engine.close()


def test_first_write_suppresses_native_thinking_without_rebuilding_prefix(
    tmp_path,
) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from ds4py._native.fake import FAKE_EOS

    from plan_comparison.adapters.ds4 import _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    engine, adapter = _fake_adapter(think_until_first_write=True, thinking=True)
    close = engine.tokenize("</think>", rendered=True)[0]
    thought = engine.tokenize("deliberate", rendered=True)
    answer = engine.tokenize("done", rendered=True)

    def script(prompt, generated):
        if close in generated:
            offset = len(generated) - generated.index(close) - 1
            return answer[offset] if offset < len(answer) else FAKE_EOS
        return thought[len(generated)] if len(generated) < len(thought) else close

    engine.native.script = script
    emitted = []
    adapter.session.on_event(
        lambda envelope: emitted.append(envelope.payload["event"].id), kinds=("Token",)
    )
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )

    async def exercise():
        boundary = await adapter.capture_boundary(
            task_id="fake",
            plan="Implement f.",
            workspace=tmp_path,
            allowed_read_paths=(),
            budget=budget,
        )
        assert emitted == thought + [close] + answer
        context = adapter._tool_context(tmp_path, (), ("ok.py",), (), budget)
        assert _write_file_result(context, "ok.py", "x") == "Wrote ok.py."

        async def generate():
            emitted.clear()
            reply = await adapter.execute_prose(
                task_id="fake",
                plan="Implement f.",
                workspace=tmp_path,
                allowed_read_paths=(),
                allowed_write_paths=("ok.py",),
                visible_gates=(),
                visible_feedback=(),
                budget=budget,
            )
            assert reply.content == "done"
            assert adapter._last_sync_events[0].plan.kind in ("extend", "restore")
            assert (
                adapter._last_sync_events[0].plan.reused
                >= boundary.evidence.token_count
            )

        await generate()
        assert emitted == [close] + answer
        await adapter.restore_boundary(boundary, budget=budget)
        await generate()
        assert emitted == thought + [close] + answer
        adapter.workspace_written()
        await generate()
        assert emitted == [close] + answer

    try:
        asyncio.run(exercise())
    finally:
        engine.close()


@pytest.mark.parametrize("reason", ["max_tokens", "parser_error"])
@pytest.mark.parametrize("token_limit", [1, 100_000])
def test_failed_responses_are_classified_and_metered(
    tmp_path, reason, token_limit
) -> None:
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits, ModelResponseFailure

    response = (
        b"unfinished reply"
        if reason == "max_tokens"
        else b"<tool_call><function=read_file><parameter=path>unfinished"
    )
    engine, adapter = _fake_adapter(response=response, family="qwen")
    if reason == "max_tokens":
        adapter.model.max_tokens = 2
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=token_limit, model_calls=10)
    )
    try:
        with pytest.raises(ModelResponseFailure) as caught:
            asyncio.run(
                adapter.execute_prose(
                    task_id="fake",
                    plan="Implement f.",
                    workspace=tmp_path,
                    allowed_read_paths=(),
                    allowed_write_paths=("app.py",),
                    visible_gates=(),
                    visible_feedback=(),
                    budget=budget,
                )
            )
        assert caught.value.reason == reason
        assert budget.snapshot().model_calls == 1
        assert budget.snapshot().tokens > 2
        assert not adapter._message_history
    finally:
        engine.close()


@pytest.mark.parametrize("reason", ["max_tokens", "parser_error"])
def test_context_failures_restart_empty_and_keep_failed_usage(tmp_path, reason) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from ds4py._native.fake import FAKE_EOS

    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    engine, adapter = _fake_adapter(family="qwen")
    adapter.model.max_tokens = 3 if reason == "max_tokens" else 1000
    calls = 0
    prompts = []

    def script(prompt, generated):
        nonlocal calls
        if not generated:
            calls += 1
            prompts.append(tuple(prompt))
        response = (
            (
                b"unfinished"
                if reason == "max_tokens"
                else b"<tool_call><function=read_file><parameter=path>unfinished"
            )
            if calls == 1
            else b"ok"
        )
        return (
            response[len(generated)] + 1 if len(generated) < len(response) else FAKE_EOS
        )

    engine.native.script = script
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )
    try:
        boundary = asyncio.run(
            adapter.capture_boundary(
                task_id="fake",
                plan="Summarize.",
                workspace=tmp_path,
                allowed_read_paths=(),
                budget=budget,
            )
        )
        assert calls == 2
        assert prompts[0] == prompts[1]
        assert budget.snapshot().model_calls == 2
        assert budget.snapshot().tokens > boundary.evidence.token_count
        assert f"ContextRetry:{reason}" in boundary.evidence.native_sync_events
    finally:
        engine.close()


def test_context_retry_exhaustion_is_distinct_and_bounded(tmp_path) -> None:
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits, ContextPreparationFailure

    engine, adapter = _fake_adapter(context_retry_limit=1)
    adapter.model.max_tokens = 2
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )
    try:
        with pytest.raises(ContextPreparationFailure) as caught:
            asyncio.run(
                adapter.capture_boundary(
                    task_id="fake",
                    plan="Summarize.",
                    workspace=tmp_path,
                    allowed_read_paths=(),
                    budget=budget,
                )
            )
        assert caught.value.reason == "max_tokens"
        assert caught.value.attempts == 2
        assert budget.snapshot().model_calls == 2
        assert budget.snapshot().tokens > 4
        assert not adapter.session.transcript.tokens
        assert not adapter._message_history
    finally:
        engine.close()


def test_failed_context_over_budget_is_cleared_without_retry(tmp_path) -> None:
    from plan_comparison.budget import BudgetExhausted, MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    engine, adapter = _fake_adapter()
    adapter.model.max_tokens = 2
    budget = MonotonicBudget(BudgetLimits(wall_seconds=30, tokens=1, model_calls=10))
    try:
        with pytest.raises(BudgetExhausted):
            asyncio.run(
                adapter.capture_boundary(
                    task_id="fake",
                    plan="Summarize.",
                    workspace=tmp_path,
                    allowed_read_paths=(),
                    budget=budget,
                )
            )
        assert budget.snapshot().model_calls == 1
        assert budget.snapshot().tokens > 1
        assert not adapter.session.transcript.tokens
        assert not adapter._message_history
    finally:
        engine.close()


def test_shared_tool_schema_still_refuses_read_only_writes_and_gates(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from ds4py._native.fake import FAKE_EOS
    from pydantic_ai.messages import ToolReturnPart

    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    engine, adapter = _fake_adapter(family="qwen")
    responses = [
        b"<tool_call><function=write_file><parameter=path>app.py</parameter>"
        b"<parameter=content>bad</parameter></function></tool_call>",
        b"<tool_call><function=run_visible_gate><parameter=gate_id>unknown</parameter>"
        b"</function></tool_call>",
        b"done",
    ]
    round_number = -1

    def script(prompt, generated):
        nonlocal round_number
        if not generated:
            round_number += 1
        response = responses[round_number]
        return (
            response[len(generated)] + 1 if len(generated) < len(response) else FAKE_EOS
        )

    engine.native.script = script
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )
    try:
        asyncio.run(
            adapter.capture_boundary(
                task_id="fake",
                plan="Summarize.",
                workspace=tmp_path,
                allowed_read_paths=(),
                budget=budget,
            )
        )
        results = [
            part.content
            for message in adapter._message_history
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert len(results) == 2
        assert all(result.startswith("error:") for result in results)
        assert not (tmp_path / "app.py").exists()
        assert adapter.agents.context is adapter.agents.prose is adapter.agents.compiled
    finally:
        engine.close()


def test_read_failures_return_to_the_model(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _read_file_result

    (tmp_path / "ok.py").write_text("x = 1\n")
    context = _tool_context(tmp_path, {"ok.py", "missing.py"}, set())

    assert _read_file_result(context, "ok.py") == "x = 1\n"
    assert _read_file_result(context, "missing.py").startswith("error:")
    assert _read_file_result(context, "secret.py").startswith("error:")
    assert _read_file_result(context, "../escape.py").startswith("error:")


def test_rejected_writes_return_to_the_model_and_change_nothing(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _write_file_result

    context = _tool_context(tmp_path, set(), {"ok.py"})

    assert _write_file_result(context, "ok.py", "x = 1\n") == "Wrote ok.py."
    assert _write_file_result(context, "other.py", "x").startswith("error:")
    assert not (tmp_path / "other.py").exists()


def test_repeat_guard_refuses_unchanged_reads_until_the_file_changes(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from dataclasses import replace as replace_context

    from plan_comparison.adapters.ds4 import _read_file_result

    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "other.py").write_text("y = 2\n")
    context = replace_context(
        _tool_context(tmp_path, {"ok.py", "other.py"}, set()), repeat_guard=True
    )

    assert _read_file_result(context, "ok.py") == "x = 1\n"
    assert _read_file_result(context, "other.py") == "y = 2\n"
    assert _read_file_result(context, "ok.py").startswith("error: ok.py")

    (tmp_path / "ok.py").write_text("x = 2\n")

    assert _read_file_result(context, "ok.py") == "x = 2\n"


def test_repeat_guard_refuses_writes_that_change_nothing(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from dataclasses import replace as replace_context

    from plan_comparison.adapters.ds4 import _write_file_result

    writes: list[None] = []
    context = replace_context(
        _tool_context(tmp_path, set(), {"ok.py"}),
        repeat_guard=True,
        on_write=lambda: writes.append(None),
    )

    assert _write_file_result(context, "ok.py", "x = 1\n") == "Wrote ok.py."
    assert _write_file_result(context, "ok.py", "x = 1\n").startswith("error: ok.py")
    assert len(writes) == 1
    assert _write_file_result(context, "ok.py", "x = 2\n") == "Wrote ok.py."
    assert (tmp_path / "ok.py").read_text() == "x = 2\n"
    assert len(writes) == 2


def test_repeated_calls_are_served_without_the_guard(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _read_file_result, _write_file_result

    (tmp_path / "ok.py").write_text("x = 1\n")
    context = _tool_context(tmp_path, {"ok.py"}, {"ok.py"})

    assert _read_file_result(context, "ok.py") == "x = 1\n"
    assert _read_file_result(context, "ok.py") == "x = 1\n"
    assert _write_file_result(context, "ok.py", "x = 1\n") == "Wrote ok.py."


def test_adapter_guard_is_optional_and_counts_refused_repeats(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _read_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    (tmp_path / "ok.py").write_text("x = 1\n")
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=10)
    )
    for enabled, expected in ((False, []), (True, ["read_file:ok.py"])):
        engine, adapter = _fake_adapter(tool_repeat_guard=enabled)
        try:
            context = adapter._tool_context(tmp_path, ("ok.py",), (), (), budget)
            _read_file_result(context, "ok.py")
            _read_file_result(context, "ok.py")
            assert adapter.refused_tool_repeats == expected
            fresh = adapter._tool_context(tmp_path, ("ok.py",), (), (), budget)
            assert _read_file_result(fresh, "ok.py") == "x = 1\n"
        finally:
            engine.close()


def test_repeating_a_refused_call_ends_the_run_as_a_tool_loop(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from dataclasses import replace as replace_context

    from plan_comparison.adapters.ds4 import _read_file_result, _write_file_result
    from plan_comparison.contracts import ModelResponseFailure

    (tmp_path / "ok.py").write_text("x = 1\n")
    context = replace_context(
        _tool_context(tmp_path, {"ok.py"}, {"ok.py"}), repeat_guard=True
    )

    assert _write_file_result(context, "ok.py", "x = 1\n").startswith("error: ok.py")
    with pytest.raises(ModelResponseFailure) as caught:
        _write_file_result(context, "ok.py", "x = 1\n")
    assert caught.value.reason == "tool_loop"
    assert "write_file ok.py" in str(caught.value)

    assert _read_file_result(context, "ok.py") == "x = 1\n"
    assert _read_file_result(context, "ok.py").startswith("error: ok.py")
    with pytest.raises(ModelResponseFailure):
        _read_file_result(context, "ok.py")


def test_refusals_of_different_calls_do_not_escalate(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from dataclasses import replace as replace_context

    from plan_comparison.adapters.ds4 import _read_file_result, _write_file_result

    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n")
    context = replace_context(
        _tool_context(tmp_path, {"a.py", "b.py"}, {"a.py"}), repeat_guard=True
    )
    _read_file_result(context, "a.py")
    _read_file_result(context, "b.py")

    assert _read_file_result(context, "a.py").startswith("error: a.py")
    assert _read_file_result(context, "b.py").startswith("error: b.py")
    assert _read_file_result(context, "a.py").startswith("error: a.py")
    assert _write_file_result(context, "a.py", "x = 2\n") == "Wrote a.py."
    assert _write_file_result(context, "a.py", "x = 2\n").startswith("error: a.py")
    assert _read_file_result(context, "b.py").startswith("error: b.py")
    assert _write_file_result(context, "a.py", "x = 2\n").startswith("error: a.py")


def test_tool_loop_feedback_carries_the_last_visible_gate(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from dataclasses import replace as replace_context

    from plan_comparison.adapters.ds4 import _write_file_result
    from plan_comparison.contracts import GateResult, ModelResponseFailure

    (tmp_path / "ok.py").write_text("x = 1\n")
    gate = GateResult(
        gate_id="visible",
        status="failed",
        exit_code=1,
        timed_out=False,
        duration_seconds=0.1,
        output_excerpt="assert 1 == 2",
        output_truncated=False,
        verified_red_evidence=(),
    )
    context = replace_context(
        _tool_context(tmp_path, set(), {"ok.py"}),
        repeat_guard=True,
        gate_results=[gate],
    )

    _write_file_result(context, "ok.py", "x = 1\n")
    with pytest.raises(ModelResponseFailure) as caught:
        _write_file_result(context, "ok.py", "x = 1\n")
    assert "gate=visible status=failed" in str(caught.value)
    assert "assert 1 == 2" in str(caught.value)


def test_adapter_reports_a_write_loop_as_a_model_response_failure(tmp_path) -> None:
    from ds4py._native.fake import FAKE_EOS

    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits, ModelResponseFailure

    engine, adapter = _fake_adapter(family="qwen", tool_repeat_guard=True)
    write = (
        b"<tool_call><function=write_file><parameter=path>app.py</parameter>"
        b"<parameter=content>x = 1</parameter></function></tool_call>"
    )

    def script(prompt, generated):
        return write[len(generated)] + 1 if len(generated) < len(write) else FAKE_EOS

    engine.native.script = script
    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=30, tokens=100_000, model_calls=20)
    )
    try:
        with pytest.raises(ModelResponseFailure) as caught:
            asyncio.run(
                adapter.execute_prose(
                    task_id="fake",
                    plan="Implement f.",
                    workspace=tmp_path,
                    allowed_read_paths=(),
                    allowed_write_paths=("app.py",),
                    visible_gates=(),
                    visible_feedback=(),
                    budget=budget,
                )
            )
        assert caught.value.reason == "tool_loop"
        assert adapter.refused_tool_repeats == ["write_file:app.py"]
        assert adapter.tool_loops == ["write_file:app.py"]
        assert budget.snapshot().model_calls == 3
        assert not adapter._message_history
    finally:
        engine.close()


def _exit_gate(gate_id: str, code: int):
    import sys

    from typed_packets.contract import Gate, GateExpectation

    from plan_comparison.contracts import VisibleGateSpec

    expectation = GateExpectation(exit_code=0, reason="passes")
    return VisibleGateSpec(
        gate_id=gate_id,
        gate=Gate(
            argv=(sys.executable, "-c", f"raise SystemExit({code})"),
            cwd=".",
            before=expectation,
            after=expectation,
        ),
        expectation=expectation,
    )


def _gate_context(adapter, tmp_path, budget):
    import sys
    from dataclasses import replace as replace_context

    from plan_comparison.gates import GatePolicy

    gates = (_exit_gate("red", 1), _exit_gate("green", 0))
    return replace_context(
        adapter._tool_context(tmp_path, (), ("ok.py",), gates, budget),
        gate_policy=GatePolicy(
            allowed_commands=(sys.executable,),
            environment=(),
            timeout_seconds=30,
            output_limit_bytes=128,
        ),
    )


def test_failed_visible_gate_rearms_thinking_until_the_next_write(tmp_path) -> None:
    from plan_comparison.adapters.ds4 import _visible_gate_result, _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=60, tokens=100_000, model_calls=10)
    )
    engine, adapter = _fake_adapter(
        think_until_first_write=True, rethink_after_failure=True
    )
    try:
        context = _gate_context(adapter, tmp_path, budget)
        _write_file_result(context, "ok.py", "x = 1\n")
        assert adapter._thinking_suppressed

        assert "status=passed" in _visible_gate_result(context, "green")
        assert adapter._thinking_suppressed
        assert "status=failed" in _visible_gate_result(context, "red")
        assert not adapter._thinking_suppressed
        assert adapter.rethinks == ["gate:red"]

        _write_file_result(context, "ok.py", "x = 2\n")
        assert adapter._thinking_suppressed
    finally:
        engine.close()


def test_guard_refusal_rearms_thinking(tmp_path) -> None:
    from plan_comparison.adapters.ds4 import _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=60, tokens=100_000, model_calls=10)
    )
    engine, adapter = _fake_adapter(
        think_until_first_write=True,
        rethink_after_failure=True,
        tool_repeat_guard=True,
    )
    try:
        context = adapter._tool_context(tmp_path, (), ("ok.py",), (), budget)
        _write_file_result(context, "ok.py", "x = 1\n")
        assert _write_file_result(context, "ok.py", "x = 1\n").startswith("error:")
        assert not adapter._thinking_suppressed
        assert adapter.rethinks == ["repeat:write_file:ok.py"]
        assert adapter.refused_tool_repeats == ["write_file:ok.py"]
    finally:
        engine.close()


def test_failures_keep_thinking_suppressed_without_rethink(tmp_path) -> None:
    from plan_comparison.adapters.ds4 import _visible_gate_result, _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=60, tokens=100_000, model_calls=10)
    )
    engine, adapter = _fake_adapter(
        think_until_first_write=True, tool_repeat_guard=True
    )
    try:
        context = _gate_context(adapter, tmp_path, budget)
        _write_file_result(context, "ok.py", "x = 1\n")
        _visible_gate_result(context, "red")
        _write_file_result(context, "ok.py", "x = 1\n")
        assert adapter._thinking_suppressed
        assert adapter.rethinks == []
    finally:
        engine.close()


def test_rethink_requires_thinking_until_first_write() -> None:
    with pytest.raises(ValueError, match="rethink"):
        _fake_adapter(rethink_after_failure=True)


def test_a_gate_call_between_refusals_breaks_the_loop(tmp_path) -> None:
    from plan_comparison.adapters.ds4 import _visible_gate_result, _write_file_result
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits

    budget = MonotonicBudget(
        BudgetLimits(wall_seconds=60, tokens=100_000, model_calls=10)
    )
    engine, adapter = _fake_adapter(tool_repeat_guard=True)
    try:
        context = _gate_context(adapter, tmp_path, budget)
        _write_file_result(context, "ok.py", "x = 1\n")
        assert _write_file_result(context, "ok.py", "x = 1\n").startswith("error:")
        _visible_gate_result(context, "green")
        assert _write_file_result(context, "ok.py", "x = 1\n").startswith("error:")
        assert adapter.tool_loops == []
    finally:
        engine.close()


def test_prompts_name_the_files_the_worker_may_use() -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    from plan_comparison.adapters.ds4 import _paths_prompt

    text = _paths_prompt(("app/a.py", "task.md"), ("app/a.py",))

    assert "Readable files:" in text
    assert "task.md" in text
    assert "Writable files:" in text


def test_boundary_capture_reads_engine_events_from_session_envelopes(tmp_path) -> None:
    pytest.importorskip("ds4py")
    pytest.importorskip("pydantic_ai")
    import ds4py
    from ds4py import ThinkMode
    from ds4py._native.fake import FakeNative, reply
    from ds4py.engine.sampling import SamplingPolicy
    from ds4py.model import DS4Model

    from plan_comparison.adapters.ds4 import (
        Ds4WorkerAdapter,
        build_restricted_agents,
    )
    from plan_comparison.budget import MonotonicBudget
    from plan_comparison.contracts import BudgetLimits
    from plan_comparison.gates import GatePolicy

    with ds4py.open(
        "fake.gguf",
        ctx=8192,
        think=ThinkMode.NONE,
        native=FakeNative(script=reply(b"done")),
    ) as engine:
        model = DS4Model(engine.session(), sampling=SamplingPolicy(seed=5))
        policy = GatePolicy(
            allowed_commands=("pytest",),
            environment=(),
            timeout_seconds=1,
            output_limit_bytes=128,
        )
        adapter = Ds4WorkerAdapter(
            model=model,
            agents=build_restricted_agents(model, policy),
            model_id="fake-ds4",
            model_revision="fake-revision",
            runtime_revision="fake-runtime",
            tokenizer_revision="fake-tokenizer",
            gate_policy=policy,
        )
        budget = MonotonicBudget(
            BudgetLimits(wall_seconds=10, tokens=10_000, model_calls=10)
        )

        boundary = asyncio.run(
            adapter.capture_boundary(
                task_id="fake",
                plan="Summarize nothing.",
                workspace=tmp_path,
                allowed_read_paths=(),
                budget=budget,
            )
        )

        assert boundary.evidence.token_count > 0
        assert budget.snapshot().model_calls == 1
        assert budget.snapshot().tokens > 0
