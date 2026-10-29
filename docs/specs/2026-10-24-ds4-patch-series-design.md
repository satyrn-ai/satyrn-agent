# ds4 patch series: repo bootstrap design

| | |
| --- | --- |
| Date | 2026-10-24, updated 2026-10-26 to match the series that landed in #3 |
| Status | Accepted. The initial series is in `patches/` (#3) |
| Upstream | `https://github.com/antirez/ds4` pinned at `5379c1c9ac315f1540371b06a3db88491d4059ff` (2026-10-19), the upstream ds4-py pins |
| Migration source | `https://github.com/pauleveritt/ds4.git` at `3e61e09`, the fork's merge of upstream `5379c1c`. Its carried commits are `0aaea5a..cfb2faf` |
| Related | `ds4-py/docs/specs/2026-10-21-ds4-py-design.md` §18–19 (the downstream agent and the `libds4` build this repo feeds) |

## 1. Intent

satyrn-agent will hold the downstream agent described in the ds4-py spec: a
customisation of ds4-py that runs against a patched ds4 engine. Before any
agent code exists, this repo must own the ds4 patches.

Until now the patches lived as commits on branches of the `pauleveritt/ds4`
fork. That made the fork the source of truth and forced consumers to track a
moving source tree. Instead, this repo holds **discrete patch files against
upstream ds4** plus the tooling to apply, edit, verify and build them. All ds4
patch work happens in this repo from now on; the fork is frozen.

## 2. Scope of the initial series

The initial series carries the fork's own commits, rebased onto `5379c1c` and
grouped by topic:

- Source: the 39 non-merge commits in `0aaea5a..cfb2faf`, less the three Q5_K
  commits for the 9B and 4B (`14c3c7e`, `946a0ad`, `cfb2faf`). That is the
  same set of commits as `ds4-engine` main's gitlink `ebdcb0f`.
- Result: ten patches on disk: the nine migrated patches below (16 files,
  +8,306/−61 against `5379c1c`) plus 0010, the macOS 15 Metal fix from #4
  (+9/−2).
- Held back: the Q5_K commits as a ready model-local qwen35 follow-up, until
  Paul decides whether the 9B and 4B stay.
- Left out of every patch: the llama.cpp parity scripts and notes
  (`tests/qwen35_parity/`, `docs/QWEN35_DENSE.md`, 394 lines). They compare
  against llama.cpp and are not engine code.
- Excluded: the 13 newer commits on `qwen35-cuda-port` (the CUDA port and
  parity work) and every other fork branch.

| # | Patch | Carried commits | Upstream |
| --- | --- | --- | --- |
| 0001 | dense qwen35 on the Metal graph | `591c6a0`, `6a015c6`, `3ffc922` | not offered, fork only |
| 0002 | Qwen chat special tokens and documented sampling | `480df32`, `14212a9` | offer, after narrowing it so tool text stays plain |
| 0003 | dense qwen35 payloads and snapshots | `2d90d19`, `d4bd58d` | not offered, fork only |
| 0004 | host extensions (`ds4_engine_sampling_defaults`, `ds4_session_supports_payload`) | `8b70f74` | offer with the `libds4` target |
| 0005 | verify mode | `0b5f915` … `b3d766f` (11) | not offered, fork only |
| 0006 | DFlash drafter | `4fff88b` … `6d2c2d0` (7) | not offered, fork only |
| 0007 | prefill flash attention | `334a9a3`, `6d985f6`, `dccb545` | not offered, fork only |
| 0008 | kernel follow-ups for the drafter and verify | `b00831d`, `17a9818`, `2fefe5f` | not offered, fork only |
| 0009 | Metal 4.0 shaders on SDK and OS 26 (Paul's patch) | `ebdcb0f` | offer, together with the macOS 15 fix in #4 |

Each patch's message carries `Upstream:`, `Retire-when:` and
`Carried-commits:`, so the series is its own ledger.

## 3. Goals, non-goals, anti-goals

### Goals

1. `patches/` holds common and per-model series as numbered `git format-patch`
   files. Each target applies common and then a deterministic prefix of the
   model directories to the pinned upstream commit with plain `git am` — no
   fork object store required. The full prefix includes every supported model.
2. `upstream.pin` records the upstream URL and commit.
3. One command materializes common-only, a model prefix, or the full multi-model
   tree in a gitignored working tree for day-to-day editing; one command exports
   its commits back to the correct directory; one command verifies each target
   from a pristine upstream clone; ds4-py builds `libds4` from the real tree.
4. devenv supplies every tool the workflow needs; conventions mirror ds4-py.
5. The original migration is verified: the nine migrated patches, with the
   held-back Q5_K patch (then the tenth), give a tree byte-identical to the
   fork's `3e61e09`, apart from the left-out parity scripts and notes. The
   later 0010 macOS 15 fix is outside that fork-equivalence comparison.

### Non-goals

- Moving the pin past `5379c1c`. Upstream is at `ee7e840` (2026-10-21) and
  later. Catching up is a separate, verifiable step.
- The Python downstream-agent package, ds4-py integration, CI wiring, and any
  change to how ds4-engine consumes the engine. All follow-ups.
- Publishing patch-derived branches back to the fork.

### Anti-goals

- Committing the ds4 source tree (or a submodule of it) into this repo.
- Hand-editing patch files as the normal workflow. Patches are regenerated
  from real commits in the scratch tree.
- Patches that only apply with the fork's objects present (no `git am -3`
  dependency).
- A second copy of build logic: ds4-py owns `Makefile.lib` and build behavior;
  satyrn-agent only materializes the source tree and optionally passes build
  options through to ds4-py.

## 4. Constraints

- The Metal backend loads its kernels relative to the ds4 checkout, so the
  patched tree must be a real directory at run time. The scratch tree layout
  satisfies this; a Nix-store-only source would not.
- Per the project testing policy, the tooling is verified by running it
  (`ds4-check` is the gate), not by unit tests asserting script structure.

## 5. Repo layout

```
satyrn-agent/
├── .envrc                  # direnv → devenv (same as ds4-py)
├── .gitignore              # .devenv/, .direnv/, .ds4/, .worktrees/, build outputs
├── devenv.nix
├── devenv.yaml             # nixpkgs rolling input (same as ds4-py)
├── README.md               # the three-command workflow
├── upstream.pin            # UPSTREAM_URL=…, UPSTREAM_COMMIT=…
├── patches/
│   ├── common/             # model-independent numbered format-patch files
│   ├── qwen35/             # Qwen policy and dense-qwen35 implementation
│   └── mellum/             # added later
├── tools/                  # not written yet
│   ├── ds4-sync.sh        # materialize common-only, a prefix, or all models
│   ├── ds4-export.sh      # transactionally regenerate the owned directories
│   ├── ds4-check.sh       # pristine-clone verification (the gate)
│   └── ds4-build.sh       # optional pass-through to ds4py build --src
└── docs/
    └── specs/2026-10-24-ds4-patch-series-design.md  (this file)
```

## 6. The workflow

### Patch layout and model selection

The series is split into a reusable common base and one series per model:

```
patches/
├── common/    # model-independent 0004 host support, 0009 and 0010
├── qwen35/    # 0002, Qwen policy from 0004, and dense-qwen35 patches
└── mellum/    # added later from Paul's ds4-mellum commits
```

Ownership is semantic, not merely an application dependency. `common` contains
only model-independent host and engine support. Qwen chat, sampling policy and
implementation stay in `qwen35` even when a hunk could apply to upstream alone.
In a common-only tree, the host APIs preserve upstream's existing sampling
defaults and report only payload capabilities present in that tree; they do not
install dense-qwen35 behavior. The qwen35 series adds the Qwen policy and the
rest of its implementation.

Every target has the topology `pin → common → ordered model prefix`. The
common series must apply on its own to the pinned upstream tree. Model
directories apply in directory-name order, and each model series starts at the
previous model's tip; it need not apply directly to the pin or to common.
Numbered `format-patch` filenames define order within each directory, and
numbering restarts in each directory. The `[PATCH n/m]` text in subjects is not
authoritative. No series file is needed because directory order and filename
order are deterministic and patches are never interleaved.

The chosen alternative is a real reusable base, not an ownership-only split of
an interleaved series. An interleaved split would need a manifest and could
leave common dependent on qwen35; independent pin-based common and model series
would still need a separate integration step when combined. The reusable base
makes common available to every model and keeps sync, check and export on the
same topology.

The default materialized tree contains common and **all** model directories, so
the ds4 engine used by the coding agent includes every supported model. A
`--model <name>` checkout stops after that model in the fixed order, making the
selected model the editable tip. These are prefixes, not arbitrary combinations:
adding, removing or reordering a model requires rebasing every later model
series and resolving both textual and semantic conflicts before the full tree
can be verified.

Once Mellum lands, the full order is `pin → common → mellum → qwen35`. Paul's
Mellum commits are first rebased onto the then-current common tip and exported
to `patches/mellum/`, without duplicating common changes. The qwen35 series is
then rebased onto the Mellum tip. Common + Mellum, the qwen35-inclusive prefix,
and every intermediate boundary get pristine apply/build checks. After Mellum
lands, the combined tree intentionally differs from the earlier qwen35-only
byte-identity baseline.

### Day one: how the initial series was made

1. The 39 carried commits were cherry-picked onto `5379c1c` in topological
   order, three-way, with the 4 merges between the fork's own branches
   dropped. `6a015c6` (one line) moved forward next to `591c6a0`.
2. Six commits stopped on conflicts. Each was resolved without writing a new
   line, trying in turn: put both sides in the order `3e61e09` has them; for
   a file upstream never changed between `0aaea5a` and `5379c1c`, take it whole
   from the fork's branch merge; otherwise take the conflicting hunks from that
   merge (`54cb21b` for the drafter commits, `2d38cb1` for the prefill
   commits).

   | Commit | File | Resolution |
   | --- | --- | --- |
   | `5823f98` | `ds4.c` | ordered as `3e61e09` |
   | `4fff88b` | `Makefile` | from `54cb21b` |
   | `4fff88b` | `ds4.c` | ordered as `3e61e09` |
   | `e2d05e2` | `Makefile` | ordered as `3e61e09` |
   | `334a9a3` | `tests/test_qwen4_kernels.c` | whole file from `2d38cb1` |
   | `6d985f6` | `ds4.c`, `ds4_gpu.h` | from `2d38cb1` |
   | `6d985f6` | `ds4_metal.m` | ordered as `3e61e09` |
   | `dccb545` | `ds4.c` | from `2d38cb1` |

   At the end of the prefill run, `metal/qwen4.metal` and
   `tests/test_qwen4_kernels.c`, which upstream never changed, were set to
   `2d38cb1`, their exact state there.
3. Runs of consecutive commits were squashed into one patch per topic, with
   the left-out parity scripts and notes removed from every tree, and exported
   with `git format-patch`.

Two first attempts failed and are worth knowing for the next rebase. Ordering
a prefill conflict in the test file by hand put a block of tests inside
another function, so an intermediate tree would not compile; taking the branch
merge's text fixed it. And taking hunks from a branch merge where upstream also
changed the lines drops upstream's lines silently; trying the `3e61e09`
ordering first, and the byte comparison at the end, guard against that.

### Migrating the flat series to common + qwen35

This migration is a rebase and re-export of real commits, not a move of patch
files. Apply experiments against a pristine pin show that the current 0002
applies independently, but ownership still puts its Qwen policy in qwen35. The
ordered pair 0009 → 0010 can move to the common front without changing the
tree. The current 0004 cannot move as-is: its `ds4.c` definitions use context
introduced by qwen35 0001 and 0003, while qwen35 0006 in turn depends on 0004.
Its independent `ds4.h` declarations alone are not enough to make the complete
host-extension change reusable.

1. Materialize today's flat ten-patch series and retain its Git tree ID and a
   full filesystem comparison baseline (excluding only `.git` metadata).
2. Split 0004 by ownership: model-independent host API support goes into
   common, while Qwen-specific sampling policy joins 0002 in qwen35. Rework the
   common host support to apply before any model without qwen35 context and to
   preserve upstream defaults and capabilities in a common-only tree. Rebase
   the qwen35 commits onto that new common tip, preserving the final combined
   content; keep 0009 before 0010.
3. Export `pin..common-tip` to `patches/common/` and `common-tip..HEAD` to
   `patches/qwen35/`, then remove the old flat files only after the new layout
   verifies. Do not hand-edit patches to force the new topology.
4. Verify common alone and common + qwen35 from separate pristine clones. The
   common-only Git tree ID must equal the source common tip. The new common +
   qwen35 Git tree ID must equal the flat-series baseline, and a full
   filesystem diff excluding `.git` must be empty. Patch bytes, filenames,
   commit IDs and patch numbers may change; file contents may not.

The byte-identity comparison is the migration acceptance gate, not a frozen
baseline that prevents later intentional qwen35 changes.

### Initial flat-series checks, with results

These are the historical results for the original flat migration and predate
#4. Here "ten patches" means the nine migrated patches plus the held-back Q5_K
patch, not the current 0001–0010. The migration above must re-run the
applicable checks for common alone and for common + qwen35.

| Check | Result |
| --- | --- |
| The original nine migrated patches plus the held-back Q5_K patch on a pristine `5379c1c` equal `3e61e09` (`diff -r`, left-out files excluded) | pass |
| `git am` of the nine patches on a pristine `5379c1c` gives the same tree as `git apply` | pass |
| After every patch, `ds4py build` for CPU and for Metal, with the ABI checks from ds4-py #3 | 20 of 20 pass |
| After every patch, `ds4-agent` and the engine's test programs compile | 10 of 10 pass |
| With all ten patches, on an M4 Max (macOS 15.7.1): `test_qwen4_kernels`, `test_qwen35_host` | pass |
| With all ten patches: `ds4py check --live` on Qwen3.8-27B | sync and restore pass |

Not run: the verify and DFlash live tests (`test_qwen35_verify_live`,
`test_dflash_live`) on intermediate trees, and CUDA.

### Daily work

- `ds4-sync [--common-only | --model <name>]` — refresh `.ds4/tree`: fetch
  upstream into the cache clone, check out the pin, `git am
  patches/common/*.patch`, then apply model directories in directory-name
  order. With no option, materialize all models. `--common-only` stops after
  common; `--model <name>` stops after that model, making it the editable tip.
  Record the common tip, every applied model tip and the selected target in the
  scratch clone. Refuse to destroy uncommitted work or unexported commits
  unless `--force`.
- Keep history linear and merge-free. Change common only in a common-only
  checkout, where the common-tip branch is checked out and advances with every
  commit so it always equals `HEAD`. In a model-prefix checkout, only append
  commits for the selected final model after its previous-model or common base;
  never rewrite an earlier range there. After exporting a change, sync later
  prefixes onto the new base. Repair and revalidate every later model series if
  its patches no longer apply or its behavior changes.
- `ds4-export` — require a clean tree and generate a candidate under `.ds4/`
  for the editable range: common from `pin..HEAD` in a common-only checkout, or
  the selected model from `previous-tip..HEAD` in a model-prefix checkout,
  where `previous-tip` is the common tip or the preceding model tip. Require
  the recorded linear ancestry so every commit belongs to exactly one range,
  and reject merge commits. Reconstruct the target from pristine clones using
  the committed preceding directories plus the candidate, and require each
  boundary and final Git tree ID to equal its corresponding source tree. Only
  after all checks pass, replace the owned directory in `patches/`; a failed
  export leaves the existing patch set untouched. Never delete or renumber
  another directory. Refuse to overwrite a dirty `patches/` unless `--force`.
- `ds4-check [--common-only | --model <name>]` — prove the committed
  directories stand together: with no option, check common and every model
  prefix in separate pristine clones at the pin, ending with the full
  multi-model tree. With an option, check only that target. Apply common and
  then model directories in their fixed order with plain `git am`. For the
  target represented by `.ds4/tree`, also compare every reconstructed boundary
  and final Git tree ID with the scratch refs and `HEAD`, catching stale or
  lossy exports. With `--build`, also build each checked tree. This is the
  pre-commit gate.
- Build the selected real source tree with `ds4py build --src .ds4/tree`.
  satyrn-agent owns materialization, not a second copy of the build logic; a
  `ds4-build` convenience wrapper only passes options through to ds4-py.

Until these exist, the same steps run by hand: clone upstream at the pin, `git
am patches/common/*.patch` and then model directories in order through the
selected prefix, commit the change, and use `git format-patch` with the common
or previous-model tip as the export boundary.

### Implementation notes for the tooling

- `.ds4/cache` is a bare mirror of upstream used by both `ds4-sync` and
  `ds4-check`, so both work offline after the first fetch.
- `.ds4/tree` is a full clone of the cache with `upstream` added as a second
  remote. Local common-tip and per-model-tip refs record every export boundary.
  The common-tip branch is checked out for common-only work; a model branch
  starts at its previous-model or common tip and accepts only that model's
  commits. The selected prefix is recorded with the scratch tree. A future
  rebase onto a newer upstream rebuilds every range and exports each separately.
- Boundary refs are metadata for export, not a replacement for verification:
  `ds4-check` always reconstructs them by applying the committed directories in
  order to the pin.
- `ds4py build --src` accepts any assembled ds4 tree, so common-only, every
  prefix and the full multi-model target use the same build path. Metal still
  finds its kernels relative to the real checkout.
- `devenv.nix` mirrors ds4-py (`languages.c`, `languages.python` + uv with
  `UV_PYTHON`/`UV_PYTHON_DOWNLOADS` pinned to Nix's Python) and adds the
  script entry points as devenv scripts so the commands work both inside and
  outside the devenv shell.

## 7. What happens next (not this design)

- The tooling in §6.
- The held-back Q5_K patch as a future model-local qwen35 patch: Paul decides
  whether the 9B and 4B stay.
- A home for the parity scripts and notes left out of the series.
- New patches: narrowing 0002 so a tool's own text stays plain.
- Moving the pin past `5379c1c`, as its own verified step.
- Wiring the optional `ds4-build` wrapper to `ds4py build --src`; ds4-py already
  owns `Makefile.lib` and the build behavior (spec §19).
- The downstream agent package (bindings via the `ds4py.bindings` entry
  point, the DFlash decode step, capabilities) is scaffolded in this repo.
- ds4-engine decides whether to keep its submodule or consume this repo's
  patch-derived tree.

## 8. Calls made

- **Base `5379c1c`, not `0aaea5a`.** The rebase past upstream's 30 newer
  commits was done during the migration, verified against the fork's own merge
  `3e61e09`, and the pin now matches ds4-py's.
- **Nine topical migrated patches, not one per commit.** Keep, drop and
  offer-upstream decisions are made per topic, and a topic is what goes
  upstream. Each patch lists its carried commits, so per-commit provenance is
  kept. One patch per commit on `5379c1c` can be produced the same way if it is
  ever needed. The standalone 0010 macOS 15 fix arrived later in #4.
- **Patch mechanics:** numbered `format-patch` files applied in filename order
  within each directory, with model directories in directory-name order after
  common. Targets are common or a model prefix, and the default target includes
  all models; no `series` file is needed.
- **Common is model-independent.** Qwen chat, sampling policy and implementation
  belong to qwen35, not to the shared base, even when they apply independently
  or are inert in another model's build.
- **The Q5_K commits are held back** rather than dropped, so Paul can decide.
- **Parity scripts and notes are left out** of the engine patches.
- **Scratch tree lives at `.ds4/`** (gitignored), not in `external/`, and the
  fork is never needed after migration day.
- **No CI and no Python package yet.** `ds4-check` is designed to drop into CI
  unchanged when wanted.
- **Scripts are bash in `tools/`** exposed through devenv, not a Justfile
  (ds4-engine's convention) — devenv is the requested bootstrap and the
  scripts stay runnable without it.
