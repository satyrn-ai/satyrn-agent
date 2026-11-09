import subprocess
import sys


def test_core_and_manifest_imports_do_not_load_model_or_django_runtime() -> None:
    # Preserve pytest's source paths without inheriting earlier tests' imports.
    script = """
import sys
from importlib import import_module

sys.path[:0] = sys.argv[1:]
import_module("plan_comparison.contracts")
import_module("plan_comparison.manifest")

forbidden_prefixes = ("django", "pydantic_ai", "ds4py")
loaded = sorted(
    module_name
    for module_name in sys.modules
    if any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in forbidden_prefixes
    )
)
assert not loaded, f"Core imports loaded optional runtimes: {loaded}"
"""
    result = subprocess.run(
        [sys.executable, "-c", script, *sys.path],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
