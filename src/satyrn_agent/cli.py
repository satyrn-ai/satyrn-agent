"""Satyrn's explicit composition into ds4-py's agent command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol

from ds4py import agent_cli
from ds4py.agent_composition import ConfiguredSession

from .engine import SatyrnEngine
from .engine import open as open_satyrn
from .errors import SatyrnError
from .settings import configure_parser, resolve_config, resolve_settings

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from ds4py.agent_composition import EngineOpenOptions
    from ds4py.runtime import AgentRuntime
    from ds4py.tui_commands import SlashCommandRegistry

    from .config import SatyrnConfig


class OpenEngine(Protocol):
    def __call__(  # noqa: PLR0913 - Mirror Satyrn's native-open options exactly.
        self,
        model: str | Path = "ds4flash.gguf",
        *,
        config: SatyrnConfig | None = None,
        ctx: int = 100_000,
        backend: str | None = None,
        think: int = 3,
        seed: int | None = None,
        threads: int = 0,
        lib: str | Path | None = None,
        interactive: bool = False,
    ) -> SatyrnEngine: ...


class SatyrnAgentExtension:
    """Per-invocation Satyrn parser and settings hooks."""

    program = "satyrn-agent"

    def __init__(self, *, open_engine: OpenEngine | None = None) -> None:
        self._open_engine = open_satyrn if open_engine is None else open_engine
        self._wrapper: SatyrnEngine | None = None

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        configure_parser(parser)

    def resolve_extension_config(self, args: argparse.Namespace, project_dir: Path) -> object:
        return resolve_settings(args, project_dir)

    def open_session(
        self,
        options: EngineOpenOptions,
        project_dir: Path,
        extension_config: object,
    ) -> ConfiguredSession:
        config = resolve_config(options, extension_config)
        wrapper = self._open_engine(
            options.model,
            config=config,
            ctx=options.ctx,
            backend=options.backend,
            think=options.think,
            seed=options.seed,
            threads=options.threads,
            lib=options.lib,
            interactive=options.interactive,
        )
        self._wrapper = wrapper
        session = wrapper.session()
        return ConfiguredSession(session=session, sampling=wrapper.sampling_defaults, close=wrapper.close)

    def configure_commands(self, registry: SlashCommandRegistry, runtime: AgentRuntime) -> None:
        if self._wrapper is not None:
            self._wrapper.controller.configure_commands(registry)

    def before_identity_change(self) -> None:
        if self._wrapper is not None:
            self._wrapper.controller.before_identity_change()

    def after_identity_change(self) -> None:
        if self._wrapper is not None:
            self._wrapper.controller.after_identity_change()


def main(argv: list[str] | None = None, *, extension: SatyrnAgentExtension | None = None) -> int:
    """Run ds4-py's canonical agent driver with one Satyrn extension."""
    active = SatyrnAgentExtension() if extension is None else extension
    try:
        return agent_cli.main(sys.argv[1:] if argv is None else argv, extension=active)
    except SatyrnError as error:
        print(f"{active.program}: {error}", file=sys.stderr)
        return 1


__all__ = ["SatyrnAgentExtension", "main", "resolve_config"]
