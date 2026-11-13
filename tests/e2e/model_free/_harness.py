"""Public Satyrn/ds4-py harness composition with only native behavior faked."""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MethodType
from typing import Any

import pytest
from ds4py._native.fake import FAKE_EOS
from ds4py._native.fake_chat import tokenize_rendered
from ds4py.runtime import AgentRuntime

import satyrn_agent
from satyrn_agent.cli import SatyrnAgentExtension
from tests.e2e.model_free._native import ScenarioFakeNative


@dataclass
class Harness:
    runtime: AgentRuntime
    extension: SatyrnAgentExtension
    native: ScenarioFakeNative
    opened: list[dict[str, Any]]
    wrappers: list[satyrn_agent.SatyrnEngine]


def native_for(script: str | list[int], *, sampling: list[float] | None = None) -> ScenarioFakeNative:
    tokens = [*tokenize_rendered(script), FAKE_EOS] if isinstance(script, str) else script
    values = sampling or [0.7, 20, 0.95, 0.05]
    return ScenarioFakeNative(
        {
            "script": tokens,
            "calls": [],
            "sampling_defaults": {
                "temperature": values[0],
                "top_k": int(values[1]),
                "top_p": values[2],
                "min_p": values[3],
            },
        }
    )


def native_for_rounds(*texts: str) -> ScenarioFakeNative:
    script: list[int] = []
    for text in texts:
        script.extend([*tokenize_rendered(text), FAKE_EOS])
    return native_for(script)


def native_for_dflash(text: str) -> ScenarioFakeNative:
    answer = tokenize_rendered(text)
    script = [*answer, FAKE_EOS, *answer, FAKE_EOS, *answer, FAKE_EOS]
    native = native_for(script)
    native.responses["draft"] = [{"op": "draft", "tokens": [token]} for token in script[1:]]
    return native


def scripted_tool_exchange() -> list[int]:
    call = "<tool_call><function=read_file><parameter=path>README.md</parameter></function></tool_call>"
    return [
        *tokenize_rendered(call),
        FAKE_EOS,
        *tokenize_rendered("The README identifies Satyrn."),
        FAKE_EOS,
    ]


@contextmanager
def open_harness(
    project_dir: Path,
    native: ScenarioFakeNative,
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    interactive: bool = False,
) -> Generator[Harness]:
    from ds4py import agent_cli

    monkeypatch.setenv("DS4PY_HOME", str(project_dir / "home"))
    monkeypatch.chdir(project_dir)
    opened: list[dict[str, Any]] = []
    wrappers: list[satyrn_agent.SatyrnEngine] = []
    runtimes: list[AgentRuntime] = []

    def open_engine(model: str | Path = "ds4flash.gguf", **kwargs: Any) -> satyrn_agent.SatyrnEngine:
        if native.cancel_event is None:
            native.cancel_event = threading.Event()
        wrapper = satyrn_agent.open(model, native=native, cancel=native.cancel_event, **kwargs)
        opened.append({"model": str(model), **kwargs})
        wrappers.append(wrapper)
        original_close = wrapper.close

        def close(self: satyrn_agent.SatyrnEngine) -> None:
            if runtimes:
                assert runtimes[0].status == "closed"
            original_close()

        monkeypatch.setattr(wrapper, "close", MethodType(close, wrapper))
        return wrapper

    extension = SatyrnAgentExtension(open_engine=open_engine)
    args = agent_cli.parser(extension).parse_args([*([] if interactive else ["--non-interactive"]), *argv])
    extension_config = extension.resolve_extension_config(args, project_dir)
    with agent_cli.open_runtime(
        args,
        project_dir,
        read_only=args.read_only,
        extension=extension,
        extension_config=extension_config,
    ) as runtime:
        runtimes.append(runtime)
        yield Harness(runtime, extension, native, opened, wrappers)
