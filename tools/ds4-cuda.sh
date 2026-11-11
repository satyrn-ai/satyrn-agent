#!/usr/bin/env bash
# Run a command with the dense qwen35 CUDA toolchain.
#
# The CUDA closure (nvcc, cudart, CCCL, cuBLAS) is about 1.5 GiB, so devenv.nix
# adds it to the shell only when DS4_CUDA=1. Every Linux CI job enters the plain
# shell, which keeps that cost out of CI. This wrapper sets the flag.
#
#   tools/ds4-cuda.sh make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-quant
#   tools/ds4-cuda.sh            # interactive shell with nvcc and cuBLAS
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Already inside a CUDA shell: run the command directly.
if [[ -n "${CUDA_PATH:-}" ]] && command -v nvcc >/dev/null 2>&1; then
    if [[ $# -eq 0 ]]; then
        exec bash -l
    fi
    exec "$@"
fi

if ! command -v devenv >/dev/null 2>&1; then
    echo "ds4-cuda: devenv is not on PATH; install it as AGENTS.md describes" >&2
    exit 127
fi

if [[ $# -eq 0 ]]; then
    set -- bash -l
fi
# The quoted program is the inner shell's: $1 and "$@" belong to it, not here.
# shellcheck disable=SC2016
exec env DS4_CUDA=1 bash -c 'cd "$1" || exit 1; shift; exec devenv shell -- "$@"' \
    ds4-cuda "$root" "$@"
