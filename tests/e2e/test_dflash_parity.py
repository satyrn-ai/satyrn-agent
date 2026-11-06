import pytest
from ds4py.engine.sampling import SamplingPolicy
from ds4py.engine.tool_prompt import ToolDefinition

from satyrn_agent.config import SatyrnConfig, ThinkBudgetConfig
from tests.conftest import (
    LiveSettings,
    MetadataRecorder,
    configured_session,
    normalized_events,
    serial_then_speculative,
)

pytestmark = pytest.mark.live


@pytest.mark.parametrize(
    ("prompt", "seed", "sampling"),
    [
        (
            "Explain speculative decoding in two concise sentences.",
            1,
            SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=1),
        ),
        (
            "List three properties of a reliable token transaction.",
            7,
            SamplingPolicy(temperature=0.6, top_k=20, top_p=0.95, min_p=0.0, seed=7),
        ),
    ],
)
def test_serial_and_speculative_parity_from_one_dflash_snapshot(
    live_settings: LiveSettings,
    prompt: str,
    seed: int,
    sampling: SamplingPolicy,
) -> None:
    config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        think_budget=ThinkBudgetConfig(max_tokens=2, bias=2.0),
    )
    recorder = MetadataRecorder()

    with configured_session(live_settings, config, seed=seed) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            prompt,
            max_tokens=40,
            sampling=sampling,
            recorder=recorder,
        )

    assert speculative.token_ids == serial.token_ids
    assert speculative.reason == serial.reason
    assert speculative.rng == serial.rng
    assert normalized_events(speculative.events) == normalized_events(serial.events)
    assert recorder.speculative == recorder.serial
    assert recorder.serial


def test_tool_opener_has_exact_tentative_metadata_and_event_parity(live_settings: LiveSettings) -> None:
    definition = ToolDefinition(
        "get_weather",
        "Return weather for one city.",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )
    config = SatyrnConfig(drafter_path=live_settings.drafter)
    recorder = MetadataRecorder()

    with configured_session(live_settings, config, seed=3) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            "Call the weather tool for Tokyo, then stop after the tool call.",
            max_tokens=64,
            sampling=SamplingPolicy(temperature=0.0, top_k=0, top_p=1.0, min_p=0.0, seed=3),
            tools=[definition],
            recorder=recorder,
        )

    assert speculative.token_ids == serial.token_ids
    assert speculative.reason == "tool_call_complete"
    assert normalized_events(speculative.events) == normalized_events(serial.events)
    assert recorder.speculative == recorder.serial
    assert any(call.parser_state is not None for call in recorder.serial)
