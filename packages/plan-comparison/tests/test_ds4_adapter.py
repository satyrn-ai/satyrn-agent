"""Optional DS4 adapter checks; all cases use the upstream FakeNative engine."""

import asyncio

import pytest

pytestmark = pytest.mark.ds4_runtime


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
