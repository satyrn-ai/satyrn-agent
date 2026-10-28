#!/usr/bin/env bash
#
# tests/ds4_e2e_test.bash
#
# Model-backed end-to-end gate for the migrated ds4 patch series. Run it inside
# the devenv shell with an external ds4-py checkout and a dense qwen35 GGUF:
#
#   export DS4PY_PROJECT=/path/to/ds4-py
#   export DS4_TEST_MODEL=/path/to/dense-qwen35.gguf
#   devenv shell -- bash tests/ds4_e2e_test.bash
#
# The script is read-only with respect to the tracked patches: it materializes
# and builds scratch trees, but never exports, edits, or commits patch files.
# macOS and Linux portable Bash 3.2 (no associative arrays, mapfile, or
# GNU/BSD-only flags).

set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/.." && pwd)"

source "$REPO_ROOT/tools/ds4-lib.bash"

E2E_SCRATCH="$REPO_ROOT/.ds4/e2e"

usage() {
    cat <<'EOF'
Usage: ds4_e2e_test [--help]

Required environment:
  DS4PY_PROJECT   path to an external ds4-py checkout (its .venv/bin is used)
  DS4_TEST_MODEL  path to a dense qwen35 GGUF

Runs: pristine checks, ds4-py build + ABI/load, live sync-plan/restore, and
deterministic raw-generation parity against ds4-agent.
EOF
}

die() {
    printf 'ds4-e2e: %s\n' "$*" >&2
    exit 1
}

main() {
    if [[ $# -gt 0 ]]; then
        case "$1" in
            --help | -h)
                usage
                exit 0
                ;;
            *)
                die "unexpected argument: $1"
                ;;
        esac
    fi

    # Validate required inputs before touching the model or building anything.
    if [[ -z "${DS4PY_PROJECT:-}" ]]; then
        die "DS4PY_PROJECT is not set (an external ds4-py checkout is required)"
    fi
    if [[ -z "${DS4_TEST_MODEL:-}" ]]; then
        die "DS4_TEST_MODEL is not set (a dense qwen35 GGUF is required)"
    fi

    # Prefer the checkout's venv (documented), then fall back to PATH.
    export PATH="$DS4PY_PROJECT/.venv/bin:$PATH"
    local ds4py
    ds4py="$(command -v ds4py)" ||
        die "ds4py not found on PATH (run 'uv sync --project $DS4PY_PROJECT')"

    # The model must be a readable GGUF; check the magic without loading it.
    [[ -f "$DS4_TEST_MODEL" ]] ||
        die "DS4_TEST_MODEL is not a file: $DS4_TEST_MODEL"
    [[ -r "$DS4_TEST_MODEL" ]] ||
        die "DS4_TEST_MODEL is not readable: $DS4_TEST_MODEL"
    local magic
    magic="$(dd if="$DS4_TEST_MODEL" bs=4 count=1 2>/dev/null)"
    [[ "$magic" == "GGUF" ]] ||
        die "DS4_TEST_MODEL is not a GGUF file: $DS4_TEST_MODEL"

    printf 'ds4-e2e: repo   %s\n' "$REPO_ROOT"
    printf 'ds4-e2e: ds4py  %s\n' "$ds4py"
    printf 'ds4-e2e: model  %s\n' "$DS4_TEST_MODEL"

    rm -rf "$E2E_SCRATCH"
    mkdir -p "$E2E_SCRATCH" || die "cannot create $E2E_SCRATCH"

    local backend
    case "$(uname -s)" in
        Darwin) backend="metal" ;;
        *) backend="cpu" ;;
    esac

    # 1. Materialize the full real tree and run pristine checks.
    printf '\n== ds4-sync (materialize full tree) ==\n'
    bash "$REPO_ROOT/tools/ds4-sync.bash" --force

    printf '\n== ds4-check (pristine checks) ==\n'
    bash "$REPO_ROOT/tools/ds4-check.bash"

    # 2. Build the checked tree through ds4-py and capture the library path.
    local lib_out="$E2E_SCRATCH/lib"
    printf '\n== ds4py build (backend=%s) ==\n' "$backend"
    local lib_path
    lib_path="$("$ds4py" build --src "$REPO_ROOT/.ds4/tree" \
        --backend "$backend" --out "$lib_out")" ||
        die "ds4py build failed"
    [[ -n "$lib_path" && -f "$lib_path" ]] ||
        die "ds4py build produced no library at '$lib_path'"
    printf 'ds4-e2e: library %s\n' "$lib_path"

    # 3. ABI/load check (no model).
    printf '\n== ds4py check --lib (ABI/load) ==\n'
    "$ds4py" check --lib "$lib_path" || die "ds4py ABI/load check failed"

    # 4. Live sync-plan and restore check against the dense qwen35 model.
    printf '\n== ds4py check --live (sync plans + restore) ==\n'
    local live_out="$E2E_SCRATCH/live.out"
    if ! "$ds4py" check --live --lib "$lib_path" \
        --model "$DS4_TEST_MODEL" > "$live_out"; then
        cat "$live_out"
        die "ds4py live check failed (see output above)"
    fi
    cat "$live_out"
    grep -Eq '^sync: +ok ' "$live_out" ||
        die "live check did not report successful sync plans"
    grep -Eq '^restore: +ok ' "$live_out" ||
        die "live check did not report a verified restore"

    # 5. Build ds4-agent from the same tree.
    printf '\n== make ds4-agent ==\n'
    local agent_bin="$REPO_ROOT/.ds4/tree/ds4-agent"
    if [[ "$backend" == "metal" ]]; then
        make -C "$REPO_ROOT/.ds4/tree" ds4-agent
    else
        make -C "$REPO_ROOT/.ds4/tree" cpu
    fi
    [[ -x "$agent_bin" ]] || die "ds4-agent binary not found: $agent_bin"

    # 6. Deterministic raw-generation parity (same prompt, temp 0, seed 1,
    # fixed token limit). Both commands write only generated token bytes to
    # stdout; progress and diagnostics go to stderr.
    printf '\n== raw generation parity ==\n'
    local prompt="The three primary colors are"
    local ctx=4096
    local tokens=64
    local py_raw="$E2E_SCRATCH/ds4py.raw"
    local agent_raw="$E2E_SCRATCH/ds4-agent.raw"

    "$ds4py" raw -p "$prompt" -m "$DS4_TEST_MODEL" -c "$ctx" -n "$tokens" \
        --temp 0 --seed 1 --backend "$backend" --lib "$lib_path" > "$py_raw" ||
        die "ds4py raw generation failed"

    # Run the agent from the source tree so its relative metal/*.metal sources
    # resolve; the model path is absolute.
    ( cd "$REPO_ROOT/.ds4/tree" &&
        "$agent_bin" --non-interactive --raw -p "$prompt" \
            -m "$DS4_TEST_MODEL" -c "$ctx" -n "$tokens" \
            --temp 0 --seed 1 --"$backend" ) > "$agent_raw" ||
        die "ds4-agent raw generation failed"

    # Both sides must have produced bytes: cmp alone would otherwise report
    # parity when both raw files are empty.
    local py_bytes agent_bytes
    py_bytes="$(wc -c < "$py_raw" | tr -d '[:space:]')"
    agent_bytes="$(wc -c < "$agent_raw" | tr -d '[:space:]')"
    if [[ "$py_bytes" -eq 0 ]]; then
        die "ds4py raw generation produced empty output"
    fi
    if [[ "$agent_bytes" -eq 0 ]]; then
        die "ds4-agent raw generation produced empty output"
    fi

    if cmp -s "$py_raw" "$agent_raw"; then
        printf 'ds4-e2e: raw parity OK (%s bytes)\n' "$py_bytes"
    else
        printf 'ds4-e2e: raw parity MISMATCH\n' >&2
        printf 'ds4-e2e: ds4py     bytes=%s hash=%s\n' \
            "$py_bytes" \
            "$(git hash-object "$py_raw")" >&2
        printf 'ds4-e2e: ds4-agent bytes=%s hash=%s\n' \
            "$agent_bytes" \
            "$(git hash-object "$agent_raw")" >&2
        die "raw generation parity failed (see hashes above)"
    fi

    printf '\nds4-e2e: PASS\n'
}

main "$@"
