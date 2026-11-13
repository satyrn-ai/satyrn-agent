from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from ds4py import EngineError
from ds4py.engine.decode import PlainStep
from ds4py.model import ResponseTerminalError
from ds4py.tui import TUI
from prompt_toolkit.output import DummyOutput

from satyrn_agent.errors import DFlashError
from tests.e2e.model_free._harness import Harness, native_for, native_for_dflash, native_for_rounds, open_harness


def make_tui(harness: Harness) -> TUI:
    return TUI(harness.runtime, output=DummyOutput(), configure_commands=harness.extension.configure_commands)


def test_new_orders_safe_native_selection_and_python_only_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta")
    argv = ["--dflash", "on", "--drafter", "drafter.gguf", "--think-budget", "10"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        old_state = controller.state
        old_state.recorder.committed(4, 2, replacement=False, discarded=2)
        asyncio.run(tui.commands.execute("/think-budget 99 8"))
        statuses = []
        listener_counts = []
        harness.runtime.on_event(statuses.append, kinds={"status"})

        def check_listener(event: object) -> None:
            listener_counts.append(len(native.call_log))
            assert isinstance(controller.state.step, PlainStep)

        harness.runtime.on_event(check_listener, kinds={"session_start"})
        try:
            asyncio.run(harness.runtime.new())

            assert old_state.closed
            assert controller.state is not old_state
            assert controller.state.recorder.snapshot().drafts_offered == 0
            setting = controller.think_hook.snapshot()
            assert setting is not None
            assert setting.max_tokens == 10
            assert [event.payload["text"] for event in statuses] == [
                "dflash: on/off, accept — (0/0)",
                "dflash: on, accept — (0/0)",
            ]
            assert len(listener_counts) == 1
            assert native.verify_modes[-2:] == [0, 1]
        finally:
            tui.close()


def test_switch_resets_state_and_restores_saved_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta gamma")
    argv = ["--dflash", "on", "--drafter", "drafter.gguf", "--think-budget", "10", "--nothink"]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller

        async def scenario() -> None:
            await harness.runtime.run("first")
            saved = await harness.runtime.save()
            saved_messages = harness.runtime.messages
            await tui.commands.execute("/think-budget 99 8")
            old_state = controller.state
            statuses = []
            harness.runtime.on_event(statuses.append, kinds={"status"})
            switching = []

            def check_switching(event: object) -> None:
                switching.append(native.verify_mode)
                assert isinstance(controller.state.step, PlainStep)

            harness.runtime.on_event(check_switching, kinds={"switching"})
            await harness.runtime.new()
            statuses.clear()
            await harness.runtime.switch(saved.session_id)

            assert old_state.closed
            assert controller.state is not old_state
            assert controller.state.recorder.snapshot().drafts_offered == 0
            setting = controller.think_hook.snapshot()
            assert setting is not None
            assert setting.max_tokens == 10
            assert harness.runtime.messages == saved_messages
            assert switching == [0]
            assert [event.payload["text"] for event in statuses] == [
                "dflash: on/off, accept — (0/0)",
                "dflash: on, accept — (0/0)",
            ]

        try:
            asyncio.run(scenario())
        finally:
            tui.close()


def test_fork_retains_state_think_metrics_and_native_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta")
    with open_harness(
        tmp_path,
        native,
        ["--dflash", "on", "--drafter", "drafter.gguf", "--think-budget", "10"],
        monkeypatch,
        interactive=True,
    ) as harness:
        controller = harness.wrappers[0].controller
        state = controller.state
        state.recorder.committed(4, 2, replacement=False, discarded=2)
        controller.set_think_budget("99", "8")
        modes = list(native.verify_modes)
        starts = []
        harness.runtime.on_event(starts.append, kinds={"session_start"})

        asyncio.run(harness.runtime.fork())

        assert controller.state is state
        assert state.recorder.snapshot().drafts_offered == 4
        setting = controller.think_hook.snapshot()
        assert setting is not None
        assert setting.max_tokens == 99
        assert native.verify_modes == modes
        assert starts == []


def test_before_identity_failure_preserves_identity_record_and_footer(
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
        session_id = harness.runtime.session_id
        footer = tui.footer.custom["dflash"]
        native.responses["mode"] = [{"op": "mode", "error": "before failed"}]
        try:
            with pytest.raises(DFlashError, match="before failed"):
                asyncio.run(harness.runtime.new())
            assert harness.runtime.session_id == session_id
            assert tui.footer.custom["dflash"] == footer
            assert isinstance(controller.state.step, PlainStep)
        finally:
            tui.close()


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_after_identity_failure_is_visible_and_never_restores_old_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rollback_fails: bool,
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
        old_id = harness.runtime.session_id
        native.responses["mode"] = [
            {"op": "mode"},
            {"op": "mode", "error": "after failed"},
            {"op": "mode", "error": "rollback failed"} if rollback_fails else {"op": "mode"},
        ]
        try:
            with pytest.raises(DFlashError, match="after failed") as caught:
                asyncio.run(harness.runtime.new())
            assert harness.runtime.session_id != old_id
            assert harness.runtime.status == "error"
            assert isinstance(controller.state.step, PlainStep)
            expected = "error" if rollback_fails else "on/off"
            assert tui.footer.custom["dflash"] == f"dflash: {expected}, accept — (0/0)"
            if rollback_fails:
                assert isinstance(caught.value.__cause__, DFlashError)
                assert "rollback failed" in str(caught.value.__cause__)
        finally:
            tui.close()


def test_failed_restore_keeps_safe_selection_and_pre_resolution_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for_dflash("alpha beta gamma")
    with open_harness(
        tmp_path,
        native,
        ["--dflash", "on", "--drafter", "drafter.gguf", "--nothink"],
        monkeypatch,
        interactive=True,
    ) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller

        async def scenario() -> None:
            await harness.runtime.run("first")
            saved = await harness.runtime.save()
            await harness.runtime.new()
            native.payload_load_error = RuntimeError("restore failed")
            with pytest.raises(RuntimeError, match="restore failed"):
                await harness.runtime.switch(saved.session_id)

            assert harness.runtime.session_id == saved.session_id
            assert harness.runtime.status == "error"
            assert isinstance(controller.state.step, PlainStep)
            assert native.verify_mode == 0
            assert tui.footer.custom["dflash"] == "dflash: on/off, accept — (0/0)"

        try:
            asyncio.run(scenario())
        finally:
            tui.close()


@pytest.mark.parametrize(
    ("outcome", "error_type"),
    [("success", None), ("interrupted", EngineError), ("error", ResponseTerminalError)],
)
def test_run_end_refreshes_footer_for_every_terminal_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    error_type: type[Exception] | None,
) -> None:
    native = native_for_rounds("answer")
    argv = ["--dflash", "off", "--nothink", *(["--tokens", "1"] if outcome == "error" else [])]
    with open_harness(tmp_path, native, argv, monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        controller.state.recorder.committed(4, 2, replacement=False, discarded=2)
        controller.publish_status()
        statuses = []
        ends = []
        harness.runtime.on_event(statuses.append, kinds={"status"})
        harness.runtime.on_event(ends.append, kinds={"run_end"})
        if outcome == "interrupted":
            assert native.cancel_event is not None
            native.cancel_event.set()
        try:
            if outcome == "success":
                asyncio.run(harness.runtime.run("hello"))
            else:
                assert error_type is not None
                with pytest.raises(error_type):
                    asyncio.run(harness.runtime.run("hello"))
            assert ends[-1].payload["status"] == outcome
            assert statuses[-1].payload["text"] == "dflash: off, accept 50.0% (2/4)"
            assert tui.footer.custom["dflash"] == "dflash: off, accept 50.0% (2/4)"
        finally:
            tui.close()


@pytest.mark.parametrize("payload_support", [True, False])
def test_public_save_switch_and_continuation_honor_payload_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload_support: bool,
) -> None:
    native = native_for_rounds("first answer", "second answer")
    native.payload_support = payload_support
    with open_harness(tmp_path, native, ["--dflash", "off", "--nothink"], monkeypatch) as harness:

        async def scenario() -> None:
            first = await harness.runtime.run("first")
            assert first.output == "first answer"
            saved = await harness.runtime.save()
            directory = harness.runtime.store.session_dir(saved.session_id)
            messages = harness.runtime.messages
            tokens = harness.runtime.model.session.transcript.tokens
            assert saved.payload_bytes > 0 if payload_support else saved.payload_bytes == 0
            assert (directory / "session.kv").exists() is payload_support
            assert saved.tokens == len(tokens) > 0

            await harness.runtime.new()
            switched = await harness.runtime.switch(saved.session_id)
            assert switched == saved
            assert harness.runtime.messages == messages
            assert bool(harness.runtime.model.session.transcript.tokens) is payload_support
            second = await harness.runtime.run("second")
            assert second.output == "second answer"

        asyncio.run(scenario())


@pytest.mark.parametrize("payload_support", [True, False])
def test_compacted_history_uses_same_public_persistence_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload_support: bool,
) -> None:
    native = native_for_rounds("first answer", "recent answer", "durable state", "continued")
    native.payload_support = payload_support
    with open_harness(tmp_path, native, ["--dflash", "off", "--nothink"], monkeypatch, interactive=True) as harness:
        tui = make_tui(harness)

        async def scenario() -> None:
            await harness.runtime.run("x" * 14000)
            await harness.runtime.run("recent")
            result = await tui.commands.execute("/compact")
            assert result == "Compacted 2 messages; kept 2 (13 generated tokens)"
            saved = await harness.runtime.save()
            messages = harness.runtime.messages
            tokens = harness.runtime.model.session.transcript.tokens
            assert saved.payload_bytes > 0 if payload_support else saved.payload_bytes == 0
            assert saved.tokens == len(tokens) > 0

            await harness.runtime.new()
            await harness.runtime.switch(saved.session_id)
            assert harness.runtime.messages == messages
            assert bool(harness.runtime.model.session.transcript.tokens) is payload_support
            continued = await harness.runtime.run("continue")
            assert continued.output == "continued"

        try:
            asyncio.run(scenario())
        finally:
            tui.close()


def test_close_clears_hook_and_unsubscribes_run_end_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = native_for("answer")
    with open_harness(
        tmp_path, native, ["--dflash", "off", "--think-budget", "10"], monkeypatch, interactive=True
    ) as harness:
        tui = make_tui(harness)
        controller = harness.wrappers[0].controller
        statuses = []
        harness.runtime.on_event(statuses.append, kinds={"status"})
        try:
            controller.close()
            controller.close()
            harness.runtime.model.session.emit("run_end", status="success")
            assert statuses == []
            assert controller.think_hook.snapshot() is None
        finally:
            tui.close()
