import sys
from importlib import import_module


def test_core_and_manifest_imports_do_not_load_model_or_django_runtime() -> None:
    import_module("plan_comparison.contracts")
    import_module("plan_comparison.manifest")

    forbidden_prefixes = ("django", "pydantic_ai", "ds4")
    assert not any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for module_name in sys.modules
        for prefix in forbidden_prefixes
    )
