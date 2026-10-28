#!/usr/bin/env python3
"""Read ``general.architecture`` from a GGUF file using only the stdlib.

This is the small metadata probe the model-backed E2E gate uses to prove it is
about to run a dense qwen35 model before it materializes or builds anything.
It parses the GGUF metadata keys and prints the architecture string on stdout.

Usage: ds4-gguf-arch.py MODEL.gguf
"""

import struct
import sys

_UINT8, _INT8, _UINT16, _INT16, _UINT32, _INT32 = range(6)
_FLOAT32, _BOOL, _STRING, _ARRAY = 6, 7, 8, 9
_UINT64, _INT64, _FLOAT64 = 10, 11, 12

_TYPE_SIZES = {
    _UINT8: 1, _INT8: 1, _UINT16: 2, _INT16: 2,
    _UINT32: 4, _INT32: 4, _FLOAT32: 4, _BOOL: 1,
    _UINT64: 8, _INT64: 8, _FLOAT64: 8,
}


def _read_exact(fp, n):
    data = fp.read(n)
    if len(data) != n:
        raise ValueError("truncated GGUF file")
    return data


def _read_string(fp):
    (length,) = struct.unpack("<Q", _read_exact(fp, 8))
    return _read_exact(fp, length).decode("utf-8", "replace")


def _skip_value(fp, value_type):
    if value_type == _STRING:
        (length,) = struct.unpack("<Q", _read_exact(fp, 8))
        _read_exact(fp, length)
    elif value_type == _ARRAY:
        (elem_type,) = struct.unpack("<I", _read_exact(fp, 4))
        (count,) = struct.unpack("<Q", _read_exact(fp, 8))
        if elem_type == _STRING:
            for _ in range(count):
                _skip_value(fp, _STRING)
        else:
            size = _TYPE_SIZES.get(elem_type)
            if size is None:
                raise ValueError(f"unknown GGUF array element type {elem_type}")
            _read_exact(fp, size * count)
    else:
        size = _TYPE_SIZES.get(value_type)
        if size is None:
            raise ValueError(f"unknown GGUF value type {value_type}")
        _read_exact(fp, size)


def main(argv):
    if len(argv) != 2:
        print("usage: ds4-gguf-arch.py MODEL.gguf", file=sys.stderr)
        return 2
    with open(argv[1], "rb") as fp:
        if _read_exact(fp, 4) != b"GGUF":
            raise ValueError("not a GGUF file")
        _read_exact(fp, 4)  # version
        _read_exact(fp, 8)  # tensor count
        (kv_count,) = struct.unpack("<Q", _read_exact(fp, 8))
        for _ in range(kv_count):
            key = _read_string(fp)
            (value_type,) = struct.unpack("<I", _read_exact(fp, 4))
            if key == "general.architecture":
                if value_type != _STRING:
                    raise ValueError("general.architecture is not a string")
                print(_read_string(fp))
                return 0
            _skip_value(fp, value_type)
    print("general.architecture not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (OSError, ValueError, struct.error) as exc:
        print(f"ds4-gguf-arch: {exc}", file=sys.stderr)
        sys.exit(1)
