import pytest
from ds4py.engine.sampling import SamplingPolicy

from satyrn_agent.config import SatyrnConfig
from tests.conftest import LiveSettings, configured_session, serial_then_speculative

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
    config = SatyrnConfig(drafter_path=live_settings.drafter)

    with configured_session(live_settings, config, seed=seed) as (wrapper, session):
        serial, speculative, _ = serial_then_speculative(
            wrapper,
            session,
            prompt,
            max_tokens=40,
            sampling=sampling,
        )

    assert speculative.token_ids == serial.token_ids
    assert speculative.reason == serial.reason
    assert speculative.rng == serial.rng
    assert [type(event) for event in speculative.events] == [type(event) for event in serial.events]
