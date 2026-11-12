# Instructions for coding agents

Run commands from the repository root. Keep the devenv + uv workflow canonical on
macOS and Linux. Do not install a second Python environment or a second hook
runner.

## Repository

This is the satyrn-agent repository. See `README.md` for the project overview,
current status, patch-tooling workflow, and repository layout.

## Set up the environment

Enter devenv before project commands:

```bash
devenv shell
```

Then synchronize the locked dependencies and install the Git hooks once:

```bash
uv sync --frozen
uv run --frozen prek install
```

The shell is CUDA-free by default. `devenv.nix` adds the pinned CUDA 12.9
toolchain only when `DS4_CUDA=1`, because its closure is about 1.5 GiB and every
Linux CI job enters the same shell. Run CUDA builds and tests through
`tools/ds4-cuda.sh`, which sets the flag:

```bash
tools/ds4-cuda.sh make -C .ds4/tree CUDA_ARCH=sm_86 test-qwen35-cuda-quant
```

`devenv.lock` pins the Nix inputs and Python 3.14 interpreter. `uv.lock` pins
Python tools and packages. `UV_PYTHON_DOWNLOADS=never` prevents uv from
downloading another interpreter.

## Run checks

Run the complete static gate after relevant changes:

```bash
uv run --frozen prek run --all-files --show-diff-on-failure
```

This includes Ruff lint and format, ty, ShellCheck, TOML, YAML, JSON, GitHub
workflow schema checks, actionlint, and the Python-only `TypeGuard` ban. Do not
run only changed files when a change can affect types, formatting, or sourced
shell code elsewhere.

Run the portable shell regression suite:

```bash
bash tests/ds4_tools_test.sh
```

Run the portable Python suite and its coverage gate:

```bash
uv run --frozen pytest tests/e2e/model_free \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
```

See `tests/e2e/README.md` for scenario-driven model-free E2E and the separate
real patched-engine suite. Model-free coverage does not prove live DFlash parity.
Unit tests are auxiliary only: parameterized value validation and complex
doubles required by exceptions or external services. Production external config
uses `schemas/satyrn-config.schema.json`, generated TypedDicts, and
`config_from_dict`; regenerate both named jobs after schema edits. Do not use
Pydantic BaseModel or TypeAdapter.

For workflow changes, also run:

```bash
actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
```

Portable tests do not prove native inference or live model parity. See
[docs/development.md](docs/development.md) and the README for native builds,
backend selection, and live checks.

## Typing and lint policy

- Use `TypeIs`, never `TypeGuard`, for custom type-narrowing validators.
- Prefer precise domain types, `TypedDict`, `Protocol`, and generics. Use
  `object` for unknown values that will be narrowed. Keep `Any` only at reviewed
  dynamic boundaries such as ctypes.
- Use lowercase `typing_extensions.sentinel` and the sentinel object itself in
  unions. Do not use `Literal[sentinel]`.
- Use standard-library `TypeIs`, `override`, `Required`, `NotRequired`, and
  `ReadOnly`. Use `typing_extensions.TypedDict` for `closed` and `extra_items`.
- Use PEP 695 `type` aliases and generic syntax. Use `Never` only for
  non-returning or unreachable paths.
- Validate dynamic values at their boundary instead of casting them throughout
  ordinary modules.
- Use safe fixes only. Never use `--unsafe-fixes`, blanket suppression comments,
  or broad per-file ignores to make a check pass.
- Every suppression must be narrow, specific, and justified by a real checker
  limitation or project contract. Do not change public behavior only to satisfy
  a linter.

## Shell policy

ShellCheck covers tools and shell tests through prek. Keep dynamic `source`
commands accompanied by a repository-relative `shellcheck source=...` directive
when ShellCheck cannot resolve the path itself. Sourced Bash libraries without a
shebang need an explicit `shellcheck shell=bash` directive.

Do not disable source following or warning categories globally. Quote intentional
literal constructs or add a narrowly scoped directive with a reason. Run the shell
suite after ShellCheck-driven edits; static analysis does not replace behavioral
tests.

## Tests

Write a focused failing test before changing runtime behavior. Run it, watch it
fail, implement the smallest change, and run it again. Keep mechanical formatting
and behavioral changes in separate commits.

Run the focused shell module or Python test for the subsystem you change, then
run the complete static gate and portable shell suite. Existing tests must not be
weakened to make a refactor pass.

See `tests/e2e/README.md` for instructions to add model-free scenarios and live
corpus cases, and to review and update inline-snapshot files.

Do not commit generated build output, native libraries, traces, virtual
environments, or local `.devenv` state.
