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

# Build a common-only patch series (no model directories) so the empty
# model-list paths are exercised.
_build_common_only_series() {
    local patches_dir="$1"
    local src="$TMP_ROOT/common-only-src"
    rm -rf "$src"
    mkdir -p "$src"
    git -C "$src" init -q
    printf 'line1\n' > "$src/notes.txt"
    git -C "$src" add notes.txt
    git -C "$src" commit -qm "base"
    printf 'common\n' >> "$src/notes.txt"
    git -C "$src" add notes.txt
    git -C "$src" commit -qm "add common"
    mkdir -p "$patches_dir/common"
    git -C "$src" format-patch -1 --stdout --no-signature \
        > "$patches_dir/common/0001-add-common.patch"
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

# --- sync tests ---------------------------------------------------------------

_run_sync() {
    bash "$REPO_ROOT/tools/ds4-sync.bash" "$@"
}

# Build an upstream, a common/alpha/zebra patch series, and export the globals
# that the ds4-sync subprocess consumes.
_sync_fixture() {
    local upstream="$1" patches="$2" cache="$3" tree="$4"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    mkdir -p "$patches"
    _build_series "$patches"

    export DS4_PATCHES_DIR="$patches"
    export DS4_CACHE_DIR="$cache"
    export DS4_TREE_DIR="$tree"
    export UPSTREAM_URL="$upstream"
    export UPSTREAM_COMMIT="$pin"
    unset DS4_STOP_MODEL 2>/dev/null || true
}

test_sync_defaults_to_all_models() {
    _sync_fixture "$TMP_ROOT/sync-all-upstream" "$TMP_ROOT/sync-all-patches" \
        "$TMP_ROOT/sync-all-cache" "$TMP_ROOT/sync-all-tree"

    _run_sync

    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' "$DS4_TREE_DIR/notes.txt" \
        "all-models notes.txt bytes"
    local branch
    branch="$(git -C "$DS4_TREE_DIR" symbolic-ref HEAD)"
    branch="${branch#refs/heads/}"
    assert_eq "ds4/model/zebra" "$branch" "all-models checked-out branch"

    local want_common want_alpha want_zebra
    want_common="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\n')"
    want_alpha="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\nalpha\n')"
    want_zebra="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\nalpha\nzebra\n')"
    assert_eq "$want_common" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/common^{tree})" \
        "all-models common boundary tree"
    assert_eq "$want_alpha" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/alpha^{tree})" \
        "all-models alpha boundary tree"
    assert_eq "$want_zebra" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/zebra^{tree})" \
        "all-models zebra boundary tree"
    assert_eq "$want_zebra" \
        "$(git -C "$DS4_TREE_DIR" rev-parse 'HEAD^{tree}')" \
        "all-models final HEAD tree"

    assert_eq "$UPSTREAM_URL" \
        "$(git -C "$DS4_TREE_DIR" config --get remote.upstream.url)" \
        "upstream remote URL"

    ds4_state_read "$DS4_TREE_DIR"
    local head
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"
    assert_eq "zebra" "$DS4_STATE_TARGET" "all-models target"
    assert_eq "zebra" "$DS4_STATE_MODEL" "all-models editable model"
    assert_eq "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/alpha)" \
        "$DS4_STATE_PREVIOUS_TIP" "all-models previous tip"
    assert_eq "$head" "$DS4_STATE_SYNC_HEAD" "all-models sync head"
    assert_eq "$head" "$DS4_STATE_EXPORTED_HEAD" "all-models exported head"
}

test_sync_common_only() {
    _sync_fixture "$TMP_ROOT/sync-common-upstream" "$TMP_ROOT/sync-common-patches" \
        "$TMP_ROOT/sync-common-cache" "$TMP_ROOT/sync-common-tree"

    _run_sync --common-only

    assert_file_eq $'line1\ncommon\n' "$DS4_TREE_DIR/notes.txt" \
        "common-only notes.txt bytes"
    local branch
    branch="$(git -C "$DS4_TREE_DIR" symbolic-ref HEAD)"
    branch="${branch#refs/heads/}"
    assert_eq "ds4/common" "$branch" "common-only checked-out branch"

    local want_common
    want_common="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\n')"
    assert_eq "$want_common" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/common^{tree})" \
        "common-only boundary tree"
    assert_eq "$want_common" \
        "$(git -C "$DS4_TREE_DIR" rev-parse 'HEAD^{tree}')" \
        "common-only HEAD tree"

    if _ref_exists "$DS4_TREE_DIR" refs/ds4/model/alpha; then
        printf '  FAIL: refs/ds4/model/alpha should be absent for common-only\n' >&2
        return 1
    fi
    if _ref_exists "$DS4_TREE_DIR" refs/ds4/model/zebra; then
        printf '  FAIL: refs/ds4/model/zebra should be absent for common-only\n' >&2
        return 1
    fi

    ds4_state_read "$DS4_TREE_DIR"
    local head
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"
    assert_eq "common" "$DS4_STATE_TARGET" "common-only target"
    assert_eq "" "$DS4_STATE_MODEL" "common-only model"
    assert_eq "$UPSTREAM_COMMIT" "$DS4_STATE_PREVIOUS_TIP" \
        "common-only previous tip"
    assert_eq "$head" "$DS4_STATE_SYNC_HEAD" "common-only sync head"
    assert_eq "$head" "$DS4_STATE_EXPORTED_HEAD" "common-only exported head"
}

test_sync_model_stops_at_editable_prefix() {
    _sync_fixture "$TMP_ROOT/sync-model-upstream" "$TMP_ROOT/sync-model-patches" \
        "$TMP_ROOT/sync-model-cache" "$TMP_ROOT/sync-model-tree"

    _run_sync --model alpha

    assert_file_eq $'line1\ncommon\nalpha\n' "$DS4_TREE_DIR/notes.txt" \
        "alpha-prefix notes.txt bytes"
    local branch
    branch="$(git -C "$DS4_TREE_DIR" symbolic-ref HEAD)"
    branch="${branch#refs/heads/}"
    assert_eq "ds4/model/alpha" "$branch" "alpha-prefix checked-out branch"

    local want_common want_alpha
    want_common="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\n')"
    want_alpha="$(_tree_id "$DS4_TREE_DIR" $'line1\ncommon\nalpha\n')"
    assert_eq "$want_common" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/common^{tree})" \
        "alpha-prefix common boundary tree"
    assert_eq "$want_alpha" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/alpha^{tree})" \
        "alpha-prefix alpha boundary tree"
    assert_eq "$want_alpha" \
        "$(git -C "$DS4_TREE_DIR" rev-parse 'HEAD^{tree}')" \
        "alpha-prefix HEAD tree"

    if _ref_exists "$DS4_TREE_DIR" refs/ds4/model/zebra; then
        printf '  FAIL: refs/ds4/model/zebra should be absent for alpha prefix\n' >&2
        return 1
    fi

    ds4_state_read "$DS4_TREE_DIR"
    local head
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"
    assert_eq "alpha" "$DS4_STATE_TARGET" "alpha-prefix target"
    assert_eq "alpha" "$DS4_STATE_MODEL" "alpha-prefix model"
    assert_eq "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/common)" \
        "$DS4_STATE_PREVIOUS_TIP" "alpha-prefix previous tip"
    assert_eq "$head" "$DS4_STATE_SYNC_HEAD" "alpha-prefix sync head"
    assert_eq "$head" "$DS4_STATE_EXPORTED_HEAD" "alpha-prefix exported head"
}

test_sync_rejects_invalid_arguments() {
    _sync_fixture "$TMP_ROOT/sync-args-upstream" "$TMP_ROOT/sync-args-patches" \
        "$TMP_ROOT/sync-args-cache" "$TMP_ROOT/sync-args-tree"
    local err="$TMP_ROOT/sync-args.err"

    if _run_sync --common-only --model alpha 2>"$err"; then
        printf '  FAIL: expected --common-only --model to fail\n' >&2
        return 1
    fi
    grep -q 'common-only' "$err" || {
        printf '  FAIL: error did not mention common-only\n' >&2
        return 1
    }

    if _run_sync --model nope 2>"$err"; then
        printf '  FAIL: expected unknown model to fail\n' >&2
        return 1
    fi
    grep -q 'unknown model' "$err" || {
        printf '  FAIL: error did not mention unknown model\n' >&2
        return 1
    }

    if _run_sync extra 2>"$err"; then
        printf '  FAIL: expected extra argument to fail\n' >&2
        return 1
    fi
    grep -q 'unexpected argument' "$err" || {
        printf '  FAIL: error did not mention unexpected argument\n' >&2
        return 1
    }

    local empty_patches="$TMP_ROOT/sync-args-empty-patches"
    mkdir -p "$empty_patches/common" "$empty_patches/alpha"
    export DS4_PATCHES_DIR="$empty_patches"
    if _run_sync 2>"$err"; then
        printf '  FAIL: expected empty common directory to fail\n' >&2
        return 1
    fi
    grep -q 'empty' "$err" || {
        printf '  FAIL: error did not mention empty common directory\n' >&2
        return 1
    }
}

test_sync_rejects_common_and_empty_model() {
    _sync_fixture "$TMP_ROOT/sync-model-args-upstream" \
        "$TMP_ROOT/sync-model-args-patches" \
        "$TMP_ROOT/sync-model-args-cache" "$TMP_ROOT/sync-model-args-tree"
    local err="$TMP_ROOT/sync-model-args.err"

    if _run_sync --model common 2>"$err"; then
        printf '  FAIL: expected --model common to fail\n' >&2
        return 1
    fi
    grep -q -- '--common-only' "$err" || {
        printf '  FAIL: --model common error did not suggest --common-only\n' >&2
        return 1
    }

    if _run_sync --model "" 2>"$err"; then
        printf '  FAIL: expected empty --model to fail\n' >&2
        return 1
    fi
    grep -q -- 'non-empty' "$err" || {
        printf '  FAIL: empty --model error did not mention non-empty\n' >&2
        return 1
    }
    [[ ! -e "$DS4_TREE_DIR" ]] || {
        printf '  FAIL: empty --model must not materialize a tree\n' >&2
        return 1
    }
}

test_sync_help_prints_usage_without_tree() {
    _sync_fixture "$TMP_ROOT/sync-help-upstream" "$TMP_ROOT/sync-help-patches" \
        "$TMP_ROOT/sync-help-cache" "$TMP_ROOT/sync-help-tree"

    local out="$TMP_ROOT/sync-help.out"
    _run_sync --help >"$out"

    grep -q 'Usage: ds4-sync' "$out" || {
        printf '  FAIL: help did not print usage\n' >&2
        return 1
    }
    [[ ! -e "$DS4_TREE_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/tree\n' >&2
        return 1
    }
}

test_sync_refuses_dirty_tree_without_force() {
    _sync_fixture "$TMP_ROOT/sync-dirty-upstream" "$TMP_ROOT/sync-dirty-patches" \
        "$TMP_ROOT/sync-dirty-cache" "$TMP_ROOT/sync-dirty-tree"

    _run_sync
    local head0
    head0="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    printf 'dirty\n' >> "$DS4_TREE_DIR/notes.txt"
    printf 'marker\n' > "$DS4_TREE_DIR/dirty-marker"

    local err="$TMP_ROOT/sync-dirty.err"
    if _run_sync 2>"$err"; then
        printf '  FAIL: expected dirty tree sync to be refused\n' >&2
        return 1
    fi
    grep -q 'dirty' "$err" || {
        printf '  FAIL: error did not mention dirty tree\n' >&2
        return 1
    }

    assert_eq "$head0" "$(git -C "$DS4_TREE_DIR" rev-parse HEAD)" \
        "dirty refusal preserved HEAD"
    assert_file_eq $'marker\n' "$DS4_TREE_DIR/dirty-marker" \
        "dirty refusal preserved marker"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\ndirty\n' \
        "$DS4_TREE_DIR/notes.txt" "dirty refusal preserved notes.txt"
}

test_sync_refuses_unexported_commit_without_force() {
    _sync_fixture "$TMP_ROOT/sync-unexported-upstream" \
        "$TMP_ROOT/sync-unexported-patches" \
        "$TMP_ROOT/sync-unexported-cache" "$TMP_ROOT/sync-unexported-tree"

    _run_sync
    printf 'unexported\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "unexported change"
    local head1
    head1="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    local err="$TMP_ROOT/sync-unexported.err"
    if _run_sync 2>"$err"; then
        printf '  FAIL: expected unexported commit sync to be refused\n' >&2
        return 1
    fi
    grep -q 'unexported' "$err" || {
        printf '  FAIL: error did not mention unexported commits\n' >&2
        return 1
    }

    assert_eq "$head1" "$(git -C "$DS4_TREE_DIR" rev-parse HEAD)" \
        "unexported refusal preserved HEAD"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\nunexported\n' \
        "$DS4_TREE_DIR/notes.txt" "unexported refusal preserved content"
}

test_sync_force_replaces_only_scratch_tree() {
    _sync_fixture "$TMP_ROOT/sync-force-upstream" "$TMP_ROOT/sync-force-patches" \
        "$TMP_ROOT/sync-force-cache" "$TMP_ROOT/sync-force-tree"

    _run_sync

    # A clean, unchanged re-sync is allowed without --force.
    _run_sync

    # Dirty the scratch tree and plant markers in both the tree and the cache.
    printf 'dirty\n' >> "$DS4_TREE_DIR/notes.txt"
    printf 'tree-marker\n' > "$DS4_TREE_DIR/tree-marker"
    printf 'cache-marker\n' > "$DS4_CACHE_DIR/cache-marker"

    if _run_sync 2>/dev/null; then
        printf '  FAIL: expected dirty sync without force to fail\n' >&2
        return 1
    fi
    [[ -f "$DS4_TREE_DIR/tree-marker" ]] || {
        printf '  FAIL: dirty tree should survive non-force refusal\n' >&2
        return 1
    }

    _run_sync --force

    [[ ! -e "$DS4_TREE_DIR/tree-marker" ]] || {
        printf '  FAIL: --force must recreate .ds4/tree\n' >&2
        return 1
    }
    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' "$DS4_TREE_DIR/notes.txt" \
        "--force rebuilt notes.txt"
    assert_file_eq $'cache-marker\n' "$DS4_CACHE_DIR/cache-marker" \
        "--force preserved cache marker"
    [[ -d "$DS4_CACHE_DIR" ]] || {
        printf '  FAIL: --force must not delete .ds4/cache\n' >&2
        return 1
    }
}

test_sync_interrupted_old_tree_move_restores_original() {
    _sync_fixture "$TMP_ROOT/sync-mv-upstream" "$TMP_ROOT/sync-mv-patches" \
        "$TMP_ROOT/sync-mv-cache" "$TMP_ROOT/sync-mv-tree"

    _run_sync
    local head0
    head0="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    # Shim mv so the old-tree move performs the rename and then reports
    # failure, exactly like a move that is interrupted after it lands but
    # before the script observes success. The original tree must survive even
    # though its backup lives inside the EXIT-cleanup work directory.
    local bindir="$TMP_ROOT/sync-mv-bin" real_mv
    real_mv="$(command -v mv)"
    mkdir -p "$bindir"
    cat > "$bindir/mv" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "$DS4_TREE_DIR" && "\$2" == */old ]]; then
    "$real_mv" "\$1" "\$2"
    exit 1
fi
exec "$real_mv" "\$@"
EOF
    chmod +x "$bindir/mv"

    local err="$TMP_ROOT/sync-mv.err"
    if PATH="$bindir:$PATH" _run_sync 2>"$err"; then
        printf '  FAIL: expected interrupted old-tree move to fail\n' >&2
        return 1
    fi
    grep -q 'cannot move existing tree aside' "$err" || {
        printf '  FAIL: error did not mention the old-tree move\n' >&2
        return 1
    }

    assert_eq "$head0" "$(git -C "$DS4_TREE_DIR" rev-parse HEAD)" \
        "interrupted old-tree move preserved HEAD"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' "$DS4_TREE_DIR/notes.txt" \
        "interrupted old-tree move preserved notes.txt bytes"
}

# --- export tests --------------------------------------------------------------

_run_export() {
    bash "$REPO_ROOT/tools/ds4-export.bash" "$@"
}

_export_fixture() {
    local upstream="$1" patches="$2" cache="$3" tree="$4" exportdir="$5"
    _sync_fixture "$upstream" "$patches" "$cache" "$tree"
    export DS4_EXPORT_DIR="$exportdir"
}

# Copy SRC recursively into DEST for a later byte comparison.
_snapshot_dir() {
    local src="$1" dest="$2"
    rm -rf "$dest"
    mkdir -p "$dest"
    cp -R "$src/." "$dest/"
}

_assert_dirs_identical() {
    local a="$1" b="$2" msg="${3:-}"
    if ! diff -r "$a" "$b" >/dev/null 2>&1; then
        printf '  FAIL: %s (directories differ)\n' "$msg" >&2
        return 1
    fi
}

# Apply every *.patch in DIR to TREE in filename order.
_apply_dir() {
    local tree="$1" dir="$2"
    ds4_patch_files "$dir"
    local f
    for f in "${DS4_PATCH_FILES[@]}"; do
        git -C "$tree" am --quiet "$f" || return 1
    done
}

test_export_common_renumbers_real_range() {
    _export_fixture "$TMP_ROOT/exp-common-upstream" "$TMP_ROOT/exp-common-patches" \
        "$TMP_ROOT/exp-common-cache" "$TMP_ROOT/exp-common-tree" \
        "$TMP_ROOT/exp-common-exportdir"

    _run_sync --common-only

    # Snapshot the directories export must not touch.
    _snapshot_dir "$DS4_PATCHES_DIR/alpha" "$TMP_ROOT/exp-common-alpha-before"
    _snapshot_dir "$DS4_PATCHES_DIR/zebra" "$TMP_ROOT/exp-common-zebra-before"

    # Append two real commits to the common-only editable tip.
    printf 'common-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "common edit a"
    printf 'common-b\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "common edit b"

    local sync_head exported_before head
    ds4_state_read "$DS4_TREE_DIR"
    sync_head="$DS4_STATE_SYNC_HEAD"
    exported_before="$DS4_STATE_EXPORTED_HEAD"
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    _run_export

    # Exported range is pin..HEAD: 1 original common commit + 2 new commits.
    ds4_patch_files "$DS4_PATCHES_DIR/common"
    assert_eq "3" "${#DS4_PATCH_FILES[@]}" "common export patch count"
    local first
    first="$(basename "${DS4_PATCH_FILES[0]}")"
    case "$first" in
        0001-*.patch) : ;;
        *)
            printf '  FAIL: common export did not start at 0001 (%s)\n' "$first" >&2
            return 1
            ;;
    esac

    # Applying the exported common patches at the pin reproduces HEAD.
    local verify="$TMP_ROOT/exp-common-verify"
    ds4_clone_at_pin "$verify"
    _apply_dir "$verify" "$DS4_PATCHES_DIR/common"
    assert_eq "$(git -C "$DS4_TREE_DIR" rev-parse 'HEAD^{tree}')" \
        "$(git -C "$verify" rev-parse 'HEAD^{tree}')" \
        "exported common patches reproduce HEAD tree"

    # Other directories remain byte-identical.
    _assert_dirs_identical "$TMP_ROOT/exp-common-alpha-before" \
        "$DS4_PATCHES_DIR/alpha" "alpha directory unchanged"
    _assert_dirs_identical "$TMP_ROOT/exp-common-zebra-before" \
        "$DS4_PATCHES_DIR/zebra" "zebra directory unchanged"

    # EXPORTED_HEAD advanced to the new HEAD.
    ds4_state_read "$DS4_TREE_DIR"
    assert_eq "$head" "$DS4_STATE_EXPORTED_HEAD" "exported head advanced"
    assert_eq "$sync_head" "$DS4_STATE_SYNC_HEAD" "sync head unchanged"
    [[ "$exported_before" != "$DS4_STATE_EXPORTED_HEAD" ]] || {
        printf '  FAIL: exported head did not change\n' >&2
        return 1
    }

    # Exercise the Task 2 exported-head resync path: a clean non-force re-sync
    # is allowed because HEAD now equals EXPORTED_HEAD rather than SYNC_HEAD.
    _run_sync --common-only
}

test_export_empty_model_list_fails_cleanly() {
    local upstream="$TMP_ROOT/exp-empty-models-upstream"
    local patches="$TMP_ROOT/exp-empty-models-patches"
    local cache="$TMP_ROOT/exp-empty-models-cache"
    local tree="$TMP_ROOT/exp-empty-models-tree"
    local exportdir="$TMP_ROOT/exp-empty-models-exportdir"

    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    mkdir -p "$patches"
    _build_common_only_series "$patches"

    export DS4_PATCHES_DIR="$patches"
    export DS4_CACHE_DIR="$cache"
    export DS4_TREE_DIR="$tree"
    export DS4_EXPORT_DIR="$exportdir"
    export UPSTREAM_URL="$upstream"
    export UPSTREAM_COMMIT="$pin"
    unset DS4_STOP_MODEL 2>/dev/null || true

    _run_sync --common-only

    # Forge the model-target state a migration bootstrap writes before its
    # first model export. With no model directories yet, export must reject
    # the unknown model cleanly instead of crashing on the empty array.
    ds4_state_write "$DS4_TREE_DIR" alpha alpha \
        "$UPSTREAM_COMMIT" "$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    local err="$TMP_ROOT/exp-empty-models.err"
    if _run_export 2>"$err"; then
        printf '  FAIL: expected unknown model export to be rejected\n' >&2
        return 1
    fi
    grep -q 'unrecognized' "$err" || {
        printf '  FAIL: error did not mention unrecognized target\n' >&2
        return 1
    }
    if grep -q 'unbound variable' "$err"; then
        printf '  FAIL: empty model list crashed with unbound variable\n' >&2
        return 1
    fi
}

test_export_model_uses_previous_model_tip() {
    _export_fixture "$TMP_ROOT/exp-model-upstream" "$TMP_ROOT/exp-model-patches" \
        "$TMP_ROOT/exp-model-cache" "$TMP_ROOT/exp-model-tree" \
        "$TMP_ROOT/exp-model-exportdir"

    _run_sync

    _snapshot_dir "$DS4_PATCHES_DIR/common" "$TMP_ROOT/exp-model-common-before"
    _snapshot_dir "$DS4_PATCHES_DIR/alpha" "$TMP_ROOT/exp-model-alpha-before"

    # Append two real commits to the zebra editable tip.
    printf 'zebra-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit a"
    printf 'zebra-b\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit b"

    local sync_head exported_before head
    ds4_state_read "$DS4_TREE_DIR"
    sync_head="$DS4_STATE_SYNC_HEAD"
    exported_before="$DS4_STATE_EXPORTED_HEAD"
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)"

    _run_export

    # Only the zebra range (previous model tip..HEAD) is exported:
    # 1 original zebra commit + 2 new commits.
    ds4_patch_files "$DS4_PATCHES_DIR/zebra"
    assert_eq "3" "${#DS4_PATCH_FILES[@]}" "zebra export patch count"
    local first
    first="$(basename "${DS4_PATCH_FILES[0]}")"
    case "$first" in
        0001-*.patch) : ;;
        *)
            printf '  FAIL: zebra export did not start at 0001 (%s)\n' "$first" >&2
            return 1
            ;;
    esac

    # The full committed series (common + alpha + exported zebra) reproduces
    # HEAD from a pristine clone at the pin.
    local verify="$TMP_ROOT/exp-model-verify"
    ds4_clone_at_pin "$verify"
    ds4_apply_target "$verify"
    assert_eq "$(git -C "$DS4_TREE_DIR" rev-parse 'HEAD^{tree}')" \
        "$(git -C "$verify" rev-parse 'HEAD^{tree}')" \
        "exported model patches reproduce HEAD tree"

    # common and alpha directories remain byte-identical.
    _assert_dirs_identical "$TMP_ROOT/exp-model-common-before" \
        "$DS4_PATCHES_DIR/common" "common directory unchanged"
    _assert_dirs_identical "$TMP_ROOT/exp-model-alpha-before" \
        "$DS4_PATCHES_DIR/alpha" "alpha directory unchanged"

    ds4_state_read "$DS4_TREE_DIR"
    assert_eq "$head" "$DS4_STATE_EXPORTED_HEAD" "exported head advanced"
    assert_eq "$sync_head" "$DS4_STATE_SYNC_HEAD" "sync head unchanged"
    [[ "$exported_before" != "$DS4_STATE_EXPORTED_HEAD" ]] || {
        printf '  FAIL: exported head did not change\n' >&2
        return 1
    }
}

test_export_rejects_merge_commit() {
    _export_fixture "$TMP_ROOT/exp-merge-upstream" "$TMP_ROOT/exp-merge-patches" \
        "$TMP_ROOT/exp-merge-cache" "$TMP_ROOT/exp-merge-tree" \
        "$TMP_ROOT/exp-merge-exportdir"

    _run_sync --common-only
    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-merge-before"

    git -C "$DS4_TREE_DIR" checkout -q -b exp-side
    printf 'side\n' > "$DS4_TREE_DIR/side.txt"
    git -C "$DS4_TREE_DIR" add side.txt
    git -C "$DS4_TREE_DIR" commit -qm "side change"
    git -C "$DS4_TREE_DIR" checkout -q refs/heads/ds4/common
    printf 'main\n' > "$DS4_TREE_DIR/main.txt"
    git -C "$DS4_TREE_DIR" add main.txt
    git -C "$DS4_TREE_DIR" commit -qm "main change"
    git -C "$DS4_TREE_DIR" merge --no-ff -q -m "merge side" exp-side

    local err="$TMP_ROOT/exp-merge.err"
    if _run_export 2>"$err"; then
        printf '  FAIL: expected merge commit to be rejected\n' >&2
        return 1
    fi
    grep -q 'merge' "$err" || {
        printf '  FAIL: error did not mention merge commits\n' >&2
        return 1
    }
    _assert_dirs_identical "$TMP_ROOT/exp-merge-before" "$DS4_PATCHES_DIR" \
        "patches unchanged after merge rejection"
}

test_export_rejects_empty_range() {
    _export_fixture "$TMP_ROOT/exp-empty-upstream" "$TMP_ROOT/exp-empty-patches" \
        "$TMP_ROOT/exp-empty-cache" "$TMP_ROOT/exp-empty-tree" \
        "$TMP_ROOT/exp-empty-exportdir"

    _run_sync
    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-empty-before"

    # Move the editable tip back to the previous model tip so the recorded
    # range PREVIOUS_TIP..HEAD is empty.
    git -C "$DS4_TREE_DIR" reset --hard -q refs/ds4/model/alpha

    local err="$TMP_ROOT/exp-empty.err"
    if _run_export 2>"$err"; then
        printf '  FAIL: expected empty range to be rejected\n' >&2
        return 1
    fi
    grep -q 'empty' "$err" || {
        printf '  FAIL: error did not mention empty range\n' >&2
        return 1
    }
    _assert_dirs_identical "$TMP_ROOT/exp-empty-before" "$DS4_PATCHES_DIR" \
        "patches unchanged after empty-range rejection"
}

test_export_rejects_dirty_patches_without_force() {
    _export_fixture "$TMP_ROOT/exp-dirty-upstream" "$TMP_ROOT/exp-dirty-patches" \
        "$TMP_ROOT/exp-dirty-cache" "$TMP_ROOT/exp-dirty-tree" \
        "$TMP_ROOT/exp-dirty-exportdir"

    _run_sync --common-only

    printf 'common-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "common edit"

    printf 'dirty\n' > "$DS4_PATCHES_DIR/common/dirty-marker"

    local err="$TMP_ROOT/exp-dirty.err"
    if _run_export 2>"$err"; then
        printf '  FAIL: expected dirty patches to be rejected without --force\n' >&2
        return 1
    fi
    grep -q 'dirty' "$err" || {
        printf '  FAIL: error did not mention dirty patches\n' >&2
        return 1
    }
    [[ -f "$DS4_PATCHES_DIR/common/dirty-marker" ]] || {
        printf '  FAIL: dirty marker should survive refusal\n' >&2
        return 1
    }

    _run_export --force

    [[ ! -e "$DS4_PATCHES_DIR/common/dirty-marker" ]] || {
        printf '  FAIL: --force must replace the dirty owned directory\n' >&2
        return 1
    }
    ds4_patch_files "$DS4_PATCHES_DIR/common"
    assert_eq "2" "${#DS4_PATCH_FILES[@]}" "forced export patch count"
}

test_export_round_trip_failure_leaves_all_patch_bytes_untouched() {
    _export_fixture "$TMP_ROOT/exp-rt-upstream" "$TMP_ROOT/exp-rt-patches" \
        "$TMP_ROOT/exp-rt-cache" "$TMP_ROOT/exp-rt-tree" \
        "$TMP_ROOT/exp-rt-exportdir"

    _run_sync

    printf 'zebra-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit"

    # Make the committed common directory stale so the reconstructed common
    # boundary can never match the scratch ref.
    local patch="$DS4_PATCHES_DIR/common/0001-add-common.patch"
    sed 's/^+common$/+STALE/' "$patch" > "$patch.tmp"
    mv "$patch.tmp" "$patch"

    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-rt-before"

    local err="$TMP_ROOT/exp-rt.err"
    if _run_export 2>"$err"; then
        printf '  FAIL: expected round-trip failure to be rejected\n' >&2
        return 1
    fi
    grep -q 'boundary' "$err" || {
        printf '  FAIL: error did not mention boundary mismatch\n' >&2
        return 1
    }
    _assert_dirs_identical "$TMP_ROOT/exp-rt-before" "$DS4_PATCHES_DIR" \
        "all patch bytes untouched after round-trip failure"
}

test_export_replacement_interruption_restores_original() {
    _export_fixture "$TMP_ROOT/exp-int-upstream" "$TMP_ROOT/exp-int-patches" \
        "$TMP_ROOT/exp-int-cache" "$TMP_ROOT/exp-int-tree" \
        "$TMP_ROOT/exp-int-exportdir"

    _run_sync

    printf 'zebra-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit"

    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-int-before"

    # Shim mv so the candidate->owned replacement reports failure *after* it
    # has already moved the candidate into place. That is the interruption
    # window after the original is backed up but before the replaced state is
    # observed; cleanup must still restore the original bytes.
    local bindir="$TMP_ROOT/exp-int-bin" real_mv
    real_mv="$(command -v mv)"
    mkdir -p "$bindir"
    cat > "$bindir/mv" <<EOF
#!/usr/bin/env bash
if [[ "\$2" == "$DS4_PATCHES_DIR/zebra" && "\$1" == */candidate ]]; then
    "$real_mv" "\$1" "\$2"
    exit 1
fi
exec "$real_mv" "\$@"
EOF
    chmod +x "$bindir/mv"

    local err="$TMP_ROOT/exp-int.err"
    if PATH="$bindir:$PATH" _run_export 2>"$err"; then
        printf '  FAIL: expected interrupted replacement to fail\n' >&2
        return 1
    fi
    grep -q 'candidate' "$err" || {
        printf '  FAIL: error did not mention candidate move failure\n' >&2
        return 1
    }
    _assert_dirs_identical "$TMP_ROOT/exp-int-before" "$DS4_PATCHES_DIR" \
        "all patch bytes untouched after replacement interruption"
}

test_export_ref_update_interruption_rolls_back_ref_and_directory() {
    _export_fixture "$TMP_ROOT/exp-ref-upstream" "$TMP_ROOT/exp-ref-patches" \
        "$TMP_ROOT/exp-ref-cache" "$TMP_ROOT/exp-ref-tree" \
        "$TMP_ROOT/exp-ref-exportdir"

    _run_sync

    printf 'zebra-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit"

    local ref_before
    ref_before="$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/zebra)"
    cp "$DS4_TREE_DIR/.git/ds4-state" "$TMP_ROOT/exp-ref-state-before" ||
        return 1
    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-ref-before"

    # Shim git so the selected-boundary update-ref performs the write and then
    # reports failure, like a signal landing after the ref write but before the
    # rollback flag was recorded in the old ordering. Cleanup must roll the ref
    # back and restore the replaced directory.
    local bindir="$TMP_ROOT/exp-ref-bin" real_git
    real_git="$(command -v git)"
    mkdir -p "$bindir"
    cat > "$bindir/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "-C" && "\$2" == "$DS4_TREE_DIR" && "\$3" == "update-ref" && "\$4" == "refs/ds4/model/zebra" ]]; then
    "$real_git" "\$@"
    exit 1
fi
exec "$real_git" "\$@"
EOF
    chmod +x "$bindir/git"

    local err="$TMP_ROOT/exp-ref.err"
    if PATH="$bindir:$PATH" _run_export 2>"$err"; then
        printf '  FAIL: expected interrupted ref update to fail\n' >&2
        return 1
    fi
    grep -q 'boundary ref' "$err" || {
        printf '  FAIL: error did not mention boundary ref\n' >&2
        return 1
    }

    assert_eq "$ref_before" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/zebra)" \
        "interrupted ref update restored selected boundary ref"
    _assert_dirs_identical "$TMP_ROOT/exp-ref-before" "$DS4_PATCHES_DIR" \
        "all patch bytes untouched after ref update interruption"
    cmp -s "$TMP_ROOT/exp-ref-state-before" "$DS4_TREE_DIR/.git/ds4-state" || {
        printf '  FAIL: state changed after ref update interruption\n' >&2
        return 1
    }
}

test_export_state_write_interruption_rolls_back_state_ref_and_directory() {
    _export_fixture "$TMP_ROOT/exp-state-upstream" "$TMP_ROOT/exp-state-patches" \
        "$TMP_ROOT/exp-state-cache" "$TMP_ROOT/exp-state-tree" \
        "$TMP_ROOT/exp-state-exportdir"

    _run_sync

    printf 'zebra-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "zebra edit"

    local ref_before
    ref_before="$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/zebra)"
    cp "$DS4_TREE_DIR/.git/ds4-state" "$TMP_ROOT/exp-state-state-before" ||
        return 1
    _snapshot_dir "$DS4_PATCHES_DIR" "$TMP_ROOT/exp-state-before"

    # Shim mv so the ds4-state write lands and then reports failure, like a
    # signal after the state file is moved but before the completion flag.
    # Cleanup must restore the original state bytes, the advanced boundary
    # ref, and the replaced patch directory.
    local bindir="$TMP_ROOT/exp-state-bin" real_mv
    real_mv="$(command -v mv)"
    mkdir -p "$bindir"
    cat > "$bindir/mv" <<EOF
#!/usr/bin/env bash
if [[ "\$3" == "$DS4_TREE_DIR/.git/ds4-state" ]]; then
    "$real_mv" "\$@"
    exit 1
fi
exec "$real_mv" "\$@"
EOF
    chmod +x "$bindir/mv"

    local err="$TMP_ROOT/exp-state.err"
    if PATH="$bindir:$PATH" _run_export 2>"$err"; then
        printf '  FAIL: expected interrupted state write to fail\n' >&2
        return 1
    fi
    grep -q 'state file' "$err" || {
        printf '  FAIL: error did not mention state file\n' >&2
        return 1
    }

    assert_eq "$ref_before" \
        "$(git -C "$DS4_TREE_DIR" rev-parse refs/ds4/model/zebra)" \
        "interrupted state write restored selected boundary ref"
    _assert_dirs_identical "$TMP_ROOT/exp-state-before" "$DS4_PATCHES_DIR" \
        "all patch bytes untouched after state write interruption"
    cmp -s "$TMP_ROOT/exp-state-state-before" "$DS4_TREE_DIR/.git/ds4-state" || {
        printf '  FAIL: state not restored after state write interruption\n' >&2
        return 1
    }
}

test_export_then_check_common() {
    _export_fixture "$TMP_ROOT/exp-check-common-upstream" \
        "$TMP_ROOT/exp-check-common-patches" \
        "$TMP_ROOT/exp-check-common-cache" \
        "$TMP_ROOT/exp-check-common-tree" \
        "$TMP_ROOT/exp-check-common-exportdir"
    export DS4_CHECK_DIR="$TMP_ROOT/exp-check-common-checkdir"

    _run_sync --common-only

    printf 'common-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "common edit a"

    _run_export

    local out="$TMP_ROOT/exp-check-common.out"
    local err="$TMP_ROOT/exp-check-common.err"
    if ! _run_check --common-only >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: export->check common failed\n' >&2
        return 1
    fi
    grep -q '^check common$' "$out" || {
        printf '  FAIL: export->check common did not report common\n' >&2
        return 1
    }
}

test_export_then_check_model() {
    _export_fixture "$TMP_ROOT/exp-check-model-upstream" \
        "$TMP_ROOT/exp-check-model-patches" \
        "$TMP_ROOT/exp-check-model-cache" \
        "$TMP_ROOT/exp-check-model-tree" \
        "$TMP_ROOT/exp-check-model-exportdir"
    export DS4_CHECK_DIR="$TMP_ROOT/exp-check-model-checkdir"

    _run_sync --model alpha

    printf 'alpha-a\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "alpha edit a"

    _run_export

    local out="$TMP_ROOT/exp-check-model.out"
    local err="$TMP_ROOT/exp-check-model.err"
    if ! _run_check --model alpha >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: export->check model failed\n' >&2
        return 1
    fi
    grep -q '^check alpha$' "$out" || {
        printf '  FAIL: export->check model did not report alpha\n' >&2
        return 1
    }
}

test_export_help_prints_usage_without_changes() {
    _export_fixture "$TMP_ROOT/exp-help-upstream" "$TMP_ROOT/exp-help-patches" \
        "$TMP_ROOT/exp-help-cache" "$TMP_ROOT/exp-help-tree" \
        "$TMP_ROOT/exp-help-exportdir"

    local out="$TMP_ROOT/exp-help.out"
    _run_export --help >"$out"

    grep -q 'Usage: ds4-export' "$out" || {
        printf '  FAIL: help did not print usage\n' >&2
        return 1
    }
    [[ ! -e "$DS4_TREE_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/tree\n' >&2
        return 1
    }
    [[ ! -e "$DS4_EXPORT_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/export\n' >&2
        return 1
    }
}

# --- check tests --------------------------------------------------------------

_run_check() {
    bash "$REPO_ROOT/tools/ds4-check.bash" "$@"
}

# Read FILE lines into the global _DS4_TEST_LINES array.
_read_lines() {
    _DS4_TEST_LINES=()
    local file="$1" line
    while IFS= read -r line || [[ -n "$line" ]]; do
        _DS4_TEST_LINES+=("$line")
    done < "$file"
}

# Build an upstream and a common/alpha/zebra patch series, then export the
# globals the ds4-check subprocess consumes. DS4_TREE_DIR points at a path
# that does not yet exist unless a test materializes a scratch tree first.
_check_fixture() {
    local upstream="$1" patches="$2" cache="$3" tree="$4" checkdir="$5"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm "base"
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    mkdir -p "$patches"
    _build_series "$patches"

    export DS4_PATCHES_DIR="$patches"
    export DS4_CACHE_DIR="$cache"
    export DS4_TREE_DIR="$tree"
    export DS4_CHECK_DIR="$checkdir"
    export UPSTREAM_URL="$upstream"
    export UPSTREAM_COMMIT="$pin"
}

test_check_default_covers_common_every_prefix_and_full_tree() {
    _check_fixture "$TMP_ROOT/check-default-upstream" \
        "$TMP_ROOT/check-default-patches" \
        "$TMP_ROOT/check-default-cache" \
        "$TMP_ROOT/check-default-tree" \
        "$TMP_ROOT/check-default-checkdir"

    local out="$TMP_ROOT/check-default.out"
    _run_check >"$out"

    grep -q '^check common$' "$out" || {
        printf '  FAIL: default check did not report common\n' >&2
        return 1
    }
    grep -q '^check alpha$' "$out" || {
        printf '  FAIL: default check did not report alpha\n' >&2
        return 1
    }
    grep -q '^check zebra$' "$out" || {
        printf '  FAIL: default check did not report zebra\n' >&2
        return 1
    }

    sed -n 's/^clone //p' "$out" > "$TMP_ROOT/check-default-paths"
    _read_lines "$TMP_ROOT/check-default-paths"
    local paths=("${_DS4_TEST_LINES[@]}")

    assert_eq "3" "${#paths[@]}" "default check clone count"
    [[ "${paths[0]}" != "${paths[1]}" &&
       "${paths[1]}" != "${paths[2]}" &&
       "${paths[0]}" != "${paths[2]}" ]] || {
        printf '  FAIL: default check must use separate pristine clones\n' >&2
        return 1
    }

    local i
    for i in 0 1 2; do
        assert_eq "$UPSTREAM_COMMIT" \
            "$(git -C "${paths[$i]}" rev-parse refs/ds4/common^)" \
            "clone $i starts at pin"
    done

    assert_file_eq $'line1\ncommon\n' "${paths[0]}/notes.txt" \
        "common target content"
    assert_file_eq $'line1\ncommon\nalpha\n' "${paths[1]}/notes.txt" \
        "alpha target content"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' "${paths[2]}/notes.txt" \
        "zebra target content"
}

test_check_selected_target() {
    _check_fixture "$TMP_ROOT/check-sel-upstream" "$TMP_ROOT/check-sel-patches" \
        "$TMP_ROOT/check-sel-cache" "$TMP_ROOT/check-sel-tree" \
        "$TMP_ROOT/check-sel-checkdir"

    local out="$TMP_ROOT/check-sel-model.out"
    _run_check --model alpha >"$out"

    grep -q '^check alpha$' "$out" || {
        printf '  FAIL: --model alpha did not report alpha\n' >&2
        return 1
    }
    if grep -q '^check common$' "$out"; then
        printf '  FAIL: --model alpha must not check common\n' >&2
        return 1
    fi
    if grep -q '^check zebra$' "$out"; then
        printf '  FAIL: --model alpha must not check zebra\n' >&2
        return 1
    fi

    sed -n 's/^clone //p' "$out" > "$TMP_ROOT/check-sel-model-paths"
    _read_lines "$TMP_ROOT/check-sel-model-paths"
    assert_eq "1" "${#_DS4_TEST_LINES[@]}" "selected model clone count"
    assert_file_eq $'line1\ncommon\nalpha\n' \
        "${_DS4_TEST_LINES[0]}/notes.txt" "selected model content"

    local out2="$TMP_ROOT/check-sel-common.out"
    _run_check --common-only >"$out2"

    grep -q '^check common$' "$out2" || {
        printf '  FAIL: --common-only did not report common\n' >&2
        return 1
    }
    if grep -q '^check alpha$' "$out2"; then
        printf '  FAIL: --common-only must not check alpha\n' >&2
        return 1
    fi
    if grep -q '^check zebra$' "$out2"; then
        printf '  FAIL: --common-only must not check zebra\n' >&2
        return 1
    fi
}

test_check_rejects_corrupt_patch_series() {
    _check_fixture "$TMP_ROOT/check-corrupt-upstream" \
        "$TMP_ROOT/check-corrupt-patches" \
        "$TMP_ROOT/check-corrupt-cache" \
        "$TMP_ROOT/check-corrupt-tree" \
        "$TMP_ROOT/check-corrupt-checkdir"

    printf 'not a patch\n' > "$DS4_PATCHES_DIR/common/0001-add-common.patch"

    local err="$TMP_ROOT/check-corrupt.err"
    if _run_check >/dev/null 2>"$err"; then
        printf '  FAIL: expected corrupt patch series to fail\n' >&2
        return 1
    fi
    grep -q 'git am' "$err" || {
        printf '  FAIL: error did not mention git am failure\n' >&2
        return 1
    }
}

test_check_build_passes_real_source_path_to_ds4py() {
    _check_fixture "$TMP_ROOT/check-build-upstream" "$TMP_ROOT/check-build-patches" \
        "$TMP_ROOT/check-build-cache" "$TMP_ROOT/check-build-tree" \
        "$TMP_ROOT/check-build-checkdir"

    local bin="$TMP_ROOT/check-build-bin"
    mkdir -p "$bin"
    local log="$TMP_ROOT/check-build-args.log"
    rm -f "$log"
    cat > "$bin/ds4py" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >> "$log"
EOF
    chmod +x "$bin/ds4py"

    local out="$TMP_ROOT/check-build.out"
    PATH="$bin:$PATH" _run_check --build >"$out"

    sed -n 's/^clone //p' "$out" > "$TMP_ROOT/check-build-paths"
    _read_lines "$TMP_ROOT/check-build-paths"
    local paths=("${_DS4_TEST_LINES[@]}")

    _read_lines "$log"
    local args=("${_DS4_TEST_LINES[@]}")

    local backend
    case "$(uname -s)" in
        Darwin) backend="metal" ;;
        *) backend="cpu" ;;
    esac

    assert_eq "3" "${#paths[@]}" "check build clone count"
    assert_eq "15" "${#args[@]}" "ds4py build argument count"

    local i off
    for i in 0 1 2; do
        off=$((i * 5))
        assert_eq "build" "${args[$off]}" "build arg $i word 1"
        assert_eq "--src" "${args[$off + 1]}" "build arg $i word 2"
        assert_eq "${paths[$i]}" "${args[$off + 2]}" "build arg $i src path"
        assert_eq "--backend" "${args[$off + 3]}" "build arg $i word 4"
        assert_eq "$backend" "${args[$off + 4]}" "build arg $i backend"
    done
}

test_check_detects_stale_scratch_tree() {
    _sync_fixture "$TMP_ROOT/check-stale-upstream" "$TMP_ROOT/check-stale-patches" \
        "$TMP_ROOT/check-stale-cache" "$TMP_ROOT/check-stale-tree"
    export DS4_CHECK_DIR="$TMP_ROOT/check-stale-checkdir"
    _run_sync

    # An unexported commit advances the scratch HEAD without touching the
    # committed patches, so the full target reconstruction must diverge.
    printf 'unexported\n' >> "$DS4_TREE_DIR/notes.txt"
    git -C "$DS4_TREE_DIR" add notes.txt
    git -C "$DS4_TREE_DIR" commit -qm "unexported change"

    local err="$TMP_ROOT/check-stale.err"
    if _run_check >/dev/null 2>"$err"; then
        printf '  FAIL: expected stale scratch tree to fail\n' >&2
        return 1
    fi
    grep -q 'final tree' "$err" || {
        printf '  FAIL: error did not mention final tree mismatch\n' >&2
        return 1
    }
}

test_check_detects_corrupt_selected_boundary_ref() {
    _check_fixture "$TMP_ROOT/check-boundary-upstream" \
        "$TMP_ROOT/check-boundary-patches" \
        "$TMP_ROOT/check-boundary-cache" \
        "$TMP_ROOT/check-boundary-tree" \
        "$TMP_ROOT/check-boundary-checkdir"
    _run_sync --model alpha

    # Corrupt only the selected model's boundary ref, leaving the preceding
    # common boundary and final HEAD intact. A stale refs/ds4/model/alpha must
    # still fail even when HEAD^{tree} still matches.
    git -C "$DS4_TREE_DIR" update-ref refs/ds4/model/alpha refs/ds4/common

    local err="$TMP_ROOT/check-boundary.err"
    if _run_check --model alpha >/dev/null 2>"$err"; then
        printf '  FAIL: expected corrupt selected boundary ref to fail\n' >&2
        return 1
    fi
    grep -q 'alpha boundary tree' "$err" || {
        printf '  FAIL: error did not mention alpha boundary mismatch\n' >&2
        return 1
    }
}

test_check_help_prints_usage_without_changes() {
    _check_fixture "$TMP_ROOT/check-help-upstream" "$TMP_ROOT/check-help-patches" \
        "$TMP_ROOT/check-help-cache" "$TMP_ROOT/check-help-tree" \
        "$TMP_ROOT/check-help-checkdir"

    local out="$TMP_ROOT/check-help.out"
    _run_check --help >"$out"

    grep -q 'Usage: ds4-check' "$out" || {
        printf '  FAIL: help did not print usage\n' >&2
        return 1
    }
    [[ ! -e "$DS4_CACHE_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/cache\n' >&2
        return 1
    }
    [[ ! -e "$DS4_TREE_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/tree\n' >&2
        return 1
    }
    [[ ! -e "$DS4_CHECK_DIR" ]] || {
        printf '  FAIL: --help must not create .ds4/check\n' >&2
        return 1
    }
}

test_check_rejects_invalid_arguments() {
    _check_fixture "$TMP_ROOT/check-args-upstream" "$TMP_ROOT/check-args-patches" \
        "$TMP_ROOT/check-args-cache" "$TMP_ROOT/check-args-tree" \
        "$TMP_ROOT/check-args-checkdir"
    local err="$TMP_ROOT/check-args.err"

    if _run_check --common-only --model alpha 2>"$err"; then
        printf '  FAIL: expected --common-only --model to fail\n' >&2
        return 1
    fi
    grep -q 'common-only' "$err" || {
        printf '  FAIL: error did not mention common-only\n' >&2
        return 1
    }

    if _run_check --model nope 2>"$err"; then
        printf '  FAIL: expected unknown model to fail\n' >&2
        return 1
    fi
    grep -q 'unknown model' "$err" || {
        printf '  FAIL: error did not mention unknown model\n' >&2
        return 1
    }

    if _run_check extra 2>"$err"; then
        printf '  FAIL: expected extra argument to fail\n' >&2
        return 1
    fi
    grep -q 'unexpected argument' "$err" || {
        printf '  FAIL: error did not mention unexpected argument\n' >&2
        return 1
    }
}

# --- devenv entry-point tests -------------------------------------------------

test_devenv_entry_points_show_help() {
    # The suite also runs on ubuntu-latest where devenv/Nix is not installed;
    # entry-point registration is exercised here whenever devenv is present
    # and via `devenv shell -- ds4-<tool> --help` in the developer workflow.
    if ! command -v devenv >/dev/null 2>&1; then
        printf '  SKIP: devenv is not available on PATH\n' >&2
        return 0
    fi

    local out err

    out="$TMP_ROOT/ds4-entry-sync.out"
    err="$TMP_ROOT/ds4-entry-sync.err"
    if ! devenv shell -- ds4-sync --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-sync --help failed\n' >&2
        return 1
    fi
    grep -q -- '--common-only' "$out" || {
        printf '  FAIL: ds4-sync help did not mention --common-only\n' >&2
        return 1
    }
    grep -q -- '--model' "$out" || {
        printf '  FAIL: ds4-sync help did not mention --model\n' >&2
        return 1
    }

    out="$TMP_ROOT/ds4-entry-export.out"
    err="$TMP_ROOT/ds4-entry-export.err"
    if ! devenv shell -- ds4-export --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-export --help failed\n' >&2
        return 1
    fi
    grep -q -- '--force' "$out" || {
        printf '  FAIL: ds4-export help did not mention --force\n' >&2
        return 1
    }

    out="$TMP_ROOT/ds4-entry-check.out"
    err="$TMP_ROOT/ds4-entry-check.err"
    if ! devenv shell -- ds4-check --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-check --help failed\n' >&2
        return 1
    fi
    grep -q -- '--common-only' "$out" || {
        printf '  FAIL: ds4-check help did not mention --common-only\n' >&2
        return 1
    }
    grep -q -- '--model' "$out" || {
        printf '  FAIL: ds4-check help did not mention --model\n' >&2
        return 1
    }
    grep -q -- '--build' "$out" || {
        printf '  FAIL: ds4-check help did not mention --build\n' >&2
        return 1
    }
}

# --- model-backed E2E preflight tests -----------------------------------------

# Write a minimal, tensor-free GGUF whose general.architecture is ARCH. This
# exercises the E2E metadata preflight without generating a real model.
_write_gguf_fixture() {
    local file="$1" arch="$2"
    python3 - "$file" "$arch" <<'PY'
import struct, sys
path, arch = sys.argv[1], sys.argv[2]
def string(data):
    return struct.pack("<Q", len(data)) + data
kv = string(b"general.architecture") + struct.pack("<I", 8) + string(arch.encode())
header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 1)
with open(path, "wb") as fp:
    fp.write(header + kv)
PY
}

# Copy the E2E script and the tools it runs into a standalone repo root so a
# test can exercise the gate hermetically (its .ds4/tree is a disposable
# "normal" tree).
_e2e_scratch_repo() {
    local dest="$1"
    mkdir -p "$dest/tools" "$dest/tests"
    cp "$REPO_ROOT/tools/ds4-lib.bash" \
        "$REPO_ROOT/tools/ds4-sync.bash" \
        "$REPO_ROOT/tools/ds4-check.bash" \
        "$REPO_ROOT/tools/ds4-export.bash" \
        "$REPO_ROOT/tools/ds4-gguf-arch.py" "$dest/tools/"
    cp "$REPO_ROOT/tests/ds4_e2e_test.bash" "$dest/tests/"
}

# Run the model-backed E2E script in a controlled environment and capture its
# stderr. These tests exercise only the script's input validation: a missing
# DS4PY_PROJECT or DS4_TEST_MODEL must produce a clear nonzero usage error
# before the script reads a model, resolves ds4py, or builds anything.
test_e2e_requires_external_ds4py() {
    local err="$TMP_ROOT/e2e-no-ds4py.err"
    if ( unset DS4PY_PROJECT DS4_TEST_MODEL 2>/dev/null || true
         bash "$REPO_ROOT/tests/ds4_e2e_test.bash" ) 2>"$err"; then
        printf '  FAIL: expected missing DS4PY_PROJECT to fail\n' >&2
        return 1
    fi
    grep -q 'DS4PY_PROJECT' "$err" || {
        printf '  FAIL: error did not mention DS4PY_PROJECT\n' >&2
        return 1
    }
    if grep -q 'DS4_TEST_MODEL' "$err"; then
        printf '  FAIL: DS4PY_PROJECT must be validated before the model\n' >&2
        return 1
    fi
}

test_e2e_requires_dense_qwen35_model() {
    # Point DS4PY_PROJECT at a path that does not exist: a correct preflight
    # must report the missing model before it ever touches that checkout.
    local err="$TMP_ROOT/e2e-no-model.err"
    if ( unset DS4_TEST_MODEL 2>/dev/null || true
         DS4PY_PROJECT="$TMP_ROOT/absent-ds4py" \
         bash "$REPO_ROOT/tests/ds4_e2e_test.bash" ) 2>"$err"; then
        printf '  FAIL: expected missing DS4_TEST_MODEL to fail\n' >&2
        return 1
    fi
    grep -q 'DS4_TEST_MODEL' "$err" || {
        printf '  FAIL: error did not mention DS4_TEST_MODEL\n' >&2
        return 1
    }
    if grep -q 'not found' "$err"; then
        printf '  FAIL: model check must not resolve the ds4-py checkout\n' >&2
        return 1
    fi
}

test_e2e_rejects_wrong_architecture_model() {
    local venv="$TMP_ROOT/e2e-wrong-venv"
    mkdir -p "$venv/.venv/bin"
    ln -s "$(command -v python3)" "$venv/.venv/bin/python3"

    local model="$TMP_ROOT/e2e-wrong.gguf"
    _write_gguf_fixture "$model" qwen4exp

    local err="$TMP_ROOT/e2e-wrong.err"
    if ( DS4PY_PROJECT="$venv" DS4_TEST_MODEL="$model" \
         bash "$REPO_ROOT/tests/ds4_e2e_test.bash" ) 2>"$err"; then
        printf '  FAIL: expected wrong-architecture model to be rejected\n' >&2
        return 1
    fi
    grep -q 'qwen35' "$err" || {
        printf '  FAIL: error did not mention the required qwen35 architecture\n' >&2
        return 1
    }
    grep -q 'qwen4exp' "$err" || {
        printf '  FAIL: error did not report the observed architecture\n' >&2
        return 1
    }
}

test_e2e_uses_isolated_tree_and_preserves_normal_tree() {
    local repo="$TMP_ROOT/e2e-repo"
    _e2e_scratch_repo "$repo"

    local upstream="$TMP_ROOT/e2e-upstream"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm base
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    local patches="$TMP_ROOT/e2e-patches"
    mkdir -p "$patches"
    _build_series "$patches"

    # A disposable "normal" .ds4/tree that the gate must leave alone.
    local normal_tree="$repo/.ds4/tree"
    mkdir -p "$normal_tree"
    git -C "$normal_tree" init -q
    printf 'keep\n' > "$normal_tree/normal-marker"
    git -C "$normal_tree" add normal-marker
    git -C "$normal_tree" commit -qm normal
    local normal_head
    normal_head="$(git -C "$normal_tree" rev-parse HEAD)"

    # Fake ds4-py venv: the pinned Python runs the metadata probe, and a stub
    # ds4py fails at the build step so the gate stops there deterministically.
    local venv="$TMP_ROOT/e2e-venv"
    mkdir -p "$venv/.venv/bin"
    ln -s "$(command -v python3)" "$venv/.venv/bin/python3"
    cat > "$venv/.venv/bin/ds4py" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
    chmod +x "$venv/.venv/bin/ds4py"

    # Correct-architecture fixture, referenced by a RELATIVE path to exercise
    # canonicalization as well.
    local model="$TMP_ROOT/e2e-model.gguf"
    _write_gguf_fixture "$model" qwen35

    local out="$TMP_ROOT/e2e-isolated.out"
    local err="$TMP_ROOT/e2e-isolated.err"
    if ( cd "$TMP_ROOT" &&
         DS4PY_PROJECT="$venv" \
         DS4_TEST_MODEL="e2e-model.gguf" \
         DS4_PATCHES_DIR="$patches" \
         DS4_CACHE_DIR="$TMP_ROOT/e2e-cache" \
         UPSTREAM_URL="$upstream" \
         UPSTREAM_COMMIT="$pin" \
         bash "$repo/tests/ds4_e2e_test.bash" ) >"$out" 2>"$err"; then
        printf '  FAIL: expected e2e to stop at the ds4py build step\n' >&2
        return 1
    fi
    grep -q 'ds4py build failed' "$err" || {
        cat "$err" >&2
        printf '  FAIL: expected e2e to reach the ds4py build step\n' >&2
        return 1
    }

    assert_eq "$normal_head" "$(git -C "$normal_tree" rev-parse HEAD)" \
        "normal .ds4/tree HEAD survives e2e"
    assert_file_eq $'keep\n' "$normal_tree/normal-marker" \
        "normal .ds4/tree marker survives e2e"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' \
        "$repo/.ds4/e2e/tree/notes.txt" "isolated e2e tree materialized"

    local canonical_model
    canonical_model="$(cd "$TMP_ROOT" && pwd)/e2e-model.gguf"
    grep -q "model  $canonical_model" "$out" || {
        cat "$out" >&2
        printf '  FAIL: e2e did not canonicalize the relative model path\n' >&2
        return 1
    }
}

# --- runner -------------------------------------------------------------------

ALL_TESTS=(
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
    test_sync_defaults_to_all_models
    test_sync_common_only
    test_sync_model_stops_at_editable_prefix
    test_sync_rejects_invalid_arguments
    test_sync_rejects_common_and_empty_model
    test_sync_help_prints_usage_without_tree
    test_sync_refuses_dirty_tree_without_force
    test_sync_refuses_unexported_commit_without_force
    test_sync_force_replaces_only_scratch_tree
    test_sync_interrupted_old_tree_move_restores_original
    test_export_common_renumbers_real_range
    test_export_empty_model_list_fails_cleanly
    test_export_model_uses_previous_model_tip
    test_export_rejects_merge_commit
    test_export_rejects_empty_range
    test_export_rejects_dirty_patches_without_force
    test_export_round_trip_failure_leaves_all_patch_bytes_untouched
    test_export_replacement_interruption_restores_original
    test_export_ref_update_interruption_rolls_back_ref_and_directory
    test_export_state_write_interruption_rolls_back_state_ref_and_directory
    test_export_then_check_common
    test_export_then_check_model
    test_export_help_prints_usage_without_changes
    test_check_default_covers_common_every_prefix_and_full_tree
    test_check_selected_target
    test_check_rejects_corrupt_patch_series
    test_check_build_passes_real_source_path_to_ds4py
    test_check_detects_stale_scratch_tree
    test_check_detects_corrupt_selected_boundary_ref
    test_check_help_prints_usage_without_changes
    test_check_rejects_invalid_arguments
    test_devenv_entry_points_show_help
    test_e2e_requires_external_ds4py
    test_e2e_requires_dense_qwen35_model
    test_e2e_rejects_wrong_architecture_model
    test_e2e_uses_isolated_tree_and_preserves_normal_tree
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
