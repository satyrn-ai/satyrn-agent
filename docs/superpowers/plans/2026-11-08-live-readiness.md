# Live Readiness Fixes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement issues #15, #14, and #17 plus thinking until the first successful write, with thinking reset on repair retries.

**Architecture:** Keep failure contracts independent of the optional DS4 runtime. Preserve native prefix reuse with fixed instructions, fixed tool definitions, and logits-based thinking suppression. Restore failed model attempts transactionally without refunding resource use.

**Tech Stack:** Python, Pydantic AI, pinned ds4-py, pytest, Ruff, ty.

**Spec:** User-approved four-part behavior in this conversation; GitHub issues satyrn-ai/satyrn-agent#14, #15, and #17.

## Global Constraints

- Work only in `.worktrees/live-fixes` on `fixes/live-readiness`.
- Preserve the unresolved native cancellation capability gate.
- Test with FakeNative and one isolated native E3 pilot before overnight runs; no external messages.
- Retry only token-cap and parser failures; keep infrastructure failures terminal.
- Restore workspace, native boundary, host history, binder provenance, and thinking policy together; do not reset budgets.

## Review Focus

- Exceptions after partial writes must retain host-only causes.
- Failed model calls must still consume budget.
- Tool definitions as well as instructions must remain fixed across phases.
- Read-only phases must refuse write and gate tools even though schemas are fixed.
- Thinking suppression must preserve the rendered system prefix and reset on retries.

### Task 1: Preserve harness causes (#15)

**Files:** `contracts.py`, `runner.py`, `gates.py`, `tests/test_runner.py`, `tests/test_budget_records.py`, package README.

**Interfaces:** Add structured `HarnessFault` details to attempt/arm results without using worker-visible feedback.

- [x] Reproduce prose/compiled worker exceptions losing their type and message, including persisted records.
- [x] Add host-only fault fields and populate exception paths, preparation faults, and gate faults.
- [x] Document pytest cache suppression next to `GatePolicy`.
- [x] Run focused tests and package checks.

### Task 2: Preserve a single prompt prefix (#14)

**Files:** `adapters/ds4.py`, `tests/test_ds4_adapter.py`.

**Interfaces:** Keep `Ds4Agents` compatible while sharing one fixed tool schema and instructions; phase-specific behavior belongs in user prompts and `_ToolContext` permissions.

- [x] Reproduce rebuilding across context/prose/compiled requests with FakeNative.
- [x] Share the stable agent configuration and enforce phase capabilities in tools.
- [x] Assert prefix reuse and checkpoint survival across both phase changes; assert forbidden tools refuse writes/gates.
- [x] Run focused tests.

### Task 3: Thinking until first write

**Files:** `adapters/think_budget.py`, `adapters/ds4.py`, adapter/hook tests.

**Interfaces:** Adapter-owned per-attempt policy closes thinking immediately after a successful write, without `Session.set_think`; boundary restore resets policy for repair retries.

- [x] Test thinking before write, refusal unchanged, suppression after successful write, and retry reset.
- [x] Implement a logits hook for immediate `</think>` while leaving the engine's system mode fixed.
- [x] Preserve/reset policy with boundary capture/restore and expose configuration in README.
- [x] Run focused tests.

### Task 4: Retry model response failures (#17)

**Files:** `contracts.py`, `adapters/ds4.py`, `runner.py`, adapter/runner tests.

**Interfaces:** A runtime-independent model failure exception carries a retryable reason. Adapter maps only DS4 `ResponseTerminalError` reasons `max_tokens`/`parser_error`, meters failed calls, and leaves original infrastructure failures intact.

- [x] Test both reasons in both arms, bounded feedback, checkpoint/workspace rollback, retry exhaustion, budget exhaustion, and restore failure diagnostics.
- [x] Classify terminal model failures and restore the pre-attempt transaction before retrying.
- [x] Retain existing retry limits and no-budget-refund behavior.
- [x] Run the full DS4-enabled suite, CPU suite, Ruff, ty, and diff checks.
- [x] Obtain an independent review and resolve blockers.

## Execution Notes

- Initial baseline: 120 DS4-enabled tests pass at `1c6f1ab`.
- User confirmed thinking should reset on each repair retry.
- Ruling: suppress thinking through logits rather than changing `Session.set_think`, because the pinned binder includes the engine think mode in its system signature.

- Initial context retries restart an empty session and a fresh binder; failed tokens/calls remain charged.
- Compiled host slot writes notify the adapter through `WorkerPort.workspace_written`.
- Review found and resolved budget-overrun masking of response failures, missing compiled-write notifications, and missing structured shared-context faults.
- FakeNative generation regression confirms immediate thinking close after writes, thinking reset on restore, and prefix reuse. Tool-call regression confirms shared schema cannot bypass read-only permissions.
- Verification: full DS4-enabled suite 155 passed; CPU suite 126 passed, 29 skipped; Ruff check/format, ty, and diff checks passed.
- `devenv` is unavailable; checks used offline uv and the pinned ds4-py checkout's existing virtual environment.
- The gitignored root baseline driver remains untouched. Its isolated copy uses the full boundary argument and the default-off thinking policy, with its own label and artifact directory.
- [x] Native E3 pilot: `.ds4/overnight-domains/item0/records/live-readiness-pilot-20261108-220615`.
- Native E3 result: passed in 263 seconds, one prose attempt, 4,331 generated tokens; shared checkpoint 7,653 tokens fully reused by the first prose request (extend, 290 new prefill tokens). No retry was needed, so live retry recovery remains unexercised. E3 has no protected hidden grade (`not_applicable`).
