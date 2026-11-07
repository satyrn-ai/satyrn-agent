"""Merge family, native, and explicit sampling defaults before generation."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ds4py.engine.sampling import SamplingPolicy

    from satyrn_agent._native import NativeSampling
    from satyrn_agent.config import SamplingOverrides


def merge_sampling(
    base: SamplingPolicy,
    native: NativeSampling | None,
    overrides: SamplingOverrides,
    seed: int | None,
) -> SamplingPolicy:
    """Return defaults without treating an explicit zero as missing."""
    merged = base
    if native is not None:
        merged = replace(
            merged,
            temperature=native.temperature,
            top_k=native.top_k,
            top_p=native.top_p,
            min_p=native.min_p,
        )
    return replace(
        merged,
        temperature=merged.temperature if overrides.temperature is None else overrides.temperature,
        top_k=merged.top_k if overrides.top_k is None else overrides.top_k,
        top_p=merged.top_p if overrides.top_p is None else overrides.top_p,
        min_p=merged.min_p if overrides.min_p is None else overrides.min_p,
        seed=merged.seed if seed is None else seed,
    )
