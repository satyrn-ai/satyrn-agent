# M3 Harness Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `satyrn-agent` on ds4-py's real agent CLI/runtime/TUI with Satyrn DFlash, mutable soft think budgets, slash commands, footer metrics, lifecycle-safe state, and real Metal acceptance coverage.

**Architecture:** One per-process `AgentExtension` resolves Satyrn settings and returns the real configured `Session` plus its already-merged `SamplingPolicy`. One engine-lifetime controller owns native policy and subscriptions; one session-scoped state owns requested/resolved DFlash mode and a shared metrics recorder. ds4-py alone owns `DS4Model`, `AgentRuntime`, tools, persistence, the TUI, and its footer.

**Tech Stack:** Python 3.14, ds4-py `95d52cbb9f189c9a940e777e9fab6baa15eac622` with the `agent` extra, `tomllib`, argparse, prompt-toolkit through ds4-py, pytest, FakeNative plus scripted optional DFlash bindings for portable tests, and patched Metal `libds4` with pinned GGUFs for live tests.

**Spec:** `/Users/koudai/work/ds4-py/docs/specs/2026-11-10-m3-harness-integration-design.md` at ds4-py commit `95d52cb`; Satyrn requirements are §§5.2, 5.3, 6–9, 11, 12.2–12.4, and 13.

## Global Constraints

- Use only ds4-py's public composition seams at `95d52cbb9f189c9a940e777e9fab6baa15eac622`; do not copy or monkeypatch ds4-py internals or change ds4-py.
- Do not modify `patches/`, `devenv*`, or `tools/`; satyrn-agent PR #24 owns those areas.
- Preserve ADR 0002: no `--yolo`, approval argument, approval prompt, or approval capability.
- No second engine/model/runtime/token loop/TUI/persistence format, no re-rendering text for token IDs, and no mid-round DFlash changes or failure-driven plain fallback.
- Read only the invocation CWD's `pyproject.toml`; precedence is domain defaults → `[tool.satyrn]` → explicit CLI, with explicit zero preserved.
- Keep drafter path and draft count process-lifetime; slash changes affect only DFlash mode and the soft think budget and are not persisted.
- Listeners do only Python-local state/footer work. Native identity changes occur only in ds4-py runtime before/after hooks.
- New model-free code has 100% line and branch coverage. A live skip or failure means the work is not done.
- Keep mechanical/structural commits separate from behavioral commits. Use repository-style messages with no co-author or tool trailers.

## Review Focus

- **Post-MMA failure atomicity:** a failing DFlash construction must leave `PlainStep`, restore verify `OFF` when possible, chain rollback errors, and never retain stale history or claim a safe mode. Task 3 tests every pre-/post-mutation branch.
- **Identity event confinement:** `/new` and failed/successful `/switch` must initialize Python state without any worker/native call from listeners. Task 4 uses a forbidden-call native boundary during every `session_start`.
- **Queued slash commands:** input during a real runtime run must not mutate decode or think state until the run ends. Task 3 drives the actual prompt-toolkit TUI with a gated model run.
- **Sampling/config ambiguity:** explicit zero, missing versus configured think bias, and relative drafter paths must not collapse into defaults or resolve against the worker CWD. Task 1 covers the complete precedence matrix before native open.
- **Live committed-stream reconciliation:** footer metrics and transcript tokens must refer to the same commit boundary across on/off/on, tool, save/new/switch, and compaction spans. Task 5 asserts per-round IDs, native position, metric deltas, and footer snapshots with no native doubles.

## File Structure

- `pyproject.toml`, `uv.lock`: pin ds4-py with `[agent]` and expose `satyrn-agent = satyrn_agent.cli:main`.
- `src/satyrn_agent/settings.py`: CWD-only TOML loading, downstream CLI/project merge, path resolution, and a JSON-shaped settings document.
- `src/satyrn_agent/cli.py`: `SatyrnAgentExtension`, final typed-sampling merge and `config_from_dict` validation, `ConfiguredSession` composition, and console entry point.
- `src/satyrn_agent/controller.py`: one engine-lifetime native policy owner, scoped state, stable think hook owner, commands, status formatting, and lifecycle hooks.
- `src/satyrn_agent/capabilities/think_budget.py`: one stable lock-protected hook with replaceable immutable settings.
- `src/satyrn_agent/dflash.py`: shared recorder constructor injection without changing decode behavior.
- `src/satyrn_agent/engine.py`: construct/expose the controller during the first/only session setup; close it with the wrapper.
- `src/satyrn_agent/__init__.py`: export only deliberate new public types needed by consumers/tests.
- `tests/e2e/model_free/_harness.py`: real extension/runtime/TUI fixture using `ScenarioFakeNative`; only native/DFlash externals are scripted.
- `tests/e2e/model_free/test_harness_cli.py`: configuration, parser, open/close, sampling, ADR 0002, noninteractive and tool-flow tests.
- `tests/e2e/model_free/test_harness_commands.py`: real TUI command, footer, policy-failure, and active-run queue tests.
- `tests/e2e/model_free/test_harness_lifecycle.py`: identity/reset/fork/close and supported/unsupported public persistence tests.
- `tests/e2e/live/test_harness_tui.py`: real Metal end-to-end TUI acceptance, including supported compaction.
- `tests/e2e/live/test_abi_workflow.py`: additionally require the optional core `ds4_session_supports_payload` record while retaining all eight Satyrn records.
- `README.md`, `docs/development.md`, `tests/e2e/README.md`: replace the old no-M3 status/pin text and document CLI/settings and the new live gate.

---

### Task 1: Pin the Harness and Implement Settings/CLI Composition

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `src/satyrn_agent/settings.py`, `src/satyrn_agent/cli.py`
- Create: `tests/e2e/model_free/_harness.py`, `tests/e2e/model_free/test_harness_cli.py`

**Interfaces:**
- Consumes: `ds4py.agent_composition.AgentExtension`, `EngineOpenOptions`, `ConfiguredSession`; `satyrn_agent.open()` and `SatyrnEngine.sampling_defaults`.
- Produces: `SatyrnAgentExtension(program="satyrn-agent", open_engine=satyrn_agent.open)` with an injectable Satyrn public-open callable as the only native test seam; `resolve_settings(args: Namespace, project_dir: Path) -> dict[str, object]` returning the downstream JSON-shaped document; `main(argv: list[str] | None = None) -> int` delegating to `ds4py.agent_cli.main(..., extension=SatyrnAgentExtension())`. `open_session` passes `interactive=options.interactive` to the wrapper so controller subscriptions exist only for interactive composition.

- [ ] **Step 1: Write failing configuration tests**

Cover absent/missing-table TOML, malformed TOML and source-file diagnostics, no parent search, unknown fields, bool-as-int, negative counts, invalid/non-finite values, `on` without a drafter, explicit zero sampling/draft values, `~` and project-relative drafter paths, and CLI-over-project precedence. Parameterize all think cases: CLI budget inherits project bias; CLI-only budget uses `2.0`; CLI bias overrides project or CLI budget; bias without a budget errors; `--no-think-budget` clears project and conflicts with either positive flag. Assert invalid input returns `satyrn-agent: ...` before the fake native open, and an unsatisfiable native-open `DFlashUnavailable` also returns a labeled error rather than a traceback.

- [ ] **Step 2: Run configuration tests and verify RED**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_cli.py -q`
Expected: collection/import failure because the settings/CLI modules and entry point do not exist.

- [ ] **Step 3: Update the ds4-py pin and implement the settings boundary**

Change the dependency to `ds4py[agent] @ git+https://github.com/rochecompaan/ds4-py.git@95d52cbb9f189c9a940e777e9fab6baa15eac622`, run `devenv shell -- uv lock`, and register `satyrn-agent`. Implement argparse options from spec §6.2 without registering `--top-k`, `--temp`, `--top-p`, or `--min-p` twice. In `resolve_extension_config`, merge only project values and downstream-owned CLI values into a raw JSON-shaped document and resolve the effective drafter path against the TOML directory after `expanduser()`; do not read generic sampling fields from `Namespace`.

- [ ] **Step 4: Write failing public-composition tests**

Use the real extension, real `DS4Model`/`AgentRuntime`, and `ScenarioFakeNative` to assert generic options reach `satyrn_agent.open`, family/native/explicit sampling values merge once (including seed and explicit zeros), noninteractive has no commands/status, close order is runtime close then wrapper close, and a scripted `read_file` call/result flows through real harness events. Assert `--yolo` remains a parser error and no approval kwargs appear.

- [ ] **Step 5: Implement `SatyrnAgentExtension.open_session` and run focused tests GREEN**

Map every `EngineOpenOptions` engine field into `satyrn_agent.open`, add its typed sampling overrides to the raw settings document, and call `config_from_dict` once on that final value before native open. Pass `interactive=options.interactive`, obtain `wrapper.session()` once, and return `ConfiguredSession(session, wrapper.sampling_defaults, wrapper.close)` without `SamplingPolicy.for_engine`. Catch `SatyrnError` in the console adapter and emit `satyrn-agent: ...`. Tests inject only the extension's `open_engine` callable to supply `ScenarioFakeNative`; they do not monkeypatch ds4-py internals. Run the two focused files and existing engine/config/scenario tests.

- [ ] **Step 6: Commit the behavioral CLI slice**

```bash
git add pyproject.toml uv.lock src/satyrn_agent/settings.py src/satyrn_agent/cli.py tests/e2e/model_free/_harness.py tests/e2e/model_free/test_harness_cli.py
git commit -m "feat(cli): compose Satyrn with the ds4-py agent harness"
```

### Task 2: Structurally Separate Decode Policy and Shared Primitives

**Files:**
- Modify: `src/satyrn_agent/dflash.py`, `src/satyrn_agent/engine.py`
- Create: `src/satyrn_agent/controller.py` (initial structural home only)
- Modify: `tests/e2e/model_free/test_engine.py`, existing DFlash scenario helpers only where constructor names require it

**Interfaces:**
- Produces: public thread-safe `Recorder` with `snapshot()`/`committed(...)`; `DFlashStep(..., recorder: Recorder | None = None)`; controller owns the existing `_select_step` policy without adding runtime toggles in this commit.

- [ ] **Step 1: Add compatibility-focused failing tests for constructor ownership**

Assert omitting `recorder` creates an independent recorder and supplying one shares metrics between steps. Assert the existing session open, off/on/auto behavior, metrics, and error behavior remain unchanged.

- [ ] **Step 2: Run focused tests RED, then make the minimal structural refactor**

Rename/export the recorder, add optional constructor injection, and move the existing policy into the controller module without adding slash/status/lifecycle behavior. Keep one code path for initial open. Do not mix formatting-only edits into this commit.

- [ ] **Step 3: Run all existing model-free tests and commit the structural change**

Run the full model-free coverage command and require the original 116-test behavior plus new ownership tests at 100%.

```bash
git add src/satyrn_agent/dflash.py src/satyrn_agent/engine.py src/satyrn_agent/controller.py tests/e2e/model_free
git commit -m "refactor(dflash): share decode policy and metrics ownership"
```

### Task 3: Mutable Think Hook, Slash Commands, Footer, and Failure Atomicity

**Files:**
- Modify: `src/satyrn_agent/capabilities/think_budget.py`, `src/satyrn_agent/controller.py`, `src/satyrn_agent/engine.py`, `src/satyrn_agent/cli.py`
- Modify: `src/satyrn_agent/dflash.py` only if recorder/state typing requires it
- Create: `tests/e2e/model_free/test_harness_commands.py`
- Modify: `tests/e2e/model_free/_harness.py`, `tests/e2e/model_free/_native.py` (record every requested verify mode and scripted failure)

**Interfaces:**
- Produces: stable `ThinkBudgetHook.set(ThinkBudgetConfig | None)`; scoped `{requested, step, recorder}` under one Satyrn key; `before_identity_change()`, `after_identity_change()`; `/dflash` and `/think-budget`; one `publish_status()` implementation. The wrapper receives the Task 1 `interactive` flag before session/controller creation; no event subscriptions or status publication occur when it is false.

- [ ] **Step 1: Write failing command/hook/footer tests through the real TUI**

Cover both query forms, every valid set form, all usage/validation errors, default/current bias rules, disabled no-op sampling, replacement observed by later samples, exact `accept — (0/0)` and one-decimal strings, metrics retained across repeated on/off toggles, run-end refresh on success/interruption/error, one initial publication after `FooterModel` subscribes, no creation-time/noninteractive publication, and active-run slash queuing. Assert on → off calls native verify `OFF`; `auto` resolves once; `on` names missing bindings/drafter/backend/zero rows/setup failures.

- [ ] **Step 2: Write the full failing mutation-failure matrix**

For pre-mutation usage/validation/probe failures assert requested/resolved step, footer, and transcript are unchanged. For post-MMA construction failure assert `PlainStep`, best-effort verify `OFF`, safe `off`/`on/off`/`auto/off` status, original error propagation, unchanged history, and `error` plus chained original/cleanup errors when rollback fails. Assert no failure path silently falls back to plain decode.

- [ ] **Step 3: Run command tests RED**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_commands.py -q`
Expected: failures for missing dynamic hook/controller commands/status behavior.

- [ ] **Step 4: Implement the controller and stable think hook**

Install exactly one no-op-capable hook. Lock only setting snapshot/replacement. Put current mode/step/recorder in `session.state`, never controller `_current`. Resolve support and construct a step before MMA; explicitly set verify `OFF` for off/auto fallback when the binding exists. Implement rollback/error chaining and one status formatter exactly as §§7–8. Commands defensively require idle native state; TUI registration occurs after builtins and initial status occurs there.

- [ ] **Step 5: Run focused tests and existing generation/scenario suites GREEN**

Run command tests, then all model-free tests with coverage. Add public-flow cases until every new line/branch is exercised; do not use unit-only coverage substitutions.

- [ ] **Step 6: Commit the behavioral command slice**

```bash
git add src/satyrn_agent tests/e2e/model_free
git commit -m "feat(tui): add DFlash and think-budget controls"
```

### Task 4: Identity Lifecycle and Public Persistence

**Files:**
- Modify: `src/satyrn_agent/controller.py`, `src/satyrn_agent/engine.py`
- Create: `tests/e2e/model_free/test_harness_lifecycle.py`
- Modify: `tests/e2e/model_free/_harness.py`, `tests/e2e/model_free/_native.py` (pass through/set `payload_support` on `FakeNative`)

**Interfaces:**
- Consumes: Task 3 controller and real `AgentRuntime.new/switch/fork/close/save/run` methods.
- Preserves: startup `SatyrnConfig`, engine-lifetime subscriptions, session-scoped recorder/state, stable hook.

- [ ] **Step 1: Write failing lifecycle tests**

Through real runtime/TUI flows assert `/new` and `/switch` order: safe `PlainStep` + verify `OFF` before identity work; Python-only `session_start` creates fresh state/recorder, resets think to startup, and emits exact safe pre-resolution status; after hook re-resolves startup mode and emits final status. Assert fork retains state/settings/counts and runs no identity hooks; close clears the hook and unsubscribes exactly once; state closes exactly once.

- [ ] **Step 2: Write failing lifecycle failure and persistence tests**

Assert listener execution never calls `on_worker`, decode setters, or native functions; before-hook errors leave identity/record untouched; after-hook errors propagate with adopted identity/error status and no stale DFlash step; failed restore keeps safe state/status. Exercise successful and interrupted/error `run_end`. Parameterize native payload support true/false through the same public runtime: KV save/switch when true, complete stripped save and rendered switch plus later generation when false, including compacted history.

- [ ] **Step 3: Run lifecycle tests RED, implement, and rerun GREEN**

Add engine-lifetime `session_start`/`run_end` subscriptions only in interactive mode. Keep all native reconfiguration in before/after runtime hooks; clean up subscriptions/hook in `SatyrnEngine.close()`. Rely on ds4-py's public `file_payloads_supported` persistence behavior rather than adding a Satyrn save format or guard.

- [ ] **Step 4: Run the full portable coverage gate and commit**

Run `devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100`; require 100%.

```bash
git add src/satyrn_agent tests/e2e/model_free
git commit -m "feat(runtime): scope Satyrn controls to session identity"
```

### Task 5: Real Metal Harness Acceptance and Documentation

**Files:**
- Create: `tests/e2e/live/test_harness_tui.py`
- Modify: `tests/e2e/live/test_abi_workflow.py`, `tests/e2e/README.md`, `README.md`, `docs/development.md`

**Interfaces:**
- Consumes: installed `satyrn-agent`, real patched Metal library, pinned target/drafter, real `AgentRuntime`/TUI and prompt-toolkit pipe input or equivalent real terminal driver.

- [ ] **Step 1: Add the live harness test before claiming live support**

Open DFlash `on`, greedy/seed 1; assert initial `dflash: on, accept — (0/0)`. Run `greedy-parity`, require offered > 0 and accepted > 0, then at least two user turns and a real `read_file` exchange with harness tool-call/tool-result events. Set/query/disable think budget and continue generation. Toggle off, prove a plain round adds no metrics, toggle on, and prove new committed metrics. Save/new/switch and continue with restored history; verify identity status/metric/think resets. Run a real supported `/compact` case, continue, save, and switch.

- [ ] **Step 2: Add committed-stream and ABI assertions**

For every round compare committed `Token` IDs to assistant segments and native position to transcript length minus unevaluated trailing EOS. For each DFlash-on span require new assistant tokens == delta committed blocks + delta accepted; off spans require zero metric delta; footer counts/ratio equal recorder snapshots at the same boundary. Extend the ABI test to require optional core `ds4_session_supports_payload` and exactly the existing eight Satyrn-owned entries/metadata.

- [ ] **Step 3: Update user/developer documentation**

Document the console command, all settings/options/slash commands/footer, no-yolo policy, new pin, and exact live inputs/command. Remove the statement that M3 CLI/TUI/persistence is absent. Do not add generated models/libraries/traces/sessions.

- [ ] **Step 4: Verify live preflight and run the focused test**

Set `SATYRN_TEST_MODEL`, `SATYRN_TEST_DRAFTER`, `SATYRN_TEST_LIB`, and `SATYRN_TEST_DS4_SRC`. Run `pgrep -fl "ds4|dogfood"` alone and stop to ask if another actual ds4/model process is present. Acquire the exclusive `fcntl` lock `/Users/koudai/work/.dflash-locks/gpu` with a temporary local wrapper before every build/live command, keeping the process check as an additional guard. Verify both pinned SHA-256 values and inspect the ABI manifest. Record Mac/memory/macOS/backend/tree/ds4-py/Satyrn/library/model identities and commands. Run `tests/e2e/live/test_harness_tui.py`; any failure or guarded skip blocks completion. Never use `--raw-prompt`.

- [ ] **Step 5: Execute the §13.2 project-plus-CLI launch**

Create a scratch read-only workspace with the exact §13.2 `pyproject.toml` and small README, set `DS4PY_HOME=/tmp/satyrn-m3-demo-home`, and launch the documented `satyrn-agent` command with `--dflash on --think-budget 256 --seed 1 --tokens 2048 --read-only --trace /tmp/satyrn-m3-demo.trace.jsonl` under the same process/GPU guards. Drive the real TUI with the corpus prompt, `/think-budget`, `/dflash`, and `/exit`; require a normal answer, DFlash acceptance, and query output `think budget 256 tokens, bias 2.0` plus `dflash: on`. Retain the trace outside the repository as evidence that this launch used the project drafter/default draft count and greedy project sampling with CLI budget inheritance. This is not the excluded §13.3 interactive acceptance script.

- [ ] **Step 6: Commit live coverage and docs**

```bash
git add tests/e2e/live README.md docs/development.md tests/e2e/README.md
git commit -m "test(e2e): exercise the Satyrn harness on Metal"
```

### Task 6: Complete Gates, Independent Review, and Delivery

**Files:**
- Modify only files needed for evidence-backed review findings or gate failures.

- [ ] **Step 1: Run all Satyrn gates from the worktree root**

Run and record exact counts/results:
1. `devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure`
2. `devenv shell -- bash tests/ds4_tools_test.sh`
3. `devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100`
4. `devenv shell -- uv run --frozen pytest tests/abnormal tests/e2e/live`
5. `git diff --check`

Before build/live commands rerun the process check, stop/ask on an actual conflict, and hold `/Users/koudai/work/.dflash-locks/gpu`. Do not modify ds4-py; per the user's delivery instructions, run the §13.4 Satyrn gates only and do not rerun the already-merged ds4-py companion gates.

- [ ] **Step 2: Run the final diff review and address evidence-backed P0/P1 findings**

Run `/review-loop` with one structural/maintainability reviewer using `thermo-nuclear-code-quality-review` and one correctness/tests reviewer. Keep scope unchanged; ask the user before any redesign beyond the approved spec.

- [ ] **Step 3: Push and open the draft PR**

Push `feat/m3-harness` to `satyrn-ai/satyrn-agent`. Keep the draft body short: M3 behavior, exact ds4-py pin, gate results/counts including live offered/accepted/tool evidence, and `docs/plans/2026-11-14-m3-harness-integration.md`. No tool/agent mentions or trailers.

- [ ] **Step 4: Run the PR review loop to its bounded outcome**

Use `~/.agents/skills/pr-review-loop`, alternating `deepseek/deepseek-v4-pro` and `kimi-coding/k3.1-pro`, ask the user for each required ruling, record dispositions in the PR body, rerun affected gates after changes, and report the loop outcome. Interactive acceptance §13.3 remains explicitly for the later user-led session.

## Spec Coverage Matrix

| Spec requirement | Owning task/tests |
| --- | --- |
| §5.2 pin, console script, typed open options, one sampling merge, close order | Task 1 CLI/composition tests |
| §5.3 runtime-owned before/after identity orchestration | Task 4 lifecycle order/failure tests |
| §6 CWD TOML, precedence, paths, validation, every option and think combination | Task 1 parameterized settings/CLI tests |
| §7 one controller/state/recorder/stable hook and close semantics | Tasks 2–4 ownership, reset/fork/close tests |
| §8 slash query/set/usage, between-prompt execution, exact footer and triggers | Task 3 real-TUI command/status/queue tests |
| §9 verify-mode and failure invariants, no transcript mutation/fallback | Task 3 policy and post-MMA failure matrix |
| §11 ADR 0002 unchanged | Task 1 parser/runtime composition assertions |
| §12.2 real public model-free stack and 100% branch coverage | Tasks 1–4 model-free E2E; Task 6 gate |
| §12.3 existing live regressions and ABI records | Task 5 ABI assertion; Task 6 full abnormal/live suite |
| §12.4 real Metal TUI, tools, controls, persistence, token/metric alignment, compaction | Task 5 `test_harness_tui.py`; Task 4 unsupported compaction persistence |
| §13.1 identity/environment and manifest | Task 5 preflight/evidence |
| §13.2 project+CLI launch | Task 1 precedence tests and Task 5 actual scratch-workspace TUI launch |
| §13.3 interactive acceptance | Out of scope by user; later user-led session |
| §13.4 Satyrn gates and `git diff --check` | Task 6 |
| §14.2 immutable boundaries and permitted builder latitude | Global constraints; any contradiction stops for user decision |
