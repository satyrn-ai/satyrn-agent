from ds4py._native.bindings import discover_extension_bindings

from satyrn_agent.bindings import BINDINGS


def test_bindings_are_unique_and_optional() -> None:
    names = [binding.name for binding in BINDINGS]

    assert len(names) == len(set(names))
    assert all(not binding.required for binding in BINDINGS)


def test_installed_entry_point_discovers_satyrn_bindings() -> None:
    discovered = {binding.name: binding for binding in discover_extension_bindings()}

    assert {binding.name for binding in BINDINGS} == set(discovered)
    assert all(discovered[binding.name].source == "satyrn" for binding in BINDINGS)
