#!/usr/bin/env bash
#
# tests/ds4_tools_test.sh
#
# Thin entry point for the ds4 shell test modules. Each module runs in its own
# bash process so module order cannot hide state leakage. With no arguments the
# entry point runs every module; with test names it routes each name to its
# owning module and preserves the requested order. Bash 3.2-compatible.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DS4_MODULES=(
    ds4_lib_test
    ds4_sync_test
    ds4_export_test
    ds4_check_test
    ds4_e2e_preflight_test
)

# Build the flat, ordered test list and the module that owns each test by
# asking each module for its tests. The module files stay the source of truth.
ALL_TESTS=()
TEST_MODULES=()

module_for() {
    local name="$1" i
    for i in "${!ALL_TESTS[@]}"; do
        if [[ "${ALL_TESTS[$i]}" == "$name" ]]; then
            printf '%s\n' "${TEST_MODULES[$i]}"
            return 0
        fi
    done
    return 1
}

run_module() {
    local module="$1"
    shift
    local counts_file="$ENTRY_TMP/counts" status=0 p f
    rm -f "$counts_file"
    DS4_MODULE_SUMMARY=0 DS4_COUNTS_FILE="$counts_file" \
        bash "$TEST_DIR/$module.sh" "$@" || status=$?
    if [[ -f "$counts_file" ]]; then
        read -r p f < "$counts_file"
        PASSED=$((PASSED + p))
        FAILED=$((FAILED + f))
    else
        FAILED=$((FAILED + 1))
    fi
    return "$status"
}

main() {
    ENTRY_TMP="$(mktemp -d "${TMPDIR:-/tmp}/ds4-entry.XXXXXX")"
    trap 'rm -rf "$ENTRY_TMP"' EXIT

    local module list t
    for module in "${DS4_MODULES[@]}"; do
        list="$(bash "$TEST_DIR/$module.sh" --list-tests)"
        while IFS= read -r t || [[ -n "$t" ]]; do
            ALL_TESTS+=("$t")
            TEST_MODULES+=("$module")
        done <<< "$list"
    done

    PASSED=0
    FAILED=0
    local status=0

    if [[ $# -eq 0 ]]; then
        for module in "${DS4_MODULES[@]}"; do
            run_module "$module" || status=1
        done
    else
        local name owner
        for name in "$@"; do
            owner="$(module_for "$name")" || {
                # Preserve the current behavior for a test name no module owns.
                printf 'RUN %s\n' "$name"
                printf 'FAIL %s\n' "$name"
                FAILED=$((FAILED + 1))
                continue
            }
            run_module "$owner" "$name" || status=1
        done
    fi

    printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
    [[ $FAILED -eq 0 && $status -eq 0 ]]
}

main "$@"
