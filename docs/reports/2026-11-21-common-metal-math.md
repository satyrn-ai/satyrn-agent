# Common-layer Metal math configuration — evidence, 2026-11-21

Patch `patches/common/0004` states the shader library's fast math configuration explicitly. Pinning
`MTLCompileOptions.languageVersion` changes the compiler's default `mathMode`, which Apple documents as
depending on the language standard version; on the SDKs tested the pinned builds compiled at strict
IEEE-754 while the unpinned reference kept fast math. This report records the fix's own gates. The
Mellum-specific 43% prefill recovery is measured on `feat/mellum-support` and does not transfer to
other models: Qwen 3.8 27B shows no measurable difference here.

## Identities

| Item | Value |
| --- | --- |
| Base | `main` `eed5c4f` (PR #24 merged) |
| Common tip | `9da2a7d6`, tree `ab4f50c6` |
| Patch | `patches/common/0004-…`, sha256 `112046388c1cee4b…` |
| Combined common+qwen35 tree | `4caa5b8d`, tree `fb0514ef` |
| Nix toolchain | clang 21.1.8, `__MAC_OS_X_VERSION_MAX_ALLOWED = __MAC_15_5` → language 3.2 |
| Xcode toolchain | Apple clang 21.0.0, `__MAC_OS_X_VERSION_MAX_ALLOWED = __MAC_27_2` → language 4.0 |
| 3.2 library | `a395eea58d9b33ea…` |
| 4.0 library (hand-linked from the Xcode objects) | `33023a5464567d38…` |
| Qwen target | `Qwen3.8-27B-Q4_K_M.gguf`, sha256 `e00082f7…e520` |
| Qwen drafter | `dflash-Qwen3.8-27B-Q4_0.gguf`, sha256 `0a994382…a3c4` |

## Effective configuration, both language paths

`tests/test_metal_math_options` is device-free and prints the configuration the library will use:

| Toolchain | Default | `DS4_METAL_MATH_SAFE=1` |
| --- | --- | --- |
| Nix clang (SDK max 15.5) | `language=3.2 mathMode=fast mathFloatingPointFunctions=fast` | `language=3.2 mathMode=safe mathFloatingPointFunctions=precise` |
| Xcode clang (SDK max 27.2) | `language=4.0 mathMode=fast mathFloatingPointFunctions=fast` | `language=4.0 mathMode=safe mathFloatingPointFunctions=precise` |

`mathFloatingPointFunctions` is reported because Apple distinguishes it from `mathMode`; both set to
fast, matching the documented defaults (`fastMathEnabled` defaults YES,
`mathFloatingPointFunctions` defaults fast). The language pins are unchanged, and the safe override
still applies after the fast default.

## Qwen 3.8 27B, without Mellum

Model-free Metal gates on the fixed combined tree (`make -C .ds4/check/qwen35`):

| Target | Result |
| --- | --- |
| `test-qwen4-kernels` | all passed |
| `test-qwen35-verify` | all qwen35 verify tests passed |
| `test-qwen35-graph` | all qwen35 verify rows passed (rows byte-equal to one-row calls; vs double ≤ 8.34e-07) |
| `test-dflash` | all dflash drafter tests passed |
| `test-qwen35-host` | all host gate tests passed |

Live suite, Python-hosted (`ds4py`, 3.2 library), `tests/abnormal tests/e2e/live`:
48 passed, 1 failed — `test_harness_tui`'s `max_tokens` after `/switch`, the same baseline failure
recorded for `main`'s own build. The run log carries
`Metal shader library language=3.2 mathMode=fast mathFloatingPointFunctions=fast`.

Live suite, Python-hosted, 4.0 library (Xcode objects, hand-linked; the ABI manifest's `library_sha256`
was updated to the linked file so `ds4py` would load it):
`test_dflash_parity` + `test_dflash_boundaries` 10 passed, with
`Metal shader library language=4.0 mathMode=fast mathFloatingPointFunctions=fast`. The existing
same-verify-mode serial/speculative parity contract is unchanged; no ordinary-decode byte-equality
claim is made.

Performance, interleaved A/B with the same prompt, model, context 4096, `-n 64`, one process per run,
order B F F B B F F B (B = main without the patch, F = the fixed tree), medians of 4:

| Arm | Prefill | Decode |
| --- | ---: | ---: |
| `main` (strict) | 205.90 t/s | 28.57 t/s |
| fixed (fast) | 204.09 t/s | 28.50 t/s |

Delta: -0.9% prefill, -0.2% decode, inside this host's run-to-run spread. **No Qwen performance claim
is made**; the 43% recovery belongs to the Mellum workload where it was measured.

## Repository gates

- `bash tests/ds4_tools_test.sh`: 53 passed (50 + the 3 new common-math checks). The new checks failed
  on the previous common series (no explicit math mode, no behavioural test target).
- `prek run --all-files`: pass.
- `ds4-check --common-only --build` and `ds4-check --model qwen35 --build`: reconstruct and build.
- Model-free Python suite: 290 passed, 100% line and branch coverage.

Raw run logs: `/tmp/qwen-perf-abba/`, `/tmp/qwen-live-fixed.log`, `/tmp/xcode-lib/`.
