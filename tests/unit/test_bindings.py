from ds4py._native.bindings import discover_extension_bindings

from satyrn_agent.bindings import BINDINGS

EXPECTED_PROTOTYPES = {
    "ds4_engine_has_dflash": "bool ds4_engine_has_dflash(ds4_engine *e)",
    "ds4_engine_verify_rows": "int ds4_engine_verify_rows(ds4_engine *e)",
    "ds4_session_set_verify_mode": "int ds4_session_set_verify_mode(ds4_session *s, int mode)",
    "ds4_session_dflash_draft": (
        "int ds4_session_dflash_draft(ds4_session *s, int anchor, int n_max, int *draft, char *err, size_t errlen)"
    ),
    "ds4_session_verify": (
        "int ds4_session_verify(ds4_session *s, int anchor, const int *draft, int n_draft, char *err, size_t errlen)"
    ),
    "ds4_session_verify_select": "int ds4_session_verify_select(ds4_session *s, int row)",
    "ds4_session_verify_commit": (
        "int ds4_session_verify_commit(ds4_session *s, int n_rows, char *err, size_t errlen)"
    ),
    "ds4_engine_sampling_defaults": (
        "void ds4_engine_sampling_defaults(ds4_engine *e, float *temperature, int *top_k, float *top_p, float *min_p)"
    ),
}


def test_bindings_cover_exact_optional_satyrn_surface() -> None:
    assert {binding.name: binding.prototype for binding in BINDINGS} == EXPECTED_PROTOTYPES
    assert all(not binding.required for binding in BINDINGS)


def test_installed_entry_point_discovers_satyrn_bindings() -> None:
    discovered = {binding.name: binding for binding in discover_extension_bindings()}

    assert {binding.name for binding in BINDINGS} == set(discovered)
    assert all(discovered[binding.name].source == "satyrn" for binding in BINDINGS)
