from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from ds4py import Session, agent_cli
from ds4py.engine.events import Token
from ds4py.engine.lifecycle import SessionEvent
from ds4py.runtime import AgentRuntime
from pydantic_ai.messages import FunctionToolResultEvent, PartEndEvent, ThinkingPart

import satyrn_agent
from satyrn_agent.cli import SatyrnAgentExtension
from satyrn_agent.dflash import DFlashStep
from tests.conftest import LiveSettings

pytestmark = pytest.mark.live


def _assistant_tokens(session: Session) -> tuple[int, ...]:
    transcript = session.transcript
    return tuple(
        token
        for segment in transcript.segments
        if segment.kind == "assistant"
        for token in transcript.tokens[segment.start : segment.end]
    )


def _assert_alignment(session: Session, generated: tuple[int, ...], assistant_start: int) -> None:
    transcript = session.transcript
    assert _assistant_tokens(session)[assistant_start:] == generated
    segments = transcript.segments
    trailing_eos = segments[-1].end - segments[-1].start if segments and segments[-1].kind == "eos" else 0
    assert session.ctx_used == len(transcript.tokens) - trailing_eos


def _thinking_text(events: list[SessionEvent]) -> str:
    return "".join(
        inner.part.content
        for event in events
        if event.kind == "agent_event"
        and isinstance((inner := event.payload["event"]), PartEndEvent)
        and isinstance(inner.part, ThinkingPart)
    )


def _write_result_index(events: list[SessionEvent]) -> int:
    for index, event in enumerate(events):
        if event.kind != "agent_event":
            continue
        inner = event.payload["event"]
        if (
            isinstance(inner, FunctionToolResultEvent)
            and inner.part.tool_name == "write_file"
            and getattr(inner.part, "outcome", None) == "success"
        ):
            return index
    raise AssertionError("the real model did not complete a write_file call")


@contextmanager
def _open_runtime(
    live_settings: LiveSettings,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    until_first_write: bool,
) -> Generator[tuple[AgentRuntime, satyrn_agent.SatyrnEngine]]:
    monkeypatch.setenv("DS4PY_HOME", str(project / "home"))
    monkeypatch.chdir(project)
    wrappers: list[satyrn_agent.SatyrnEngine] = []

    def open_engine(model: str | Path = "ds4flash.gguf", **kwargs: Any) -> satyrn_agent.SatyrnEngine:
        wrapper = satyrn_agent.open(model, **kwargs)
        wrappers.append(wrapper)
        return wrapper

    extension = SatyrnAgentExtension(open_engine=open_engine)
    argv = [
        "--model",
        str(live_settings.model),
        "--lib",
        str(live_settings.lib),
        "--metal",
        "--dflash",
        "on",
        "--drafter",
        str(live_settings.drafter),
        "--temp",
        "0",
        "--top-k",
        "0",
        "--top-p",
        "1",
        "--min-p",
        "0",
        "--seed",
        "1",
        "--think",
        "low",
        "--tokens",
        "768",
        "--request-limit",
        "8",
        "--think-budget",
        "4096",
        *(["--think-until-first-write"] if until_first_write else []),
    ]
    args = agent_cli.parser(extension).parse_args(argv)
    extension_config = extension.resolve_extension_config(args, project)
    with agent_cli.open_runtime(
        args, project, read_only=False, extension=extension, extension_config=extension_config
    ) as runtime:
        yield runtime, wrappers[0]


def test_real_first_write_closes_later_thoughts_and_next_run_resets(
    live_settings: LiveSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = {}
    for enabled in (False, True):
        project = tmp_path / ("enabled" if enabled else "disabled")
        project.mkdir()
        with _open_runtime(live_settings, project, monkeypatch, until_first_write=enabled) as (runtime, wrapper):
            events: list[SessionEvent] = []
            runtime.on_event(events.append)
            assistant_start = len(_assistant_tokens(runtime.model.session))
            before = wrapper.controller.state.recorder.snapshot()
            asyncio.run(
                runtime.run(
                    "Use write_file to create result.txt with exactly the content 'satyrn first write'. "
                    "After the write, verify the result and explain the verification."
                )
            )
            assert (project / "result.txt").read_text() == "satyrn first write"
            result_index = _write_result_index(events)
            before_write = _thinking_text(events[:result_index])
            after_write = _thinking_text(events[result_index:])
            generated = tuple(
                event.payload["event"].id
                for event in events
                if event.kind == "Token" and isinstance(event.payload["event"], Token)
            )
            _assert_alignment(runtime.model.session, generated, assistant_start)
            after = wrapper.controller.state.recorder.snapshot()
            assert isinstance(wrapper.controller.state.step, DFlashStep)
            assert len(generated) == (
                after.committed_blocks - before.committed_blocks + after.drafts_accepted - before.drafts_accepted
            )
            assert before_write
            if enabled:
                assert after_write == ""
            else:
                assert after_write

            events.clear()
            assistant_start = len(_assistant_tokens(runtime.model.session))
            before = wrapper.controller.state.recorder.snapshot()
            asyncio.run(
                runtime.run(
                    "Without using tools, think briefly about whether result.txt exists, then answer with one sentence."
                )
            )
            next_run_thinking = _thinking_text(events)
            assert next_run_thinking
            generated = tuple(
                event.payload["event"].id
                for event in events
                if event.kind == "Token" and isinstance(event.payload["event"], Token)
            )
            _assert_alignment(runtime.model.session, generated, assistant_start)
            after = wrapper.controller.state.recorder.snapshot()
            assert len(generated) == (
                after.committed_blocks - before.committed_blocks + after.drafts_accepted - before.drafts_accepted
            )
            evidence[enabled] = (
                len(runtime.model.session.engine.tokenize(before_write)),
                len(runtime.model.session.engine.tokenize(after_write)),
                len(runtime.model.session.engine.tokenize(next_run_thinking)),
            )

    print(
        f"first-write thinking tokens: off before/after/next={evidence[False]}, on before/after/next={evidence[True]}"
    )
