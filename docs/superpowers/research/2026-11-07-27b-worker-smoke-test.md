## What is measured

**Live presence checks, 2026-11-08:** one run of each check on the real 27B,
in [Real-model presence checks](#real-model-presence-checks). Each is one
observed execution: presence, not a rate. Everything else in this section
describes the earlier fake rehearsal.

**Interim item 0 note, 2026-11-07: existing-fake harness rehearsal only.**
The initial rehearsal recorded 19 passing local tests inside devenv. They
exercise actual filesystem writes, Git-tree restoration, protected pytest
subprocesses, and ds4-py's real Python session, binding, decoding, and
`DS4Model` agent loop. A later, separate focused run recorded four passing
fake-worker tests for boundary hardening; it was not a new full-suite run. Token
choices and model outputs are synthetic. No real model or native Metal library
was loaded, and no GPU was used.

## What is conjecture

The rehearsal does not establish that Qwen 27B can solve the task, restore its
native KV state without re-prefill, use FIM, or choose correct typed answers.
It also does not establish paired same-RNG draws or any success rate.
The fake evidence does not establish parallel-tool or interrupted-request
safety, including whether Qwen35 supports the facade's native rewind path.

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

The initial rehearsal evidence below is retained as a historical observation;
the later boundary-hardening run is recorded separately afterward.

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

### Later focused boundary-hardening evidence

The separate focused run reported **four passing fake-worker tests** after the
boundary changes; the full local suite was not rerun. The tests and
`.ds4/overnight-domains/item0/probe/worker.py::ProbeModel._open_stream` record
these harness-only observations:

- The saved boundary is replaced under the same checkpoint key at eligible
  completed worker-rounds. The probe requires an extending plan with reused,
  fitting, nonempty native state, and captures corresponding Git/file state,
  keyed messages, binder segment provenance, host transcript length, and
  branch-local writes before publishing the replacement.
- A two-read scenario selects the later eligible boundary. Fake snapshot
  instrumentation confirms the saved native position is restored, and the
  resumed `Synced` event satisfies the existing key/reuse/prefill predicate.
- A write-first initial round does not arm injection without an eligible
  checkpoint. If a later write makes a boundary eligible, the earlier
  successful file is included in that boundary and survives rollback of the
  injected later write.
- When no eligible later write occurs, injection and restore are left
  unexercised; the harness does not manufacture restore evidence.

These results do not cover cancellation or interrupted cleanup, parallel tools,
Python RNG restoration, Qwen compute, or real native-state behavior.

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

Run 2026-11-08 on `Qwen3.8-27B-Q4_K_M.gguf`, ds4-py
`5c98c6ac86cafef56780c3bcbb87c3ecaef52aef` (clean), the e2e `libds4.dylib`
with satyrn-agent's qwen35 patches, satyrn-agent `d157b07` plus the uncommitted
tree. Prompts, task text, tokens and answer keys were frozen in
`.ds4/overnight-domains/item0/records/frozen/` before any model answer; source
hashes at run time matched the manifest. Raw records stay in that ignored
directory.

| Check | Established for 27B? | Evidence |
| --- | --- | --- |
| Tool loop | **Yes** | Read, write, edit and pytest all succeeded through the `DS4Model` loop. Final build 20/20 on the protected tests, protected hashes unchanged. |
| Restore without re-prefill | **Yes** | Injected failure observed (`ITEM0_INJECTED_WRITE`, 20 failed). Files equal after restore in 0.05 s. The next `Synced` was `kind='restore'`, `reused=1195`, `prefilled=24`, and decoding continued for 2,279 tokens to a passing build. |
| FIM (frozen check) | **No: setup failure, not exercised** | `ds4_tokenize_rendered_chat` parses chat tokens only, so `<|fim_prefix|>` became six ordinary tokens. The check stopped before decoding, as the design requires. |
| Logits on short questions | **Yes** | 3/3 correct with margins 6.83, 8.44 and 6.77. About 0.55 s per question, no token emitted, transcript unchanged. |

**FIM diagnostic (labelled rerun, does not replace the row above).** The tokens
exist in the vocabulary (IDs 248060–248063). Built from those IDs, the prompt
gave `    return sum([x for x in values if x > 0])` in 16 tokens. It stopped on
a stop token, passed all three behaviour cases, and leaked no special tokens,
reasoning or repeated boundary. One trivial hole shows the path can work, not
that FIM is reliable.

**Worker run.** Context 16384, 8192 tokens per request, thinking HIGH, sampling
temperature 0.6, top-p 0.95, min-p 0.05, top-k 20, seed 7. 223 s wall, 4,204
generated tokens, 12 tool calls, none failed, final context 3,636 tokens.

| Observation | Detail |
| --- | --- |
| Injection | On the first write, `expenses/parser.py`. The `pytest` entry just before it in `tool-log.jsonl` is the harness's own check, not a model call. |
| Natural failure | One after the restore: the first complete build failed `pytest`. The model reasoned that category and amount need trimming separately, made one edit, and passed. |
| Multiple tool calls per response | Seen (two reads, then two writes), run sequentially. |
| Restored branch | Wrote different code from the abandoned branch, so RNG state did not carry over. |
| Thinking | About 2,650 of 4,204 tokens, the largest round about 1,380. |
| Pathologies | No probing spiral, rewrite loop, or stale keyword argument in this run. That doesn't establish absence on longer tasks. |

**Harness calls made for the live run** (none changed a verdict here):

- Live entry points were added under the ignored probe directory, and the run
  went in the background because it can outlast a foreground tool call.
- Ordinary tool failures return to the model. A path off the allowlist returns
  an error; only traversal, absolute paths, symlinks and protected writes stop
  the run. No tool call failed.
- A corruption is held back from `totals.py` while `parser.py` is absent,
  because pytest could not attribute it.
- The hard limits end the process rather than cancelling, so no cancellation
  path was exercised.
- The `think_tokens` field in `result.json` is wrong (always 0): ds4-py emits
  only `Thinking(on=False)` here. The thinking figures above count
  `TextDelta(thinking=True)` events.

**Consequences for item 3:** the worker path and checkpoint rollback without
re-prefill are viable. Still unestablished for paired draws: Python RNG
restoration and safe cancellation (`supports_paired_draws` needs both). FIM
needs prompts built from vocabulary IDs and a real test on larger holes.
Logits success permits further investigation, not routing claims.

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
- Keep same-key boundary replacement and write-first preservation in the fake
  harness contract, but do not generalize those results to parallel tools or
  interrupted branches.
- Fake success does not unblock paired native retries. Python RNG restoration
  remains unestablished by KV checkpointing.
- Failed-branch/cancellation hardening remains stopped. In the adapter,
  `DS4StreamedResponse._get_event_iterator()` marks natural facade exhaustion
  reconciled; `_close_round_locked()` then returns without reconciliation.
  Early/interrupted cleanup can instead proceed through
  `Session.reconcile_round()` to native `rewind()`. Qwen35 support for this path
  is unverified, not demonstrated broken, and no live failure has been
  reproduced. See [ds4-py #20](https://github.com/rochecompaan/ds4-py/issues/20);
  no maintainer response or resolution is claimed.
- Before relying on live runs that can be interrupted, complete the
  interruption/cancellation investigation and the parallel-tool safety
  assessment. FIM versus ordinary prefill and logits-based decisions remain
  deferred. The live presence checks ran on 2026-11-08; see above.

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
- Boundary replacement and write-first preservation are covered only by the
  later focused fake-worker tests; parallel-tool and interrupted-branch
  behavior remain unestablished. Private ds4-py integration seams may change.
- Restricted file tools are not an OS sandbox for generated Python executed
  by pytest. Live work must remain disposable and trusted; there is no claim
  of adversarial isolation.
- Each live check ran once on a small task. The logits questions and FIM hole
  are trivial, and the worker task fits in 3,636 tokens of context.