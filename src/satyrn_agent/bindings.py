"""Optional native declarations discovered through ds4-py's ABI manifest."""

from ds4py._native.bindings import Binding

BINDINGS: tuple[Binding, ...] = (
    Binding("ds4_engine_has_dflash", "bool ds4_engine_has_dflash(ds4_engine *e)", required=False),
    Binding("ds4_engine_verify_rows", "int ds4_engine_verify_rows(ds4_engine *e)", required=False),
    Binding(
        "ds4_session_set_verify_mode",
        "int ds4_session_set_verify_mode(ds4_session *s, int mode)",
        required=False,
    ),
    Binding(
        "ds4_session_dflash_draft",
        "int ds4_session_dflash_draft(ds4_session *s, int anchor, int n_max, int *draft, char *err, size_t errlen)",
        required=False,
    ),
    Binding(
        "ds4_session_verify",
        "int ds4_session_verify(ds4_session *s, int anchor, const int *draft, int n_draft, char *err, size_t errlen)",
        required=False,
    ),
    Binding(
        "ds4_session_verify_select",
        "int ds4_session_verify_select(ds4_session *s, int row)",
        required=False,
    ),
    Binding(
        "ds4_session_verify_commit",
        "int ds4_session_verify_commit(ds4_session *s, int n_rows, char *err, size_t errlen)",
        required=False,
    ),
    Binding(
        "ds4_engine_sampling_defaults",
        "void ds4_engine_sampling_defaults(ds4_engine *e, float *temperature, int *top_k, float *top_p, float *min_p)",
        required=False,
    ),
)
