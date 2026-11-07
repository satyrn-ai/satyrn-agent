# Production Config JSON Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a schema-driven production configuration boundary with generated TypedDicts and runtime conversion to the existing SatyrnConfig.

**Architecture:** A versioned JSON Schema owns external config shape and constraints. datamodel-code-generator generates TypedDicts through named jobs; handwritten `TypeIs` validation and explicit conversion implement `config_from_dict()` without Pydantic. Existing scenario configs share the schema and use the same production parser.

**Tech Stack:** JSON Schema 2020-12, datamodel-code-generator 0.90.0, TypedDict, TypeIs, Python 3.14, Ruff, ty, pytest, prek.

**Spec:** `docs/superpowers/specs/2026-11-07-production-config-schema-design.md`

## Global Constraints

- Do not use Pydantic BaseModel or TypeAdapter.
- Keep `SatyrnConfig` frozen and slotted; generated TypedDicts are external DTOs only.
- Use `practical-py314-20261104` and review `--recommend-options` output.
- Existing E2E scenarios and production config share one JSON Schema.
- No native work occurs before config validation; real-engine acceptance stays separate.
- Preserve the independent model-free E2E 100% line/branch coverage gate.

## Review Focus

- **Unknown fields and booleans-as-integers:** reject them before constructing config; Task 2 adds focused tests.
- **Nested null and non-finite values:** distinguish missing fields from explicit null and reject non-finite values; Task 2 tests both.
- **Conditional `on` requirement:** require a non-null drafter before native open; Tasks 1–2 pin schema and runtime behavior.
- **Generated drift/shared schema:** prek must check both named jobs and scenarios must use the production schema; Task 1 proves it.
- **Coverage boundary:** existing scenarios exercise `config_from_dict`, with malformed external cases added until model-free E2E alone remains at 100%; Task 3 verifies this.

---

### Task 1: Production schema, shared scenario reference, and generated DTOs

**Files:**
- Create: `schemas/satyrn-config.schema.json`
- Create: `src/satyrn_agent/_generated/{__init__,config}.py`
- Modify: `tests/e2e/schema/scenario.schema.json`
- Modify: `pyproject.toml`, `.pre-commit-config.yaml`

**Interfaces:**
- Produces: `ConfigDocument`, `SamplingOverridesDocument`, and `ThinkBudgetDocument` TypedDicts; named `agent_config` and `e2e_scenario` generation jobs.

- [ ] **Step 1: Write the schema and failing generation test**

Define strict config fields, `additionalProperties: false`, numeric bounds, enum values, and `if/then` requiring non-null `drafter_path` when `dflash` is `on`. Reference it from scenario `config`. Add a test that generated production DTOs are importable and both jobs pass `--check`.

- [ ] **Step 2: Configure named generation and prove RED**

Move the existing generator input/output into `[tool.datamodel-codegen.jobs.e2e_scenario]`; add `jobs.agent_config`. Change prek to `datamodel-codegen --all-jobs --check`. Run the test before generation; expect the production module import to fail.

- [ ] **Step 3: Generate and review both outputs**

Run `--recommend-options` for the production schema and both jobs as applicable, record any justified options, then generate. Review closed/required/optional TypedDicts and shared references. Do not generate Pydantic models.

- [ ] **Step 4: Verify and commit**

Run the generation test, both job checks, Ruff, and ty. Commit as `feat(config): generate production schema types`.

### Task 2: Typed runtime config parser and public conversion

**Files:**
- Create: `src/satyrn_agent/config_io.py`
- Modify: `src/satyrn_agent/__init__.py`, `src/satyrn_agent/config.py`
- Modify: `tests/e2e/model_free/_runner.py`
- Create: `tests/e2e/model_free/test_config_io.py`

**Interfaces:**
- Produces: `config_from_dict(data: object) -> SatyrnConfig`; scenario runner consumes it for every ordinary scenario config.

- [ ] **Step 1: Write failing external-boundary tests**

Test all valid defaults and overrides, explicit zero, path/mode conversion, unknown fields, wrong nested types, explicit null, booleans-as-integers, non-finite values, invalid ranges, and `on` without a drafter. Assert no native open occurs on failure.

- [ ] **Step 2: Confirm RED and implement `config_from_dict`**

Use `TypeIs` validators over `object`, reject unknown keys and invalid nested records, then convert to `DFlashMode`, `Path`, `SamplingOverrides`, `ThinkBudgetConfig`, and `SatyrnConfig`. Reuse generated DTO names and preserve field-specific errors. Keep constructor invariants as the final check.

- [ ] **Step 3: Route existing scenarios through the production parser**

Replace the runner's handwritten ordinary config construction with `config_from_dict`. Keep `raw_config` only for intentionally invalid Python constructor cases.

- [ ] **Step 4: Verify and commit**

Run focused tests, all model-free scenarios, Ruff, and ty. Commit as `feat(config): add schema-driven runtime parsing`.

### Task 3: Documentation, independent 100% gate, review, and PR update

**Files:**
- Modify: `README.md`, `docs/development.md`, `AGENTS.md`, `docs/reports/agent-package-validation.md`

- [ ] **Step 1: Document the public boundary**

Show `config_from_dict`, schema location, typed conversion, no-Pydantic policy, and `datamodel-codegen --all-jobs` regeneration. Record actual test counts and the unchanged live acceptance boundary.

- [ ] **Step 2: Run complete verification**

Run frozen prek, model-free E2E alone at 100% line/branch coverage, auxiliary tests, live collection, wheel build, actionlint, shell suite, and `git diff --check`. Commit as `docs: document production config schema`.

- [ ] **Step 3: Review and publish**

Obtain independent Kimi 3.1 Pro and DeepSeek reviews of the production config changes, verify and fix valid findings, rerun full checks, push `feat/agent-package`, and update existing PR #12.
