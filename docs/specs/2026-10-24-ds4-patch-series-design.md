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
- Result: nine patches, 16 files, +8,306/−61 against `5379c1c`.
- Held back: the Q5_K commits, as a ready tenth patch, until Paul decides
  whether the 9B and 4B stay.
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

1. `patches/` holds the whole series as numbered `git format-patch` files that
   apply in filename order to the pinned upstream commit with plain `git am`
   — no fork object store required.
2. `upstream.pin` records the upstream URL and commit.
3. One command materializes a patched working tree inside this repo
   (gitignored) for day-to-day editing; one command exports its commits back
   into `patches/`; one command verifies the series from a pristine upstream
   clone; one command builds `libds4` from the patched tree.
4. devenv supplies every tool the workflow needs; conventions mirror ds4-py.
5. The migration is verified: the series, with the held-back tenth patch,
   gives a tree byte-identical to the fork's `3e61e09`, apart from the
   left-out parity scripts and notes.

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
- A second copy of build logic once ds4-py exists: `Makefile.lib` here follows
  ds4-py spec §19 so ds4-py can absorb it unchanged.

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
│   └── 0001-… .patch … 0009-… .patch
├── tools/                  # not written yet
│   ├── ds4-sync.bash       # materialize/refresh .ds4/tree from pin + patches
│   ├── ds4-export.bash     # format-patch the tree's commits back into patches/
│   ├── ds4-check.bash      # pristine-clone verification (the gate)
│   ├── ds4-build.bash      # build libds4 from .ds4/tree
│   └── Makefile.lib        # shared-lib target reusing the tree's own object lists
└── docs/
    └── specs/2026-10-24-ds4-patch-series-design.md  (this file)
```

## 6. The workflow

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

### Checks, with results

| Check | Result |
| --- | --- |
| The ten patches on a pristine `5379c1c` equal `3e61e09` (`diff -r`, left-out files excluded) | pass |
| `git am` of the nine patches on a pristine `5379c1c` gives the same tree as `git apply` | pass |
| After every patch, `ds4py build` for CPU and for Metal, with the ABI checks from ds4-py #3 | 20 of 20 pass |
| After every patch, `ds4-agent` and the engine's test programs compile | 10 of 10 pass |
| With all ten patches, on an M4 Max (macOS 15.7.1): `test_qwen4_kernels`, `test_qwen35_host` | pass |
| With all ten patches: `ds4py check --live` on Qwen3.8-27B | sync and restore pass |

Not run: the verify and DFlash live tests (`test_qwen35_verify_live`,
`test_dflash_live`) on intermediate trees, and CUDA.

### Daily work

- `ds4-sync` — refresh `.ds4/tree`: fetch upstream into the cache clone,
  check out the pin, `git am` the series. Refuses to destroy uncommitted work
  or unexported commits unless `--force`.
- Edit and commit normally in `.ds4/tree`.
- `ds4-export` — require a clean tree, then regenerate `patches/` from
  `pin..HEAD` (renumbered). Refuses to overwrite a dirty `patches/` unless
  `--force`.
- `ds4-check` — prove the committed series stands alone: from the cache,
  pristine clone at the pin, apply `patches/` in order. With `--build`, also
  run the build. This is the pre-commit gate.
- `ds4-build [cpu|metal|cuda]` — build `libds4` (and, when wanted, the tree's
  own binaries) in `.ds4/tree`.

Until these exist, the same steps run by hand: clone upstream at the pin,
`git am patches/*.patch`, commit the change, and
`git format-patch -1 --start-number <next> -o patches`, as #4 did for the
macOS 15 fix.

### Implementation notes for the tooling

- `.ds4/cache` is a bare mirror of upstream used by both `ds4-sync` and
  `ds4-check`, so both work offline after the first fetch.
- `.ds4/tree` is a full clone of the cache with `upstream` added as a second
  remote, so a future rebase onto a newer upstream is an ordinary rebase in
  the scratch tree followed by `ds4-export`.
- `Makefile.lib` follows ds4-py spec §19: it includes the tree's own Makefile
  and links the tree's `$(CORE_OBJS)` (or `$(CPU_CORE_OBJS)`) plus
  `ds4_kvstore.o` into `libds4.so` with `-shared`; objects are compiled with
  `-fPIC`. Objects build in-tree (the spec leaves this to the builder), which
  also lets the same objects link the tree's own binaries.
- `devenv.nix` mirrors ds4-py (`languages.c`, `languages.python` + uv with
  `UV_PYTHON`/`UV_PYTHON_DOWNLOADS` pinned to Nix's Python) and adds the
  script entry points as devenv scripts so the commands work both inside and
  outside the devenv shell.

## 7. What happens next (not this design)

- The tooling in §6.
- The held-back tenth patch: Paul decides whether the 9B and 4B stay.
- A home for the parity scripts and notes left out of the series.
- New patches: the macOS 15 Metal language version fix (#4), and narrowing
  0002 so a tool's own text stays plain.
- Moving the pin past `5379c1c`, as its own verified step.
- ds4-py lands; `ds4py build --src .ds4/tree` takes over the build and
  `Makefile.lib` moves there (spec §19).
- The downstream agent package (bindings via the `ds4py.bindings` entry
  point, the DFlash decode step, capabilities) is scaffolded in this repo.
- ds4-engine decides whether to keep its submodule or consume this repo's
  patch-derived tree.

## 8. Calls made

- **Base `5379c1c`, not `0aaea5a`.** The rebase past upstream's 30 newer
  commits was done during the migration, verified against the fork's own merge
  `3e61e09`, and the pin now matches ds4-py's.
- **Nine topical patches, not one per commit.** Keep, drop and offer-upstream
  decisions are made per topic, and a topic is what goes upstream. Each patch
  lists its carried commits, so per-commit provenance is kept. One patch per
  commit on `5379c1c` can be produced the same way if it is ever needed.
- **Patch mechanics:** numbered `format-patch` files applied in filename
  order; no `series` file (redundant with numbered names).
- **The Q5_K commits are held back** rather than dropped, so Paul can decide.
- **Parity scripts and notes are left out** of the engine patches.
- **Scratch tree lives at `.ds4/`** (gitignored), not in `external/`, and the
  fork is never needed after migration day.
- **No CI and no Python package yet.** `ds4-check` is designed to drop into CI
  unchanged when wanted.
- **Scripts are bash in `tools/`** exposed through devenv, not a Justfile
  (ds4-engine's convention) — devenv is the requested bootstrap and the
  scripts stay runnable without it.
