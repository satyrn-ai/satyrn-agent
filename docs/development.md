# Development

## Environment

The repository uses devenv for the system toolchain and uv for locked Python
dependencies. The devenv configuration selects Python 3.14 and prevents uv from
downloading another interpreter.

```bash
devenv shell
uv sync --frozen
uv run --frozen prek install
```

The hook installation is needed once per clone. Use the same uv environment for
Python tools and prek; do not create a separate pre-commit or Pyright setup.
Outside an interactive shell, prefix commands with `devenv shell --`.

## Static quality gate

Run the complete gate from the repository root:

```bash
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
```

The gate includes:

- Ruff safe lint fixes and formatting;
- whole-project ty checks with warnings treated as errors;
- ShellCheck for shell tools and tests;
- the Python-only `TypeGuard` ban;
- TOML, YAML, JSON, and pyproject formatting or validation;
- GitHub workflow schemas, required job timeouts, and actionlint; and
- whitespace, line-ending, merge-conflict, case-conflict, and private-key checks.

Ruff and ty run from `uv.lock`. Remote hooks have pinned revisions in
`.pre-commit-config.yaml`. Patch files and generated lockfiles are excluded from
rewriting hooks. Review and stage any automatic rewrite, then rerun the complete
gate.

Use safe fixes only. Do not use Ruff `--unsafe-fixes`. Keep lint and type
suppressions narrow and include the project contract or checker limitation that
justifies each one.

### ShellCheck

Run only the ShellCheck hook while iterating on shell diagnostics:

```bash
devenv shell -- uv run --frozen prek run shellcheck --all-files --show-diff-on-failure
```

The hook follows sources with `--external-sources`. A dynamic repository-root
`source` needs a repository-relative annotation such as:

```bash
# shellcheck source=tools/ds4-lib.sh
source "$_DS4_LIB_DIR/ds4-lib.sh"
```

Do not change the runtime source path merely to satisfy ShellCheck. Use
`# shellcheck shell=bash` for sourced Bash libraries that intentionally have no
shebang. Literal test data and externally consumed variables can require narrow
SC2016 or SC2034 directives; explain why at each site rather than disabling the
rule for a file.

## Behavioral tests

Run the portable ds4 patch-tooling suite:

```bash
devenv shell -- bash tests/ds4_tools_test.sh
```

The suite covers sync, export, check, shared library behavior, and model-backed
E2E preflight behavior without requiring a model. Run a focused module while
developing, but finish with the complete suite. ShellCheck and Python static
checks do not prove these runtime contracts.

For workflow changes, run:

```bash
devenv shell -- actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
```

For all changes, finish with:

```bash
git diff --check
```

## Patch builds and live models

The README remains the canonical guide for patch-series work and native builds:

- [Sync, edit, and export](../README.md#sync-edit-export)
- [Check](../README.md#check)
- [Build](../README.md#build)
- [Model-backed end-to-end gate](../README.md#model-backed-end-to-end-gate)

Those workflows require the relevant external ds4-py checkout, patched ds4 tree,
or dense qwen35 GGUF. Portable quality and shell checks do not establish native
inference correctness, live replay parity, or DFlash correctness.

## Agent package checks

Run the model-free public-flow E2E suite with its independent line and branch
coverage gate:

```bash
devenv shell -- uv run --frozen pytest tests/e2e/model_free \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

This is the primary Python verification suite. Auxiliary unit/abnormal tests run
separately and do not fill missing E2E branches:

```bash
devenv shell -- uv run --frozen pytest tests/abnormal
```

### Add a scenario

Add a JSON document to `tests/e2e/scenarios/`. Its `expected_branches` declares
the behavior the scenario must reach. The shared runner executes public
`satyrn_agent.open()` and real ds4-py worker/session code; only optional native
bindings are scripted. Do not add scenario-specific expected values to the
runner.

`tests/e2e/schema/scenario.schema.json` is the external contract. After editing
it, regenerate the checked-in TypedDicts:

```bash
devenv shell -- uv run --frozen datamodel-codegen
```

The project uses `practical-py314-20261104`. Review `--recommend-options` when
the schema changes substantially. Generated TypedDicts use no Pydantic models or
TypeAdapter. Handwritten `TypeIs` validators and conversion logic perform
runtime validation. prek rejects stale generated files and invalid scenario
documents.

Build and inspect the wheel:

```bash
devenv shell -- uv build --wheel
unzip -l dist/*.whl | grep 'satyrn_agent/'
```

The package pins ds4-py companion commit
`02562e51589d1db75ba96c23cd05603bf2a248dd`, including tentative decode
transactions and fatal-state poisoning. Rebuild the ds4 ABI manifest after
installing or updating `satyrn_agent`; optional symbols still need a fresh probe
record.

The real patched-engine suite and its required model, drafter, library, and
SHA-256 inputs are documented in `tests/e2e/README.md`. Run it before claiming
native DFlash correctness or live parity. Its 100% coverage requirement is
separate from the portable coverage result, even when both commands report 100%.
