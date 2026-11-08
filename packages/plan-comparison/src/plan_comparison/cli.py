import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from plan_comparison.budget import MonotonicBudget
from plan_comparison.contracts import (
    PublicTaskInputs,
    ReferenceTaskPort,
    RunMode,
    TaskSeedPair,
    WorkerPort,
)
from plan_comparison.reports import StyleEvidence
from plan_comparison.runner import ExperimentRunner


@dataclass(frozen=True, slots=True)
class ExperimentServices:
    runner: ExperimentRunner
    task_port: ReferenceTaskPort
    inputs_by_task: Mapping[str, PublicTaskInputs]
    worker_factory: Callable[[PublicTaskInputs, int], WorkerPort]
    schedule: tuple[TaskSeedPair, ...]
    mechanical_style: tuple[StyleEvidence, ...] = ()
    human_style: tuple[StyleEvidence, ...] = ()
    decision_value: float | None = None


class ExperimentFactory(Protocol):
    def __call__(self, arguments: argparse.Namespace) -> ExperimentServices: ...


def _factory(specification: str) -> ExperimentFactory:
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("Factory must use the form 'package.module:function'.")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError("Configured experiment factory is not callable.")
    return factory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-comparison")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run an explicitly configured pair sweep.")
    run.add_argument("--factory", required=True)
    run.add_argument("--mode", choices=("cpu", "pilot", "deciding"), required=True)
    run.add_argument("--experiment-id", required=True)
    run.add_argument("--registration", type=Path)
    run.add_argument("--live-authorization-ref")
    run.add_argument("--disposable-policy-ref")

    capabilities = commands.add_parser(
        "capabilities", help="Run an explicitly authorized boundary capability check."
    )
    capabilities.add_argument("--factory", required=True)
    capabilities.add_argument("--task-id", required=True)
    capabilities.add_argument("--seed", type=int, default=0)
    capabilities.add_argument("--live-authorization-ref", required=True)
    capabilities.add_argument("--disposable-policy-ref", required=True)
    return parser


def _check_service_mode(
    parser: argparse.ArgumentParser,
    services: ExperimentServices,
    mode: RunMode,
    authorization_ref: str | None,
    disposable_policy_ref: str | None,
) -> None:
    config = services.runner.config
    if config.mode != mode:
        parser.error("Experiment factory mode does not match the requested mode.")
    if mode != "cpu" and (
        config.live_authorization_ref != authorization_ref
        or config.disposable_policy_ref != disposable_policy_ref
    ):
        parser.error("Factory authorization references do not match the command.")


async def _capability_run(
    services: ExperimentServices,
    inputs: PublicTaskInputs,
    worker: WorkerPort,
    authorization_ref: str,
    disposable_policy_ref: str,
):
    budget = MonotonicBudget(services.runner.config.budgets)
    try:
        return await services.runner.check_capabilities(
            worker,
            task_id=inputs.task_id,
            plan=inputs.plan_path.read_text(encoding="utf-8"),
            workspace=inputs.workspace,
            allowed_read_paths=inputs.allowed_read_paths,
            authorization_ref=authorization_ref,
            disposable_policy_ref=disposable_policy_ref,
            budget=budget,
        )
    finally:
        await worker.close(budget=budget)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "run":
        mode = arguments.mode
        if mode in ("pilot", "deciding") and (
            not arguments.live_authorization_ref or not arguments.disposable_policy_ref
        ):
            parser.error("Pilot and deciding runs require both approval references.")
        if mode == "deciding" and arguments.registration is None:
            parser.error("Deciding runs require a complete registration document.")
        try:
            services = _factory(arguments.factory)(arguments)
            _check_service_mode(
                parser,
                services,
                mode,
                arguments.live_authorization_ref,
                arguments.disposable_policy_ref,
            )
            registration = (
                arguments.registration.read_bytes()
                if arguments.registration is not None
                else None
            )
            report = asyncio.run(
                services.runner.run_sweep(
                    services.inputs_by_task,
                    services.worker_factory,
                    services.task_port,
                    services.schedule,
                    experiment_id=arguments.experiment_id,
                    registration_document=registration,
                    mechanical_style=services.mechanical_style,
                    human_style=services.human_style,
                    decision_value=services.decision_value,
                )
            )
        except (OSError, ValueError, TypeError) as error:
            parser.error(str(error))
        print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
        return 0 if report.status == "completed" else 2

    if arguments.command == "capabilities":
        try:
            services = _factory(arguments.factory)(arguments)
            inputs = services.inputs_by_task[arguments.task_id]
            preflight = services.runner.preflight_task_inputs(inputs)
            if preflight:
                parser.error(
                    "Capability check blocked by task preflight: "
                    + "; ".join(item.message for item in preflight)
                )
            if (
                services.runner.config.live_authorization_ref
                != arguments.live_authorization_ref
                or services.runner.config.disposable_policy_ref
                != arguments.disposable_policy_ref
            ):
                parser.error(
                    "Factory authorization references do not match the command."
                )
            worker = services.worker_factory(inputs, arguments.seed)
            record = asyncio.run(
                _capability_run(
                    services,
                    inputs,
                    worker,
                    arguments.live_authorization_ref,
                    arguments.disposable_policy_ref,
                )
            )
        except (KeyError, OSError, ValueError, TypeError) as error:
            parser.error(str(error))
        print(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True))
        return 0 if record.status == "passed" else 2

    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
