import pytest
from ds4py import EngineError

import satyrn_agent
from satyrn_agent._native import CtypesDFlashNative
from satyrn_agent.config import DFlashMode, SatyrnConfig
from satyrn_agent.dflash import DFlashMetrics, DFlashStep, Recorder
from satyrn_agent.errors import DFlashError
from tests.e2e.model_free._native import ScenarioFakeNative


def test_dflash_steps_share_only_an_explicit_recorder() -> None:
    native = ScenarioFakeNative({"script": [10], "calls": []})
    adapter = CtypesDFlashNative(native)
    recorder = Recorder()
    first = DFlashStep(adapter, recorder=recorder)
    second = DFlashStep(adapter, recorder=recorder)
    independent = DFlashStep(adapter)

    recorder.committed(4, 3, replacement=True, discarded=1)

    expected = DFlashMetrics(
        committed_blocks=1,
        drafts_offered=4,
        drafts_accepted=3,
        replacement_anchors=1,
        discarded_tails=1,
    )
    assert first.metrics == expected
    assert second.metrics == expected
    assert independent.metrics == DFlashMetrics()


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


def test_failed_session_setup_closes_wrapper() -> None:
    native = ScenarioFakeNative(
        {
            "script": [10],
            "calls": [{"op": "sampling_defaults", "values": [1, 0, 1, 0], "nonfinite": True}],
        }
    )
    wrapper = satyrn_agent.open("scenario.gguf", config=SatyrnConfig(dflash=DFlashMode.OFF), native=native)

    with pytest.raises(DFlashError, match="invalid sampling defaults"):
        wrapper.session()

    with pytest.raises(EngineError, match="engine is closed"):
        wrapper.session()


def test_close_failure_does_not_replace_session_setup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = ScenarioFakeNative(
        {
            "script": [10],
            "calls": [{"op": "sampling_defaults", "values": [1, 0, 1, 0], "nonfinite": True}],
        }
    )
    wrapper = satyrn_agent.open("scenario.gguf", config=SatyrnConfig(dflash=DFlashMode.OFF), native=native)

    def fail_close() -> None:
        raise RuntimeError("close injected")

    monkeypatch.setattr(wrapper._engine, "close", fail_close)
    with pytest.raises(DFlashError, match="invalid sampling defaults") as caught:
        wrapper.session()

    assert caught.value.__notes__ == [
        "Satyrn engine close failed after session setup error: RuntimeError: close injected"
    ]
