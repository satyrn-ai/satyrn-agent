## What is measured

**Interim item 0 note, 2026-11-07: existing-fake harness rehearsal only.**
The 19 local tests pass inside devenv. They exercise actual filesystem writes,
Git-tree restoration, protected pytest subprocesses, and ds4-py's real Python
session, binding, decoding, and `DS4Model` agent loop. Token choices and model
outputs are synthetic. No real model or native Metal library was loaded.

## What is conjecture

The rehearsal does not establish that Qwen 27B can solve the task, restore its
native KV state without re-prefill, use FIM, or choose correct typed answers.
It also does not establish paired same-RNG draws or any success rate.

## Implementation and provenance

Paul asked to reuse the existing fake, without inventing another engine.
The test imports `FakeNative` from the adjacent checkout's
`src/ds4py/_native/fake.py`; its `open_engine` returns that module's existing
`FakeEngine`. No replacement engine class was added. The fake originated in
Roché's work and was subsequently updated by Koudai, as established in the
preceding history inspection.

- ds4-py revision: `5c98c6ac86cafef56780c3bcbb87c3ecaef52aef`; checkout clean.
- satyrn-agent branch: `research/overnight-domains`.
- Rehearsal settings: fake Qwen family, context 16384, request cap 8192,
  thinking disabled, greedy sampling with seed 7. These are synthetic-test
  settings, not replacements for the approved live sampling policy.
- Implementation: `.ds4/overnight-domains/item0/probe/`.
- Tests and scripted outputs: `.ds4/overnight-domains/item0/tests/`.
- Local test report: `.ds4/overnight-domains/item0/records/rehearsal.xml`.

The probe directory and report remain ignored, following the approved plan.
They are local artifacts, not included in a clone of this branch. Synthetic
expense implementations exist only in the integration test; they must never
be supplied to the live worker or used to repair its output.

## Observed rehearsal evidence

1. The unfinished scaffold produces a real pytest behavior failure, including
   `NotImplementedError`, before any scripted implementation is provided.
2. The real agent loop decodes scripted Qwen tool calls and executes the four
   registered tools. The operation sequence is read, injected write, host
   pytest, replayed write, second write, edit, worker-requested pytest.
3. Before generating the first write round, the harness saves a Git tree,
   hashes, keyed host history, segment provenance, host transcript length,
   and `session.checkpoint` token count.
4. Exactly one host corruption produces a real failing pytest result containing
   `ITEM0_INJECTED_WRITE`. This is a harness fault, not a model mistake.
5. After the failed round closes, Git restores the exact file-set/content
   snapshot. `session.truncate` and `MessageBinder.restore` restore the host
   boundary and discard the abandoned tool result. Aggregate time and call
   budgets survive rollback; branch-local repeated-write state is restored.
6. Retry predicts `restore` and emits an actual engine `Synced` event selecting
   the saved key, reusing exactly the checkpoint token count, and prefilling
   only `event.pos - checkpoint_tokens`. A spy delegates to the existing
   `FakeSession.load_snapshot` and confirms one load at that token count.
   Fake-native call records contain no rewind. The resumed protected build
   passes, with unchanged protected files and no failed-branch result in the
   resumed host conversation.
7. A separate raw-session test reads synthetic A/B logits and terminates via
   `CaptureComplete`. It observes one score pair, unchanged transcript tokens,
   zero emitted `Token` events, and zero fake-native samples.

Negative tests reject unsafe paths, symlinks, protected writes, replacement
through the new-file tool, ambiguous edits, repeated writes, exhausted call
budgets, and deletion of unowned new files during restoration. Evidence tests
reject rebuilds, wrong keys, incomplete reuse, excess prefill, and tied choices.

Harness debugging found an invalid raw segment kind, failure to unwrap
`SessionEvent.payload["event"]`, and an incorrect expected operation count.
These were corrected before the final test pass; no real-model result was
produced or replaced by those debugging runs. Initial missing-module failures
were also observed before implementing the corresponding probe modules.

## Real-model presence checks

| Check | Established for 27B? | Status |
| --- | --- | --- |
| Tool loop | No | Unexercised; scripted harness path passes only |
| Restore without re-prefill | No | Native capability unverified; fake transaction passes |
| FIM | No | Unexercised; FIM plumbing and tokenizer checks still pending |
| Logits on short questions | No | Unexercised; synthetic capture plumbing passes only |

These are absences of live evidence, not observed 27B failures. No model
pathologies can be inferred from synthetic outputs.

## Reproduce the local rehearsal

From the satyrn-agent root, using the existing devenv installation:

```bash
devenv shell -- env -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 \
  uv run --project /Users/pauleveritt/projects/satyrn/ds4-py \
  --locked --extra agent --group dev \
  pytest .ds4/overnight-domains/item0/tests \
  --basetemp=.ds4/overnight-domains/item0/test-tmp \
  --junitxml=.ds4/overnight-domains/item0/records/rehearsal.xml \
  -q -p no:cacheprovider
```

Observed final result: **19 passed in 4.37s**. A targeted Ruff check for import,
syntax, and undefined-name rules also passed. No dependencies were installed,
remote model API used, or commits/pushes made.

## Consequences for item 3 and remaining work

- Keep Git, native checkpoint, keyed host messages, binder provenance, and
  branch-local harness state in one transaction. Restoring files alone is not
  a worker rollback. Budgets must not reset with the branch.
- Collect the nested engine event, not the session-event envelope, for reuse
  accounting. Compare checkpoint length to native reuse, not host length;
  the host can contain a not-yet-prefilled tool-result suffix.
- Fake success does not unblock paired native retries. Python RNG restoration
  remains unestablished by KV checkpointing.
- Before live execution, complete general boundary selection/replacement,
  watchdog/cancellation validation, persistent telemetry, the live entry
  points, and FIM/logits prompt freezing against the real tokenizer.
  FIM versus ordinary prefill and logits-based decisions remain deferred.

## What would falsify this

The harness claims would be falsified by reproducing a failed local assertion,
missing checkpoint load, prefix replay despite the reuse evidence, protected
file mutation, leaked abandoned tool result, or sampling before logits capture.
Real-model transfer is only a hypothesis: a live failure, full-prefix rebuild,
or unsupported tokenizer/termination path would refute that transfer even if
these synthetic tests continue to pass.

## Risks

- FakeNative's deterministic token/state model cannot reproduce Qwen compute,
  memory use, timing, stochastic behavior, or native cancellation semantics.
- The rehearsal captures one boundary after a read, not arbitrary write-first
  or parallel-tool transactions. Private ds4-py integration seams may change.
- Restricted file tools are not an OS sandbox for generated Python executed
  by pytest. Live work must remain disposable and trusted; there is no claim
  of adversarial isolation. All four live presence checks remain outstanding.