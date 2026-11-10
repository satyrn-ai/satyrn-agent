# Qwen35 Dense CUDA Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dense serial qwen35 decode path to the CUDA build as four new patches in `patches/qwen35/`, each proven by an independent reference test.

**Architecture:** The neutral op contract already exists — `ds4_gpu.h` declares `ds4_gpu_qwen35_gdn_out_tensor`, `ds4_gpu_qwen35_attn_prep_tensor` and `ds4_gpu_qwen35_attn_fa_tensor`, and the Metal backend implements them. This plan implements the same symbols for CUDA in a new `ds4_qwen35_cuda.cuh`, extends the existing Qwen CUDA quant dispatch with Q5_K and Q6_K, and replaces the model-support refusal with backend-aware dispatch. Verify, DFlash and the drafter stay Metal-only.

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
- The pin already carries `.shared` on all three `ldmatrix` forms. Do not re-add it.

## Decisions required before execution

- **D1 — Q5_K loader acceptance.** The K-quant product kernels handle Q5_K (type 13) regardless. Accepting a Q5_K *dense tensor at load time* also changes the Metal graph's accepted set, so it is a separate patch and is **deferred** here. Revisit only if the pinned 27B fails to load with an unsupported tensor type (Task 8, Step 4).
- **D2 — Correctness evidence for the model-level run.** A numerical oracle is mandatory: the smallest graph the GPU path accepts is compared against a double-precision reference (Task 5), and the real-model run adds batch-versus-serial agreement (Task 8). Determinism, finite logits and correct terminal reasons are supplementary checks, never the oracle. Token-identical agreement with another implementation stays out of scope.
- **D3 — Metal regression owner.** Task 5 touches shared code. Adoption requires a Metal run by someone with macOS; until then the patches are carried but unadopted.

## File Structure

| Path | Responsibility | Task |
| --- | --- | --- |
| `ds4_qwen35_cuda.cuh` | The three dense qwen35 CUDA ops; thin adapters over existing shared CUDA kernels | 3, 4 |
| `ds4_qwen4_cuda.cuh` | Q5_K/Q6_K row decoding and matrix dispatch for the shared Qwen CUDA path | 2 |
| `ds4_cuda.cu` | One include line at the end of the CUDA translation unit | 3 |
| `ds4.c` | Model-support gate and dense-graph dispatch | 5 |
| `tests/qwen35_cuda_test.{c,h}` | Shared harness: arena, upload, independent CPU quant reference, tolerance checks | 2 |
| `tests/test_qwen35_cuda_quant.c` | Q5_K/Q6_K product tests against an independent decoder | 2 |
| `tests/test_qwen35_cuda_recurrent.c` | Recurrent SiLU output tests, schedules and refusals | 3 |
| `tests/test_qwen35_cuda_attention.c` | Attention preparation and causal attention tests | 4 |
| `tests/test_qwen35_host.c` | New host suite: weight acceptance, refusals, Metal-only verdicts (includes `../ds4.c`) | 5 |
| `tests/test_qwen35_graph.c` | Numerical oracle: tiny graph versus a double-precision reference | 5 |
| `Makefile`, `.gitignore` | Test targets and build products | 2–5 |
| `patches/qwen35/0009-*.patch` … `0012-*.patch` | Generated ledger entries | 6 |
| `docs/specs/2026-10-24-ds4-patch-series-design.md` | Patch ledger table | 6 |

## Review Focus

1. **Guard-boundary completeness.** Task 5 must leave `qwen35_graph_weights_supported`, `qwen4_graph_linear`'s qwen35 branch, `qwen35_graph_attention`, `qwen35_graph_stage_inputs`, `qwen35_graph_forward_tokens` and the qwen35 dispatch in `qwen4_graph_forward_tokens` backend-neutral. Only verify mode, verify allocation, the DFlash capture/drafter helpers and `ds4_engine_verify_rows()` stay inside `#if defined(__APPLE__)`. Unguarding the whole region, or leaving the forward guarded, both fail this: the first compiles Metal-only code on CUDA, the second means CUDA never reaches the qwen35 graph.
2. **Dispatch-layer coverage.** Types 13 and 14 must be registered in every layer `ds4_gpu_qwen4_dense_mm_tensor` can select: `matvec_dispatch` (`T <= 8`, the serial decode path), `matrix_dispatch` (`QWEN_TC` and the non-tensor-core `QWEN_MM`), and `dense_blas` (`QWEN_UNPACK`, `T >= 32`). A gap surfaces only at one `T` range, which is why the test sweeps `T`.
3. **Independent references.** The quant test must decode stored bytes with its own arithmetic. Calling the production `value<TYPE>` helper would make the test restate the implementation.
4. **Shape and refusal invariants.** `row_bytes` keeps the `n % 256 ? 0 : …` guard, so a non-multiple-of-256 `K` is refused instead of truncated. Every op validates bounds, overflow and finite constants before launching and leaves outputs unchanged on refusal.
5. **Diff hygiene.** No captured logs, `.o` files, absolute Nix paths, or test binaries in any patch; `.gitignore` entries match the new targets.

---

### Task 1: Materialise the scratch tree and confirm the starting state

**Files:**
- Modify (scratch only): `.ds4/tree` (gitignored)

**Interfaces:**
- Produces: `.ds4/tree` at 11 commits past the pin (`3 common + 8 qwen35`), with a clean status and the scratch range recorded.

- [ ] **Step 1: Sync the qwen35 target**

Run: `tools/ds4-sync --model qwen35`
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

### Task 2: Add Q5_K and Q6_K products to the shared Qwen CUDA path

**Files:**
- Modify: `.ds4/tree/ds4_qwen4_cuda.cuh` (row bytes, `value<TYPE>`, `matvec_dispatch`, `matrix_dispatch`, `dense_blas`)
- Create: `.ds4/tree/tests/qwen35_cuda_test.c`, `.ds4/tree/tests/qwen35_cuda_test.h`
- Create: `.ds4/tree/tests/test_qwen35_cuda_quant.c`
- Modify: `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`

**Interfaces:**
- Consumes: `ds4_gpu_tensor_alloc`, `ds4_gpu_tensor_view`, `ds4_gpu_tensor_write`, `ds4_gpu_tensor_read`, and `ds4_gpu_qwen4_dense_mm_tensor`.
- Produces: `row_bytes(13) = n % 256 ? 0 : n/256*176`, `row_bytes(14) = n % 256 ? 0 : n/256*210`; `value<13>`/`value<14>` and `unpack<13>`/`unpack<14>`; registration in `matvec_dispatch`, `matrix_dispatch` (`QWEN_TC` and `QWEN_MM`) and `dense_blas` (`QWEN_UNPACK`); make target `test-qwen35-cuda-quant`.

- [ ] **Step 1: Write the failing test**

`tests/test_qwen35_cuda_quant.c` decodes each type with its own arithmetic and asserts:

- Q5_K block: `d` at byte 0, `dmin` at byte 2, 6-bit scales/mins from the 12-byte scale area, low nibbles at byte 48 plus 32-bit high bits at byte 16, `q = low | (high_bit << 4)`.
- Q6_K block: 128 low nibbles at byte 0, high 2-bit parts at byte 128, int8 scales at byte 192, fp16 `d` at byte 208, `q = (lo | hi << 4) - 32`.
- Product cases for `K ∈ {256, 512}`, `M ∈ {1, 4}` and `T ∈ {1, 8, 9, 17, 32, 33}`, comparing GPU output against the reference within `5e-5`. `T ∈ {1, 8}` exercises `matvec_dispatch`, `T ∈ {9, 17}` exercises `matrix_dispatch`, `T ∈ {32, 33}` exercises `dense_blas` and its `unpack` path.
- One run with the cuBLAS and tensor-core layers forced off, so `QWEN_MM` and unquantized fallbacks are covered too; the switch is the existing quality-mode / no-TF32 environment knob.
- Invalid-`K` refusal: `K = 384` must return 0 because `row_bytes` yields 0, and the output must stay unchanged.
- Short-buffer refusal: a view one byte short must return 0 and leave the output unchanged.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree test-qwen35-cuda-quant`
Expected: no rule to make target, because the target does not exist yet.

- [ ] **Step 3: Add the test harness and target**

`tests/qwen35_cuda_test.h` exposes `q35_init`, `q35_cleanup`, `q35_upload`, `q35_check_tensor`, `q35_require` and the shared arena type. `Makefile` gains object rules and `test-qwen35-cuda-quant` (mirroring the existing `test-qwen4-cuda` block). `.gitignore` gains `/tests/test_qwen35_cuda_quant`.

- [ ] **Step 4: Implement the decoding**

`row_bytes` gains `case 13: n % 256 ? 0 : n/256*176` and `case 14: n % 256 ? 0 : n/256*210`, preserving the dimension guard every other K-quant case uses. `value<TYPE>` gains the type-13 Q5_K and type-14 Q6_K branches described above, and `unpack<TYPE>` gains both so the cuBLAS path can materialize them. Register both types in all four places: `QWEN_MV` in `matvec_dispatch`, `QWEN_TC` and `QWEN_MM` in `matrix_dispatch`, and `QWEN_UNPACK` in `dense_blas`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `make -C .ds4/tree test-qwen35-cuda-quant`
Expected: `all qwen35 CUDA quant tests passed`.

- [ ] **Step 6: Inject the stride fault and restore**

Change the type-13 stride to `144`; the test must fail on the first Q5_K case. Restore and rerun: passes.

- [ ] **Step 7: Commit**

```bash
git -C .ds4/tree add Makefile .gitignore ds4_qwen4_cuda.cuh tests/qwen35_cuda_test.c tests/qwen35_cuda_test.h tests/test_qwen35_cuda_quant.c
git -C .ds4/tree commit -m "qwen35: dense Q5_K and Q6_K weight products on CUDA"
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

Run: `make -C .ds4/tree test-qwen35-cuda-recurrent`
Expected: link failure, `undefined reference to ds4_gpu_qwen35_gdn_out_tensor`.

- [ ] **Step 3: Implement the op in `ds4_qwen35_cuda.cuh`**

One kernel launch: 32 threads per head slice, `T × H` blocks. Validate `T ≤ 65535`, `D ∈ [32, 128]`, `D % 32 == 0`, finite positive `eps`, and `T * H * D * 4` without overflow, returning 0 before any launch when a check fails.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make -C .ds4/tree test-qwen35-cuda-recurrent`
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
- Routes: `T ≤ 8` must take the decode kernel and `T > 8` the attention adapter.
- Refusals: `pos0 + T > cap`, `nrot > D`, odd `nrot`, short cache view, `scale ≤ 0`, `D = 128`.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree test-qwen35-cuda-attention`
Expected: link failure for both new symbols.

- [ ] **Step 3: Implement both ops**

`attn_prep` launches the shared `attn_prep` kernel with the indexer arguments null and the qwen35 rope settings. `attn_fa` delegates to `ds4_gpu_qwen4_attn_decode_tensor(out, q, gate, kc, vc, NULL, NULL, NULL, T, H, Hkv, D, pos0, /*use_sel=*/0, /*sel_stride=*/0, scale)`. There is no causal argument: dense causal behaviour is the non-sparse path, and passing a nonzero `use_sel` would select sparse attention and reject the null selection tensors. The test must call the public `ds4_gpu_qwen35_attn_fa_tensor` so a wrong delegation cannot be papered over. Both ops validate shape, overflow, `pos0 + T ≤ cap`, finite `base`/`scale`/`eps` before launching.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make -C .ds4/tree test-qwen35-cuda-attention`
Expected: `all qwen35 CUDA attention tests passed`.

- [ ] **Step 5: Commit**

```bash
git -C .ds4/tree add ds4_qwen35_cuda.cuh Makefile .gitignore tests/test_qwen35_cuda_attention.c
git -C .ds4/tree commit -m "qwen35: dense preparation and causal attention on CUDA"
```

---

### Task 5: Enable the ordinary dense graph on CUDA

**Files:**
- Modify: `.ds4/tree/ds4.c` — `qwen35_graph_weights_supported`, `qwen4_graph_linear`, `qwen35_graph_attention`, the `qwen35_graph_verify_*` boundary, `qwen35_graph_stage_inputs`, `qwen35_graph_forward_tokens`, `qwen4_graph_forward_tokens`
- Create: `.ds4/tree/tests/test_qwen35_host.c`
- Create: `.ds4/tree/tests/test_qwen35_graph.c`
- Modify: `.ds4/tree/Makefile`, `.ds4/tree/.gitignore`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: make targets `test-qwen35-host` and `test-qwen35-graph`; a CUDA build in which `qwen4_graph_forward_tokens` reaches the qwen35 graph.

- [ ] **Step 1: Create the host test**

`tests/test_qwen35_host.c` is a new file. It includes `../ds4.c` so the statics are reachable, opens no device and no model, and asserts:

- a dense qwen35 layout is accepted by `qwen35_graph_weights_supported` on either backend;
- the string `dense qwen35 runs on the Metal graph only` no longer exists in the translation unit;
- Q5_K/Q6_K dense tensors are still refused while D1 is deferred;
- under `__APPLE__` only, the existing verify-mode verdict cases still hold.

- [ ] **Step 2: Run it to verify it fails**

Run: `make -C .ds4/tree test-qwen35-host`
Expected: no rule to make target, because neither the target nor the file exists yet.

- [ ] **Step 3: Add both test targets**

`Makefile` gains `test-qwen35-host` and `test-qwen35-graph`; `.gitignore` gains `/tests/test_qwen35_host` and `/tests/test_qwen35_graph`.

- [ ] **Step 4: Run the host test to see the real red state**

Run: `make -C .ds4/tree test-qwen35-host`
Expected: failure reporting `dense qwen35 runs on the Metal graph only`.

- [ ] **Step 5: Restructure the guards**

Seven edits. Each names the boundary it must end at; unguarding the whole Apple region or leaving the forward inside it both fail Review Focus 1.

1. `qwen35_graph_weights_supported` — delete the `#if !defined(__APPLE__) … return false; #else` wrapper and its `#endif`; keep the layout validation for both backends.
2. `qwen4_graph_linear` — move the qwen35 `ds4_gpu_qwen35_gdn_out_tensor` branch out of `#if defined(__APPLE__)` so both backends dispatch it.
3. `qwen35_graph_attention` — keep the preparation call shared and wrap only the verify-mode selection and the `attn_slot` use.
4. Close the Apple block after the `qwen35_graph_verify_*` helpers, allocation included; `qwen35_graph_stage_inputs` must be neutral.
5. Re-open `#if defined(__APPLE__)` around the DFlash capture and drafter helpers only, ending before `qwen35_graph_forward_tokens`.
6. `qwen35_graph_forward_tokens` — the verify-mode probe and `qwen35_graph_verify_alloc` become Apple-only; the non-Apple branch sets `verify = DS4_QWEN35_VERIFY_OFF`. The ordinary logits read stays neutral; the `qwen35_dflash_capture_end` call is Apple-only.
7. `qwen4_graph_forward_tokens` — the `ds4_model_is_qwen35()` dispatch must compile and run on both backends, with `all_rows` behaviour unchanged.

Leave `ds4_engine_verify_rows()` untouched: it must still return `8` only under `DS4_HAS_QWEN4_METAL` on Metal.

- [ ] **Step 6: Add the numerical oracle**

`tests/test_qwen35_graph.c` constructs the smallest graph the GPU path accepts — two layers, F32 tensors, `D = 64`, `vocab = 32`, no GGUF and no loader — runs `qwen4_graph_forward_tokens` for one token through the built backend, and compares the logits against a double-precision reference implementing the documented layer order. Assert `max_abs_err < 1e-3` and an identical repeat run. On a build without a GPU, skip with a printed reason. If direct construction proves impractical, the fallback oracle is the pinned model with a layer-0 hidden-state comparison against a NumPy recomputation; record which oracle was used in the patch message. A graph wired to the wrong model path fails this test; determinism alone would not.

- [ ] **Step 7: Run both tests to verify they pass**

Run: `make -C .ds4/tree test-qwen35-host test-qwen35-graph`
Expected: both pass. The graph test must report that the qwen35 path ran, not the qwen4 path.

- [ ] **Step 8: Commit**

```bash
git -C .ds4/tree add ds4.c Makefile .gitignore tests/test_qwen35_host.c tests/test_qwen35_graph.c
git -C .ds4/tree commit -m "qwen35: the ordinary dense graph on CUDA"
```

---

### Task 6: Export the patches and prove the series reconstructs

**Files:**
- Create: `patches/qwen35/0009-*.patch` … `0012-*.patch`
- Modify: `docs/specs/2026-10-24-ds4-patch-series-design.md:44-51`

- [ ] **Step 1: Export**

Run: `tools/ds4-export`
Expected: exit 0. A dirty-tree refusal means a task left work uncommitted; fix that, do not pass `--force`.

- [ ] **Step 2: Prove the existing series is untouched**

```bash
git status --porcelain patches/qwen35
git diff --stat -- 'patches/qwen35/000[1-8]-*.patch'
```
Expected: only `??` entries for the new files; the diff is empty.

- [ ] **Step 3: Inspect a new patch**

Run: `sed -n '1,20p' patches/qwen35/0009-*.patch`
Expected: `From <sha>`, `Subject: [PATCH n/N] qwen35: …`, body, then the three trailers and a diffstat.

- [ ] **Step 4: Reconstruct from a pristine pin**

Run: `tools/ds4-check --model qwen35`
Expected: exit 0.

- [ ] **Step 5: Update the ledger table**

Add four rows to the spec's patch table with the new subjects and `not offered, fork only`.

- [ ] **Step 6: Run the full check and commit**

```bash
nix flake check --accept-flake-config --print-build-logs
git add patches/qwen35 docs/specs/2026-10-24-ds4-patch-series-design.md docs/plans/2026-11-09-qwen35-cuda-dense-path.md
git commit -m "qwen35: add the dense serial CUDA path to the patch series"
```

---

### Task 7 (blocked on D3): Adopt or park

- [ ] **Step 1:** Run the Metal live gate on a macOS host against the patched tree; record the result beside the patches.
- [ ] **Step 2:** If Metal passes, mark the four patches adopted in the spec ledger. If not, leave them carried and unadopted and record why.

---

### Task 8 (deferred): CUDA build path and model-level evidence

**Files:**
- Modify: `tools/ds4-check.sh` (backend selection), or the ds4-py invocation it uses

- [ ] **Step 1:** Select `--backend cuda` when `nvcc` is present, falling back to `cpu`; do not add a local build file.
- [ ] **Step 2:** Build with `CUDA_ARCH=sm_86` and run `test-qwen35-cuda-quant`, `-recurrent`, `-attention`, and `test-qwen35-host`.
- [ ] **Step 3 (optional):** Run the three CUDA tests under `compute-sanitizer --tool memcheck`; zero errors required.
- [ ] **Step 4:** Load the pinned `Qwen3.8-27B-Q4_K_M.gguf` at `ctx=8192` and decode two prompts twice. If loading reports an unsupported dense tensor type, that is the trigger to revisit **D1**.
- [ ] **Step 5:** Add the batch-versus-serial check: a prompt of 9 tokens must give the same logits at its last row as a single-token decode at that position. This is the cheapest detector for a missing dispatch layer.
- [ ] **Step 6:** Record evidence per **D2**: the Task 5 oracle result, batch-versus-serial agreement, finite logits, identical token sequence across repeats, correct terminal reason, metrics identities. Do not record repeatability alone as a pass.

---

## Verification Matrix

| Claim | Command | Expected |
| --- | --- | --- |
| Baseline series applies | `git -C .ds4/tree rev-list --count 5379c1c..HEAD` | `11` before, `15` after |
| Quant types decode correctly | `make -C .ds4/tree test-qwen35-cuda-quant` | pass |
| Recurrent op matches reference | `make -C .ds4/tree test-qwen35-cuda-recurrent` | pass |
| Attention matches reference | `make -C .ds4/tree test-qwen35-cuda-attention` | pass |
| Graph accepts the model | `make -C .ds4/tree test-qwen35-host` | pass |
| Graph is wired correctly | `make -C .ds4/tree test-qwen35-graph` | logits within `1e-3` of the reference |
| Metal verify still gated | `grep -c "DS4_HAS_QWEN4_METAL" .ds4/tree/ds4.c` | unchanged from baseline |
| Existing patches unchanged | `git diff --stat -- 'patches/qwen35/000[1-8]-*.patch'` | empty |
| Series reconstructs | `tools/ds4-check --model qwen35` | exit 0 |
| Repo healthy | `nix flake check --accept-flake-config` | exit 0 |

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
