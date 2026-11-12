# Qwen35 Dense CUDA Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dense serial qwen35 decode path to the CUDA build as five new patches in `patches/qwen35/`, each proven by an independent reference test.

**Architecture:** The neutral op contract already exists — `ds4_gpu.h` declares `ds4_gpu_qwen35_gdn_out_tensor`, `ds4_gpu_qwen35_attn_prep_tensor` and `ds4_gpu_qwen35_attn_fa_tensor`, and the Metal backend implements them. This plan implements the same symbols for CUDA in a new `ds4_qwen35_cuda.cuh`, extends the existing Qwen CUDA quant dispatch with Q6_K, and replaces the model-support refusal with backend-aware dispatch. Verify, DFlash and the drafter stay Metal-only.

**Tech Stack:** C11, CUDA 12.9 (`sm_86`), GNU make, the repo's `ds4-sync` / `ds4-export` / `ds4-check` tools, Nix flake checks.

**Spec:** `docs/specs/2026-10-24-ds4-patch-series-design.md`

## Global Constraints

- Upstream pin stays `5379c1c9ac315f1540371b06a3db88491d4059ff`.
- Never commit the ds4 source tree or a submodule into this repo (spec anti-goal, L83).
- Never hand-edit `.patch` files; they are generated from commits in the `.ds4/tree` scratch range (L84).
- Every line ships in the series itself: no patch may depend on files, objects or configuration outside this repo (L85).
- ds4-py owns `Makefile.lib` and build behaviour. Do not add a second build system, a `cuda.mk`, or absolute toolchain paths to any patch (L86).
- CUDA lives inside `patches/qwen35`, never a sibling model directory; series order is `common` then models in `LC_ALL=C` order (L178).
- Patch ledger trailers are mandatory: `Upstream:`, `Retire-when:`, `Carried-commits:` (L54).
- CUDA architecture is `sm_86` for the RTX 3060 and RTX 3090.
- The CUDA toolchain comes from `devenv.nix`: `cudaPackages` 12.9 (`cuda_nvcc`, `cuda_cudart`, `cuda_cccl`, `libcublas`), Linux only, added to the shell only when `DS4_CUDA=1`. Run every CUDA build and test through `tools/ds4-cuda.sh`, which sets that flag; a plain `devenv shell` stays CUDA-free because the closure is about 1.5 GiB and every CI job enters it. Do not add a second toolchain, a hand-rolled `nix shell` line or a `cuda.mk`.
- The pin already carries `.shared` on all three `ldmatrix` forms. Do not re-add it.

## Decisions required before execution

- **D1 — Q5_K is out of scope; Q6_K is required.** The pinned 27B holds 439 Q4_K, 67 Q6_K and 360 F32 dense tensors, and no Q5_K. Q6_K must work on CUDA because `output.weight` and two tensors in each of the 33 layers are Q6_K. `tensor_type_is_qwen35_dense` already accepts Q4_K and Q6_K, so no change may narrow it. Q5_K is deferred in every layer — product kernel, dispatch registration and loader acceptance — until a model in scope needs it.
- **D2 — Correctness evidence for the model-level run.** A numerical oracle is mandatory: the smallest graph the GPU path accepts is compared against a double-precision reference (Task 5), and the real-model run adds batch-versus-serial agreement (Task 8). Determinism, finite logits and correct terminal reasons are supplementary checks, never the oracle. Token-identical agreement with another implementation stays out of scope.
- **D3 — Metal regression owner: koxudaxi.** He will run the live suite (`tests/e2e/live`, 19 tests) on an M4 Max with 0009–0012 applied. Adoption is gated on that run; until it lands the patches are carried but unadopted (Task 7).

## File Structure

| Path | Responsibility | Task |
| --- | --- | --- |
| `ds4_qwen35_cuda.cuh` | The three dense qwen35 CUDA ops; thin adapters over existing shared CUDA kernels | 3, 4 |
| `ds4_qwen4_cuda.cuh` | Q6_K row decoding and dispatch registration for the shared Qwen CUDA path | 2 |
| `ds4_cuda.cu` | One include line at the end of the CUDA translation unit | 3 |
| `ds4.c` | Model-support gate and dense-graph dispatch | 5 |
| `tests/qwen35_cuda_test.{c,h}` | Shared harness: arena, upload, independent CPU quant reference, tolerance checks | 2 |
| `tests/test_qwen35_cuda_quant.c` | Q6_K product tests against an independent decoder | 2 |
| `tests/test_qwen35_cuda_recurrent.c` | Recurrent SiLU output tests, schedules and refusals | 3 |
| `tests/test_qwen35_cuda_attention.c` | Attention preparation and causal attention tests | 4 |
| `tests/test_qwen35_host.c` | New host suite: weight acceptance, refusals, Metal-only verdicts (includes `../ds4.c`) | 5 |
| `tests/test_qwen35_oracle.c` | Numerical oracle: tiny graph versus a double-precision reference | 5 |
| `Makefile`, `.gitignore` | Test targets and build products | 2–5 |
| `patches/qwen35/0009-*.patch` … `0012-*.patch` | Generated ledger entries | 6 |
| `docs/specs/2026-10-24-ds4-patch-series-design.md` | Patch ledger table | 6 |

## Review Focus

1. **Guard-boundary completeness.** Task 5 must leave `qwen35_graph_weights_supported`, `qwen4_graph_linear`'s qwen35 branch, `qwen35_graph_attention`, `qwen35_graph_stage_inputs`, `qwen35_graph_forward_tokens` and the qwen35 dispatch in `qwen4_graph_forward_tokens` backend-neutral. Only verify mode, verify allocation, the DFlash capture/drafter helpers, the verify and draft helpers after the forward (Block C), and `ds4_engine_verify_rows()` stay inside `#if defined(__APPLE__)`. `ds4_gpu_qwen35_set_verify_rows` is Metal-only, so any unguarded call breaks the CUDA link. Unguarding the whole region, or leaving the forward guarded, both fail this: the first compiles Metal-only code on CUDA, the second means CUDA never reaches the qwen35 graph.
2. **Dispatch-layer coverage.** Types 13 and 14 must be registered in every layer `ds4_gpu_qwen4_dense_mm_tensor` can select: `matvec_dispatch` (`T <= 8`, the serial decode path), `matrix_dispatch` (`QWEN_TC` and the non-tensor-core `QWEN_MM`), and `dense_blas` (`QWEN_UNPACK`, `T >= 32`). A gap surfaces only at one `T` range, which is why the test sweeps `T`.
3. **Independent references.** The quant test must decode stored bytes with its own arithmetic. Calling the production `value<TYPE>` helper would make the test restate the implementation.
4. **Shape and refusal invariants.** `row_bytes` keeps the `n % 256 ? 0 : …` guard, so a non-multiple-of-256 `K` is refused instead of truncated. `tensor_type_is_qwen35_dense` keeps accepting Q4_K and Q6_K; only Q5_K is refused. Every op validates bounds, overflow and finite constants before launching and leaves outputs unchanged on refusal.
5. **Diff hygiene.** No captured logs, `.o` files, absolute Nix paths, or test binaries in any patch; `.gitignore` entries match the new targets.

---

### Task 1: Materialise the scratch tree and confirm the starting state

**Files:**
- Modify (scratch only): `.ds4/tree` (gitignored)

**Interfaces:**
- Produces: `.ds4/tree` at 11 commits past the pin (`3 common + 8 qwen35`) on branch `ds4/model/qwen35`, clean status, and the scratch range recorded in `.ds4/tree/.git/ds4-state`.

- [ ] **Step 1: Sync the qwen35 target**

Run: `ds4-sync --model qwen35` (inside `devenv shell`; the sources are `tools/ds4-*.sh`)
Expected: exit 0; `.ds4/tree/.git` exists; state records target `qwen35`.

- [ ] **Step 2: Record the baseline**

```bash
git -C .ds4/tree rev-list --count 5379c1c9ac315f1540371b06a3db88491d4059ff..HEAD
git -C .ds4/tree status --porcelain
```
Expected: `11` and empty status.

- [ ] **Step 3: Confirm the pin's ldmatrix state**

```bash
for pat in m8n8.x4.shared m8n8.x2.shared m8n8.x2.trans.shared; do
  git -C .ds4/cache show 5379c1c:ds4_cuda.cu | grep -c "$pat"
done
```
Expected: `1`, `1`, `1`.

- [ ] **Step 4: Confirm the contract and the red state**

```bash
grep -c "ds4_gpu_qwen35_gdn_out_tensor\|ds4_gpu_qwen35_attn_prep_tensor\|ds4_gpu_qwen35_attn_fa_tensor" .ds4/tree/ds4_gpu.h
grep -c "ds4_gpu_qwen35_gdn_out_tensor" .ds4/tree/ds4_cuda.cu .ds4/tree/ds4_qwen4_cuda.cuh
```
Expected: `3` declarations in the header, `0` definitions in the CUDA sources. That absence is the red state for Tasks 3 and 4.

---

### Task 2: Add Q6_K products to the shared Qwen CUDA path

**Files:**
- Modify: `.ds4/tree/ds4_qwen4_cuda.cuh` (row bytes, `value<TYPE>`, `matvec_dispatch`, `matrix_dispatch`, `dense_blas`)
- Create: `.ds4/tree/tests/qwen35_cuda_test.c`, `.ds4/tree/tests/qwen35_cuda_test.h`
- Create: `.ds4/tree/tests/test_qwen35_cuda_quant.c`
- Modify: `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`

**Interfaces:**
- Consumes: `ds4_gpu_tensor_alloc`, `ds4_gpu_tensor_view`, `ds4_gpu_tensor_write`, `ds4_gpu_tensor_read`, and `ds4_gpu_qwen4_dense_mm_tensor`.
- Produces: `row_bytes(14) = n % 256 ? 0 : n/256*210`; `value<14>` and `unpack<14>`; type-14 registration in `matvec_dispatch`, `matrix_dispatch` (`QWEN_TC` and `QWEN_MM`) and `dense_blas` (`QWEN_UNPACK`); make target `test-qwen35-cuda-quant`.

- [ ] **Step 1: Write the failing test**

`tests/test_qwen35_cuda_quant.c` decodes Q6_K with its own arithmetic and asserts:

- Q6_K block: 128 low nibbles at byte 0, high 2-bit parts at byte 128, int8 scales at byte 192, fp16 `d` at byte 208, `q = (lo | hi << 4) - 32`.
- Product cases for `K ∈ {256, 512}`, `M ∈ {1, 4}` and `T ∈ {1, 8, 9, 17, 32, 33}`, comparing GPU output against the reference within `5e-5`. `T ∈ {1, 8}` exercises `matvec_dispatch`, `T ∈ {9, 17}` exercises `matrix_dispatch`, `T ∈ {32, 33}` exercises `dense_blas` and its `unpack` path.
- One run with `DS4_CUDA_NO_TF32=1`, which forces the plain matrix kernel (`QWEN_MM`) instead of the tensor-core one. cuBLAS has no disable knob, so `T ≥ 32` always exercises `dense_blas` and its `unpack` path.
- Invalid-`K` refusal: `K = 384` must return 0 because `row_bytes` yields 0, and the output must stay unchanged.
- Short-buffer refusal: a view one byte short must return 0 and leave the output unchanged.

- [ ] **Step 2: Add the test harness and the target**

`tests/qwen35_cuda_test.h` exposes `q35_init`, `q35_cleanup`, `q35_require`, `q35_alloc`, `q35_random`, the `q35_arena` bump allocator and `q35_check_tensor`. `tests/qwen35_cuda_test.c` implements them. `Makefile` gains object rules and `test-qwen35-cuda-quant` (mirroring the existing `test-qwen4-cuda` block). `.gitignore` gains `/tests/test_qwen35_cuda_quant`.

- [ ] **Step 3: Run it to see the real red state**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-quant`
Expected: the test fails at `qwen35 test: Q6_K dense mm`, because `row_bytes(14)` is still 0. A missing make rule would mean the target was not added.

- [ ] **Step 4: Implement the decoding**

`row_bytes` gains `case 14: n % 256 ? 0 : n/256*210`, preserving the dimension guard every other K-quant case uses. `value<TYPE>` gains the type-14 Q6_K branch described above, and `unpack<TYPE>` gains type 14 so the cuBLAS path can materialize it. Register type 14 in all four places: `QWEN_MV` in `matvec_dispatch`, `QWEN_TC` and `QWEN_MM` in `matrix_dispatch`, and `QWEN_UNPACK` in `dense_blas`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-quant`
Expected: `all qwen35 CUDA quant tests passed`.

- [ ] **Step 6: Inject the stride fault and restore**

Change the type-14 stride to `176`; the test must fail on the first multi-row case (`K = 256`, `M = 4`, `T = 1`), where a truncated row makes the next row's bytes bleed in. Restore and rerun: passes.

- [ ] **Step 7: Commit**

```bash
git -C .ds4/tree add Makefile .gitignore ds4_qwen4_cuda.cuh tests/qwen35_cuda_test.c tests/qwen35_cuda_test.h tests/test_qwen35_cuda_quant.c
git -C .ds4/tree commit -m "qwen35: dense Q6_K weight products on CUDA"
```

---

### Task 3: Add the dense recurrent SiLU output op

**Files:**
- Create: `.ds4/tree/ds4_qwen35_cuda.cuh`
- Modify: `.ds4/tree/ds4_cuda.cu` (append one include), `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`
- Create: `.ds4/tree/tests/test_qwen35_cuda_recurrent.c`

**Interfaces:**
- Consumes: `qwen4_cuda::sum`, `qwen4_cuda::silu`, `tensor()`, `weight()`, `launched()`, `cuda_decode_stream()` from the shared Qwen CUDA header.
- Produces: `int ds4_gpu_qwen35_gdn_out_tensor(ds4_gpu_tensor *out, const ds4_gpu_tensor *z, const void *map, uint64_t size, uint64_t off, uint32_t T, uint32_t H, uint32_t D, float eps)` — RMS-norm `out` per head slice with the `D`-wide norm weights, then multiply by `silu(z)`.

- [ ] **Step 1: Write the failing test**

`tests/test_qwen35_cuda_recurrent.c`:

- Reference: for each token and head, `out[i] = x[i] / sqrt(mean(x²) + eps) * w[i] * silu(z[i])` computed in double.
- Lengths `{1, 8, 9, 17, 256}`, zero and non-zero norm weights, tolerance `5e-5`.
- Flash-preservation case: the same inputs through the existing `ds4_gpu_qwen4_gdn_out_tensor` must still use `sigmoid(z)`, proving the new op did not change the Qwen4 path.
- Refusals, each leaving `out` unchanged: short `z` view, `off + D*4 - 1` norm weights, `T = 0`, `H = 0`, `D = 127`, `eps = NAN`.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-recurrent`
Expected: link failure, `undefined reference to ds4_gpu_qwen35_gdn_out_tensor`.

- [ ] **Step 3: Implement the op in `ds4_qwen35_cuda.cuh`**

One kernel launch: 32 threads per head slice, `T × H` blocks. Validate `T ≤ 65535`, `D ∈ [32, 128]`, `D % 32 == 0`, finite positive `eps`, and `T * H * D * 4` without overflow, returning 0 before any launch when a check fails.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-recurrent`
Expected: `all qwen35 CUDA recurrent tests passed`.

- [ ] **Step 5: Commit**

```bash
git -C .ds4/tree add ds4_qwen35_cuda.cuh ds4_cuda.cu Makefile .gitignore tests/test_qwen35_cuda_recurrent.c
git -C .ds4/tree commit -m "qwen35: dense recurrent SiLU output on CUDA"
```

---

### Task 4: Add the attention preparation and causal attention ops

**Files:**
- Modify: `.ds4/tree/ds4_qwen35_cuda.cuh`, `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`
- Create: `.ds4/tree/tests/test_qwen35_cuda_attention.c`

**Interfaces:**
- Consumes: the shared `attn_prep` kernel and `ds4_gpu_qwen4_attn_decode_tensor`.
- Produces:
  - `int ds4_gpu_qwen35_attn_prep_tensor(ds4_gpu_tensor *q, ds4_gpu_tensor *gate, ds4_gpu_tensor *kc, ds4_gpu_tensor *vc, const ds4_gpu_tensor *qg, const ds4_gpu_tensor *kp, const ds4_gpu_tensor *vp, const ds4_gpu_tensor *pos3, const void *map, uint64_t size, uint64_t qo, uint64_t ko, uint32_t T, uint32_t H, uint32_t Hkv, uint32_t D, uint32_t nrot, uint32_t pos0, uint32_t cap, float base, float eps)`
  - `int ds4_gpu_qwen35_attn_fa_tensor(ds4_gpu_tensor *out, const ds4_gpu_tensor *q, const ds4_gpu_tensor *gate, const ds4_gpu_tensor *kc, const ds4_gpu_tensor *vc, uint32_t T, uint32_t H, uint32_t Hkv, uint32_t D, uint32_t pos0, float scale)`

- [ ] **Step 1: Write the failing test**

`tests/test_qwen35_cuda_attention.c`:

- Reference in double: RMS-norm `q` and `k` per head, partial NeoX rope over `nrot` dimensions at absolute positions `pos0..pos0+T-1`, half-precision K/V cache, then causal `softmax(q·k/√D) · v` multiplied by `sigmoid(gate)`.
- Shapes `T ∈ {1, 7, 8, 9, 31, 32, 33}`, `pos0 ∈ {0, 13}`, `D = 256`, `nrot = 64`, with `Hkv` dividing `H` and `Hkv < H`.
- Schedules: whole batch, single row, split rows, reset/replay, and prepare-only (prep twice, attend once).
- Routing: the shared decode entry point the adapter delegates to handles every `T`. From `T = 32` it takes the token-tile kernel when `D = 256`, `H/Hkv ≤ 16`, the K/V caches are 16-byte aligned, the architecture supports it, quality mode is off and `DS4_QWEN4_NO_ATTN_MM` is unset; otherwise it takes the per-row kernel. The sweep covers `T = 31` and `32` so both routes run, and one case sets `DS4_QWEN4_NO_ATTN_MM` to force the per-row route.
- Refusals: `pos0 + T > cap`, `nrot > D`, odd `nrot`, short cache view, `scale ≤ 0`, `D = 128`.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-attention`
Expected: link failure for both new symbols.

- [ ] **Step 3: Implement both ops**

`attn_prep` launches the shared `attn_prep` kernel with the indexer arguments null and the qwen35 rope settings. `attn_fa` delegates to `ds4_gpu_qwen4_attn_decode_tensor(out, q, gate, kc, vc, NULL, NULL, NULL, T, H, Hkv, D, pos0, /*use_sel=*/0, /*sel_stride=*/0, scale)`. There is no causal argument: dense causal behaviour is the non-sparse path, and passing a nonzero `use_sel` would select sparse attention and reject the null selection tensors. The test must call the public `ds4_gpu_qwen35_attn_fa_tensor` so a wrong delegation cannot be papered over. Both ops validate shape, overflow, `pos0 + T ≤ cap`, finite `base`/`scale`/`eps` before launching.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-attention`
Expected: `all qwen35 CUDA attention tests passed`.

- [ ] **Step 5: Commit**

```bash
git -C .ds4/tree add ds4_qwen35_cuda.cuh Makefile .gitignore tests/test_qwen35_cuda_attention.c
git -C .ds4/tree commit -m "qwen35: dense preparation and causal attention on CUDA"
```

---

### Task 5: Enable the ordinary dense graph on CUDA

**Execution notes** (from the completed Tasks 2–4 baseline at the 11-commit pin):

- `ds4_cuda.o` must list `ds4_qwen35_cuda.cuh` among its prerequisites. Without that line a header edit leaves a stale object file and a fault injection silently passes.
- Half caches cannot be compared bitwise to a double reference: one ULP of half, plus the float-versus-double difference in the norm and rope intermediates, moves the last bit. Compare them at `2e-3`.
- Feed the attention check with the q, gate and cache halves the device wrote, after checking them separately against the reference. Otherwise a prep rounding difference leaks into the attention assertion.
- Refusal tests must seed the output tensor with a sentinel; a freshly allocated CUDA tensor is uninitialized, so "unchanged" cannot mean "zero".

**Files:**
- Modify: `.ds4/tree/ds4.c` — `qwen35_graph_weights_supported`, `qwen4_graph_linear`, `qwen35_graph_attention`, the `qwen35_graph_verify_*` boundary, `qwen35_graph_stage_inputs`, `qwen35_graph_forward_tokens`, `qwen4_graph_forward_tokens`
- Create: `.ds4/tree/tests/test_qwen35_host.c`
- Create: `.ds4/tree/tests/test_qwen35_graph.c`
- Modify: `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: make targets `test-qwen35-host` and `test-qwen35-graph`; a CUDA build in which `qwen4_graph_forward_tokens` reaches the qwen35 graph.

**Guard map for Step 5** (measured at the 14-commit tree):

- `ds4.c` has no `int main`, and eight existing tests already `#include "../ds4.c"`, so the host test can reach the statics that way.
- `g_ds4_shape` is the runtime shape; `DS4_SHAPE_QWEN35` is its qwen35 initializer. `ds4_qwen4_layer_is_linear(il)` reads `n_full_attn_interval` and `n_nextn_predict`, so the test must set both before checking per-layer verdicts.
- `qwen35_graph_dense_ok` (ds4.c:59437) accepts `qwen4_graph_dense_ok` types plus Q4_K and Q6_K, and requires `dim[0] % 256 == 0` for those two. `qwen4_graph_dense_ok` accepts Q8_0, F16, F32, BF16 and Q4_0.
- The single `#if defined(__APPLE__)` block that blocks CUDA runs from just above `qwen35_graph_attention` to just above `qwen4_graph_forward_tokens`. Member order inside it: `qwen35_graph_attention`, `qwen35_graph_verify_mode`, `qwen35_graph_verify_alloc`, `qwen35_graph_stage_inputs`, `qwen35_dflash_capture`, `qwen35_dflash_capture_begin`, `qwen35_dflash_capture_end`, `qwen35_graph_forward_tokens`, `qwen35_graph_verify`, `qwen35_graph_commit`, `qwen35_dflash_rows`, `qwen35_dflash_draft`.
- Two smaller Apple guards also matter: the qwen35 branch in `qwen4_graph_linear`, and the qwen35 dispatch inside `qwen4_graph_forward_tokens`.
- `DS4_HAS_QWEN4_GPU` (ds4.c:59242 onward) already encloses the whole graph, so the neutral functions are compiled on every GPU build and only need symbols from the selected backend.

- [ ] **Step 1: Create the host test**

`tests/test_qwen35_host.c` is a new file. It includes `../ds4.c` so the statics are reachable, opens no device and no model, and asserts:

- a dense qwen35 layout is accepted by `qwen35_graph_weights_supported` on either backend;
- the string `dense qwen35 runs on the Metal graph only` no longer exists in the translation unit;
- Q6_K dense tensors are accepted (`output.weight` is Q6_K and two tensors per layer are Q6_K), and Q5_K is refused while D1 holds;
- under `__APPLE__` only, the existing verify-mode verdict cases still hold.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-host`
Expected: no rule to make target, because neither the target nor the file exists yet.

- [ ] **Step 3: Add both test targets**

`Makefile` gains `test-qwen35-host` and `test-qwen35-oracle`; `.gitignore` gains `/tests/test_qwen35_host` and `/tests/test_qwen35_oracle`. The oracle cannot be called `test-qwen35-graph`: that target already exists and drives `tests/test_qwen4_kernels` with `DS4_TEST_QWEN35_GRAPH_ONLY=1` on Metal.

- [ ] **Step 4: Run the host test to see the real red state**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-host`
Expected: failure reporting `dense qwen35 runs on the Metal graph only`.

- [ ] **Step 5: Restructure the guards**

The qwen35 region currently sits in one `#if defined(__APPLE__)` block that opens before `qwen35_graph_attention` and closes before `qwen4_graph_forward_tokens`. Split it into three Apple blocks with neutral functions between them. Unguarding the whole region and leaving the forward inside it both fail Review Focus 1.

1. `qwen35_graph_weights_supported` — delete the `#if !defined(__APPLE__) … return false; #else` wrapper and its `#endif`; keep the layout validation for both backends.
2. `qwen4_graph_linear` — move the qwen35 `ds4_gpu_qwen35_gdn_out_tensor` branch out of `#if defined(__APPLE__)` so both backends dispatch it.
3. `qwen35_graph_attention` — keep the preparation call shared and wrap only the verify-mode selection and the `attn_slot` use.
4. **Block A** — `#if defined(__APPLE__)` around the verify helpers from `qwen35_graph_verify_mode` to `qwen35_graph_verify_alloc`, closed before `qwen35_graph_stage_inputs` so staging is neutral.
5. **Block B** — `#if defined(__APPLE__)` around the DFlash capture helpers (`qwen35_dflash_capture_begin`, `qwen35_dflash_capture`, `qwen35_dflash_capture_end`), closed before `qwen35_graph_forward_tokens`.
6. `qwen35_graph_forward_tokens` — guard four call sites inside the body: `qwen35_dflash_capture_begin`, the per-layer `qwen35_dflash_capture`, both `ds4_gpu_qwen35_set_verify_rows` calls, and `qwen35_dflash_capture_end`. `ds4_gpu_qwen35_set_verify_rows` is defined only in `ds4_metal.m`, so an unguarded call breaks the CUDA link. The verify-mode probe and `qwen35_graph_verify_alloc` become Apple-only; the non-Apple branch sets `verify = DS4_QWEN35_VERIFY_OFF` and `g->qwen35_verify_now = DS4_QWEN35_VERIFY_OFF`. The ordinary logits read stays neutral.
7. **Block C** — `#if defined(__APPLE__)` after the forward, around `qwen35_graph_verify`, `qwen35_graph_commit`, `qwen35_dflash_rows` and `qwen35_dflash_draft`, closed before `qwen4_graph_forward_tokens`.
8. `qwen4_graph_forward_tokens` — the `ds4_model_is_qwen35()` dispatch must compile and run on both backends, with `all_rows` behaviour unchanged.

Leave `ds4_engine_verify_rows()` untouched: it must still return `8` only under `DS4_HAS_QWEN4_METAL` on Metal.

- [x] **Step 6: Add the numerical oracle**

`tests/test_qwen35_graph.c` builds a small dense qwen35 model in memory: two layers, F32 tensors, `head_dim = 256` (Task 4 accepts no other size), `n_head = 2`, `n_head_kv = 1`, `n_embd = 512`, `vocab = 32`, and `full_attention_interval = 2`. Interval 2 makes layer 1 full attention and layer 0 linear; interval 4 would make both layers linear and leave Task 4's ops and its guard edits unexercised. The dims live in `g_ds4_shape`, so they are runtime values and no GGUF or loader is involved. Run `qwen4_graph_forward_tokens` for one token and compare the logits against a double-precision reference implementing the documented layer order. Assert `max_abs_err < 1e-3` and an identical repeat run. On a build without a GPU, skip with a printed reason. A graph wired to the wrong model path fails this test; determinism alone would not.

**As executed (`tests/test_qwen35_oracle.c`, `test-qwen35-oracle`).** Three cases
run against the reference: `full_attention_interval = 1` (both layers attention,
so a failure cannot be confused with the recurrent mixer), and `interval = 2`
(linear layer 0, attention layer 1) once through the fused decode front and once
through `DS4_QWEN4_NO_FUSE`'s plain ops. One token at position 0 keeps the
attention contract small: with a single cached key the softmax is 1, so a head's
output is its value rounded to the half cache times `sigmoid(gate)`; rope and the
q/k norms belong to Task 4's suite. The reference does not read the alpha
projection, because the decay multiplies a zero state and cannot move these
logits.

Two traps, both found by running it:

- **Gamma vectors must not be scaled like matrices.** Generating every tensor at
  `1/sqrt(width)` shrinks each normalisation by `sqrt(width)`, the residual
  stream decays geometrically and the logits land near `1e-2`, where a `1e-3`
  absolute bound stops discriminating: an injected `sigmoid` for `silu` in the
  gated output norm moved them by only `1.06e-04`. With the gammas centred on 1
  the same injection moves a logit from `1.30` to `-0.09`.
- **The oracle must be shown to fail.** Injections used: `silu(z)` -> `sigmoid(z)`
  in `qwen35_cuda::gdn_out` (fails at `1.40`, while the attention-only case stays
  at `3.2e-06`, which is the coverage split working) and the FFN normalisation
  reading `attn_norm` (fails at `0.24`). Both were reverted before the commit.

- [ ] **Step 7: Run both tests to verify they pass**

Run: `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-host test-qwen35-graph`
Expected: both pass. The graph test must report that the qwen35 path ran, not the qwen4 path.

- [ ] **Step 8: Commit**

```bash
git -C .ds4/tree add ds4.c Makefile .gitignore tests/test_qwen35_host.c tests/test_qwen35_oracle.c
git -C .ds4/tree commit -m "qwen35: the ordinary dense graph on CUDA"
```

---

### Task 6: Export the patches and prove the series reconstructs

**Files:**
- Create: `patches/qwen35/0009-*.patch` … `0012-*.patch`
- Modify: `docs/specs/2026-10-24-ds4-patch-series-design.md:44-51`

- [x] **Step 1: Export**

Run: `ds4-export`
Expected: exit 0. A dirty-tree refusal means a task left work uncommitted; fix that, do not pass `--force`.

Here the first refusal was the export's own output: a successful `ds4-export`
leaves `patches/qwen35` modified, so a second run sees a dirty directory. The fix
is to discard that output with `git checkout -- patches/qwen35 && git clean -fdq
patches/qwen35` and export again, never `--force`.

- [x] **Step 2: Prove the existing series is untouched**

```bash
git status --porcelain patches/qwen35
git diff --stat -- 'patches/qwen35/000[1-8]-*.patch'
```
Expected: only `??` entries for the new files; the diff is empty.

It cannot be empty when the series grows: `git format-patch` rewrites `From
<sha>` in every patch and `[PATCH n/8]` becomes `[PATCH 0n/13]`. The check that
means something is that no other line changes:

```bash
git diff -U0 -- 'patches/qwen35/000[1-8]-*.patch' | grep -E '^[-+][^-+]' \
  | grep -vE '^[-+](From [0-9a-f]{40} Mon Sep 17|Subject: \[PATCH )'
```
Expected: `Subject: [PATCH 1/8]` … lines only for the pre-extension numbering.

- [x] **Step 3: Inspect a new patch**

Run: `sed -n '1,20p' patches/qwen35/0009-*.patch`
Expected: `From <sha>`, `Subject: [PATCH n/N] qwen35: …`, body, then the three trailers and a diffstat.

- [x] **Step 4: Reconstruct from a pristine pin**

Run: `ds4-check --model qwen35`
Expected: exit 0.

- [x] **Step 5: Update the ledger table**

Add four rows to the spec's patch table with the new subjects and `not offered, fork only`.

- [x] **Step 6: Run the full check and commit**

```bash
nix flake check --accept-flake-config --print-build-logs
git add patches/qwen35 docs/specs/2026-10-24-ds4-patch-series-design.md docs/plans/2026-11-09-qwen35-cuda-dense-path.md
git commit -m "qwen35: add the dense serial CUDA path to the patch series"
```

---

**As executed.** Five patches, not the four this plan predicted: Task 5 became
two commits, so `0009`-`0013` extend the series. The first export shipped them
without the mandatory `Upstream:` / `Retire-when:` / `Carried-commits:` trailers
because the commits were authored without them; the five commits were reworded
with `git rebase -i` and re-exported. `ds4-check --model qwen35` exits 0, and
`diff` over the thirteen touched files between `.ds4/check/qwen35` and
`.ds4/tree` reports no differences, with the reconstructed `ds4.c` holding the
neutral graph region and none of the old Metal-only verdict. The series was exported a second time after the oracle
gained the batch-versus-serial case, so `0013` carries it; the exported tip is
`10c8e748` and `ds4-state` records it.

### Task 7 (done): Adopt or park

- [x] **Step 1:** On a macOS host, materialise and build the patched tree, then run the Metal suites.
- [x] **Step 2:** Run the model-backed gate against a dense qwen35 GGUF.
- [x] **Step 3:** Mark `qwen35/0009`-`0013` adopted in the spec ledger and record the result here.

**Recorded result, 2026-11-12.** On an Apple M4 Max, `ds4-check --model qwen35
--build`, `make -C .ds4/tree test-qwen4-kernels` and `DS4_TEST_MODEL=
Qwen3.8-27B-Q4_K_M.gguf bash tests/ds4_e2e_test.sh` all pass. The guard split
kept verify, DFlash and the drafter Apple-only and left the Metal path working,
which is the property this task existed to check; `qwen35/0009`-`0013` are adopted
in `docs/specs/2026-10-24-ds4-patch-series-design.md` §2.1.

### Task 8: CUDA build path and model-level evidence

**Files:**
- Modify: `tools/ds4-check.sh` (backend selection), or the ds4-py invocation it uses

- [x] **Step 1:** Make the build backend explicit: `--backend NAME`, with `DS4_CHECK_BACKEND` as the environment default and `metal`/`cpu` unchanged as the defaults, so no existing build flow moves; do not add a local build file.
- [x] **Step 2:** Build with `CUDA_ARCH=sm_86` and run `test-qwen35-cuda-quant`, `-recurrent`, `-attention`, and `test-qwen35-host`.
- [x] **Step 3 (optional):** Run the three CUDA tests under `compute-sanitizer --tool memcheck`; zero errors required.
- [x] **Step 4:** Load the pinned `Qwen3.8-27B-Q4_K_M.gguf` at `ctx=8192` and decode two prompts twice. The 27B carries no Q5_K, so an unsupported-dense-type error here means a real gap in Task 2, not a reason to revisit **D1**.
- [x] **Step 5:** Add the batch-versus-serial check: a prompt of 9 tokens must give the same logits at its last row as a single-token decode at that position. This is the cheapest detector for a missing dispatch layer.
- [~] **Step 6:** Record evidence per **D2**: the Task 5 oracle result, batch-versus-serial agreement, finite logits, identical token sequence across repeats, correct terminal reason, metrics identities. Do not record repeatability alone as a pass.

---

**As executed for Steps 1 and 2.** The first attempt inferred `cuda` from `nvcc`
on `PATH`, which retargeted every target's build and made an unrelated flow
depend on what happened to be installed. Review rejected it; the backend is now
`--backend NAME` or `DS4_CHECK_BACKEND`, and `nvcc` on `PATH` selects nothing.
`ds4-check --model qwen35 --build --backend cuda` inside the CUDA devenv with
`CUDA_ARCH=sm_86` reconstructed the series from a pristine pin and linked
`libds4.so` with `nvcc -arch=sm_86`, exit 0. Invoking it needs the venv on `PATH`
(`uv run --frozen bash tools/ds4-check.sh --build`) or an external ds4-py
checkout, as the README's build section describes; the devenv shell alone does
not put `ds4py` there.

**As executed for Step 3.** `compute-sanitizer` is in the store but not on the
devenv PATH, so it was invoked from `cuda-merged-12.9` directly. `--tool memcheck`
reported `0 errors` for `test_qwen35_cuda_quant`, `-recurrent` and `-attention`,
each exit 0. `test_qwen35_host` passes under it too, then exits 255 because it
makes no CUDA call to instrument; it is not one of the three suites this step
covers.

**As executed for Step 5.** The oracle gained a fourth case: nine tokens in one
forward against the same nine decoded one at a time, which is nine separate
one-token forwards, so every recurrent state transition is the serial one. (The
first version ran an eight-token prefix and then one step, which review caught:
it did not exercise repeated one-token transitions. The measured difference did
not move, `1.538e-05`, because it comes from the last row's prompt-versus-decode
kernel pair, not from the schedule.) The synthetic model needs no weights. Measured `max |batch - serial| = 1.538e-05`. It is a real
detector, not a tautology: making the batch tail read the row before the last
trips it at `1.6` while the three reference cases stay green, because they all
run one token. A second injection that dropped `dt_bias` from the decay passed
at `2.6e-05`: the gated output norm renormalises each head, so this synthetic
model is weakly sensitive to decay, and Step 4's model-level agreement remains
the check for that.

**As executed for Step 4.** `Qwen3.8-27B-Q4_K_M.gguf` (15.66 GiB) through the
tree's own `ds4` binary:

```
ds4 -m Qwen3.8-27B-Q4_K_M.gguf --cuda -c 8192 -p "The capital of France is" \
    -n 24 --temp 0 --seed 1
```

`CUDA backend initialized on NVIDIA GeForce RTX 3090 (sm_86)`, planned memory
`17.24 GiB` = resident model `15.65` + buffers `1.09` + KV `0.50`. The run
answered `Paris` after a 63-token prompt, prefill `31.25 t/s`, generation
`0.48 t/s`. Two prompts each decoded twice at `temp 0, seed 1, -n 16` produced
byte-identical streams (`sha256` `74fc3c65c80b` and `2984507e565a`). Generation
at `0.48 t/s` is slow enough to deserve its own look: the serial decode path for
this model's Q4_K/Q6_K mix is the suspect, and nothing here claims it is
optimised.

**Step 6 evidence, per D2.** Measured: the Task 5 oracle (four cases, `3.2e-06` to
`3.6e-05`), batch-versus-serial on the synthetic graph (`1.5e-05`), finite logits,
identical token sequences across repeats, and the model's planned-memory and
throughput figures. Not measured, and not claimed: the engine's terminal reason
and its metrics identities (the `ds4` CLI prints neither), and model-level
batch-versus-serial, because no CLI path exposes the last row's logits. The
synthetic graph covers the wiring; the 27B run covers load, decode and
reproducibility.

## Verification Matrix

| Claim | Command | Expected |
| --- | --- | --- |
| Baseline series applies | `git -C .ds4/tree rev-list --count 0674e31d..HEAD` | `5`, and `ds4-state` records `EXPORTED_HEAD` at that tip |
| Quant types decode correctly | `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-quant` | pass |
| Recurrent op matches reference | `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-recurrent` | pass |
| Attention matches reference | `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-attention` | pass |
| Graph accepts the model | `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-host` | pass |
| Graph is wired correctly | `make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-oracle` | logits within `1e-3` of the reference |
| Batch and serial agree | same target | a 9-token forward matches nine single-token forwards at the last row |
| Metal verify still gated | `grep -c "DS4_HAS_QWEN4_METAL" .ds4/tree/ds4.c` | unchanged from baseline |
| Existing patches unchanged | `git diff -U0 -- 'patches/qwen35/000[1-8]-*.patch'` | only `From <sha>` and the `[PATCH n/13]` counter differ |
| Series reconstructs | `ds4-check --model qwen35` | exit 0 |
| Repo healthy | `uv run --frozen prek run --all-files` and `bash tests/ds4_tools_test.sh` | exit 0, 49 passed |

## Review handoff

**On any host (Linux with the CUDA toolchain):**

```bash
uv run --frozen prek run --all-files            # 23 hooks
bash tests/ds4_tools_test.sh                    # 49 shell tests
ds4-check --model qwen35                        # the thirteen patches reconstruct
./tools/ds4-cuda.sh make -C .ds4/tree CUDA_ARCH=sm_86 \
    test-qwen35-cuda-quant test-qwen35-cuda-recurrent \
    test-qwen35-cuda-attention test-qwen35-host test-qwen35-oracle
```

The CUDA toolchain is behind `DS4_CUDA=1`; `tools/ds4-cuda.sh <command>` sets it
and enters the devenv.

**On macOS: done, 2026-11-12.** `ds4-check --build`, `test-qwen4-kernels` and the
model-backed e2e gate pass on an Apple M4 Max, so the guard split did not disturb
the Metal paths. The five patches are adopted; see Task 7 for the record.

**Known limits, stated so they are not mistaken for results:**

- Generation on the 3090 runs at `0.48 t/s`. Correctness is pinned by the oracle;
  speed is not addressed anywhere in this branch.
- Model-level batch-versus-serial agreement and the engine's terminal reason have
  no CLI path here, so Task 8 Step 6 records them as unmeasured rather than
  passing.
- `qwen35/0009`-`0013` are adopted on the macOS evidence recorded in Task 7.

## PR review follow-ups

Review on PR #24 raised five findings and one performance question. What changed:

| Finding | Response |
| --- | --- |
| `ds4-check` retargeted every build when `nvcc` existed | Backend is `--backend NAME` / `DS4_CHECK_BACKEND`; defaults stay metal/cpu; a shell test asserts `nvcc` on `PATH` selects nothing |
| Platform branches scattered through the dense graph | Attention keeps one ordinary prompt/decode flow with only the verify override guarded; five helpers (`verify_select`, `verify_rows`, `dflash_begin`, `dflash_layer`, `dflash_end`) absorb the rest, so the forward has no `#if` |
| The batch-versus-serial case ran 8+1, not nine serial steps | Nine one-token forwards; the measurement is unchanged at `1.538e-05` because it comes from the kernel pair, not the schedule |
| `tools/ds4-cuda.sh` treated any ambient CUDA as the pinned toolchain | devenv is entered unless `DS4_CUDA_SHELL` (set by the script) or `DS4_CUDA_AMBIENT` (explicit) marks the shell |
| The host gate diverted `stderr` through temp files | `verdict()` deleted; the predicate is called directly, and the positive assertion already catches the old non-Apple refusal |

Performance: `DS4_CUDA_COPY_MODEL=1` did not change the `0.48 t/s` decode rate —
this build registers the 27B through the multi-tier selective cache, which
deliberately refuses a full-model copy (`ds4.c:72585`, message from
`ds4_cuda.cu:4206`), so the variable is never consulted. The arithmetic still
supports the PCIe diagnosis: one pass over 15.65 GiB at PCIe 4.0 x16 (~25 GB/s)
is about 0.65 s, and a token costs about 2.1 s, while the 3090's compute time for
27B at one token is roughly 2 ms. Finding the knob that selects the plain copy
path is follow-up work.

## Performance: device-resident weights (follow-up, blocking for a non-demo use)

Decode runs at `0.48 t/s` on the 3090. That is not a tuning gap, and it is not
`DS4_CUDA_COPY_MODEL` either. What was measured:

| Probe | Result |
| --- | --- |
| Peak VRAM during a run (`nvidia-smi`) | **5.7 GiB** of 24 GB, GPU utilization 100% |
| `DS4_CUDA_COPY_MODEL=1` | no change: `0.49 t/s`, still `(no-copy) registered` |
| `--gpu-vram 22` | no change: `0.52 t/s` |
| `engine_install_gpu_placement`, `engine_install_per_device_caches` | never reached from the CLI generation path (temporary `fprintf` markers, since removed) |
| Graph weight access | `qwen4_graph_gemv(..., m->map, m->size, offset)`: the host model map |

So the dense qwen35 CUDA graph has no device-resident weights path at all. It was
designed where host and device memory are the same memory; on CUDA every weight
byte crosses PCIe on every step. At ~25 GB/s a single pass over 15.65 GiB costs
~0.65 s, and a token costs ~2.1 s.

**The work this implies.** Put the weights in a device slab and resolve graph
weights from it: the multi-tier path already has the mechanism
(`ds4_gpu_device_cache_tensors` allocates the slab, checks free VRAM, and maps the
ranges), and the dense graph needs to consume it instead of the host map. Then
decode is bounded by VRAM bandwidth rather than PCIe.

**Acceptance bar, measured the same way as the rest of this plan:**

1. Peak VRAM ≈ model + context (≈17 GiB for the 27B), not 5.7 GiB.
2. Decode at least 10x today's figure on the same prompt and settings.
3. Oracle and host-gate results unchanged; `compute-sanitizer` still 0 errors.
4. The host-map path still works where no slab is installed, so the model-free
   suites keep running without a device.

This is deliberately not in this branch: it changes how the hot kernels reach
their weights, and the correctness PR is worth merging on its own evidence.

## Risks and rollback

- **Quant stride error.** Silent wrong output. Mitigation: Task 2 Step 6 injects the fault and requires the test to fail first; rollback is discarding the commit in `.ds4/tree` and re-exporting.
- **Attention kernel reuse hides a semantics gap.** The qwen4 decode kernel must not silently apply a sigmoid gate where qwen35 needs silu. Mitigation: Task 3's Flash-preservation case and Task 4's reference comparison; rollback is the same commit-level reset.
- **Guard leakage compiles Metal-only code on CUDA.** Mitigation: Task 5 Step 3 and the Review Focus item; verification is a CUDA build plus `grep` on the guarded regions.
- **Export rewrites the whole directory.** Mitigation: Task 6 Step 2's empty diff is a hard gate; rollback is `git checkout -- patches/qwen35` then `ds4-sync`.
- **Adoption without Metal evidence.** The patches stay carried and unadopted (Task 7). Nothing here claims the path is correct on Metal; only that it is reproducible and reference-checked on CUDA.

## Self-Review

- Spec coverage: L54 trailers (Task 6), L83-86 anti-goals (constraints, Tasks 2–5, Task 8), L178 ordering (single directory constraint). No spec section is left without a task.
- Step scan: each step names one command or one concrete edit and its expected result. Refusal lists are explicit so no step says "handle invalid input".
- Type consistency: the three op signatures match `ds4_gpu.h` declarations exactly; type codes 13/14 and their strides are stated once in Task 2 and reused.
- Review Focus: guard-boundary completeness (Task 5 Step 5's seven named edits), dispatch-layer coverage (Task 2's `T` sweep), independent references (Task 2's own decoder), shape and refusal invariants (Task 2 invalid-`K`, Task 3 refusals), diff hygiene (Task 6's empty diff gate).
- Proportion: no function bodies; signatures, assertions and expected outputs only.
