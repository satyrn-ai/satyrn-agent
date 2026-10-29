#!/usr/bin/env bash
#
# tools/ds4-sync.bash
#
# Materialize .ds4/tree from .ds4/cache at the pinned upstream commit, apply
# the selected patch target, and record the scratch branch and state.
#
# Usage:
#   ds4-sync [--common-only | --model NAME] [--force]
#   ds4-sync --help
#
# Environment overrides (used by tests and the other ds4 tools):
#   DS4_PATCHES_DIR  patch series root (default <repo>/patches)
#   DS4_CACHE_DIR    upstream mirror (default <repo>/.ds4/cache)
#   DS4_TREE_DIR     materialized tree (default <repo>/.ds4/tree)
#   UPSTREAM_URL, UPSTREAM_COMMIT  skip reading upstream.pin when both are set

set -euo pipefail

_DS4_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_DS4_LIB_DIR/ds4-lib.bash"

DS4_TREE_DIR="${DS4_TREE_DIR:-$DS4_REPO_ROOT/.ds4/tree}"

usage() {
    cat <<'EOF'
Usage: ds4-sync [--common-only | --model NAME] [--force]
       ds4-sync --help

Materialize .ds4/tree from the pinned upstream and apply the selected target.

Options:
  --common-only  stop after the common patch directory
  --model NAME   stop after the named model
  --force        replace .ds4/tree even if it has unexported or dirty work
  --help         print this help and exit
EOF
}

_DS4_SYNC_CLEANUP=""
_DS4_SYNC_OLD_TREE=""
_sync_cleanup() {
    # The old-tree backup lives inside the work directory that this trap
    # removes. Restore it first when a move already landed but reported
    # failure (or the script was interrupted), so recursive cleanup cannot
    # delete both the original and its backup.
    if [[ -n "$_DS4_SYNC_OLD_TREE" && -e "$_DS4_SYNC_OLD_TREE" && ! -e "$DS4_TREE_DIR" ]]; then
        mv "$_DS4_SYNC_OLD_TREE" "$DS4_TREE_DIR" 2>/dev/null || true
    fi
    if [[ -n "$_DS4_SYNC_CLEANUP" ]]; then
        rm -rf "$_DS4_SYNC_CLEANUP" 2>/dev/null || true
    fi
}
trap _sync_cleanup EXIT

# Print the name of the model immediately before NAME in DS4_MODEL_NAMES, or
# an empty string when NAME is the first model.
_prev_model_name() {
    local name="$1" prev="" m
    for m in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
        if [[ "$m" == "$name" ]]; then
            printf '%s\n' "$prev"
            return 0
        fi
        prev="$m"
    done
    ds4_die "model '$name' not found"
}

main() {
    local common_only=0 force=0 model="" positional=() prev="" head=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --common-only)
                common_only=1
                shift
                ;;
            --model)
                [[ $# -ge 2 ]] || ds4_die "--model requires a model name"
                model="$2"
                [[ -n "$model" ]] ||
                    ds4_die "--model requires a non-empty model name"
                [[ "$model" != "common" ]] ||
                    ds4_die "--model common is not a model; use --common-only"
                shift 2
                ;;
            --force)
                force=1
                shift
                ;;
            --help)
                usage
                exit 0
                ;;
            --)
                shift
                positional+=("$@")
                break
                ;;
            -*)
                ds4_die "unknown option: $1"
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [[ $common_only -eq 1 && -n "$model" ]]; then
        ds4_die "cannot combine --common-only and --model"
    fi
    if [[ ${#positional[@]} -gt 0 ]]; then
        ds4_die "unexpected argument: ${positional[0]}"
    fi

    if [[ -z "${UPSTREAM_URL:-}" && -z "${UPSTREAM_COMMIT:-}" ]]; then
        ds4_load_pin
    fi
    [[ -n "${UPSTREAM_URL:-}" && -n "${UPSTREAM_COMMIT:-}" ]] ||
        ds4_die "upstream pin not loaded"

    ds4_model_names

    if [[ $common_only -eq 1 ]]; then
        ds4_target_stop_model common
    elif [[ -n "$model" ]]; then
        ds4_target_stop_model "$model"
    else
        ds4_target_stop_model
    fi

    # Reject a missing or empty common directory before touching the tree.
    ds4_patch_files "$DS4_PATCHES_DIR/common"

    # Without --force, refuse to replace a tree that carries uncommitted or
    # unexported work so that scratch content is never silently destroyed.
    if [[ $force -eq 0 && -e "$DS4_TREE_DIR" ]]; then
        if [[ ! -d "$DS4_TREE_DIR/.git" ]]; then
            ds4_die "refusing to replace .ds4/tree: not a synced git tree (use --force)"
        fi
        if [[ -n "$(git -C "$DS4_TREE_DIR" status --porcelain 2>/dev/null)" ]]; then
            ds4_die "refusing to replace .ds4/tree: working tree is dirty (use --force)"
        fi
        if [[ ! -f "$DS4_TREE_DIR/.git/ds4-state" ]]; then
            ds4_die "refusing to replace .ds4/tree: missing state (use --force)"
        fi
        head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)" ||
            ds4_die "cannot resolve existing tree HEAD"
        ds4_state_read "$DS4_TREE_DIR"
        if [[ "$head" != "$DS4_STATE_SYNC_HEAD" && "$head" != "$DS4_STATE_EXPORTED_HEAD" ]]; then
            ds4_die "refusing to replace .ds4/tree: unexported commits (use --force)"
        fi
    fi

    local state_target="" state_model="" edit_branch="" prev_ref=""
    if [[ $common_only -eq 1 ]]; then
        state_target="common"
        state_model=""
        edit_branch="ds4/common"
        prev_ref=""
    elif [[ -n "$model" ]]; then
        state_target="$model"
        state_model="$model"
        edit_branch="ds4/model/$model"
        prev="$(_prev_model_name "$model")"
        if [[ -n "$prev" ]]; then
            prev_ref="refs/ds4/model/$prev"
        else
            prev_ref="refs/ds4/common"
        fi
    elif [[ ${#DS4_MODEL_NAMES[@]} -eq 0 ]]; then
        state_target="common"
        state_model=""
        edit_branch="ds4/common"
        prev_ref=""
    else
        state_model="${DS4_MODEL_NAMES[${#DS4_MODEL_NAMES[@]}-1]}"
        state_target="$state_model"
        edit_branch="ds4/model/$state_model"
        if [[ ${#DS4_MODEL_NAMES[@]} -gt 1 ]]; then
            prev_ref="refs/ds4/model/${DS4_MODEL_NAMES[${#DS4_MODEL_NAMES[@]}-2]}"
        else
            prev_ref="refs/ds4/common"
        fi
    fi

    # Build the new tree in a sibling scratch directory and swap it into place
    # only after it is complete, so a failed apply never clobbers the old tree.
    local parent workdir tmp_tree old_tree
    parent="$(dirname "$DS4_TREE_DIR")"
    mkdir -p "$parent" || ds4_die "cannot create tree parent: $parent"
    workdir="${DS4_TREE_DIR}.work.$$"
    rm -rf "$workdir" 2>/dev/null || true
    mkdir -p "$workdir" || ds4_die "cannot create work directory: $workdir"
    _DS4_SYNC_CLEANUP="$workdir"
    tmp_tree="$workdir/tree"
    old_tree="$workdir/old"
    _DS4_SYNC_OLD_TREE="$old_tree"

    ds4_clone_at_pin "$tmp_tree"
    git -C "$tmp_tree" remote add upstream "$UPSTREAM_URL" ||
        ds4_die "failed to add upstream remote"
    ds4_apply_target "$tmp_tree"
    git -C "$tmp_tree" checkout --quiet -b "$edit_branch" ||
        ds4_die "failed to create branch $edit_branch"

    local previous_tip sync_head
    if [[ -n "$prev_ref" ]]; then
        previous_tip="$(git -C "$tmp_tree" rev-parse "$prev_ref")" ||
            ds4_die "failed to resolve previous tip $prev_ref"
    else
        previous_tip="$UPSTREAM_COMMIT"
    fi
    sync_head="$(git -C "$tmp_tree" rev-parse HEAD)" ||
        ds4_die "failed to resolve HEAD"
    ds4_state_write "$tmp_tree" "$state_target" "$state_model" \
        "$previous_tip" "$sync_head"

    if [[ -e "$DS4_TREE_DIR" ]]; then
        mv "$DS4_TREE_DIR" "$old_tree" ||
            ds4_die "cannot move existing tree aside"
    fi
    if ! mv "$tmp_tree" "$DS4_TREE_DIR"; then
        mv "$old_tree" "$DS4_TREE_DIR" 2>/dev/null || true
        ds4_die "cannot move new tree into place"
    fi
    rm -rf "$old_tree" 2>/dev/null || true
}

main "$@"
