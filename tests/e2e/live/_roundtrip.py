"""Exercise one exact built library in an isolated native-loader process."""

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from satyrn_agent.config import SatyrnConfig
from tests.conftest import LiveSettings, assert_alignment, configured_session, observe_round, prepare_chat


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--drafter", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = LiveSettings(args.model, args.drafter, args.lib, None)
    config = SatyrnConfig(drafter_path=settings.drafter)
    with configured_session(settings, config) as (wrapper, session):
        assert wrapper.dflash_metrics is not None
        for prompt in ("Say hello briefly.", "Say goodbye briefly."):
            prepare_chat(session, prompt)
            observation = observe_round(session, max_tokens=16, started=time.perf_counter())
            assert_alignment(session, observation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
