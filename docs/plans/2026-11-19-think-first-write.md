# Think First Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in forced think-budget close and an opt-in mode that stops thinking after the first successful file write in each agent run.

**Architecture:** Extend M3's one lock-protected `ThinkBudgetHook` with the tested forced-close state machine. Keep its existing soft-bias branch unchanged. Extend M3's `RuntimeController` to reset run state and observe public session events emitted for tool results. Do not add a second hook, agent loop, or controller.

**Tech Stack:** Python 3.14, ds4-py public session and runtime events, Pydantic AI tool-result events, JSON Schema, generated TypedDicts, pytest, and the real Metal/Qwen live suite.

**Spec:** GitHub issues #27 and #18; `docs/specs/2026-11-10-m3-harness-integration-design.md` sections 7.1, 8.2, and 14.2 in ds4-py at commit `95d52cbb9f189c9a940e777e9fab6baa15eac622`.

## Global Constraints

- Leave `think_budget` unset by default. Keep `close = "bias"` and `until_first_write = false` as the defaults inside a configured budget.
- Keep `max_tokens` and `bias` required in external configuration. `bias` remains unused in forced-close mode.
- Use the exact close `"\n\nConsidering the limited time by the user, I have to give the solution based on the thinking directly now.\n</think>"`.
- After the first successful `write_file` or `edit_file`, force only `</think>` at the first later sample where `view.in_think` is true. This check precedes both close-mode branches and does not depend on `think_tokens`. Reset this suppression on the next `run_start`.
- Do not trigger on failed writes, other tools, or shell commands that write files. Require `ToolReturnPart.outcome == "success"` as well as the matching tool name.
- Keep one stable hook. Protect the configuration snapshot and run suppression with the hook's lock. Do not call session, engine, cancellation, or blocking APIs from `__call__`.
- Use ds4-py's public event seam. Do not edit ds4-py. Stop and ask the user if the public events cannot implement the required behavior.
- Preserve existing generation and sampling behavior when neither new setting is enabled. The `/think-budget` query intentionally adds the new setting values to its response.
- Issue #27 explicitly requires `/think-budget` to show and change the new settings. Its new subcommands, query fields, and usage text supersede M3 section 8.2 for those parts only. All other command and footer contracts remain unchanged.
- Follow test-driven development. Run each new test before its implementation and observe the expected failure.
- Run commands from the worktree root through `devenv shell -- uv run --frozen ...` unless a command is explicitly a shell test or Git command.

## Review Focus

- A discarded DFlash staged suffix must rewind both cumulative thinking usage and the forced-close offset; Task 2 ports the reference rewind test into the coverage-measured model-free suite and adds a forced-close public-flow scenario.
- A failed write can produce a retry event rather than a return event; Task 3 exercises a real failed `write_file` through the fake-native agent runtime.
- A run can contain several assistant replies and reopened think blocks; Task 2 tests reply-local budget accounting and Task 3 tests run-local suppression across those replies.
- A disabled or bias-mode hook must leave logits untouched; Task 2 retains the existing scenario and adds direct no-op assertions.
- A slash-command change must preserve unrelated values and leave the DFlash footer unchanged; Task 3 tests command transitions and footer equality.

## Approaches

1. Extend the existing M3 hook and controller. This keeps one stable worker hook and uses public run and tool-result events. This is the selected approach.
2. Add a separate immediate-close hook and a Pydantic AI capability. This would duplicate close state and add composition ownership that M3 already assigns to the controller.
3. Wrap or replace ds4-py's file tools. This would couple Satyrn to tool internals and would not use the public event contract.

## File Map

- `schemas/satyrn-config.schema.json`: external `think_budget` fields and defaults.
- `src/satyrn_agent/_generated/config.py`: generated external configuration types.
- `tests/e2e/scenarios/_generated/scenario_types.py`: generated scenario types that reference the same schema.
- `src/satyrn_agent/config.py`: frozen domain configuration and validation.
- `src/satyrn_agent/config_io.py`: external document validation and conversion.
- `src/satyrn_agent/settings.py`: CLI flags and project/CLI merge rules.
- `src/satyrn_agent/capabilities/think_budget.py`: stable bias/force/immediate-close hook and its locked state.
- `src/satyrn_agent/engine.py`: rendered close tokenization and vocabulary setup.
- `src/satyrn_agent/controller.py`: run reset, successful-write detection, and slash commands.
- `tests/unit/test_config.py`: parameterized domain validation.
- `tests/e2e/model_free/test_think_budget.py`: parameterized close-input validation and complex logits-double tests included in the coverage gate.
- `tests/e2e/model_free/test_config_io.py`, `test_harness_cli.py`, `test_harness_commands.py`, and `test_harness_lifecycle.py`: public-flow configuration and harness behavior.
- `tests/e2e/model_free/_harness.py`: scripted tool exchanges shared by agent-level tests.
- `tests/e2e/scenarios/capability-think-budget_forced.json`: exact forced-close public-flow scenario. The underscore keeps filename and ID ordering consistent.
- `tests/e2e/live/test_capabilities.py`: real forced-close comparison.
- `tests/e2e/live/test_harness_tui.py` or a focused new live module: real first-write comparison and slash controls.
- `README.md` and `tests/e2e/README.md`: user configuration, CLI, slash commands, and shell-command limitation.

---

### Task 1: Configuration, generated types, and CLI

**Files:**
- Modify: `schemas/satyrn-config.schema.json`
- Modify: `src/satyrn_agent/config.py`
- Modify: `src/satyrn_agent/config_io.py`
- Modify: `src/satyrn_agent/settings.py`
- Regenerate: `src/satyrn_agent/_generated/config.py`
- Regenerate: `tests/e2e/scenarios/_generated/scenario_types.py`
- Test: `tests/unit/test_config.py`, `tests/e2e/model_free/test_config_io.py`, `tests/e2e/model_free/test_harness_cli.py`

**Interfaces:**
- Produces: `ThinkBudgetConfig(max_tokens: int, bias: float, close: ThinkCloseMode = ThinkCloseMode.BIAS, until_first_write: bool = False)`.
- Produces: `ThinkCloseMode` string enum values `bias` and `force`.
- Produces: CLI `--think-close bias|force` and `--think-until-first-write` with its `--no-think-until-first-write` form.
- Consumes: existing `config_from_dict()`, `validate_think_budget_document()`, and `ResolvedSettings` contracts.

- [x] **Step 1: Write failing domain and external-configuration tests**

Assert the defaults on `ThinkBudgetConfig(10, 2.0)`. Assert both close modes and both boolean values convert from external strings and booleans. Parameterize invalid close values, non-string close values, and non-boolean `until_first_write` values. Assert unknown think-budget fields still fail and missing `max_tokens` or `bias` still fail.

- [x] **Step 2: Write failing CLI merge tests**

Cover project-only values, CLI-only values, CLI overrides, `--think-budget N` inheritance of project close/first-write values, explicit `--no-think-until-first-write`, and `--no-think-budget` clearing every field. Assert close or first-write flags without an effective budget fail before native open. Assert `--no-think-budget` conflicts with either new setting when supplied.

- [x] **Step 3: Run the tests and observe failures**

Run:

```bash
devenv shell -- uv run --frozen pytest tests/unit/test_config.py tests/e2e/model_free/test_config_io.py tests/e2e/model_free/test_harness_cli.py -q
```

Expected: failures name missing close/first-write fields and CLI flags.

- [x] **Step 4: Update schema, validation, domain values, and settings together**

Add optional schema fields with defaults `bias` and `false`. Keep the existing required fields. Add the frozen enum and domain validation. Replace the exact-key-set check with required-plus-allowed validation. Preserve sourced errors and existing CLI precedence.

- [x] **Step 5: Regenerate both named TypedDict jobs**

Run:

```bash
devenv shell -- uv run --frozen datamodel-codegen --all-jobs
```

Expected: both generated files contain the new optional fields, with no handwritten generated-code edits.

- [x] **Step 6: Run the focused tests**

Run the Step 3 command. Expected: all selected tests pass.

- [x] **Step 7: Commit the configuration slice**

```bash
git add schemas src/satyrn_agent/config.py src/satyrn_agent/config_io.py src/satyrn_agent/settings.py src/satyrn_agent/_generated/config.py tests/unit/test_config.py tests/e2e/model_free/test_config_io.py tests/e2e/model_free/test_harness_cli.py tests/e2e/scenarios/_generated/scenario_types.py
git commit -m "feat(config): add think close and first-write settings"
```

### Task 2: Forced-close hook and model-free decode evidence

**Files:**
- Modify: `src/satyrn_agent/capabilities/think_budget.py`
- Modify: `src/satyrn_agent/engine.py`
- Create: `tests/e2e/model_free/test_think_budget.py`
- Create: `tests/e2e/scenarios/capability-think-budget_forced.json`
- Test: `tests/e2e/scenarios/capability-think-budget.json`

**Interfaces:**
- Consumes: Task 1 `ThinkBudgetConfig` and `ThinkCloseMode`.
- Produces: `THINKING_BUDGET_CLOSE` with the exact required sentence.
- Produces: the existing `ThinkBudgetHook.set()` and `snapshot()` APIs, plus locked `start_run()` and `suppress_thinking()` methods for Task 3.
- Keeps: one `ThinkBudgetHook` instance and the existing bias algorithm for `close == bias`. First-write suppression is checked before this branch and remains budget-independent.

- [x] **Step 1: Port the reference logits-double tests as failing tests**

Port tests from `origin/research/overnight-domains:packages/plan-comparison/tests/test_think_budget.py` where they fit the stable hook. Cover no-op before the limit, exact one-token-at-a-time forcing, repeated calls on staged history, cumulative reopened blocks, reply reset, discarded-token rewind, nonthinking replies, immediate close, invalid token sequences, and vocabulary sizes. Adapt constructors to Task 1 configuration without weakening assertions.

- [x] **Step 2: Add failing public-flow forced-close scenarios**

Use chat mode, `think_budget = {max_tokens = 1, bias = 2.0, close = "force"}`, and a deterministic native script in `capability-think-budget_forced.json`. Require the emitted suffix to equal the rendered tokenization of `THINKING_BUDGET_CLOSE`, followed by the normal stop. The ported model-free logits-double tests cover reopened blocks, reply reset, and discarded staged suffixes. Keep the existing bias scenario unchanged and assert its original output still passes. The public-flow scenario and ported model-free tests, together with Task 3's enabled, disabled, and immediate-close cases, must cover every production branch.

- [x] **Step 3: Run the new tests and observe failures**

Run:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_think_budget.py -q
devenv shell -- uv run --frozen pytest 'tests/e2e/model_free/test_scenarios.py::test_model_free_scenario[capability-think-budget-force]' -q
```

Expected: the forced sequence is absent because the current hook only biases token 267.

- [x] **Step 4: Port the forced-close state machine into the stable hook**

Read the configuration and suppression in one lock-protected snapshot. When suppression is active, force `(end_think_token,)` immediately, before either close-mode branch and without reading the budget. Otherwise keep the current bias branch unchanged. For forced mode, port the reference reply-origin, common-prefix, checkpoint, cumulative-block, and force-prefix accounting. Use a reusable `-inf` vocabulary mask and open exactly one closing token per call.

- [x] **Step 5: Tokenize and validate the close at engine setup**

Pass `engine.info.vocab_size` and `engine.tokenize(THINKING_BUDGET_CLOSE, rendered=True)` from `SatyrnEngine.session()` into the same controller-owned hook. Keep `resolve_end_think()` validation. Reject empty or out-of-vocabulary close sequences before generation.

- [x] **Step 6: Run focused and existing decode tests**

Run both Step 3 commands, the existing `capability-think-budget` scenario, and `tests/e2e/model_free/test_harness_lifecycle.py`. Then run the complete model-free coverage gate from Task 3 Step 6. Expected: all pass, the stable-hook identity/lifecycle assertions remain valid, and every new production branch is covered by model-free tests. Add a named public-flow case for any missed branch before proceeding.

- [x] **Step 7: Commit the hook slice**

```bash
git add src/satyrn_agent/capabilities/think_budget.py src/satyrn_agent/engine.py tests/e2e/model_free/test_think_budget.py tests/e2e/scenarios/capability-think-budget_forced.json
git commit -m "feat(think): force the closing sequence at the budget"
```

### Task 3: First-write events, slash commands, lifecycle, and documentation

**Files:**
- Modify: `src/satyrn_agent/controller.py`
- Modify: `tests/e2e/model_free/_harness.py`
- Modify: `tests/e2e/model_free/test_harness_cli.py`
- Modify: `tests/e2e/model_free/test_harness_commands.py`
- Modify: `tests/e2e/model_free/test_harness_lifecycle.py`
- Modify: `README.md`
- Modify: `tests/e2e/README.md`

**Interfaces:**
- Consumes: Task 2 `ThinkBudgetHook.start_run()` and `suppress_thinking()`.
- Consumes: public `Session.on_event()` events `run_start` and `agent_event`.
- Detects: `FunctionToolResultEvent` whose `part` is `ToolReturnPart` with `outcome == "success"` and `tool_name` equal to `write_file` or `edit_file`.
- Produces: `/think-budget close bias|force` and `/think-budget until-first-write on|off` subcommands. Existing `N [BIAS]` and `off` forms retain the other current values where a budget remains enabled.

- [x] **Step 1: Write failing real-runtime write-detection tests**

Use a large `--think-budget 4096` so budget-triggered closing cannot mask first-write behavior. Script a successful `write_file`, a successful `edit_file`, a failed `write_file`, a `read_file`, and a shell command that creates a file. Assert successful writes suppress later thinking in the same run, failed writes and other tools do not, and a second `runtime.run()` allows thinking again. Include emitted `ToolReturnPart` fixtures with `outcome` equal to `failed`, `denied`, and `interrupted`, and assert that none suppresses thinking. Assert the actual target file effects and the emitted result-part types so the test cannot pass through an unrelated branch. Use one portable `bash` one-liner under `tmp_path` for the shell case, or use a successful `run_command` return event without a subprocess if the harness does not expose a portable shell execution contract.

- [x] **Step 2: Write failing slash-command and lifecycle tests**

Extend query output to `think budget N tokens, bias B, close C, until first write on|off`. Test both new subcommands, invalid arity/value usage, preservation of unrelated fields, `off`, and re-enabling with defaults. When no budget is active, `close` and `until-first-write` subcommands raise `CommandError` with the extended usage string; they do not invent a budget. Assert no active-round mutation, `/new` and `/switch` restore startup values, fork retains values, close unsubscribes all listeners, and the DFlash footer text stays equal to `controller.status_text()`.

- [x] **Step 3: Run the tests and observe failures**

Run:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_harness_cli.py tests/e2e/model_free/test_harness_commands.py tests/e2e/model_free/test_harness_lifecycle.py -q
```

Expected: failures show missing subcommands and no suppression after a successful write.

- [x] **Step 4: Implement public-event integration and command controls**

Subscribe the controller to run and agent events for both interactive and noninteractive modes. Reset suppression at every `run_start`. On a matching tool return with `outcome == "success"`, set suppression. Add no native or blocking calls to listeners. Extend the existing usage string and command parser without replacing the hook.

- [x] **Step 5: Document the settings and limits**

Document both TOML fields, defaults, CLI flags, and slash subcommands. State that `bias` is unused with forced close. State that only successful `write_file` and `edit_file` calls trigger first-write mode. State that failed writes and shell commands that write files do not trigger it. Update the live-test instructions with the new evidence.

- [x] **Step 6: Run the complete model-free coverage gate**

Run:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Expected: all tests pass with 100% line and branch coverage. Add behavior tests for any missed branch; do not add coverage exclusions.

- [x] **Step 7: Commit the integration slice**

```bash
git add src/satyrn_agent/controller.py tests/e2e/model_free tests/unit README.md tests/e2e/README.md
git commit -m "feat(agent): stop thinking after the first successful write"
```

### Task 4: Real Metal evidence and complete delivery gates

**Files:**
- Modify: `tests/e2e/live/test_capabilities.py`
- Modify: `tests/e2e/live/test_harness_tui.py` or create a focused live test module
- Modify: `tests/e2e/corpus.json` only if a required live branch needs a checked-in prompt
- Modify: `docs/plans/2026-11-19-think-first-write.md` to record completed checks

**Interfaces:**
- Consumes: all previous public settings, hook, runtime, and command contracts.
- Produces: paired real-model observations with and without forced close and first-write suppression.

- [x] **Step 1: Write failing real forced-close and first-write tests**

For forced close, compare the existing soft-bias case with `close = force` at the same seed. Require the exact forced closing suffix and record thinking-token counts for both arms. For first write, use a real `write_file` exchange. Require thinking before the write, no thinking content after it, and thinking again on the next user run. Run a feature-off arm and record its post-write thinking count. Keep token/transcript/native-position alignment assertions and DFlash on for the required first-write run.

- [x] **Step 2: Check the live process guard and model identities**

Run `pgrep -fl "ds4|dogfood|satyrn-agent"`. If another model process appears, stop and ask the user. Otherwise verify the pinned target and drafter hashes and resolve the patched library from the documented environment. Never use `--raw-prompt`.

- [x] **Step 3: Run the focused live tests**

Run only the new forced-close and first-write tests first. Expected: both pass with the real Metal library and pinned GGUFs. Save counts and command output outside the repository for the final report.

- [x] **Step 4: Run every required static and portable gate**

```bash
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
bash tests/ds4_tools_test.sh
devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100
git diff --check
```

Expected: every command exits zero. Record test and hook counts.

- [x] **Step 5: Run the abnormal and complete live gate**

Repeat the process guard. Then run:

```bash
devenv shell -- uv run --frozen pytest tests/abnormal tests/e2e/live
```

Expected: no guarded skips when the documented real inputs are present. Record pass, skip, failure, and coverage counts. If the environment is missing, report the gate honestly instead of claiming live success.

- [ ] **Step 6: Review the complete diff and commit final evidence**

Evidence before review: prek passed; shell tools 49/49; model-free 279/279 with 100% line and branch coverage; abnormal plus live 49/49 with 0 skips; `git diff --check` passed. Forced close: bias/force maximum thinking counts 2/25, including the forced sentence. First write: off before/after/next 60/30/47 tokenized thinking content; on 60/0/47.

Use a fresh reviewer for correctness and tests. Fix concrete P0/P1 findings through failing tests. Run `git diff --check` again. Commit any remaining test or documentation changes in the repository style. The final commit body must contain:

```text
Fixes #27
Fixes #18
```

Do not add co-author or tool trailers.

- [ ] **Step 7: Push, open the PR, and run the requested review loop**

Push `feat/think-first-write`. Open a PR with a short body covering each setting, defaults, gate results with counts, and a link to this plan. Do not mention tools or agents in the PR body. Run the pr-review-loop skill, alternating reviewer models as the user requested, and ask the user for each ruling.
