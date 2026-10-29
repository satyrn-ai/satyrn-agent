#!/usr/bin/env bash
#
# tests/ds4_lib_test.bash
#
# Tests for tools/ds4-lib.bash: pin parsing, model discovery, apply-target
# boundaries and stop-model selection, plus offline cache and state helpers.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TEST_DIR/ds4_test_helpers.bash"

# --- discovery and pin tests --------------------------------------------------

test_load_pin_requires_exact_url_and_commit() {
    ds4_load_pin
    assert_eq "https://github.com/antirez/ds4.git" "$UPSTREAM_URL" "UPSTREAM_URL"
    assert_eq "5379c1c9ac315f1540371b06a3db88491d4059ff" "$UPSTREAM_COMMIT" \
        "UPSTREAM_COMMIT"

    # The pin is parsed, not sourced: a command-substitution marker must be
    # kept verbatim and never executed.
    local pin="$TMP_ROOT/malicious.pin"
    local marker="$TMP_ROOT/pin-executed"
    local want_commit="1234567890abcdef\$(touch $marker)"
    {
        printf 'UPSTREAM_URL=https://example.invalid/ds4.git\n'
        printf 'UPSTREAM_COMMIT=1234567890abcdef$(touch %s)\n' "$marker"
    } > "$pin"

    ds4_load_pin "$pin"
    assert_eq "https://example.invalid/ds4.git" "$UPSTREAM_URL" \
        "pin URL parsed literally"
    assert_eq "$want_commit" "$UPSTREAM_COMMIT" "pin commit parsed literally"
    [[ ! -e "$marker" ]] || {
        printf '  FAIL: pin value was executed\n' >&2
        return 1
    }
}

test_model_names_use_c_locale_order() {
    local patches="$TMP_ROOT/models-patches"
    mkdir -p "$patches/common" "$patches/zulu" "$patches/alpha" \
        "$patches/Model10" "$patches/model2" "$patches/model_1" \
        "$patches/model-1"
    touch "$patches/NOT_A_DIRECTORY"

    DS4_PATCHES_DIR="$patches"
    ds4_model_names

    local want=("Model10" "alpha" "model-1" "model2" "model_1" "zulu")
    assert_eq "6" "${#DS4_MODEL_NAMES[@]}" "model directory count"
    local i
    for i in 0 1 2 3 4 5; do
        assert_eq "${want[$i]}" "${DS4_MODEL_NAMES[$i]}" "model order index $i"
    done

    # Directory names outside [A-Za-z0-9][A-Za-z0-9_-]* must be rejected.
    local bad="$TMP_ROOT/bad-models"
    mkdir -p "$bad/ok_name" "$bad/bad.name"
    DS4_PATCHES_DIR="$bad"
    if ( ds4_model_names ) 2>/dev/null; then
        printf '  FAIL: expected invalid model directory to be rejected\n' >&2
        return 1
    fi
}

test_empty_common_or_model_directory_fails() {
    local patches="$TMP_ROOT/empty-patches"
    mkdir -p "$patches/common" "$patches/alpha"
    DS4_PATCHES_DIR="$patches"

    if ( ds4_patch_files "$patches/common" ) 2>/dev/null; then
        printf '  FAIL: expected empty common directory to fail\n' >&2
        return 1
    fi
    if ( ds4_patch_files "$patches/alpha" ) 2>/dev/null; then
        printf '  FAIL: expected empty model directory to fail\n' >&2
        return 1
    fi
    if ( ds4_patch_files "$patches/missing" ) 2>/dev/null; then
        printf '  FAIL: expected missing patch directory to fail\n' >&2
        return 1
    fi
}

test_empty_model_list_helpers_do_not_crash() {
    local upstream="$TMP_ROOT/empty-models-upstream"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    local patches="$TMP_ROOT/empty-models-patches"
    mkdir -p "$patches"
    _build_common_only_series "$patches"

    DS4_PATCHES_DIR="$patches"
    DS4_CACHE_DIR="$TMP_ROOT/empty-models-cache"
    UPSTREAM_URL="$upstream"
    UPSTREAM_COMMIT="$pin"

    ds4_model_names
    assert_eq "0" "${#DS4_MODEL_NAMES[@]}" "empty model count"

    # Empty model lists must reject a model cleanly, not crash on the
    # bash-3.2 empty-array + set -u expansion.
    if ( ds4_is_model alpha ); then
        printf '  FAIL: expected empty model list to reject alpha\n' >&2
        return 1
    fi
    if ( ds4_target_stop_model alpha ) 2>/dev/null; then
        printf '  FAIL: expected unknown model to be rejected\n' >&2
        return 1
    fi

    ds4_ensure_cache
    local tree="$TMP_ROOT/empty-models-tree"
    ds4_clone_at_pin "$tree"
    ds4_apply_target "$tree"

    assert_file_eq $'line1\ncommon\n' "$tree/notes.txt" \
        "common-only notes.txt with empty model list"
    if _ref_exists "$tree" refs/ds4/model/alpha; then
        printf '  FAIL: empty model list should not create model refs\n' >&2
        return 1
    fi
}

test_apply_target_builds_common_and_ordered_prefix() {
    local upstream="$TMP_ROOT/apply-upstream"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    local patches="$TMP_ROOT/apply-patches"
    mkdir -p "$patches"
    _build_series "$patches"

    DS4_PATCHES_DIR="$patches"
    DS4_CACHE_DIR="$TMP_ROOT/apply-cache"
    UPSTREAM_URL="$upstream"
    UPSTREAM_COMMIT="$pin"

    ds4_ensure_cache
    local tree="$TMP_ROOT/apply-tree"
    ds4_clone_at_pin "$tree"
    ds4_apply_target "$tree"

    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' "$tree/notes.txt" \
        "final notes.txt bytes"

    local want_tree
    want_tree="$(_tree_id "$tree" $'line1\ncommon\n')"
    assert_eq "$want_tree" "$(git -C "$tree" rev-parse refs/ds4/common^{tree})" \
        "common boundary tree"
    want_tree="$(_tree_id "$tree" $'line1\ncommon\nalpha\n')"
    assert_eq "$want_tree" \
        "$(git -C "$tree" rev-parse refs/ds4/model/alpha^{tree})" \
        "alpha boundary tree"
    want_tree="$(_tree_id "$tree" $'line1\ncommon\nalpha\nzebra\n')"
    assert_eq "$want_tree" \
        "$(git -C "$tree" rev-parse refs/ds4/model/zebra^{tree})" \
        "zebra boundary tree"
    assert_eq "$want_tree" "$(git -C "$tree" rev-parse 'HEAD^{tree}')" \
        "final HEAD tree"
}

# --- stop-model selection tests ------------------------------------------------

# Shared setup for the apply-target stop tests: an upstream, a common/alpha/
# zebra patch series, a warmed cache, and a scratch clone at the pin.
_apply_target_stop_fixture() {
    local upstream="$1" patches="$2" cache="$3" tree="$4"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    UPSTREAM_COMMIT="$(git -C "$upstream" rev-parse HEAD)"

    mkdir -p "$patches"
    _build_series "$patches"

    DS4_PATCHES_DIR="$patches"
    DS4_CACHE_DIR="$cache"
    UPSTREAM_URL="$upstream"

    ds4_ensure_cache
    ds4_clone_at_pin "$tree"
}

test_apply_target_stops_at_common() {
    _apply_target_stop_fixture \
        "$TMP_ROOT/stop-common-upstream" \
        "$TMP_ROOT/stop-common-patches" \
        "$TMP_ROOT/stop-common-cache" \
        "$TMP_ROOT/stop-common-tree"

    ds4_apply_target "$TMP_ROOT/stop-common-tree" common

    assert_file_eq $'line1\ncommon\n' \
        "$TMP_ROOT/stop-common-tree/notes.txt" "common-only notes.txt bytes"

    local want_tree
    want_tree="$(_tree_id "$TMP_ROOT/stop-common-tree" $'line1\ncommon\n')"
    assert_eq "$want_tree" \
        "$(git -C "$TMP_ROOT/stop-common-tree" rev-parse refs/ds4/common^{tree})" \
        "common boundary tree"
    assert_eq "$want_tree" \
        "$(git -C "$TMP_ROOT/stop-common-tree" rev-parse 'HEAD^{tree}')" \
        "common HEAD tree"

    if _ref_exists "$TMP_ROOT/stop-common-tree" refs/ds4/model/alpha; then
        printf '  FAIL: refs/ds4/model/alpha should be absent after common stop\n' >&2
        return 1
    fi
    if _ref_exists "$TMP_ROOT/stop-common-tree" refs/ds4/model/zebra; then
        printf '  FAIL: refs/ds4/model/zebra should be absent after common stop\n' >&2
        return 1
    fi
}

test_apply_target_stops_at_model() {
    _apply_target_stop_fixture \
        "$TMP_ROOT/stop-model-upstream" \
        "$TMP_ROOT/stop-model-patches" \
        "$TMP_ROOT/stop-model-cache" \
        "$TMP_ROOT/stop-model-tree"

    ds4_apply_target "$TMP_ROOT/stop-model-tree" alpha

    assert_file_eq $'line1\ncommon\nalpha\n' \
        "$TMP_ROOT/stop-model-tree/notes.txt" "alpha-prefix notes.txt bytes"

    local want_common want_alpha
    want_common="$(_tree_id "$TMP_ROOT/stop-model-tree" $'line1\ncommon\n')"
    assert_eq "$want_common" \
        "$(git -C "$TMP_ROOT/stop-model-tree" rev-parse refs/ds4/common^{tree})" \
        "common boundary tree"
    want_alpha="$(_tree_id "$TMP_ROOT/stop-model-tree" $'line1\ncommon\nalpha\n')"
    assert_eq "$want_alpha" \
        "$(git -C "$TMP_ROOT/stop-model-tree" rev-parse refs/ds4/model/alpha^{tree})" \
        "alpha boundary tree"
    assert_eq "$want_alpha" \
        "$(git -C "$TMP_ROOT/stop-model-tree" rev-parse 'HEAD^{tree}')" \
        "alpha HEAD tree"

    if _ref_exists "$TMP_ROOT/stop-model-tree" refs/ds4/model/zebra; then
        printf '  FAIL: refs/ds4/model/zebra should be absent after alpha stop\n' >&2
        return 1
    fi
}

test_apply_target_uses_global_stop_model() {
    _apply_target_stop_fixture \
        "$TMP_ROOT/global-stop-upstream" \
        "$TMP_ROOT/global-stop-patches" \
        "$TMP_ROOT/global-stop-cache" \
        "$TMP_ROOT/global-stop-tree"

    ds4_model_names
    ds4_target_stop_model alpha
    assert_eq "alpha" "$DS4_STOP_MODEL" "recorded stop model"

    # No positional STOP_MODEL: ds4_apply_target must consume DS4_STOP_MODEL.
    ds4_apply_target "$TMP_ROOT/global-stop-tree"

    assert_file_eq $'line1\ncommon\nalpha\n' \
        "$TMP_ROOT/global-stop-tree/notes.txt" \
        "global stop model notes.txt bytes"

    local want_alpha
    want_alpha="$(_tree_id "$TMP_ROOT/global-stop-tree" $'line1\ncommon\nalpha\n')"
    assert_eq "$want_alpha" \
        "$(git -C "$TMP_ROOT/global-stop-tree" rev-parse refs/ds4/model/alpha^{tree})" \
        "global stop alpha boundary tree"

    if _ref_exists "$TMP_ROOT/global-stop-tree" refs/ds4/model/zebra; then
        printf '  FAIL: trailing ref should be absent when global stop model is set\n' >&2
        return 1
    fi
}

test_target_stop_model_valid_empty_common_unknown() {
    local patches="$TMP_ROOT/stop-model-cases-patches"
    mkdir -p "$patches/common" "$patches/alpha" "$patches/zebra"
    DS4_PATCHES_DIR="$patches"
    ds4_model_names

    ds4_target_stop_model alpha
    assert_eq "alpha" "$DS4_STOP_MODEL" "valid model stop"

    ds4_target_stop_model common
    assert_eq "common" "$DS4_STOP_MODEL" "common stop"

    ds4_target_stop_model
    assert_eq "" "$DS4_STOP_MODEL" "empty stop"

    if ( ds4_target_stop_model nope ) 2>/dev/null; then
        printf '  FAIL: expected unknown stop model to be rejected\n' >&2
        return 1
    fi
}

# --- offline cache and state tests ----------------------------------------------

test_cached_pin_works_when_remote_is_unreachable() {
    local upstream="$TMP_ROOT/offline-upstream"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    DS4_CACHE_DIR="$TMP_ROOT/offline-cache"
    UPSTREAM_URL="$upstream"
    UPSTREAM_COMMIT="$pin"

    ds4_ensure_cache
    git -C "$DS4_CACHE_DIR" cat-file -e "${pin}^{commit}"

    # Make the remote unreachable and prove the cached pin still works.
    mv "$upstream" "$upstream.moved"
    ds4_ensure_cache

    local tree="$TMP_ROOT/offline-tree"
    ds4_clone_at_pin "$tree"
    assert_eq "$pin" "$(git -C "$tree" rev-parse HEAD)" "offline clone HEAD"
    assert_file_eq $'line1\n' "$tree/notes.txt" "offline clone content"
}

test_missing_cached_pin_fails() {
    DS4_CACHE_DIR="$TMP_ROOT/missing-cache"
    UPSTREAM_URL="$TMP_ROOT/does-not-exist-upstream"
    UPSTREAM_COMMIT="1111111111111111111111111111111111111111"

    local err="$TMP_ROOT/missing-cache.err"
    if ( ds4_ensure_cache ) 2>"$err"; then
        printf '  FAIL: expected ds4_ensure_cache to fail\n' >&2
        return 1
    fi
    grep -q 'upstream' "$err" || {
        printf '  FAIL: error did not mention upstream\n' >&2
        return 1
    }
}

test_state_round_trip_does_not_execute_values() {
    local tree="$TMP_ROOT/state-tree"
    mkdir -p "$tree"
    git -C "$tree" init -q

    local marker="$TMP_ROOT/state-executed"
    local target="common \$(touch \"$marker\")"
    local model="\$(touch \"$marker\")"
    local previous_tip="deadbeef \$(touch \"$marker\")"
    local sync_head="cafebabe \$(touch \"$marker\")"

    ds4_state_write "$tree" "$target" "$model" "$previous_tip" "$sync_head"
    ds4_state_read "$tree"

    assert_eq "$target" "$DS4_STATE_TARGET" "TARGET round-trip"
    assert_eq "$model" "$DS4_STATE_MODEL" "MODEL round-trip"
    assert_eq "$previous_tip" "$DS4_STATE_PREVIOUS_TIP" "PREVIOUS_TIP round-trip"
    assert_eq "$sync_head" "$DS4_STATE_SYNC_HEAD" "SYNC_HEAD round-trip"
    assert_eq "$sync_head" "$DS4_STATE_EXPORTED_HEAD" "EXPORTED_HEAD initialized"
    [[ ! -e "$marker" ]] || {
        printf '  FAIL: state values were executed\n' >&2
        return 1
    }
}

test_state_write_accepts_explicit_exported_head() {
    local tree="$TMP_ROOT/state-exported-tree"
    mkdir -p "$tree"
    git -C "$tree" init -q

    ds4_state_write "$tree" alpha alpha prev-tip sync-head exported-head
    ds4_state_read "$tree"

    assert_eq "alpha" "$DS4_STATE_TARGET" "explicit TARGET"
    assert_eq "alpha" "$DS4_STATE_MODEL" "explicit MODEL"
    assert_eq "prev-tip" "$DS4_STATE_PREVIOUS_TIP" "explicit PREVIOUS_TIP"
    assert_eq "sync-head" "$DS4_STATE_SYNC_HEAD" "explicit SYNC_HEAD"
    assert_eq "exported-head" "$DS4_STATE_EXPORTED_HEAD" \
        "explicit EXPORTED_HEAD override"
}

DS4_MODULE_TESTS=(
    test_load_pin_requires_exact_url_and_commit
    test_model_names_use_c_locale_order
    test_empty_common_or_model_directory_fails
    test_empty_model_list_helpers_do_not_crash
    test_apply_target_builds_common_and_ordered_prefix
    test_apply_target_stops_at_common
    test_apply_target_stops_at_model
    test_apply_target_uses_global_stop_model
    test_target_stop_model_valid_empty_common_unknown
    test_cached_pin_works_when_remote_is_unreachable
    test_missing_cached_pin_fails
    test_state_round_trip_does_not_execute_values
    test_state_write_accepts_explicit_exported_head
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
