# Qwen 27B worker smoke-test design

| | |
| --- | --- |
| Date | 2026-11-07 |
| Status | Approved by Paul on 2026-11-07; implementation plan pending |
| Track | Overnight domains, item 0 |
| Branch | `research/overnight-domains` |
| Related | [Roadmap](../research/2026-11-07-overnight-domains-roadmap.md), [survey](../research/2026-11-07-overnight-domains-survey.md) |

## 1. Goal and evidence boundary

Establish whether the local Qwen 27B can act as a worker through ds4-py,
and whether three engine capabilities support the proposed item 3 design.
Run four isolated presence checks, sharing one build between the tool-loop
and restore checks. A successful observed execution establishes presence,
not reliability, a success rate, or comparative performance.

The non-live `ds4py check` reported a Metal library, known headers, matching
layouts, and all 52 required bindings. It did not verify live restore or any
of these four checks. Record fresh runtime identities when execution begins;
do not treat the earlier library's temporary install path as a stable pin.

Paul approved isolated checks, one deliberately corrupted write, the worker
task below, and the acceptance and stopping policy, then reviewed and approved
this written spec. Prepare the implementation plan next; no probe has run.

## 2. Scope and environment

- Work in the repository's `devenv shell`.
- Use `/Users/pauleveritt/models/Qwen3.8-27B-Q4_K_M.gguf` through
  `/Users/pauleveritt/projects/satyrn/ds4-py` and the patched qwen35 engine.
- Use serial decoding. Do not depend on satyrn-agent PR #12, DFlash, or its
  think-budget hook. Do not use `rewind`.
- Do not source ds4-py's `.envrc.local`, use OpenRouter, or make network
  requests from the worker. Do not install Nix or change dependencies as part
  of these probes without a separate need and authorization.
- Record model identity, engine and ds4-py revisions, Python version,
  context size, sampling settings, seed, and serial mode before running.
- Keep the disposable workspace and raw records under an ignored directory
  inside this repository, outside `.junie`. Verify that it is ignored first.
- Commit neither raw traces, stdout, nor patches. Commit and push nothing
  unless Paul asks.

No packet compiler, symbol index, domain pack, style checker, benchmark,
trie-mask timing, or item 3 implementation belongs in this spike. The brief's
four checks take precedence over the roadmap's additional mask-timing bullet.

## 3. Probe architecture and data flow

Use a thin throwaway probe harness rather than a new agent framework.
The worker exercise must use ds4-py's existing agent/tool loop. Separate
sessions isolate FIM and each logits question from worker conversation state.
Load the model once if supported without compromising that isolation.

The host owns the initial scaffold, protected tests, tool policy, checkpoints,
failure injection, execution limits, and evidence collection. The model owns
the requested implementation. Never substitute host-written solution code
when the worker fails.

Tools expose bounded reads, new-file writes, exact edits, and a fixed pytest
command. Paths must resolve inside the disposable workspace; reject traversal,
symlink escapes, protected-test writes, and arbitrary shell commands. Tool
results return actual operation or test outcomes, not simulated success.

The harness records tool names and outcomes, generated-token counts, available
thinking counters, elapsed times, checkpoint boundaries, and engine evaluation
events. Raw records remain local. The research note contains concise evidence
and reproducible commands, not transcript dumps.

## 4. Tool-loop check

Create a small expense-report package with an existing report formatter that
needs editing. Ask the worker to add a parser and aggregation helper in separate
modules, then wire them into that formatter.

The task contract is deliberately small:

- Input consists of `category,amount` lines. Trim surrounding whitespace,
  ignore blank lines, and accept nonnegative decimal amounts with at most
  two fractional digits. Require exactly one comma and a nonempty category;
  quoting and embedded commas are unsupported. After trimming, amounts match
  `[0-9]+(?:\.[0-9]{1,2})?`; signs, exponent notation, and special values are
  invalid.
- Parse amounts into integer cents, rejecting malformed records and amounts
  with `ValueError` rather than silently dropping them.
- Aggregate cents by category and format sorted category totals with exactly
  two fractional digits as `category: amount`, one per line without a trailing
  newline. Category matching and sorting are case-sensitive. Empty input
  produces an empty report.

Protected tests cover ordinary records, repeated categories, decimal arithmetic,
ordering, whitespace and empty input, and malformed or negative amounts.
Freeze tests before the run. The worker sees the behavioral contract and may
read tests, but receives no reference implementation. Confirm the scaffold
does not already satisfy the requested behavior.

Pass only when the observed ds4-py loop successfully exercises read, write,
edit, and pytest tools, the completed build passes the protected tests, and
protected-file hashes are unchanged. A passing build that omits a required
tool is not a pass for this check. Report observed partial capabilities too.

## 5. Restore check

Use the same worker build and exactly one host-injected corruption. Report
this fault separately from any natural model errors.

At a completed round boundary before generating a write-capable round:

1. Establish a Git snapshot of the allowed workspace, including earlier
   successful worker changes, and record file paths and hashes. The snapshot
   must account for newly created files as well as tracked files.
2. Save `session.checkpoint` and the matching host conversation, pending-tool,
   and harness state. Checkpoints must not race an active generation.
3. Execute the next round. On the first applicable model-produced Python write,
   save its unmodified content locally, then replace that write's content with
   syntactically valid code that raises an identifiable runtime error. Do not
   corrupt the protected tests.
4. Run real pytest and confirm failure attributable to the injected error.
5. Restore the exact workspace snapshot using Git and targeted removal only
   of new files created by this probe since the snapshot. Restore the model
   checkpoint and matching host state; discard abandoned tool results.
6. Confirm file-set and content equality and continue from the restored state
   with injection disabled. Fresh failure feedback, if supplied, must describe
   the injected fault truthfully and be recorded as new input.

Pass requires observed test failure, exact file restoration, successful model
state restoration, continuation, and evidence that restoration did not replay
the saved prefix. Instrument evaluation/prefill events and token ranges around
the boundary. Processing newly appended feedback is allowed; reevaluating the
saved prefix is not. Elapsed time alone is insufficient evidence.

If the existing hooks cannot expose that distinction, report the no-reprefill
requirement as unverified, not passed. A final failing build may fail the
tool-loop check while still providing valid evidence for successful restore.
No applicable write before a limit means the restore check was not exercised.

## 6. FIM check

Independently verify that the tokenizer recognizes `<|fim_prefix|>`,
`<|fim_suffix|>`, and `<|fim_middle|>` as the intended special tokens.
Use raw FIM serialization, not a chat prompt merely requesting insertion.

Provide a prefix ending with the signature of a function that sums positive
integers from a list, and a suffix containing a separate, fixed function.
Ask for the missing body only. Do not supply a solution or demonstrations.
Freeze the exact prompt, stop handling, and tests before execution.

Insert only the generated middle between the original boundaries. Pass requires
valid Python, correct behavior for empty, mixed-sign, and all-nonpositive
inputs, and unchanged prefix and suffix. Report unwanted boundary repetition,
reasoning text, or special-token leakage. One failed completion does not prove
the model lacks FIM training.

## 7. Logits check

Freeze three short binary questions and their answer keys before running:

| Question contract | A | B | Correct |
| --- | --- | --- | --- |
| Which view form satisfies an explicit function-view requirement? | Function view | Class-based view | A |
| Which action is permitted for a protected test file? | Rewrite it | Leave it unchanged | B |
| Which representation avoids binary floating-point arithmetic for expense totals? | Integer cents | Binary float | A |

Use concise wording that states each requirement explicitly. Verify that each
label is one token in its actual answer context and that the prompt ends at
the answer position, outside a thinking block. Freeze the rendered prompts
and token IDs before observing scores. Unsupported tokenization is a setup
failure, not grounds for tuning prompts against observed answers.

For each question, capture the first answer-position logits through the hook
after prompt processing, then terminate without answer sampling or reasoning
decoding. Do not call engine APIs from the hook. One answer-position evaluation
per question is the target; normal prompt prefill is still necessary.

Choose the larger of the two label logits, without biasing or masking them.
Record both logits and the winner's margin; an exact tie is not correct.
Pass this check only if all three predetermined choices are correct. These
simple cases test plumbing and presence, not routing quality or calibration.

## 8. Limits and failure handling

- Shared worker/restore exercise: at most 20 minutes and 32 tool calls.
- FIM completion: at most 5 minutes.
- Each independent logits question: at most 5 minutes.
- Stop at the first applicable limit. Stop immediately on unsafe tool
  arguments or a repeated identical write attempt to the same file within
  one uninterrupted branch. Replaying a write after the deliberate checkpoint
  restoration is expected and does not itself trigger this rule.
- Cancellation must leave the engine idle or close its session before any
  checkpoint operation. Do not infer this from a host timeout alone.
- On setup or instrumentation failures, preserve the error and do not silently
  switch engines, prompts, models, or decoding strategies.

Measure probe wall time from session preparation, including prompt processing;
record shared model-load time separately. Record time spent in pytest and
restoration separately when available. Choose and record generation/context
caps before execution to prevent context overflow; do not extend a stopped
probe to chase a pass.

A limit or unexercised path yields a non-passing presence check with its reason,
not a claim of impossible capability. Run each frozen check once; debugging
reruns require explicit labeling and must not replace the original result.

## 9. Pathology observations

Record observed probing spirals, long thinking, stale keyword arguments, and
rewrite loops. Consult ds4-engine `docs/pathologies.md`, particularly entries
102, 103, 114, 115, 121, 122, and 124, before interpreting similarities.
The survey corrects entry 103's attribution to Ornith-1.5-9B, not the 27B.
Do not present it as prior evidence about this model.

Report counts or durations supported by the local record. Distinguish an
observed pattern, a resemblance to an earlier report, and a conjectured cause.
Failure to observe a pattern in this run does not establish its absence.

## 10. Deliverable and item 3 implications

Write `docs/superpowers/research/2026-11-07-27b-worker-smoke-test.md`.
Begin with **What is measured** and **What is conjecture**; end with
**What would falsify this** and **Risks**.

Include one yes/no row per check, the evidence supporting that verdict, and
an explicit distinction between observed failure, unexercised capability, and
insufficient instrumentation. Include runtime identities, frozen settings,
commands, limits hit, fault-injection attribution, and pathology observations.
Do not call one execution a rate or a null.

State item 3 consequences conditionally:

- Tool-loop failure blocks using this worker path until diagnosed.
- Unverified restore blocks claims about paired checkpoint rollback and
  decode-only retries; Git rollback alone is insufficient.
- FIM failure favors ordinary skeleton prefill for the next design, without
  concluding that all FIM prompting is impossible.
- Logits failure defers logits-based typed decisions; success permits further
  investigation, not production routing claims.

## 11. Review and execution gates

Self-review this spec for ambiguity, contradictions, placeholders, and scope.
Ask Paul to review the written file. Only after explicit approval, create the
implementation plan and prepare the throwaway probes. Do not commit the spec
unless Paul requests it.