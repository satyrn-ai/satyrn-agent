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
    if [[ -n "$_DS4_EXPORT_WORK" ]]; then
        rm -rf "$_DS4_EXPORT_WORK" 2>/dev/null || true
    fi
}
trap _export_cleanup EXIT

_export_is_model() {
    local name="$1" m
    for m in "${DS4_MODEL_NAMES[@]}"; do
        [[ "$m" == "$name" ]] && return 0
    done
    return 1
}

_export_git_am() {
    local tree="$1"
    shift
    if ! git -C "$tree" am --quiet "$@"; then
        git -C "$tree" am --abort >/dev/null 2>&1 || true
        ds4_die "git am failed in $tree"
    fi
}

# Compare a reconstructed tree id in CHECK with the matching source tree id in
# SOURCE, and die with a clear message on mismatch.
_export_assert_tree_eq() {
    local check="$1" check_spec="$2" source="$3" source_spec="$4" what="$5"
    local got want
    got="$(git -C "$check" rev-parse "$check_spec")" ||
        ds4_die "cannot resolve reconstructed $what"
    want="$(git -C "$source" rev-parse "$source_spec")" ||
        ds4_die "cannot resolve source $what"
    [[ "$got" == "$want" ]] ||
        ds4_die "$what mismatch: reconstructed $got != source $want"
}

_ds4_export_write_state() {
    local tree="$1" target="$2" model="$3" prev="$4" sync="$5" exported="$6"
    local state_file="$tree/.git/ds4-state"
    local tmp="$state_file.tmp.$$"
    {
        printf 'TARGET=%s\n' "$target"
        printf 'MODEL=%s\n' "$model"
        printf 'PREVIOUS_TIP=%s\n' "$prev"
        printf 'SYNC_HEAD=%s\n' "$sync"
        printf 'EXPORTED_HEAD=%s\n' "$exported"
    } > "$tmp" || ds4_die "failed to write state file $state_file"
    mv -f "$tmp" "$state_file" || ds4_die "failed to move state file into place"
}

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
    elif [[ "$DS4_STATE_TARGET" == "all" ]]; then
        _export_is_model "$DS4_STATE_MODEL" ||
            ds4_die "state MODEL is not a known model"
        owned_name="$DS4_STATE_MODEL"
        range_base="$DS4_STATE_PREVIOUS_TIP"
    elif _export_is_model "$DS4_STATE_TARGET"; then
        [[ "$DS4_STATE_MODEL" == "$DS4_STATE_TARGET" ]] ||
            ds4_die "state MODEL does not match TARGET"
        owned_name="$DS4_STATE_MODEL"
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
        for m in "${DS4_MODEL_NAMES[@]}"; do
            [[ "$m" == "$owned_name" ]] && break
            prev_dirs+=("$m")
        done
    fi
    if [[ ${#prev_dirs[@]} -gt 0 ]]; then
        for prev_dir in "${prev_dirs[@]}"; do
            ds4_patch_files "$DS4_PATCHES_DIR/$prev_dir"
            _export_git_am "$check" "${DS4_PATCH_FILES[@]}"
            if [[ "$prev_dir" == "common" ]]; then
                ref="refs/ds4/common"
            else
                ref="refs/ds4/model/$prev_dir"
            fi
            _export_assert_tree_eq "$check" 'HEAD^{tree}' \
                "$DS4_TREE_DIR" "$ref^{tree}" "$prev_dir boundary tree"
        done
    fi

    ds4_patch_files "$candidate"
    _export_git_am "$check" "${DS4_PATCH_FILES[@]}"
    _export_assert_tree_eq "$check" 'HEAD^{tree}' \
        "$DS4_TREE_DIR" 'HEAD^{tree}' "final HEAD tree"

    # Replace only the owned directory, keeping a backup for rollback.
    _DS4_EXPORT_OWNED="$owned_dir"
    local backup="$work/backup"
    if [[ -e "$owned_dir" ]]; then
        mv "$owned_dir" "$backup" ||
            ds4_die "cannot move existing patch directory aside"
    fi
    mv "$candidate" "$owned_dir" ||
        ds4_die "cannot move candidate into place"
    _DS4_EXPORT_REPLACED=1

    # Record the successful export so a later sync knows HEAD is exported.
    _ds4_export_write_state "$DS4_TREE_DIR" "$DS4_STATE_TARGET" \
        "$DS4_STATE_MODEL" "$DS4_STATE_PREVIOUS_TIP" \
        "$DS4_STATE_SYNC_HEAD" "$head"
    _DS4_EXPORT_DONE=1
}

main "$@"
