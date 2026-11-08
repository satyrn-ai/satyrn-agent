import json

import pytest

from tests.packet_factory import valid_packet
from typed_packets import contract


def test_packet_round_trip_preserves_contract() -> None:
    packet = contract.decode_packet(json.dumps(valid_packet()))

    assert contract.decode_packet(contract.encode_packet(packet)) == packet


@pytest.mark.parametrize(
    ("document", "field"),
    [
        ('{"schema_version":0,"schema_version":0}', "/schema_version"),
        (json.dumps(valid_packet() | {"unexpected": True}), "/unexpected"),
        (json.dumps(valid_packet() | {"schema_version": True}), "/schema_version"),
        (json.dumps(valid_packet() | {"schema_version": 1}), "/schema_version"),
        (json.dumps(valid_packet() | {"task": "  "}), "/task"),
        (json.dumps(valid_packet() | {"task": float("inf")}), "/task"),
    ],
)
def test_decode_rejects_invalid_json_contract(document: str, field: str) -> None:
    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(document)

    assert error.value.field == field


def test_decode_rejects_unknown_nested_fields() -> None:
    packet = valid_packet()
    packet["gates"][0]["unexpected"] = True

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/gates/0/unexpected"


def test_decode_rejects_duplicate_nested_json_keys() -> None:
    document = json.dumps(valid_packet()).replace(
        '"operation": "modify"',
        '"operation": "modify", "operation": "delete"',
        1,
    )

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(document)

    assert error.value.field == "/file_changes/0/operation"


def test_decode_rejects_malformed_json() -> None:
    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet("{")

    assert error.value.code == "json.syntax"
    assert error.value.field == ""


def test_decode_rejects_malformed_declaration_and_test_source() -> None:
    packet = valid_packet()
    packet["produces"][0]["declaration"] = "def unrelated(:"

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/produces/0/declaration"

    packet = valid_packet()
    packet["tests"][0]["content"] = "def broken(:"
    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))
    assert error.value.field == "/tests/0/content"


def test_decode_rejects_produced_declaration_name_mismatch() -> None:
    packet = valid_packet()
    packet["produces"][0]["declaration"] = "def another_rule(value: str) -> bool:"

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/produces/0/declaration"


def test_decode_rejects_test_operation_mismatch() -> None:
    packet = valid_packet()
    packet["file_changes"][1]["operation"] = "modify"

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/tests/0/path"


def test_decode_rejects_duplicate_test_artifact_paths() -> None:
    packet = valid_packet()
    packet["tests"].append(packet["tests"][0].copy())

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/tests/1/path"


def test_decode_rejects_conflicting_import_bindings() -> None:
    packet = valid_packet()
    packet["imports"] = [
        {
            "path": "app/domain.py",
            "module": "crm.contacts",
            "name": "Contact",
            "alias": None,
            "target": "existing",
        },
        {
            "path": "app/domain.py",
            "module": "crm.alternate_contacts",
            "name": "Contact",
            "alias": None,
            "target": "existing",
        },
    ]

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/imports/1/alias"


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "Contact.Other"), ("alias", "Local.Name")],
)
def test_decode_requires_import_names_to_be_identifiers(field: str, value: str) -> None:
    packet = valid_packet()
    packet["imports"] = [
        {
            "path": "app/domain.py",
            "module": "crm.contacts",
            "name": "Contact",
            "alias": None,
            "target": "existing",
        }
    ]
    packet["imports"][0][field] = value

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == f"/imports/0/{field}"


def test_decode_rejects_duplicate_file_operations() -> None:
    packet = valid_packet()
    packet["file_changes"].append({"path": "app/domain.py", "operation": "delete"})

    with pytest.raises(contract.PacketDecodeError) as error:
        contract.decode_packet(json.dumps(packet))

    assert error.value.field == "/file_changes/2/path"
