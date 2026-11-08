---
sessionId: session-261107-173932-2vst
---

# Evidence Record Follow-up

This revision supersedes the unfinished transaction-hardening delivery work. Boundary hardening is complete; failed-branch/cancellation hardening remains stopped by Paul's explicit direction. The next slice is documentation only, following the recommendation to update the evidence record before brainstorming roadmap item 1.

# Requirements

### Outcome
Bring the retained item 0 implementation checkpoint and research note into agreement with completed fake-only work and the reported interruption compatibility gap.

- Preserve the completed boundary-hardening milestone; do not resume stopped cancellation work or implement adapter changes.
- No GPU use, native engine loading, model runs, test execution, dependency changes, commits, or pushes in this slice.
- Reuse existing evidence: the historical 19-test full-suite runs and the later four passing focused fake-worker tests are separate observations. Do not infer a new suite total or claim a fresh full-suite run.
- All four 27B presence checks remain unverified. Fake results establish harness behavior only.
- Reference-app and typed-packet design remain subsequent, separate brainstorm/spec/approval cycles; neither is implemented or designed by this documentation slice.

# Technical Design

### Grounded changes
- In `docs/superpowers/plans/2026-11-07-27b-worker-smoke-test.md`, replace the outdated execution-checkpoint bullets about one read-first boundary with completed same-key boundary replacement, write-first preservation, and unexercised restore when no eligible later write occurs. Keep the original live task checkboxes open where evidence is incomplete. Add the no-GPU-without-explicit-approval constraint and distinguish completed work from stopped cancellation/failed-branch work.
- In `docs/superpowers/research/2026-11-07-27b-worker-smoke-test.md`, preserve the initial rehearsal as historical evidence and add the later focused-test results and boundary-hardening findings. Update remaining-work and risk statements that currently describe boundary replacement and write-first handling as entirely absent; parallel-tool and interruption safety remain unestablished. Preserve the opening `What is measured` / `What is conjecture` and closing `What would falsify this` / `Risks` structure.
- Describe the compatibility gap accurately in both records: `DS4StreamedResponse._get_event_iterator()` marks natural facade exhaustion reconciled, so `_close_round_locked()` returns without reconciliation on that path. Early/interrupted cleanup can proceed through `Session.reconcile_round()` to native `rewind()`. Qwen35 support is unverified, not demonstrated broken; no live failure has been reproduced.
- Link [ds4-py #20](https://github.com/rochecompaan/ds4-py/issues/20), already filed in the preceding work. Do not claim a current maintainer response or resolution: this planning session could not retrieve the issue page.
- Use `.ds4/overnight-domains/item0/probe/worker.py::ProbeModel._open_stream` and `tests/test_fake_worker.py` as implementation references, without modifying or publishing ignored code, scripted solutions, traces, stdout, or patches. Keep Python RNG restoration, FIM/tokenizer checks, live entry points, complete telemetry, and all live verdicts pending.

### Validation
Read the two edited documentation files against the existing source and recorded results. Check that normal completion is not described as always rewinding, interrupted cleanup is not described as proven safe, no fake evidence is promoted to a 27B result, and historical test results are labeled separately. Run only a targeted whitespace check inside `devenv`; do not rerun Python tests or load native libraries.

# Delivery Steps

### ✓ Step 1: Correct the implementation checkpoint and stopped-work status
The retained implementation plan accurately records completed boundary hardening and the interruption blocker.

- Update `docs/superpowers/plans/2026-11-07-27b-worker-smoke-test.md` execution-checkpoint bullets using the completed fake-worker scenarios.
- Record four focused fake-worker tests passing as historical evidence, separate from the earlier 19-test baseline; note that no later full-suite run occurred.
- Record the stopped cancellation/failed-branch slice, the natural-completion correction, and ds4-py #20 without asserting a reproduced Qwen bug.
- Add the explicit GPU-approval constraint and keep incomplete live tasks open.

### ✓ Step 2: Reconcile the research note with the verified evidence
The interim research note distinguishes completed fake-only progress, unresolved safety work, and all outstanding live checks.

- Update `docs/superpowers/research/2026-11-07-27b-worker-smoke-test.md` with the later boundary-hardening results and historical verification provenance.
- Correct outdated read-first-only limitations and remaining-work statements while retaining parallel-tool, cancellation, RNG, and native-state evidence limits.
- Link the interruption issue with the corrected natural-completion distinction; preserve the required research-note opening and closing sections.
- Read both documents for consistency and run a targeted `git diff --check` inside `devenv`; execute no tests or models and retain raw artifacts locally.