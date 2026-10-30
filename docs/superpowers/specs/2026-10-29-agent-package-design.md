# Satyrn agent package design

| | |
| --- | --- |
| Date | 2026-10-29 |
| Status | Draft for review |
| Package | `satyrn-agent`, imported as `satyrn_agent` |
| Base | ds4-py M1/M2, plus the small generic companion changes in section 8 |
| Engine | The patched ds4 tree owned by this repository; DFlash is dense qwen35 on Metal |
| Related | `docs/specs/2026-10-24-ds4-patch-series-design.md`; ds4-py `docs/specs/2026-10-21-ds4-py-design.md` §9–10, §18, §22–23 |

## 1. Intent

Build the downstream Python package that turns ds4-py into the Satyrn agent.
The package owns the downstream bindings, the host-driven DFlash decode step,
and three small runtime capabilities: DFlash selection, native sampling
defaults, and a soft think budget. It must not fork ds4-py or move downstream
policy into ds4-py.

The first slice works against the M1/M2 engine facade directly. Harness
integration is a separate, later slice because ds4-py M3 owns `DS4Model`,
capability lifecycle, session state, and the TUI registries. This document
names that later slice **After M3** and does not design around unreleased M3
APIs.

The work also tests ds4-py's extension contract against a real downstream
consumer. Where M1/M2 lacks generic host wiring, ds4-py gets a small companion
change with no Satyrn or DFlash identifiers in it.

## 2. What exists, and what is missing

M1/M2 already provides the required engine primitives and most host seams:

- `Binding` records and the `ds4py.bindings` entry-point group;
- build-time signature probes, load-time ABI validation, and optional bindings;
- `engine.native.bind(name)` and `session.on_worker(fn)`;
- the single native worker thread and opaque raw handles for extensions;
- `DecodeContext`, `DecodeStep`, `PlainStep`, `accept()`, `commit()`,
  `before_sample()`, `sampling()`, cancellation, and rewind;
- committed-token transcript and parser state, tool-call stops, and logits
  hooks;
- the existing `ds4_engine_options.mtp_path` and `mtp_draft_tokens` fields in
  the native struct mirror.

The patched engine supplies the DFlash primitives. A verify has at most eight
rows: one anchor and up to seven drafts. `mtp_draft_tokens=0` selects the
engine's default of seven, clamped to the drafter and the context. Verify rows
in `DS4_VERIFY_MODE_MMA` are bitwise equivalent to serial evals in that same
mode. DFlash-mode numerics are not required to match ordinary decode numerics.

Three generic ds4-py connections are not yet public:

1. `generate(..., step=...)` accepts a step, but `Session.run_round()` has no
   way to select one and `EngineWorker` does not forward one.
2. `ds4py.open()` does not expose the existing MTP engine options needed to
   load a DFlash drafter.
3. `DecodeContext` observes only canonical committed history. It has no
   speculative overlay through which later rows can see tentative parser state,
   think counts, sampled IDs, and tool-syntax greedy sampling before native
   commit.

Section 8 defines those companion changes. No engine patch is part of this
package design.

## 3. Goals, non-goals, and anti-goals

### Goals

1. Install one typed `BINDINGS` tuple through `ds4py.bindings`, so every native
   function used by the package is covered by ds4-py's ABI probe and loader.
2. Load a DFlash drafter through the existing engine options and select the
   DFlash step with `auto`, `on`, or `off` policy.
3. Preserve ds4-py's token, parser, cancellation, and KV invariants across
   multi-token verification, including mid-block stops and discarded tails.
4. Run logits hooks before every target sample, including each selected verify
   row, so the think-budget capability remains active during DFlash decode.
5. Apply the patched engine's sampling defaults without overriding explicit
   caller values.
6. Provide a disabled-by-default, soft think-budget hook.
7. Measure DFlash behavior with real model E2E tests and reach 100% line and
   branch coverage for the new `satyrn_agent` Python code.
8. Keep the later harness slice small: an already configured ds4-py session
   must carry its decode step and hooks into M3 without a second token loop.

### Non-goals for the first slice

- Changes to DFlash, verify kernels, model loading, or any other engine code.
- A generic MTP `SpeculativeStep`; ds4-py reserves that for M5.
- CUDA, ROCm, distributed, or tensor-parallel DFlash support.
- Payload persistence or a `ds4_session_supports_payload` guard.
- Repetition suppression or a hard reasoning stop.
- Engine work between runs, a second front end, or records in a new downstream
  schema.
- Native DFlash test hooks for feature rows, rings, and selector lattices.
- Native `ds4_spec_stats` marshalling. Python counters and external timing are
  sufficient for this slice.
- Harness, CLI, TUI, persistence, and session-lifecycle customizations; these
  are **After M3**.

### Anti-goals

- DFlash-specific code or Satyrn imports inside ds4-py.
- A second worker, an inference server, or native calls from the caller thread.
- Bypassing the ABI manifest, declaring ctypes signatures in unrelated modules,
  or scattering raw-pointer handling through the package.
- Re-rendering sampled text to recover token IDs.
- Publishing a token, parser event, or tool call before its native state is
  committed.
- Falling back to `PlainStep` after a DFlash block has started or after a
  native failure. That would hide errors and can leave verify state open.
- Comparing DFlash output with ordinary-mode output and treating their numeric
  difference as a correctness failure.
- Using mocks for normal-path coverage, or excluding difficult branches from
  the coverage denominator to reach 100%.

## 4. Constraints

- Python 3.14 or later, a `uv` project, and a `src/` package layout.
- devenv/Nix supplies the shared development and test toolchain, with `uv`
  locking Python dependencies. Do not build parallel GNU/BSD compatibility
  branches for repository tooling or test helpers.
- The package depends on the ds4-py version containing section 8 and on
  `typing_extensions`. It has no harness dependency in the first slice.
- Only ds4-py's worker may call native functions. A `DFlashStep` runs inside
  that worker; its public configuration and metric snapshots run outside it.
- Raw pointers, ctypes buffers, and native return-code checks live in one
  downstream native adapter. Everything above it uses typed Python values.
- DFlash requires a loaded drafter and engine support. `is_qwen4` alone is not
  sufficient because it does not distinguish every supported dense target.
- While verify is open, the engine refuses eval, sync, rewind, payload and
  snapshot operations, another verify, and a mode change. Every path out of a
  step must close or invalidate that verify before returning.
- The first slice inherits ds4-py's native-open limits: inspection is not
  containment, and some native failures can still terminate Python.
- The full normal-path E2E and coverage gate needs macOS/Metal, the dense
  qwen35 target GGUF, and its matching DFlash drafter GGUF. Non-Metal CI can run
  packaging, typing, ABI-negative, and other non-live checks, but cannot be the
  final DFlash gate.
- PR #6 changes patch tooling, patch layout, CI, and its own plan. This new
  spec is independent of that PR's files.

## 5. Approaches considered

### A. Generic ds4-py companion seam plus the Satyrn package — selected

Add only decode-step forwarding and the existing MTP options to ds4-py. Keep
all bindings, DFlash behavior, policy, and capabilities in `satyrn_agent`.

This costs a coordinated ds4-py change, but it preserves the core/downstream
boundary and works with M3's `DS4Model` without replacing the session or token
loop. It also makes the new wiring useful to other extensions.

### B. A Satyrn-only adapter around private M2 internals

Call `session._worker` and `generate(..., step=...)` from a downstream adapter.
This avoids a ds4-py change today, but depends on private implementation,
duplicates round orchestration, and would need replacement when M3 arrives.

It is rejected because the small generic seam is less total machinery and is
exactly the extension boundary ds4-py intends to provide.

## 6. Package shape and public flow

Proposed initial layout:

```text
satyrn-agent/
├── pyproject.toml
├── src/satyrn_agent/
│   ├── __init__.py             # open, typed config and error exports
│   ├── bindings.py             # BINDINGS only; no ctypes calls
│   ├── config.py               # frozen, slotted configuration values
│   ├── engine.py               # open/configure and policy selection
│   ├── errors.py
│   ├── _native.py              # the only ctypes/pointer adapter
│   ├── dflash.py               # DFlashStep and Python metrics
│   └── capabilities/
│       ├── sampling.py         # native defaults and explicit overrides
│       └── think_budget.py     # soft logits hook
└── tests/
    ├── conftest.py              # shared real fixtures and alignment assertions
    ├── e2e/
    │   ├── test_abi_workflow.py # build → check → open → repeated rounds
    │   ├── test_policy.py
    │   ├── test_dflash_parity.py
    │   ├── test_dflash_boundaries.py
    │   ├── test_capabilities.py
    │   └── test_metrics.py
    └── abnormal/                # focused mock-based native/error modules
```

The public entry point is `satyrn_agent.open(...)`, returning a thin engine
factory wrapper. On its first and only `session()` call it:

1. creates the ds4-py session;
2. resolves and applies native sampling defaults;
3. installs the configured think-budget hook, if any;
4. probes DFlash support and installs either `DFlashStep` or `PlainStep`
   through the generic ds4-py API; and
5. returns the configured ds4-py `Session`, not a parallel session wrapper.

M3 can pass that same session to `DS4Model`; no Satyrn adapter is needed in the
model's request loop.

Illustrative typed configuration, with final names left to the builder:

```python
@dataclass(frozen=True, slots=True)
class ThinkBudgetConfig:
    max_tokens: int
    bias: float


@dataclass(frozen=True, slots=True)
class SamplingOverrides:
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    min_p: float | None = None


class DFlashMode(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class SatyrnConfig:
    dflash: DFlashMode = DFlashMode.AUTO
    drafter_path: Path | None = None
    draft_tokens: int = 0
    sampling: SamplingOverrides = SamplingOverrides()
    think_budget: ThinkBudgetConfig | None = None
```

`draft_tokens=0` means the engine default. Invalid booleans-as-integers,
negative draft counts, non-positive think budgets, non-finite sampling values,
and non-positive think bias fail before native open where possible.

## 7. Downstream bindings

`pyproject.toml` registers:

```toml
[project.entry-points."ds4py.bindings"]
satyrn = "satyrn_agent.bindings:BINDINGS"
```

The initial tuple contains exactly these inference and configuration functions,
with prototypes copied from the patched `ds4.h`:

- `ds4_engine_has_dflash`
- `ds4_engine_verify_rows`
- `ds4_session_set_verify_mode`
- `ds4_session_dflash_draft`
- `ds4_session_verify`
- `ds4_session_verify_select`
- `ds4_session_verify_commit`
- `ds4_engine_sampling_defaults`

All eight are **optional** at the ds4-py ABI layer. Entry-point discovery is
process-wide: making these required would make an unrelated upstream ds4 build
fail merely because `satyrn_agent` is installed. The Satyrn `on` policy, not the
loader, decides that a missing DFlash function is fatal. `auto` can use an
engine without the extensions, and native sampling defaults can retain
ds4-py's generic defaults when their optional function is absent.

The patched qwen35 E2E build asserts that all eight probes passed. A separate
ABI test proves that missing functions are listed as absent and that `on`
reports the missing capability by name. Optional symbols still require a fresh
`ds4py build` after installing the package: ds4-py correctly refuses an older
manifest that has no probe record for the newly discovered bindings.

The native adapter converts native return conventions immediately:

- `ds4_engine_has_dflash` returns a boolean presence flag;
- `ds4_engine_verify_rows` returns a non-negative row count;
- `ds4_engine_sampling_defaults` returns `void` and fills four checked
  out-parameters;
- draft count `>= 0` is success and `-1` is an error;
- verify setup, selection, commit, and mode setting return zero on success;
- error buffers become `DFlashError` with the native message and operation;
- draft buffers are bounded by the engine's verify-row count and configured
  maximum;
- no ctypes object or raw pointer escapes the adapter or the worker job.

## 8. Generic ds4-py companion changes

These changes are planned and reviewed in ds4-py, not silently implemented as
part of the Satyrn package. They contain no DFlash policy.

### 8.1 Decode-step selection

Add a `DecodeStep | None` field to `GenerateJob` and forward it to
`generate(..., step=job.decode_step)`. Add a session-level way to install a
step between rounds, such as `Session.set_decode_step(step)`. The exact public
name can follow ds4-py's conventions.

The session must:

- reject changing the step during an active or paused round;
- carry the same step through chat, raw, and reserve-resume jobs;
- retain `generate()`'s existing fallback to `PlainStep` when a step declares
  `hooks_every_sample = False` while hooks are installed;
- leave the default `None` behavior byte-for-byte equivalent to the current
  `PlainStep` path; and
- release the step with the session without adding another worker or native
  owner.

`DFlashStep.hooks_every_sample` is `True`, so installing a think-budget hook
must not silently disable DFlash.

### 8.2 Tentative decode transactions

Add a generic staged-decode transaction to `DecodeContext` for multi-token
steps. Conceptually it supports stage, publish, and discard operations; exact
method names belong to the ds4-py builder. `PlainStep` keeps its current direct
path and pays no speculative-overlay cost.

The transaction must:

- introduce a first-class capture/fork/restore primitive for the complete
  per-round streaming state: every family parser, UTF-8 `Decoder`,
  `ControlSpan`/stop-sequence matcher, and sampled history. Ad hoc
  `copy.copy`/`deepcopy` of selected fields is not sufficient;
- stage an accepted token and its verdict in a per-block overlay containing
  token IDs, `RoundStream`/parser/decoder/control state, sampled history, and
  buffered events, without mutating the canonical transcript or publishing to
  the caller;
- let `before_sample()` and `sampling()` read canonical plus staged state, so
  position, `think_tokens`, sampled IDs, parser state, and tool-syntax greedy
  sampling are exact for every tentative verify row;
- return a commit-time terminal verdict during staging, allowing the step to
  stop scanning before it samples or commits any later row;
- publish the exact staged prefix only after native commit, applying it to the
  canonical transcript and emitting buffered `Token`, thinking, text, parser,
  and tool-call events in their original order, even when staging already
  selected a terminal reason;
- discard the overlay without changing canonical history when a draft,
  verification, hook, or cancellation path abandons the block; and
- keep this policy in ds4-py rather than cloning the parser, stream, or
  transcript in Satyrn code.

This seam is required for correctness, not just test parity. Without it, a
Qwen tool opener inside a verify block cannot switch later rows to greedy
sampling, and the think-budget hook sees a stale count.

### 8.3 Existing MTP engine options

Expose `mtp_path` and `mtp_draft_tokens` through `EngineConfig` and
`ds4py.open()`, and pass them to the existing `EngineOptions` fields. Resolve a
relative drafter path on the caller thread, as for the model path, and keep its
encoded string alive for the native engine lifetime. Zero selects the engine's
default draft count.

The ds4-py API default remains its current `mtp_draft_tokens=1`, so existing
callers do not silently change behavior. `satyrn_agent.open()` explicitly
passes its own `draft_tokens` value, whose default zero selects DFlash's
default of seven. The companion change replaces the hardcoded value with the
config value and tests `None` path → null, encoded path lifetime, zero, one,
and seven.

No new engine option struct, binding, or DFlash-specific alias is introduced.

### 8.4 Compatibility checks

The ds4-py change keeps its own repository test policy and adds focused tests
for step forwarding, active-round rejection, reserve resume, hook fallback,
MTP option marshalling, and path lifetimes. Tentative-transaction tests prove
that a tool opener changes the next row to greedy, a metadata-sensitive hook
sees the exact tentative count, staged terminal tokens still publish after
native commit, and discarded overlays never leak events or tokens. For every
family, staged-then-published and direct serial observation must produce the
same token, thinking, text, tool-syntax, and tool-call events in the same
order, including chunk-boundary and control-matcher cases. The Satyrn
real-engine E2E suite is the downstream acceptance test for the combined
wiring.

## 9. DFlash policy

`DFlashMode` uses a `match` statement or an equivalent single dispatch point;
capability checks are not duplicated across the package.

- `off`: install `PlainStep` and leave verify mode off. A configured drafter may
  still be loaded by the engine, but it is not used for decode.
- `on`: require every DFlash binding, a loaded drafter, Metal, at least one
  verify row, and successful entry into `DS4_VERIFY_MODE_MMA`. Otherwise raise
  `DFlashUnavailable` before generation, naming the failed requirement.
- `auto`: use DFlash only when those support probes succeed; otherwise install
  `PlainStep`. Missing bindings, no configured/loaded drafter, a non-Metal
  backend, and zero verify rows are ordinary fallback conditions.

If the engine claims DFlash support but setup or decode fails unexpectedly,
`auto` raises; it does not hide a native error by switching modes. Fallback is
a pre-generation policy decision, never recovery in the middle of a block.

Resolve the requested mode once into a concrete `PlainStep` or `DFlashStep`
selection. Decode jobs consume only that resolved selection; they do not carry
and re-interpret `auto`, a separate availability flag, and a second step value.
This keeps contradictory policy states unrepresentable.

## 10. DFlash decode step

### 10.1 Block algorithm

The step owns one per-invocation state record with an explicit phase. A pending
anchor and its post-sample RNG state form one value, and the kept tokens carry
their own verdicts and RNG snapshots. Independent booleans must not be able to
describe contradictory states such as "verify closed" with rows still selected
or "anchor consumed" with a stale pending anchor.

The step may carry one sampled, unevaluated `pending_anchor` between verify
blocks.

1. **Choose the anchor.** Run `ctx.before_sample()`, sample with
   `ctx.sampling()`, and save the RNG state after the sample. If a previous
   block already produced a pending anchor, use it without sampling or running
   the hooks a second time.
2. **Classify and stage the anchor.** Check `ctx.is_stop(anchor)` before
   `ctx.accept(anchor)`. A stop token ends without staging or native movement.
   Otherwise accept and stage it in the tentative transaction. If its verdict
   is `STOP_AFTER` for any reason (budget, tool close, parser error, or stop
   sequence), skip drafting and row sampling: close the speculative phase with
   one ordinary `session.eval(anchor)`, publish the staged anchor, and return.
   No verify is open on this path.
3. **Draft.** Ask `ds4_session_dflash_draft` for at most the configured and
   engine-supported number of drafts. Zero drafts is valid.
4. **Verify.** Call `ds4_session_verify(anchor, drafts)` and mark verify open in
   the Python state machine only after the native call succeeds.
5. **Select and sample rows.** For each row, select it, run
   `ctx.before_sample()`, sample with the canonical-plus-staged sampling state,
   and record the post-sample RNG state.
   - Check `ctx.is_stop(candidate)` before `accept()`. On a stop, keep the
     already staged prefix, do not stage the stop, stop scanning, and defer
     `finish("stop_token")` until after publication. This avoids
     `DecodeContext.finalized` suppressing the kept prefix's publication.
   - At the first mismatch, the sampled replacement becomes the next pending
     anchor. It is neither accepted nor staged yet; stop scanning rows.
   - After the last draft, the sampled bonus token likewise becomes the next
     pending anchor without another acceptance or sample.
   - For a matching draft, call `ctx.accept()` and stage the token. Its
     tentative parser, stream, and hook state now includes this token. Stop
     immediately on `STOP_AFTER`, including budget and tool/parser stops;
     never sample later rows or a bonus token.
6. **Commit native state.** Commit exactly the staged anchor plus accepted
   draft prefix. This closes verify. A mismatch or bonus remains unevaluated.
7. **Publish in order.** Publish the staged transaction only after native
   commit. Staging has already observed tool closes and parser errors, so no
   later native rows exist to rewind. If a stop was deferred, finish with
   `stop_token` only when no earlier staged terminal verdict takes precedence.
8. **Continue or return.** Carry a pending anchor into the next block only if
   generation will continue. On the next block its acceptance can produce the
   budget `STOP_AFTER` described in step 2, in which case it is evaluated and
   published exactly once. Cancellation or any other terminal verdict discards
   an unused pending anchor and restores its speculative RNG advancement.

The tentative transaction is owned by ds4-py; Satyrn does not invent a second
transcript, parser, or event stream. Native commit precedes every externally
visible token or parser event, while later row samples still see exact
tentative metadata.

### 10.2 Stop, cancel, and error invariants

At every successful or controlled-stop return:

- transcript length, native position, and emitted `Token` IDs describe the same
  kept prefix;
- stop tokens are neither evaluated nor staged, and accepting one cannot
  suppress publication of the preceding prefix;
- a tool closing token is kept, and later drafts are neither sampled nor
  present in the transcript or native state;
- a mismatch keeps the accepted prefix and uses the replacement exactly once;
- a budget stop at an anchor, replacement, or bonus keeps that token through a
  one-token eval and performs no further draft or row sample;
- no unused sampled bonus token survives cancellation or a terminal verdict;
- the RNG state corresponds to the kept samples, matching serial DFlash-mode
  decode for the same seed, parser state, and hooks;
- no verify remains open, and no sync, rewind, payload, or snapshot job is
  attempted while one is open; and
- a runtime failure is never converted into a silent plain-decode fallback.

Cancellation after an accepted anchor but before verify uses the same
one-token eval and publication path as an anchor budget stop, then returns
`interrupted`. Cancellation or a hook exception while verify is open commits
only the staged prefix (including the anchor) to close verify, publishes it,
and then finishes or re-raises. A draft/verify setup failure before native
state advances discards the overlay and restores the block-start RNG.

If native commit or cleanup fails, canonical publication does not pretend to
succeed. Chain the original and cleanup errors as applicable, invalidate or
close the session, and forbid further native work on uncertain state. This is
the explicit exception to alignment claims: a failed native operation is
reported as unusable rather than as a valid prefix.

The ds4-py tentative transaction makes `LogitsView.position`, `think_tokens`,
`sampled_tokens`, and parser state exact for each staged row. Canonical
history and external events still change only after native commit.

### 10.3 Metrics

`DFlashStep` keeps Python-only counters for committed blocks, drafts offered,
drafts accepted, replacement anchors, and discarded tails. An immutable
metrics snapshot computes acceptance rate without a native stats struct.
Counters reflect the final committed prefix, not tentative rows later rewound.

The first slice exposes these snapshots for tests and diagnostics only. It
does not persist them, add TUI status, or define a JSON record format. E2E
benchmarks measure serial and speculative wall time externally.

## 11. Runtime capabilities

### 11.1 Native sampling defaults

After session creation and before the first round, call
`ds4_engine_sampling_defaults` on the worker when present. Merge values in
this order:

1. ds4-py's family defaults;
2. native engine defaults, for fields the binding returns; then
3. explicit `SamplingOverrides` and the caller's seed.

An explicit zero is a value, not a missing override. The merged result replaces
`engine.sampling_defaults` before the first round reads it. Session construction
may already have captured the seed, but this native function returns no seed
and cannot invalidate that RNG. If the optional binding is absent, the ds4-py
defaults remain unchanged.

The capability does not change sampling later in a round. ds4-py's tool-syntax
greedy override still takes precedence at each sample.

### 11.2 Soft think budget

`ThinkBudgetConfig` is `None` by default. When configured, resolve `</think>`
to exactly one rendered token before installing the hook. Registration happens
between rounds through `session.add_logits_hook`.

The hook is a pure worker-thread function over `LogitsView`:

```python
if view.in_think and view.think_tokens >= config.max_tokens:
    view.bias(end_think_token, config.bias)
```

It applies on every later sample that still satisfies the condition, including
selected DFlash rows. It does not inject a token, truncate text, cancel the
round, change the transcript, or guarantee closure. It performs no engine,
session, harness, cancellation, or blocking-I/O call.

A model that cannot resolve the marker to one token fails configuration with a
clear error rather than tokenizing user content or guessing an ID.

## 12. Errors and observability

Use a small typed hierarchy rooted at `SatyrnError`:

- `ConfigurationError` for invalid values and think-marker resolution;
- `DFlashUnavailable` for an unmet `on` requirement;
- `DFlashError` for draft, verify, selection, commit, and cleanup failures;
- existing ds4-py ABI and engine errors propagate unchanged at their own
  boundaries.

Messages name the operation, model/backend capability, and native error where
available. Exception text is not a stable machine-readable schema.

## 13. After ds4-py M3

The first slice must leave these integration points, but does not implement
them:

- construct the default harness agent with the already configured ds4-py
  session;
- expose DFlash mode, drafter path, draft count, sampling overrides, and think
  budget through the CLI and project settings;
- add `/dflash` and think-budget commands through the TUI command registry;
- publish DFlash state and acceptance rate through the status registry;
- keep mutable capability settings in `session.state`, including the correct
  `/new`, `/switch`, and fork behavior;
- decide whether changing DFlash mode is allowed only between prompts and how
  a paused round is closed first;
- add payload-support guards with M3/M4 persistence; and
- integrate metrics with run telemetry only if the team chooses a schema then.

No second front end or downstream persistence schema is implied by this list.

## 14. Implementation and typing policy

- Use current Python 3.14 typing syntax and `typing_extensions` where it
  improves the contract, including precise protocols, `Self`, `override`, and
  narrowed result types as appropriate.
- Run strict `basedpyright` over `src/` and tests. Native ctypes callables are
  wrapped immediately behind typed protocols; unchecked `Any` and `cast` are
  not an acceptable way to silence the native boundary.
- Prefer frozen, slotted dataclasses for values, enums for closed modes, and
  explicit state types for the decode state machine.
- Use the walrus operator, early returns, and `match` statements where they
  remove nested or repeated logic. Keep one capability dispatch and one native
  error-conversion path rather than copying conditions.
- Keep raw pointers, array sizes, and buffer lifetimes inside `_native.py`.
  Public and decode-step code handles integers, paths, immutable values, and
  typed snapshots only.
- Keep row sampling, native commit/publication, and verify cleanup in one path
  each. Normal, stop, cancellation, and error exits select states in the state
  machine; they must not become separate copies of the decode loop.
- Share real-engine fixtures, serial/speculative comparison, and one
  token/transcript/native-position/RNG/event alignment assertion across the
  E2E cases. A new boundary case supplies inputs and expected outcomes, not a
  copy of the checking machinery.
- Do not add abstractions solely to satisfy a style rule; the decode and native
  invariants take precedence over brevity.

## 15. Verification

### 15.1 Real-component E2E

Normal-path coverage uses the actual Satyrn package, the companion ds4-py, a
patched `libds4`, and real GGUFs. `FakeNative`, scripted native steps, and mock
models do not count as normal-path coverage.

The Metal E2E suite covers:

1. **Complete public workflow:** install the package, run `ds4py build`
   against the patched tree, verify all eight bindings in the manifest, load
   them via `ds4py check`, open through `satyrn_agent`, and run consecutive
   rounds through the resulting public session. The exact built library,
   manifest, configured session, and generated state must agree across this
   whole workflow; isolated internal checks are not a substitute.
2. **Policy:** real opens with and without a drafter cover `auto`, `on`, and
   `off`, native defaults, explicit-zero overrides, and successful verify-mode
   setup.
3. **Serial parity:** from one real DFlash-mode snapshot, compare serial
   `PlainStep` and speculative `DFlashStep` token streams for greedy and seeded
   stochastic decoding, including parser/hook operation and RNG continuation.
4. **Boundaries:** real generation covers full and partial draft acceptance,
   mismatch replacement, zero drafts, max tokens, stop tokens, tool-call close,
   parser error, stop sequence where supported, context reserve, and cancel.
   Assertions compare transcript, native position, emitted events, tool calls,
   and RNG continuation after every case.
5. **Capabilities:** native Qwen defaults affect real samples unless explicitly
   overridden; a low think budget changes real decoding through the closing
   marker's logit without injecting the marker into the transcript.
6. **Metrics and speed:** counters reconcile with real committed streams, and
   a documented prompt corpus compares serial/speculative wall time and
   acceptance rate. Speed is reported with machine, backend, model, quant, and
   drafter; a noisy timing regression alone is not a correctness failure.

Prompts and seeds must be checked into the E2E fixtures with the exact model
and drafter identities. Check in a corpus-to-branch mapping showing which case
covers every normal-path decode branch. If a required branch is not produced
by the real corpus, extend or adjust the corpus before implementation is
accepted; an unreachable required case triggers re-planning, not a mock or a
coverage exclusion. This mapping is a first-class deliverable because the
live corpus is the deterministic record of the 100% normal-path gate.

### 15.2 Abnormal paths

Mocks are allowed only for failures that are unsafe or impractical to induce
with the real engine: missing/incompatible bindings, native error returns,
hook exceptions, commit/cleanup failure, invalid native counts, and simulated
unsupported capabilities. Include faults where an operation performs its side
effect and then reports failure; a nonzero return must not cause cleanup to
discard the last valid state or permit another native operation on uncertain
state. Each test still checks the real Satyrn state-machine cleanup and error
translation rather than mocking that logic away.

### 15.3 Gates

Run at minimum:

```bash
uv run basedpyright src tests
uv run pytest tests/abnormal
uv run pytest tests/abnormal tests/e2e \
  --cov=satyrn_agent --cov-branch --cov-report=term-missing \
  --cov-fail-under=100
git diff --check
```

The E2E command requires the target and drafter environment variables and the
patched tree. Record the command, Mac model, macOS version, Metal backend,
GGUF paths/quantization, ds4 tree commit, ds4-py companion commit, coverage
result, and live parity result in the implementation PR.

The 100% line and branch requirement applies to new `satyrn_agent` code. The
small ds4-py companion change follows ds4-py's own gates and is additionally
exercised by this E2E suite. There are no coverage exclusions for inconvenient
normal-path branches.

## 16. Done when

- All eight bindings are discovered and probed through the installed entry
  point; after a rebuild, missing optional functions do not break unrelated
  ds4-py builds, while stale pre-install manifests still fail closed.
- The generic ds4-py companion tests pass, with no Satyrn-specific code in
  ds4-py.
- Real Metal E2E covers the complete build/check/open/repeated-round workflow
  and proves DFlash/serial parity in DFlash mode, including stops,
  cancellation, parser events, hooks, and seeded RNG continuation.
- `auto`, `on`, and `off` behave as specified, with no mid-block fallback.
- Native defaults preserve explicit overrides, and the disabled-by-default
  think budget works through both plain and DFlash decode.
- Metrics reconcile with committed streams; no M3 UI or persistence dependency
  has entered the first slice.
- Strict typing, abnormal tests, the real E2E suite, and 100% line/branch
  coverage pass on the documented machine.
- The **After M3** section remains a separate later design/implementation
  slice.

## 17. Calls made and builder latitude

Calls made in this design, which the reviewer may challenge:

- All downstream bindings are optional at the ABI layer; `on` enforces their
  presence at runtime.
- `auto` is the default, while think budget is opt-in.
- The first public flow returns a configured ds4-py session, not a second
  session abstraction.
- Metrics are Python-side diagnostic values, not native stats or persisted
  records.
- Coverage means both line and branch coverage for the new Satyrn package;
  ds4-py keeps its own test policy.
- Strict `basedpyright` is the initial type gate.

The builder may choose exact internal helper names, exception wording,
configuration keyword names, E2E prompt text and seeds, and small module
boundaries. The builder may not weaken native/thread confinement, token/KV/RNG
alignment, real-normal-path testing, or the M3 boundary without a new design
decision.
