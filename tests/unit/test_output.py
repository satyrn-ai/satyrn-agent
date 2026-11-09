from pathlib import Path
from typing import Any, cast, get_overloads

import pytest

from tests.conftest import assert_output


def test_output_has_text_and_mapping_overloads() -> None:
    assert len(get_overloads(assert_output)) == 2


def test_text_output_matches(tmp_path: Path) -> None:
    expected = tmp_path / "output.txt"
    expected.write_text("first\nsecond\n")

    assert_output("first\nsecond\n", expected)


def test_mapping_output_matches(tmp_path: Path) -> None:
    expected = tmp_path / "output.json"
    expected.write_text('{"committed_blocks": 1}\n')

    assert_output({"committed_blocks": 1}, expected)


def test_scalar_output_is_rejected(tmp_path: Path) -> None:
    expected = tmp_path / "output.txt"
    expected.write_text("1\n")

    with pytest.raises(pytest.fail.Exception, match="expected text output"):
        assert_output(cast("Any", 1), expected)
