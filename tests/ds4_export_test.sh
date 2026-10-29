#!/usr/bin/env bash
#
# tests/ds4_export_test.sh
#
# Tests for tools/ds4-export.sh.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TEST_DIR/ds4_test_helpers.sh"

# --- export tests --------------------------------------------------------------

_run_export() {
    bash "$REPO_ROOT/tools/ds4-export.sh" "$@"
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

DS4_MODULE_TESTS=(
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
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
