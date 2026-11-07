# Satyrn E2E tests

## Model-free public-flow scenarios

`tests/e2e/model_free` is the primary suite. JSON scenarios in
`tests/e2e/scenarios/` drive public `satyrn_agent.open()` through real ds4-py
workers and sessions. Only the external native library is replaced by ds4-py's
deterministic `FakeNative` and scripted optional DFlash bindings.

`tests/e2e/schema/scenario.schema.json` is the external contract. Generate
TypedDicts with `uv run --frozen datamodel-codegen` after schema edits. The
project uses `practical-py314-20261104`; use `--recommend-options` for
schema-specific review. Handwritten `TypeIs` validators and conversion logic
perform runtime validation. No Pydantic models or TypeAdapter are used.

Run the independent coverage gate:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

Auxiliary unit tests are limited to parameterized values and complex
exception/external-service doubles. They are not used to fill missing E2E
branches. Model-free coverage is not native inference or live parity evidence.

## Real patched-engine acceptance tests

The tests in `tests/e2e/live` use the actual installed `satyrn_agent`, the pinned
ds4-py companion, a patched `libds4`, and real target/drafter GGUFs. They do not
use `FakeNative` or scripted decode steps. Every round uses the shared
token/transcript/native-position alignment assertion in `tests/conftest.py`.

## Required identity and library inputs

```bash
export SATYRN_TEST_MODEL=/path/to/dense-qwen35.gguf
export SATYRN_TEST_DRAFTER=/path/to/matching-dflash.gguf
export SATYRN_TEST_LIB=/path/to/patched/libds4.dylib
```

For the build/check workflow, also set:

```bash
export SATYRN_TEST_DS4_SRC=/path/to/patched/ds4
```

`tests/e2e/corpus.json` pins prompts, seeds, expected native sampling defaults,
and approved model/drafter SHA-256 and quantization values. The approved values
are currently `null` because no model was available for this implementation run;
fill them from the reviewed GGUFs before enabling live acceptance. An external
hash environment variable cannot substitute for this repository identity check.

The corpus also maps each case to normal decode branches and expected terminal
reasons. Tests load it through typed validators and fail with corpus-adjustment
diagnostics when a required branch is not reached. Do not replace that branch
with a mock, a coverage exclusion, or a post-round skip.

## Run

```bash
devenv shell -- uv run --frozen pytest tests/abnormal tests/e2e/live \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

The real acceptance gate requires this real-engine run. The model-free 100%
coverage result does not replace it. Tests skip with an explicit missing-input
message when the required environment or approved identity is absent.

The parity test saves one real DFlash-mode snapshot, runs serial `PlainStep`, then
restores native/transcript/RNG state and runs `DFlashStep`. It compares token IDs,
stop reasons, RNG continuation, and event types in that same verify mode. It does
not compare DFlash-mode numerics with ordinary decode mode.

Timing is measured externally and recorded with platform, model, and drafter
metadata. There is no wall-time regression assertion.
