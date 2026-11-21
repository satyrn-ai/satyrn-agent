#!/usr/bin/env bash
#
# tests/ds4_common_math_test.sh
#
# Regression for the shader library's math configuration in patches/common.
#
# Pinning MTLLanguageVersion also changes the compiler's default mathMode:
# Apple documents the mathMode default as depending on the language standard
# version, and pinning 3.2 or 4.0 selects strict IEEE-754 on the SDKs tested,
# which costs ~43% of prefill. The build cannot see the difference, so this
# test reads the exported common series: it materializes the common prefix
# with ds4-check and checks the compile-options source and its test target.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/ds4_test_helpers.sh
source "$TEST_DIR/ds4_test_helpers.sh"

# Print the materialized common prefix, materializing it once per module run.
_cm_tree() {
    local marker="$TMP_ROOT/common-math-tree" out
    if [[ -f "$marker" ]]; then
        cat "$marker"
        return 0
    fi
    out="$TMP_ROOT/common-math-check.out"
    if ! DS4_CHECK_DIR="$TMP_ROOT/common-math-check" \
        bash "$REPO_ROOT/tools/ds4-check.sh" --common-only >"$out" 2>&1; then
        printf '  FAIL: ds4-check could not materialize the common prefix\n' >&2
        sed -n '1,20p' "$out" | sed 's/^/    /' >&2
        return 1
    fi
    printf '%s\n' "$TMP_ROOT/common-math-check/common" > "$marker"
    cat "$marker"
}

# Print the body of ds4_gpu_compile_options() from TREE's ds4_metal.m.
_cm_compile_options() {
    local tree="$1"
    awk '
        /static MTLCompileOptions \*ds4_gpu_compile_options\(void\) \{/ { inside = 1 }
        inside { print }
        inside && /^}/ { exit }
    ' "$tree/ds4_metal.m"
}

# The pins must keep their language versions and gain an explicit fast math
# configuration, because the pinned compiler would otherwise choose strict.
test_common_pins_state_fast_math() {
    local tree body
    tree=$(_cm_tree)
    body=$(_cm_compile_options "$tree")
    [[ -n "$body" ]] || {
        printf '  FAIL: ds4_gpu_compile_options() not found in ds4_metal.m\n' >&2
        return 1
    }
    grep -q 'options.languageVersion = MTLLanguageVersion3_2;' <<< "$body" || {
        printf '  FAIL: the Metal 3.2 language pin is gone\n' >&2
        return 1
    }
    grep -q 'options.languageVersion = MTLLanguageVersion4_0;' <<< "$body" || {
        printf '  FAIL: the Metal 4.0 language pin is gone\n' >&2
        return 1
    }
    grep -q 'options.mathMode = MTLMathModeFast;' <<< "$body" || {
        printf '  FAIL: the pinned shaders do not state mathMode = fast\n' >&2
        return 1
    }
    grep -q 'options.mathFloatingPointFunctions = MTLMathFloatingPointFunctionsFast;' <<< "$body" || {
        printf '  FAIL: the pinned shaders do not state the fast floating-point functions\n' >&2
        return 1
    }
}

# DS4_METAL_MATH_SAFE is the diagnostic override and must stay effective: it
# must apply after the fast default, set the strict configuration, and keep the
# diagnostic line in the init path.
test_common_safe_override_stays_effective() {
    local tree source body fast_at safe_at
    tree=$(_cm_tree)
    source="$tree/ds4_metal.m"
    body=$(_cm_compile_options "$tree")
    [[ -n "$body" ]] || {
        printf '  FAIL: ds4_gpu_compile_options() not found in ds4_metal.m\n' >&2
        return 1
    }
    grep -q 'ds4_gpu_env_bool("DS4_METAL_MATH_SAFE") > 0' <<< "$body" || {
        printf '  FAIL: the override is not applied by the compile options\n' >&2
        return 1
    }
    grep -q 'options.mathMode = MTLMathModeSafe;' <<< "$body" || {
        printf '  FAIL: the safe override no longer sets MTLMathModeSafe\n' >&2
        return 1
    }
    grep -q 'options.mathFloatingPointFunctions = MTLMathFloatingPointFunctionsPrecise;' <<< "$body" || {
        printf '  FAIL: the safe override no longer sets the precise floating-point functions\n' >&2
        return 1
    }
    fast_at=$(grep -n 'options.mathMode = MTLMathModeFast;' "$source" | head -1 | cut -d: -f1)
    safe_at=$(grep -n 'options.mathMode = MTLMathModeSafe;' "$source" | head -1 | cut -d: -f1)
    [[ -n "$fast_at" && -n "$safe_at" && "$fast_at" -lt "$safe_at" ]] || {
        printf '  FAIL: the safe override must follow the fast default\n' >&2
        return 1
    }
    grep -q 'math mode = safe (strict IEEE-754) by DS4_METAL_MATH_SAFE' "$source" || {
        printf '  FAIL: the diagnostic line for the override is gone\n' >&2
        return 1
    }
    grep -q 'ds4_gpu_math_config_text' "$source" || {
        printf '  FAIL: the engine does not report its effective math configuration\n' >&2
        return 1
    }
    grep -q 'ds4_gpu_math_config_text' "$tree/ds4_gpu.h" || {
        printf '  FAIL: ds4_gpu.h does not declare ds4_gpu_math_config_text\n' >&2
        return 1
    }
}

# The behavioural check ships with the series so a developer can run it.
test_common_ships_the_behavioural_test() {
    local tree
    tree=$(_cm_tree)
    [[ -f "$tree/tests/test_metal_math_options.c" ]] || {
        printf '  FAIL: tests/test_metal_math_options.c is missing\n' >&2
        return 1
    }
    grep -q '^test-metal-math-options:' "$tree/Makefile" || {
        printf '  FAIL: the Makefile has no test-metal-math-options target\n' >&2
        return 1
    }
    grep -q '/tests/test_metal_math_options$' "$tree/.gitignore" || {
        printf '  FAIL: the test binary is not ignored\n' >&2
        return 1
    }
}

# The runner reads this registry after sourcing the module.
# shellcheck disable=SC2034
DS4_MODULE_TESTS=(
    test_common_pins_state_fast_math
    test_common_safe_override_stays_effective
    test_common_ships_the_behavioural_test
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
