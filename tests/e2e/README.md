# Real patched-engine acceptance tests

These tests use the actual installed `satyrn_agent`, the pinned ds4-py companion,
a patched `libds4`, and real target/drafter GGUFs. They do not use `FakeNative` or
scripted decode steps. Every round uses the shared token/transcript/native-position
alignment assertion in `tests/conftest.py`.

## Required identity and library inputs

```bash
export SATYRN_TEST_MODEL=/path/to/dense-qwen35.gguf
export SATYRN_TEST_MODEL_SHA256=<full target SHA-256>
export SATYRN_TEST_DRAFTER=/path/to/matching-dflash.gguf
export SATYRN_TEST_DRAFTER_SHA256=<full drafter SHA-256>
export SATYRN_TEST_LIB=/path/to/patched/libds4.dylib
```

For the build/check workflow, also set:

```bash
export SATYRN_TEST_DS4_SRC=/path/to/patched/ds4
```

`tests/e2e/corpus.json` pins prompts, seeds, and the required model/drafter identity
variables. It also maps each corpus case to the normal decode branches it is meant
to reach. If a required branch is not reached on the documented machine, adjust the
corpus and record the result; do not replace that branch with a mock or a coverage
exclusion.

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
