# PR #25 Review Fixes Design

## Intent

Address four review findings without changing the M3 harness's public behavior or native safety contract: separate DFlash policy selection from mutation, remove duplicate engine step state, make configuration diagnostics name the actual source, and share schema validators.

## Goals

- Make `select_step` a read-only policy/constructor operation and centralize decode/verify application in one controller helper.
- Capture the last resolved decode step only when `SatyrnEngine.close()` begins.
- Return typed resolved settings and prevent CLI-only validation failures from being labeled as `pyproject.toml` errors.
- Reuse the `config_io.py` mapping and think-budget document validators.
- Preserve pre-mutation failure state, post-MMA rollback, identity safety, metrics, and 100% model-free coverage.

## Non-goals

- No new CLI options, configuration fields, persistence behavior, or public runtime API.
- No ds4-py changes, native/live suite expansion, or unrelated restructuring.
- No change to the requirement that DFlash changes occur only between rounds.

## Approaches

1. **Selected: follow the review seams with safety-preserving application order.** Return `(DecodeStep, int | None)` from `select_step`; apply the step and optional verify mode through `_install`; snapshot the final step at close; use a typed `ResolvedSettings`; hoist shared validators. This removes the fragile mutation flag and duplicated state while keeping changes local.
2. **Minimal patches around the current structure.** Keep `SettingsDocument`, `on_step`, and mutation tracking and add special cases. This is smaller textually but leaves the fragility and duplicate sources identified by review, so it does not satisfy the request.
3. **General provenance-tracking configuration system.** Track a source for every nested field. This would handle arbitrary future mixed-source errors but is unnecessary for the current schema and review reproductions.

## Design

- `select_step(...)` performs support probes and constructs a step but never calls `set_verify_mode`. It returns the desired verify value (`0`, `1`, or `None` when the binding is unavailable).
- `RuntimeController._install(state, step, verify)` retains the exact state being applied, calls `session.set_decode_step(step)`, and then, when requested, sets verify mode on the worker. The same order is used for normal changes, rollback, and identity transitions; `_install_plain` owns the safe OFF transition. The initial no-op `set_decode_step(state.step)` remains the idle guard, and no generation can occur between the two synchronous apply operations.
- `_change` leaves selection/probe/construction failures untouched and enters `_fail_change` only for `_install` failures. `_fail_change` retains the existing requested state, footer, original-error propagation, and cleanup-error chaining.
- `SatyrnEngine` removes `on_step`/`_record_step` and stores `_finished_step = controller.resolved_step` immediately before controller teardown. `RuntimeController` retains the latest live `RuntimeState` reference whenever `state` is accessed, so `resolved_step` does not call the already-closed session during canonical CLI teardown. A resolved flag preserves `None` when setup failed before any decode step was applied. While open, `decode_step` continues to read the session-scoped controller state.
- `ResolvedSettings` is a frozen dataclass containing `values: dict[str, object]` and `source: Path`. `resolve_settings` validates only explicit CLI domain components before merging them; inherited project bias remains project-sourced. It validates the merged non-sampling Satyrn fields so project-shape and project-originated failures receive the source prefix, while the reviewer CLI reproductions remain unsourced. A typed `MissingDrafterPath` error replaces message matching. `resolve_config` unwraps the dataclass before mapping validation, copies its values, validates generic downstream sampling separately, then merges it so valid CLI overrides can repair project sampling values. Remaining merged sampling failures are project-sourced; generic CLI failures are unsourced.
- `config_io.py` owns `is_mapping` and `validate_think_budget_document`; both its document parser and `settings.py` use those functions.

## Verification

Add regression tests for close during the post-`session_start`/pre-after-hook boundary, both incorrect CLI source-prefix reproductions, and an unrelated existing project file. Reuse the existing mutation-failure and identity matrices for the structural controller refactor. Run focused tests, all model-free tests with coverage, the complete static gate, shell regression suite, and `git diff --check` before pushing and replying to each inline thread.
