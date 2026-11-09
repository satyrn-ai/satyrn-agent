import json
import platform
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.conftest import LiveSettings, assert_alignment, assert_output, configured_session, serial_then_speculative
from tests.e2e.corpus import corpus_cases, corpus_config, corpus_sampling, metric_branches, require_branches

pytestmark = pytest.mark.live

EXPECTED = Path(__file__).with_name("expected")


@pytest.mark.parametrize("case_name", ["greedy-parity", "full-acceptance", "partial-acceptance"])
def test_metrics_reconcile_with_committed_stream(live_settings: LiveSettings, case_name: str) -> None:
    case = corpus_cases()[case_name]
    with configured_session(live_settings, corpus_config(live_settings, case), seed=case["seed"]) as (wrapper, session):
        _, result, _ = serial_then_speculative(
            wrapper,
            session,
            case["prompt"],
            max_tokens=case["max_tokens"],
            sampling=corpus_sampling(case),
        )
        metrics = wrapper.dflash_metrics
        assert_alignment(session, result)

    assert metrics is not None
    assert len(result.token_ids) == metrics.committed_blocks + metrics.drafts_accepted
    assert metrics.discarded_tails == metrics.drafts_offered - metrics.drafts_accepted
    assert metrics.acceptance_rate == pytest.approx(metrics.drafts_accepted / metrics.drafts_offered)
    assert_output(asdict(metrics), EXPECTED / f"{case_name}.json")
    require_branches(case, metric_branches(metrics))


def test_external_serial_speculative_timing_metadata(live_settings: LiveSettings, tmp_path: Path) -> None:
    case = corpus_cases()["external-timing"]
    with configured_session(live_settings, corpus_config(live_settings, case), seed=case["seed"]) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            case["prompt"],
            max_tokens=case["max_tokens"],
            sampling=corpus_sampling(case),
        )
        metrics = wrapper.dflash_metrics
        assert_alignment(session, speculative)

    assert metrics is not None
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
        "drafts_offered": metrics.drafts_offered,
        "drafts_accepted": metrics.drafts_accepted,
        "replacement_anchors": metrics.replacement_anchors,
        "acceptance_rate": metrics.acceptance_rate,
    }
    rendered = json.dumps(evidence, indent=2) + "\n"
    (tmp_path / "timing.json").write_text(rendered)
    print(f"timing.json:\n{rendered}", end="")
    assert serial.wall_seconds > 0
    assert speculative.wall_seconds > 0
    require_branches(case, metric_branches(metrics) | {"external-timing"})
