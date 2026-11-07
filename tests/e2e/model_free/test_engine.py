from pathlib import Path

import pytest
from ds4py import EngineError
from ds4py.engine.sampling import SamplingPolicy

import satyrn_agent
from satyrn_agent.config import DFlashMode, SatyrnConfig
from tests.conftest import MetadataRecorder, normalized_events, serial_then_speculative
from tests.e2e.model_free._native import ScenarioFakeNative


def test_first_only_session_close_and_closed_error() -> None:
    native = ScenarioFakeNative({"script": [10], "calls": []})
    wrapper = satyrn_agent.open("scenario.gguf", config=SatyrnConfig(dflash=DFlashMode.OFF), native=native)
    wrapper.session()

    with pytest.raises(EngineError, match="one session per engine"):
        wrapper.session()

    wrapper.close()
    wrapper.close()
    with pytest.raises(EngineError, match="engine is closed"):
        wrapper.session()


def test_snapshot_serial_speculative_parity() -> None:
    native = ScenarioFakeNative({"script": [10, 11, 12], "calls": [{"op": "draft", "tokens": [11]}]})
    recorder = MetadataRecorder()

    with satyrn_agent.open(
        "scenario.gguf",
        config=SatyrnConfig(drafter_path=Path("drafter.gguf")),
        native=native,
        seed=1,
    ) as wrapper:
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            wrapper.session(),
            "Check speculative parity.",
            max_tokens=3,
            sampling=SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=1),
            recorder=recorder,
            scripted_native=native,
        )

    assert speculative.token_ids == serial.token_ids
    assert speculative.reason == serial.reason
    assert speculative.rng == serial.rng
    assert normalized_events(speculative.events) == normalized_events(serial.events)
    assert recorder.speculative == recorder.serial
