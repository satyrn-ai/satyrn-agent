import json
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.model_free._schema import iter_scenarios, load_scenario, load_scenarios

SCHEMA_ROOT = Path(__file__).parents[1]


def valid_document() -> dict[str, Any]:
    return {
        "version": 1,
        "id": "basic",
        "backend": "metal",
        "native": {
            "script": [11, 12],
            "calls": [{"op": "draft", "tokens": [12]}],
            "sampling_defaults": {"temperature": 0.6, "top_k": 20, "top_p": 0.95, "min_p": 0.0},
        },
        "config": {"dflash": "auto", "drafter_path": "drafter.gguf"},
        "rounds": [
            {
                "prompt": "Say hello.",
                "max_tokens": 2,
                "expect": {
                    "reason": "max_tokens",
                    "token_ids": [11, 12],
                    "native_position": 2,
                    "rng": 1,
                    "metrics": {
                        "committed_blocks": 1,
                        "drafts_offered": 1,
                        "drafts_accepted": 1,
                        "replacement_anchors": 0,
                        "discarded_tails": 0,
                    },
                    "metadata": [],
                    "event_types": ["Token", "Token", "Stopped"],
                },
            }
        ],
        "expected_branches": ["anchor"],
    }


def write_document(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document))
    return path


def test_load_valid_scenario_uses_generated_types() -> None:
    scenario = load_scenario(SCHEMA_ROOT / "scenarios" / "basic_round.json")

    assert scenario["id"] == "basic-round"
    assert scenario["native"]["calls"][0]["op"] == "draft"
    assert scenario["rounds"][0]["expect"]["token_ids"] == [11, 12]


def test_iter_scenarios_loads_documents_in_name_order() -> None:
    scenarios = list(iter_scenarios())

    assert [scenario["id"] for scenario in scenarios] == sorted(scenario["id"] for scenario in scenarios)


def test_missing_id_is_rejected(tmp_path: Path) -> None:
    document = valid_document()
    del document["id"]
    path = write_document(tmp_path / "missing.json", document)

    with pytest.raises(ValueError, match="id"):
        load_scenario(path)


def test_boolean_is_not_an_integer(tmp_path: Path) -> None:
    document = valid_document()
    document["rounds"][0]["max_tokens"] = True

    with pytest.raises(ValueError, match="max_tokens"):
        load_scenario(write_document(tmp_path / "boolean.json", document))


def test_unknown_native_operation_is_rejected(tmp_path: Path) -> None:
    document = valid_document()
    document["native"]["calls"][0]["op"] = "unknown"

    with pytest.raises(ValueError, match="op"):
        load_scenario(write_document(tmp_path / "operation.json", document))


def test_invalid_nested_call_is_rejected(tmp_path: Path) -> None:
    document = valid_document()
    document["native"]["calls"][0]["tokens"] = "12"

    with pytest.raises(ValueError, match="tokens"):
        load_scenario(write_document(tmp_path / "nested.json", document))


def test_duplicate_scenario_ids_are_rejected(tmp_path: Path) -> None:
    first = write_document(tmp_path / "first.json", valid_document())
    second = write_document(tmp_path / "second.json", valid_document())

    with pytest.raises(ValueError, match="duplicate"):
        load_scenarios([first, second])
