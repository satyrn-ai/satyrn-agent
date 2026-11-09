# Production config JSON Schema design

| | |
| --- | --- |
| Date | 2026-11-07 |
| Status | Draft for review |
| Branch | `feat/agent-package` |
| Related | `docs/superpowers/specs/2026-11-07-e2e-scenario-testing-design.md` |

## Intent

Apply the schema-driven boundary to the actual external Satyrn configuration, not
only to E2E scenarios. Generate TypedDicts from JSON Schema, parse and validate
external values with ordinary Python, and convert them into the existing frozen,
slotted `SatyrnConfig` domain object. Do not use Pydantic models or TypeAdapter.

## Goals

- Add a versioned JSON Schema for `SatyrnConfig`, including DFlash mode, drafter
  path, draft count, sampling overrides, and think budget.
- Generate production TypedDicts with datamodel-code-generator using the existing
  `practical-py314-20261104` preset and Ruff formatting.
- Add `config_from_dict(data: object) -> SatyrnConfig` as the single external
  parsing boundary, using `TypeIs` and explicit conversion before native open.
- Share the production config schema with E2E scenarios rather than maintaining a
  second divergent config contract.
- Preserve current constructor validation and all public behavior.

## Non-goals

- No Pydantic BaseModel or TypeAdapter.
- No JSON representation of native C prototypes or raw pointers.
- No generated replacement for the handwritten frozen, slotted domain config.
- No second configuration path used by existing callers or tests.

## Approaches considered

### Generated TypedDict plus handwritten runtime validation — selected

This matches the existing no-Pydantic decision and keeps the external schema,
static types, runtime validation, and internal domain object clearly separated.

### Generated Pydantic BaseModel

Rejected. Pydantic models are not used in this implementation.

### Keep only the E2E scenario schema

Rejected because it leaves the production external config without the requested
schema-driven boundary.

## Implementation shape

Create `schemas/satyrn-config.schema.json` with `additionalProperties: false`,
strict scalar types, numeric bounds, and the `on` → `drafter_path` requirement.
Use `$defs` for sampling and think-budget records. Reference this schema from the
scenario schema so both boundaries share the same fields.

Use datamodel-code-generator named jobs for the production and scenario outputs:

- production: `src/satyrn_agent/_generated/config.py`;
- E2E: `tests/e2e/scenarios/_generated/scenario_types.py`.

The prek generation hook runs all jobs with `--all-jobs --check`. Generated files
are committed and reviewed.

`config_from_dict` accepts `object`, rejects non-mappings and unknown fields,
uses focused `TypeIs` validators for nested values, then constructs
`DFlashMode`, `Path`, `SamplingOverrides`, `ThinkBudgetConfig`, and
`SatyrnConfig`. The existing constructors remain the final invariant check.
Malformed input fails with a field-specific `ConfigurationError` or `TypeError`;
no native work occurs.

The E2E runner's normal config path calls `config_from_dict`, so existing public
scenarios exercise the production parser. Raw constructor-validation scenarios
remain separate for intentionally invalid Python values.

## Verification

- Test valid config conversion and each malformed external field, including
  booleans-as-integers, unknown keys, invalid ranges, and missing drafter for
  `on`.
- Run model-free E2E alone at 100% line and branch coverage after adding the new
  boundary.
- Run auxiliary unit/abnormal tests, live collection, full prek, wheel,
  actionlint, shell suite, and `git diff --check`.
- Document the public schema/parser and regeneration commands. Keep real native
  acceptance separate and unchanged.
