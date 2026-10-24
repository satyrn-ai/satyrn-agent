# ds4 patch series: repo bootstrap design

| | |
| --- | --- |
| Date | 2026-10-24 |
| Status | Draft for review |
| Upstream | `https://github.com/antirez/ds4` pinned at `0aaea5a238fb41a35106a551e73c8409dfb751ac` (2026-09-20) |
| Migration source | `https://github.com/pauleveritt/ds4.git`, tip `ebdcb0f9a8ba74a440604da900665afbdf4f4f57` (the gitlink recorded on `ds4-engine`'s `main` for `external/ds4`) |
| Related | `ds4-py/docs/specs/2026-10-21-ds4-py-design.md` §18–19 (the downstream agent and the `libds4` build this repo feeds) |

## 1. Intent

satyrn-agent will hold the downstream agent described in the ds4-py spec: a
customisation of ds4-py that runs against a patched ds4 engine. Before any
agent code exists, this repo must own the ds4 patches.

Today the patches live as commits on branches of the `pauleveritt/ds4` fork.
That makes the fork the source of truth and forces consumers to track a moving
source tree. Instead, this repo holds **discrete patch files against upstream
ds4** plus the tooling to apply, edit, verify and build them. All ds4 patch
work happens in this repo from now on; the fork is frozen.

## 2. Scope of the initial series

The initial series is the patch content of `ds4-engine` **main**'s gitlink for
`external/ds4`:

- Range: `0aaea5a..ebdcb0f` — 40 commits (36 non-merge, 4 merges),
  24 files, +8,700/−61.
- Content: dense qwen35 on the Metal graph, Q5_K/Q6_K dense matmuls, in-memory
  and file payloads for the dense path, DFlash drafter and verify paths,
  prefill flash-attention, MMA kernels, host extensions
  (`ds4_engine_sampling_defaults`, `ds4_session_supports_payload`), Qwen chat
  template fixes, tests.
- Explicitly excluded (the user's call): the 13 newer commits on
  `qwen35-cuda-port` (the CUDA port and parity work) and every other fork
  branch.

Note: `ds4-engine`'s `crates/ds4-sys/engine.pin` names `cfb2faf`, three
commits ahead of the gitlink (`ebdcb0f`). The user chose the gitlink as the
scope after seeing this discrepancy. The three skipped commits
(`14c3c7e`, `946a0ad`, `cfb2faf`) can be added later as ordinary new patches
if they turn out to be needed.

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
5. The migration is verified: a tree materialized from `patches/` is
   byte-identical to the fork tip `ebdcb0f`.

### Non-goals

- Rebasing the series onto a newer upstream. The fork branches sit on
  `0aaea5a` (2026-09-20); upstream is now at `ee7e840` (2026-10-21) and
  ds4-py's spec pins `5379c1c` (2026-10-19). Catching up is a separate,
  verifiable exercise after this bootstrap.
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
├── upstream.pin            # UPSTREAM_URL, UPSTREAM_COMMIT
├── patches/
│   └── 0001-… .patch … 0036-… .patch
├── tools/
│   ├── ds4-sync.bash       # materialize/refresh .ds4/tree from pin + patches
│   ├── ds4-export.bash     # format-patch the tree's commits back into patches/
│   ├── ds4-check.bash      # pristine-clone verification (the gate)
│   ├── ds4-build.bash      # build libds4 from .ds4/tree
│   ├── Makefile.lib        # shared-lib target reusing the tree's own object lists
│   └── migrate/
│       └── README.md       # how the initial series was produced (provenance)
└── docs/
    └── specs/2026-10-24-ds4-patch-series-design.md  (this file)
```

## 6. The workflow

### Day one (migration, run once)

1. Clone the fork to `.ds4/migrate-src` at `ebdcb0f`.
2. Linearize the range: `git rebase --onto 0aaea5a 0aaea5a <branch>` replays
   the 36 non-merge commits in topological order and drops the 4 merges.
   Measured on 2026-10-24: this stops for conflicts at 5 commits —
   `4fff88b` (Makefile), `334a9a3` (tests/test_qwen4_kernels.c),
   `6d985f6` (ds4.c, ds4_gpu.h, ds4_metal.m), `b00831d` (ds4_gpu.h,
   ds4_metal.m, tests/test_qwen4_kernels.c), `17a9818` (ds4.c).
   Resolve each by reference to the original merge commits
   (`1e08b41`, `1657deb`, `54cb21b`, `2d38cb1`), which contain the same
   resolutions.
3. Gate 1: `git diff ebdcb0f <branch>` must be empty.
4. `git format-patch` the linear branch into `patches/`.
5. Gate 2: `ds4-check` — pristine upstream clone at the pin + `git am
   patches/*.patch` must succeed and produce a tree byte-identical to
   `ebdcb0f`.

Fallback if a resolution stalls: export the first-parent chain instead —
28 per-commit patches plus 4 fold-in patches (`git diff <merge>^1 <merge>`)
covering the 8 side-branch commits. Zero conflicts by construction; 8 commits
lose their individual identity. Same gates.

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

- Rebase the series onto a newer upstream commit, as its own verified step.
- ds4-py lands; `ds4py build --src .ds4/tree` takes over the build and
  `Makefile.lib` moves there (spec §19).
- The downstream agent package (bindings via the `ds4py.bindings` entry
  point, the DFlash decode step, capabilities) is scaffolded in this repo.
- ds4-engine decides whether to keep its submodule or consume this repo's
  patch-derived tree; the `engine.pin` vs gitlink discrepancy disappears
  either way.

## 8. Calls I made

- **Patch mechanics:** numbered `format-patch` files applied in filename
  order; no `series` file (redundant with numbered names).
- **Base stays at `0aaea5a`** for the migration; no rebase now.
- **Linearize the 4 merges** (36 fine-grained patches) rather than fold side
  branches into 4 fat patches; the fallback exists if resolution stalls.
- **Scratch tree lives at `.ds4/`** (gitignored), not in `external/`, and the
  fork is never needed after migration day.
- **No CI and no Python package yet.** `ds4-check` is designed to drop into CI
  unchanged when wanted.
- **Scripts are bash in `tools/`** exposed through devenv, not a Justfile
  (ds4-engine's convention) — devenv is the requested bootstrap and the
  scripts stay runnable without it.
