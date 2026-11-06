import subprocess
import sys
from pathlib import Path

import pytest
from ds4py.abi.manifest import Manifest, manifest_path

from satyrn_agent.bindings import BINDINGS
from tests.conftest import LiveSettings

pytestmark = [pytest.mark.build, pytest.mark.live]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def test_build_check_manifest_and_load_workflow(live_settings: LiveSettings, tmp_path: Path) -> None:
    if live_settings.source is None:
        pytest.skip("SATYRN_TEST_DS4_SRC is required for the ABI build workflow")
    out = tmp_path / "abi"

    run(
        sys.executable,
        "-m",
        "ds4py.cli",
        "build",
        "--src",
        str(live_settings.source),
        "--backend",
        "metal",
        "--out",
        str(out),
    )
    libraries = list(out.glob("libds4.*"))
    assert len(libraries) == 1
    library = libraries[0]
    run(sys.executable, "-m", "ds4py.cli", "check", "--lib", str(library))

    manifest = Manifest.read(manifest_path(library))
    for binding in BINDINGS:
        record = manifest.bindings[binding.name]
        assert record.source == "satyrn"
        assert record.ok, f"{binding.name}: {record.message}"
        assert not record.required
