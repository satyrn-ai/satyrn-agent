# Satyrn Agent Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the typed downstream Satyrn package, its optional native bindings, DFlash policy/decode step, sampling and think-budget capabilities, and portable plus real-engine verification.

**Architecture:** `satyrn_agent.open()` wraps one ds4-py `Engine` and configures its only `Session` on first use. One ctypes adapter owns all optional native calls; immutable configuration and typed Python values sit above it. `DFlashStep` runs on ds4-py's worker and uses its tentative staging transaction so native commit precedes publication.

**Tech Stack:** Python 3.14, ds4-py companion commit `02562e51589d1db75ba96c23cd05603bf2a248dd`, typing_extensions 4.16, ctypes, pytest/pytest-cov, Ruff, ty, prek, patched ds4 qwen35/Metal.

**Spec:** `docs/superpowers/specs/2026-10-29-agent-package-design.md`

## Global Constraints

- Only ds4-py's worker calls native functions; raw pointers, ctypes buffers, and return-code conversion stay in `src/satyrn_agent/_native.py`.
- All eight downstream bindings are optional at ABI discovery; `DFlashMode.ON`, not the loader, enforces presence.
- Use stdlib `TypeIs`, never `TypeGuard`; use lowercase `typing_extensions.sentinel` where an actual sentinel contract is needed.
- Do not fork ds4-py, add Satyrn identifiers to it, create another worker/token loop, or implement M3 CLI/TUI/persistence integration.
- `auto` falls back only before generation; never recover a started/failed DFlash block with `PlainStep`.
- Stop tokens are not staged/evaluated; native commit precedes every staged event; discard never leaks tentative events.
- Native commit/cleanup uncertainty calls `DecodeContext.poison()` and forbids later ordinary native work.
- Normal-path coverage requires real patched ds4 and real GGUFs. Portable doubles are for abnormal paths and policy only.
- Keep Python 3.14, frozen uv, complete prek, and existing shell suite green.

## Review Focus

- **Stop or terminal verdict at an anchor/replacement/bonus:** exactly one ordinary eval and publication, with no later row sample; Task 7 tests token/native/RNG alignment.
- **Hook exception or cancellation with verify open:** commit only the accepted prefix, close verify, publish it, then finish/re-raise; Task 8 checks cleanup and exception identity.
- **Native side effect followed by failure:** never publish uncertain tokens or admit another ordinary native operation; Task 8 checks poison causes and exactly-once engine cleanup.
- **Explicit zero and boolean-as-integer configuration:** zero is a valid override while booleans are rejected; Tasks 1 and 3 pin validation and merge behavior.
- **Absent optional symbols/stale manifests:** unrelated ds4 builds remain usable, `auto` falls back, and `on` names the missing capability; Tasks 1, 2, and 4 pin the boundary.
- **Tentative parser/hook metadata:** later rows see canonical-plus-staged state but no event escapes before commit; Tasks 6 and 9 cover raw doubles and real chat/parser flows.

---

### Task 1: Package, immutable configuration, errors, and bindings

**Files:**
- Modify: `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`
- Create: `src/satyrn_agent/__init__.py`, `config.py`, `errors.py`, `bindings.py`
- Create: `tests/unit/{test_config,test_bindings}.py`

**Interfaces:**
- Produces: `SatyrnConfig`, `SamplingOverrides`, `ThinkBudgetConfig`, `DFlashMode`; `SatyrnError`, `ConfigurationError`, `DFlashUnavailable`, `DFlashError`; optional `BINDINGS: tuple[Binding, ...]`.

- [ ] **Step 1: Write failing configuration and binding tests**

Pin frozen/slotted defaults; reject booleans-as-integers, negative drafts/top-k, non-finite or negative sampling values, out-of-range top-p/min-p, non-positive think limits/bias, and `on` without a drafter before native open. Assert exactly the eight specified prototypes, all `required=False`, and entry-point discovery from installed metadata.

- [ ] **Step 2: Run tests and confirm RED**

Run `devenv shell -- uv run --frozen pytest tests/unit/test_config.py tests/unit/test_bindings.py -q` after updating dependencies but before implementing modules. Expected: collection fails because `satyrn_agent` is absent.

- [ ] **Step 3: Add package/build configuration**

Use `uv_build`; remove `tool.uv.package=false`; add the pinned ds4-py Git dependency and existing typing_extensions dependency. Register `ds4py.bindings` entry point `satyrn = "satyrn_agent.bindings:BINDINGS"`. Add `src` to ty and pytest markers `build`/`live`; add pytest-cov and a portable unit CI command without changing the quality job topology.

- [ ] **Step 4: Implement values, errors, and declarations**

Implement the exact eight prototypes from the patched `ds4.h`, with no extra test-hook or stats bindings. Validate configuration in dataclass `__post_init__` methods. Re-export only the intended public configuration/error API and `open` (added in Task 4).

- [ ] **Step 5: Run tests/static checks and commit**

Run focused tests, `ruff check`, `ruff format --check`, `ty check`, and `uv build --wheel`; verify the wheel contains `satyrn_agent` and entry-point metadata. Commit as `feat(agent): add typed package configuration and bindings`.

### Task 2: Confine ctypes in one optional native adapter

**Files:**
- Create: `src/satyrn_agent/_native.py`
- Create: `tests/abnormal/test_native.py`

**Interfaces:**
- Produces: `NativeSampling`; `DFlashNative` protocol and `CtypesDFlashNative` with `missing_dflash`, `has_dflash(engine_raw)`, `verify_rows(engine_raw)`, `set_verify_mode(session_raw, mode)`, `draft(session_raw, anchor, maximum)`, `verify(session_raw, anchor, drafts)`, `select(session_raw, row)`, `commit(session_raw, rows)`, and `sampling_defaults(engine_raw)`.

- [ ] **Step 1: Write failing adapter tests**

Use scripted bound callables only at this abnormal boundary. Cover absent symbols, boolean/count conversion, negative rows, draft limits and invalid counts, zero/nonzero status, native error text/operation, bounded buffers, and all four sampling out-parameters. Assert no ctypes object escapes return values.

- [ ] **Step 2: Confirm RED, then implement the adapter**

Bind symbols lazily through ds4-py's `Native.bind`; keep `Any` and ctypes signatures only in `_native.py`. Allocate error/draft/out buffers at call time, convert immediately, and centralize operation-error construction. `DS4_VERIFY_MODE_MMA=1` and `OFF=0` are the only modes.

- [ ] **Step 3: Verify and commit**

Run `pytest tests/abnormal/test_native.py`, Ruff, and ty. Commit as `feat(agent): add typed optional native adapter`.

### Task 3: Native sampling defaults and soft think budget

**Files:**
- Create: `src/satyrn_agent/capabilities/{__init__,sampling,think_budget}.py`
- Create: `tests/unit/{test_sampling,test_think_budget}.py`

**Interfaces:**
- Produces: `merge_sampling(base, native, overrides, seed) -> SamplingPolicy`; `ThinkBudgetHook` callable over `LogitsView`; `resolve_end_think(engine) -> int`.

- [ ] **Step 1: Write failing capability tests**

Prove family defaults < native defaults < explicit overrides < caller seed; explicit zero survives; absent native defaults preserve the base. Prove the hook biases only when `in_think` and the threshold is reached, applies on later samples, and performs no other operation. Prove marker resolution requires exactly one rendered token and never guesses an ID.

- [ ] **Step 2: Confirm RED and implement**

Use pure immutable merge logic and a small hook object holding the resolved token/config. The hook executes only `view.bias(token, bias)` and has no engine/session/blocking-I/O dependency.

- [ ] **Step 3: Verify and commit**

Run focused tests and static checks. Commit as `feat(agent): add sampling defaults and think budget`.

### Task 4: Engine factory and one-point DFlash policy

**Files:**
- Create: `src/satyrn_agent/engine.py`
- Modify: `src/satyrn_agent/__init__.py`
- Create: `tests/unit/test_engine.py`

**Interfaces:**
- Produces: `SatyrnEngine.session() -> Session`, `.close()`, context-manager methods; `satyrn_agent.open(...) -> SatyrnEngine`; one `_select_step(...) -> PlainStep | DFlashStep` policy result.

- [ ] **Step 1: Write failing factory/policy tests**

Cover first-and-only session, idempotent close, `off`, `auto` fallback for missing binding/drafter/backend/zero rows, `on` errors naming each requirement, and unexpected setup errors propagating in `auto`. Assert native defaults are merged before the first round, the optional hook is installed once, and the resolved step is passed to `Session.set_decode_step`.

- [ ] **Step 2: Confirm RED and implement**

Mirror ds4-py open options while passing `config.drafter_path` and `config.draft_tokens` explicitly. Perform adapter probes through `session.on_worker`; configure sampling, think hook, and the concrete step between rounds. Return the actual configured ds4-py `Session`, not a second session wrapper.

- [ ] **Step 3: Verify and commit**

Run focused tests, static checks, and wheel build. Commit as `feat(agent): configure sessions through DFlash policy`.

### Task 5: DFlash state values and metrics

**Files:**
- Create: `src/satyrn_agent/dflash.py`
- Create: `tests/abnormal/test_dflash_metrics.py`
- Create: `tests/abnormal/_decode_helpers.py`

**Interfaces:**
- Produces: `DFlashStep.hooks_every_sample=True`, `DFlashStep.run(session, ctx)`, immutable `DFlashMetrics`, and internal explicit phase/pending-anchor/block records.

- [ ] **Step 1: Build real DecodeContext test helpers and failing metric tests**

Use real ds4-py `DecodeContext`, `GenerateJob`, `Transcript`, `Rng`, and `PlainStep`-compatible fake native handles. Only the optional DFlash adapter is scripted. Test zero/committed acceptance rate and that counters change only after successful native commit, not staged/discarded rows.

- [ ] **Step 2: Confirm RED and implement state/metrics skeleton**

Define explicit idle/staging/verify-open phases and a pending anchor carrying token plus pre/post-sample RNG. Implement thread-safe immutable snapshots for committed blocks, offered/accepted drafts, replacements, discarded tails, and acceptance rate.

- [ ] **Step 3: Verify and commit**

Run focused tests and static checks. Commit as `feat(agent): add DFlash decode state and metrics`.

### Task 6: DFlash anchor, verify rows, commit, and publication

**Files:**
- Modify: `src/satyrn_agent/dflash.py`
- Create: `tests/abnormal/test_dflash_blocks.py`

**Interfaces:**
- Consumes: `DFlashNative`, real `DecodeContext.begin_staging/stage/publish/discard`, and metrics/state from Task 5.
- Produces: complete normal block algorithm for anchor eval, draft, verify, row sampling, matching drafts, mismatch replacements, and bonus anchors.

- [ ] **Step 1: Write failing block tests**

Cover anchor stop before native movement; anchor terminal verdict through one eval; zero drafts; full acceptance plus bonus; first/middle mismatch replacement; pending anchor reused exactly once; no duplicate hook/sample; commit-before-event ordering; transcript/native-position/emitted-token alignment; and metrics for kept prefixes/discarded tails.

- [ ] **Step 2: Confirm RED and implement one decode path**

Keep one anchor path, one row-sampling path, and one native-commit/publication path. Stage accepted tokens with their actual verdicts. Commit the anchor plus accepted draft prefix; carry unevaluated mismatch/bonus anchors only when generation continues.

- [ ] **Step 3: Verify and commit**

Run focused block/metrics tests, all abnormal/unit tests, and static checks. Commit as `feat(agent): implement DFlash verify blocks`.

### Task 7: Stop, limit, cancellation, and RNG boundaries

**Files:**
- Modify: `src/satyrn_agent/dflash.py`
- Create: `tests/abnormal/test_dflash_boundaries.py`

- [ ] **Step 1: Write failing boundary tests**

Cover stop candidate after an accepted prefix; budget/tool/parser `STOP_AFTER`; max tokens; cancellation before verify and during rows; unused replacement/bonus discard; deferred `stop_token` publication; exact pre/post-sample RNG restoration; no later row samples after a terminal verdict.

- [ ] **Step 2: Confirm RED and implement controlled exits**

Reuse the one-token eval path for accepted-anchor cancellation/terminal verdicts. Commit/publish accepted prefixes before finishing or returning. Restore only speculative RNG advancement that serial decode would not retain; do not rewind RNG for a genuinely sampled stop.

- [ ] **Step 3: Verify and commit**

Run all boundary/block tests and the portable suite with branch coverage. Commit as `fix(agent): preserve DFlash stop and RNG invariants`.

### Task 8: Native failures, cleanup, and fatal poisoning

**Files:**
- Modify: `src/satyrn_agent/dflash.py`, `_native.py`
- Create: `tests/abnormal/test_dflash_failures.py`

- [ ] **Step 1: Write failing failure-injection tests**

Cover draft/verify setup failure before advancement; select/sample/hook exceptions with verify open; commit and cleanup failure; operation side effect followed by nonzero status; original/cleanup exception chaining; no uncertain publication; `ctx.poison` identity; no later native operation; owner cleanup exactly once; no plain fallback.

- [ ] **Step 2: Confirm RED and implement failure ownership**

Discard only known-unadvanced setup overlays. On open verify, commit the accepted prefix as controlled cleanup where valid. If commit/cleanup leaves state uncertain, chain errors and call `ctx.poison` with the fatal error; never publish a prefix as if native commit succeeded.

- [ ] **Step 3: Verify and commit**

Run failure tests, all portable tests, and static checks. Commit as `fix(agent): poison uncertain DFlash native failures`.

### Task 9: Real patched-engine E2E and branch corpus

**Files:**
- Create: `tests/conftest.py`, `tests/e2e/corpus.json`, `tests/e2e/README.md`
- Create: `tests/e2e/test_{abi_workflow,policy,dflash_parity,dflash_boundaries,capabilities,metrics}.py`

- [ ] **Step 1: Define real fixtures and shared alignment assertion**

Read explicit model, drafter, patched library/source environment; skip with `live`/`build` markers when absent. Fixtures run the real installed package, ABI build/check, public open, repeated sessions/rounds, snapshots, and one token/transcript/native-position/RNG/event alignment assertion. Check in prompts, seeds, model/drafter identities, and corpus-to-normal-branch mapping.

- [ ] **Step 2: Implement real workflow and policy E2E**

Cover all eight ABI probes, missing-symbol behavior separately, auto/on/off, native defaults, explicit zero, successful MMA setup, and consecutive public rounds.

- [ ] **Step 3: Implement real parity and boundary E2E**

From one real DFlash-mode snapshot, compare serial and speculative greedy/seeded stochastic streams, hooks, parser events, and RNG continuation. Exercise full/partial acceptance, mismatch, zero drafts, limits, stop tokens, tool close, parser error, stop sequence where supported, reserve, and cancellation without comparing DFlash numerics to ordinary mode.

- [ ] **Step 4: Implement real capabilities/metrics/speed E2E**

Verify Qwen defaults and overrides through real samples, soft think bias without marker injection, committed metrics reconciliation, and documented serial/speculative wall time with machine/model/drafter metadata. Timing regression alone is not correctness failure.

- [ ] **Step 5: Run available live gates and record evidence**

When model/drafter/library are available, run the full E2E plus 100% line/branch coverage and adjust the real corpus for missing normal branches. Otherwise run all portable gates, explicitly record the missing live inputs, and do not claim the design's live Done criteria. Commit as `test(agent): add real DFlash acceptance coverage`.

### Task 10: Documentation, complete verification, review, and stacked PR

**Files:**
- Modify: `README.md`, `docs/development.md`, `AGENTS.md` only where package commands are now real
- Create: `docs/reports/agent-package-validation.md`

- [ ] **Step 1: Document package API and verification boundary**

Show typed `satyrn_agent.open` configuration, ds4-py companion pin, ABI rebuild requirement, portable commands, real E2E inputs, and the M3 non-goal. Record exact companion/patched ds4 revisions and all observed results without substituting portable tests for live parity.

- [ ] **Step 2: Run final portable verification**

Run frozen prek, unit+abnormal pytest with branch coverage, wheel build/content inspection, actionlint, existing shell suite, and `git diff --check`. Run live gates when inputs exist and distinguish their result explicitly.

- [ ] **Step 3: Review and publish**

Inspect the complete diff against the agent spec. Obtain independent Kimi 3.1 Pro and DeepSeek reviews, verify findings, and fix valid issues with focused RED→GREEN tests. Push `feat/agent-package` and open a stacked PR whose base is `build/python-quality-foundation`.
