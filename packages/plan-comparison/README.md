# Plan comparison core

`plan-comparison` is an isolated Python package for validating execution
manifests and preregistrations for a prose-versus-compiled workflow study. Its
CPU core is independent of Django and model runtimes. `typed-packets` is a
read-only local dependency; it remains the source of the packet schema and
static packet validation.

## Development

Use the repository development environment and this package's lockfile:

```bash
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/plan-comparison pytest packages/plan-comparison/tests
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/plan-comparison ruff check packages/plan-comparison
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/plan-comparison ruff format --check packages/plan-comparison
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/plan-comparison ty check \
  packages/plan-comparison/src/plan_comparison/contracts.py \
  packages/plan-comparison/src/plan_comparison/budget.py \
  packages/plan-comparison/src/plan_comparison/manifest.py \
  packages/plan-comparison/src/plan_comparison/workspace.py \
  packages/plan-comparison/src/plan_comparison/prepare.py \
  packages/plan-comparison/src/plan_comparison/slots.py \
  packages/plan-comparison/src/plan_comparison/gates.py \
  packages/plan-comparison/src/plan_comparison/records.py \
  packages/plan-comparison/src/plan_comparison/runner.py
```

The package has no model or Django runtime dependency. Live worker integration
is a separately approved adapter concern; importing the CPU core does not
authorize model execution.

`RunnerConfig` defaults to `mode="cpu"`. `pilot` and `deciding` modes require a
nonempty `live_authorization_ref`; deciding runs additionally require the
complete frozen registration and registered H1-H3 artifact hashes. The
`ExperimentRunner.check_capabilities` entry point also requires a separate
authorization reference. The optional ds4 adapter currently reports paired
execution as blocked because upstream cancellation rewind semantics remain
unverified; a fake-worker pass is not native Qwen or RNG evidence.

The DS4 worker adapter enforces a hard budget of 4,096 thinking tokens per
assistant reply by default. When the budget is reached, it forces the Qwen
model-card closing sentence and `</think>` one token at a time; pass
`thinking_budget=0` to disable the hook, or set a different non-negative token
limit. Usage accumulates across all thinking blocks in a reply. This does not
bypass request, context, or output-token caps, which can
still interrupt generation before the close sequence is complete.

The optional `think_until_first_write=True` adapter setting closes thinking
immediately on subsequent generations after the first successful workspace
write. Rejected writes do not activate it. Both prose tool writes and host-applied
compiled slot writes count. Restoring a boundary for a repair retry re-enables
thinking. This setting defaults to `False` so it can be evaluated separately
from retry and prompt changes. It uses logits hooks without changing the engine
thinking mode or rendered system prefix.

Context, prose, and compiled phases share one system instruction and tool schema.
Per-request allowlists enforce read-only context and compiled requests. Native
checkpoints include the complete host transcript, including the reply suffix,
so the next phase can reuse the full prefix.

DS4 `max_tokens` and `parser_error` responses consume the existing arm retry
allowance. Failed generations count against aggregate tokens and model calls.
Before retrying, the runner restores the pre-attempt workspace and native/host
boundary; budgets remain monotonic. Initial context preparation has no boundary,
so it clears the session and starts fresh, with `context_retry_limit=2` by
default (allowed range: 0–2). Exhaustion produces a distinct `context_failed`
pair result and stops the schedule. Packet context preparation retries from the
existing boundary using the compiled retry limit. Infrastructure failures remain
terminal, with exception type and message stored in host-only `harness_fault`
fields on attempt, arm, or pair records. These details are not worker feedback.

Private baseline drivers calling `_run_prose_arm` must pass the complete
`WorkerBoundary` returned by `capture_boundary`, replacing `boundary.evidence`
with `boundary`. A new experimental batch should retain the default thinking
policy unless it explicitly measures `think_until_first_write=True`.

Both arms run against the same visible packet tests: the prose arm has them
installed before its first attempt and may not write them. Arms that exhaust
their retries or budget are graded on the files their last attempt left behind.

## Scope

The v0 execution manifest is separate from the canonical typed-packet schema.
It links immutable plan and packet artifacts by SHA-256, declares exact source
edit slots and placements, and identifies visible tests with structured red
evidence. Registration validation requires complete H1-H3 artifact hashes,
task/seed pairs, model and runtime revisions, shared budgets, both arms' repair
policy, scoring procedures, and a numeric decision rule.

## CPU contracts

The public decoding and artifact-validation functions are in
`plan_comparison.manifest`:

```python
from pathlib import Path

from plan_comparison.contracts import ManifestInputs, PacketSource
from plan_comparison.manifest import (
    decode_execution_manifest,
    validate_manifest_artifacts,
)

manifest = decode_execution_manifest(Path("manifest.json").read_text())
inputs = ManifestInputs(
    task_id="E1",
    workspace=Path("references/customer-tracker/examples/E1/start"),
    plan_path=Path("E1.plan.md"),
    packet_sources=(
        PacketSource(
            packet_id="customer-tracker-e1-model-slice",
            path=Path("packages/typed-packets/examples/customer_tracker/E1.json"),
        ),
    ),
)
diagnostics = validate_manifest_artifacts(manifest, inputs)
```

The manifest has `manifest_version: 0`, a `task_id`, the raw-byte SHA-256 of
the frozen plan, and a nonempty ordered `packets` array. Each packet entry
binds a packet ID and raw-byte SHA-256 to its slots, placements, and red checks.
Callable slots identify a produced qualified name and the whole callable body;
ancillary slots identify either a structural node with a `body`/`definition`
extent, a unique exact text anchor with a byte extent, or a new whole file.
Preimage hashes bind only the exact existing target bytes or anchor, not the
whole file, so an earlier packet can change other regions without staling a
later independent slot. Paths must be canonical relative POSIX paths, IDs and
write extents must not conflict, and slots may not write packet test artifacts.
Packet and plan hashes are checked against host-supplied artifact paths. The
validator reads but does not write or execute those artifacts.

Red checks name a visible test function, expected exception, and a stable marker
present in that test source. This is only a structural contract: proving that a
run fails for the intended reason and that collection, environment, and timeout
errors are excluded belongs to the later gate runner.

`decode_registration` accepts only version `0` and requires exactly H1, H2,
and H3 in that order. Each task records its plan, manifest, and ordered packet
hashes; task/seed pairs cover all three tasks and specify each arm exactly once.
The registration also freezes model/runtime/tokenizer revisions, tool-policy
hash, scalar sampler/thinking settings, aggregate wall/token/call limits, the
prose repair policy, a compiled retry limit of at most two, four separate
scoring procedures, and a finite numeric decision rule.
`validate_registration_artifacts` compares those frozen hashes to host-owned
artifact digests. A valid registration is not live-run authorization.

## Explicit run entry points

The installed `plan-comparison` command exposes `capabilities` and `run`
subcommands. Both require a host-supplied `--factory module:function`; the
factory returns trusted task inputs and a lazy worker factory, so artifact
hashes and packet readiness are checked before a worker is created. `pilot` and
`deciding` runs require both `--live-authorization-ref` and
`--disposable-policy-ref`; `deciding` also requires a complete
`--registration` document. The CPU runner is intended for scripted workers
only and rejects a worker reporting `runtime_kind="live"`.

The visible H1-H3 plans, packets, and manifests are stored in
`experiments/reference-held-out/customer_tracker/`. Their artifacts are
hash-checked without opening protected graders or solutions. The conservative
Python validator currently marks H1-H3 packet readiness `inconclusive` for
decorated domain definitions, including `CustomerPage`; accordingly the
deciding sweep blocks before capability checks. This behavior is intentional
and fail-closed; changing it requires a separately approved treatment rather
than silently dropping the references.

## Preparation, slots, and gates

`prepare_packet` accepts the original packet bytes, its decoded execution
entry, and a typed-packet `ValidationContext`. Before writing, it checks the
packet hash, reruns packet validation against the current workspace, and
validates slot and placement preimages. It then installs the declared visible
tests, creates deterministic declarations and `NotImplementedError` callable
placeholders, and records the exact pre- and post-preparation workspace
snapshots. Imports are added only when explicitly declared in the packet and
given a manifest placement; no imports are inferred from prose or generated
code. Unsupported syntax or transformations fail closed and preparation
restores its original snapshot.

`apply_slot_edit(prepared, slot_id, content)` replaces only the selected
callable body, structural extent, text-anchor extent, or declared whole-file
creation target. It parses edited Python source, compares callable signatures
to the frozen packet declaration, preserves host-installed tests, and rejects
changes outside the slot. Every edit is transactional; rejected edits restore
the previous snapshot. `snapshot_workspace` and `restore_workspace` bind bytes,
file modes, and directory membership and refuse symlinks.

`PublicTaskInputs` supplies exact read and worker-write allowlists from the
trusted task adapter. Packet paths and compiled slots are checked against the
host write policy before worker capabilities are queried; a packet declaration
cannot widen that policy.

`run_gate` requires a host-supplied `GatePolicy` with an exact command
allowlist, explicit environment, wall-time limit, output cap, and termination
grace period. Commands are argument arrays with no shell. A red check is
accepted only when captured output identifies the declared test, expected
exception, and marker; a generic nonzero exit, collection failure, timeout,
truncated output, or unverifiable cleanup cannot satisfy it. If this platform
does not permit process-group termination, the direct child is stopped and the
gate is recorded as a harness error rather than a model failure.

The E1 and E2 manifests reference the read-only public packets in
`packages/typed-packets/examples/customer_tracker/`. E3 uses the explicit,
task-derived packet in `examples/customer_tracker/E3.packet.json` so its visible
red check exercises contact validation rather than only checking that a
callable exists. The non-Django packet is reused from `typed-packets` and
validated against the fixture in `examples/plain_python/start/`. None of these
examples uses held-out task or grader material.

File permissions and source paths are declarations for the later execution
harness, not an operating-system sandbox. This package does not run gates,
prepare source, load a model, grade protected tests, or authorize a live run.
