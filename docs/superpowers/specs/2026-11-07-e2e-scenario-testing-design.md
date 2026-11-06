# Scenario-driven E2E testing design

| | |
| --- | --- |
| Date | 2026-11-07 |
| Status | Draft for review |
| Branch | `feat/agent-package` |
| Related | `docs/superpowers/specs/2026-10-29-agent-package-design.md`; `docs/reports/agent-package-validation.md` |

## 1. Intent

Make end-to-end tests the primary verification mechanism for Satyrn behavior.
Exercise the public `satyrn_agent.open()` flow through real ds4-py workers and
sessions, using deterministic model-free scenarios in ordinary CI. Keep unit
tests only for parameterized value checks and for complex doubles required by
exceptions or external services. Grow normal-path scenarios through data rather
than adding scenario-specific test functions and mock plumbing.

## 2. Test categories

### Model-free E2E

Model-free E2E is the main suite and owns the ordinary coverage gate. It uses the
real Satyrn package, real ds4-py `EngineWorker`, `Session`, `DecodeContext`, and
transcript/stream implementation. Only the external native library is replaced
by ds4-py's deterministic `FakeNative` plus scripted optional DFlash bindings.
The public open/session/round flow is always exercised.

These tests establish Python orchestration and decode correctness, not native
inference, ABI, GGUF, Metal, or live numeric parity.

### Real-engine E2E

The existing real patched-engine tests remain a separate acceptance gate for
those native properties. Their skips and missing approved model identities are
never hidden by model-free results. The real suite remains required before the
original design's live Done criteria are claimed.

### Auxiliary unit tests

Keep unit tests only where they provide clear value through parameterized value
validation or where exceptions/external services require complex doubles.
Examples include configuration scalar validation, ctypes return conversion,
missing symbols, native error returns, and commit/cleanup failure injection.

Other behavior moves to scenario-driven E2E. Policy selection, public session
configuration, normal DFlash blocks, stop/cancellation boundaries, capabilities,
and metrics must not depend on unit-only mock flows.

## 3. Goals

- Make model-free E2E the main suite for normal behavior and reach 100% line and
  branch coverage of `satyrn_agent` through that suite.
- Add scenarios without editing the shared runner or adding custom mocks.
- Validate every scenario at load time and check its declared branch coverage
  against observed behavior.
- Preserve auxiliary tests for their narrower purposes without using them to
  inflate the main E2E coverage claim.
- Keep generated scenario models and all new dependencies out of the production
  package's runtime dependencies.
- Keep real-engine acceptance visibly separate.

## 4. Non-goals and anti-goals

- Do not call model-free doubles evidence of native inference or live parity.
- Do not generate the public `SatyrnConfig` or other handwritten runtime domain
  objects from JSON Schema.
- Do not add Pydantic to production dependencies.
- Do not create a second public session/token loop or a Satyrn-specific worker.
- Do not retain parallel handwritten scenario validators, generated models, and
  ad hoc dictionaries for the same JSON documents.
- Do not hide unreached branches with skips, broad expected outcomes, or
  scenario-specific exceptions in the runner.
- Do not move exception-oriented unit tests into scenarios when fault injection
  is their clearest representation.

## 5. Approaches considered

### A. Typed Python scenario objects

Use handwritten frozen dataclasses for scenario definitions. This avoids JSON
Schema and generation but duplicates schema maintenance as scenario shapes grow
and does not provide declarative validation for JSON-authored scenarios.

### B. JSON scenarios, generated Pydantic models, shared runner — selected

Use JSON Schema as the external scenario contract, generate Pydantic v2
BaseModels with datamodel-code-generator, and execute every scenario through one
public-flow runner. Pydantic and datamodel-code-generator are development-only
dependencies. This provides runtime validation, typed scenario access, and a
small addition path for future cases.

### C. JSON scenarios, TypedDict, and TypeAdapter

Generate TypedDict/std-library dataclasses and validate them through a separate
adapter. Rejected because it adds a second validation layer while Pydantic is
already being introduced. BaseModel generation keeps validation in the generated
boundary model.

### D. Handwritten TypedDict and TypeIs validators

Keep the current small validators. Rejected for the larger scenario DSL because
schema and handwritten narrowing would grow together and invite divergence.
TypeIs remains appropriate for focused custom runtime narrowing elsewhere, not
as a duplicate scenario schema.

## 6. Scenario schema and generated models

Create a versioned JSON Schema for model-free scenarios. The schema includes:

- scenario identity, description, and schema version;
- model/backend identity and optional native defaults;
- Satyrn configuration values, including DFlash mode, drafter, draft count,
  sampling overrides, and think budget;
- ordered native script operations and optional per-step faults when a scenario
  is explicitly an abnormal E2E case;
- one or more public rounds with prompt, sampling, stop sequences, cancellation
  instructions, and expected terminal reason;
- expected token/event/transcript/native-position/RNG state;
- expected sampling metadata, parser state, and metrics; and
- `expected_branches`, matched against the shared runner's observed branch set.

Generate test-only Pydantic v2 BaseModels. Generated files are reviewed and
committed. Scenario loading constructs the generated root model directly; no
TypeAdapter or parallel handwritten TypedDict validator is used. Handwritten
checks are limited to cross-field invariants JSON Schema cannot express and to
converting validated scenario data into the handwritten public `SatyrnConfig`.

Pin `datamodel-code-generator==0.90.0`. Start from this configuration and then
apply schema-specific results from `--recommend-options`:

```toml
[tool.datamodel-codegen]
input = "tests/e2e/scenarios/schema.json"
output = "tests/e2e/_generated/scenarios.py"
input-file-type = "jsonschema"
output-model-type = "pydantic_v2.BaseModel"
preset = "standard-py314-20261104"
formatters = ["ruff-check", "ruff-format"]
extra-fields = "forbid"
```

The immutable preset is the latest Python 3.14 preset in the researched 0.90.0
release. Run the recommender against the actual schema, review class-name and
constraint effects, and record additional options rather than enabling every
possible rule. Consider strict scalar handling and generated schema validators
only when the report shows they are needed. Use Ruff for generated-code
formatting and a prek generation/check command to reject stale generated files.

Pydantic and datamodel-code-generator remain in the `dev` dependency group.

## 7. Shared E2E runner

The runner interprets a validated scenario without scenario-specific branches:

1. construct the scripted optional bindings and ds4-py `FakeNative`;
2. call public `satyrn_agent.open()` and obtain the real configured session;
3. execute one or more public rounds and native script operations;
4. record public events, transcript, native position, RNG, sampling metadata,
   parser state, metrics, and the exercised decode branches; and
5. compare all observations with the scenario, failing with scenario name and
   missing branch details when behavior or coverage differs.

`FakeNative` supplies core behavior and deterministic sampling. Optional DFlash
bindings are ordinary callables at the external native boundary, not mocks of
Satyrn's state machine. The same runner supports full/partial draft acceptance,
mismatch/replacement, bonus anchors, zero drafts, stops, cancellation,
consecutive rounds, native defaults, think budget, and parser/tool behavior.

The runner owns no expected result values. All expected behavior lives in the
scenario. Adding a normal scenario requires only a new JSON document and, when a
new branch is introduced, updating the expected-branch registry.

## 8. Layout and migration

```text
tests/e2e/
  schema/                 # versioned scenario JSON Schema
  scenarios/              # independent scenario documents
  _generated/             # checked-in Pydantic models
  model_free/             # shared runner and scenario acceptance tests
  live/                   # real patched-engine acceptance, moved as a group
  corpus.json             # live model identities/prompts during migration
```

Move current real-engine files under `live/` while preserving their fixture
inputs. Move normal public-flow behavior currently covered by unit/abnormal
helpers into JSON scenarios. Retain only justified auxiliary unit tests. Keep
the existing shell suite unchanged.

## 9. Coverage and verification

Run the main model-free E2E suite with its own 100% line and branch gate:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

Run auxiliary unit/abnormal tests separately; their results must not be used to
fill missing E2E branches. Run real-engine acceptance separately with its
required inputs. The final PR reports the three results independently.

Add schema validation tests for malformed scenarios and generated-model drift,
plus a registry completeness check proving every runner branch is claimed by at
least one scenario. These are test-infrastructure checks, not substitutes for
behavioral scenarios.

## 10. Documentation and design update

Update the agent-package design's testing section to distinguish the accepted
model-free E2E normal-path gate from real-engine acceptance. Document scenario
addition, generated-code refresh, coverage commands, and the narrow unit-test
role. Preserve the original native/thread/token invariants and the explicit live
acceptance boundary.
