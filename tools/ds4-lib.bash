# tools/ds4-lib.bash
#
# Shared primitives for the ds4 patch-series tools (ds4-sync, ds4-export,
# ds4-check). Bash 3.2-compatible: no associative arrays, mapfile/readarray,
# globstar, or GNU/BSD-only flags. Source this file; do not execute it.
#
# Public functions and the variables they produce:
#   ds4_die MESSAGE
#       Print MESSAGE to stderr and exit 1.
#   ds4_repo_root
#       Print the absolute path of the repository root (the directory that
#       contains upstream.pin).
#   ds4_load_pin [PIN_FILE]
#       Parse PIN_FILE (default: <repo>/upstream.pin) line-by-line without
#       sourcing it, and set UPSTREAM_URL and UPSTREAM_COMMIT.
#   ds4_model_names
#       Populate the DS4_MODEL_NAMES array with immediate model directory
#       names under DS4_PATCHES_DIR (excluding "common"), in LC_ALL=C order.
#       Names must match [A-Za-z0-9][A-Za-z0-9_-]*.
#   ds4_target_stop_model [STOP]
#       Validate and record STOP in DS4_STOP_MODEL: "" (apply every model),
#       "common" (common only), or a known model name. Requires
#       DS4_MODEL_NAMES to be populated.
#   ds4_is_model NAME
#       Return success when NAME is one of the names in DS4_MODEL_NAMES.
#   ds4_patch_files DIR
#       Populate DS4_PATCH_FILES with DIR/*.patch paths in LC_ALL=C filename
#       order. Dies if DIR is missing or contains no *.patch files.
#   ds4_ensure_cache
#       Ensure DS4_CACHE_DIR is a --mirror clone of UPSTREAM_URL containing
#       UPSTREAM_COMMIT. Refreshing the mirror is best-effort when the pin is
#       already cached locally (so a cached pin works offline); a missing pin
#       or first clone that cannot reach the remote is fatal.
#   ds4_clone_at_pin DEST
#       Clone DS4_CACHE_DIR into DEST and detach HEAD at UPSTREAM_COMMIT.
#   ds4_apply_target TREE [STOP_MODEL]
#       Apply DS4_PATCHES_DIR/common then model directories in DS4_MODEL_NAMES
#       order with git am. STOP_MODEL is "" (apply every model), "common"
#       (common only), or a known model name to stop after. When STOP_MODEL is
#       omitted, DS4_STOP_MODEL (set by ds4_target_stop_model) is used. After
#       each applied range, records refs/ds4/common and refs/ds4/model/<name>
#       in TREE.
#   ds4_git_am TREE PATCH...
#       Apply PATCH... with `git am` in TREE, aborting and dying on failure.
#   ds4_assert_tree_eq CHECK CHECK_SPEC SOURCE SOURCE_SPEC WHAT
#       Die unless CHECK:CHECK_SPEC and SOURCE:SOURCE_SPEC resolve to the
#       same tree id.
#   ds4_state_write TREE TARGET MODEL PREVIOUS_TIP SYNC_HEAD [EXPORTED_HEAD]
#       Write TREE/.git/ds4-state with TARGET, MODEL, PREVIOUS_TIP, SYNC_HEAD,
#       and EXPORTED_HEAD (defaults to SYNC_HEAD when omitted).
#   ds4_state_read TREE
#       Read TREE/.git/ds4-state into DS4_STATE_TARGET, DS4_STATE_MODEL,
#       DS4_STATE_PREVIOUS_TIP, DS4_STATE_SYNC_HEAD, and
#       DS4_STATE_EXPORTED_HEAD.
#
# Overridable globals (defaults derived from the repository root):
#   DS4_PATCHES_DIR  -> <repo>/patches
#   DS4_CACHE_DIR    -> <repo>/.ds4/cache
#   UPSTREAM_URL, UPSTREAM_COMMIT (set by ds4_load_pin)

if ! _DS4_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; then
    printf 'ds4: cannot resolve library directory\n' >&2
    exit 1
fi
DS4_REPO_ROOT="$(cd "$_DS4_LIB_DIR/.." && pwd)"
if [[ -z "$DS4_REPO_ROOT" ]]; then
    printf 'ds4: cannot resolve repository root\n' >&2
    exit 1
fi

DS4_PATCHES_DIR="${DS4_PATCHES_DIR:-$DS4_REPO_ROOT/patches}"
DS4_CACHE_DIR="${DS4_CACHE_DIR:-$DS4_REPO_ROOT/.ds4/cache}"

ds4_die() {
    printf 'ds4: %s\n' "$*" >&2
    exit 1
}

ds4_repo_root() {
    printf '%s\n' "$DS4_REPO_ROOT"
}

# Parse upstream.pin without sourcing it so its values can never execute.
ds4_load_pin() {
    local pin_file="${1:-$DS4_REPO_ROOT/upstream.pin}"
    UPSTREAM_URL=""
    UPSTREAM_COMMIT=""
    [[ -f "$pin_file" ]] || ds4_die "missing upstream pin: $pin_file"

    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -z "$line" ]] && continue
        case "$line" in
            '#'*) continue ;;
        esac
        case "$line" in
            UPSTREAM_URL=*) UPSTREAM_URL="${line#UPSTREAM_URL=}" ;;
            UPSTREAM_COMMIT=*) UPSTREAM_COMMIT="${line#UPSTREAM_COMMIT=}" ;;
            *) ds4_die "unrecognized line in $pin_file: $line" ;;
        esac
    done < "$pin_file"

    [[ -n "$UPSTREAM_URL" && -n "$UPSTREAM_COMMIT" ]] ||
        ds4_die "$pin_file must define UPSTREAM_URL and UPSTREAM_COMMIT"
}

ds4_is_model() {
    local name="$1" m
    for m in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
        [[ "$m" == "$name" ]] && return 0
    done
    return 1
}

ds4_model_names() {
    DS4_MODEL_NAMES=()
    local dir="$DS4_PATCHES_DIR"
    [[ -d "$dir" ]] || ds4_die "patches directory not found: $dir"

    local entry name
    for entry in "$dir"/*/; do
        [[ -d "$entry" ]] || continue
        name="${entry%/}"
        name="${name##*/}"
        [[ "$name" == "common" ]] && continue
        if [[ ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
            ds4_die "invalid model directory name '$name'"
        fi
        DS4_MODEL_NAMES+=("$name")
    done

    local sorted
    if [[ ${#DS4_MODEL_NAMES[@]} -gt 0 ]]; then
        sorted="$(printf '%s\n' "${DS4_MODEL_NAMES[@]}" | LC_ALL=C sort)"
        DS4_MODEL_NAMES=()
        while IFS= read -r name || [[ -n "$name" ]]; do
            DS4_MODEL_NAMES+=("$name")
        done <<< "$sorted"
    fi
}

ds4_target_stop_model() {
    local stop="${1:-}"
    if [[ -n "$stop" && "$stop" != "common" ]]; then
        ds4_is_model "$stop" || ds4_die "unknown model '$stop'"
    fi
    DS4_STOP_MODEL="$stop"
}

ds4_patch_files() {
    local dir="$1"
    DS4_PATCH_FILES=()
    [[ -d "$dir" ]] || ds4_die "patch directory not found: $dir"

    local f count=0
    for f in "$dir"/*.patch; do
        if [[ -f "$f" ]]; then
            DS4_PATCH_FILES+=("$f")
            count=$((count + 1))
        fi
    done
    [[ $count -gt 0 ]] || ds4_die "empty patch directory: $dir"

    local sorted
    if [[ $count -gt 1 ]]; then
        sorted="$(printf '%s\n' "${DS4_PATCH_FILES[@]}" | LC_ALL=C sort)"
        DS4_PATCH_FILES=()
        while IFS= read -r f || [[ -n "$f" ]]; do
            DS4_PATCH_FILES+=("$f")
        done <<< "$sorted"
    fi
}

ds4_ensure_cache() {
    local cache="$DS4_CACHE_DIR"
    [[ -n "$UPSTREAM_URL" && -n "$UPSTREAM_COMMIT" ]] ||
        ds4_die "upstream pin not loaded"

    local have_pin=0
    if [[ -d "$cache" ]] &&
        git -C "$cache" cat-file -e "${UPSTREAM_COMMIT}^{commit}" 2>/dev/null; then
        have_pin=1
    fi

    if [[ ! -d "$cache/.git" && ! -f "$cache/HEAD" ]]; then
        mkdir -p "$(dirname "$cache")" || ds4_die "cannot create cache parent"
        if ! git clone --mirror --quiet "$UPSTREAM_URL" "$cache"; then
            rm -rf "$cache" 2>/dev/null || true
            ds4_die "failed to clone upstream $UPSTREAM_URL"
        fi
    else
        # Refresh is best-effort only when the pin is already cached.
        if ! git -C "$cache" fetch --quiet origin '+refs/*:refs/*' 2>/dev/null; then
            [[ $have_pin -eq 1 ]] ||
                ds4_die "cannot fetch upstream $UPSTREAM_URL and pin is not cached"
        fi
    fi

    git -C "$cache" cat-file -e "${UPSTREAM_COMMIT}^{commit}" 2>/dev/null ||
        ds4_die "upstream commit $UPSTREAM_COMMIT not available"
}

ds4_clone_at_pin() {
    local dest="$1"
    [[ -n "$dest" ]] || ds4_die "ds4_clone_at_pin: missing DEST"
    [[ -e "$dest" ]] && ds4_die "destination already exists: $dest"

    ds4_ensure_cache
    git clone --quiet "$DS4_CACHE_DIR" "$dest" ||
        ds4_die "failed to clone cache into $dest"
    git -C "$dest" checkout --quiet --detach "$UPSTREAM_COMMIT" ||
        ds4_die "upstream commit $UPSTREAM_COMMIT not found in cache"
}

ds4_git_am() {
    local tree="$1"
    shift
    if ! git -C "$tree" am --quiet "$@"; then
        git -C "$tree" am --abort >/dev/null 2>&1 || true
        ds4_die "git am failed in $tree"
    fi
}

# Compare a reconstructed tree id in CHECK with the matching source tree id in
# SOURCE, and die with a clear message on mismatch.
ds4_assert_tree_eq() {
    local check="$1" check_spec="$2" source="$3" source_spec="$4" what="$5"
    local got want
    got="$(git -C "$check" rev-parse "$check_spec")" ||
        ds4_die "cannot resolve reconstructed $what"
    want="$(git -C "$source" rev-parse "$source_spec")" ||
        ds4_die "cannot resolve source $what"
    [[ "$got" == "$want" ]] ||
        ds4_die "$what mismatch: reconstructed $got != source $want"
}

ds4_apply_target() {
    local tree="$1" stop="${2:-${DS4_STOP_MODEL:-}}"
    [[ -d "$tree/.git" ]] || ds4_die "not a git tree: $tree"

    ds4_model_names

    if [[ -n "$stop" && "$stop" != "common" ]]; then
        ds4_is_model "$stop" || ds4_die "unknown model '$stop'"
    fi

    if ! git -C "$tree" diff --quiet; then
        ds4_die "target tree has unstaged changes: $tree"
    fi
    if ! git -C "$tree" diff --cached --quiet; then
        ds4_die "target tree has staged changes: $tree"
    fi

    ds4_patch_files "$DS4_PATCHES_DIR/common"
    ds4_git_am "$tree" "${DS4_PATCH_FILES[@]}"
    git -C "$tree" update-ref "refs/ds4/common" HEAD ||
        ds4_die "failed to update refs/ds4/common"

    [[ "$stop" == "common" ]] && return 0

    local model
    for model in "${DS4_MODEL_NAMES[@]+"${DS4_MODEL_NAMES[@]}"}"; do
        ds4_patch_files "$DS4_PATCHES_DIR/$model"
        ds4_git_am "$tree" "${DS4_PATCH_FILES[@]}"
        git -C "$tree" update-ref "refs/ds4/model/$model" HEAD ||
            ds4_die "failed to update refs/ds4/model/$model"
        [[ -n "$stop" && "$stop" == "$model" ]] && return 0
    done
    return 0
}

ds4_state_write() {
    local tree="$1" target="$2" model="$3" previous_tip="$4" sync_head="$5"
    local exported_head="${6:-$sync_head}"
    [[ -d "$tree/.git" ]] || ds4_die "not a git tree: $tree"

    local state_file="$tree/.git/ds4-state"
    local tmp="$state_file.tmp.$$"
    {
        printf 'TARGET=%s\n' "$target"
        printf 'MODEL=%s\n' "$model"
        printf 'PREVIOUS_TIP=%s\n' "$previous_tip"
        printf 'SYNC_HEAD=%s\n' "$sync_head"
        printf 'EXPORTED_HEAD=%s\n' "$exported_head"
    } > "$tmp" || ds4_die "failed to write state file $state_file"
    mv -f "$tmp" "$state_file" || ds4_die "failed to move state file into place"
}

ds4_state_read() {
    local tree="$1"
    local state_file="$tree/.git/ds4-state"
    [[ -f "$state_file" ]] || ds4_die "missing state file: $state_file"

    DS4_STATE_TARGET=""
    DS4_STATE_MODEL=""
    DS4_STATE_PREVIOUS_TIP=""
    DS4_STATE_SYNC_HEAD=""
    DS4_STATE_EXPORTED_HEAD=""

    local key value line
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
            TARGET) DS4_STATE_TARGET="$value" ;;
            MODEL) DS4_STATE_MODEL="$value" ;;
            PREVIOUS_TIP) DS4_STATE_PREVIOUS_TIP="$value" ;;
            SYNC_HEAD) DS4_STATE_SYNC_HEAD="$value" ;;
            EXPORTED_HEAD) DS4_STATE_EXPORTED_HEAD="$value" ;;
            *) ds4_die "unrecognized state key in $state_file: $key" ;;
        esac
    done < "$state_file"
}
