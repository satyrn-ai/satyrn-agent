# Mellum port: open decisions and external dependencies

Status of the items that cannot be closed inside this worktree, written so they can be raised as they stand.

## 1. Exact-prefill diagnostic and fast-path target — resolved: they stay in 0004

Koudai accepted the move on 2026-11-20; spec §4/§9 now put both in 0004. The published-Q8 exact oracle
on the 0003 tree is recorded in `mellum-engine-evidence.md`; the exact graph runs it without the 0004
diagnostic. Preserve the measured tree and any later relocation-equivalence evidence separately.

The spec's §4 table originally put `DS4_MELLUM_EXACT_PREFILL` in patch 0003 and its §9 acceptance for 0003 ran
`DS4_TEST_MELLUM_MODEL="$Q8" make test-mellum-fastpath`. Both shipped in 0004 instead, because:

- the flag exists to disable the tiled/batched thresholds that 0004 introduces (`73544c91`'s diff is written
  against them), so in 0003 it has nothing to disable;
- `test-mellum-fastpath` is the 0004 target; running it at 0003 fails at "no rule to make target".

0003's acceptance is the kernel suite (509 checks at that point), the trace driver's untraced-versus-traced
equality, the rewind cases and the 64-id comparison; 0004 carries the diagnostic, the fast-path target and the
45-check suite. The port's exact prefill is byte-equal to its decode at 2,200 tokens; the reference's diagnostic
disables the same tiled thresholds, so exact-prefill comparisons are exact (see `mellum-engine-evidence.md`).

**Ruling:** Koudai accepted the move on 2026-11-20; spec §4/§9 were amended in #26. The dependency order was
real, not stylistic.

## 2. Koudai and Roché: PR #24 sequencing

Spec §10 says satyrn-agent PR #24 merges before Mellum implementation, and that both owners should be told. The
Mellum engine series 0001–0005 was implemented and exported before #24 merged, against the current qwen35 series
(0001–0008) and the current `tools/ds4-check.sh`.

Consequence: after #24 merges, the rebase must cover the then-current 18-patch qwen35 series and the changed
check script, and the shell suite must be re-run before any boundary result is trusted. The task is Task 17 in
`docs/superpowers/plans/2026-11-16-mellum-support.md`, with the corrected procedure (both ranges in one scratch
repository).

**Question for both:** does #24 land before the Mellum PR opens, and who rebases qwen35 afterwards? The spec
assigns it to Paul and the review to Koudai.

**Resolved:** #24 merged on 2026-11-21 as `eed5c4f`, after Mellum PR #29 opened, and Paul rebased qwen35
in this worktree (Task 17). All eighteen patches now sit on the Mellum tip `f2c40f41` and export from tip
`320627f2`; the boundary checks, the tooling suite (50/50), and the kernel gates pass. The rebase resolved
two semantic conflicts in the qwen35 patches in favour of #24: 0002 renders a system turn's `<tool_call>`
and the `<tool_response>` wrapper as the template's added tokens for every qwen4 shape, and 0004 keeps the
Qwen family's 0.6 / 20 / 0.95 / 0 defaults. That means Mellum no longer narrows Flash Next's rendering
to Mellum alone, and `tests/test_mellum_config.c`'s sibling assertions were updated to match. Koudai's
focused review of those two resolutions is recommended before merge. The approvals do not require a
new design ruling; the missing Make include dependencies and evidence corrections found in the
[2026-11-21 review](2026-11-21-mellum-review.md) are tracked in the plan's engine closure checklist.

## 3. Physical acceptance on 36 / 24 / 16 / 8 GB

Not run. The machine attached to this work is an Apple M5 Max with 128 GiB, which is not the M4 Max 36 GB target
the spec measures, and no 24 GB Air, 16 GB mini or 8 GB machine is reachable from here. The spec's §8 rows require
per-machine Metal limit, planned bytes, peak, swap before/after and n, recorded on the target itself.

What is ready: the ported A/B/B/A runners and (with 0006) `tools/mellum_s4_measure` produce those fields; the
acceptance procedure is Task 20.

## 4. `.inc` files vs inline `ds4.c` — resolved: restore the reference layout

Koudai ruled on 2026-11-20: restore the reference's `ds4_mellum_*.inc` layout before Task 17. Done in this
series: 0001 adds `config`/`plan`, 0002 adds `tokenizer`/`unicode`, 0003 adds `graph_alloc`/`graph`/`test_hooks`,
and 0004–0006 extend the graph and hooks files. This moves about 1,700 lines out of `ds4.c` and matches the
spec's §4 ledger.

The reference's `.inc` layout shrinks the `ds4.c` region the coming qwen35 rebase must resolve, allows a
file-by-file diff against `d2d9338` (the closest thing to Koudai's byte-identity gate), and makes later updates
from the still-moving `ds4-mellum` cheaper. The series now carries `ds4_mellum_config.inc`,
`ds4_mellum_plan.inc`, `ds4_mellum_tokenizer.inc`, `ds4_mellum_graph_alloc.inc`, `ds4_mellum_graph.inc` and
`ds4_mellum_test_hooks.inc`; only `ds4_mellum_unicode.inc` and `ds4_mellum_stream.[ch]` were already separate.

Implementing the ruling also means declaring the includes as Make dependencies: 0001–0003 add
`MELLUM_DS4_INCS` entries at each introducing boundary and name every `ds4.c` consumer, so an
incremental build cannot report "up to date" after an include changes. The regression is
`tests/ds4_series_deps_test.sh`; the review's P1 finding records why the pristine gates missed it.

A second, concrete rebase surface is independent of the `.inc` choice: 0003 wraps
`ds4_gpu_qwen4_attn_decode_tensor` / `ds4_gpu_qwen4_attn_decode_rows_tensor` in static `_impl(..., bool ungated)`
helpers (public signatures unchanged). qwen35 patch 0005 inserts `ds4_gpu_qwen35_attn_verify_tensor` immediately
after the old `_rows_tensor` closing brace as hunk context, so that hunk will conflict even though the callers
still compile. Task 17's cherry-pick procedure resolves it; the rebase owner should expect this function-level
collision in addition to the `ds4.c` region.

## 5. S4 driver slot count — closed

`tests/test_mellum_s4_driver.py` no longer hardcodes Q8's 979 alone: it holds the known counts for both quants
(979 for Q8_0, 1,958 for MXFP4_MOE) and asserts the run's slot count is the one for its quant. No new public API
was added; the test passes on both files (3 tests, OK each).
