from ds4py.engine.sampling import SamplingPolicy

from satyrn_agent._native import NativeSampling
from satyrn_agent.capabilities.sampling import merge_sampling
from satyrn_agent.config import SamplingOverrides


def test_native_defaults_override_family_defaults_and_seed_wins() -> None:
    base = SamplingPolicy(temperature=1.0, top_k=0, top_p=1.0, min_p=0.05, seed=11)
    native = NativeSampling(temperature=0.6, top_k=20, top_p=0.95, min_p=0.0)

    merged = merge_sampling(base, native, SamplingOverrides(), 22)

    assert merged == SamplingPolicy(temperature=0.6, top_k=20, top_p=0.95, min_p=0.0, seed=22)


def test_explicit_overrides_override_native_including_zero() -> None:
    base = SamplingPolicy(seed=11)
    native = NativeSampling(temperature=0.6, top_k=20, top_p=0.95, min_p=0.1)
    overrides = SamplingOverrides(temperature=0.0, top_k=0, top_p=0.0, min_p=0.0)

    merged = merge_sampling(base, native, overrides, None)

    assert merged == SamplingPolicy(temperature=0.0, top_k=0, top_p=0.0, min_p=0.0, seed=11)


def test_absent_native_defaults_preserve_base() -> None:
    base = SamplingPolicy(temperature=0.7, top_k=30, top_p=0.9, min_p=0.02, seed=11)

    assert merge_sampling(base, None, SamplingOverrides(), None) == base


def test_explicit_overrides_apply_without_native_defaults() -> None:
    base = SamplingPolicy(temperature=0.7, top_k=30, top_p=0.9, min_p=0.02, seed=11)

    merged = merge_sampling(base, None, SamplingOverrides(top_k=40), None)

    assert merged == SamplingPolicy(temperature=0.7, top_k=40, top_p=0.9, min_p=0.02, seed=11)
