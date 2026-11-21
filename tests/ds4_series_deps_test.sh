#!/usr/bin/env bash
#
# tests/ds4_series_deps_test.sh
#
# Regression for the Mellum include dependencies in the exported series.
#
# ds4.c includes the ds4_mellum_*.inc files, and every object that compiles
# ds4.c or includes it from a test must list those includes as prerequisites.
# Without them an incremental build reports "up to date" after an include
# changes, and a pristine build cannot see the problem. The test therefore
# reads the exported series itself: it materializes the combined prefix with
# ds4-check and inspects the Makefile at every patch boundary, Mellum's six
# and qwen35's eighteen, because the two qwen35 test objects include ds4.c
# and need the same dependencies.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/ds4_test_helpers.sh
source "$TEST_DIR/ds4_test_helpers.sh"

# Cap the per-test diagnostics so one broken series stays readable.
_MD_MAX_REPORT=6

# Print the materialized combined prefix, materializing it once per module run.
_md_tree() {
    local marker="$TMP_ROOT/make-deps-tree" out
    if [[ -f "$marker" ]]; then
        cat "$marker"
        return 0
    fi
    out="$TMP_ROOT/make-deps-check.out"
    if ! DS4_CHECK_DIR="$TMP_ROOT/make-deps-check" \
        bash "$REPO_ROOT/tools/ds4-check.sh" --model qwen35 >"$out" 2>&1; then
        printf '  FAIL: ds4-check could not materialize the combined prefix\n' >&2
        sed -n '1,20p' "$out" | sed 's/^/    /' >&2
        return 1
    fi
    printf '%s\n' "$TMP_ROOT/make-deps-check/qwen35" > "$marker"
    cat "$marker"
}

# Print every patch boundary from the common tip to the combined tip, oldest
# first: the applied Mellum and qwen35 commits ds4-check records as refs.
_md_boundaries() {
    local tree="$1"
    if ! git -C "$tree" rev-parse --verify --quiet refs/ds4/model/qwen35 >/dev/null; then
        printf '  FAIL: the materialized tree has no qwen35 boundary ref\n' >&2
        return 1
    fi
    git -C "$tree" rev-list --reverse refs/ds4/common..refs/ds4/model/qwen35
}

# Print a short, stable label for a boundary: sha and subject.
_md_label() {
    local tree="$1" sha="$2"
    printf '%s %s' "${sha:0:7}" "$(git -C "$tree" log -1 --format=%s "$sha" | cut -c1-40)"
}

# Print the ds4_mellum_*.inc files that ds4.c includes at TREE, following
# includes of the .inc files themselves (the tokenizer includes the unicode
# table).
_md_includes() {
    local tree="$1" pending="ds4.c" seen=" " name found inc
    while [[ -n "$pending" ]]; do
        name="${pending%% *}"
        if [[ "$pending" == *" "* ]]; then
            pending="${pending#* }"
        else
            pending=""
        fi
        [[ -f "$tree/$name" ]] || continue
        found=$(grep -o 'ds4_mellum_[A-Za-z0-9_]*\.inc' "$tree/$name" || true)
        for inc in $found; do
            case "$seen" in
                *" $inc "*) ;;
                *)
                    seen="$seen$inc "
                    if [[ -n "$pending" ]]; then
                        pending="$pending $inc"
                    else
                        pending="$inc"
                    fi
                    ;;
            esac
        done
    done
    for inc in $seen; do
        printf '%s\n' "$inc"
    done
}

# Write TREE's make database to DB and print each object whose rule names ds4.c
# as a prerequisite, followed by that rule's prerequisites. These are exactly
# the objects that see the Mellum includes, because those includes reach them
# through ds4.c.
_md_consumers() {
    local tree="$1" db="$2"
    ( cd "$tree" && make -qp 2>/dev/null ) > "$db" || true
    awk '
        /^[A-Za-z0-9_.\/-]+( +[A-Za-z0-9_.\/-]+)*: / {
            colon = index($0, ": ")
            targets = substr($0, 1, colon - 1)
            prereqs = substr($0, colon + 2)
            if (prereqs !~ /(^| )ds4\.c( |$)/) next
            n = split(targets, t, " ")
            for (i = 1; i <= n; i++) {
                if (t[i] !~ /\.o$/) continue
                print t[i] " " prereqs
            }
        }' "$db"
}

# Report OBJECT/INCLUDE pairs that the Makefile does not declare.
_md_report_missing() {
    local pairs="$1" incs="$2" label="$3" reported=0 line obj rest inc
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        obj="${line%% *}"
        rest="${line#* }"
        for inc in $incs; do
            case " $rest " in
                *" $inc "*) ;;
                *)
                    printf '  FAIL: %s does not depend on %s (%s)\n' "$obj" "$inc" "$label" >&2
                    reported=$((reported + 1))
                    if [[ $reported -ge $_MD_MAX_REPORT ]]; then
                        printf '  FAIL: more than %d missing include dependencies at %s\n' \
                            "$_MD_MAX_REPORT" "$label" >&2
                        return 1
                    fi
                    ;;
            esac
        done
    done < "$pairs"
    [[ $reported -eq 0 ]]
}

# Every object that sees the includes must declare every include it sees, at
# every Mellum boundary, not only on the final tree.
test_series_mellum_incs_are_declared_dependencies() {
    local tree sha incs pairs
    tree=$(_md_tree)
    while IFS= read -r sha; do
        git -C "$tree" checkout --quiet --detach "$sha"
        incs=$(_md_includes "$tree")
        if [[ -z "$incs" ]]; then
            printf '  FAIL: no ds4_mellum_*.inc includes at %s\n' "$(_md_label "$tree" "$sha")" >&2
            return 1
        fi
        pairs="$TMP_ROOT/make-deps-pairs-${sha:0:7}"
        _md_consumers "$tree" "$TMP_ROOT/make-deps-db-${sha:0:7}" > "$pairs"
        if [[ ! -s "$pairs" ]]; then
            printf '  FAIL: no ds4.c consumers at %s\n' "$(_md_label "$tree" "$sha")" >&2
            return 1
        fi
        _md_report_missing "$pairs" "$incs" "boundary $(_md_label "$tree" "$sha")" || return 1
    done <<< "$(_md_boundaries "$tree")"
}

# The declared dependencies must be the ones Make uses: with up-to-date
# objects and a changed include, `make -n` must still schedule each consumer's
# recipe. Timestamps are controlled so only the include can trigger it.
test_series_mellum_inc_changes_rebuild_consumers() {
    local tree tip incs pairs scratch line obj rest inc out reported=0 p
    tree=$(_md_tree)
    tip=$(git -C "$tree" rev-parse refs/ds4/model/qwen35)
    git -C "$tree" checkout --quiet --detach "$tip"
    incs=$(_md_includes "$tree")
    pairs="$TMP_ROOT/make-deps-final-pairs"
    _md_consumers "$tree" "$TMP_ROOT/make-deps-final-db" > "$pairs"
    scratch="$TMP_ROOT/make-deps-scratch"
    rm -rf "$scratch"
    mkdir -p "$scratch"
    cp "$tree/Makefile" "$scratch/Makefile"

    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        obj="${line%% *}"
        rest="${line#* }"
        for inc in $incs; do
            for p in $rest "$inc"; do
                case "$p" in
                    /*) continue ;;
                esac
                mkdir -p "$scratch/$(dirname "$p")"
                : > "$scratch/$p"
                touch -t 200001010000 "$scratch/$p"
            done
            mkdir -p "$scratch/$(dirname "$obj")"
            : > "$scratch/$obj"
            touch -t 200101010000 "$scratch/$obj"
            out=$( cd "$scratch" && make -n -W "$inc" "$obj" 2>/dev/null || true )
            case "$out" in
                *"-o $obj"*) ;;
                *)
                    printf '  FAIL: make skipped %s after %s changed\n' "$obj" "$inc" >&2
                    reported=$((reported + 1))
                    if [[ $reported -ge $_MD_MAX_REPORT ]]; then
                        printf '  FAIL: more than %d stale rebuilds\n' "$_MD_MAX_REPORT" >&2
                        return 1
                    fi
                    ;;
            esac
        done
    done < "$pairs"
    [[ $reported -eq 0 ]]
}

# Adding a dependency group must not displace the default goal.
test_series_default_goal_is_all() {
    local tree sha goal
    tree=$(_md_tree)
    while IFS= read -r sha; do
        git -C "$tree" checkout --quiet --detach "$sha"
        goal=$( cd "$tree" && make -qp 2>/dev/null | awk '$1 == ".DEFAULT_GOAL" { print $3; exit }' || true )
        assert_eq "all" "$goal" "default goal at $(_md_label "$tree" "$sha")" || return 1
    done <<< "$(_md_boundaries "$tree")"
}

# The runner reads this registry after sourcing the module.
# shellcheck disable=SC2034
DS4_MODULE_TESTS=(
    test_series_mellum_incs_are_declared_dependencies
    test_series_mellum_inc_changes_rebuild_consumers
    test_series_default_goal_is_all
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
