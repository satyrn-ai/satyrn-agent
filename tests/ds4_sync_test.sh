#!/usr/bin/env bash
#
# tests/ds4_sync_test.sh
#
# Tests for tools/ds4-sync.sh.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TEST_DIR/ds4_test_helpers.sh"

# --- sync tests ---------------------------------------------------------------

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

DS4_MODULE_TESTS=(
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
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
