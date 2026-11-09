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
from tests.e2e.corpus import corpus_cases, require_branches

pytestmark = pytest.mark.live


@pytest.mark.parametrize("case_name", ["greedy-parity", "seeded-parity"])
def test_serial_and_speculative_parity_from_one_dflash_snapshot(
    live_settings: LiveSettings,
    case_name: str,
) -> None:
    case = corpus_cases()[case_name]
    sampling = SamplingPolicy(
        temperature=case["temperature"],
        top_k=0 if case["temperature"] == 0 else 20,
        top_p=1.0 if case["temperature"] == 0 else 0.95,
        min_p=0.0,
        seed=case["seed"],
    )
    config = SatyrnConfig(
        drafter_path=live_settings.drafter,
        think_budget=ThinkBudgetConfig(max_tokens=2, bias=2.0),
    )
    recorder = MetadataRecorder()

    with configured_session(live_settings, config, seed=case["seed"]) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            case["prompt"],
            max_tokens=case["max_tokens"],
            sampling=sampling,
            recorder=recorder,
        )
        metrics = wrapper.dflash_metrics

    assert speculative.token_ids == serial.token_ids
    assert speculative.reason == serial.reason
    assert speculative.rng == serial.rng
    assert normalized_events(speculative.events) == normalized_events(serial.events)
    assert recorder.speculative == recorder.serial
    assert recorder.serial
    assert metrics is not None
    reached = {"anchor", "native-commit-publication"}
    if metrics.drafts_accepted > 0:
        reached.add("matching-draft")
    if metrics.drafts_accepted < metrics.drafts_offered:
        reached.add("partial-acceptance")
    if metrics.replacement_anchors > 0:
        reached.update({"mismatch-or-bonus", "mismatch-replacement"})
    if speculative.rng == serial.rng:
        reached.add("seeded-rng-continuation")
    if recorder.speculative == recorder.serial:
        reached.add("canonical-plus-staged-sampling")
    require_branches(case, reached)


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
