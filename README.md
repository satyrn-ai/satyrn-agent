# satyrn-agent

The downstream agent from the ds4-py design: a customisation of ds4-py that
runs against a patched ds4 engine (dense qwen35 on Metal, DFlash speculative
decode).

Status: patch-series tooling. `ds4-sync`, `ds4-export`, and `ds4-check` are
registered as devenv commands and also run standalone from `tools/`. The
patch series is now the per-model layout: `patches/common/` (model-independent
host extensions and Metal language-version pins) plus `patches/qwen35/` (the
dense qwen35 policy and implementation). The migrated series reconstructs the
same Git tree and filesystem bytes as the former flat ten-patch bootstrap
series, and the tools are exercised against the repo's own series in addition
to the test suite.

## Layout

- `patches/` — the ds4 patch series against `antirez/ds4` at the commit in
  `upstream.pin`. Split into `common/` plus one directory per model; apply
  `common/` first, then model directories in name order.
- `tools/` — the Bash patch-series tools (`ds4-sync`, `ds4-export`,
  `ds4-check`) and their shared library.
- `docs/specs/2026-10-24-ds4-patch-series-design.md` — the governing design,
  including the §6 workflow and the migration plan.
- `.ds4/` — gitignored scratch trees (upstream cache, editable tree, pristine
  check clones, export candidates) materialized by the tools.
- `upstream.pin` — the pinned upstream URL and commit.

## Develop

devenv provides the toolchain (C, Python + uv from Nix) and registers the
three tool entry points. After cloning:

```
direnv allow    # or: devenv shell
```

The commands below are available inside the devenv shell and through
`devenv shell -- <command>`.

### Sync, edit, export

```
ds4-sync --common-only          # or --model NAME, or omit to materialize every model
# edit the checked-out tree under .ds4/tree
ds4-export                      # regenerate the owned patch directory
```

`ds4-sync` materializes `.ds4/tree` from the pinned upstream and applies the
selected patch target. `ds4-export` regenerates the owned patch directory from
the linear commits recorded in the tree; it refuses dirty or unexported work
unless `--force`.

### Check

```
ds4-check                       # common + every model prefix from pristine clones
ds4-check --model NAME          # a single target
```

`ds4-check` reconstructs each selected target from a pristine clone of the
pinned upstream. Run it before committing patch changes.

### Build

Building requires an external ds4-py checkout; ds4-py is not a dependency of
this repo. Select it with `DS4PY_PROJECT`, install its environment, and expose
its `ds4py` command:

```
export DS4PY_PROJECT=/path/to/ds4-py
devenv shell
uv sync --project "$DS4PY_PROJECT"
export PATH="$DS4PY_PROJECT/.venv/bin:$PATH"
ds4-check --build
```

`ds4-check --build` runs `ds4py build --src <tree>` for each checked tree,
using the Metal backend on macOS and the CPU backend elsewhere.
