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

## Second finding: the toolchain's SDK decides the tensor path (added 2026-11-21)

The fix above removes the math-mode loss, but the prefill gap had two causes. The Metal 4 tensor probe
is compiled out when the C SDK is older than 26 (`#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 260000`), so
the engine reports `tensor_matmul=off` and falls back to the simdgroup path. That costs the same ~43%
and is independent of the pins and of math mode:

| Build | SDK | `tensor_matmul` | Prefill |
| --- | --- | --- | ---: |
| reference `d2d9338`, Xcode clang | 27.2 | on | 4,150 t/s |
| reference `d2d9338`, Nix clang | 15.5 | **off** | 2,326 / 2,354 t/s |
| port 0005, Nix clang, pins + math fast | 15.5 | **off** | 2,327–2,353 t/s |
| port 0005, Xcode clang, 4.0 pin, safe math | 27.2 | on | 2,331–2,367 t/s |
| port 0005, Xcode clang, 4.0 pin, math fast | 27.2 | on | 4,041–4,137 t/s |

The dev/CI build (`devenv shell -- make`, `ds4py build` under devenv) uses Nix clang and is in the
"tensor off" row, so its performance is not comparable with the reference build. Acceptance runs must
record the compiler, the SDK's `__MAC_OS_X_VERSION_MAX_ALLOWED`, and the `tensor_matmul` flag, and the
Mellum performance pairs must be measured with an SDK-26-or-later build. Correctness gates — oracle,
kernels, rewind, streaming parity — are unaffected by which path is taken, and the parity runs above
use the 2048-token prompt (`68132d36…`) with 512 generated ids, `7 GiB`/`2 GiB` caches (979/652 slots).

## Policy update: the Nix toolchain is canonical (added 2026-11-21)

All builds and measurements use the Nix toolchain. Consequences:

- The reference for any performance comparison must also be built with Nix. The valid current-0005
  MXFP4 pair is then port `f5463ed1` 2,327 t/s against a Nix-built `d2d9338` 2,326 t/s prefill
  (eight stable single-process runs each, same prompt, context 3,072), i.e. parity within 0.1%; the
  previously quoted 4,081 / 4,078 pair used the Xcode toolchain and is supplementary, not canonical.
- With the *old* `apple-sdk_15` pin the math-mode fix was inert for performance, because the tensor
  path was compiled out and 3.2 + safe and 3.2 + fast both measured ~2,330 t/s. With PR #38
  (`apple-sdk_26`) the canonical build compiles Metal 4 in, the 4.0 pin applies, and the fix becomes
  performance-relevant: without explicit fast math the shaders compile strict and lose ~43%. The two
  changes are a pair, and #33 should land first so the bumped build never runs strict.
- Even with the old pin the fix mattered for determinism: an SDK-26 build would otherwise run strict
  while everything else ran fast, changing numerics for the same source.
- Runtime-gating the 4.0 pin and the probe is not sufficient: `ds4_gpu_detect_metal4_features()` is
  itself wrapped in `#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 260000` and uses `MTLGPUFamilyMetal4`, so an
  old-SDK build still reports `tensor_matmul=off` (measured: language=4.0, math fast, 2,312–2,328 t/s).
  Reaching the tensor path under Nix needs that detection block runtime-gated as well, with a documented
  fallback for `MTLGPUFamilyMetal4`, or a newer apple-sdk. That is Koudai's Metal 4 gating, not this
  patch; it is tracked in #37.
- The runner-based series (0004/0005/0006 and the MXFP4 pair) must be re-measured on a quiet host; the
  runs collected while this machine was busy (PyCharm ~200% CPU) are not usable, and are not quoted.
