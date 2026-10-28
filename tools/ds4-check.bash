#!/usr/bin/env bash
#
# tools/ds4-check.bash
#
# Verify that the committed patch directories reconstruct each selected target
# from a pristine clone of the pinned upstream, and optionally build each
# checked tree with ds4-py.
#
# Usage:
#   ds4-check [--common-only | --model NAME] [--build]
#   ds4-check --help
#
# Environment overrides (used by tests and the other ds4 tools):
#   DS4_PATCHES_DIR  patch series root (default <repo>/patches)
#   DS4_CACHE_DIR    upstream mirror (default <repo>/.ds4/cache)
#   DS4_TREE_DIR     materialized tree (default <repo>/.ds4/tree)
#   DS4_CHECK_DIR    pristine check clones (default <repo>/.ds4/check)
#   UPSTREAM_URL, UPSTREAM_COMMIT  skip reading upstream.pin when both are set

set -euo pipefail

_DS4_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_DS4_LIB_DIR/ds4-lib.bash"

DS4_TREE_DIR="${DS4_TREE_DIR:-$DS4_REPO_ROOT/.ds4/tree}"
DS4_CHECK_DIR="${DS4_CHECK_DIR:-$DS4_REPO_ROOT/.ds4/check}"

usage() {
    cat <<'EOF'
Usage: ds4-check [--common-only | --model NAME] [--build]
       ds4-check --help

Verify each selected patch target from a pristine clone of the pinned
upstream, ending with the full multi-model tree when no selector is given.

Options:
  --common-only  check only the common patch directory
  --model NAME   check only the named model prefix
  --build        build each checked tree with ds4py build --src
  --help         print this help and exit
EOF
}

_check_is_model() {
    local name="$1" m
    for m in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
        [[ "$m" == "$name" ]] && return 0
    done
    return 1
}

# Compare a reconstructed tree id in CHECK with the matching source tree id in
# SOURCE, and die with a clear message on mismatch.
_check_assert_tree_eq() {
    local check="$1" check_spec="$2" source="$3" source_spec="$4" what="$5"
    local got want
    got="$(git -C "$check" rev-parse "$check_spec")" ||
        ds4_die "cannot resolve reconstructed $what"
    want="$(git -C "$source" rev-parse "$source_spec")" ||
        ds4_die "cannot resolve scratch $what"
    [[ "$got" == "$want" ]] ||
        ds4_die "$what mismatch: reconstructed $got != scratch $want"
}

main() {
    local common_only=0 model="" build=0 positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --common-only)
                common_only=1
                shift
                ;;
            --model)
                [[ $# -ge 2 ]] || ds4_die "--model requires a model name"
                model="$2"
                shift 2
                ;;
            --build)
                build=1
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

    if [[ -n "$model" ]]; then
        _check_is_model "$model" || ds4_die "unknown model '$model'"
    fi

    # Fail before any clone or scratch directory is created if the common
    # patch directory is missing or empty.
    ds4_patch_files "$DS4_PATCHES_DIR/common"

    mkdir -p "$DS4_CHECK_DIR" ||
        ds4_die "cannot create check scratch dir: $DS4_CHECK_DIR"
    DS4_CHECK_DIR="$(cd "$DS4_CHECK_DIR" && pwd)" ||
        ds4_die "cannot resolve check scratch dir: $DS4_CHECK_DIR"

    local targets=() target
    if [[ $common_only -eq 1 ]]; then
        targets=("common")
    elif [[ -n "$model" ]]; then
        targets=("$model")
    else
        targets=("common")
        for target in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
            targets+=("$target")
        done
    fi

    # Determine which checked target .ds4/tree represents, if any.
    local scratch_check_target=""
    if [[ -d "$DS4_TREE_DIR/.git" && -f "$DS4_TREE_DIR/.git/ds4-state" ]]; then
        ds4_state_read "$DS4_TREE_DIR"
        case "$DS4_STATE_TARGET" in
            common)
                scratch_check_target="common"
                ;;
            all)
                if [[ ${#DS4_MODEL_NAMES[@]} -gt 0 ]]; then
                    scratch_check_target="${DS4_MODEL_NAMES[${#DS4_MODEL_NAMES[@]}-1]}"
                fi
                ;;
            *)
                if _check_is_model "$DS4_STATE_TARGET"; then
                    scratch_check_target="$DS4_STATE_TARGET"
                fi
                ;;
        esac
    fi

    local backend
    case "$(uname -s)" in
        Darwin) backend="metal" ;;
        *) backend="cpu" ;;
    esac

    local stop clone m
    for target in "${targets[@]}"; do
        if [[ "$target" == "common" ]]; then
            stop="common"
        else
            stop="$target"
        fi

        clone="$DS4_CHECK_DIR/$target"
        printf 'check %s\n' "$target"
        printf 'clone %s\n' "$clone"

        # Recreate the clone fresh each run so every target is applied to a
        # pristine tree at the pinned commit.
        rm -rf "$clone" 2>/dev/null || true
        ds4_clone_at_pin "$clone"
        ds4_apply_target "$clone" "$stop"

        # When .ds4/tree represents this same target, the committed patches
        # must reproduce every preceding boundary ref and the editable HEAD.
        if [[ -n "$scratch_check_target" && "$target" == "$scratch_check_target" ]]; then
            if [[ "$target" == "common" ]]; then
                _check_assert_tree_eq "$clone" 'refs/ds4/common^{tree}' \
                    "$DS4_TREE_DIR" 'refs/ds4/common^{tree}' "common boundary tree"
            else
                _check_assert_tree_eq "$clone" 'refs/ds4/common^{tree}' \
                    "$DS4_TREE_DIR" 'refs/ds4/common^{tree}' "common boundary tree"
                for m in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
                    [[ "$m" == "$target" ]] && break
                    _check_assert_tree_eq "$clone" "refs/ds4/model/$m^{tree}" \
                        "$DS4_TREE_DIR" "refs/ds4/model/$m^{tree}" \
                        "$m boundary tree"
                done
                _check_assert_tree_eq "$clone" "refs/ds4/model/$target^{tree}" \
                    "$DS4_TREE_DIR" "refs/ds4/model/$target^{tree}" \
                    "$target boundary tree"
            fi
            _check_assert_tree_eq "$clone" 'HEAD^{tree}' \
                "$DS4_TREE_DIR" 'HEAD^{tree}' "final tree"
        fi

        if [[ $build -eq 1 ]]; then
            printf 'build %s\n' "$target"
            ds4py build --src "$clone" --backend "$backend" ||
                ds4_die "ds4py build failed for $target"
        fi
    done
}

main "$@"
