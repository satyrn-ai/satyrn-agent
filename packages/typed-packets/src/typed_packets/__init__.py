"""Strict task packets and conservative static validation."""

from typed_packets.contract import (
    Consume,
    Diagnostic,
    FileChange,
    Gate,
    GateExpectation,
    ImportReference,
    Packet,
    PacketDecodeError,
    Produce,
    SourceReference,
    TestArtifact,
    ValidationReport,
    decode_packet,
    encode_packet,
)
from typed_packets.index import SourceRoot, SymbolIndex, ValidationContext, build_index
from typed_packets.validate import validate_document, validate_packet

__all__ = [
    "Consume",
    "Diagnostic",
    "FileChange",
    "Gate",
    "GateExpectation",
    "ImportReference",
    "Packet",
    "PacketDecodeError",
    "Produce",
    "SourceRoot",
    "SourceReference",
    "SymbolIndex",
    "TestArtifact",
    "ValidationReport",
    "ValidationContext",
    "build_index",
    "decode_packet",
    "encode_packet",
    "validate_document",
    "validate_packet",
]
