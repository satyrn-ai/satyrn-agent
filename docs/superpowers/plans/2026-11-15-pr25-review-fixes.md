# PR #25 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all four PR #25 review findings while preserving the M3 harness behavior and native failure-safety guarantees.

**Architecture:** Separate DFlash selection from application, keep only session state while the engine is open, and make settings provenance explicit with a typed return. Reuse the existing external-config validators rather than duplicating schema rules.

**Tech Stack:** Python 3.14, ds4-py agent composition, pytest model-free E2E with `ScenarioFakeNative`, devenv + uv, prek.

**Spec:** `docs/superpowers/specs/2026-11-15-pr25-review-fixes-design.md`

## Global Constraints

- Work only in the existing `.worktrees/m3-harness` checkout on `feat/m3-harness`; leave the dirty `AGENTS.md` in the main checkout untouched.
- Preserve the existing public CLI/configuration behavior except for correcting diagnostic source prefixes.
- Preserve the idle guard, between-prompt-only native changes, safe identity transitions, original-error propagation, cleanup-error chaining, and session metrics.
- Use test-first changes for observable behavior; structural refactors must keep the existing behavior matrix green.
- New model-free code retains 100% line and branch coverage. Keep behavioral and structural commits separate where practical.

## Review Focus

- **Apply failure after step installation:** `_install` must roll back to `PlainStep` and verify OFF without hiding the original error; Task 2 runs the existing post-MMA and cleanup-failure matrix.
- **Identity transition interruption:** closing after fresh session state exists must expose that state's step, not the previous session's step; Task 1 adds a regression test.
- **Mixed project/CLI input:** a valid CLI override must not hide a project error, and a CLI-only error must not acquire a project prefix; Task 3 tests both directions.
- **Missing verify binding:** a decision of `None` must not call the worker; Task 2 runs the existing off/auto fallback tests.
- **Generic sampling CLI validation:** downstream CLI values merged in `resolve_config` must remain unsourced; Task 3 adds a non-finite sampling regression test if the downstream parser permits one through.

---

### Task 1: Snapshot the Resolved Step Only at Close

**Files:**
- Modify: `src/satyrn_agent/engine.py`
- Modify: `src/satyrn_agent/controller.py`
- Test: `tests/e2e/model_free/test_harness_lifecycle.py`

**Interfaces:**
- Consumes: existing `RuntimeController.state.step` and real runtime identity hooks.
- Produces: `SatyrnEngine._finished_step: DecodeStep | None`; removes `RuntimeController(on_step=...)` and `SatyrnEngine._record_step`; `RuntimeController.resolved_step: DecodeStep | None` reads a retained live-state reference without calling the closed session and returns `None` until a step has been resolved.

- [ ] **Step 1: Write the failing fresh-session close regression test**

Use the real interactive harness. Patch the already-created `controller.after_identity_change` (the runtime captured the extension's bound hook before the fixture yielded), so the test stops at the post-`session_start` boundary. Run `runtime.new()`, retain `controller.state.step`, exit the harness context to perform canonical runtime-then-wrapper close, and assert `wrapper.decode_step is retained_step`. The current `_step` belongs to the old session state, so identity comparison fails before the fix.

- [ ] **Step 2: Run the test and verify RED**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_lifecycle.py -q`
Expected: the new test fails because the closed wrapper returns the previous session state's `PlainStep`.

- [ ] **Step 3: Implement close-time capture**

Remove `on_step` and `_record_step`. Keep the latest `RuntimeState` reference whenever `controller.state` is accessed and expose `controller.resolved_step` without calling `Session.state`; track resolution at the exact points where `_on_step` previously ran so failed pre-resolution setup still returns `None`. In `close()`, set `_closed`, capture `controller.resolved_step` into `_finished_step`, close the controller, then close the native engine. Return `_finished_step` only when closed; use controller state while open. This must work after the runtime has already closed the session.

- [ ] **Step 4: Run focused tests GREEN and commit**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_engine.py tests/e2e/model_free/test_harness_lifecycle.py -q`
Expected: PASS. Also run `tests/e2e/model_free/test_scenarios.py` and confirm the policy-error scenarios retain their existing branch expectations.

```bash
git add src/satyrn_agent/engine.py src/satyrn_agent/controller.py tests/e2e/model_free/test_harness_lifecycle.py
git commit -m "fix(engine): snapshot resolved step at close"
```

### Task 2: Separate DFlash Selection from Native Application

**Files:**
- Modify: `src/satyrn_agent/controller.py`
- Test: `tests/e2e/model_free/test_harness_commands.py`, `tests/e2e/model_free/test_harness_lifecycle.py` (existing behavior matrix)

**Interfaces:**
- Consumes: Task 1 controller without `on_step`.
- Produces: `select_step(...) -> tuple[DecodeStep, int | None]` without `session_raw` or `before_mode_change`; `RuntimeController._install(step: DecodeStep, verify: int | None) -> None`.

- [ ] **Step 1: Record the structural behavior baseline**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_commands.py tests/e2e/model_free/test_harness_lifecycle.py -q`
Expected: PASS before the refactor. The existing probe, support, post-MMA, rollback-failure, missing-binding, and identity tests are the behavioral oracle; no runtime behavior change is intended.

- [ ] **Step 2: Make selection read-only and centralize application**

Return `(PlainStep(), 0 | None)` for off/fallback and `(DFlashStep(...), 1)` for available DFlash. Keep probes and step construction before mutation. `_install` sets the decode step first, marks a step resolved, then calls native verify on the worker when `verify` is not `None`. In `_change`, perform the idle guard and selection outside the apply-failure `try`; call `_fail_change` only when `_install` raises. Use `_install` in `_fail_change` and `before_identity_change`, removing `_set_verify_off` and `mutated`; those callers pass `0` only when `native.verify_mode_available`, otherwise `None`. Add a comment that the two apply operations are synchronous with no await/generation boundary, and that the initial no-op setter proves later decode setters cannot fail before native mutation under the session contract.

- [ ] **Step 3: Run the behavior matrix GREEN**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_commands.py tests/e2e/model_free/test_harness_lifecycle.py -q`
Expected: PASS, including verify `[1, 0]` after post-MMA failure and safe `PlainStep` state after identity failures.

- [ ] **Step 4: Run model-free coverage and commit**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100`
Expected: PASS with 100% line and branch coverage.

```bash
git add src/satyrn_agent/controller.py
git commit -m "refactor(dflash): separate policy selection from application"
```

### Task 3: Make Settings Provenance Explicit and Share Validators

**Files:**
- Modify: `src/satyrn_agent/settings.py`
- Modify: `src/satyrn_agent/config_io.py`
- Test: `tests/e2e/model_free/test_harness_cli.py`, `tests/e2e/model_free/test_config_io.py`

**Interfaces:**
- Consumes: `config_from_dict`, `ThinkBudgetConfig`, existing argparse namespace and `EngineOpenOptions`.
- Produces: frozen `ResolvedSettings(values: dict[str, object], source: Path)`; shared `is_mapping(value: object) -> TypeIs[Mapping[str, object]]` and `validate_think_budget_document(value: object) -> TypeIs[ThinkBudgetDocument]` in `config_io.py`.

- [ ] **Step 1: Write failing source-attribution tests**

Assert both reviewer reproductions have no `pyproject.toml` prefix: `--think-budget 2 --think-bias=nan` and `--dflash on`. Repeat `--dflash on` with an existing but unrelated `pyproject.toml`. Require the project prefix for project-only `dflash = "on"` without a drafter and for project `bias = nan` inherited by CLI `--think-budget 5`. Add a successful CLI `--dflash on` satisfied by project `drafter_path`. Add a mandatory generic `--temp=nan` case requiring no project prefix.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_cli.py -q`
Expected: new CLI cases fail with the incorrect project-file prefix; project-only diagnostics remain unchanged.

- [ ] **Step 3: Implement typed settings and canonical validation**

Replace `SettingsDocument` with `ResolvedSettings`. Hoist and rename the mapping/think-budget validators in `config_io.py`, then use them in both modules; translate shared-validator `TypeError` at the settings boundary to the existing sourced `ConfigurationError`. Validate only explicit CLI think components with `ThinkBudgetConfig` before merging (an explicit bias uses a dummy valid token count), retaining inherited project bias for sourced merged validation. Validate the merged Satyrn document in `resolve_settings`; prefix project errors, except the specific missing-drafter error when `args.dflash == "on"` and neither project nor CLI supplied a drafter. In `resolve_config`, narrow `ResolvedSettings` with `isinstance` before the plain-mapping check, copy its values, merge generic sampling, and leave the final generic downstream validation unsourced.

- [ ] **Step 4: Run configuration tests GREEN**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_cli.py tests/e2e/model_free/test_config_io.py -q`
Expected: PASS, including all prior precedence and validation cases.

- [ ] **Step 5: Run model-free coverage and commit**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100`
Expected: PASS with 100% line and branch coverage.

```bash
git add src/satyrn_agent/settings.py src/satyrn_agent/config_io.py tests/e2e/model_free/test_harness_cli.py tests/e2e/model_free/test_config_io.py
git commit -m "fix(cli): attribute settings errors to their source"
```

### Task 4: Complete Gates, Review, and PR Responses

**Files:**
- Modify only files required by evidence-backed final-review findings.

- [ ] **Step 1: Run all portable verification**

```bash
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
devenv shell -- bash tests/ds4_tools_test.sh
devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100
git diff --check
```

Expected: all pass; record exact test counts and coverage.

- [ ] **Step 2: Run the required fresh final review**

Run `/review-loop` on the complete diff with one structural/maintainability reviewer and one correctness/tests reviewer. Fix evidence-backed P0 and worthwhile P1 findings within this approved scope; ask before broader redesign.

- [ ] **Step 3: Push and run the PR review-loop evidence update**

Push `feat/m3-harness` without amending or force-pushing. Because this adds commits to a reviewed PR, run `pr-review-loop` according to its existing evidence markers and project model rules.

- [ ] **Step 4: Reply to all four GitHub inline threads**

Reply through `gh api repos/satyrn-ai/satyrn-agent/pulls/25/comments/<comment-id>/replies`, naming the fix commit and verification for comment IDs `4579378091`, `4579380636`, `4579382580`, and `4579384081`. Do not use top-level PR comments as substitutes.
