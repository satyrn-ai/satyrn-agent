# Real patched-engine acceptance tests

These tests use the actual installed `satyrn_agent`, the pinned ds4-py companion,
a patched `libds4`, and real target/drafter GGUFs. They do not use `FakeNative` or
scripted decode steps. Every round uses the shared token/transcript/native-position
alignment assertion in `tests/conftest.py`.

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
devenv shell -- uv run --frozen pytest tests/abnormal tests/e2e \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

The design's 100% line/branch gate requires this real-engine run. A portable
`tests/unit tests/abnormal` run is useful regression evidence but does not satisfy
that gate. Tests skip with an explicit missing-input message when the required
environment is absent.

The parity test saves one real DFlash-mode snapshot, runs serial `PlainStep`, then
restores native/transcript/RNG state and runs `DFlashStep`. It compares token IDs,
stop reasons, RNG continuation, and event types in that same verify mode. It does
not compare DFlash-mode numerics with ordinary decode mode.

Timing is measured externally and recorded with platform, model, and drafter
metadata. There is no wall-time regression assertion.
