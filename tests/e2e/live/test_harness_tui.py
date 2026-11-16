from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from ds4py import Session, agent_cli
from ds4py.engine.decode import PlainStep
from ds4py.engine.events import Token
from ds4py.tui import TUI
from prompt_toolkit.output import DummyOutput
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent

import satyrn_agent
from satyrn_agent.cli import SatyrnAgentExtension
from satyrn_agent.dflash import DFlashMetrics, DFlashStep
from tests.conftest import LiveSettings
from tests.e2e.corpus import corpus_cases

pytestmark = pytest.mark.live


@dataclass(frozen=True)
class RoundEvidence:
    tokens: tuple[int, ...]
    before: DFlashMetrics
    after: DFlashMetrics
    dflash: bool


def _assistant_tokens(session: Session) -> tuple[int, ...]:
    transcript = session.transcript
    return tuple(
        token
        for segment in transcript.segments
        if segment.kind == "assistant"
        for token in transcript.tokens[segment.start : segment.end]
    )


def _assert_native_alignment(session: Session, generated: tuple[int, ...], assistant_start: int) -> None:
    transcript = session.transcript
    assistant = _assistant_tokens(session)
    assert assistant[assistant_start:] == generated
    segments = transcript.segments
    trailing_eos = segments[-1].end - segments[-1].start if segments and segments[-1].kind == "eos" else 0
    assert session.ctx_used == len(transcript.tokens) - trailing_eos


def test_real_metal_satyrn_harness_tui(
    live_settings: LiveSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("Satyrn M3 live harness identifying text\n")
    (project / "pyproject.toml").write_text('[tool.satyrn]\ndflash = "off"\n')
    monkeypatch.setenv("DS4PY_HOME", str(tmp_path / "home"))
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
        "--tokens",
        "32",
        "--think-budget",
        "64",
        "--think-bias",
        "2",
        "--read-only",
    ]
    args = agent_cli.parser(extension).parse_args(argv)
    extension_config = extension.resolve_extension_config(args, project)
    corpus = corpus_cases()

    with agent_cli.open_runtime(
        args,
        project,
        read_only=True,
        extension=extension,
        extension_config=extension_config,
    ) as runtime:
        tui = TUI(runtime, output=DummyOutput(), configure_commands=extension.configure_commands)
        assert len(wrappers) == 1
        controller = wrappers[0].controller
        events = []
        messages: list[str] = []
        runtime.on_event(events.append)
        monkeypatch.setattr(tui, "show_message", messages.append)
        rounds: list[RoundEvidence] = []
        tool_calls = 0
        tool_results = 0

        async def scenario() -> None:
            nonlocal tool_calls, tool_results

            async def command(line: str) -> str:
                start = len(messages)
                await tui.dispatch(line)
                feedback = messages[start:]
                assert not any(item.startswith("error:") for item in feedback), (line, feedback)
                return feedback[-1] if feedback else ""

            async def prompt(text: str, *, max_tokens: int) -> RoundEvidence:
                start = len(events)
                assistant_start = len(_assistant_tokens(runtime.model.session))
                before = controller.state.recorder.snapshot()
                dflash = isinstance(controller.state.step, DFlashStep)
                runtime.model.max_tokens = max_tokens
                await tui.dispatch(text)
                assert not any(item.startswith("error:") for item in messages), (text, messages)
                current = events[start:]
                generated = tuple(
                    event.payload["event"].id
                    for event in current
                    if event.kind == "Token" and isinstance(event.payload["event"], Token)
                )
                assert generated
                _assert_native_alignment(runtime.model.session, generated, assistant_start)
                after = controller.state.recorder.snapshot()
                if dflash:
                    assert isinstance(controller.state.step, DFlashStep)
                    assert len(generated) == (
                        after.committed_blocks
                        - before.committed_blocks
                        + after.drafts_accepted
                        - before.drafts_accepted
                    )
                else:
                    assert isinstance(controller.state.step, PlainStep)
                    assert after == before
                assert tui.footer.custom["dflash"] == controller.status_text()
                evidence = RoundEvidence(generated, before, after, dflash)
                rounds.append(evidence)
                return evidence

            assert tui.footer.custom["dflash"] == "dflash: on, accept — (0/0)"
            first = await prompt(corpus["greedy-parity"]["prompt"], max_tokens=256)
            assert first.after.drafts_offered > 0
            assert first.after.drafts_accepted > 0

            tool_start = len(events)
            await prompt(
                "Use the read_file tool on README.md now, then report its identifying text. Do not answer from memory.",
                max_tokens=256,
            )
            tool_events = [event.payload["event"] for event in events[tool_start:] if event.kind == "agent_event"]
            tool_calls = sum(isinstance(event, FunctionToolCallEvent) for event in tool_events)
            tool_results = sum(isinstance(event, FunctionToolResultEvent) for event in tool_events)
            assert tool_calls > 0
            assert tool_results > 0
            await prompt("Which file did you just read, and what identifying text did it contain?", max_tokens=256)

            assert await command("/think-budget 2 32") == "think budget 2 tokens, bias 32.0"
            assert await command("/think-budget") == "think budget 2 tokens, bias 32.0"
            await prompt(corpus["think-budget"]["prompt"], max_tokens=256)
            assert await command("/think-budget 256 2") == "think budget 256 tokens, bias 2.0"
            assert await command("/think-budget off") == "think budget off"
            assert await command("/think-budget") == "think budget off"
            await prompt("Give one concise sentence about durable agent state.", max_tokens=256)

            await command("/dflash off")
            assert tui.footer.custom["dflash"].startswith("dflash: off,")
            await prompt("Give one concise sentence about ordinary decoding.", max_tokens=256)
            await command("/dflash on")
            assert tui.footer.custom["dflash"].startswith("dflash: on,")
            resumed_before = controller.state.recorder.snapshot()
            await prompt("Give one concise sentence about speculative decoding.", max_tokens=256)
            resumed_after = controller.state.recorder.snapshot()
            assert resumed_after.drafts_offered > resumed_before.drafts_offered

            saved_text = await command("/save")
            saved_id = saved_text.split()[1]
            saved_messages = runtime.messages
            saved_record = runtime.store.read_record(runtime.store.session_dir(saved_id) / "save.json")
            assert saved_record.payload_bytes > 0
            await command("/new")
            assert tui.footer.custom["dflash"] == "dflash: on, accept — (0/0)"
            assert await command("/think-budget") == "think budget 64 tokens, bias 2.0"
            await command(f"/switch {saved_id}")
            assert runtime.messages == saved_messages
            assert tui.footer.custom["dflash"] == "dflash: on, accept — (0/0)"
            assert await command("/think-budget") == "think budget 64 tokens, bias 2.0"
            await prompt("Confirm the README identifying text is still in our history.", max_tokens=256)

            before_compact = controller.state.recorder.snapshot()
            compacted = await command("/compact")
            assert compacted.startswith("Compacted "), compacted
            assert controller.state.recorder.snapshot() == before_compact
            await prompt("Continue with one concise sentence about the compacted history.", max_tokens=256)
            compacted_save = await command("/save")
            compacted_id = compacted_save.split()[1]
            await command("/new")
            await command(f"/switch {compacted_id}")
            await prompt("Give one final concise status sentence.", max_tokens=256)

        try:
            asyncio.run(asyncio.wait_for(scenario(), timeout=1800))
        finally:
            tui.close()

    accepted = max(evidence.after.drafts_accepted for evidence in rounds)
    offered = max(evidence.after.drafts_offered for evidence in rounds)
    print(
        f"M3 live harness: {len(rounds)} generation prompts, "
        f"DFlash offered={offered}, accepted={accepted}, "
        f"tool calls={tool_calls}, tool results={tool_results}"
    )
