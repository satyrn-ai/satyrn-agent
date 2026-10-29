#!/usr/bin/env bash
#
# tests/ds4_e2e_preflight_test.sh
#
# Devenv entry-point checks and model-backed E2E preflight tests. The preflight
# tests exercise only the input validation of tests/ds4_e2e_test.sh; they do
# not require a real model or a ds4-py checkout.

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TEST_DIR/ds4_test_helpers.sh"

# --- devenv entry-point tests -------------------------------------------------

test_devenv_entry_points_show_help() {
    # The suite also runs on ubuntu-latest where devenv/Nix is not installed;
    # entry-point registration is exercised here whenever devenv is present
    # and via `devenv shell -- ds4-<tool> --help` in the developer workflow.
    if ! command -v devenv >/dev/null 2>&1; then
        printf '  SKIP: devenv is not available on PATH\n' >&2
        return 0
    fi

    local out err

    out="$TMP_ROOT/ds4-entry-sync.out"
    err="$TMP_ROOT/ds4-entry-sync.err"
    if ! devenv shell -- ds4-sync --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-sync --help failed\n' >&2
        return 1
    fi
    grep -q -- '--common-only' "$out" || {
        printf '  FAIL: ds4-sync help did not mention --common-only\n' >&2
        return 1
    }
    grep -q -- '--model' "$out" || {
        printf '  FAIL: ds4-sync help did not mention --model\n' >&2
        return 1
    }

    out="$TMP_ROOT/ds4-entry-export.out"
    err="$TMP_ROOT/ds4-entry-export.err"
    if ! devenv shell -- ds4-export --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-export --help failed\n' >&2
        return 1
    fi
    grep -q -- '--force' "$out" || {
        printf '  FAIL: ds4-export help did not mention --force\n' >&2
        return 1
    }

    out="$TMP_ROOT/ds4-entry-check.out"
    err="$TMP_ROOT/ds4-entry-check.err"
    if ! devenv shell -- ds4-check --help >"$out" 2>"$err"; then
        cat "$err" >&2
        printf '  FAIL: devenv shell -- ds4-check --help failed\n' >&2
        return 1
    fi
    grep -q -- '--common-only' "$out" || {
        printf '  FAIL: ds4-check help did not mention --common-only\n' >&2
        return 1
    }
    grep -q -- '--model' "$out" || {
        printf '  FAIL: ds4-check help did not mention --model\n' >&2
        return 1
    }
    grep -q -- '--build' "$out" || {
        printf '  FAIL: ds4-check help did not mention --build\n' >&2
        return 1
    }
}

# --- model-backed E2E preflight tests -----------------------------------------

# Write a minimal, tensor-free GGUF whose general.architecture is ARCH. This
# exercises the E2E metadata preflight without generating a real model.
_write_gguf_fixture() {
    local file="$1" arch="$2"
    python3 - "$file" "$arch" <<'PY'
import struct, sys
path, arch = sys.argv[1], sys.argv[2]
def string(data):
    return struct.pack("<Q", len(data)) + data
kv = string(b"general.architecture") + struct.pack("<I", 8) + string(arch.encode())
header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 1)
with open(path, "wb") as fp:
    fp.write(header + kv)
PY
}

# Copy the E2E script and the tools it runs into a standalone repo root so a
# test can exercise the gate hermetically (its .ds4/tree is a disposable
# "normal" tree).
_e2e_scratch_repo() {
    local dest="$1"
    mkdir -p "$dest/tools" "$dest/tests"
    cp "$REPO_ROOT/tools/ds4-lib.sh" \
        "$REPO_ROOT/tools/ds4-sync.sh" \
        "$REPO_ROOT/tools/ds4-check.sh" \
        "$REPO_ROOT/tools/ds4-export.sh" \
        "$REPO_ROOT/tools/ds4-gguf-arch.py" "$dest/tools/"
    cp "$REPO_ROOT/tests/ds4_e2e_test.sh" "$dest/tests/"
}

# Run the model-backed E2E script in a controlled environment and capture its
# stderr. These tests exercise only the script's input validation: a missing
# DS4PY_PROJECT or DS4_TEST_MODEL must produce a clear nonzero usage error
# before the script reads a model, resolves ds4py, or builds anything.
test_e2e_requires_external_ds4py() {
    local err="$TMP_ROOT/e2e-no-ds4py.err"
    if ( unset DS4PY_PROJECT DS4_TEST_MODEL 2>/dev/null || true
         bash "$REPO_ROOT/tests/ds4_e2e_test.sh" ) 2>"$err"; then
        printf '  FAIL: expected missing DS4PY_PROJECT to fail\n' >&2
        return 1
    fi
    grep -q 'DS4PY_PROJECT' "$err" || {
        printf '  FAIL: error did not mention DS4PY_PROJECT\n' >&2
        return 1
    }
    if grep -q 'DS4_TEST_MODEL' "$err"; then
        printf '  FAIL: DS4PY_PROJECT must be validated before the model\n' >&2
        return 1
    fi
}

test_e2e_requires_dense_qwen35_model() {
    # Point DS4PY_PROJECT at a path that does not exist: a correct preflight
    # must report the missing model before it ever touches that checkout.
    local err="$TMP_ROOT/e2e-no-model.err"
    if ( unset DS4_TEST_MODEL 2>/dev/null || true
         DS4PY_PROJECT="$TMP_ROOT/absent-ds4py" \
         bash "$REPO_ROOT/tests/ds4_e2e_test.sh" ) 2>"$err"; then
        printf '  FAIL: expected missing DS4_TEST_MODEL to fail\n' >&2
        return 1
    fi
    grep -q 'DS4_TEST_MODEL' "$err" || {
        printf '  FAIL: error did not mention DS4_TEST_MODEL\n' >&2
        return 1
    }
    if grep -q 'not found' "$err"; then
        printf '  FAIL: model check must not resolve the ds4-py checkout\n' >&2
        return 1
    fi
}

test_e2e_rejects_wrong_architecture_model() {
    local venv="$TMP_ROOT/e2e-wrong-venv"
    mkdir -p "$venv/.venv/bin"
    ln -s "$(command -v python3)" "$venv/.venv/bin/python3"

    local model="$TMP_ROOT/e2e-wrong.gguf"
    _write_gguf_fixture "$model" qwen4exp

    local err="$TMP_ROOT/e2e-wrong.err"
    if ( DS4PY_PROJECT="$venv" DS4_TEST_MODEL="$model" \
         bash "$REPO_ROOT/tests/ds4_e2e_test.sh" ) 2>"$err"; then
        printf '  FAIL: expected wrong-architecture model to be rejected\n' >&2
        return 1
    fi
    grep -q 'qwen35' "$err" || {
        printf '  FAIL: error did not mention the required qwen35 architecture\n' >&2
        return 1
    }
    grep -q 'qwen4exp' "$err" || {
        printf '  FAIL: error did not report the observed architecture\n' >&2
        return 1
    }
}

test_e2e_uses_isolated_tree_and_preserves_normal_tree() {
    local repo="$TMP_ROOT/e2e-repo"
    _e2e_scratch_repo "$repo"

    local upstream="$TMP_ROOT/e2e-upstream"
    mkdir -p "$upstream"
    git -C "$upstream" init -q
    printf 'line1\n' > "$upstream/notes.txt"
    git -C "$upstream" add notes.txt
    git -C "$upstream" commit -qm base
    local pin
    pin="$(git -C "$upstream" rev-parse HEAD)"

    local patches="$TMP_ROOT/e2e-patches"
    mkdir -p "$patches"
    _build_series "$patches"

    # A disposable "normal" .ds4/tree that the gate must leave alone.
    local normal_tree="$repo/.ds4/tree"
    mkdir -p "$normal_tree"
    git -C "$normal_tree" init -q
    printf 'keep\n' > "$normal_tree/normal-marker"
    git -C "$normal_tree" add normal-marker
    git -C "$normal_tree" commit -qm normal
    local normal_head
    normal_head="$(git -C "$normal_tree" rev-parse HEAD)"

    # Fake ds4-py venv: the pinned Python runs the metadata probe, and a stub
    # ds4py fails at the build step so the gate stops there deterministically.
    local venv="$TMP_ROOT/e2e-venv"
    mkdir -p "$venv/.venv/bin"
    ln -s "$(command -v python3)" "$venv/.venv/bin/python3"
    cat > "$venv/.venv/bin/ds4py" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
    chmod +x "$venv/.venv/bin/ds4py"

    # Correct-architecture fixture, referenced by a RELATIVE path to exercise
    # canonicalization as well.
    local model="$TMP_ROOT/e2e-model.gguf"
    _write_gguf_fixture "$model" qwen35

    local out="$TMP_ROOT/e2e-isolated.out"
    local err="$TMP_ROOT/e2e-isolated.err"
    if ( cd "$TMP_ROOT" &&
         DS4PY_PROJECT="$venv" \
         DS4_TEST_MODEL="e2e-model.gguf" \
         DS4_PATCHES_DIR="$patches" \
         DS4_CACHE_DIR="$TMP_ROOT/e2e-cache" \
         UPSTREAM_URL="$upstream" \
         UPSTREAM_COMMIT="$pin" \
         bash "$repo/tests/ds4_e2e_test.sh" ) >"$out" 2>"$err"; then
        printf '  FAIL: expected e2e to stop at the ds4py build step\n' >&2
        return 1
    fi
    grep -q 'ds4py build failed' "$err" || {
        cat "$err" >&2
        printf '  FAIL: expected e2e to reach the ds4py build step\n' >&2
        return 1
    }

    assert_eq "$normal_head" "$(git -C "$normal_tree" rev-parse HEAD)" \
        "normal .ds4/tree HEAD survives e2e"
    assert_file_eq $'keep\n' "$normal_tree/normal-marker" \
        "normal .ds4/tree marker survives e2e"
    assert_file_eq $'line1\ncommon\nalpha\nzebra\n' \
        "$repo/.ds4/e2e/tree/notes.txt" "isolated e2e tree materialized"

    local canonical_model
    canonical_model="$(cd "$TMP_ROOT" && pwd)/e2e-model.gguf"
    grep -q "model  $canonical_model" "$out" || {
        cat "$out" >&2
        printf '  FAIL: e2e did not canonicalize the relative model path\n' >&2
        return 1
    }
}

DS4_MODULE_TESTS=(
    test_devenv_entry_points_show_help
    test_e2e_requires_external_ds4py
    test_e2e_requires_dense_qwen35_model
    test_e2e_rejects_wrong_architecture_model
    test_e2e_uses_isolated_tree_and_preserves_normal_tree
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ds4_module_main "$@"
fi
