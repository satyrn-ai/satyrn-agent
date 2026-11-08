import json

import pytest

from plan_comparison.contracts import PacketDigest, RegisteredTaskArtifacts
from plan_comparison.manifest import (
    ManifestDecodeError,
    decode_registration,
    validate_registration_artifacts,
)


def registration_document() -> dict[str, object]:
    return {
        "registration_version": 0,
        "experiment_id": "overnight-domains-v1",
        "model_id": "qwen-27b",
        "model_revision": "model-revision-1",
        "runtime_revision": "runtime-revision-1",
        "tokenizer_revision": "tokenizer-revision-1",
        "tasks": [
            {
                "task_id": f"H{index}",
                "plan_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "packets": [
                    {"packet_id": f"packet-H{index}", "packet_sha256": str(index) * 64}
                ],
            }
            for index in range(1, 4)
        ],
        "task_seed_pairs": [
            {"task_id": f"H{index}", "seed": 7, "arm_order": ["P", "C"]}
            for index in range(1, 4)
        ],
        "tool_policy_sha256": "c" * 64,
        "sampler_settings": {"temperature": 0.2, "top_p": 0.9},
        "thinking_settings": {"mode": "fixed", "budget": 4096},
        "budgets": {"wall_seconds": 3600, "tokens": 50000, "model_calls": 40},
        "p_repair_policy": {"max_retries": 1, "description": "One documented repair."},
        "c_retry_limit": 2,
        "scoring": {
            "behavior": "Run the protected grader once after each arm.",
            "style_mechanical": "Report static diagnostics separately.",
            "style_human": "Use blinded rubric judgments.",
            "timing": "Measure paired end-to-end wall time.",
        },
        "decision_rule": {
            "metric": "paired_behavior_pass_rate",
            "direction": "at_least",
            "threshold": 0.8,
            "unit": "fraction",
        },
    }


def test_registration_decodes_complete_held_out_contract() -> None:
    registration = decode_registration(json.dumps(registration_document()))

    assert tuple(task.task_id for task in registration.tasks) == ("H1", "H2", "H3")
    assert registration.c_retry_limit == 2
    assert registration.task_seed_pairs[1].arm_order == ("P", "C")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value["tasks"].pop(), "schema.empty_array"),
        (lambda value: value.update(c_retry_limit=3), "registration.retry_limit"),
        (lambda value: value.update(c_retry_limit=True), "schema.integer"),
        (
            lambda value: value["decision_rule"].update(threshold=True),
            "registration.threshold",
        ),
        (
            lambda value: value["tasks"][0].update(unexpected=True),
            "schema.unknown_field",
        ),
    ],
)
def test_registration_rejects_incomplete_or_invalid_decisions(
    mutate, code: str
) -> None:
    document = registration_document()
    mutate(document)

    with pytest.raises(ManifestDecodeError) as error:
        decode_registration(json.dumps(document))

    assert error.value.code == code


def test_registration_requires_at_least_one_seed_for_each_held_out_task() -> None:
    document = registration_document()
    document["task_seed_pairs"] = [
        pair for pair in document["task_seed_pairs"] if pair["task_id"] != "H1"
    ]
    document["task_seed_pairs"].append(
        {"task_id": "H2", "seed": 8, "arm_order": ["P", "C"]}
    )

    with pytest.raises(ManifestDecodeError) as error:
        decode_registration(json.dumps(document))

    assert error.value.code == "registration.missing_task_pairs"


def test_registration_requires_each_pair_to_include_both_arms() -> None:
    document = registration_document()
    document["task_seed_pairs"][0]["arm_order"] = ["P", "P"]

    with pytest.raises(ManifestDecodeError) as error:
        decode_registration(json.dumps(document))

    assert error.value.code == "registration.arm_order"


def test_registration_rejects_duplicate_task_seed_pairs() -> None:
    document = registration_document()
    document["task_seed_pairs"].append(document["task_seed_pairs"][0].copy())

    with pytest.raises(ManifestDecodeError) as error:
        decode_registration(json.dumps(document))

    assert error.value.code == "registration.duplicate_task_seed"


def test_registration_artifact_validation_accepts_exact_hashes() -> None:
    registration = decode_registration(json.dumps(registration_document()))
    artifacts = tuple(
        RegisteredTaskArtifacts(
            task_id=task.task_id,
            plan_sha256=task.plan_sha256,
            manifest_sha256=task.manifest_sha256,
            packets=task.packets,
        )
        for task in registration.tasks
    )

    assert validate_registration_artifacts(registration, artifacts) == ()


def test_registration_artifact_validation_rejects_mismatched_hashes() -> None:
    registration = decode_registration(json.dumps(registration_document()))
    artifacts = tuple(
        RegisteredTaskArtifacts(
            task_id=task.task_id,
            plan_sha256="d" * 64 if task.task_id == "H1" else task.plan_sha256,
            manifest_sha256=task.manifest_sha256,
            packets=task.packets,
        )
        for task in registration.tasks
    )

    diagnostics = validate_registration_artifacts(registration, artifacts)

    assert "registration.plan_hash_mismatch" in {item.code for item in diagnostics}


def test_registration_artifact_validation_rejects_packet_hash_mismatch() -> None:
    registration = decode_registration(json.dumps(registration_document()))
    artifacts = tuple(
        RegisteredTaskArtifacts(
            task_id=task.task_id,
            plan_sha256=task.plan_sha256,
            manifest_sha256=task.manifest_sha256,
            packets=(PacketDigest(packet_id="other-packet", packet_sha256="e" * 64),)
            if task.task_id == "H2"
            else task.packets,
        )
        for task in registration.tasks
    )

    diagnostics = validate_registration_artifacts(registration, artifacts)

    assert "registration.packet_hash_mismatch" in {item.code for item in diagnostics}
