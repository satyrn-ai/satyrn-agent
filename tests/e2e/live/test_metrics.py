import json
import platform
from pathlib import Path

import pytest
from ds4py.engine.sampling import SamplingPolicy

from satyrn_agent.config import SatyrnConfig
from tests.conftest import LiveSettings, configured_session, serial_then_speculative

pytestmark = pytest.mark.live


def test_metrics_reconcile_with_committed_stream(live_settings: LiveSettings) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (wrapper, session):
        _, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            "List three properties of a reliable token transaction.",
            max_tokens=48,
            sampling=SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=1),
        )
        metrics = wrapper.dflash_metrics

    assert metrics is not None
    assert metrics.committed_blocks > 0
    assert 0 <= metrics.drafts_accepted <= metrics.drafts_offered
    assert metrics.discarded_tails == metrics.drafts_offered - metrics.drafts_accepted
    assert metrics.acceptance_rate == pytest.approx(metrics.drafts_accepted / metrics.drafts_offered)
    assert speculative.native_position == len(speculative.transcript)


def test_external_serial_speculative_timing_metadata(live_settings: LiveSettings, tmp_path: Path) -> None:
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            "Explain speculative decoding in two concise sentences.",
            max_tokens=48,
            sampling=SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=1),
        )
        metrics = wrapper.dflash_metrics

    evidence = {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "backend": "metal",
        "model": str(live_settings.model),
        "drafter": str(live_settings.drafter),
        "serial_seconds": serial.wall_seconds,
        "speculative_seconds": speculative.wall_seconds,
        "acceptance_rate": metrics.acceptance_rate if metrics is not None else None,
    }
    (tmp_path / "timing.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert serial.wall_seconds > 0
    assert speculative.wall_seconds > 0
