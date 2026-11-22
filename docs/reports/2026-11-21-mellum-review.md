# Mellum review and revised delivery plan — 2026-11-21

Reviewed satyrn-agent `862ff0bb46ebd7123d9cccc947b562ccbc9135f8`, published PR #29
head `8ccc4fcb99b1e08dc952f37adb88d2e4ae41cc77`, and main
`eed5c4fe66f867252f457789ef0ee0972b6e89af`. Engine identities:

| Target | Engine commit | Git tree |
| --- | --- | --- |
| Mellum prefix | `f2c40f41c3390026d10fa46a4d329de1f30edfca` | `ca24315387f6e074a5667bd21753d324e1819476` |
| Combined qwen35 prefix | `320627f2d751beea88dbc659292ce4edb52bd826` | `ee45405ca1f9a7e6047d6097fef66ba0b86a6247` |

The engine checkpoint is close, but the proposed “push, CI, merge, then evidence”
sequence misses a reproducible build defect and an outstanding prefix-specific
performance requirement. No engine patches were changed during this review.

## Findings

### P1 — Restoring the include layout omitted its Make dependencies

The six restored `ds4_mellum_*.inc` files are included by `ds4.c`, but their
prerequisites were not carried into the Makefile. For example, the reconstructed
Makefile at lines 818, 884, 1122 and 1129 does not connect the graph/config/tokenizer
includes to `ds4.o`, `ds4_cpu.o`, or the config/tokenizer test objects. The pinned
reference has a `MELLUM_DS4_INCS` dependency group at Makefile lines 79–87.

With otherwise up-to-date objects and controlled timestamps in a temporary
directory, using the exported Makefile and its actual expanded prerequisite lists:

```text
make -n -W ds4_mellum_graph.inc ds4.o
make: 'ds4.o' is up to date.
make -n -W ds4_mellum_config.inc ds4_cpu.o
make: 'ds4_cpu.o' is up to date.
make -n -W ds4_mellum_config.inc tests/test_mellum_config.o
make: 'tests/test_mellum_config.o' is up to date.
make -n -W ds4_mellum_tokenizer.inc tests/test_mellum_tokenizer.o
make: 'tests/test_mellum_tokenizer.o' is up to date.
```

An include-only fix can therefore be absent from an apparently successful
incremental build or test. Pristine builds avoid this problem, which explains why
reconstruction and kernel results do not detect it. Add a regression, restore the
dependencies for every direct `ds4.c` consumer at each introducing prefix, preserve
`all` as the default target, then re-export and validate. This is the concrete code
fix required before calling the branch merge-ready.

### P2 — The streaming ledger changes measured tree IDs without new raw runs

Commit `3c25b22` changes both parity summaries' `current_tree` from `8b8ef87a` to
`ca243153`. Their notes still say the runs were rerun on the `.inc` series, while
the top-level raw run ledger names `ece0d5fe` and its older prefix IDs. The prose
report still explicitly attributes MXFP4's rerun to `8b8ef87a`.

Those measurements need not be discarded. Independently expanding all Mellum
includes in `ds4.c` at `8b8ef87a` and `ca243153` gives identical bytes, SHA-256
`391d3ba992b840d6669c48af69b6df1c10ea1d6c61a9d6ab8b78c2b58ba22c25`.
The tree diff is exactly 274 lines moved between `ds4.c` and the graph include.
This verifies the relocation, but cannot turn an old run into a new one or prove
the later combined qwen35 stack.

Keep `measured_commit/tree` separate from `applicable_export` and the equivalence
proof. Record final combined-stack 3+3 runs per quant with raw 512-token IDs after
the build fix; never update historical measurement identity merely to match HEAD.

### P2 — Task 15's required current-0005 comparison remains unproven

The evidence report's corrected MXFP4 timing is explicitly “at 0006” (4,085/151.99
t/s versus 4,074/152.13). Spec §4/§8 requires the current **0005** export, published
MXFP4, immutable `d2d9338`, n=6 and one machine. A 0006 result does not verify that
the independently consumable 0005 boundary meets its gate. The original plan's
Task 15 status obscured this distinction.

Capture the current-0005 pair and prefix-specific numerical/Q8 non-regression
artifacts. This comparison can run on the M5 Max; it does not depend on access to
the smaller machines. The physical M4 Max n=6 performance row and n=3 32K row are
separate requirements. Koudai's n=1 screen remains supplemental.

### P2 — Full live acceptance is still red, and downstream support is unfinished

The recorded Qwen live suite has 48 passes and one failure: `max_tokens` after
`/switch`. The plan reports the same failure against main's own rebuilt engine.
That supports treating it as a baseline failure; it is not a green live gate or
proof that every Qwen behavior is unchanged. Preserve both build identities and
track the failing acceptance separately. This review did not rerun the full Qwen
live suite or validate CUDA execution on this Mac.

The actual ds4-py dependency repository is `rochecompaan/ds4-py`; the plan named
`satyrn-ai/ds4-py`, whose API returned 404. No Hermes/tool-profile companion PRs
appear in the accessible repository's current PR list. Task 18 still needs those
APIs and a single reviewed dependency commit containing both companions.

Tasks 7/9 also preselected `auto -> pi`, although the spec reserves that decision
for Koudai after 120 measured tasks. The revised plan enables explicit profiles
first and postpones the permanent Mellum default. The plan's task numbers differ
from the spec: plan Task 18 includes spec Tasks 18/19, plan Task 19 is the tool
comparison (spec Task 21), and plan Task 21 is the final gate (spec Task 22).

### P2 — Acceptance records and handoff instructions need reconciliation

The PR body still says “not a merge request”, excludes Task 17, names superseded
trees, and requests design rulings that have already been given. The local plan
also said the specification was unchanged and called completed published-file
checks pending. The decisions report incorrectly said #24 merged before #29
opened. The plan and decisions document were corrected during this review; the
PR body and raw evidence ledger remain work for the closure checklist.

The physical matrix is still open. Koudai owns 36/24/16 GB and Paul owns 8 GB.
Capture no-swap evidence, actual Metal limit, planned bytes and peak, not merely
the driver's JSON. Obtain resident reference IDs for the 16 GB Q8 and 8 GB MXFP4
streaming rows on a larger machine; do not generate those baselines by forcing
resident models into swap on the smaller targets.

## What the approvals change

[Koudai's comment](https://github.com/satyrn-ai/satyrn-agent/pull/29#issuecomment-7028398662)
settles exact-prefill placement in 0004 and requires the reference include layout.
It also explicitly withholds acceptance of Tasks 10–16 pending results. Both
design decisions are now reflected in the spec and implementation.

GitHub currently reports `APPROVED`, `isDraft=true`, and `UNSTABLE` for #29.
Koudai approved `c21b0be`; Roché approved `8ccc4fc`. These reviews do have recorded
commit identities. Main is unprotected, so approval does not enforce freshness of
later changes or CI. The latest published `test` check fails in the CPU-build step;
the local Task 17 result has not been pushed to obtain fresh CI.

[Roché explicitly said](https://github.com/satyrn-ai/satyrn-agent/pull/29#issuecomment-7049111967)
to proceed without waiting for CUDA support. #24 has since merged, and the local
branch already contains its complete 18-patch rebase. Do not schedule another
rebase or reopen the accepted architecture. Notify both owners that Task 17 is
done, and disclose the relocation, both semantic resolutions and the new build
fix. Focused review of those later changes is prudent; GitHub does not impose a
new permission gate. This review did not post comments or notifications.

Approval supports landing a clearly scoped engine checkpoint after correcting
the build defect and validating the pushed head. It does not waive physical
acceptance, choose the tool default, deliver Satyrn controls, or unblock Task 18.

## Revised sequence

1. Add the failing include-dependency regression, fix the Makefile dependencies
   at their introducing boundaries, re-export, and rebuild pristine prefixes.
2. Correct measurement provenance, close current-0005 MXFP4 evidence, and run
   final combined-stack Mellum/Qwen regressions. Track the existing Qwen live
   failure explicitly; keep the physical rows visibly pending until measured.
3. Prepare the accurate PR description, then push without force and require all
   CI checks on that exact head. Obtain focused review of the later changes,
   notify the owners when authorized, make ready, and merge the engine checkpoint.
4. Run physical rows and the generic ds4-py companion handoff independently.
   Do not wait for the merge or every hardware row to prepare that work.
5. After the companions merge, integrate Task 18, run the 120-task comparison,
   record Koudai's default-profile ruling, and complete full product acceptance.

The executable details and owners are in the revised
[implementation plan](../superpowers/plans/2026-11-16-mellum-support.md#engine-closure-before-pushing-pr-29).

## Verification performed in this review

On the actual Mellum worktree, inside the canonical devenv environment:

- All-files prek gate: PASS.
- Portable shell suite: 50 passed, 0 failed.
- Model-free Python suite: 290 passed, 100% line and branch coverage.
- Pristine `ds4-check` reconstruction: PASS for common, Mellum and combined
  qwen35; final trees `ca243153` and `ee45405c` match the exported engine.
- `DS4_TEST_MELLUM_MODEL=... make -C .ds4/tree test-mellum test-mellum-kernels`:
  PASS, including real-model config/chat, 30/30 tokenizer IDs, 56 stream checks,
  4 trace-stream checks and 992 Metal kernel checks.
- The isolated Make dependency reproducer: FAILS the required invalidation in
  all four sampled cases, as described above.
- The 274-line relocation: expanded engine source is byte-identical.
- Final combined-stack published-Q8 oracle: PASS at 29/1,100/2,200 input tokens,
  with 64/64 greedy decode IDs and logits equal to the pinned reference. Exact
  prefill and decode comparisons are byte-equal. Optimized prefill passes the
  configured bounds but is not byte-equal at the longer prompts: at 1,100 tokens,
  63/65 sampled top-1 IDs agree with the reference, with two permitted near-tie
  changes; at 2,200, 65/65 agree and max absolute logit difference is 8.320 (cap
  10). Do not extend older byte-equality claims to this optimized combined path.
- The model used for native checks verifies to published Q8 SHA-256
  `69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f`.

Raw local review artifacts are `/private/tmp/mellum-deep-review-native.log`,
`/private/tmp/mellum-deep-review-oracle.log`, and the reproducer
`/private/tmp/mellum-review-make-deps.py`. Physical memory/performance acceptance,
fresh remote CI, full Qwen live and CUDA execution were not run in this review.
