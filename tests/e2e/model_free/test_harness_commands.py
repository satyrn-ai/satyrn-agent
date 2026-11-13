from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path

import pytest
from ds4py.engine.decode import PlainStep
from ds4py.tui import TUI
from ds4py.tui_commands import CommandError
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from satyrn_agent.config import DFlashMode
from satyrn_agent.dflash import DFlashStep
from satyrn_agent.errors import DFlashError, DFlashUnavailable
from tests.e2e.model_free._harness import Harness, native_for, native_for_dflash, open_harness
from tests.e2e.model_free._native import ScenarioFakeNative


def make_tui(harness: Harness) -> TUI:
    return TUI(harness.runtime, output=DummyOutput(), configure_commands=harness.extension.configure_commands)


def test_initial_footer_and_think_budget_query_set_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta gamma")
    argv = [
        "--dflash",
        "on",
        "--drafter",
        "drafter.gguf",
        "--think-budget",
        "10",
        "--think-bias",
        "2",
        "--nothink",
    ]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        events = []
        harness.runtime.on_event(events.append, kinds={"status"})
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        try:
            expected = "dflash: on, accept — (0/0)"
            assert tui.footer.custom["dflash"] == expected
            assert len(events) == 1
            assert asyncio.run(tui.commands.execute("/dflash")) == expected
            assert asyncio.run(tui.commands.execute("/think-budget")) == "think budget 10 tokens, bias 2.0"
            hook = controller.think_hook

            assert asyncio.run(tui.commands.execute("/think-budget 20")) == "think budget 20 tokens, bias 2.0"
            assert controller.think_hook is hook
            setting = hook.snapshot()
            assert setting is not None
            assert (setting.max_tokens, setting.bias) == (20, 2.0)
            assert asyncio.run(tui.commands.execute("/think-budget 30 4.5")) == ("think budget 30 tokens, bias 4.5")
            assert asyncio.run(tui.commands.execute("/think-budget off")) == "think budget off"
            assert hook.snapshot() is None
            assert asyncio.run(tui.commands.execute("/think-budget 12")) == "think budget 12 tokens, bias 2.0"
            assert not hasattr(controller, "_current")
        finally:
            tui.close()


@pytest.mark.parametrize(
    ("command", "usage"),
    [
        ("/dflash invalid", "/dflash [auto|on|off]"),
        ("/dflash on extra", "/dflash [auto|on|off]"),
        ("/think-budget 0", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget -1", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget nope", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget 2 0", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget 2 -1", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget 2 nan", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget 2 inf", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget 2 3 extra", "/think-budget [<max_tokens> [bias]|off]"),
        ("/think-budget off extra", "/think-budget [<max_tokens> [bias]|off]"),
    ],
)
def test_command_usage_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    usage: str,
) -> None:
    with open_harness(tmp_path, native_for("answer"), ["--dflash", "off"], monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        try:
            with pytest.raises(CommandError, match=f"usage: {re.escape(usage)}"):
                asyncio.run(tui.commands.execute(command))
        finally:
            tui.close()


def test_dflash_metrics_accumulate_across_toggles_and_refresh_on_run_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta gamma delta epsilon zeta")
    argv = ["--dflash", "on", "--drafter", "drafter.gguf", "--nothink"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        try:

            async def rounds() -> None:
                await harness.runtime.run("first")
                first = controller.state.recorder.snapshot()
                assert first.drafts_offered > 0
                assert first.drafts_accepted > 0
                assert tui.footer.custom["dflash"] == controller.status_text()

                await tui.commands.execute("/dflash off")
                assert controller.state.requested is DFlashMode.OFF
                assert isinstance(controller.state.step, PlainStep)
                assert native.verify_modes[-1] == 0
                await harness.runtime.run("second")
                assert controller.state.recorder.snapshot() == first
                assert "accept" in tui.footer.custom["dflash"]

                await tui.commands.execute("/dflash auto")
                assert controller.state.requested is DFlashMode.AUTO
                assert isinstance(controller.state.step, DFlashStep)
                await harness.runtime.run("third")
                third = controller.state.recorder.snapshot()
                assert third.committed_blocks > first.committed_blocks
                assert third.drafts_offered > first.drafts_offered
                assert tui.footer.custom["dflash"] == controller.status_text()

            asyncio.run(rounds())
        finally:
            tui.close()


def test_footer_uses_one_decimal_and_retains_counts_while_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta")
    with open_harness(
        tmp_path,
        native,
        ["--dflash", "on", "--drafter", "drafter.gguf"],
        monkeypatch,
        interactive=True,
    ) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        try:
            controller.state.recorder.committed(16, 10, replacement=False, discarded=6)
            controller.publish_status()
            assert tui.footer.custom["dflash"] == "dflash: on, accept 62.5% (10/16)"
            asyncio.run(tui.commands.execute("/dflash off"))
            assert tui.footer.custom["dflash"] == "dflash: off, accept 62.5% (10/16)"
        finally:
            tui.close()


@pytest.mark.parametrize(
    ("native", "match"),
    [
        (
            ScenarioFakeNative({"script": [0], "calls": [], "missing": {"ds4_engine_has_dflash"}}),
            "bindings are missing",
        ),
        (ScenarioFakeNative({"script": [0], "calls": []}), "drafter path"),
        (ScenarioFakeNative({"script": [0], "calls": []}, backend="cpu"), "requires Metal"),
        (ScenarioFakeNative({"script": [0], "calls": [], "has_dflash": False}), "loaded drafter"),
        (ScenarioFakeNative({"script": [0], "calls": [], "verify_rows": 0}), "at least one verify row"),
    ],
)
def test_dflash_support_errors_preserve_pre_mutation_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native: ScenarioFakeNative,
    match: str,
) -> None:
    argv = ["--dflash", "off", *([] if match == "drafter path" else ["--drafter", "drafter.gguf"])]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        state = controller.state
        previous_step = state.step
        previous_status = tui.footer.custom["dflash"]
        previous_history = harness.runtime.model.session.transcript.tokens
        previous_modes = list(native.verify_modes)
        try:
            with pytest.raises(DFlashUnavailable, match=match):
                asyncio.run(tui.commands.execute("/dflash on"))
            assert controller.state is state
            assert state.requested is DFlashMode.OFF
            assert state.step is previous_step
            assert tui.footer.custom["dflash"] == previous_status
            assert harness.runtime.model.session.transcript.tokens == previous_history
            assert native.verify_modes == previous_modes
        finally:
            tui.close()


def test_dflash_probe_failure_preserves_pre_mutation_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for("answer")
    argv = ["--dflash", "off", "--drafter", "drafter.gguf"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        native.responses["has_dflash"] = [{"op": "has_dflash", "error": "probe failed"}]
        previous_step = controller.state.step
        previous_status = tui.footer.custom["dflash"]
        previous_history = harness.runtime.model.session.transcript.tokens
        try:
            with pytest.raises(DFlashError, match="probe failed"):
                asyncio.run(tui.commands.execute("/dflash on"))
            assert controller.state.step is previous_step
            assert controller.state.requested is DFlashMode.OFF
            assert tui.footer.custom["dflash"] == previous_status
            assert harness.runtime.model.session.transcript.tokens == previous_history
        finally:
            tui.close()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [("on", "dflash: on/off, accept — (0/0)"), ("auto", "dflash: auto/off, accept — (0/0)")],
)
def test_post_mma_failure_installs_plain_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
) -> None:
    native = native_for("answer")
    argv = ["--dflash", "off", "--drafter", "drafter.gguf"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        native.responses["mode"] = [{"op": "mode", "error": "MMA failed"}]
        previous_history = harness.runtime.model.session.transcript.tokens
        try:
            with pytest.raises(DFlashError, match="MMA failed"):
                asyncio.run(tui.commands.execute(f"/dflash {mode}"))
            assert isinstance(controller.state.step, PlainStep)
            assert controller.state.requested is DFlashMode(mode)
            assert native.verify_modes[-2:] == [1, 0]
            assert tui.footer.custom["dflash"] == expected_status
            assert harness.runtime.model.session.transcript.tokens == previous_history
        finally:
            tui.close()


def test_rollback_failure_chains_original_and_cleanup_and_reports_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for("answer")
    argv = ["--dflash", "off", "--drafter", "drafter.gguf"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        native.responses["mode"] = [
            {"op": "mode", "error": "MMA failed"},
            {"op": "mode", "error": "OFF failed"},
        ]
        previous_history = harness.runtime.model.session.transcript.tokens
        try:
            with pytest.raises(DFlashError, match="MMA failed") as caught:
                asyncio.run(tui.commands.execute("/dflash on"))
            assert isinstance(caught.value.__cause__, DFlashError)
            assert "OFF failed" in str(caught.value.__cause__)
            assert isinstance(controller.state.step, PlainStep)
            assert tui.footer.custom["dflash"] == "dflash: error, accept — (0/0)"
            assert harness.runtime.model.session.transcript.tokens == previous_history
        finally:
            tui.close()


def test_off_and_auto_fallback_do_not_require_verify_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for mode in ("off", "auto"):
        native = ScenarioFakeNative(
            {
                "script": [0],
                "calls": [],
                "missing": {"ds4_session_set_verify_mode", "ds4_session_verify"},
            }
        )
        argv = ["--dflash", mode, "--drafter", "drafter.gguf"]
        with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
            controller = harness.wrappers[0].controller
            assert isinstance(controller.state.step, PlainStep)
            assert native.verify_modes == []
            asyncio.run(harness.runtime.new())
            assert isinstance(controller.state.step, PlainStep)
            assert native.verify_modes == []


def test_identity_hooks_reset_startup_state_and_close_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta")
    argv = [
        "--dflash",
        "on",
        "--drafter",
        "drafter.gguf",
        "--think-budget",
        "10",
        "--think-bias",
        "2",
    ]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        try:
            asyncio.run(tui.commands.execute("/think-budget 99 8"))
            controller.state.recorder.committed(4, 2, replacement=False, discarded=2)
            asyncio.run(harness.runtime.new())
            assert controller.state.requested is DFlashMode.ON
            assert isinstance(controller.state.step, DFlashStep)
            assert controller.state.recorder.snapshot().drafts_offered == 0
            setting = controller.think_hook.snapshot()
            assert setting is not None
            assert setting.max_tokens == 10
            assert tui.footer.custom["dflash"] == "dflash: on, accept — (0/0)"
            controller.close()
            controller.close()
            assert controller.think_hook.snapshot() is None
        finally:
            tui.close()


def test_slash_mode_change_waits_for_active_native_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for("answer")
    native.sample_started = threading.Event()
    native.sample_release = threading.Event()
    started = native.sample_started
    release = native.sample_release
    with (
        open_harness(
            tmp_path,
            native,
            ["--dflash", "on", "--drafter", "drafter.gguf", "--nothink"],
            monkeypatch,
            interactive=True,
        ) as harness,
        create_pipe_input() as input_,
    ):
        tui = TUI(
            harness.runtime,
            input=input_,
            output=DummyOutput(),
            configure_commands=harness.extension.configure_commands,
        )

        try:

            async def run() -> None:
                task = asyncio.create_task(tui.run("hello"))
                await asyncio.wait_for(asyncio.to_thread(started.wait), 2)
                input_.send_text("/dflash off\n/exit\n")
                await asyncio.sleep(0.02)
                assert native.verify_modes[-1] == 1
                release.set()
                await asyncio.wait_for(task, 2)
                assert native.verify_modes[-1] == 0

            asyncio.run(run())
        finally:
            release.set()
