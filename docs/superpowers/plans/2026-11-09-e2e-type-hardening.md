# E2E Type Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make corpus branch names, terminal reasons, model hashes, metric snapshots, and output assertions stricter without changing runtime E2E behavior or JSON formats.

**Architecture:** Keep handwritten closed TypedDicts and TypeIs validators at the existing test boundaries. Use Literal aliases for finite domain values, overload the output helper for text versus mappings, and validate metric snapshots before inline-snapshot comparison. No datamodel-code-generator changes are needed.

**Tech Stack:** Python 3.14, `typing.Literal`, `typing.TypeIs`, `typing_extensions.TypedDict`, pytest, inline-snapshot, Ruff, ty, uv.

**Spec:** `docs/superpowers/specs/2026-10-29-agent-package-design.md` §§15.1–15.4 and the current user-approved 1–4 type-hardening scope.

## Global Constraints

- Preserve all JSON schemas, runtime E2E behavior, and existing valid corpus/snapshot files.
- Use `TypeIs`, never `TypeGuard`; use closed TypedDicts and Protocols instead of Pydantic.
- Keep `DrafterSettings` and `corpus_config`/`corpus_sampling` interfaces unchanged.
- Do not add datamodel-code-generator jobs, mocks, skips, or coverage exclusions.
- Each behavior change starts with a focused failing test and finishes with model-free 100% line/branch coverage, abnormal/unit tests, prek, and the real Metal suite where applicable.

## Review Focus

- Unknown or misspelled branch/terminal labels must fail corpus validation rather than disappearing into `require_branches`.
- SHA-256 values must be exactly 64 lowercase hexadecimal characters.
- Metric snapshots must contain all five nonnegative integer counters with no missing fields.
- `assert_output` must reject unsupported output types while preserving existing text and mapping behavior.
- Existing valid fixtures and runtime sampling behavior must remain unchanged.

---

### Task 1: Literal branch and terminal domains

**Files:**
- Modify: `tests/e2e/corpus.py`
- Modify: `tests/e2e/live/test_dflash_boundaries.py`
- Modify: `tests/unit/test_corpus.py`

**Interfaces:**
- Produces: `type Branch = Literal[...]`, `type TerminalReason = Literal[...]`; `CorpusCase.branches: list[Branch]`; `CorpusCase.expected_reason: NotRequired[TerminalReason]`; `metric_branches(...) -> set[Branch]`; `require_branches(..., reached: set[Branch]) -> None`.

- [ ] **Step 1: Add failing validation tests** for an unknown branch and an unknown `expected_reason`.
- [ ] **Step 2: Run the tests and confirm they fail** because both values are currently accepted.
- [ ] **Step 3: Implement Branch/TerminalReason and TypeIs checks**, then update reached-set annotations without changing valid labels.
- [ ] **Step 4: Run focused tests and prek**, fixing any set-literal inference issues in call sites.

### Task 2: Strict SHA-256 identities

**Files:**
- Modify: `tests/e2e/corpus.py`
- Modify: `tests/unit/test_corpus.py`

**Interfaces:**
- Produces: `type Sha256 = str`; `is_sha256(value: object) -> TypeIs[Sha256]`, accepting exactly 64 lowercase hex characters.

- [ ] **Step 1: Add failing tests** for 63 characters, uppercase hex, and non-hex input.
- [ ] **Step 2: Confirm current identity validation accepts those values**, then implement the regex/TypeIs check in both identity validators.
- [ ] **Step 3: Run focused tests and prek** while preserving the two pinned hashes.

### Task 3: Typed metric snapshots

**Files:**
- Modify: `tests/e2e/corpus.py`
- Modify: `tests/conftest.py`
- Modify: `tests/e2e/live/test_metrics.py`
- Modify: `tests/unit/test_corpus.py`

**Interfaces:**
- Produces: `ExpectedMetrics` with `committed_blocks`, `drafts_offered`, `drafts_accepted`, `replacement_anchors`, `discarded_tails` as `int`; `is_expected_metrics(value: object) -> TypeIs[ExpectedMetrics]`; `assert_metrics(metrics: DFlashMetrics, expected_path: Path) -> None`.

- [ ] **Step 1: Add failing tests** for missing, negative, and non-integer counters.
- [ ] **Step 2: Implement ExpectedMetrics and assert_metrics**, validating the snapshot JSON before calling `assert_output(asdict(metrics), expected_path)`.
- [ ] **Step 3: Replace direct metric assert_output calls** and run focused tests plus prek.

### Task 4: Output overloads and final verification

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/unit/test_corpus.py` or a focused output-helper test module
- Modify: `docs/reports/agent-package-validation.md`

**Interfaces:**
- Produces: `assert_output(output: str, expected_path: Path) -> None` and `assert_output(output: Mapping[str, object], expected_path: Path) -> None` overloads with the existing `object` implementation.

- [ ] **Step 1: Add failing runtime tests** proving unsupported scalar output is rejected while text and mappings remain valid.
- [ ] **Step 2: Add overloads**, keeping inline-snapshot comparison and line-ending behavior unchanged.
- [ ] **Step 3: Run unit/model-free/abnormal/shell/prek/actionlint/build/diff checks and the full live suite** with the GPU lock.
- [ ] **Step 4: Refresh report evidence, commit locally, and push the existing follow-up branch** without naming review models in the PR body.
