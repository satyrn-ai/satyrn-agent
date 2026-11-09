import json
import platform
from pathlib import Path

import pytest
from ds4py.engine.sampling import SamplingPolicy

from satyrn_agent.config import SamplingOverrides, SatyrnConfig
from tests.conftest import LiveSettings, assert_alignment, configured_session, serial_then_speculative
from tests.e2e.corpus import CorpusCase, corpus_cases, require_branches

pytestmark = pytest.mark.live


def _config(settings: LiveSettings, case: CorpusCase) -> SatyrnConfig:
    return SatyrnConfig(
        drafter_path=settings.drafter,
        draft_tokens=case.get("draft_tokens", 0),
        sampling=SamplingOverrides(temperature=case["temperature"]),
    )


def _policy(case: CorpusCase) -> SamplingPolicy:
    return SamplingPolicy(
        temperature=case["temperature"],
        top_k=0 if case["temperature"] == 0 else 20,
        top_p=1.0 if case["temperature"] == 0 else 0.95,
        min_p=0.0,
        seed=case["seed"],
    )


def test_metrics_reconcile_with_committed_stream(live_settings: LiveSettings) -> None:
    cases = corpus_cases()
    case = cases["greedy-parity"]
    config = _config(live_settings, case)

    with configured_session(live_settings, config, seed=case["seed"]) as (wrapper, session):
        _, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            case["prompt"],
            max_tokens=case["max_tokens"],
            sampling=_policy(case),
        )
        metrics = wrapper.dflash_metrics
        assert_alignment(session, speculative)

    assert metrics is not None
    assert metrics.committed_blocks > 0
    assert 0 <= metrics.drafts_accepted <= metrics.drafts_offered
    assert metrics.discarded_tails == metrics.drafts_offered - metrics.drafts_accepted
    assert metrics.acceptance_rate == pytest.approx(metrics.drafts_accepted / metrics.drafts_offered)
    assert len(speculative.token_ids) == metrics.committed_blocks + metrics.drafts_accepted
    reached = {"anchor", "native-commit-publication"}
    if metrics.drafts_accepted > 0:
        reached.add("matching-draft")
    if metrics.drafts_accepted < metrics.drafts_offered:
        reached.add("partial-acceptance")
    if metrics.replacement_anchors > 0:
        reached.update({"mismatch-or-bonus", "mismatch-replacement"})
    require_branches(case, reached)

    full_case = cases["full-acceptance"]
    full_config = _config(live_settings, full_case)
    with configured_session(live_settings, full_config, seed=full_case["seed"]) as (wrapper, session):
        _, full, _ = serial_then_speculative(
            wrapper,
            session,
            full_case["prompt"],
            max_tokens=full_case["max_tokens"],
            sampling=_policy(full_case),
        )
        full_metrics = wrapper.dflash_metrics
        assert_alignment(session, full)

    assert full_metrics is not None
    assert len(full.token_ids) == full_metrics.committed_blocks + full_metrics.drafts_accepted
    full_reached = set()
    if full_metrics.committed_blocks > 0:
        full_reached.add("native-commit-publication")
    if full_metrics.drafts_offered > 0 and full_metrics.drafts_accepted == full_metrics.drafts_offered:
        full_reached.add("full-acceptance")
    require_branches(full_case, full_reached)

    partial_case = cases["partial-acceptance"]
    partial_config = _config(live_settings, partial_case)
    with configured_session(live_settings, partial_config, seed=partial_case["seed"]) as (wrapper, session):
        _, partial, _ = serial_then_speculative(
            wrapper,
            session,
            partial_case["prompt"],
            max_tokens=partial_case["max_tokens"],
            sampling=_policy(partial_case),
        )
        partial_metrics = wrapper.dflash_metrics
        assert_alignment(session, partial)

    assert partial_metrics is not None
    assert len(partial.token_ids) == partial_metrics.committed_blocks + partial_metrics.drafts_accepted
    assert partial_metrics.committed_blocks == 1
    assert partial_metrics.drafts_offered == 2
    assert partial_metrics.drafts_accepted == 1
    require_branches(partial_case, {"native-commit-publication", "partial-acceptance"})


def test_external_serial_speculative_timing_metadata(live_settings: LiveSettings, tmp_path: Path) -> None:
    case = corpus_cases()["external-timing"]
    config = _config(live_settings, case)

    with configured_session(live_settings, config, seed=case["seed"]) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            case["prompt"],
            max_tokens=case["max_tokens"],
            sampling=_policy(case),
        )
        metrics = wrapper.dflash_metrics
        assert_alignment(session, speculative)

    evidence = {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "backend": "metal",
        "model": str(live_settings.model),
        "drafter": str(live_settings.drafter),
        "serial_seconds": serial.wall_seconds,
        "speculative_seconds": speculative.wall_seconds,
        "serial_tokens": len(serial.token_ids),
        "speculative_tokens": len(speculative.token_ids),
        "drafts_offered": metrics.drafts_offered if metrics is not None else None,
        "drafts_accepted": metrics.drafts_accepted if metrics is not None else None,
        "replacement_anchors": metrics.replacement_anchors if metrics is not None else None,
        "acceptance_rate": metrics.acceptance_rate if metrics is not None else None,
    }
    rendered = json.dumps(evidence, indent=2) + "\n"
    (tmp_path / "timing.json").write_text(rendered)
    print(f"timing.json:\n{rendered}", end="")
    assert serial.wall_seconds > 0
    assert speculative.wall_seconds > 0
    assert metrics is not None
    assert len(speculative.token_ids) == metrics.committed_blocks + metrics.drafts_accepted
    reached = {"external-timing"}
    if metrics.drafts_accepted < metrics.drafts_offered:
        reached.add("partial-acceptance")
    if metrics.replacement_anchors > 0:
        reached.add("mismatch-replacement")
    require_branches(case, reached)
