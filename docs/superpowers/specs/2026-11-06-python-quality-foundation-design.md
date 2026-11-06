# Python and shell quality foundation design

| | |
| --- | --- |
| Date | 2026-11-06 |
| Status | Approved, with review amendments |
| Branch | `build/python-quality-foundation` |
| Stacked successor | `feat/agent-package` |
| Related | `docs/superpowers/specs/2026-10-29-agent-package-design.md`; ds4-py PRs #8, #9, and #10 |

## 1. Intent

Establish one strict, reproducible quality workflow before the Satyrn agent
package grows. Match the useful end state of ds4-py's three quality PRs in one
PR because this repository currently has only one Python source file,
`tools/ds4-gguf-arch.py`. Add shell checking because most executable project
logic is Bash. Then implement the agent package on top of this foundation in a
separate stacked branch, governed by the existing agent-package design.

## 2. Goals

- Create a Python 3.14 uv project with a committed `uv.lock` and locked
  development tools.
- Configure Ruff formatting and broad, explicit lint rules; format the existing
  Python tool without unrelated behavioral changes.
- Configure ty with strict diagnostics over Python sources and tests.
- Add `typing-extensions>=4.16.0,<5` as a direct dependency and adopt ds4-py's
  modern typing policy.
- Run Ruff, ty, ShellCheck, configuration validation, and repository hygiene
  checks through prek with a checked-in `.pre-commit-config.yaml`.
- Add a frozen-lockfile CI quality job and retain the existing ds4 tools tests
  and native build checks in their existing `test` job, separate from `quality`.
- Add timeouts, full-SHA Action pins, least-privilege permissions, and disabled
  persisted checkout credentials to `.github/workflows/ds4-tools.yml`.
- Expand `AGENTS.md` and add focused development documentation without
  duplicating the patch-series or live-model guides.
- Leave a clean base for `feat/agent-package`.

## 3. Non-goals and anti-goals

- Do not implement Satyrn's DFlash step, native adapter, capabilities, CLI, TUI,
  or persistence in the quality PR.
- Do not split mechanical Ruff formatting, strict typing, and prek into three
  PRs; the single existing Python file does not justify that overhead.
- Do not replace the existing ds4 patch tooling workflow or weaken its tests.
- Do not add a second Python environment, a second hook runner, Pyright, or a
  Nix-generated pre-commit configuration.
- Do not enable automatic unsafe fixes, blanket suppressions, advisory-only CI,
  or broad rewrites solely to satisfy a checker.
- Do not claim that portable checks prove native inference or live model parity.

## 4. Constraints

- Base the quality branch on current `main`; base `feat/agent-package` on the
  quality branch.
- Keep devenv + uv canonical on macOS and Linux. Enter devenv for project
  commands and prevent uv from downloading another interpreter.
- Use Python 3.14 as the minimum version for type analysis. Pin
  `languages.python.package = pkgs.python314` in `devenv.nix`; the locked
  nixpkgs revision provides Python 3.14.7.
- Keep mechanical formatting separate from behavioral fixes within the PR's
  commit history.
- Preserve patch bytes, generated lockfiles, and existing ds4 command
  contracts. Exclude patch files and generated lockfiles from rewriting hooks.
- ShellCheck findings in existing scripts require minimal safe corrections or
  narrow, justified directives. The existing 49-test shell suite is the
  regression baseline.
- The quality PR has no agent wheel to build yet. Packaging and wheel-content
  checks begin with `feat/agent-package`.

## 5. Approaches considered

### A. Copy ds4-py's three-PR stack exactly

Rejected. A mechanical formatting PR, a typing-remediation PR, and a hook/CI PR
would mostly pass configuration back and forth for one existing Python file.

### B. One quality-foundation PR, then the agent package — selected

Combine Ruff, ty, typing_extensions, prek, ShellCheck, CI, and agent/development
instructions in one reviewable infrastructure PR. Keep runtime package work in
`feat/agent-package`, stacked on it. This preserves the quality/runtime boundary
without empty or nearly empty PRs.

### C. Add Python checks but leave Bash unchecked

Rejected. Bash carries most current repository behavior. Python-only gates would
miss a meaningful class of defects in the patch tools. ShellCheck joins the same
prek gate, with the existing shell suite retained for runtime behavior.

## 6. uv project and dependency design

Create `pyproject.toml` with Satyrn project metadata, Python `>=3.14`, and direct
`typing-extensions>=4.16.0,<5`. Initially treat it as a uv-managed tools project
rather than publishing an empty `satyrn_agent` package. `feat/agent-package`
will add the actual `src/` package build configuration and public entry points.

Use a development dependency group matching ds4-py's tool versions where
applicable: Ruff, ty, prek, and pytest. The configuration source is pinned to
ds4-py commit `c93babb2bb7d4da6575c9a7c1f975f7aefe3b620`, the head of its
quality-gates stack; the implementation plan copies the concrete settings rather
than resolving a moving branch. Commit the resulting `uv.lock`. Use
`uv sync --frozen` and `uv run --frozen` after the lockfile is created; dependency
updates are deliberate lockfile changes, not side effects of checks.

## 7. Ruff and typing design

Set Ruff line length to 120 and use ds4-py's selected categories, explicit
preview-rule policy, formatter-conflict ignores, McCabe limit, safe fixes, and
narrow per-file exceptions. Apply Ruff format and safe lint fixes to
`tools/ds4-gguf-arch.py`. Do not use `--unsafe-fixes`.

Configure ty initially for `tools` and `tests`. Add `src` in
`feat/agent-package` when that directory exists, expanding rather than relaxing
the gate; do not create a placeholder package in the quality PR. Set Python 3.14,
warnings as errors, strict equality and generic narrowing, and ds4-py's explicit
strict rules. Avoid enabling ty's known false-positive-prone rules wholesale.

Adopt these typing policies in `AGENTS.md` and implementation:

- Use standard-library `TypeIs` on Python 3.14; ban `TypeGuard` in both stdlib
  and typing_extensions forms through a dedicated prek `pygrep` hook scoped with
  `types: [python]`, so documentation can name the prohibited API.
- Prefer precise domain types, `TypedDict`, `Protocol`, generics, and `object`
  with runtime narrowing. Confine `Any` to reviewed dynamic boundaries.
- Use lowercase `typing_extensions.sentinel`; use the sentinel object itself in
  unions and identity narrowing, not `Literal[sentinel]`.
- Use `typing_extensions.TypedDict` for `closed` and `extra_items`; use stdlib
  `Required`, `NotRequired`, `ReadOnly`, `Self`, and `override` where applicable.
- Use PEP 695 aliases and generic syntax when they improve contracts. Do not add
  modern typing constructs merely for novelty.
- Keep suppressions narrow and justified. Do not use `cast` or `Any` to hide an
  unmodeled native boundary.

The existing Python tool receives only annotations or validators needed by the
new checks. `TypeIs` and `sentinel` are policies for real contracts, not
artificial usages to add in this infrastructure PR.

## 8. prek and ShellCheck design

Use `.pre-commit-config.yaml` with pinned remote hook revisions and local hooks
for project-locked Python commands. Include:

- Ruff check with safe fixes and Ruff format, both failing when they rewrite a
  file so the developer reviews and restages the result;
- whole-project `ty check`, not changed-file-only checking;
- the independent `TypeGuard` ban;
- ShellCheck through the pinned `shellcheck-py/shellcheck-py` hook;
- `pyproject-fmt`, yamllint, JSON/TOML/YAML checks, stable JSON formatting, and
  general whitespace/hygiene checks;
- GitHub workflow schema, required-timeout checks, and actionlint.

Run ShellCheck over executable shell sources and shell test files. Add
`# shellcheck shell=bash` to the sourced, shebang-less `tools/ds4-lib.sh` so its
Bash constructs are not misdiagnosed as POSIX `sh`. Use source annotations only
where dynamic repository-root paths prevent ShellCheck from resolving a real
sourced file. Do not globally disable source following or a whole warning
category. If a finding exposes a runtime bug, reproduce it with a focused shell
test before changing behavior; otherwise keep the correction mechanical.

Exclude patch content and generated lockfiles from rewriting. Keep one prek
entry point locally and in CI:

```bash
uv run --frozen prek run --all-files --show-diff-on-failure
```

## 9. CI design

Add `.github/workflows/ci.yml` with a read-only, time-bounded `quality` job on
Ubuntu. Use a full-SHA `actions/checkout` pin with `persist-credentials: false`,
the same full-SHA `cachix/install-nix-action` and pinned devenv installation as
the ds4 tools workflow, and run the frozen prek command through
`devenv shell -- ...`. Do not use setup-uv to install a second interpreter.
Install the devenv CLI from the exact NixOS/nixpkgs revision recorded in
`devenv.lock`, rather than the ambient moving `nixpkgs` flake registry.

Update `.github/workflows/ds4-tools.yml` without changing its test scope:

- add `timeout-minutes` to every job;
- pin every Action to a full commit SHA while retaining human-readable version
  comments;
- pin the devenv CLI installation to the NixOS/nixpkgs revision in `devenv.lock`;
- disable persisted checkout credentials for repository and ds4-py checkouts;
- keep the existing shell syntax checks, 49-test shell suite, actionlint, ds4-py
  checkout, and CPU build checks in the existing single `test` job.

The Python quality job is additive. Native builds and model-backed checks keep
their current ownership and limitations.

## 10. AGENTS.md and development documentation

Expand root `AGENTS.md` with the canonical devenv/uv setup, one-time prek hook
installation, complete static and shell test commands, typing/lint policy,
ShellCheck expectations, safe-fix rules, and test-first requirements for
behavioral changes.

Add `docs/development.md` for the quality workflow and links to the existing
README's patch, build, and model-backed instructions. Update README development
navigation only as needed. Do not duplicate detailed ds4 engine workflows in
`AGENTS.md`.

## 11. Stacked agent package

After this design is approved and its implementation plan is complete, create
`feat/agent-package` from `build/python-quality-foundation`. Its implementation
remains governed by `docs/superpowers/specs/2026-10-29-agent-package-design.md`.
It adds the real `src/satyrn_agent` package, typed tests, bindings, configuration,
native adapter, DFlash policy/decode, capabilities, and the prescribed abnormal
and real Metal E2E gates. It does not weaken the quality configuration to make
new code pass.

The agent implementation receives its own detailed plan. Any unresolved ds4-py
companion API or real-model availability issue is reported before code depends
on assumptions.

## 12. Verification

For the quality PR, run from the repository root:

```bash
devenv shell -- uv sync --frozen
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
devenv shell -- uv run --frozen ty check
devenv shell -- bash tests/ds4_tools_test.sh
devenv shell -- actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
git diff --check
```

The shell suite must retain the clean baseline of 49 passed and 0 failed unless
a focused new regression test intentionally increases the count. CI must execute
the equivalent frozen quality command. No live-model success is claimed by this
infrastructure PR.

For `feat/agent-package`, additionally follow the existing design's abnormal,
real Metal E2E, 100% line/branch coverage, wheel, and native parity requirements.
