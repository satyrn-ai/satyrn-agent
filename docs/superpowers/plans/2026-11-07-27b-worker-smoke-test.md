# Qwen 27B Worker Smoke-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce evidence-backed yes/no answers for four local 27B presence checks, not a reusable worker subsystem.

**Architecture:** Keep throwaway Python probes and raw records under the already ignored `.ds4/overnight-domains/item0/` directory. Run the existing Pydantic AI loop with `DS4Model` and four restricted tools; use separate raw sessions for FIM and logits. Only the spec, plan, and final research note are retained project artifacts.

**Tech Stack:** Python 3.14+, ds4-py, Pydantic AI, pytest, Git, qwen35/Metal, serial decode.

**Spec:** [Approved smoke-test design](../specs/2026-11-07-27b-worker-smoke-test-design.md).

## Execution checkpoint: existing-fake rehearsal and boundary hardening, 2026-11-07

Paul authorized implementation using the existing ds4-py fake, not a new engine
double. The local rehearsal imports `FakeNative`, which opens ds4-py's existing
`FakeEngine`. No upstream source or dependencies were changed. All fake results
below establish harness behavior only; they are not evidence for the 27B.

- The initial rehearsal recorded **19 passing local tests**. A later,
  separately recorded run passed **four focused fake-worker tests** for
  boundary hardening. No later full-suite run occurred; do not combine these
  observations into a new suite total.
- Boundary hardening replaces the saved boundary under the same checkpoint key
  at eligible completed worker-rounds. The probe requires an extending plan
  with reused, fitting, nonempty native state, and captures matching Git/files,
  keyed messages, binder provenance, host transcript length, and write state.
- Fake scenarios cover replacement after multiple reads, preservation of an
  earlier successful write when a later write is injected, exact file/host
  rollback, and actual `Synced` checkpoint reuse. A write-first round alone
  cannot arm injection; if no later eligible write occurs, restore remains
  unexercised rather than inferred.
- Failed-branch and cancellation hardening remains stopped at Paul's direction;
  it was not implemented or validated. In `DS4StreamedResponse`,
  `_get_event_iterator()` marks natural facade exhaustion reconciled, so
  `_close_round_locked()` returns without reconciliation on normal completion.
  Early/interrupted cleanup can proceed through `Session.reconcile_round()` to
  native `rewind()`. Qwen35 support is unverified, not demonstrated broken; no
  live failure has been reproduced. See [ds4-py #20](https://github.com/rochecompaan/ds4-py/issues/20);
  no maintainer response or resolution is claimed.
- No GPU use without Paul's explicit approval. FIM/tokenizer checks, live entry
  points, complete live telemetry, and all four 27B presence checks remain
  pending. The original task checkboxes below remain open where evidence is
  incomplete.

See the [interim research note](../research/2026-11-07-27b-worker-smoke-test.md)
for the separate evidence provenance and remaining work. The fake rehearsal
does not complete the live tasks below.

## Global Constraints

- Work in the repository's `devenv shell`.
- Do not use the GPU without Paul's explicit approval.
- Use `/Users/pauleveritt/models/Qwen3.8-27B-Q4_K_M.gguf` through `/Users/pauleveritt/projects/satyrn/ds4-py` and the patched qwen35 engine.
- Use serial decoding. Do not depend on satyrn-agent PR #12, DFlash, or its think-budget hook. Do not use `rewind`.
- Do not source ds4-py's `.envrc.local`, use OpenRouter, or make network requests from the worker.
- Commit neither raw traces, stdout, nor patches. Commit and push nothing unless Paul asks.
- Shared worker/restore exercise: at most 20 minutes and 32 tool calls.
- FIM completion: at most 5 minutes. Each independent logits question: at most 5 minutes.
- Stop immediately on unsafe tool arguments or a repeated identical write within one uninterrupted branch; deliberate post-restore replay is exempt.
- Never tune prompts, tests, or settings against observed answers. Preserve the first frozen result when labeling debugging reruns.
- No production package, upstream edits, dependency changes, or benchmark expansion.

## Grounded integration points

Read these implementations before executing their tasks; paths are in the adjacent ds4-py checkout:

| Source | Relevant contract |
| --- | --- |
| `src/ds4py/agent.py:42-101` | Default composition includes unrestricted shell and user skills; do not use it unchanged. |
| `src/ds4py/model.py:121-140` | `DS4Model(session, sampling=..., max_tokens=...)` is the existing harness adapter. |
| `src/ds4py/model.py:194-220` | `_open_stream` prepares binding before starting the facade round; checkpoint interception must occur while idle. |
| `src/ds4py/binding.py:390-410` | `MessageBinder.restore(messages, segments)` binds preserved message keys and segment provenance. |
| `src/ds4py/engine/session.py:388-399` | `truncate()` changes the host transcript without invoking native rewind. |
| `src/ds4py/engine/session.py:608-617` | `checkpoint(key)` records native state, not an arbitrary unsynchronized host suffix. |
| `src/ds4py/engine/worker.py:311-351` | Sync loads the selected snapshot and emits `Synced(pos, plan, prefilled)`. |
| `src/ds4py/engine/plan.py:10-41` | `Plan` exposes `kind`, `checkpoint`, `reused`, `to_prefill`, and `fits`. |
| `src/ds4py/engine/worker.py:405-436` | Checkpoints require valid nonempty state and have a default 1 GiB budget. |
| `src/ds4py/engine/decode.py:149-165,331-345` | Logits hooks precede sampling; normal `PlainStep` samples immediately afterward. |
| `src/ds4py/engine/session.py:56-107,128-129` | Open with `think`, `ctx`, `seed`; tokenize special-token prompts with `rendered=True`. |

Checkpoint snapshots do not visibly save the facade's Python RNG. Record this
as an item 3 design concern, not proof of same-RNG paired draws. Item 0 tests KV
restore and continuation; it must not claim the broader paired-draw capability.

## File ownership

All paths below are repository-relative unless absolute:

- `.ds4/overnight-domains/item0/probe/common.py`: settings, limits, local evidence serialization.
- `.ds4/overnight-domains/item0/probe/workspace.py`: scaffold, protected tests, bounded tools, Git snapshots.
- `.ds4/overnight-domains/item0/probe/worker.py`: `DS4Model` integration, checkpoint transaction, worker entry point.
- `.ds4/overnight-domains/item0/probe/raw.py`: independent FIM and logits entry points.
- `.ds4/overnight-domains/item0/tests/conftest.py`: local probe import path for pytest.
- `.ds4/overnight-domains/item0/tests/test_workspace.py`: real filesystem/Git/tool tests.
- `.ds4/overnight-domains/item0/tests/test_evidence.py`: verdict and capture tests.
- `.ds4/overnight-domains/item0/workspace/`: disposable nested Git repository used by the worker.
- `.ds4/overnight-domains/item0/records/`: frozen settings, prompts, hashes, raw events, and machine-readable results.
- `docs/superpowers/research/2026-11-07-27b-worker-smoke-test.md`: retained research findings.

Create an empty `probe/__init__.py`. Keep scaffold test source inside
`workspace.py` as fixed strings so the host can create protected files without
shipping a reference implementation. Do not add root project configuration.

## Command environment

Enter `devenv shell` from the repository root. If this agent's inherited PATH
does not contain `devenv`, its verified installation is
`~/.nix-profile/bin/devenv`. Do not resolve or override `HOME`.

Commands below assume that shell and the repository root. Invoke Python with:

```bash
env -u UV_PROJECT_ENVIRONMENT uv run \
  --project /Users/pauleveritt/projects/satyrn/ds4-py \
  --locked --extra agent --group dev python --version
```

Run the probe module from its ignored parent directory using a subshell;
this changes neither the outer working directory nor any direnv configuration.

## Task 1: Protected workspace and real tool gates

**Files:** Create `probe/common.py`, `probe/workspace.py`, `probe/__init__.py`, `tests/conftest.py`, and `tests/test_workspace.py` under the ignored item directory.

**Interfaces:**
- `create_workspace(root: Path) -> None` creates the frozen scaffold and tests.
- `Workspace(root: Path)` exposes `read_file(path: str) -> str`, `write_file(path: str, content: str) -> str`, `edit_file(path: str, old: str, new: str) -> str`, and `pytest() -> str`.
- `snapshot_files(root: Path) -> dict[str, str]` returns relative file paths and SHA-256 digests, excluding `.git` and execution caches.
- `git_snapshot(root: Path) -> str` and `git_restore(root: Path, tree: str) -> None` use Git trees, not commits in the parent repository.

- [ ] Confirm branch and ignored artifact path before creating anything:

```bash
git status --short --branch
git check-ignore .ds4/overnight-domains/item0/records/result.json
```

- [ ] Add the local test import path in `tests/conftest.py`, then write failing tests for the four tools, exact-one-match editing, protected-file denial, traversal and symlink denial, and restoration of both modified and newly created files. Include this boundary case with real files:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

```python
def test_restore_removes_only_new_probe_files(tmp_path):
    create_workspace(tmp_path)
    baseline = snapshot_files(tmp_path)
    tree = git_snapshot(tmp_path)
    (tmp_path / "expenses" / "new.py").write_text("x = 1\n")
    (tmp_path / "expenses" / "report.py").write_text("broken\n")
    git_restore(tmp_path, tree)
    assert snapshot_files(tmp_path) == baseline
```

- [ ] Run the local tests and confirm missing probe functions fail before implementing them:

```bash
env -u UV_PROJECT_ENVIRONMENT uv run \
  --project /Users/pauleveritt/projects/satyrn/ds4-py \
  --locked --extra agent --group dev pytest \
  .ds4/overnight-domains/item0/tests/test_workspace.py -v
```

- [ ] Implement allowlisted source paths: `expenses/parser.py`, `expenses/totals.py`, and `expenses/report.py`. Reads may include protected tests. Deny writes elsewhere, existing-file replacement through the new-file tool, symlinks, and ambiguous edits. Enforce limits before dispatch, not after side effects.

```python
candidate = (self.root / path).resolve()
if not candidate.is_relative_to(self.root.resolve()):
    raise PermissionError(path)
if path not in {"expenses/parser.py", "expenses/totals.py", "expenses/report.py"}:
    raise PermissionError(path)
```

Reject symlink components separately: resolving a symlink inside the root is
still not sufficient permission. Use a fixed `subprocess.run` argv with
`sys.executable`, `-m`, `pytest`, protected test paths, `cwd=root`, and a timeout;
never accept a command string. Disable bytecode and pytest cache creation.

- [ ] Create `expenses/__init__.py`, an existing `expenses/report.py` stub, and `tests/test_expenses.py`. Freeze these public interfaces in the worker prompt: `parse_records(text: str) -> list[tuple[str, int]]`, `total_by_category(records: list[tuple[str, int]]) -> dict[str, int]`, and `render_report(text: str) -> str`.

Protected behavior examples include:

```python
def test_report_aggregates_exact_cents_and_sorts():
    from expenses.report import render_report
    assert render_report("food,0.10\nbooks,2\nfood,0.20") == "books: 2.00\nfood: 0.30"
```

Also test empty and whitespace-only input, repeated categories, all malformed
amount forms from the spec, missing/extra commas, and empty categories. Keep
expected values fixed; do not derive them using a hidden reference parser.
Include direct parser and totals tests with imports inside the test functions,
so an injected error in either new module is actually exercised even before
the worker wires the report formatter. The initial report stub raises
`NotImplementedError`, giving a genuine behavior failure independently of
missing new modules.

- [ ] Use a private Git index (`GIT_INDEX_FILE` pointing inside this disposable repository) with `git add`/`git write-tree` to snapshot source files without commits. Restore tracked content from the tree and unlink only recorded post-snapshot probe-created files. Never use `git clean` or broad deletion. Hash protected tests before and after each tool operation.
- [ ] Rerun local tests and require pass. Run the scaffold's protected tests separately and require a genuine behavior failure, not only an import/configuration error.

## Task 2: Checkpoint evidence and zero-sampling logits capture

**Files:** Create `probe/raw.py`, `tests/test_evidence.py`; extend `probe/common.py`.

**Interfaces:**
- `restore_verified(event: Synced, checkpoint_key: str, checkpoint_tokens: int) -> bool` judges reuse from actual sync events.
- `CaptureComplete(Exception)` is an intentional probe-local termination signal.
- `capture_choices(view: LogitsView, token_ids: tuple[int, int], scores: list[tuple[float, float]]) -> None` captures scores then raises `CaptureComplete` before sampling.

- [ ] Write tests that reject `rebuild`, wrong checkpoint keys, too-short reuse, missing events, and ties. Test logits capture using a minimal view fake; verify a sampling spy is never invoked after `CaptureComplete`. This tests harness logic only, not engine capability.
- [ ] Run `tests/test_evidence.py` using the same uv prefix as Task 1; confirm missing functions fail.
- [ ] Implement the evidence rules and capture hook:

```python
def restore_verified(event, checkpoint_key, checkpoint_tokens):
    return (
        event.plan.kind == "restore"
        and event.plan.checkpoint == checkpoint_key
        and event.plan.reused == checkpoint_tokens
        and event.prefilled == event.pos - checkpoint_tokens
    )

def capture_choices(view, token_ids, scores):
    logits = view.logits()
    scores.append(tuple(float(logits[token]) for token in token_ids))
    raise CaptureComplete
```

The raw round catches only `CaptureComplete` and closes/drains its iterator.
The hook performs no session call, cancellation, I/O, or masking. Assert exactly
one score pair, unchanged transcript token count, and zero emitted `Token`
events. A real-engine run must verify this sentinel path; a unit fake cannot
establish that native sampling was avoided.

- [ ] Rerun both local test modules. Do not load the model for these tests.

## Task 3: Existing worker loop with transactional restore

**Files:** Create `probe/worker.py`; extend local tests for transaction evidence and fault injection.

**Interfaces:**
- `run_worker(run_dir: Path) -> dict[str, object]` runs one frozen build and returns separate tool-loop and restore verdict records.
- `Boundary` stores Git tree, file hashes, deep-copied keyed host messages, binder segment provenance, native checkpoint key/count, and host transcript length.
- A probe-local `DS4Model` subclass intercepts `_open_stream` while idle; it delegates actual generation to `super()._open_stream` unchanged.

- [ ] Write failing tests for corruption once only, rollback preserving protected tests, abandoning failed-branch tool results, and repeated-write limits exempting the deliberate restore replay.
- [ ] Register only the four `Workspace` methods with `pydantic_ai.Agent(model, tools=[...], instructions=...)`. Do not call `build_agent_components` or install shell, skills, repo scanning, or system-note capabilities. Freeze tool definitions and instructions for the entire run.

```python
sampling = SamplingPolicy(temperature=0.6, top_p=0.95, min_p=0.05, top_k=20, seed=7)
model = ProbeModel(session, sampling=sampling, max_tokens=8192)
agent = Agent(model, tools=[workspace.read_file, workspace.write_file,
                            workspace.edit_file, workspace.pytest],
              instructions=instructions)
```

- [ ] At each eligible pre-generation boundary, preserve keyed messages and provenance and replace the previous native checkpoint using one fixed key. Do not checkpoint an empty/invalid initial native state. Save the checkpoint's returned token count separately from host transcript length; a host-only suffix may not be native yet.
- [ ] Corrupt the first eligible `.py` write with `raise RuntimeError("ITEM0_INJECTED_WRITE")`. Immediately run real protected tests through the same pytest implementation; require the marker in the failure. Preserve original bytes locally, but never use them as a host-written replacement solution.
- [ ] Finish/drain the current agent round before restoring. Resume a fresh agent run from the saved keyed host history, not the failed branch. Use `session.truncate(saved_host_length)` and `MessageBinder.restore(saved_messages, saved_segments)` to restore matching host state while retaining native checkpoints. Let the next normal sync choose the checkpoint; do not call `reconcile_round`, `rewind`, `session.new`, or a native reset to implement rollback.
- [ ] Verify `session.plan()` predicts checkpoint reuse, then require the actual `Synced` event to satisfy Task 2's evidence predicate. Any newly required assistant prefix or feedback must be a suffix beyond the native checkpoint. If preserved binder provenance cannot be restored exactly, stop and report the boundary failure rather than reconstructing the conversation through full prefill.
- [ ] Record tool-call names/outcomes, protected hashes, thinking token observations, cancellation, file equality, `Checkpointed`, `Prefill`, and `Synced` events. Use `session.on_event` only to collect data; its listeners must not call blocking session APIs.
- [ ] Set worker context to 16384, generation cap to 8192 per model request, and the fixed sampling above. Enforce the approved 20-minute/32-call aggregate limit across failed and restored branches. A watchdog may set cancellation outside hooks; await draining and close the engine on timeout. A cancellation path that internally requires unsupported rewind is a reported failure, not permission to change ds4-py.
- [ ] Rerun local tests before any model run. Record API/budget blockers rather than increasing checkpoint budgets or modifying upstream code silently.

## Task 4: Freeze independent FIM and logits probes

**Files:** Extend `probe/raw.py` and local capture tests; create frozen inputs under `records/` only after local tests pass.

**Interfaces:** `run_fim(run_dir: Path) -> dict[str, object]` and `run_logits(run_dir: Path) -> dict[str, object]` produce independent verdict records.

- [ ] Fix the FIM boundaries and tests before execution:

```python
prefix = "def sum_positive(values: list[int]) -> int:\n"
suffix = "\n\ndef marker() -> str:\n    return 'unchanged'\n"
prompt = "<|fim_prefix|>" + prefix + "<|fim_suffix|>" + suffix + "<|fim_middle|>"
cases = [([], 0), ([1, -2, 3, 0], 4), ([-3, 0], 0)]
```

Tokenize each special token with `rendered=True`; require one intended token
and matching token text. Tokenize the raw prompt with `rendered=True` too.
Use the existing raw `append_tokens`/`run_round` path, at most 512 generated
tokens, and stop on recognized FIM-end/EOS tokens. Assemble prefix + generated
middle + suffix without code-fence stripping or repair. Check the AST, both
function names/boundaries, and the fixed behavioral cases in a separate Python
subprocess with a short timeout.

- [ ] Freeze these three logits prompts, each ending at the shown `Answer:` position followed by the exact label context selected before scoring:

```text
The requirement explicitly says to use a function-based view.
Which implementation satisfies it?
A: Function view
B: Class-based view
Answer:

The test file is protected and must not be modified.
Which action is permitted?
A: Rewrite it
B: Leave it unchanged
Answer:

Expense totals must avoid binary floating-point arithmetic.
Which representation meets this requirement?
A: Integer cents
B: Binary float
Answer:
```

Use a raw chat-shaped prompt with a closed thinking block before the question's
answer position if required by Qwen's template; obtain the actual delimiters
from its existing prompt renderer, not from guessed token names. Save the final
rendered bytes and token IDs. Verify concatenating each label produces exactly
one additional token without retokenizing the prompt prefix. Answers are A,
B, A; store them separately from model input. Stop on tokenization mismatch.

- [ ] Use a fresh engine/session per independent probe if required: the current `Engine.session()` allows only one session, even after its session is closed. Separate processes are an acceptable isolation strategy; record each model-load cost separately. Never use `session.new()` as an unexamined reset fallback because its native reset can call rewind.
- [ ] Use ctx 4096 and seed 7 for raw probes; FIM uses the worker sampling policy. Logits are read before any sampling and therefore do not depend on that policy. Enforce 5 minutes per FIM run or logits question.
- [ ] Freeze settings, exact prompts, scaffold hashes, test hashes, and answer keys into a manifest. Hash the manifest. Do not revise frozen inputs after inspecting model answers.

## Task 5: Run the frozen presence checks once

**Files:** Local `records/` outputs only. No retained source changes.

- [ ] Read the engine's relevant pathology entries before interpretation, including the survey correction about entry 103. Record model/library/checkouts and verify the model path exists without opening it as text.
- [ ] Confirm no competing model process from this session remains active. Run all local tests with the uv command from Task 1 targeting the entire ignored `tests/` directory; require pass.
- [ ] Run the worker entry point from the ignored parent directory:

```bash
(cd .ds4/overnight-domains/item0 && \
  env -u UV_PROJECT_ENVIRONMENT uv run \
    --project /Users/pauleveritt/projects/satyrn/ds4-py \
    --locked --extra agent --group dev python -m probe.worker)
```

The entry point has no prompt-tuning options and writes results to its local
`records/` directory. Enforce the aggregate limits inside the harness, not only
with the terminal timeout. Keep the model run synchronous, not backgrounded.

- [ ] Run raw probes serially with the same subshell/uv prefix and `python -m probe.raw fim`, then `python -m probe.raw logits`. The logits entry point executes each frozen question in its own session/process, once.
- [ ] Read complete result records and relevant event windows. Check actual test exit codes, injection marker, file equality, selected checkpoint/reuse/prefill counts, FIM assembly/tests, and logits scores/margins. Missing evidence is a non-pass with its reason.
- [ ] Preserve every original outcome. If a probe implementation error requires a debugging rerun, label it separately and describe what changed; never replace the frozen original silently.

## Task 6: Research note and review handoff

**Files:** Create `docs/superpowers/research/2026-11-07-27b-worker-smoke-test.md`.

- [ ] Write the note beginning with `What is measured` and `What is conjecture`. Include four yes/no rows, evidence and commands, runtime identities/settings, limits, injected versus natural failures, and explicit unexercised/unverified statuses behind non-passes. Never call one run a rate or a null.
- [ ] Explain the implications for item 3: worker viability, checkpoint retry restrictions, FIM versus ordinary prefill, and logits readiness. Explicitly flag that facade RNG restoration is not established by KV checkpoint presence.
- [ ] End with `What would falsify this` and `Risks`. Include remaining instrumentation uncertainty and the limits of these trivial logits/FIM cases.
- [ ] Verify retained Markdown whitespace and local links, then inspect `git status --short` and `git diff`. Ensure raw artifacts remain ignored. No tests or builds are required solely for the research Markdown.
- [ ] Report actual outcomes and any unfinished check. Do not delete the ignored evidence directory unless Paul asks. Do not commit or push.

## Plan self-review

- Spec sections 1–3 map to global constraints, grounded interfaces, and Tasks 1–3.
- Tool-loop and restore acceptance map to Tasks 1–3 and actual event inspection in Task 5.
- Independent FIM/logits checks map to Tasks 2, 4, and 5.
- Limits, safety, and pathology attribution map to Tasks 1, 3–5.
- Research structure, falsification, risks, and item 3 consequences map to Task 6.
- Private integration seams and zero-sampling termination remain explicit probe risks, not predeclared successful capabilities. Stop rather than expand scope if these seams cannot satisfy the approved design.