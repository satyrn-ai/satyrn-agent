# Scenario-Driven E2E Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model-free public-flow E2E scenarios the primary Satyrn verification suite, with generated TypedDict boundaries and a 100% line/branch coverage gate.

**Architecture:** Versioned JSON scenarios use one shared runner over `satyrn_agent.open()`, real ds4-py workers/sessions, and deterministic scripted optional bindings. datamodel-code-generator produces checked-in TypedDicts; handwritten `TypeIs` validators and conversion logic provide runtime validation. Real-engine tests and narrow auxiliary unit/abnormal tests remain separate.

**Tech Stack:** Python 3.14, pytest/coverage, ds4-py FakeNative, JSON Schema, datamodel-code-generator 0.90.0, TypedDict, TypeIs, Ruff, ty, prek.

**Spec:** `docs/superpowers/specs/2026-11-07-e2e-scenario-testing-design.md`

## Global Constraints

- Pydantic BaseModel and TypeAdapter are not used; datamodel-code-generator is a development-only dependency.
- Use `preset = "practical-py314-20261104"` for schema-authored names, model reuse, and embedded descriptions, then apply reviewed `--recommend-options` results to the actual scenario schema.
- Every model-free scenario runs public `satyrn_agent.open()` and real ds4-py worker/session code; only the external native boundary is scripted.
- Unit tests remain only for parameterized values and complex exception/external-service doubles.
- Model-free E2E must independently reach 100% line and branch coverage; auxiliary tests cannot fill missing branches.
- Model-free results never substitute for real ds4/GGUF/Metal acceptance.
- Preserve all native/thread/token invariants and the existing shell suite.

## Review Focus

- **Boolean-vs-integer and nested union inputs:** malformed scenario data must fail before field access; Task 1 tests valid/invalid schema parity.
- **Stale generated models:** schema edits without regeneration must fail in CI; Task 1 adds a prek check.
- **Scenario-specific logic hidden in the runner:** every expected value and branch belongs to scenario data; Tasks 2–4 use independent documents and a registry completeness check.
- **Consecutive rounds and pending anchors:** observations must use per-round offsets and exactly-once sampling; Task 3 asserts tokens/events/RNG/metrics.
- **Model-free versus live evidence:** moving live tests must not change their identity checks or skip reasons; Task 5 runs both suites separately.
- **Coverage by doubles only at the external boundary:** the runner must not bypass Satyrn's public open/session/decode path; Tasks 2–4 assert the public call sequence.

---

### Task 1: Versioned scenario schema, generated TypedDicts, and validation

**Files:**
- Create: `tests/e2e/schema/scenario.schema.json`
- Create: `tests/e2e/scenarios/_generated/scenario_types.py`
- Create: `tests/e2e/model_free/{__init__,_schema.py,test_schema.py}`
- Modify: `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`

**Interfaces:**
- Produces: `Scenario`, `ScenarioConfig`, `Round`, `NativeCall`, `Expectation` TypedDicts; `load_scenario(path: Path) -> Scenario`; `iter_scenarios() -> Iterator[Scenario]`.

- [ ] **Step 1: Define schema and failing validation tests**

Define schema version 1 with scenario id/description, backend/native defaults, config, native call scripts, rounds, expected events/metrics/metadata, and `expected_branches`. Write tests for missing names, wrong scalar types, booleans as integers, unknown operations, duplicate ids, invalid nested calls, and valid typed loading.

- [ ] **Step 2: Add generator and prove RED**

Add `datamodel-code-generator==0.90.0` to `dev` and the baseline `[tool.datamodel-codegen]` settings from the design. Run `uv lock`, then run the validation tests before the generated models/loader exist; expect import failure.

- [ ] **Step 3: Generate and review TypedDicts**

Run `--recommend-options` on the actual schema, record the recommended additions in `pyproject.toml`, generate TypedDicts with Ruff formatters, and inspect generated closed/required/optional types. Add a prek local `datamodel-codegen --check` hook so stale output fails.

- [ ] **Step 4: Implement runtime parsing**

Implement `TypeIs` validators and explicit conversion from `object` to generated TypedDicts. Validate nested unions before indexing, reject duplicate scenario ids, and convert validated config dictionaries into `SatyrnConfig` in one later-runner helper. Keep Pydantic models/TypeAdapter out of the code.

- [ ] **Step 5: Verify and commit**

Run schema tests, `datamodel-codegen --check`, Ruff, and ty. Commit as `test(e2e): add typed scenario schema`.

### Task 2: Public-flow model-free runner and first scenario

**Files:**
- Create: `tests/e2e/model_free/{_native,_runner,_observations}.py`
- Create: `tests/e2e/scenarios/basic_round.json`
- Create: `tests/e2e/model_free/test_scenarios.py`

**Interfaces:**
- Consumes: `Scenario` from Task 1.
- Produces: `run_scenario(scenario: Scenario) -> ScenarioResult`; `ScenarioResult.events`, `.transcript`, `.native_position`, `.rng`, `.metrics`, `.metadata`, `.reached_branches`.

- [ ] **Step 1: Write the first failing public-flow scenario**

`basic_round.json` defines native sampling defaults, a short deterministic script, one chat round, expected tokens/reason/transcript/native position/RNG, and expected branches. The scenario test asserts that public `satyrn_agent.open()` and one real ds4-py session are used.

- [ ] **Step 2: Confirm RED and implement the scripted native boundary**

Subclass ds4-py `FakeNative`/`FakeEngine` only to register real fake sessions by raw handle and backend metadata. Implement optional DFlash binding callables whose buffers/status values follow the real ABI. Scripted `draft`, `verify`, `select`, and `commit` operate on fake session tokens without replacing Satyrn's decode logic.

- [ ] **Step 3: Implement the shared runner and observations**

Run the public factory/session/round path, collect per-round assistant offsets, full event payloads, transcript/native position, RNG, metrics, and sample metadata. Assert scenario expectations centrally; the runner contains no scenario-specific expected values.

- [ ] **Step 4: Verify and commit**

Run `basic_round`, all schema tests, Ruff, and ty. Commit as `test(e2e): run public flows through model-free scenarios`.

### Task 3: DFlash decode and boundary scenarios

**Files:**
- Create: `tests/e2e/scenarios/dflash_*.json`
- Modify: `tests/e2e/model_free/{_native,_runner,_observations}.py`
- Modify: `tests/abnormal/test_dflash_*.py` only to remove duplicated normal-path cases after migration

- [ ] **Step 1: Add normal block scenarios**

Cover full acceptance, partial acceptance, first/middle mismatch, zero drafts, bonus/pending anchors, anchor stop, max tokens, tool close, parser error, stop sequence, and native commit-before-publication. Assert exact tokens, per-round transcript suffixes, native positions, events, metrics, reasons, and reached branches.

- [ ] **Step 2: Add cancellation/RNG and metadata scenarios**

Cover cancellation before verify/before rows/after unused candidates, unused replacement/bonus restoration, pre-finalized/no-pending exits, canonical-plus-staged metadata, and no duplicate sample/hook execution. Assert exact RNG and metadata sequences.

- [ ] **Step 3: Add fault scenarios where E2E is clearest**

Cover draft/verify poison, select/sample/hook cleanup, commit side effects, cleanup failure chaining, and eval/publication uncertainty through the same public-flow boundary. Keep unusually complex low-level fault combinations in auxiliary abnormal unit tests.

- [ ] **Step 4: Migrate duplicate normal unit tests**

Delete only tests whose behavior is now proven by scenarios; leave narrow parameterized or complex fault tests. Add a registry assertion that every runner branch has at least one scenario and no scenario declares an unknown branch.

- [ ] **Step 5: Verify and commit**

Run all model-free scenarios with coverage, auxiliary abnormal tests, Ruff, and ty. Commit as `test(e2e): cover DFlash decode boundaries with scenarios`.

### Task 4: Policy, capabilities, and consecutive-round scenarios

**Files:**
- Create: `tests/e2e/scenarios/{policy,capability,multi_round}_*.json`
- Modify: `tests/unit/test_engine.py`, `tests/unit/test_sampling.py`, `tests/unit/test_think_budget.py` only to remove duplicated public-flow coverage

- [ ] **Step 1: Add policy scenarios**

Cover `off`, `auto` fallback for no drafter/missing binding/backend/no loaded drafter/zero rows, `on` requirement failures, setup failure, first-and-only session, closed wrapper, and idempotent close through the public factory. Assert exact error class/message and step metrics.

- [ ] **Step 2: Add capability scenarios**

Cover native/family/explicit merge precedence, explicit zero, absent native defaults, marker resolution errors, think-hook threshold/later samples, and no transcript injection. Keep scalar configuration matrices in auxiliary unit tests.

- [ ] **Step 3: Add consecutive-round and snapshot parity scenarios**

Cover repeated public rounds with per-round offsets, snapshot serial/speculative parity, full normalized event sequences, and exact metadata/RNG continuation. Keep real native parity in the separate live suite.

- [ ] **Step 4: Remove duplicated public-flow unit tests and verify**

Run model-free E2E and auxiliary suites independently. Commit as `test(e2e): cover policy and capabilities through public sessions`.

### Task 5: Live layout, documentation, and the independent 100% gate

**Files:**
- Move: `tests/e2e/test_*.py` to `tests/e2e/live/`
- Modify: `tests/conftest.py`, `tests/e2e/README.md`, `docs/superpowers/specs/2026-10-29-agent-package-design.md`, `docs/development.md`, `AGENTS.md`, `README.md`, `docs/reports/agent-package-validation.md`

- [ ] **Step 1: Separate live acceptance without changing its contract**

Move real-engine modules under `tests/e2e/live`, update imports/paths, and verify their required inputs, approved identity checks, skip reasons, and real snapshot assertions are unchanged.

- [ ] **Step 2: Update the governing design and developer guide**

Amend §15 of the existing agent-package design to make model-free public-flow E2E the normal-path coverage gate, with real ds4/GGUF acceptance separate and auxiliary unit tests limited to their stated roles. Document scenario addition, TypedDict regeneration, validation, and coverage commands.

- [ ] **Step 3: Require 100% from model-free E2E alone**

Run:
```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100
```
Add only missing behavior scenarios, never exclusions. Run auxiliary tests separately and report all three results independently.

- [ ] **Step 4: Run complete verification**

Run frozen prek, model-free 100% coverage, auxiliary unit/abnormal tests, live collection/skips, wheel build, actionlint, existing shell suite, and `git diff --check`. Record exact counts and the unchanged live acceptance boundary. Commit as `test(e2e): make scenario coverage the primary quality gate`.
