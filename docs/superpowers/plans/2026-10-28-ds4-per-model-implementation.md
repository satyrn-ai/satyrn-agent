# DS4 Per-Model Tooling and Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the §6 patch-series tools, then use them to migrate the flat ten patches into `common/` and `qwen35/` without changing the materialized tree.

**Architecture:** Bash 3.2-compatible command wrappers share a small library for pin parsing, deterministic patch discovery, cache management, target application, and scratch state. `ds4-sync`, transactional `ds4-export`, and pristine `ds4-check` operate on the same `pin → common → ordered model prefix` history. Migration rebases and splits real commits, exports them through the new tools, and compares both Git tree IDs and filesystem bytes with the retained flat-series baseline before deleting the old patches.

**Tech Stack:** Bash 3.2, Git, macOS system tools, devenv/Nix, ds4-py (`ds4py build --src`), upstream Make targets.

**Spec:** `docs/specs/2026-10-24-ds4-patch-series-design.md`, especially §6. §7 excludes Mellum, Q5_K, pin movement, and the optional `ds4-build` wrapper from this implementation.

## Global Constraints

- Use upstream URL `https://github.com/antirez/ds4.git` and commit `5379c1c9ac315f1540371b06a3db88491d4059ff` from `upstream.pin`; do not move the pin.
- Implement tools before changing patch ownership. Do not hand-edit generated patch files to force the migration topology.
- Support macOS and Linux with Bash 3.2+: no associative arrays, `mapfile`, `readarray`, or `globstar`. Avoid both GNU-only and BSD-only commands/flags, including `realpath`, `readlink -f`, `find -printf`, `sort -z`, `stat -c`/BSD `stat -f`, `sha256sum`/`shasum` dependence, `cp -a`, and `sed -i`; use Git, POSIX utilities, and portable temporary-directory patterns instead.
- Apply `common` first and immediate model subdirectories in `LC_ALL=C` directory-name order. Apply numbered `*.patch` files in filename order within each directory. Do not add a series file.
- Targets are common-only or a model prefix; the default target includes every model. Do not support arbitrary model combinations.
- The final `common + qwen35` Git tree ID and full filesystem contents, excluding only `.git`, must equal the current flat ten-patch tree. Patch names, patch bytes, commit IDs, and numbering may change.
- Keep `common` semantically model-independent. Common-only host APIs preserve upstream sampling defaults and report only payload capabilities actually present; qwen35 restores the final Qwen policy and implementation.
- Builds use `ds4py build --src <tree>`; do not copy ds4-py's build logic or add `Makefile.lib` here. Linux builds must use ds4-py's CPU backend (its non-Darwin default). ds4-py remains an external prerequisite, not a package/integration added to this repo; CI/Linux verification uses public repository `https://github.com/rochecompaan/ds4-py.git` at known commit `f0e2118629c315e835435c82c973638e6f9e49bc`.
- Use one fresh worker per task and one fresh reviewer per task. A task cannot advance with an open Critical or Important finding. Finish with a whole-branch reviewer.
- Run the shell suite on Ubuntu CI and run Linux `ds4-check --build` with the CPU backend.
- Before completion, pass model-backed E2E on a dense qwen35 model: library ABI/load checks, live sync/restore, and deterministic raw-generation parity between ds4-py and `ds4-agent`. Missing model/assets is a blocked verification, not a passing result.
- Work in an isolated branch/worktree created from the merged `origin/main`; preserve the user's current checkout.

## Review Focus

- **Portable filesystem/process behavior:** the same shell suite must pass with macOS/BSD utilities and Ubuntu/GNU utilities, without relying on either platform's non-POSIX flags. Pin this in Task 1 with portable checksums/temp paths and in Task 5 with Ubuntu CI.
- **Offline cache:** an unavailable remote must not break a cached pin, while a missing cached pin must fail clearly. Pin this in Tasks 1 and 2 with a local upstream whose remote is made unreachable after the first sync.
- **Scratch safety:** dirty or unexported `.ds4/tree` content must survive a non-force sync. Pin this in Task 2 by asserting both bytes and HEAD before and after refusal, then verify explicit `--force` replacement.
- **Export atomicity:** failed candidate reconstruction must leave every existing patch byte and directory untouched. Pin this in Task 3 with a stale boundary and checksums of the complete `patches/` tree.
- **Target ambiguity:** unknown models, empty patch directories, conflicting selection flags, and merge commits must be rejected rather than guessed. Pin argument/discovery cases in Tasks 1–3.
- **Migration semantics and live behavior:** common-only must compile without qwen35 context and must not advertise qwen35 behavior, while the full tree must remain byte-identical. Pin this in Task 6 with common-only checks plus the two acceptance comparisons, and in Task 7 with real-model sync/restore and deterministic generation parity.

---

### Task 1: Shared Bash Library and Test Harness

**Files:**
- Create: `tools/ds4-lib.bash`
- Create: `tests/ds4_tools_test.bash`

**Interfaces:**
- Produces: `ds4_die MESSAGE`, `ds4_repo_root`, `ds4_load_pin` setting `UPSTREAM_URL` and `UPSTREAM_COMMIT`, `ds4_model_names` setting the `DS4_MODEL_NAMES` array, `ds4_target_stop_model` setting `DS4_STOP_MODEL`, `ds4_patch_files DIR` setting `DS4_PATCH_FILES`, `ds4_ensure_cache`, `ds4_clone_at_pin DEST`, and `ds4_apply_target TREE [STOP_MODEL]`.
- Produces: `ds4_state_write TREE TARGET MODEL PREVIOUS_TIP SYNC_HEAD` and `ds4_state_read TREE`, using `.git/ds4-state` keys `TARGET`, `MODEL`, `PREVIOUS_TIP`, `SYNC_HEAD`, and `EXPORTED_HEAD`.
- Produces: scratch refs `refs/ds4/common` and `refs/ds4/model/<name>` after each applied range.
- Test harness creates temporary local upstream repositories and patch directories; tests invoke real Git and real scripts, with no network dependency. Use `git hash-object` or POSIX `cksum` for checksums, `mktemp -d "${TMPDIR:-/tmp}/ds4.XXXXXX"` for temporary paths, and no GNU/BSD-specific filesystem flags so the same file runs on macOS and Ubuntu.

- [ ] **Step 1: Write failing discovery and pin tests**

Add tests named `test_load_pin_requires_exact_url_and_commit`, `test_model_names_use_c_locale_order`, `test_empty_common_or_model_directory_fails`, and `test_apply_target_builds_common_and_ordered_prefix`. Use an upstream containing one text file, common/model patches that append distinct lines, and assert the final file bytes and boundary tree IDs.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `bash tests/ds4_tools_test.bash`; expect failure because `tools/ds4-lib.bash` does not exist.

- [ ] **Step 3: Implement the shared library**

Parse `upstream.pin` without sourcing it, validate immediate model directory names against `[A-Za-z0-9][A-Za-z0-9_-]*`, use Bash 3.2 arrays and `LC_ALL=C`, reject empty patch directories, and apply patches with `git am`. `ds4_ensure_cache` maintains `.ds4/cache` as a mirror and treats fetch as best-effort only when the pin already exists locally. State parsing must not source the state file.

- [ ] **Step 4: Add failing offline/state tests, then implement their behavior**

Add `test_cached_pin_works_when_remote_is_unreachable`, `test_missing_cached_pin_fails`, and `test_state_round_trip_does_not_execute_values`. Verify the first two fail before the cache behavior is complete and the third fails before safe state parsing is complete; then implement and rerun.

- [ ] **Step 5: Run library tests and syntax checks**

Run `bash tests/ds4_tools_test.bash` and `bash -n tools/ds4-lib.bash tests/ds4_tools_test.bash`; expect all tests to pass.

- [ ] **Step 6: Commit**

```bash
git add tools/ds4-lib.bash tests/ds4_tools_test.bash
git commit -m "feat: add shared ds4 patch tooling primitives"
```

### Task 2: `ds4-sync`

**Files:**
- Create: `tools/ds4-sync.bash`
- Modify: `tests/ds4_tools_test.bash`
- Consume: `tools/ds4-lib.bash` interfaces from Task 1

**Interfaces:**
- CLI: `ds4-sync [--common-only | --model NAME] [--force]`; `--help` prints usage without changing files.
- Produces: `.ds4/tree` as a full clone of `.ds4/cache` with an `upstream` remote, branch `ds4/common` for common-only or `ds4/model/<name>` for a model tip, all applied boundary refs, and `.git/ds4-state`.
- `EXPORTED_HEAD` initially equals `SYNC_HEAD`; a later successful export updates it.

- [ ] **Step 1: Write failing sync target and metadata tests**

Add `test_sync_defaults_to_all_models`, `test_sync_common_only`, and `test_sync_model_stops_at_editable_prefix`. Assert file contents, current branch, target state, every boundary ref, and `HEAD == EXPORTED_HEAD == SYNC_HEAD`.

- [ ] **Step 2: Run sync tests and verify RED**

Run `bash tests/ds4_tools_test.bash`; expect the new tests to fail because `tools/ds4-sync.bash` is missing.

- [ ] **Step 3: Implement sync materialization and argument validation**

Reject both selection flags together, unknown models, extra positional arguments, and an empty common directory. Clone at the pin, create linear branches, apply the selected prefix through the shared library, and write refs/state atomically.

- [ ] **Step 4: Add failing safety tests, then implement guards**

Add `test_sync_refuses_dirty_tree_without_force`, `test_sync_refuses_unexported_commit_without_force`, and `test_sync_force_replaces_only_scratch_tree`. Non-force refusal must preserve a marker file and HEAD. Allow an unchanged synced HEAD or a HEAD recorded as exported; `--force` may recreate `.ds4/tree` but must not recreate or delete `.ds4/cache`.

- [ ] **Step 5: Run the complete tool suite**

Run `bash tests/ds4_tools_test.bash` and `bash -n tools/ds4-*.bash`; expect all tests to pass.

- [ ] **Step 6: Commit**

```bash
git add tools/ds4-sync.bash tests/ds4_tools_test.bash
git commit -m "feat: materialize ordered ds4 patch targets"
```

### Task 3: Transactional `ds4-export`

**Files:**
- Create: `tools/ds4-export.bash`
- Modify: `tests/ds4_tools_test.bash`
- Consume: Task 1 state/refs and Task 2 `.ds4/tree`

**Interfaces:**
- CLI: `ds4-export [--force]`; `--help` prints usage without changing files. `--force` only overrides a dirty `patches/` guard, not ancestry, merge, or round-trip failures.
- Common-only range: `UPSTREAM_COMMIT..HEAD`; model range: `PREVIOUS_TIP..HEAD`, where the previous tip is common or the preceding model.
- Candidate path: a unique `.ds4/export/` temporary directory; only the owned patch directory is replaced after successful reconstruction.

- [ ] **Step 1: Write failing common and model export tests**

Add `test_export_common_renumbers_real_range` and `test_export_model_uses_previous_model_tip`. Make real commits in synced fixtures, invoke the tool, and assert `git format-patch` output starts at 0001, patch application reproduces HEAD, other directories remain byte-identical, and `EXPORTED_HEAD` advances.

- [ ] **Step 2: Run export tests and verify RED**

Run `bash tests/ds4_tools_test.bash`; expect failure because `tools/ds4-export.bash` is missing.

- [ ] **Step 3: Implement range validation and candidate generation**

Require clean `.ds4/tree`, a recognized target/state, nonempty linear ancestry, no merge commits, and a clean `patches/` tree unless `--force`. Generate the candidate with `git format-patch --start-number 1` under `.ds4/export/`; never edit the existing patch first.

- [ ] **Step 4: Add failing transaction tests, then implement validation and replacement**

Add `test_export_rejects_merge_commit`, `test_export_rejects_empty_range`, `test_export_rejects_dirty_patches_without_force`, and `test_export_round_trip_failure_leaves_all_patch_bytes_untouched`. Reconstruct the selected target in a pristine clone from committed preceding directories plus the candidate; compare every source boundary tree ID and final HEAD tree ID. On success replace only the owned directory and update state; on every failure or signal preserve/restore the original directory.

- [ ] **Step 5: Run the complete tool suite**

Run `bash tests/ds4_tools_test.bash` and `bash -n tools/ds4-*.bash`; expect all tests to pass.

- [ ] **Step 6: Commit**

```bash
git add tools/ds4-export.bash tests/ds4_tools_test.bash
git commit -m "feat: export ds4 patch ranges transactionally"
```

### Task 4: `ds4-check`

**Files:**
- Create: `tools/ds4-check.bash`
- Modify: `tests/ds4_tools_test.bash`
- Consume: Task 1 target application and Task 2 scratch state/refs

**Interfaces:**
- CLI: `ds4-check [--common-only | --model NAME] [--build]`; `--help` prints usage without changing files.
- Default checks common and every model prefix in separate pristine clones. A selector checks only that target.
- `--build` invokes `ds4py build --src <absolute-clone-path> --backend cpu` on Linux and `ds4py build --src <absolute-clone-path> --backend metal` on macOS, once per checked target.

- [ ] **Step 1: Write failing pristine-check tests**

Add `test_check_default_covers_common_every_prefix_and_full_tree`, `test_check_selected_target`, and `test_check_rejects_corrupt_patch_series`. Record clone paths/targets through the real command's output; assert each target starts at the pin and corrupted patches produce nonzero status.

- [ ] **Step 2: Run check tests and verify RED**

Run `bash tests/ds4_tools_test.bash`; expect failure because `tools/ds4-check.bash` is missing.

- [ ] **Step 3: Implement target reconstruction and scratch comparisons**

Use the shared cache, independent temporary clones, and deterministic prefix application. If `.ds4/tree` represents the same target, compare every reconstructed boundary and final Git tree ID with scratch refs/HEAD; stale or lossy exports must fail.

- [ ] **Step 4: Add failing build/stale tests, then implement them**

Add `test_check_build_passes_real_source_path_to_ds4py` and `test_check_detects_stale_scratch_tree`. Use a temporary `ds4py` executable that records its arguments to avoid requiring a compiler in shell unit tests; assert exact `build --src <path> --backend metal` arguments on macOS and `--backend cpu` on Linux. Implement `--build`, platform backend selection, and the stale-tree comparison, then rerun.

- [ ] **Step 5: Run the complete tool suite**

Run `bash tests/ds4_tools_test.bash` and `bash -n tools/ds4-*.bash`; expect all tests to pass.

- [ ] **Step 6: Commit**

```bash
git add tools/ds4-check.bash tests/ds4_tools_test.bash
git commit -m "feat: verify ds4 patch targets from pristine clones"
```

### Task 5: Devenv Entry Points, Ubuntu CI, and User Workflow

**Files:**
- Modify: `devenv.nix`
- Modify: `README.md`
- Modify: `tests/ds4_tools_test.bash`
- Create: `.github/workflows/ds4-tools.yml`

**Interfaces:**
- Produces commands `ds4-sync`, `ds4-export`, and `ds4-check` inside and through `devenv shell --`.
- Produces an Ubuntu CI job that runs syntax checks, the complete shell suite, and `ds4-check --build` through ds4-py's CPU backend.
- Does not add `ds4-build`; §7 leaves that optional wrapper outside this slice.

- [ ] **Step 1: Write failing entry-point test**

Add `test_devenv_entry_points_show_help`, which invokes each command with `--help` through `devenv shell --` and checks for its selection/build options. Add a README documentation check for the three commands and the migration acceptance invariant only if the team wants documentation tested; do not create a documentation-only substitute for behavior tests.

- [ ] **Step 2: Run the entry-point test and verify RED**

Run `bash tests/ds4_tools_test.bash`; expect the new test to fail because the devenv scripts are not registered.

- [ ] **Step 3: Register scripts and document the workflow**

Add devenv script entry points that exec the repository's Bash tools and forward `"$@"`. Replace bootstrap layout/status text with the current flat-series status and concise sync/edit/export/check/build instructions. Document that build commands require an external ds4-py checkout selected with `DS4PY_PROJECT`, initialized with `devenv shell -- uv sync --project "$DS4PY_PROJECT"` and exposed by prepending `$DS4PY_PROJECT/.venv/bin` to `PATH`; do not add ds4-py as a repo dependency or document the migration as completed yet.

- [ ] **Step 4: Add Ubuntu CI**

Create `.github/workflows/ds4-tools.yml` for pull requests, pushes to `main`, and manual dispatch. On `ubuntu-latest`, check out this repo, install uv/Python 3.14, run Bash syntax checks and `bash tests/ds4_tools_test.bash`, then check out `rochecompaan/ds4-py` at `f0e2118629c315e835435c82c973638e6f9e49bc` under `.ds4/ds4-py`. Run `uv sync --project .ds4/ds4-py --python 3.14`, prepend `.ds4/ds4-py/.venv/bin` to `PATH`, and run `bash tools/ds4-check.bash --build`; the tool must explicitly select `--backend cpu` on Linux. Validate locally with `actionlint .github/workflows/ds4-tools.yml`.

- [ ] **Step 5: Run integration and complete tool tests**

Run `devenv shell -- ds4-sync --help`, `devenv shell -- ds4-export --help`, `devenv shell -- ds4-check --help`, `bash tests/ds4_tools_test.bash`, and `devenv shell -- actionlint .github/workflows/ds4-tools.yml`; expect success. CI cannot pass the post-migration build until Task 6 supplies the new directories, so do not publish this intermediate branch merely to run it.

- [ ] **Step 6: Commit**

```bash
git add devenv.nix README.md tests/ds4_tools_test.bash .github/workflows/ds4-tools.yml
git commit -m "docs: add portable ds4 tooling workflow"
```

### Task 6: Rebase and Migrate `common + qwen35`

**Files:**
- Create: `patches/common/*.patch`
- Create: `patches/qwen35/*.patch`
- Delete: the ten tracked `patches/0001-*.patch` through `patches/0010-*.patch` only after acceptance passes
- Modify: `README.md` only to mark the new layout complete after verification
- Consume: all tools and state interfaces from Tasks 1–5

**Interfaces:**
- Migration scratch: `.ds4/migration/flat`, `.ds4/migration/work`, `.ds4/migration/flat.tree-id`; all remain ignored.
- Common export boundary: actual `common-tip`; qwen35 export boundary: `common-tip..qwen35-HEAD`.
- Acceptance baseline: the actual Git tree and filesystem produced by the flat ten patches at the pre-migration revision, not a hard-coded historical ID.

- [ ] **Step 1: Materialize and retain the flat baseline**

Record the pre-migration revision. Clone the cached pin into `.ds4/migration/flat`, apply the current ten root-level patches in filename order, require a clean tree, save `HEAD^{tree}` to `.ds4/migration/flat.tree-id`, and retain this tree untouched. No build artifacts may exist in either comparison tree.

- [ ] **Step 2: Create the candidate by rebasing real commits**

Clone the flat history into `.ds4/migration/work`. Use scripted, non-interactive history editing (`GIT_SEQUENCE_EDITOR` for the rebase todo plus real commit edits, or cherry-pick plus `git rebase --onto`; never a bare interactive rebase requiring a terminal) to produce linear `pin → common → qwen35` history. The common order is 0004-common → 0009 → 0010, followed by the rebased qwen35 commits. Do not move or manually rewrite patch files; Step 6 must reconfirm that moving 0009→0010 preserves the final tree.

- [ ] **Step 3: Split 0004 by semantic ownership**

In common, include the host declarations and generic+GLM sampling defaults. Define common-only `ds4_session_supports_payload` with the actual upstream Qwen4 payload predicate `s != NULL && !s->distributed && ds4_session_is_qwen4(s)`, so common does not advertise absent qwen35 or unsupported/distributed payload support; do not include Qwen sampling overrides, qwen35 declarations, or Qwen-specific comments. In a later qwen35 commit, restore the original Qwen sampling branch/comment and edit the function body back to the flat series' exact legacy `return s != NULL;`. This later restoration is intentional and required for final byte identity; it is not the common-only behavior. Preserve every other final full-tree byte exactly and keep common-only compilable without qwen35 context.

- [ ] **Step 4: Export common through `ds4-export`**

After proving the existing `.ds4/tree` has no dirty/unexported work, replace it with a full clone of the migration work at `common-tip`; add the upstream remote and register the common branch, pin, boundary ref, and state through the Task 1 helper. Run `ds4-export`, then `ds4-check --common-only`. Commit the exported common directory while retaining the flat baseline patches.

- [ ] **Step 5: Export qwen35 through `ds4-export`**

Check out the actual qwen35 HEAD on `ds4/model/qwen35`, register `PREVIOUS_TIP=common-tip` and model state/refs, then run `ds4-export`. The export's internal round-trip runs before replacement; after it succeeds, run `ds4-check` against the committed `common/` and the now-written `patches/qwen35/`. Commit the qwen35 directory after this post-write check succeeds.

- [ ] **Step 6: Prove acceptance before deleting flat patches**

Run `ds4-sync` to materialize the new default tree. Assert `git -C .ds4/tree rev-parse HEAD^{tree}` equals `.ds4/migration/flat.tree-id`, and assert `diff -r -x .git .ds4/migration/flat .ds4/tree` is empty. Also require the common-only reconstructed tree ID to equal the source common tip. If any comparison fails, retain all flat patches and repair the real commit history.

- [ ] **Step 7: Remove the flat series, repeat verification, and commit**

Only after Step 6 passes, delete the ten root-level patch files. Run the complete shell suite, `ds4-check`, and the acceptance comparisons again. Update README status/layout to the verified `common/` and `qwen35/` directories, then commit the deletion/README change. Together with Steps 4 and 5 this produces three migration commits:

```bash
git commit -m "refactor: export model-independent ds4 common patches"  # Step 4
git commit -m "refactor: export qwen35 ds4 patches"                 # Step 5
git add patches README.md
git commit -m "refactor: replace flat ds4 series with per-model layout"
```

### Task 7: Real-Tree and Model-Backed E2E

**Files:**
- Create: `tests/ds4_e2e_test.bash`
- Modify: `tests/ds4_tools_test.bash`
- Modify: `README.md`
- Consume: the completed tools and migrated real patch directories

**Interfaces:**
- `DS4PY_PROJECT` selects an external ds4-py checkout; its `.venv/bin` is on `PATH` during execution.
- `DS4_TEST_MODEL` is required and must identify a dense qwen35 GGUF so the migrated implementation is exercised.
- `tests/ds4_e2e_test.bash` is read-only with respect to tracked patches: it may materialize/build scratch trees but must not export, edit patches, or commit.
- Ubuntu CI continues to run only the no-model shell suite and CPU builds; this model-backed test is an explicit local release gate.

- [ ] **Step 1: Write failing E2E preflight tests**

Add `test_e2e_requires_dense_qwen35_model` and `test_e2e_requires_external_ds4py` to the shell suite. They must fail because `tests/ds4_e2e_test.bash` does not exist, then verify clear nonzero usage errors without reading a model or building when required inputs are absent.

- [ ] **Step 2: Implement the real-tree E2E script**

Materialize the default real tree and run `ds4-check`. Build it through ds4-py with the platform backend, capture the resulting library path, and require `ds4py check --lib <library>` to pass. Require `ds4py check --live --lib <library> --model "$DS4_TEST_MODEL"` to report successful sync plans and restore. Build `ds4-agent`, then compare deterministic raw generation for the same dense-qwen35 prompt, `--temp 0`, seed 1, and fixed token limit between `ds4py raw` and `ds4-agent --raw`; exclude progress/diagnostics and compare the generated text/token bytes. Any difference or unverified restore fails the script.

- [ ] **Step 3: Run the E2E gate and inspect its evidence**

Run the script with a dense qwen35 model and the external ds4-py environment. Expect pristine checks, ABI/load checks, sync/restore, and raw-generation parity all to pass. Preserve command output in the task report. Do not mark this task complete with a skipped live test, and do not claim that compile-only DFlash/verify binaries substitute for model-backed behavior.

- [ ] **Step 4: Document and commit the repeatable gate**

Document the two environment variables and the E2E command in README without machine-specific paths. Run `bash -n tests/ds4_e2e_test.bash` and the no-model shell suite again, then commit:

```bash
git add tests/ds4_e2e_test.bash tests/ds4_tools_test.bash README.md
git commit -m "test: add model-backed ds4 migration e2e gate"
```

## Mac Build and Test Commands (Run Last)

Run these from the implementation worktree after all task reviews. The acceptance comparisons must run before builds add artifacts to `.ds4/tree`; the model-backed E2E is a separate required gate after migration acceptance.

```bash
# External ds4-py prerequisite (set this to a local ds4-py checkout)
export DS4PY_PROJECT=/path/to/ds4-py
devenv shell -- uv sync --project "$DS4PY_PROJECT"
export PATH="$DS4PY_PROJECT/.venv/bin:$PATH"
devenv shell -- ds4py --help

# Shell syntax and tool behavior
devenv shell -- bash -n tools/ds4-*.bash tests/ds4_tools_test.bash
devenv shell -- bash tests/ds4_tools_test.bash

# Materialize the full common + qwen35 tree
devenv shell -- ds4-sync

# Required migration acceptance: identical Git tree and filesystem bytes
test "$(git -C .ds4/tree rev-parse 'HEAD^{tree}')" = "$(<.ds4/migration/flat.tree-id)"
diff -r -x .git .ds4/migration/flat .ds4/tree

# Pristine common-only and full-target checks, including ds4-py builds
devenv shell -- ds4-check --build

# CPU build and test/program compilation on the real full tree
devenv shell -- make -C .ds4/tree cpu
devenv shell -- make -C .ds4/tree clean
devenv shell -- ds4py build --src .ds4/tree
devenv shell -- make -C .ds4/tree ds4-agent tests/test_qwen35_verify_live tests/test_dflash_live

# Metal kernel tests on Apple Silicon
devenv shell -- make -C .ds4/tree test-qwen4-kernels

# Required model-backed E2E: dense qwen35, sync/restore, and generation parity
export DS4_TEST_MODEL=/path/to/dense-qwen35.gguf
devenv shell -- bash tests/ds4_e2e_test.bash
```
