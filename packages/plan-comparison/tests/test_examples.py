import json
from pathlib import Path

import pytest
from typed_packets import SourceRoot, ValidationContext, validate_document

from plan_comparison.adapters.customer_tracker import (
    held_out_customer_tracker_artifacts,
)
from plan_comparison.contracts import ManifestInputs, PacketSource
from plan_comparison.manifest import (
    decode_execution_manifest,
    validate_manifest_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "plan-comparison"
PACKET_ROOT = REPOSITORY_ROOT / "packages" / "typed-packets" / "examples"
REFERENCE_ROOT = REPOSITORY_ROOT / "references" / "customer-tracker" / "examples"
HELD_OUT_ROOT = REPOSITORY_ROOT / "references" / "customer-tracker" / "tasks"
HELD_OUT_PACKAGE = (
    PACKAGE_ROOT / "experiments" / "reference-held-out" / "customer_tracker"
)


def example_inputs() -> tuple[ManifestInputs, ...]:
    customer_tracker = PACKAGE_ROOT / "examples" / "customer_tracker"
    held_out = PACKAGE_ROOT / "experiments" / "reference-held-out" / "customer_tracker"
    return (
        ManifestInputs(
            task_id="E1",
            workspace=REFERENCE_ROOT / "E1" / "start",
            plan_path=customer_tracker / "E1.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e1-model-slice",
                    path=PACKET_ROOT / "customer_tracker" / "E1.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="E2",
            workspace=REFERENCE_ROOT / "E2" / "start",
            plan_path=customer_tracker / "E2.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e2-rules-and-create",
                    path=PACKET_ROOT / "customer_tracker" / "E2.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="E3",
            workspace=REFERENCE_ROOT / "E3" / "start",
            plan_path=customer_tracker / "E3.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-e3-contact-validation",
                    path=customer_tracker / "E3.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H1",
            workspace=REFERENCE_ROOT.parent / "tasks" / "H1" / "start",
            plan_path=held_out / "H1.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h1-search-pagination",
                    path=held_out / "H1.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H2",
            workspace=REFERENCE_ROOT.parent / "tasks" / "H2" / "start",
            plan_path=held_out / "H2.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h2-follow-up-workflow",
                    path=held_out / "H2.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H3",
            workspace=REFERENCE_ROOT.parent / "tasks" / "H3" / "start",
            plan_path=held_out / "H3.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h3-archive-workflow",
                    path=held_out / "H3.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H1",
            workspace=HELD_OUT_ROOT / "H1" / "start",
            plan_path=HELD_OUT_PACKAGE / "H1.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h1-search-pagination",
                    path=HELD_OUT_PACKAGE / "H1.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H2",
            workspace=HELD_OUT_ROOT / "H2" / "start",
            plan_path=HELD_OUT_PACKAGE / "H2.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h2-follow-up-workflow",
                    path=HELD_OUT_PACKAGE / "H2.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="H3",
            workspace=HELD_OUT_ROOT / "H3" / "start",
            plan_path=HELD_OUT_PACKAGE / "H3.plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="customer-tracker-h3-archive-workflow",
                    path=HELD_OUT_PACKAGE / "H3.packet.json",
                ),
            ),
        ),
        ManifestInputs(
            task_id="plain-python",
            workspace=PACKAGE_ROOT / "examples" / "plain_python" / "start",
            plan_path=PACKAGE_ROOT / "examples" / "plain_python" / "plan.md",
            packet_sources=(
                PacketSource(
                    packet_id="plain-python-balance-report",
                    path=PACKET_ROOT / "plain_python.json",
                ),
            ),
        ),
    )


def _manifest_path(task_id: str) -> Path:
    if task_id == "plain-python":
        return PACKAGE_ROOT / "examples" / "plain_python" / "manifest.json"
    if task_id.startswith("H"):
        return (
            PACKAGE_ROOT
            / "experiments"
            / "reference-held-out"
            / "customer_tracker"
            / f"{task_id}.manifest.json"
        )
    if task_id.startswith("H"):
        return HELD_OUT_PACKAGE / f"{task_id}.manifest.json"
    return PACKAGE_ROOT / "examples" / "customer_tracker" / f"{task_id}.manifest.json"


def test_public_example_manifests_match_frozen_plans_packets_and_starts() -> None:
    for inputs in example_inputs():
        manifest_path = _manifest_path(inputs.task_id)
        manifest = decode_execution_manifest(manifest_path.read_text())

        assert validate_manifest_artifacts(manifest, inputs) == (), inputs.task_id


def test_public_packets_validate_against_their_own_start_workspaces() -> None:
    for inputs in example_inputs():
        packet_path = inputs.packet_sources[0].path
        packet = json.loads(packet_path.read_text())
        import_base = "src" if inputs.task_id == "plain-python" else "app"
        context = ValidationContext(
            workspace=inputs.workspace,
            roots=(
                SourceRoot(
                    root_id="workspace",
                    path=inputs.workspace,
                    kind="project",
                    import_base=import_base,
                ),
            ),
        )

        report = validate_document(json.dumps(packet), context)

        assert report.status == "valid", (inputs.task_id, report.diagnostics)


def test_held_out_packets_stay_inside_the_host_access_policy() -> None:
    bundles = held_out_customer_tracker_artifacts(
        REPOSITORY_ROOT, PACKAGE_ROOT, django_source_root=Path("unused")
    )

    for task_id, bundle in bundles.items():
        packet = json.loads(bundle.packet_sources[0].path.read_text())
        manifest = json.loads(bundle.manifest_path.read_text())
        start = HELD_OUT_ROOT / task_id / "start"
        assert bundle.packet_sources[0].packet_id == packet["packet_id"]
        assert [entry["packet_id"] for entry in manifest["packets"]] == [
            packet["packet_id"]
        ]
        readable = {
            path.relative_to(start).as_posix()
            for path in start.rglob("*")
            if path.is_file()
        }

        writes = {change["path"] for change in packet["file_changes"]}
        assert writes <= set(bundle.worker_writable_paths), task_id
        assert set(packet["readable_files"]) <= readable, task_id


@pytest.mark.parametrize(
    ("task_id", "literal"),
    [
        ("H1", "`customer_page`"),
        ("H1", "`query`"),
        ("H2", "`in UTC`"),
        ("H3", "`Archived`"),
    ],
)
def test_names_the_hidden_tests_assert_are_told_to_both_arms(
    task_id: str, literal: str
) -> None:
    task = (HELD_OUT_ROOT / task_id / "task.md").read_text()
    plan = (HELD_OUT_PACKAGE / f"{task_id}.plan.md").read_text()

    assert literal in task
    assert literal in plan


def test_held_out_plan_keeps_the_insert_only_template_rendering() -> None:
    plan = (HELD_OUT_PACKAGE / "H1.plan.md").read_text()

    assert "`customers`" in plan
