import pytest
from ds4py import EngineError

import satyrn_agent
from satyrn_agent.config import DFlashMode, SatyrnConfig
from satyrn_agent.errors import DFlashError
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
