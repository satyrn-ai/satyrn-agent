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
- `uv run --frozen pytest tests/unit tests/abnormal --cov=satyrn_agent
  --cov-branch --cov-report=term-missing --cov-fail-under=100 -q` —
  **113 passed; 100% line and 100% branch coverage** over `satyrn_agent`.
- `uv run --frozen --no-sync pytest tests/unit tests/abnormal tests/e2e -q` —
  **113 passed, 17 skipped**. Every skip is a real patched-engine test whose
  required model, drafter, library, or approved repository identity is absent.
- `uv build --wheel` — passed; the wheel contains the native adapter, DFlash
  step, engine factory, and `ds4py.bindings` entry-point metadata.
- `actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml` — passed.
- `bash tests/ds4_tools_test.sh` — **49 passed, 0 failed**.
- `git diff --check` — passed.

The 113 portable tests use real ds4-py decode context/state code and real
Satyrn state-machine code. Scripted doubles are confined to abnormal native,
failure, and policy boundaries. This result does not convert those doubles into
normal-path real-engine evidence.

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
injection prohibition. Its unit tests separately prove that the hook only biases
logits and never appends transcript content.
