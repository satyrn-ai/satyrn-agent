#!/usr/bin/env bash
#
# tools/ds4-export.bash
#
# Transactionally regenerate the owned patch directory from the editable
# scratch range recorded in .ds4/tree.
#
# Usage:
#   ds4-export [--force]
#   ds4-export --help
#
# Environment overrides (used by tests and the other ds4 tools):
#   DS4_PATCHES_DIR  patch series root (default <repo>/patches)
#   DS4_CACHE_DIR    upstream mirror (default <repo>/.ds4/cache)
#   DS4_TREE_DIR     materialized tree (default <repo>/.ds4/tree)
#   DS4_EXPORT_DIR   candidate scratch root (default <repo>/.ds4/export)
#   UPSTREAM_URL, UPSTREAM_COMMIT  skip reading upstream.pin when both are set

set -euo pipefail

_DS4_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_DS4_LIB_DIR/ds4-lib.bash"

DS4_TREE_DIR="${DS4_TREE_DIR:-$DS4_REPO_ROOT/.ds4/tree}"
DS4_EXPORT_DIR="${DS4_EXPORT_DIR:-$DS4_REPO_ROOT/.ds4/export}"

usage() {
    cat <<'EOF'
Usage: ds4-export [--force]
       ds4-export --help

Transactionally regenerate the owned patch directory for the editable range
recorded in .ds4/tree.

Options:
  --force  replace a dirty patches/ directory
  --help   print this help and exit
EOF
}

_DS4_EXPORT_WORK=""
_DS4_EXPORT_OWNED=""
_DS4_EXPORT_REPLACED=0
_DS4_EXPORT_DONE=0
_DS4_EXPORT_SELECTED_REF=""
_DS4_EXPORT_SELECTED_REF_PREV=""
_DS4_EXPORT_SELECTED_REF_CHANGED=0
_DS4_EXPORT_STATE_BACKUP=""
_DS4_EXPORT_STATE_CHANGED=0
_export_cleanup() {
    # If the export did not complete, restore the original owned directory.
    if [[ $_DS4_EXPORT_DONE -eq 0 && -n "$_DS4_EXPORT_OWNED" ]]; then
        local backup="${_DS4_EXPORT_WORK:+$_DS4_EXPORT_WORK/backup}"
        if [[ -n "$backup" && -e "$backup" ]]; then
            if [[ $_DS4_EXPORT_REPLACED -eq 1 ]]; then
                rm -rf "$_DS4_EXPORT_OWNED" 2>/dev/null || true
                mv "$backup" "$_DS4_EXPORT_OWNED" 2>/dev/null || true
            elif [[ ! -e "$_DS4_EXPORT_OWNED" ]]; then
                mv "$backup" "$_DS4_EXPORT_OWNED" 2>/dev/null || true
            fi
        elif [[ $_DS4_EXPORT_REPLACED -eq 1 ]]; then
            # No original directory existed; roll back to "no directory".
            rm -rf "$_DS4_EXPORT_OWNED" 2>/dev/null || true
        fi
    fi
    # Roll back the selected boundary ref and ds4-state as well, so the
    # committed patches, boundary ref, and state never diverge when a later
    # step (or an interruption) fails after the directory replacement began.
    if [[ $_DS4_EXPORT_DONE -eq 0 && $_DS4_EXPORT_SELECTED_REF_CHANGED -eq 1 && -n "$_DS4_EXPORT_SELECTED_REF" ]]; then
        if [[ -n "$_DS4_EXPORT_SELECTED_REF_PREV" ]]; then
            git -C "$DS4_TREE_DIR" update-ref "$_DS4_EXPORT_SELECTED_REF" \
                "$_DS4_EXPORT_SELECTED_REF_PREV" 2>/dev/null || true
        else
            git -C "$DS4_TREE_DIR" update-ref -d "$_DS4_EXPORT_SELECTED_REF" \
                2>/dev/null || true
        fi
    fi
    if [[ $_DS4_EXPORT_DONE -eq 0 && $_DS4_EXPORT_STATE_CHANGED -eq 1 && -n "$_DS4_EXPORT_STATE_BACKUP" ]]; then
        mv -f "$_DS4_EXPORT_STATE_BACKUP" "$DS4_TREE_DIR/.git/ds4-state" \
            2>/dev/null || true
    fi
    if [[ -n "$_DS4_EXPORT_WORK" ]]; then
        rm -rf "$_DS4_EXPORT_WORK" 2>/dev/null || true
    fi
}
trap _export_cleanup EXIT

# Print success when the patches tree is dirty: either it has uncommitted
# changes in its containing repository, or (when no repository exists) the
# owned directory contains entries other than *.patch files.
_export_patches_dirty() {
    local out=""
    if out="$(git -C "$DS4_PATCHES_DIR" status --porcelain -- . 2>/dev/null)"; then
        if [[ -n "$out" ]]; then
            return 0
        fi
        return 1
    fi

    local dir="$1" entry
    for entry in "$dir"/*; do
        [[ -e "$entry" ]] || continue
        case "$entry" in
            *.patch) continue ;;
            *) return 0 ;;
        esac
    done
    return 1
}

main() {
    local force=0 positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
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
    if [[ ${#positional[@]} -gt 0 ]]; then
        ds4_die "unexpected argument: ${positional[0]}"
    fi

    if [[ -z "${UPSTREAM_URL:-}" && -z "${UPSTREAM_COMMIT:-}" ]]; then
        ds4_load_pin
    fi
    [[ -n "${UPSTREAM_URL:-}" && -n "${UPSTREAM_COMMIT:-}" ]] ||
        ds4_die "upstream pin not loaded"

    [[ -d "$DS4_TREE_DIR/.git" ]] ||
        ds4_die "not a synced git tree: $DS4_TREE_DIR"
    ds4_state_read "$DS4_TREE_DIR"
    ds4_model_names

    # Map the recorded target to the owned patch directory and export range.
    local owned_name range_base
    if [[ "$DS4_STATE_TARGET" == "common" ]]; then
        owned_name="common"
        range_base="$UPSTREAM_COMMIT"
    elif ds4_is_model "$DS4_STATE_TARGET"; then
        owned_name="$DS4_STATE_TARGET"
        range_base="$DS4_STATE_PREVIOUS_TIP"
    else
        ds4_die "unrecognized state TARGET '$DS4_STATE_TARGET'"
    fi
    [[ -n "$range_base" ]] || ds4_die "missing export range base"

    # Require a clean scratch tree before generating anything.
    if [[ -n "$(git -C "$DS4_TREE_DIR" status --porcelain 2>/dev/null)" ]]; then
        ds4_die "refusing to export: .ds4/tree working tree is dirty"
    fi

    # Require nonempty linear ancestry with no merges.
    local base head
    base="$(git -C "$DS4_TREE_DIR" rev-parse "$range_base")" ||
        ds4_die "cannot resolve export base $range_base"
    head="$(git -C "$DS4_TREE_DIR" rev-parse HEAD)" ||
        ds4_die "cannot resolve .ds4/tree HEAD"
    if ! git -C "$DS4_TREE_DIR" merge-base --is-ancestor "$base" "$head"; then
        ds4_die "export base $base is not an ancestor of HEAD"
    fi
    if [[ "$base" == "$head" ]]; then
        ds4_die "export range is empty"
    fi
    if [[ -n "$(git -C "$DS4_TREE_DIR" rev-list --merges "$base..$head")" ]]; then
        ds4_die "export range contains merge commits"
    fi

    local owned_dir="$DS4_PATCHES_DIR/$owned_name"
    if [[ $force -eq 0 ]] && _export_patches_dirty "$owned_dir"; then
        ds4_die "refusing to overwrite dirty patches/ directory (use --force)"
    fi

    # Generate the candidate and reconstruct the target in a sibling scratch
    # area so the committed patches are never touched before every check
    # passes.
    mkdir -p "$DS4_EXPORT_DIR" || ds4_die "cannot create export scratch root"
    local work candidate check
    work="$(mktemp -d "$DS4_EXPORT_DIR/export.XXXXXX")" ||
        ds4_die "cannot create export scratch directory"
    _DS4_EXPORT_WORK="$work"
    candidate="$work/candidate"
    check="$work/check"
    mkdir -p "$candidate" || ds4_die "cannot create candidate directory"

    git -C "$DS4_TREE_DIR" format-patch --quiet --start-number 1 --no-signature \
        "$base..$head" --output-directory "$candidate" ||
        ds4_die "failed to generate export candidate"

    ds4_clone_at_pin "$check"

    # Apply the committed preceding directories and compare every boundary.
    local prev_dirs=() prev_dir ref
    if [[ "$owned_name" != "common" ]]; then
        prev_dirs+=("common")
        local m
        for m in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
            [[ "$m" == "$owned_name" ]] && break
            prev_dirs+=("$m")
        done
    fi
    if [[ ${#prev_dirs[@]} -gt 0 ]]; then
        for prev_dir in "${prev_dirs[@]}"; do
            ds4_patch_files "$DS4_PATCHES_DIR/$prev_dir"
            ds4_git_am "$check" "${DS4_PATCH_FILES[@]}"
            if [[ "$prev_dir" == "common" ]]; then
                ref="refs/ds4/common"
            else
                ref="refs/ds4/model/$prev_dir"
            fi
            ds4_assert_tree_eq "$check" 'HEAD^{tree}' \
                "$DS4_TREE_DIR" "$ref^{tree}" "$prev_dir boundary tree"
        done
    fi

    ds4_patch_files "$candidate"
    ds4_git_am "$check" "${DS4_PATCH_FILES[@]}"
    ds4_assert_tree_eq "$check" 'HEAD^{tree}' \
        "$DS4_TREE_DIR" 'HEAD^{tree}' "final HEAD tree"

    # Replace only the owned directory, keeping a backup for rollback. The
    # replaced state is recorded *before* the candidate move so that a failure
    # or signal after the original is backed up always restores the original
    # bytes (including when the move already landed but the shell exits before
    # the next statement).
    _DS4_EXPORT_OWNED="$owned_dir"

    # Capture the pre-transaction boundary ref and state bytes before any
    # mutation so cleanup can restore them if a later step fails. The
    # selected boundary is the ref ds4-check verifies for this target, so it
    # must advance to the same HEAD the exported patches reconstruct.
    local selected_ref state_file state_backup
    if [[ "$owned_name" == "common" ]]; then
        selected_ref="refs/ds4/common"
    else
        selected_ref="refs/ds4/model/$owned_name"
    fi
    _DS4_EXPORT_SELECTED_REF="$selected_ref"
    if git -C "$DS4_TREE_DIR" rev-parse --verify --quiet "$selected_ref" \
        >/dev/null 2>&1; then
        _DS4_EXPORT_SELECTED_REF_PREV="$(git -C "$DS4_TREE_DIR" rev-parse "$selected_ref")" ||
            ds4_die "cannot resolve selected boundary ref $selected_ref"
    else
        _DS4_EXPORT_SELECTED_REF_PREV=""
    fi
    state_file="$DS4_TREE_DIR/.git/ds4-state"
    state_backup="$work/state-backup"
    if [[ -f "$state_file" ]]; then
        cp "$state_file" "$state_backup" ||
            ds4_die "cannot back up state file"
        _DS4_EXPORT_STATE_BACKUP="$state_backup"
    fi

    local backup="$work/backup"
    if [[ -e "$owned_dir" ]]; then
        mv "$owned_dir" "$backup" ||
            ds4_die "cannot move existing patch directory aside"
    fi
    _DS4_EXPORT_REPLACED=1
    mv "$candidate" "$owned_dir" ||
        ds4_die "cannot move candidate into place"

    # Advance the boundary ref inside the same transaction as the directory
    # replacement so ds4-check verifies the freshly exported patches against
    # the new boundary rather than the stale pre-export tip. Record the
    # rollback intent *before* the ref write so a signal that lands after the
    # write still rolls the ref back.
    _DS4_EXPORT_SELECTED_REF_CHANGED=1
    git -C "$DS4_TREE_DIR" update-ref "$selected_ref" "$head" ||
        ds4_die "cannot advance selected boundary ref $selected_ref"

    # Record the successful export so a later sync knows HEAD is exported.
    _DS4_EXPORT_STATE_CHANGED=1
    ds4_state_write "$DS4_TREE_DIR" "$DS4_STATE_TARGET" \
        "$DS4_STATE_MODEL" "$DS4_STATE_PREVIOUS_TIP" \
        "$DS4_STATE_SYNC_HEAD" "$head"
    _DS4_EXPORT_DONE=1
}

main "$@"
