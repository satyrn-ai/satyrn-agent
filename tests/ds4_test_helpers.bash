#!/usr/bin/env bash
#
# tests/ds4_test_helpers.bash
#
# Shared setup, assertions, fixtures, and runner for the ds4 test modules.
# Source this file; do not execute it. Bash 3.2-compatible.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TEST_DIR/.." && pwd)"

source "$REPO_ROOT/tools/ds4-lib.bash"

# Run every test module in a private temp tree and keep Git isolated from user
# and system configuration while still giving temp repositories an identity.
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

# Return success when REF resolves in TREE, failure when it is absent.
_ref_exists() {
    local tree="$1" ref="$2"
    git -C "$tree" rev-parse --verify --quiet "$ref" >/dev/null 2>&1
}

# --- shared tool runners and fixtures -----------------------------------------

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

_run_check() {
    bash "$REPO_ROOT/tools/ds4-check.bash" "$@"
}

# --- runner -------------------------------------------------------------------

PASSED=0
FAILED=0

ds4_run_test() {
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

ds4_run_module() {
    local names=() t
    if [[ $# -eq 0 ]]; then
        names=("${DS4_MODULE_TESTS[@]}")
    else
        names=("$@")
    fi

    PASSED=0
    FAILED=0
    for t in "${names[@]}"; do
        ds4_run_test "$t"
    done

    if [[ -n "${DS4_COUNTS_FILE:-}" ]]; then
        printf '%d %d\n' "$PASSED" "$FAILED" > "$DS4_COUNTS_FILE"
    fi
    if [[ "${DS4_MODULE_SUMMARY:-1}" == "1" ]]; then
        printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
    fi
    [[ $FAILED -eq 0 ]]
}

ds4_module_main() {
    if [[ "${1:-}" == "--list-tests" ]]; then
        printf '%s\n' "${DS4_MODULE_TESTS[@]}"
        return 0
    fi
    ds4_run_module "$@"
}
