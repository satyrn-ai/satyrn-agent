#!/usr/bin/env bash
#
# tests/ds4_check_test.sh
#
# Tests for tools/ds4-check.sh.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TEST_DIR/ds4_test_helpers.sh"

# --- check tests --------------------------------------------------------------

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

DS4_MODULE_TESTS=(
    test_check_default_covers_common_every_prefix_and_full_tree
    test_check_selected_target
    test_check_rejects_corrupt_patch_series
    test_check_build_passes_real_source_path_to_ds4py
    test_check_detects_stale_scratch_tree
    test_check_detects_corrupt_selected_boundary_ref
    test_check_help_prints_usage_without_changes
    test_check_rejects_invalid_arguments
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
