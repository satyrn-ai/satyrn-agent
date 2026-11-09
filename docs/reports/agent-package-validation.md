# Satyrn agent package validation

Date: 2026-11-09

## Revisions

- Agent implementation at validation: `test/live-metal-e2e` from `origin/main` at
  `c50f2c4fbe7eb87874df64832bdfdde638029beb`
- Quality-foundation base: `60baa62151fdfdd6f1b62ef955bfd6e7b4456ee0`
- ds4-py companion: `5c98c6ac86cafef56780c3bcbb87c3ecaef52aef`
- ds4 upstream pin: `antirez/ds4` at `5379c1c9ac315f1540371b06a3db88491d4059ff`
- ds4 patch series: tracked `patches/common` plus `patches/qwen35`, materialized at
  `~/work/satyrn-live-metal/ds4`; patched commit
  `2a4b3beee29a181c90914e25436eb0e82167465f` on upstream pin
  `5379c1c9ac315f1540371b06a3db88491d4059ff`
- Proposed live identities, requiring PR review approval: target `Qwen3.8-27B-Q4_K_M.gguf`
  (`Q4_K_M`, SHA-256 `e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520`)
  and drafter `dflash-Qwen3.8-27B-Q4_0.gguf` (`Q4_0`, SHA-256
  `0a994382adf17c720c9e5d4292f57344f3b445f058d3e9d5b0f601ae7d6ca3c4`).
  These values are not approved merely because they are pinned for this test run.

## Machine

- Apple M4 Max, `arm64`, 36 GiB RAM
- macOS 15.7.1 (24G309)
- Python 3.14.7 from the locked devenv interpreter
- Live backend: Metal on the Apple M4 Max GPU

## Portable results

All commands ran from the repository root through devenv.

- `uv sync --frozen` — passed.
- `uv run --frozen prek run --all-files --show-diff-on-failure` — passed,
  including Ruff, ty, ShellCheck, configuration, and workflow checks.
- `uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent
  --cov-branch --cov-report=term-missing --cov-fail-under=100 -q` —
  **116 passed; 100% line and 100% branch coverage** over `satyrn_agent`,
  including 59 JSON scenarios and production config-boundary tests through the
  shared public-flow runner.
- `uv run --frozen --no-sync pytest tests/abnormal -q` — **27 passed** in the
  separate exception suite.
- `uv run --frozen pytest tests/e2e/live -q -rA` — **17 passed, 0 skipped** in
  109.72 seconds with the real inputs and GPU lock below.
- `uv build --wheel` — passed; the wheel contains the native adapter, DFlash
  step, engine factory, and `ds4py.bindings` entry-point metadata.
- `actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml` — passed.
- `bash tests/ds4_tools_test.sh` — **49 passed, 0 failed**.
- `git diff --check` — passed.

The 116 model-free tests combine public-flow scenarios with direct parser,
schema, and generation checks. Public scenarios use `satyrn_agent.open()` and
real ds4-py worker/session/decode code; only the external native library is
scripted. The 100% result does not convert those doubles into normal-path
real-engine evidence or use auxiliary unit tests to fill missing branches.

## Real Metal acceptance

The initial implementation run had no live inputs and skipped all 17 tests. This
run used the proposed identities listed above; **PR review must still approve
those identities**. The successful test run is not itself identity approval.

Materialization, build, and ABI check used:

```bash
devenv shell -- env \
  DS4_CACHE_DIR="$HOME/work/satyrn-live-metal/cache" \
  DS4_TREE_DIR="$HOME/work/satyrn-live-metal/ds4" \
  ds4-sync --model qwen35
devenv shell -- uv run --frozen ds4py build \
  --src "$HOME/work/satyrn-live-metal/ds4" --backend metal \
  --out "$HOME/work/satyrn-live-metal/build"
devenv shell -- uv run --frozen ds4py check \
  --lib "$HOME/work/satyrn-live-metal/build/libds4.dylib"
```

The check found 52 required bindings and all eight optional Satyrn bindings, with
known headers and valid layouts. The live workflow rebuilt and checked another
library from this exact tree, then opened that built library in a subprocess and
completed two consecutive public rounds. The subprocess respects ds4-py's
intentional one-native-library-per-process rule.

The live test inputs were:

```bash
export SATYRN_TEST_MODEL="$HOME/models/Qwen3.8-27B-Q4_K_M.gguf"
export SATYRN_TEST_DRAFTER="$HOME/models/dflash-Qwen3.8-27B-Q4_0.gguf"
export SATYRN_TEST_LIB="$HOME/work/satyrn-live-metal/build/libds4.dylib"
export SATYRN_TEST_DS4_SRC="$HOME/work/satyrn-live-metal/ds4"
```

Every live invocation held an exclusive `fcntl` lock on
`/Users/koudai/work/.dflash-locks/gpu`. The final command inside that lock was:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/live -q -rA
```

It produced **17 passed, 0 skipped**. This covers real auto/on/off policy,
explicit-zero and native float32 sampling defaults, repeated rounds, greedy and
seeded serial/speculative parity (tokens, events, metadata, terminal reason, and
RNG continuation), tool-close and parser-error behavior, stop token/sequence,
max-token, native empty-draft/bonus-row, context-reserve, and cancellation cases.
Cancellation is triggered by the real cancellation event during the first verify-row
sample. Full, partial, and mismatch-replacement acceptance are asserted from real
metrics. The corpus pins the actual context and non-thinking settings needed to
reach the parser, stop, and reserve branches. Metrics reconcile with the committed
stream.

### Serial/speculative speed

The latest full-suite timing case used the documented greedy corpus prompt
`Explain speculative decoding in two concise sentences.`, seed 1, and a 48-token
limit. Timing excludes model loading and snapshot setup. A noisy timing change is
not a correctness failure. Both rounds emitted 48 tokens. The run printed this
timing JSON into the retained log:

```json
{
  "machine": "arm64",
  "platform": "macOS-15.7.1-arm64-arm-64bit-Mach-O",
  "backend": "metal",
  "model": "/Volumes/WD_Black_SN8100/models/Qwen3.8-27B-Q4_K_M.gguf",
  "drafter": "/Volumes/WD_Black_SN8100/models/dflash-Qwen3.8-27B-Q4_0.gguf",
  "serial_seconds": 3.11832766700536,
  "speculative_seconds": 1.0575361247174442,
  "serial_tokens": 48,
  "speculative_tokens": 48,
  "drafts_offered": 84,
  "drafts_accepted": 36,
  "replacement_anchors": 9,
  "acceptance_rate": 0.42857142857142855
}
```

| Machine | Backend | Target | Drafter | Serial | Speculative | Speedup | Acceptance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Apple M4 Max, 36 GiB, macOS 15.7.1 | Metal | `Qwen3.8-27B-Q4_K_M.gguf`, Q4_K_M | `dflash-Qwen3.8-27B-Q4_0.gguf`, Q4_0 | 3.118328 s | 1.057536 s | 2.949x | 42.857% |

`tests/e2e/README.md` and `tests/e2e/corpus.json` retain the identities, prompts,
seeds, expected terminal reasons, and branch mapping. The separate model-free
100% result is not used as a substitute for this real-engine evidence.

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
failure. Cleanup failure adds a note without replacing the setup exception.
`decode_step` and `sampling_defaults` expose the selected public policy
without harness access to wrapper internals. Context-fault scenarios use a
`DecodeContext` public-interface test double instead of mutating ds4-py private
state.

The real acceptance modules moved to `tests/e2e/live`. The governing agent
package design now distinguishes the model-free normal-path coverage gate from
real ds4/GGUF/Metal acceptance and limits auxiliary unit tests to parameterized
values and complex exception/external-service doubles.
