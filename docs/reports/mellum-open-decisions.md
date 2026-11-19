# Mellum port: open decisions and external dependencies

Status of the items that cannot be closed inside this worktree, written so they can be raised as they stand.

## 1. Koudai: move the exact-prefill diagnostic and the fast-path target from 0003 to 0004?

The spec's §4 table puts `DS4_MELLUM_EXACT_PREFILL` in patch 0003 and its §9 acceptance for 0003 runs
`DS4_TEST_MELLUM_MODEL="$Q8" make test-mellum-fastpath`. We shipped both in 0004 instead, because:

- the flag exists to disable the tiled/batched thresholds that 0004 introduces (`73544c91`'s diff is written
  against them), so in 0003 it has nothing to disable;
- `test-mellum-fastpath` is the 0004 target; running it at 0003 fails at "no rule to make target".

Current state: 0003's acceptance is the kernel suite (662 checks at that point), the trace driver's
untraced-versus-traced equality, the rewind cases and the 64-id comparison; 0004 carries the diagnostic, the
fast-path target and the 45-check suite. The port's exact prefill is byte-equal to its decode at 2,200 tokens
(the reference's own flag does not disable its attention tiles — see `mellum-engine-evidence.md`).

**Question:** accept the move and amend §4/§9, or restore the flag and target to 0003 with the thresholds they
disable? Recommendation: accept the move; the dependency order is real, not stylistic.

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

## 3. Physical acceptance on 36 / 24 / 16 / 8 GB

Not run. The machine attached to this work is an Apple M5 Max with 128 GiB, which is not the M4 Max 36 GB target
the spec measures, and no 24 GB Air, 16 GB mini or 8 GB machine is reachable from here. The spec's §8 rows require
per-machine Metal limit, planned bytes, peak, swap before/after and n, recorded on the target itself.

What is ready: the ported A/B/B/A runners and (with 0006) `tools/mellum_s4_measure` produce those fields; the
acceptance procedure is Task 20.

## 4. S4 driver slot count — closed

`tests/test_mellum_s4_driver.py` no longer hardcodes 979. The driver now reports `expert_bytes` from a new
`ds4_engine_mellum_expert_bytes` hook, and the smoke test asserts `slots == (6 GiB // expert_bytes)`, which holds
for Q8 (979) and MXFP4 alike. Verified by running the test against both files: 3 tests, OK each.
