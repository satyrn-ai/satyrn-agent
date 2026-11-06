# Python and Shell Quality Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one reproducible Ruff, ty, typing_extensions, prek, ShellCheck, CI, and contributor-workflow foundation without implementing the agent package.

**Architecture:** A uv-managed Python tools project uses the Nix/devenv Python 3.14 interpreter and one lockfile. prek orchestrates local project checks and pinned remote hooks; GitHub Actions runs the same frozen gate through devenv while preserving the existing ds4 tools job. `feat/agent-package` will add the distributable `src/` package later.

**Tech Stack:** Python 3.14.7, uv, Ruff, ty, typing_extensions 4.16, prek, ShellCheck 0.11, Nix/devenv, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-06-python-quality-foundation-design.md`

## Global Constraints

- Run project commands from the repository root through `devenv shell -- ...`.
- Use `pkgs.python314` and keep `UV_PYTHON_DOWNLOADS=never`; do not install a second CI interpreter.
- Mirror ds4-py quality configuration from commit `c93babb2bb7d4da6575c9a7c1f975f7aefe3b620`.
- Use safe Ruff fixes only; never use `--unsafe-fixes` or blanket suppressions.
- Ban `TypeGuard` only in Python files; use stdlib `TypeIs` for real narrowing contracts.
- Use lowercase `typing_extensions.sentinel` and sentinel objects in unions, not `Literal[sentinel]`.
- Keep `src/` out of ty until `feat/agent-package` creates it; do not add a placeholder package.
- Keep the existing ds4 tools checks in one `test` job, separate from the new `quality` job.
- Do not claim live model parity from this infrastructure PR.

## Review Focus

- **Dynamic shell sources:** ShellCheck must analyze real sourced files without rewriting runtime paths; Task 3 adds source directives and reruns all 49 shell tests.
- **Library shell dialect:** `tools/ds4-lib.sh` has no shebang and uses Bash; Task 3 adds a file-level Bash directive and checks that SC2148/SC2039 diagnostics are absent.
- **Literal test fixtures:** command-substitution text and `^{tree}` revisions are intentional; Task 3 uses one narrow SC2016 directive and quotes revision arguments, then runs their focused tests.
- **Generated/patch content:** hooks must not rewrite patches or lockfiles; Task 3 verifies a second prek run produces no diff and `git diff --check` stays clean.
- **CI toolchain drift:** quality and ds4-tools jobs must use the locked nixpkgs revision for devenv; Task 4 checks workflow schema/actionlint and exact full-SHA Action references.

---

### Task 1: Pin Python and establish uv + Ruff formatting

**Files:**
- Modify: `devenv.nix`
- Create: `pyproject.toml`
- Create: `uv.lock`
- Modify: `tools/ds4-gguf-arch.py`

**Interfaces:**
- Consumes: locked nixpkgs revision `8edc0c72e3a38faf5434e40d1f19431125fe4b30` from `devenv.lock`.
- Produces: Python 3.14.7 devenv interpreter; uv project metadata; Ruff line length 120; reproducible `uv run --frozen ruff` command.

- [ ] **Step 1: Pin the devenv interpreter**

Set `languages.python.package = pkgs.python314` in `devenv.nix`. Leave `UV_PYTHON` and `UV_PYTHON_DOWNLOADS` unchanged.

- [ ] **Step 2: Verify the interpreter**

Run: `devenv shell -- python3 --version`
Expected: `Python 3.14.7`.

- [ ] **Step 3: Create the uv tools project**

Create project metadata named `satyrn-agent`, version `0.1.0`, `requires-python = ">=3.14"`, and `[tool.uv] package = false`. Add Ruff `>=0.17.3` to the `dev` dependency group. Set Ruff `line-length = 120`, `lint.preview = true`, and `lint.explicit-preview-rules = true`.

Run: `devenv shell -- uv sync`
Expected: `pyproject.toml` and `uv.lock` resolve successfully without downloading a Python interpreter.

- [ ] **Step 4: Format the existing Python tool**

Run: `devenv shell -- uv run --frozen ruff format tools/ds4-gguf-arch.py`
Then run: `devenv shell -- uv run --frozen ruff format --check tools/ds4-gguf-arch.py`
Expected: the second command reports the file already formatted. Do not change parser behavior.

- [ ] **Step 5: Run the behavioral baseline**

Run: `devenv shell -- bash tests/ds4_tools_test.sh`
Expected: `49 passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add devenv.nix pyproject.toml uv.lock tools/ds4-gguf-arch.py
git commit -m "build: establish uv and Ruff formatting"
```

### Task 2: Enable strict Ruff lint and ty

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tools/ds4-gguf-arch.py`

**Interfaces:**
- Consumes: the uv project from Task 1.
- Produces: `uv run --frozen ruff check tools tests` and `uv run --frozen ty check`; typed GGUF helper signatures `_read_exact(fp: BinaryIO, n: int) -> bytes`, `_read_string(fp: BinaryIO) -> str`, `_skip_value(fp: BinaryIO, value_type: int) -> None`, and `main(argv: Sequence[str]) -> int`.

- [ ] **Step 1: Add direct typing and checker dependencies**

Add production dependency `typing-extensions>=4.16.0,<5`. Add `ty==0.0.95` and `pytest>=9.1.1` to `dev`. Run `devenv shell -- uv lock` and verify `typing-extensions` resolves to 4.16.0 or newer within the constraint.

- [ ] **Step 2: Copy the pinned strict Ruff policy**

Select `ANN`, `ASYNC`, `BLE`, `C90`, `complexity`, `correctness`, `DTZ`, `FBT`, `FURB`, `G`, `LOG`, `performance`, `PGH`, `PIE`, `PL`, `PT`, `PTH`, `PYI`, `RET`, `RSE`, `RUF`, `S`, `SIM`, `SLOT`, `style`, `suspicious`, `TC`, `TID`, `TRY`, `UP`, and `YTT`. Ignore only `COM812`, `E501`, `ISC001`, and `TRY003`; set McCabe maximum complexity to 15. Ban `typing.Any` through `TID251` with the precise-type message from the pinned ds4-py configuration. Add the ds4-py test-tree per-file ignores for future Python tests, excluding rules irrelevant to this repository only when justified in a comment.

- [ ] **Step 3: Configure strict ty**

Set `src.include = ["tests", "tools"]`, `environment.python-version = "3.14"`, `terminal.error-on-warning = true`, `analysis.strict-equality-semantics = true`, and `analysis.strict-generic-narrowing = true`. Copy as errors: `blanket-ignore-comment`, `disjoint-cast`, `dynamic-function-decorator-return`, `invalid-legacy-positional-parameter`, `mismatched-sentinel-name`, `missing-override-decorator`, `missing-type-argument`, `possibly-unresolved-reference`, `redundant-cast`, `redundant-condition-strict`, `truthiness-test-of-none-union`, `unsound-assignment`, `unsound-return-statement`, `unsound-yield`, `unsupported-dynamic-base`, and `unused-ignore-comment`.

- [ ] **Step 4: Type the GGUF reader without changing its CLI**

Annotate the four interfaces above using `BinaryIO` and `Sequence`; use `Path.open("rb")` for the input path. Keep all output strings, return codes, GGUF parsing, and exception handling unchanged. Do not introduce artificial `TypeIs` or sentinel usage.

- [ ] **Step 5: Run static and behavioral checks**

Run:
```bash
devenv shell -- uv run --frozen ruff check tools tests
devenv shell -- uv run --frozen ruff format --check tools tests
devenv shell -- uv run --frozen ty check
devenv shell -- bash tests/ds4_tools_test.sh
```
Expected: all static commands exit 0; shell baseline remains `49 passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tools/ds4-gguf-arch.py
git commit -m "build: enforce strict typing and lint rules"
```

### Task 3: Add prek, configuration checks, and ShellCheck

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.yamllint.yaml`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tools/ds4-lib.sh`
- Modify: `tools/ds4-check.sh`
- Modify: `tools/ds4-export.sh`
- Modify: `tools/ds4-sync.sh`
- Modify: `tests/ds4_test_helpers.sh`
- Modify: shell test files with source, module-registry, literal, or revision diagnostics

**Interfaces:**
- Consumes: locked Ruff and ty commands from Task 2.
- Produces: `uv run --frozen prek run --all-files --show-diff-on-failure` as the complete static gate.

- [ ] **Step 1: Add prek and the pinned hook configuration**

Add `prek==0.5.7` to `dev` and lock it. Mirror the pinned ds4-py hooks for hygiene, TOML/YAML/JSON, pyproject-fmt, yamllint, GitHub workflow schemas/timeouts, and actionlint. Exclude `patches/`, `uv.lock`, and `devenv.lock` from rewriting. Add local Ruff check/format hooks using `uv run --frozen`, safe fixes only, and failure on rewrites. Add whole-project ty with `pass_filenames: false`, `always_run: true`, and the `TypeGuard` pygrep hook with `types: [python]`.

- [ ] **Step 2: Add ShellCheck with repository-local source resolution**

Add `https://github.com/shellcheck-py/shellcheck-py` at `v0.11.0.1`, hook `shellcheck`, with `--external-sources`. Add `# shellcheck shell=bash` to `tools/ds4-lib.sh`. Add `source=tools/ds4-lib.sh` or `source=tests/ds4_test_helpers.sh` immediately before each dynamic `source` command as appropriate. Do not disable SC1091 globally.

- [ ] **Step 3: Resolve the known intentional-construct diagnostics**

Quote every Git `refs/...^{tree}` argument flagged by SC1083. Keep the malicious-pin literal `$(touch ...)` unexpanded and annotate only that assignment with SC2016 disabled and a reason. Scope SC2034 directives to `ds4_state_read` outputs, test setup globals consumed by sourced library functions, and each `DS4_MODULE_TESTS` registry consumed by the runner; include a short reason. Do not add a file-wide SC2034 exemption.

- [ ] **Step 4: Run ShellCheck and focused behavior tests**

Run:
```bash
devenv shell -- uv run --frozen prek run shellcheck --all-files --show-diff-on-failure
devenv shell -- bash tests/ds4_tools_test.sh
```
Expected: ShellCheck exits 0 with no remaining diagnostics; all 49 tests pass.

- [ ] **Step 5: Run the complete hook gate twice**

Run:
```bash
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
git diff --check
```
Expected: the first run either passes or reports only reviewed automatic rewrites; after staging those rewrites, the next run passes without changing files. No patch or lockfile is reformatted.

- [ ] **Step 6: Commit**

```bash
git add .pre-commit-config.yaml .yamllint.yaml pyproject.toml uv.lock tools tests
git commit -m "build: add prek and ShellCheck quality gate"
```

### Task 4: Add CI quality and harden ds4-tools Actions

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `.github/workflows/ds4-tools.yml`

**Interfaces:**
- Consumes: complete prek gate and locked nixpkgs revision.
- Produces: separate `quality` and existing `test` jobs with full-SHA Actions, explicit timeouts, pinned devenv CLI, and no persisted checkout credentials.

- [ ] **Step 1: Create the quality workflow**

Use `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (`v7`) with `persist-credentials: false`, and `cachix/install-nix-action@d9186cbdca7adedf113a159fa91f725a27866771` (`v31`). Install devenv with `nix profile add --accept-flake-config github:NixOS/nixpkgs/8edc0c72e3a38faf5434e40d1f19431125fe4b30#devenv`. Run `devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure`. Set read-only contents permission, explicit quality-job timeout, bash defaults, and the same push/pull-request triggers as the existing workflow.

- [ ] **Step 2: Harden the existing ds4 tools job**

Pin both checkout uses and install-nix-action to the SHAs above with version comments. Add `persist-credentials: false` to both checkouts, including the ds4-py checkout. Add a job timeout and replace ambient `nixpkgs#devenv` installation with the pinned install command from Step 1. Preserve all existing test/build commands and the single-job topology.

- [ ] **Step 3: Validate workflow configuration**

Run:
```bash
devenv shell -- actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
```
Expected: actionlint and every workflow/schema/timeout hook pass; all Actions use 40-character commit SHAs.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/ds4-tools.yml
git commit -m "ci: add frozen quality job and pin Actions"
```

### Task 5: Document the canonical workflow and verify the branch

**Files:**
- Modify: `AGENTS.md`
- Create: `docs/development.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all commands from Tasks 1–4.
- Produces: contributor and agent instructions for setup, static checks, shell tests, typing, ShellCheck, and native/live verification boundaries.

- [ ] **Step 1: Write AGENTS.md policy**

Document `devenv shell`, one-time `uv sync --frozen` and `uv run prek install`, the complete prek gate, `bash tests/ds4_tools_test.sh`, safe fixes, narrow suppressions, modern typing (`TypeIs`, lowercase `sentinel`, TypedDict/PEP 695), dynamic-boundary `Any`, and focused test-first behavioral changes. State that portable checks do not prove live model parity.

- [ ] **Step 2: Add development documentation**

In `docs/development.md`, record setup, hook installation, static commands, ShellCheck/source-directive expectations, shell suite, workflow validation, and links to README patch/build/model-backed sections. Add a concise README link to the development guide without duplicating its existing native instructions.

- [ ] **Step 3: Run final verification**

Run:
```bash
devenv shell -- uv sync --frozen
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
devenv shell -- uv run --frozen ty check
devenv shell -- bash tests/ds4_tools_test.sh
devenv shell -- actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
git diff --check
```
Expected: every command exits 0; shell suite reports `49 passed, 0 failed`; worktree contains no generated build artifacts.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/development.md README.md
git commit -m "docs: document strict quality workflow"
```

- [ ] **Step 5: Review and publish**

Review the complete diff against the spec, obtain independent Kimi 3.1 Pro and DeepSeek implementation reviews, and correct only verified findings. Push `build/python-quality-foundation`, open its PR to `main`, then create `feat/agent-package` from this branch for the separately planned stacked implementation.
