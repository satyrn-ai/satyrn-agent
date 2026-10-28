#!/usr/bin/env bash
#
# tests/ds4_tools_test.bash
#
# Self-contained tests for tools/ds4-lib.bash. They build local upstream
# repositories and patch directories, then exercise real Git and the real
# scripts. No network is used: remote failures are simulated by moving the
# local upstream path. The same file must pass with Bash 3.2 on macOS and
# Ubuntu, so only POSIX/Bash builtins and portable Git invocations are used.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TEST_DIR/.." && pwd)"

source "$REPO_ROOT/tools/ds4-lib.bash"

# Run every test in a private temp tree and keep Git isolated from user and
# system configuration while still giving temp repositories an identity.
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ds4.XXXXXX")"
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME"
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL="$TMP_ROOT/gitconfig"
export GIT_AUTHOR_NAME="ds4 test"
export GIT_AUTHOR_EMAIL="ds4-test@example.com"
export GIT_COMMITTER_NAME="ds4 test"
export GIT_COMMITTER_EMAIL="ds4-test@example.com"

trap 'rm -rf "$TMP_ROOT"' EXIT

# --- assertion helpers -------------------------------------------------------

assert_eq() {
    local want="$1" got="$2" msg="${3:-}"
    if [[ "$want" != "$got" ]]; then
        printf '  FAIL: %s\n    expected: %s\n    actual:   %s\n' \
            "$msg" "$want" "$got" >&2
        return 1
    fi
}

assert_file_eq() {
    local want="$1" file="$2" msg="${3:-}"
    [[ -f "$file" ]] || {
        printf '  FAIL: %s (missing file: %s)\n' "$msg" "$file" >&2
        return 1
    }
    local want_hash got_hash
    want_hash="$(printf '%s' "$want" | git hash-object --stdin)"
    got_hash="$(git hash-object "$file")"
    assert_eq "$want_hash" "$got_hash" "$msg (git hash-object)"
}

# --- fixture helpers ----------------------------------------------------------

# Build a linear patch series under PATCHES_DIR. Each directory appends one
# distinct line to notes.txt in order: common, alpha, zebra. Patches are real
# git format-patch output and are generated on top of each other so that they
# apply in exactly that order.
_build_series() {
    local patches_dir="$1"
    local src="$TMP_ROOT/series-src"
    rm -rf "$src"
    mkdir -p "$src"
    git -C "$src" init -q
    printf 'line1\n' > "$src/notes.txt"
    git -C "$src" add notes.txt
    git -C "$src" commit -qm "base"

    local spec dir line
    for spec in "common:common" "alpha:alpha" "zebra:zebra"; do
        dir="${spec%%:*}"
        line="${spec#*:}"
        mkdir -p "$patches_dir/$dir"
        printf '%s\n' "$line" >> "$src/notes.txt"
        git -C "$src" add notes.txt
        git -C "$src" commit -qm "add $line"
        git -C "$src" format-patch -1 --stdout --no-signature \
            > "$patches_dir/$dir/0001-add-$line.patch"
    done
}

# Print the Git tree id of a tree containing a single notes.txt blob.
_tree_id() {
    local tree="$1" content="$2"
    local blob
    blob="$(printf '%s' "$content" | git -C "$tree" hash-object --stdin -w)" \
        || return 1
    printf '100644 blob %s\tnotes.txt\n' "$blob" | git -C "$tree" mktree
}

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

# Return success when REF resolves in TREE, failure when it is absent.
_ref_exists() {
    local tree="$1" ref="$2"
    git -C "$tree" rev-parse --verify --quiet "$ref" >/dev/null 2>&1
}

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

# --- runner -------------------------------------------------------------------

ALL_TESTS=(
    test_load_pin_requires_exact_url_and_commit
    test_model_names_use_c_locale_order
    test_empty_common_or_model_directory_fails
    test_apply_target_builds_common_and_ordered_prefix
    test_apply_target_stops_at_common
    test_apply_target_stops_at_model
    test_apply_target_uses_global_stop_model
    test_target_stop_model_valid_empty_common_unknown
    test_cached_pin_works_when_remote_is_unreachable
    test_missing_cached_pin_fails
    test_state_round_trip_does_not_execute_values
)

PASSED=0
FAILED=0

run_test() {
    local name="$1" status
    printf 'RUN %s\n' "$name"
    # Run in a standalone subshell (not an `if`/`&&` context) so that
    # `set -e` really applies inside the test function.
    ( set -e; "$name" )
    status=$?
    if [[ $status -eq 0 ]]; then
        printf 'PASS %s\n' "$name"
        PASSED=$((PASSED + 1))
    else
        printf 'FAIL %s\n' "$name"
        FAILED=$((FAILED + 1))
    fi
}

main() {
    local names=()
    local t
    if [[ $# -eq 0 ]]; then
        names=("${ALL_TESTS[@]}")
    else
        names=("$@")
    fi

    for t in "${names[@]}"; do
        run_test "$t"
    done

    printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
    [[ $FAILED -eq 0 ]]
}

main "$@"
