from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from ds4py.agent_composition import EngineOpenOptions
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ToolCallPart,
    ToolReturnPart,
)

from satyrn_agent.cli import SatyrnAgentExtension, main, resolve_config
from satyrn_agent.config import DFlashMode, SatyrnConfig
from satyrn_agent.errors import ConfigurationError
from tests.e2e.model_free._harness import native_for, open_harness, scripted_tool_exchange
from tests.e2e.model_free._native import ScenarioFakeNative


def options(
    *,
    temperature: float | None = None,
    top_k: int | None = None,
    top_p: float | None = None,
    min_p: float | None = None,
) -> EngineOpenOptions:
    return EngineOpenOptions(
        model="scenario.gguf",
        ctx=100_000,
        backend="metal",
        think=3,
        seed=1,
        threads=0,
        lib=None,
        tokens=50,
        interactive=False,
        temperature=temperature,
        top_k=top_k,
        top_p=top_p,
        min_p=min_p,
    )


def parse(extension: SatyrnAgentExtension, argv: list[str]) -> argparse.Namespace:
    from ds4py import agent_cli

    return agent_cli.parser(extension).parse_args(argv)


def resolved(
    project_dir: Path,
    argv: list[str],
    *,
    toml: str | None = None,
    generic: list[str] | None = None,
) -> SatyrnConfig:
    if toml is not None:
        (project_dir / "pyproject.toml").write_text(toml)
    extension = SatyrnAgentExtension()
    args = parse(extension, [*argv, *(generic or [])])
    document = extension.resolve_extension_config(args, project_dir)
    generic_args = parse(extension, generic or [])
    typed = options(
        temperature=generic_args.temp,
        top_k=generic_args.top_k,
        top_p=generic_args.top_p,
        min_p=generic_args.min_p,
    )
    return resolve_config(typed, document)


def test_absent_project_file_uses_domain_defaults(tmp_path: Path) -> None:
    config = resolved(tmp_path, [])

    assert config.dflash is DFlashMode.AUTO
    assert config.drafter_path is None
    assert config.draft_tokens == 0
    assert config.think_budget is None


def test_only_current_directory_is_read(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.satyrn]\ndflash = "off"\ndraft_tokens = 9\n')
    child = tmp_path / "child"
    child.mkdir()
    (child / "pyproject.toml").write_text("[project]\nname = 'child'\n")

    config = resolved(child, [])

    assert config.dflash is DFlashMode.AUTO
    assert config.draft_tokens == 0


def test_project_cli_precedence_paths_and_explicit_zero_sampling(tmp_path: Path) -> None:
    toml = """
[tool.satyrn]
dflash = "off"
drafter_path = "models/project.gguf"
draft_tokens = 7
think_budget = { max_tokens = 512, bias = 3.0 }

[tool.satyrn.sampling]
temperature = 0.8
top_k = 40
top_p = 0.9
min_p = 0.2
"""
    config = resolved(
        tmp_path,
        [
            "--dflash",
            "auto",
            "--drafter",
            "~/cli.gguf",
            "--draft-tokens",
            "0",
            "--think-budget",
            "256",
        ],
        toml=toml,
        generic=["--temp", "0", "--top-k", "0", "--top-p", "0", "--min-p", "0"],
    )

    assert config.dflash is DFlashMode.AUTO
    assert config.drafter_path == Path.home() / "cli.gguf"
    assert config.draft_tokens == 0
    assert config.think_budget is not None
    assert (config.think_budget.max_tokens, config.think_budget.bias) == (256, 3.0)
    assert config.sampling.temperature == 0.0
    assert config.sampling.top_k == 0
    assert config.sampling.top_p == 0.0
    assert config.sampling.min_p == 0.0


def test_project_relative_drafter_uses_toml_directory(tmp_path: Path) -> None:
    config = resolved(
        tmp_path,
        [],
        toml='[tool.satyrn]\ndrafter_path = "models/drafter.gguf"\n',
    )

    assert config.drafter_path == tmp_path / "models/drafter.gguf"


@pytest.mark.parametrize(
    ("toml", "argv", "expected"),
    [
        (None, ["--think-budget", "12"], (12, 2.0)),
        (
            "[tool.satyrn]\nthink_budget = { max_tokens = 50, bias = 4.0 }\n",
            ["--think-bias", "1.5"],
            (50, 1.5),
        ),
        (None, ["--think-budget", "12", "--think-bias", "3.5"], (12, 3.5)),
        ("[tool.satyrn]\nthink_budget = { max_tokens = 50, bias = 4.0 }\n", [], (50, 4.0)),
        (
            "[tool.satyrn]\nthink_budget = { max_tokens = 50, bias = 4.0 }\n",
            ["--no-think-budget"],
            None,
        ),
    ],
)
def test_think_budget_source_rules(
    tmp_path: Path,
    toml: str | None,
    argv: list[str],
    expected: tuple[int, float] | None,
) -> None:
    config = resolved(tmp_path, argv, toml=toml)
    actual = None if config.think_budget is None else (config.think_budget.max_tokens, config.think_budget.bias)
    assert actual == expected


@pytest.mark.parametrize(
    ("toml", "argv", "match"),
    [
        (None, ["--think-bias", "2"], "effective think budget"),
        (None, ["--no-think-budget", "--think-budget", "2"], "conflicts"),
        (
            "[tool.satyrn]\nthink_budget = { max_tokens = 50, bias = 4.0 }\n",
            ["--no-think-budget", "--think-bias", "2"],
            "conflicts",
        ),
        ("[tool.satyrn]\nunknown = 1\n", [], "unknown config fields"),
        ("[tool.satyrn]\ndraft_tokens = true\n", [], "must be an integer"),
        ("[tool.satyrn]\ndraft_tokens = -1\n", [], "at least 0"),
        ('[tool.satyrn]\ndflash = "on"\n', [], "drafter_path is required"),
        ("[tool.satyrn.sampling]\ntop_k = -1\n", [], "at least 0"),
        ("[tool.satyrn.sampling]\ntop_p = 2.0\n", [], "between 0 and 1"),
        ("[tool.satyrn]\nthink_budget = { max_tokens = 50 }\n", [], "requires max_tokens and bias"),
        ("tool = 1\n", [], "tool must be a table"),
        ("[tool]\nsatyrn = 1\n", [], "tool.satyrn must be a table"),
        ("[tool.satyrn]\ndrafter_path = 1\n", [], "drafter_path must be a string"),
        ("[tool.satyrn]\nthink_budget = 1\n", [], "think_budget must be an object"),
        ("[tool.satyrn]\nsampling = 1\n", [], "sampling must be an object"),
    ],
)
def test_invalid_settings_fail_before_native_open(
    tmp_path: Path,
    toml: str | None,
    argv: list[str],
    match: str,
) -> None:
    with pytest.raises((ConfigurationError, TypeError, ValueError), match=match):
        resolved(tmp_path, argv, toml=toml)


@pytest.mark.parametrize("argv", [["--think-budget", "0"], ["--draft-tokens", "-1"]])
def test_non_positive_cli_numbers_are_argparse_errors(tmp_path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        resolved(tmp_path, argv)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_cli_think_bias_is_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigurationError, match="finite"):
        resolved(tmp_path, ["--think-budget", "2", f"--think-bias={value}"])


def test_malformed_toml_names_source_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"pyproject\.toml"):
        resolved(tmp_path, [], toml="[tool.satyrn\n")


def test_top_level_satyrn_error_has_program_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from satyrn_agent.errors import DFlashUnavailable

    extension = SatyrnAgentExtension()
    monkeypatch.setattr(
        extension,
        "resolve_extension_config",
        lambda args, project_dir: (_ for _ in ()).throw(DFlashUnavailable("missing test binding")),
    )
    monkeypatch.chdir(tmp_path)

    assert main([], extension=extension) == 1
    assert capsys.readouterr().err == "satyrn-agent: missing test binding\n"


def test_yolo_remains_invalid(tmp_path: Path) -> None:
    extension = SatyrnAgentExtension()
    with pytest.raises(SystemExit):
        parse(extension, ["--yolo"])


def test_extension_protocol_noops_are_safe_before_controller_configuration() -> None:
    extension = SatyrnAgentExtension()

    assert extension.configure_commands(cast("Any", object()), cast("Any", object())) is None
    assert extension.before_identity_change() is None
    assert extension.after_identity_change() is None


def test_resolve_config_rejects_a_non_mapping_document() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        resolve_config(options(), object())


def test_resolve_config_preserves_unsourced_validation_errors() -> None:
    with pytest.raises(ConfigurationError, match="unknown config fields") as caught:
        resolve_config(options(), {"unknown": 1})

    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("sampling_argv", "expected"),
    [
        ([], (0.7, 20, 0.95, 0.05)),
        (["--temp", "0", "--top-k", "0", "--top-p", "0", "--min-p", "0"], (0.0, 0, 0.0, 0.0)),
    ],
)
def test_public_runtime_maps_typed_options_and_exact_sampling_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sampling_argv: list[str],
    expected: tuple[float, int, float, float],
) -> None:
    native = native_for("answer")
    lib = tmp_path / "libds4.dylib"
    argv = [
        "--model",
        "custom.gguf",
        "--ctx",
        "4096",
        "--metal",
        "--nothink",
        "--seed",
        "0",
        "--threads",
        "3",
        "--lib",
        str(lib),
        "--tokens",
        "123",
        "--dflash",
        "off",
        *sampling_argv,
    ]

    with open_harness(tmp_path, native, argv, monkeypatch) as harness:
        opened = harness.opened[0]
        assert opened["model"] == "custom.gguf"
        assert opened["ctx"] == 4096
        assert opened["backend"] == "metal"
        assert opened["think"] == 0
        assert opened["seed"] == 0
        assert opened["threads"] == 3
        assert opened["lib"] == lib
        assert opened["interactive"] is False
        assert opened["config"].dflash is DFlashMode.OFF
        policy = harness.runtime.model.sampling
        assert policy is harness.wrappers[0].sampling_defaults
        assert policy.temperature == pytest.approx(expected[0])
        assert policy.top_k == expected[1]
        assert policy.top_p == pytest.approx(expected[2])
        assert policy.min_p == pytest.approx(expected[3])
        assert policy.seed == 0
        assert harness.runtime.model.max_tokens == 123


def test_real_runtime_executes_tool_call_and_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text("Satyrn harness marker")
    native = native_for(scripted_tool_exchange())

    with open_harness(tmp_path, native, ["--dflash", "off", "--nothink"], monkeypatch) as harness:
        events = []
        harness.runtime.on_event(events.append, kinds={"agent_event"})
        result = asyncio.run(harness.runtime.run("Read the README"))

    parts = [part for message in result.all_messages() for part in message.parts]
    assert any(isinstance(part, ToolCallPart) and part.tool_name == "read_file" for part in parts)
    assert any(isinstance(part, ToolReturnPart) and "Satyrn harness marker" in str(part.content) for part in parts)
    agent_events = [event.payload["event"] for event in events]
    assert any(isinstance(event, FunctionToolCallEvent) for event in agent_events)
    assert any(isinstance(event, FunctionToolResultEvent) for event in agent_events)


def test_noninteractive_main_runs_and_saves_without_status_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import satyrn_agent

    native = native_for("final answer")

    def open_engine(model: str | Path = "ds4flash.gguf", **kwargs: Any) -> satyrn_agent.SatyrnEngine:
        return satyrn_agent.open(model, native=native, **kwargs)

    extension = SatyrnAgentExtension(open_engine=open_engine)
    monkeypatch.setenv("DS4PY_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            ["--non-interactive", "--prompt", "hello", "--dflash", "off", "--nothink"],
            extension=extension,
        )
        == 0
    )
    assert capsys.readouterr().out == "final answer\n"
    records = [
        json.loads(line)
        for path in tmp_path.glob("home/sessions/*/events.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert records
    assert not any(record["kind"] == "status" for record in records)


def test_native_dflash_unavailable_is_labeled_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import satyrn_agent

    native = ScenarioFakeNative({"script": [0], "calls": [], "missing": {"ds4_engine_has_dflash"}})

    def open_engine(model: str | Path = "ds4flash.gguf", **kwargs: Any) -> satyrn_agent.SatyrnEngine:
        return satyrn_agent.open(model, native=native, **kwargs)

    extension = SatyrnAgentExtension(open_engine=open_engine)
    monkeypatch.chdir(tmp_path)
    argv = [
        "--non-interactive",
        "--prompt",
        "hello",
        "--dflash",
        "on",
        "--drafter",
        "drafter.gguf",
    ]

    assert main(argv, extension=extension) == 1
    captured = capsys.readouterr()
    assert "satyrn-agent: DFlash bindings are missing: ds4_engine_has_dflash" in captured.err
    assert "Traceback" not in captured.err
