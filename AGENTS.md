# AGENTS.md

## What this repo is

The downstream agent from the ds4-py design
(`../ds4-py/docs/specs/2026-10-21-ds4-py-design.md`): a customisation of
ds4-py that runs against a patched ds4 engine.

The patch-series design is on branch `docs/ds4-patch-series`
(`docs/specs/2026-10-24-ds4-patch-series-design.md` there) and merges with
the patch tooling slice.

## Invariants

- The ds4 patch series is the source of truth for engine changes. Never
  commit the ds4 source tree, a ds4 submodule, or a materialized `.ds4/`
  scratch tree into this repo.
- Patch files under `patches/` are regenerated from real commits in the
  scratch tree; do not hand-edit them as the normal workflow.
- Work happens in a task worktree under `.worktrees/`.

## Conventions

- devenv mirrors `../ds4-py/devenv.nix`; change them together while this repo
  tracks ds4-py conventions.
- Once `tools/` exists: verify patch changes with `tools/ds4-check.bash`
  before committing; it is the gate that proves the series applies standalone
  to the pinned upstream.

## Verification

For this bootstrap slice there are no automated tests (per the Testing Value
Gate, static config and docs are verified by command, not tests). The check
that must pass before committing changes here:

```
devenv shell -- true
```
