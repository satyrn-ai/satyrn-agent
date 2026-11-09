"""Optional DS4 adapter checks; all cases use the upstream FakeNative engine."""

import asyncio
from inspect import signature

import pytest

pytestmark = pytest.mark.ds4_runtime


def _fake_adapter(*, thinking_budget: int | None = None):
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
    boundary = adapter._capture_boundary()
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
