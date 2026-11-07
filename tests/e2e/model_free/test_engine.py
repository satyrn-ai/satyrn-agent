import pytest
from ds4py import EngineError

import satyrn_agent
from satyrn_agent.config import DFlashMode, SatyrnConfig
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
