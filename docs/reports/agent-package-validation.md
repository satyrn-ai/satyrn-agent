# Satyrn agent package validation

Date: 2026-11-06

## Revisions

- Agent implementation at validation: `feat/agent-package` worktree before publication
- Quality-foundation base: `60baa62151fdfdd6f1b62ef955bfd6e7b4456ee0`
- ds4-py companion: `02562e51589d1db75ba96c23cd05603bf2a248dd`
- ds4 upstream pin: `antirez/ds4` at `5379c1c9ac315f1540371b06a3db88491d4059ff`
- ds4 patch series: tracked `patches/common` plus `patches/qwen35`; no live tree was materialized for this run

## Machine

- Apple `arm64`
- macOS 15.7.1 (24G309)
- Python 3.14.7 from the locked devenv interpreter
- Required live backend: Metal (not exercised in this run)

## Portable results

All commands ran from the repository root through devenv.

- `uv sync --frozen` — passed.
- `uv run --frozen prek run --all-files --show-diff-on-failure` — passed,
  including Ruff, ty, ShellCheck, configuration, and workflow checks.
- `uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent
  --cov-branch --cov-report=term-missing --cov-fail-under=100 -q` —
  **114 passed; 100% line and 100% branch coverage** over `satyrn_agent`,
  including 58 JSON scenarios and production config-boundary tests through the
  shared public-flow runner.
- `uv run --frozen --no-sync pytest tests/unit tests/abnormal -q` — **60 passed**
  in the separate auxiliary unit/exception suite.
- `uv run --frozen --no-sync pytest tests/e2e/live -q` — **17 skipped**. Every
  skip is a real patched-engine test whose required model, drafter, library, or
  approved repository identity is absent.
- `uv build --wheel` — passed; the wheel contains the native adapter, DFlash
  step, engine factory, and `ds4py.bindings` entry-point metadata.
- `actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml` — passed.
- `bash tests/ds4_tools_test.sh` — **49 passed, 0 failed**.
- `git diff --check` — passed.

The 114 model-free tests combine public-flow scenarios with direct parser,
schema, and generation checks. Public scenarios use `satyrn_agent.open()` and
real ds4-py worker/session/decode code; only the external native library is
scripted. The 100% result does not convert those doubles into normal-path
real-engine evidence or use auxiliary unit tests to fill missing branches.

## Live acceptance boundary

No `SATYRN_TEST_MODEL`, `SATYRN_TEST_DRAFTER`, or `SATYRN_TEST_LIB` inputs were
available, and no GGUF files were found on the workstation. Approved target and
drafter SHA-256/quantization values in `tests/e2e/corpus.json` consequently remain
`null`; external hashes cannot override that repository identity gate. The real
Metal E2E suite therefore was not run. The following design acceptance claims remain
unverified:

- all eight ABI probes against a built patched library;
- real auto/on/off policy and repeated native rounds;
- serial/speculative parity from a real DFlash-mode snapshot;
- real stop/tool/parser/reserve/cancellation boundaries and RNG continuation;
- native sampling and think-budget effects on real samples;
- committed metrics and external serial/speculative timing; and
- the real-normal-path 100% coverage gate.

`tests/e2e/README.md` and `tests/e2e/corpus.json` define the required identities,
commands, prompts, seeds, expected terminal reasons, and enforced branch mapping
for that later run. The portable 100% result is not represented as the design's
live Done criterion.

## Review remediation

Independent reviews by Kimi 3.1 Pro and DeepSeek were evaluated against the
native patch and ds4-py contracts. Changes made after that review include:

- poison every native draft/verify exception after discarding without
  publication, because the patched graph failure path invalidates the native
  checkpoint;
- validate native sampling ranges as well as finite values;
- make consecutive-round alignment use per-round assistant offsets;
- require exact live terminal reasons and reached branches, including zero
  drafts, parser error, context reserve, and cancellation;
- compare full normalized event sequences and canonical-plus-staged metadata;
- open the exact ABI-built library for consecutive public rounds; and
- reject sessions on a closed wrapper and preserve the `on` policy's missing
  drafter check.

The soft think-budget test intentionally does not require the closing marker to
be absent: the capability is a soft bias, not a guaranteed stop or token
injection prohibition. Its tests separately prove that the hook only biases
logits and never appends transcript content.

## Production config schema

`schemas/satyrn-config.schema.json` now defines the actual external Satyrn config,
including nested sampling/think-budget values and the `on` drafter requirement.
Named datamodel-code-generator jobs generate production and scenario TypedDicts
with `practical-py314-20261104`; prek checks both with `--all-jobs --check`.
The scenario schema references the production schema rather than duplicating it.

`config_from_dict()` validates external `object` input with handwritten `TypeIs`
logic and converts it to the existing frozen, slotted `SatyrnConfig`. Existing
ordinary scenarios use this production parser. No Pydantic BaseModel or
TypeAdapter is used.

## Production config review remediation

The second Kimi/DeepSeek review led to additional fixes: reject empty drafter
paths for `on`, use `ConfigurationError` for external value failures, accept
read-only mappings, normalize oversized-number failures, align the scenario
validator with the production drafter rule, and test that conversion failures do
not open native code. The report distinguishes direct parser/schema/generation
checks from public-flow scenarios.

## Scenario-driven E2E migration

The primary suite is now model-free public-flow E2E. A versioned JSON Schema and
datamodel-code-generator 0.90.0 with `practical-py314-20261104` produce the
scenario TypedDicts. `jsonschema` validates scenario documents against the
versioned schema, followed by explicit list-to-set conversion. Pydantic models
and TypeAdapter are not used. prek checks scenario documents and generated-model
drift.

## PR review remediation

The PR #12 review reduced duplicate validation and test doubles while preserving
the model-free gate. Numeric rules now live in the domain constructors, native
capability names derive from `bindings.py`, and DFlash publication has one
failure/poison path. Session setup claims and closes its session atomically on
failure. `decode_step` and `sampling_defaults` expose the selected public policy
without harness access to wrapper internals. Context-fault scenarios use a
`DecodeContext` public-interface test double instead of mutating ds4-py private
state.

The real acceptance modules moved to `tests/e2e/live`. The governing agent
package design now distinguishes the model-free normal-path coverage gate from
real ds4/GGUF/Metal acceptance and limits auxiliary unit tests to parameterized
values and complex exception/external-service doubles.
