import ast
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from typed_packets import PacketDecodeError, decode_packet
from typed_packets.contract import Packet

from plan_comparison.contracts import (
    Arm,
    BudgetLimits,
    ByteExtent,
    CallableBodyExtent,
    CallableBodyTarget,
    DecisionRule,
    ExecutionManifest,
    ManifestDiagnostic,
    ManifestInputs,
    PacketDigest,
    PacketExecution,
    PacketSource,
    Placement,
    RedCheck,
    RegisteredTaskArtifacts,
    Registration,
    RegistrationDirection,
    RegistrationScalar,
    RegistrationSetting,
    RegistrationTask,
    RepairPolicy,
    ScoringProcedures,
    Slot,
    SlotExtent,
    SlotKind,
    SlotOperation,
    StructuralExtent,
    StructuralTarget,
    TaskSeedPair,
    TextAnchorTarget,
    WholeFileExtent,
    WholeFileTarget,
)

type JsonObject = dict[str, object]
type ManifestOutcome = Literal["invalid", "inconclusive"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_HELD_OUT_TASKS = ("H1", "H2", "H3")


class ManifestDecodeError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message
        super().__init__(self.__str__())

    def __str__(self) -> str:
        location = self.field or "/"
        return f"{self.code} at {location}: {self.message}"


@dataclass(frozen=True, slots=True)
class _ObjectPairs:
    pairs: tuple[tuple[str, object], ...]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _object_pairs_hook(pairs: list[tuple[str, object]]) -> _ObjectPairs:
    return _ObjectPairs(tuple(pairs))


def _reject_constant(value: str) -> object:
    raise ManifestDecodeError("", "json.non_finite", f"non-finite number {value}")


def _pointer_child(field: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{field}/{escaped}"


def _materialize(value: object, field: str = "") -> object:
    if isinstance(value, _ObjectPairs):
        result: JsonObject = {}
        for key, child in value.pairs:
            child_field = _pointer_child(field, key)
            if key in result:
                raise ManifestDecodeError(
                    child_field, "json.duplicate_key", "duplicate JSON object key"
                )
            result[key] = _materialize(child, child_field)
        return result
    if isinstance(value, list):
        return [
            _materialize(child, _pointer_child(field, index))
            for index, child in enumerate(value)
        ]
    return value


def _parse_document(document: str) -> object:
    try:
        parsed = json.loads(
            document,
            object_pairs_hook=_object_pairs_hook,
            parse_constant=_reject_constant,
        )
    except ManifestDecodeError:
        raise
    except json.JSONDecodeError as error:
        raise ManifestDecodeError("", "json.syntax", error.msg) from error
    return _materialize(parsed)


def _record(value: object, field: str, expected: tuple[str, ...]) -> JsonObject:
    if not isinstance(value, dict):
        raise ManifestDecodeError(field, "schema.type", "expected an object")
    record = cast(JsonObject, value)
    allowed = set(expected)
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise ManifestDecodeError(
            _pointer_child(field, unknown[0]), "schema.unknown_field", "unknown field"
        )
    missing = [key for key in expected if key not in record]
    if missing:
        raise ManifestDecodeError(
            _pointer_child(field, missing[0]),
            "schema.missing_field",
            "required field is missing",
        )
    return record


def _array(value: object, field: str, *, minimum: int = 0) -> list[object]:
    if not isinstance(value, list):
        raise ManifestDecodeError(field, "schema.type", "expected an array")
    if len(value) < minimum:
        raise ManifestDecodeError(
            field, "schema.empty_array", f"expected at least {minimum} item(s)"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestDecodeError(field, "schema.string", "expected a nonblank string")
    return value


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestDecodeError(field, "schema.integer", "expected an integer")
    if minimum is not None and value < minimum:
        raise ManifestDecodeError(
            field, "schema.range", f"expected an integer of at least {minimum}"
        )
    return value


def _sha256(value: object, field: str) -> str:
    text = _string(value, field)
    if _SHA256.fullmatch(text) is None:
        raise ManifestDecodeError(
            field, "schema.sha256", "expected a lowercase 64-character SHA-256 digest"
        )
    return text


def _nullable_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field)


def _relative_path(value: object, field: str) -> str:
    path = _string(value, field)
    pure = PurePosixPath(path)
    invalid = (
        pure.is_absolute()
        or "\\" in path
        or path.startswith("//")
        or re.match(r"^[A-Za-z]:", path) is not None
        or any(part in ("", ".", "..") for part in path.split("/"))
        or any(character in path for character in "*?[]")
        or str(pure) != path
    )
    if invalid:
        raise ManifestDecodeError(
            field, "schema.path", "expected a canonical relative POSIX file path"
        )
    return path


def _identifier_path(value: object, field: str) -> str:
    text = _string(value, field)
    if _IDENTIFIER_PATH.fullmatch(text) is None:
        raise ManifestDecodeError(
            field, "schema.qualified_name", "expected a dotted Python qualified name"
        )
    return text


def _enum(value: object, field: str, options: tuple[str, ...]) -> str:
    text = _string(value, field)
    if text not in options:
        raise ManifestDecodeError(
            field,
            "schema.choice",
            f"expected one of {', '.join(options)}",
        )
    return text


def _decode_extent(value: object, field: str) -> SlotExtent:
    if not isinstance(value, dict):
        raise ManifestDecodeError(field, "schema.type", "expected an extent object")
    record = cast(JsonObject, value)
    extent_kind = _enum(
        record.get("kind"),
        _pointer_child(field, "kind"),
        ("bytes", "callable_body", "structural", "whole_file"),
    )
    if extent_kind == "bytes":
        record = _record(value, field, ("kind", "start_byte", "end_byte"))
        start = _integer(
            record["start_byte"], _pointer_child(field, "start_byte"), minimum=0
        )
        end = _integer(record["end_byte"], _pointer_child(field, "end_byte"), minimum=0)
        if end < start:
            raise ManifestDecodeError(
                field, "manifest.extent_order", "end_byte must not precede start_byte"
            )
        return ByteExtent(start_byte=start, end_byte=end)
    if extent_kind == "callable_body":
        _record(value, field, ("kind",))
        return CallableBodyExtent()
    if extent_kind == "structural":
        record = _record(value, field, ("kind", "region"))
        return StructuralExtent(
            region=cast(
                Literal["body", "definition"],
                _enum(
                    record["region"],
                    _pointer_child(field, "region"),
                    ("body", "definition"),
                ),
            )
        )
    _record(value, field, ("kind",))
    return WholeFileExtent()


def _decode_target(
    value: object, field: str
) -> CallableBodyTarget | StructuralTarget | TextAnchorTarget | WholeFileTarget:
    if not isinstance(value, dict):
        raise ManifestDecodeError(field, "schema.type", "expected a target object")
    target_record = cast(JsonObject, value)
    target_kind = _enum(
        target_record.get("kind"),
        _pointer_child(field, "kind"),
        ("callable", "structural", "text_anchor", "whole_file"),
    )
    if target_kind == "callable":
        record = _record(value, field, ("kind", "qualified_name"))
        return CallableBodyTarget(
            qualified_name=_identifier_path(
                record["qualified_name"], _pointer_child(field, "qualified_name")
            )
        )
    if target_kind == "structural":
        record = _record(value, field, ("kind", "qualified_name"))
        return StructuralTarget(
            qualified_name=_identifier_path(
                record["qualified_name"], _pointer_child(field, "qualified_name")
            )
        )
    if target_kind == "text_anchor":
        record = _record(value, field, ("kind", "anchor"))
        return TextAnchorTarget(
            anchor=_string(record["anchor"], _pointer_child(field, "anchor"))
        )
    _record(value, field, ("kind",))
    return WholeFileTarget()


def _decode_slot(value: object, field: str) -> Slot:
    record = _record(
        value,
        field,
        (
            "slot_id",
            "path",
            "kind",
            "operation",
            "target",
            "extent",
            "preimage_sha256",
        ),
    )
    kind = cast(
        SlotKind,
        _enum(
            record["kind"],
            _pointer_child(field, "kind"),
            ("callable_body", "ancillary"),
        ),
    )
    operation = cast(
        SlotOperation,
        _enum(
            record["operation"],
            _pointer_child(field, "operation"),
            ("replace_body", "replace", "insert_before", "insert_after", "create_file"),
        ),
    )
    target = _decode_target(record["target"], _pointer_child(field, "target"))
    extent = _decode_extent(record["extent"], _pointer_child(field, "extent"))
    preimage_sha256 = _nullable_sha256(
        record["preimage_sha256"], _pointer_child(field, "preimage_sha256")
    )
    if kind == "callable_body":
        if (
            operation != "replace_body"
            or not isinstance(target, CallableBodyTarget)
            or not isinstance(extent, CallableBodyExtent)
        ):
            raise ManifestDecodeError(
                field,
                "manifest.callable_slot_shape",
                "callable-body slots require a callable target, callable_body extent, "
                "and replace_body operation",
            )
    else:
        if isinstance(target, CallableBodyTarget) or operation == "replace_body":
            raise ManifestDecodeError(
                field,
                "manifest.ancillary_slot_shape",
                "ancillary slots cannot target callable bodies",
            )
        if operation == "create_file":
            if not isinstance(target, WholeFileTarget) or not isinstance(
                extent, WholeFileExtent
            ):
                raise ManifestDecodeError(
                    field,
                    "manifest.whole_file_slot_shape",
                    "create_file slots require a whole_file target and extent",
                )
        elif isinstance(target, WholeFileTarget) or isinstance(extent, WholeFileExtent):
            raise ManifestDecodeError(
                field,
                "manifest.whole_file_slot_shape",
                "whole-file targets are only valid for create_file slots",
            )
        elif isinstance(target, StructuralTarget) != isinstance(
            extent, StructuralExtent
        ):
            raise ManifestDecodeError(
                field,
                "manifest.structural_slot_shape",
                "structural targets require structural extents, while text anchors "
                "require byte extents",
            )
        elif isinstance(target, TextAnchorTarget) != isinstance(extent, ByteExtent):
            raise ManifestDecodeError(
                field,
                "manifest.anchor_slot_shape",
                "text anchors require byte extents",
            )
        if (
            operation == "replace"
            and isinstance(extent, ByteExtent)
            and extent.start_byte == extent.end_byte
        ):
            raise ManifestDecodeError(
                field,
                "manifest.empty_replace",
                "replace slots require a nonempty byte extent",
            )
        if (
            operation in ("insert_before", "insert_after")
            and isinstance(extent, ByteExtent)
            and extent.start_byte != extent.end_byte
        ):
            raise ManifestDecodeError(
                field,
                "manifest.nonempty_insert",
                "insertion slots require a zero-width extent",
            )
    if isinstance(extent, WholeFileExtent) and preimage_sha256 is not None:
        raise ManifestDecodeError(
            _pointer_child(field, "preimage_sha256"),
            "manifest.whole_file_preimage",
            "new whole-file targets cannot declare an existing preimage",
        )
    return Slot(
        slot_id=_string(record["slot_id"], _pointer_child(field, "slot_id")),
        path=_relative_path(record["path"], _pointer_child(field, "path")),
        kind=kind,
        operation=operation,
        target=target,
        extent=extent,
        preimage_sha256=preimage_sha256,
    )


def _decode_placement(value: object, field: str) -> Placement:
    record = _record(
        value,
        field,
        (
            "placement_id",
            "path",
            "kind",
            "target",
            "position",
            "anchor",
            "preimage_sha256",
        ),
    )
    kind = cast(
        Literal["imports", "declarations"],
        _enum(
            record["kind"], _pointer_child(field, "kind"), ("imports", "declarations")
        ),
    )
    target = _string(record["target"], _pointer_child(field, "target"))
    if target != "module" and not target.startswith("class:"):
        raise ManifestDecodeError(
            _pointer_child(field, "target"),
            "manifest.placement_target",
            "target must be 'module' or 'class:<qualified_name>'",
        )
    if target.startswith("class:"):
        _identifier_path(target.removeprefix("class:"), _pointer_child(field, "target"))
    position = cast(
        Literal["before", "after", "start", "end"],
        _enum(
            record["position"],
            _pointer_child(field, "position"),
            ("before", "after", "start", "end"),
        ),
    )
    anchor_value = record["anchor"]
    anchor = (
        None
        if anchor_value is None
        else _string(anchor_value, _pointer_child(field, "anchor"))
    )
    if position in ("before", "after") and anchor is None:
        raise ManifestDecodeError(
            _pointer_child(field, "anchor"),
            "manifest.placement_anchor",
            "before/after placements require an exact text anchor",
        )
    if position in ("start", "end") and anchor is not None:
        raise ManifestDecodeError(
            _pointer_child(field, "anchor"),
            "manifest.placement_anchor",
            "start/end placements cannot include an anchor",
        )
    preimage_sha256 = _nullable_sha256(
        record["preimage_sha256"], _pointer_child(field, "preimage_sha256")
    )
    if (anchor is None) != (preimage_sha256 is None):
        raise ManifestDecodeError(
            _pointer_child(field, "preimage_sha256"),
            "manifest.placement_preimage",
            "only exact text-anchor placements carry a preimage hash",
        )
    return Placement(
        placement_id=_string(
            record["placement_id"], _pointer_child(field, "placement_id")
        ),
        path=_relative_path(record["path"], _pointer_child(field, "path")),
        kind=kind,
        target=target,
        position=position,
        anchor=anchor,
        preimage_sha256=preimage_sha256,
    )


def _decode_red_check(value: object, field: str) -> RedCheck:
    record = _record(
        value, field, ("path", "test_node", "expected_exception", "marker")
    )
    node = _string(record["test_node"], _pointer_child(field, "test_node"))
    if _IDENTIFIER_PATH.fullmatch(node) is None:
        raise ManifestDecodeError(
            _pointer_child(field, "test_node"),
            "manifest.test_node",
            "test_node must be a dotted Python identifier",
        )
    exception = _string(
        record["expected_exception"], _pointer_child(field, "expected_exception")
    )
    if _IDENTIFIER_PATH.fullmatch(exception) is None:
        raise ManifestDecodeError(
            _pointer_child(field, "expected_exception"),
            "manifest.exception_name",
            "expected_exception must be a Python exception name",
        )
    return RedCheck(
        path=_relative_path(record["path"], _pointer_child(field, "path")),
        test_node=node,
        expected_exception=exception,
        marker=_string(record["marker"], _pointer_child(field, "marker")),
    )


def _overlap(left: Slot, right: Slot) -> bool:
    left_extent, right_extent = left.extent, right.extent
    if isinstance(left.target, TextAnchorTarget) and isinstance(
        right.target, TextAnchorTarget
    ):
        return left.target.anchor == right.target.anchor
    if isinstance(left.target, TextAnchorTarget) or isinstance(
        right.target, TextAnchorTarget
    ):
        return False
    if isinstance(left_extent, WholeFileExtent) or isinstance(
        right_extent, WholeFileExtent
    ):
        return True
    if isinstance(left_extent, CallableBodyExtent) and isinstance(
        right_extent, CallableBodyExtent
    ):
        return (
            isinstance(left.target, CallableBodyTarget)
            and isinstance(right.target, CallableBodyTarget)
            and left.target.qualified_name == right.target.qualified_name
        )
    if isinstance(left_extent, StructuralExtent) and isinstance(
        right_extent, StructuralExtent
    ):
        return (
            isinstance(left.target, StructuralTarget)
            and isinstance(right.target, StructuralTarget)
            and left.target.qualified_name == right.target.qualified_name
        )
    if isinstance(left_extent, ByteExtent) and isinstance(right_extent, ByteExtent):
        if left_extent.start_byte == left_extent.end_byte:
            point = left_extent.start_byte
            return right_extent.start_byte <= point <= right_extent.end_byte
        if right_extent.start_byte == right_extent.end_byte:
            point = right_extent.start_byte
            return left_extent.start_byte <= point <= left_extent.end_byte
        return max(left_extent.start_byte, right_extent.start_byte) < min(
            left_extent.end_byte, right_extent.end_byte
        )
    return False


def _decode_packet_execution(value: object, field: str) -> PacketExecution:
    record = _record(
        value,
        field,
        ("packet_id", "packet_sha256", "slots", "placements", "red_checks"),
    )
    slots = tuple(
        _decode_slot(item, _pointer_child(_pointer_child(field, "slots"), index))
        for index, item in enumerate(
            _array(record["slots"], _pointer_child(field, "slots"), minimum=1)
        )
    )
    placements = tuple(
        _decode_placement(
            item, _pointer_child(_pointer_child(field, "placements"), index)
        )
        for index, item in enumerate(
            _array(record["placements"], _pointer_child(field, "placements"))
        )
    )
    red_checks = tuple(
        _decode_red_check(
            item, _pointer_child(_pointer_child(field, "red_checks"), index)
        )
        for index, item in enumerate(
            _array(record["red_checks"], _pointer_child(field, "red_checks"), minimum=1)
        )
    )
    for collection, name, key in (
        (slots, "slots", lambda item: item.slot_id),
        (placements, "placements", lambda item: item.placement_id),
        (red_checks, "red_checks", lambda item: (item.path, item.test_node)),
    ):
        seen: set[object] = set()
        for index, item in enumerate(collection):
            item_key = key(item)
            if item_key in seen:
                raise ManifestDecodeError(
                    _pointer_child(_pointer_child(field, name), index),
                    f"manifest.duplicate_{name}",
                    f"duplicate {name[:-1]} declaration",
                )
            seen.add(item_key)
    for index, slot in enumerate(slots):
        for prior in slots[:index]:
            if slot.path == prior.path and _overlap(prior, slot):
                raise ManifestDecodeError(
                    _pointer_child(_pointer_child(field, "slots"), index),
                    "manifest.overlapping_slots",
                    f"slot {slot.slot_id!r} overlaps {prior.slot_id!r}",
                )
    placement_targets: set[tuple[str, str, str, str | None]] = set()
    for index, placement in enumerate(placements):
        key = (placement.path, placement.target, placement.position, placement.anchor)
        if key in placement_targets:
            raise ManifestDecodeError(
                _pointer_child(_pointer_child(field, "placements"), index),
                "manifest.overlapping_placements",
                "multiple placements target the same insertion point",
            )
        placement_targets.add(key)
    return PacketExecution(
        packet_id=_string(record["packet_id"], _pointer_child(field, "packet_id")),
        packet_sha256=_sha256(
            record["packet_sha256"], _pointer_child(field, "packet_sha256")
        ),
        slots=slots,
        placements=placements,
        red_checks=red_checks,
    )


def decode_execution_manifest(document: str) -> ExecutionManifest:
    record = _record(
        _parse_document(document),
        "",
        ("manifest_version", "task_id", "plan_sha256", "packets"),
    )
    version = _integer(record["manifest_version"], "/manifest_version", minimum=0)
    if version != 0:
        raise ManifestDecodeError(
            "/manifest_version",
            "manifest.version",
            "only manifest version 0 is supported",
        )
    packets = tuple(
        _decode_packet_execution(item, _pointer_child("/packets", index))
        for index, item in enumerate(_array(record["packets"], "/packets", minimum=1))
    )
    packet_ids = [packet.packet_id for packet in packets]
    if len(set(packet_ids)) != len(packet_ids):
        duplicate = next(
            index
            for index, packet_id in enumerate(packet_ids)
            if packet_id in packet_ids[:index]
        )
        raise ManifestDecodeError(
            _pointer_child("/packets", duplicate),
            "manifest.duplicate_packets",
            "packet IDs must be unique",
        )
    return ExecutionManifest(
        manifest_version=version,
        task_id=_string(record["task_id"], "/task_id"),
        plan_sha256=_sha256(record["plan_sha256"], "/plan_sha256"),
        packets=packets,
    )


def _decode_packet_digest(value: object, field: str) -> PacketDigest:
    record = _record(value, field, ("packet_id", "packet_sha256"))
    return PacketDigest(
        packet_id=_string(record["packet_id"], _pointer_child(field, "packet_id")),
        packet_sha256=_sha256(
            record["packet_sha256"], _pointer_child(field, "packet_sha256")
        ),
    )


def _decode_registration_task(value: object, field: str) -> RegistrationTask:
    record = _record(
        value, field, ("task_id", "plan_sha256", "manifest_sha256", "packets")
    )
    packets = tuple(
        _decode_packet_digest(
            item, _pointer_child(_pointer_child(field, "packets"), index)
        )
        for index, item in enumerate(
            _array(record["packets"], _pointer_child(field, "packets"), minimum=1)
        )
    )
    packet_ids = [packet.packet_id for packet in packets]
    if len(set(packet_ids)) != len(packet_ids):
        duplicate = next(
            index
            for index, packet_id in enumerate(packet_ids)
            if packet_id in packet_ids[:index]
        )
        raise ManifestDecodeError(
            _pointer_child(_pointer_child(field, "packets"), duplicate),
            "registration.duplicate_packets",
            "packet IDs must be unique within a task",
        )
    return RegistrationTask(
        task_id=_string(record["task_id"], _pointer_child(field, "task_id")),
        plan_sha256=_sha256(
            record["plan_sha256"], _pointer_child(field, "plan_sha256")
        ),
        manifest_sha256=_sha256(
            record["manifest_sha256"], _pointer_child(field, "manifest_sha256")
        ),
        packets=packets,
    )


def _decode_task_seed(value: object, field: str) -> TaskSeedPair:
    record = _record(value, field, ("task_id", "seed", "arm_order"))
    arm_order = _array(
        record["arm_order"], _pointer_child(field, "arm_order"), minimum=2
    )
    if len(arm_order) != 2:
        raise ManifestDecodeError(
            _pointer_child(field, "arm_order"),
            "registration.arm_order",
            "each pair must run both arms exactly once",
        )
    arms = tuple(
        cast(
            Arm,
            _enum(
                arm,
                _pointer_child(_pointer_child(field, "arm_order"), index),
                ("P", "C"),
            ),
        )
        for index, arm in enumerate(arm_order)
    )
    if set(arms) != {"P", "C"}:
        raise ManifestDecodeError(
            _pointer_child(field, "arm_order"),
            "registration.arm_order",
            "arm_order must contain P and C exactly once",
        )
    return TaskSeedPair(
        task_id=_string(record["task_id"], _pointer_child(field, "task_id")),
        seed=_integer(record["seed"], _pointer_child(field, "seed"), minimum=0),
        arm_order=cast(tuple[Arm, Arm], arms),
    )


def _decode_settings(value: object, field: str) -> tuple[RegistrationSetting, ...]:
    if not isinstance(value, dict) or not value:
        raise ManifestDecodeError(
            field, "registration.settings", "expected a nonempty scalar object"
        )
    settings: list[RegistrationSetting] = []
    for name in sorted(value):
        setting = value[name]
        if not isinstance(name, str) or not name.strip():
            raise ManifestDecodeError(
                field, "registration.settings", "setting names must be nonblank"
            )
        if not (
            setting is None
            or isinstance(setting, (str, bool, int))
            or (isinstance(setting, float) and math.isfinite(setting))
        ):
            raise ManifestDecodeError(
                _pointer_child(field, name),
                "registration.setting_value",
                "settings must be JSON scalar values",
            )
        if isinstance(setting, str) and not setting.strip():
            raise ManifestDecodeError(
                _pointer_child(field, name),
                "registration.setting_value",
                "string settings must be nonblank",
            )
        settings.append((name, cast(RegistrationScalar, setting)))
    return tuple(settings)


def _decode_budget(value: object, field: str) -> BudgetLimits:
    record = _record(value, field, ("wall_seconds", "tokens", "model_calls"))
    return BudgetLimits(
        wall_seconds=_integer(
            record["wall_seconds"], _pointer_child(field, "wall_seconds"), minimum=1
        ),
        tokens=_integer(record["tokens"], _pointer_child(field, "tokens"), minimum=1),
        model_calls=_integer(
            record["model_calls"], _pointer_child(field, "model_calls"), minimum=1
        ),
    )


def _decode_repair_policy(value: object, field: str) -> RepairPolicy:
    record = _record(value, field, ("max_retries", "description"))
    return RepairPolicy(
        max_retries=_integer(
            record["max_retries"], _pointer_child(field, "max_retries"), minimum=0
        ),
        description=_string(
            record["description"], _pointer_child(field, "description")
        ),
    )


def _decode_scoring(value: object, field: str) -> ScoringProcedures:
    record = _record(
        value, field, ("behavior", "style_mechanical", "style_human", "timing")
    )
    return ScoringProcedures(
        behavior=_string(record["behavior"], _pointer_child(field, "behavior")),
        style_mechanical=_string(
            record["style_mechanical"], _pointer_child(field, "style_mechanical")
        ),
        style_human=_string(
            record["style_human"], _pointer_child(field, "style_human")
        ),
        timing=_string(record["timing"], _pointer_child(field, "timing")),
    )


def _decode_decision_rule(value: object, field: str) -> DecisionRule:
    record = _record(value, field, ("metric", "direction", "threshold", "unit"))
    threshold = record["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ManifestDecodeError(
            _pointer_child(field, "threshold"),
            "registration.threshold",
            "decision threshold must be numeric and not boolean",
        )
    if isinstance(threshold, float) and not math.isfinite(threshold):
        raise ManifestDecodeError(
            _pointer_child(field, "threshold"),
            "registration.threshold",
            "decision threshold must be finite",
        )
    return DecisionRule(
        metric=_string(record["metric"], _pointer_child(field, "metric")),
        direction=cast(
            RegistrationDirection,
            _enum(
                record["direction"],
                _pointer_child(field, "direction"),
                ("at_least", "at_most"),
            ),
        ),
        threshold=threshold,
        unit=_string(record["unit"], _pointer_child(field, "unit")),
    )


def decode_registration(document: str) -> Registration:
    field_names = (
        "registration_version",
        "experiment_id",
        "model_id",
        "model_revision",
        "runtime_revision",
        "tokenizer_revision",
        "tasks",
        "task_seed_pairs",
        "tool_policy_sha256",
        "sampler_settings",
        "thinking_settings",
        "budgets",
        "p_repair_policy",
        "c_retry_limit",
        "scoring",
        "decision_rule",
    )
    record = _record(_parse_document(document), "", field_names)
    version = _integer(
        record["registration_version"], "/registration_version", minimum=0
    )
    if version != 0:
        raise ManifestDecodeError(
            "/registration_version",
            "registration.version",
            "only registration version 0 is supported",
        )
    tasks = tuple(
        _decode_registration_task(item, _pointer_child("/tasks", index))
        for index, item in enumerate(_array(record["tasks"], "/tasks", minimum=3))
    )
    task_ids = tuple(task.task_id for task in tasks)
    if task_ids != _HELD_OUT_TASKS:
        raise ManifestDecodeError(
            "/tasks",
            "registration.held_out_tasks",
            "deciding registrations must include H1, H2, and H3 exactly once in order",
        )
    task_seed_pairs = tuple(
        _decode_task_seed(item, _pointer_child("/task_seed_pairs", index))
        for index, item in enumerate(
            _array(record["task_seed_pairs"], "/task_seed_pairs", minimum=3)
        )
    )
    seen_pairs: set[tuple[str, int]] = set()
    for index, pair in enumerate(task_seed_pairs):
        key = (pair.task_id, pair.seed)
        if pair.task_id not in _HELD_OUT_TASKS:
            raise ManifestDecodeError(
                _pointer_child(_pointer_child("/task_seed_pairs", index), "task_id"),
                "registration.unknown_task",
                "task_seed_pairs may reference only H1, H2, and H3",
            )
        if key in seen_pairs:
            raise ManifestDecodeError(
                _pointer_child("/task_seed_pairs", index),
                "registration.duplicate_task_seed",
                "task/seed pairs must be unique",
            )
        seen_pairs.add(key)
    missing_tasks = [
        task_id
        for task_id in _HELD_OUT_TASKS
        if not any(pair.task_id == task_id for pair in task_seed_pairs)
    ]
    if missing_tasks:
        raise ManifestDecodeError(
            "/task_seed_pairs",
            "registration.missing_task_pairs",
            f"missing task repetitions for {missing_tasks[0]}",
        )
    c_retry_limit = _integer(record["c_retry_limit"], "/c_retry_limit", minimum=0)
    if c_retry_limit > 2:
        raise ManifestDecodeError(
            "/c_retry_limit",
            "registration.retry_limit",
            "compiled retries may not exceed two",
        )
    return Registration(
        registration_version=version,
        experiment_id=_string(record["experiment_id"], "/experiment_id"),
        model_id=_string(record["model_id"], "/model_id"),
        model_revision=_string(record["model_revision"], "/model_revision"),
        runtime_revision=_string(record["runtime_revision"], "/runtime_revision"),
        tokenizer_revision=_string(record["tokenizer_revision"], "/tokenizer_revision"),
        tasks=tasks,
        task_seed_pairs=task_seed_pairs,
        tool_policy_sha256=_sha256(record["tool_policy_sha256"], "/tool_policy_sha256"),
        sampler_settings=_decode_settings(
            record["sampler_settings"], "/sampler_settings"
        ),
        thinking_settings=_decode_settings(
            record["thinking_settings"], "/thinking_settings"
        ),
        budgets=_decode_budget(record["budgets"], "/budgets"),
        p_repair_policy=_decode_repair_policy(
            record["p_repair_policy"], "/p_repair_policy"
        ),
        c_retry_limit=c_retry_limit,
        scoring=_decode_scoring(record["scoring"], "/scoring"),
        decision_rule=_decode_decision_rule(record["decision_rule"], "/decision_rule"),
    )


def _diagnostic(
    code: str,
    field: str,
    message: str,
    *,
    path: str | None = None,
    packet_id: str | None = None,
    outcome: ManifestOutcome = "invalid",
) -> ManifestDiagnostic:
    return ManifestDiagnostic(
        code=code,
        field=field,
        message=message,
        outcome=outcome,
        path=path,
        packet_id=packet_id,
    )


def _workspace_file(
    workspace: Path, relative_path: str
) -> tuple[Path, bytes | None, str | None]:
    pure = PurePosixPath(relative_path)
    target = workspace.joinpath(*pure.parts)
    current = workspace
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            return target, None, "path contains a symlink"
    try:
        target.resolve(strict=False).relative_to(workspace.resolve())
    except ValueError:
        return target, None, "path escapes the workspace"
    if not target.exists():
        return target, None, None
    if not target.is_file():
        return target, None, "path is not a regular file"
    try:
        return target, target.read_bytes(), None
    except OSError as error:
        return target, None, f"could not read file: {error}"


def _ast_definitions(source: bytes) -> tuple[set[str], set[str]] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None
    definitions: set[str] = set()
    callables: set[str] = set()

    def visit(statements: list[ast.stmt], prefix: str = "") -> None:
        for statement in statements:
            if isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                name = f"{prefix}.{statement.name}" if prefix else statement.name
                definitions.add(name)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    callables.add(name)
                if isinstance(statement, ast.ClassDef):
                    visit(statement.body, name)
            elif isinstance(statement, ast.TypeAlias) and isinstance(
                statement.name, ast.Name
            ):
                definitions.add(statement.name.id)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        definitions.add(target.id)

    visit(tree.body)
    return definitions, callables


def _ast_node_map(source: bytes) -> dict[str, ast.AST] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None
    nodes: dict[str, ast.AST] = {}

    def visit(statements: list[ast.stmt], prefix: str = "") -> None:
        for statement in statements:
            if isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                name = f"{prefix}.{statement.name}" if prefix else statement.name
                nodes[name] = statement
                if isinstance(statement, ast.ClassDef):
                    visit(statement.body, name)
            elif isinstance(statement, ast.TypeAlias) and isinstance(
                statement.name, ast.Name
            ):
                nodes[statement.name.id] = statement

    visit(tree.body)
    return nodes


def _line_byte_offsets(source: bytes) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _definition_bytes(source: bytes, node: ast.AST) -> bytes | None:
    if not isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.TypeAlias,
        ),
    ):
        return None
    end_line = node.end_lineno
    if end_line is None:
        return None
    offsets = _line_byte_offsets(source)
    return source[offsets[node.lineno - 1] : offsets[end_line]]


def _body_bytes(
    source: bytes,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> bytes | None:
    if not node.body or node.body[0].lineno == node.lineno:
        return None
    last = node.body[-1]
    if last.end_lineno is None:
        return None
    offsets = _line_byte_offsets(source)
    return source[offsets[node.body[0].lineno - 1] : offsets[last.end_lineno]]


def slot_preimage_bytes(
    packet: Packet, slot: Slot, source: bytes | None
) -> bytes | None:
    if source is None or isinstance(slot.target, WholeFileTarget):
        return None
    if isinstance(slot.target, TextAnchorTarget):
        anchor = slot.target.anchor.encode("utf-8")
        if len(re.findall(re.escape(anchor), source)) != 1:
            return None
        return anchor
    produced = next(
        (
            item
            for item in packet.produces
            if item.path == slot.path
            and item.qualified_name == slot.target.qualified_name
        ),
        None,
    )
    if produced is None or produced.operation == "create":
        return None
    nodes = _ast_node_map(source)
    if nodes is None:
        return None
    node = nodes.get(slot.target.qualified_name)
    if isinstance(slot.target, CallableBodyTarget):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return _body_bytes(source, node)
        return None
    if isinstance(slot.target, StructuralTarget):
        if isinstance(slot.extent, StructuralExtent) and slot.extent.region == "body":
            if isinstance(node, ast.ClassDef):
                return _body_bytes(source, node)
            return None
        return _definition_bytes(source, node) if isinstance(node, ast.AST) else None
    return None


def _validate_packet_targets(
    execution: PacketExecution,
    packet: Packet,
    workspace: Path,
    file_changes: Mapping[str, str],
    test_paths: set[str],
    field_prefix: str = "/packets",
) -> list[ManifestDiagnostic]:
    diagnostics: list[ManifestDiagnostic] = []
    produced = {(item.path, item.qualified_name): item for item in packet.produces}
    source_cache: dict[str, bytes | None] = {}

    def source_for(path: str, field: str) -> bytes | None:
        if path not in source_cache:
            resolved, data, error = _workspace_file(workspace, path)
            source_cache[path] = data
            if error is not None:
                diagnostics.append(
                    _diagnostic(
                        "manifest.workspace_path",
                        field,
                        error,
                        path=path,
                        packet_id=execution.packet_id,
                    )
                )
            elif data is None and file_changes.get(path) != "create":
                diagnostics.append(
                    _diagnostic(
                        "manifest.source_missing",
                        field,
                        "declared source file is missing",
                        path=path,
                        packet_id=execution.packet_id,
                    )
                )
        return source_cache[path]

    for index, slot in enumerate(execution.slots):
        field = _pointer_child(_pointer_child(field_prefix, "slots"), index)
        operation = file_changes.get(slot.path)
        if operation not in ("create", "modify"):
            diagnostics.append(
                _diagnostic(
                    "manifest.slot_undeclared_path",
                    _pointer_child(field, "path"),
                    "slot path must be declared for create or modify by its packet",
                    path=slot.path,
                    packet_id=execution.packet_id,
                )
            )
            continue
        if slot.path in test_paths:
            diagnostics.append(
                _diagnostic(
                    "manifest.host_test_slot",
                    _pointer_child(field, "path"),
                    "compiled slots cannot edit packet test artifacts",
                    path=slot.path,
                    packet_id=execution.packet_id,
                )
            )
        if slot.operation == "create_file" and operation != "create":
            diagnostics.append(
                _diagnostic(
                    "manifest.create_file_operation",
                    _pointer_child(field, "operation"),
                    "create_file slots require a packet create operation",
                    path=slot.path,
                    packet_id=execution.packet_id,
                )
            )
        source = source_for(slot.path, _pointer_child(field, "path"))
        if operation == "create" and source is not None:
            diagnostics.append(
                _diagnostic(
                    "manifest.create_exists",
                    _pointer_child(field, "path"),
                    "packet declares a new file that already exists in the workspace",
                    path=slot.path,
                    packet_id=execution.packet_id,
                )
            )
        if operation == "modify" and source is None:
            continue
        if isinstance(slot.target, TextAnchorTarget) and source is not None:
            anchor = slot.target.anchor.encode("utf-8")
            occurrences = [
                match.start() for match in re.finditer(re.escape(anchor), source)
            ]
            if len(occurrences) != 1:
                diagnostics.append(
                    _diagnostic(
                        "manifest.ambiguous_anchor",
                        _pointer_child(field, "target"),
                        "text anchor must occur exactly once; "
                        f"found {len(occurrences)} occurrences",
                        path=slot.path,
                        packet_id=execution.packet_id,
                    )
                )
            elif isinstance(slot.extent, ByteExtent):
                valid_extent = (
                    slot.operation == "replace"
                    and slot.extent.end_byte - slot.extent.start_byte == len(anchor)
                ) or (
                    slot.operation in ("insert_before", "insert_after")
                    and slot.extent.start_byte == slot.extent.end_byte
                )
                if not valid_extent:
                    diagnostics.append(
                        _diagnostic(
                            "manifest.anchor_extent_mismatch",
                            _pointer_child(field, "extent"),
                            "byte extent length does not match the target and "
                            "operation",
                            path=slot.path,
                            packet_id=execution.packet_id,
                        )
                    )
        target_preimage = slot_preimage_bytes(packet, slot, source)
        if target_preimage is None:
            if slot.preimage_sha256 is not None:
                diagnostics.append(
                    _diagnostic(
                        "manifest.stale_preimage",
                        _pointer_child(field, "preimage_sha256"),
                        "slot declares a preimage for an absent or unresolved target",
                        path=slot.path,
                        packet_id=execution.packet_id,
                    )
                )
        elif (
            slot.preimage_sha256 is None
            or sha256_bytes(target_preimage) != slot.preimage_sha256
        ):
            diagnostics.append(
                _diagnostic(
                    "manifest.stale_preimage",
                    _pointer_child(field, "preimage_sha256"),
                    "slot target bytes do not match the declared preimage hash",
                    path=slot.path,
                    packet_id=execution.packet_id,
                )
            )
        target_name: str | None = None
        if isinstance(slot.target, (CallableBodyTarget, StructuralTarget)):
            target_name = slot.target.qualified_name
            declaration = produced.get((slot.path, target_name))
            if declaration is None:
                diagnostics.append(
                    _diagnostic(
                        "manifest.slot_target_undeclared",
                        _pointer_child(field, "target"),
                        "symbol target must be an explicit packet production in "
                        "the same file",
                        path=slot.path,
                        packet_id=execution.packet_id,
                    )
                )
            elif isinstance(
                slot.target, CallableBodyTarget
            ) and declaration.kind not in (
                "function",
                "async_function",
            ):
                diagnostics.append(
                    _diagnostic(
                        "manifest.slot_target_kind",
                        _pointer_child(field, "target"),
                        "callable-body targets must be produced functions",
                        path=slot.path,
                        packet_id=execution.packet_id,
                    )
                )
            elif isinstance(slot.target, StructuralTarget) and declaration.kind not in (
                "class",
                "type_alias",
            ):
                diagnostics.append(
                    _diagnostic(
                        "manifest.slot_target_kind",
                        _pointer_child(field, "target"),
                        "structural targets must be produced classes or type aliases",
                        path=slot.path,
                        packet_id=execution.packet_id,
                    )
                )
            if source is not None and declaration is not None:
                definitions = _ast_definitions(source)
                if definitions is None:
                    diagnostics.append(
                        _diagnostic(
                            "manifest.source_parse",
                            _pointer_child(field, "path"),
                            "Python target source could not be parsed without "
                            "execution",
                            path=slot.path,
                            packet_id=execution.packet_id,
                            outcome="inconclusive",
                        )
                    )
                else:
                    all_definitions, callable_definitions = definitions
                    exists = target_name in all_definitions
                    expected_exists = declaration.operation == "modify"
                    if exists != expected_exists:
                        diagnostics.append(
                            _diagnostic(
                                "manifest.slot_target_presence",
                                _pointer_child(field, "target"),
                                "target presence does not match its create/modify "
                                "declaration",
                                path=slot.path,
                                packet_id=execution.packet_id,
                            )
                        )
                    if (
                        isinstance(slot.target, CallableBodyTarget)
                        and expected_exists
                        and target_name not in callable_definitions
                    ):
                        diagnostics.append(
                            _diagnostic(
                                "manifest.slot_target_not_callable",
                                _pointer_child(field, "target"),
                                "modified callable target is not a function definition",
                                path=slot.path,
                                packet_id=execution.packet_id,
                            )
                        )
    return diagnostics


def _validate_placement(
    placement: Placement,
    field: str,
    execution: PacketExecution,
    packet: Packet,
    workspace: Path,
    file_changes: Mapping[str, str],
    test_paths: set[str],
) -> list[ManifestDiagnostic]:
    diagnostics: list[ManifestDiagnostic] = []
    operation = file_changes.get(placement.path)
    if operation not in ("create", "modify"):
        diagnostics.append(
            _diagnostic(
                "manifest.placement_undeclared_path",
                _pointer_child(field, "path"),
                "placement path must be declared for create or modify by its packet",
                path=placement.path,
                packet_id=execution.packet_id,
            )
        )
        return diagnostics
    if placement.path in test_paths:
        diagnostics.append(
            _diagnostic(
                "manifest.host_test_placement",
                _pointer_child(field, "path"),
                "compiled placements cannot edit packet test artifacts",
                path=placement.path,
                packet_id=execution.packet_id,
            )
        )
    _, source, error = _workspace_file(workspace, placement.path)
    if error is not None:
        diagnostics.append(
            _diagnostic(
                "manifest.workspace_path",
                _pointer_child(field, "path"),
                error,
                path=placement.path,
                packet_id=execution.packet_id,
            )
        )
        return diagnostics
    if operation == "create":
        if source is not None:
            diagnostics.append(
                _diagnostic(
                    "manifest.create_exists",
                    _pointer_child(field, "path"),
                    "packet declares a new file that already exists in the workspace",
                    path=placement.path,
                    packet_id=execution.packet_id,
                )
            )
        if placement.anchor is not None:
            diagnostics.append(
                _diagnostic(
                    "manifest.create_anchor",
                    _pointer_child(field, "anchor"),
                    "new files cannot use preexisting text anchors",
                    path=placement.path,
                    packet_id=execution.packet_id,
                )
            )
    elif source is None:
        diagnostics.append(
            _diagnostic(
                "manifest.source_missing",
                _pointer_child(field, "path"),
                "placement source file is missing",
                path=placement.path,
                packet_id=execution.packet_id,
            )
        )
    if source is not None and placement.anchor is not None:
        anchor = placement.anchor.encode("utf-8")
        occurrences = [
            match.start() for match in re.finditer(re.escape(anchor), source)
        ]
        if len(occurrences) != 1:
            diagnostics.append(
                _diagnostic(
                    "manifest.ambiguous_placement_anchor",
                    _pointer_child(field, "anchor"),
                    "placement anchor must occur exactly once; "
                    f"found {len(occurrences)} occurrences",
                    path=placement.path,
                    packet_id=execution.packet_id,
                )
            )
        elif (
            placement.preimage_sha256 is None
            or sha256_bytes(anchor) != placement.preimage_sha256
        ):
            diagnostics.append(
                _diagnostic(
                    "manifest.stale_preimage",
                    _pointer_child(field, "preimage_sha256"),
                    "placement anchor bytes do not match the declared preimage hash",
                    path=placement.path,
                    packet_id=execution.packet_id,
                )
            )
    if placement.target.startswith("class:"):
        qualified_name = placement.target.removeprefix("class:")
        planned = any(
            item.path == placement.path
            and item.qualified_name == qualified_name
            and item.kind == "class"
            for item in packet.produces
        )
        if not planned and source is not None:
            definitions = _ast_definitions(source)
            if definitions is None:
                diagnostics.append(
                    _diagnostic(
                        "manifest.placement_source_parse",
                        _pointer_child(field, "path"),
                        "Python placement source could not be parsed without execution",
                        path=placement.path,
                        packet_id=execution.packet_id,
                        outcome="inconclusive",
                    )
                )
            elif qualified_name not in definitions[0]:
                diagnostics.append(
                    _diagnostic(
                        "manifest.placement_class_missing",
                        _pointer_child(field, "target"),
                        "class placement target is neither present nor declared "
                        "by the packet",
                        path=placement.path,
                        packet_id=execution.packet_id,
                    )
                )
    return diagnostics


def _test_nodes(source: str) -> set[str] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _validate_text_slot_overlaps(
    execution: PacketExecution,
    workspace: Path,
    field_prefix: str,
) -> list[ManifestDiagnostic]:
    diagnostics: list[ManifestDiagnostic] = []
    slots_by_path: dict[str, list[tuple[int, Slot, tuple[int, int]]]] = {}
    for index, slot in enumerate(execution.slots):
        if not isinstance(slot.target, TextAnchorTarget):
            continue
        _, source, error = _workspace_file(workspace, slot.path)
        if source is None or error is not None:
            continue
        anchor = slot.target.anchor.encode("utf-8")
        occurrences = [
            match.start() for match in re.finditer(re.escape(anchor), source)
        ]
        if len(occurrences) != 1:
            continue
        start = occurrences[0]
        end = start + len(anchor)
        if slot.operation == "replace":
            extent = (start, end)
        elif slot.operation == "insert_before":
            extent = (start, start)
        else:
            extent = (end, end)
        slots_by_path.setdefault(slot.path, []).append((index, slot, extent))
    for entries in slots_by_path.values():
        for offset, (index, slot, extent) in enumerate(entries):
            for _, prior, prior_extent in entries[:offset]:
                if _ranges_overlap(extent, prior_extent):
                    diagnostics.append(
                        _diagnostic(
                            "manifest.overlapping_slots",
                            _pointer_child(
                                _pointer_child(field_prefix, "slots"), index
                            ),
                            f"slot {slot.slot_id!r} overlaps {prior.slot_id!r}",
                            path=slot.path,
                            packet_id=execution.packet_id,
                        )
                    )
    return diagnostics


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    if left[0] == left[1]:
        return right[0] <= left[0] <= right[1]
    if right[0] == right[1]:
        return left[0] <= right[0] <= left[1]
    return max(left[0], right[0]) < min(left[1], right[1])


def validate_packet_execution(
    packet: Packet,
    execution: PacketExecution,
    workspace: Path,
    field_prefix: str = "/packets",
) -> tuple[ManifestDiagnostic, ...]:
    diagnostics: list[ManifestDiagnostic] = []
    if packet.packet_id != execution.packet_id:
        diagnostics.append(
            _diagnostic(
                "manifest.packet_id_mismatch",
                _pointer_child(field_prefix, "packet_id"),
                "packet ID does not match the execution entry",
                packet_id=execution.packet_id,
            )
        )
    file_changes = {change.path: change.operation for change in packet.file_changes}
    test_paths = {test.path for test in packet.tests}
    for index, placement in enumerate(execution.placements):
        placement_field = _pointer_child(
            _pointer_child(field_prefix, "placements"), index
        )
        diagnostics.extend(
            _validate_placement(
                placement,
                placement_field,
                execution,
                packet,
                workspace,
                file_changes,
                test_paths,
            )
        )
    diagnostics.extend(
        _validate_packet_targets(
            execution,
            packet,
            workspace,
            file_changes,
            test_paths,
            field_prefix,
        )
    )
    diagnostics.extend(_validate_text_slot_overlaps(execution, workspace, field_prefix))
    for produced in packet.produces:
        if produced.kind not in ("function", "async_function"):
            continue
        matching_slots = [
            slot
            for slot in execution.slots
            if isinstance(slot.target, CallableBodyTarget)
            and slot.path == produced.path
            and slot.target.qualified_name == produced.qualified_name
        ]
        if len(matching_slots) != 1:
            diagnostics.append(
                _diagnostic(
                    "manifest.callable_slot_count",
                    _pointer_child(field_prefix, "slots"),
                    f"callable {produced.qualified_name!r} requires exactly one "
                    "body slot",
                    path=produced.path,
                    packet_id=execution.packet_id,
                )
            )
    for produced in packet.produces:
        if produced.operation != "create":
            continue
        parent = produced.qualified_name.rpartition(".")[0]
        expected_target = f"class:{parent}" if parent else "module"
        if not any(
            placement.path == produced.path
            and placement.kind == "declarations"
            and placement.target == expected_target
            for placement in execution.placements
        ):
            diagnostics.append(
                _diagnostic(
                    "manifest.missing_placement",
                    _pointer_child(field_prefix, "placements"),
                    f"created declaration {produced.qualified_name!r} lacks "
                    "an exact placement",
                    path=produced.path,
                    packet_id=execution.packet_id,
                )
            )
    tests = {test.path: test.content for test in packet.tests}
    for check_index, check in enumerate(execution.red_checks):
        check_field = _pointer_child(
            _pointer_child(field_prefix, "red_checks"), check_index
        )
        test_source = tests.get(check.path)
        if test_source is None:
            diagnostics.append(
                _diagnostic(
                    "manifest.red_check_not_visible",
                    _pointer_child(check_field, "path"),
                    "red check must target a visible packet test artifact",
                    path=check.path,
                    packet_id=execution.packet_id,
                )
            )
            continue
        nodes = _test_nodes(test_source)
        if nodes is None:
            diagnostics.append(
                _diagnostic(
                    "manifest.red_test_parse",
                    _pointer_child(check_field, "path"),
                    "visible test source could not be parsed",
                    path=check.path,
                    packet_id=execution.packet_id,
                )
            )
        elif check.test_node not in nodes:
            diagnostics.append(
                _diagnostic(
                    "manifest.red_test_node_missing",
                    _pointer_child(check_field, "test_node"),
                    "red check must name a top-level test function in the packet "
                    "artifact",
                    path=check.path,
                    packet_id=execution.packet_id,
                )
            )
        if check.marker not in test_source:
            diagnostics.append(
                _diagnostic(
                    "manifest.red_marker_missing",
                    _pointer_child(check_field, "marker"),
                    "stable red marker must appear in the visible test source",
                    path=check.path,
                    packet_id=execution.packet_id,
                )
            )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.field,
                item.code,
                item.path or "",
                item.packet_id or "",
            ),
        )
    )


def validate_manifest_artifacts(
    manifest: ExecutionManifest,
    inputs: ManifestInputs,
    *,
    validate_workspace: bool = True,
) -> tuple[ManifestDiagnostic, ...]:
    diagnostics: list[ManifestDiagnostic] = []
    if manifest.task_id != inputs.task_id:
        diagnostics.append(
            _diagnostic(
                "manifest.task_id_mismatch",
                "/task_id",
                "manifest task ID does not match the trusted input registration",
            )
        )
    try:
        plan_bytes = inputs.plan_path.read_bytes()
    except OSError as error:
        diagnostics.append(
            _diagnostic(
                "manifest.plan_missing",
                "/plan_sha256",
                f"cannot read plan artifact: {error}",
            )
        )
    else:
        if sha256_bytes(plan_bytes) != manifest.plan_sha256:
            diagnostics.append(
                _diagnostic(
                    "manifest.stale_plan",
                    "/plan_sha256",
                    "plan artifact hash does not match the manifest",
                )
            )
    packet_sources: dict[str, PacketSource] = {}
    for source in inputs.packet_sources:
        if source.packet_id in packet_sources:
            diagnostics.append(
                _diagnostic(
                    "manifest.duplicate_packet_input",
                    "/packets",
                    f"duplicate packet input {source.packet_id!r}",
                    packet_id=source.packet_id,
                )
            )
        packet_sources[source.packet_id] = source
    manifest_ids = {item.packet_id for item in manifest.packets}
    if manifest_ids != set(packet_sources):
        diagnostics.append(
            _diagnostic(
                "manifest.packet_inputs_mismatch",
                "/packets",
                "manifest packet IDs must exactly match the trusted packet "
                "artifact inputs",
            )
        )
    for packet_index, execution in enumerate(manifest.packets):
        field = _pointer_child("/packets", packet_index)
        source = packet_sources.get(execution.packet_id)
        if source is None:
            continue
        try:
            document = source.path.read_bytes()
        except OSError as error:
            diagnostics.append(
                _diagnostic(
                    "manifest.packet_missing",
                    _pointer_child(field, "packet_sha256"),
                    f"cannot read packet artifact: {error}",
                    path=str(source.path),
                    packet_id=execution.packet_id,
                )
            )
            continue
        if sha256_bytes(document) != execution.packet_sha256:
            diagnostics.append(
                _diagnostic(
                    "manifest.stale_packet",
                    _pointer_child(field, "packet_sha256"),
                    "packet artifact hash does not match the manifest",
                    path=str(source.path),
                    packet_id=execution.packet_id,
                )
            )
        try:
            packet = decode_packet(document.decode("utf-8"))
        except (UnicodeDecodeError, PacketDecodeError) as error:
            diagnostics.append(
                _diagnostic(
                    "manifest.packet_invalid",
                    field,
                    f"packet does not decode as typed-packet v0: {error}",
                    path=str(source.path),
                    packet_id=execution.packet_id,
                )
            )
            continue
        if packet.packet_id != execution.packet_id:
            diagnostics.append(
                _diagnostic(
                    "manifest.packet_id_mismatch",
                    _pointer_child(field, "packet_id"),
                    f"packet artifact declares ID {packet.packet_id!r}",
                    path=str(source.path),
                    packet_id=execution.packet_id,
                )
            )
        if validate_workspace:
            diagnostics.extend(
                validate_packet_execution(packet, execution, inputs.workspace, field)
            )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.field,
                item.code,
                item.path or "",
                item.packet_id or "",
            ),
        )
    )


def validate_registration_artifacts(
    registration: Registration,
    artifacts: tuple[RegisteredTaskArtifacts, ...],
) -> tuple[ManifestDiagnostic, ...]:
    diagnostics: list[ManifestDiagnostic] = []
    artifact_map: dict[str, RegisteredTaskArtifacts] = {}
    for item in artifacts:
        if item.task_id in artifact_map:
            diagnostics.append(
                _diagnostic(
                    "registration.duplicate_artifact_task",
                    "/tasks",
                    f"duplicate trusted artifacts for {item.task_id}",
                )
            )
        artifact_map[item.task_id] = item
    if set(artifact_map) != set(_HELD_OUT_TASKS):
        diagnostics.append(
            _diagnostic(
                "registration.artifact_tasks",
                "/tasks",
                "trusted artifacts must contain exactly H1, H2, and H3",
            )
        )
    for index, registered in enumerate(registration.tasks):
        field = _pointer_child("/tasks", index)
        actual = artifact_map.get(registered.task_id)
        if actual is None:
            continue
        if registered.plan_sha256 != actual.plan_sha256:
            diagnostics.append(
                _diagnostic(
                    "registration.plan_hash_mismatch",
                    _pointer_child(field, "plan_sha256"),
                    "registered plan hash does not match the frozen artifact",
                    path=registered.task_id,
                )
            )
        if registered.manifest_sha256 != actual.manifest_sha256:
            diagnostics.append(
                _diagnostic(
                    "registration.manifest_hash_mismatch",
                    _pointer_child(field, "manifest_sha256"),
                    "registered manifest hash does not match the frozen artifact",
                    path=registered.task_id,
                )
            )
        if registered.packets != actual.packets:
            diagnostics.append(
                _diagnostic(
                    "registration.packet_hash_mismatch",
                    _pointer_child(field, "packets"),
                    "registered packet IDs and hashes do not match the frozen "
                    "artifacts",
                    path=registered.task_id,
                )
            )
    return tuple(
        sorted(diagnostics, key=lambda item: (item.field, item.code, item.path or ""))
    )
