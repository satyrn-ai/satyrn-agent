# Thinking placement finding: thinking until the first write keeps the score at about a fifth less cost, and the rest of the thinking is mostly runaway (2026-11-10)

**Prior art this replicates.** Koudai Aono's ds4-engine finding
(`pauleveritt/ds4-engine`, `docs/superpowers/research/2026-10-03-qwen-thinking-finding.md`):
on Qwen3.8-27B under the engine's `qwen38-native` profile, thinking until a prompt's first
write kept the median score and saved 19–22% of wall time. The loop guard escalation below
follows his host-side loop guards (`dc6255a2f`), and the analysis of where thinking goes
follows his survey's step 1 (`2026-10-03-thinking-control-survey.md`).

**What is measured.** The prose arm of `plan-comparison` on branch `research/overnight-domains`
(adapter at `packages/plan-comparison/src/plan_comparison/adapters/ds4.py`), driving
Qwen3.8-27B (Q4_K_M) in-process through ds4-py `5c98c6a`, Apple M5 Max. Tasks H1–H3 of the
customer-tracker Django project, seeds 1–3, so 9 runs a batch; each run is its own process,
one prose attempt plus one repair retry, 40-minute wall limit, `max_tokens` 8,192 a reply,
context 65,536, sampling temperature 0.6, top-p 0.95, top-k 20, min-p 0.05, `ThinkMode.LOW`
("Reasoning effort is set to low"), 4,096-token thinking budget with a forced close. The score
is the hidden test suite run on the final workspace. The driver and its records are gitignored
under `.ds4/overnight-domains/item0/` (`probe/overnight.py`); `probe/tally.py` recomputes the
table and `probe/split.py` the thinking split from each batch's `runs.jsonl` and `events.jsonl`.

**What is conjecture.** Whether any of this holds for another model, another project or
other seeds; and whether the cost saving survives tasks where the model rewrites code after a
failed gate, which these seeds barely exercised.

## Result

Hidden tests, n = 9 runs a batch (H1–H3 × seeds 1–3):

| Batch | Thinking | Guard | Hidden full passes | Pass but the two unstated tests | Median wall | Total wall | Median tokens | Total tokens | Thinking deltas |
|---|---|---|---|---|---|---|---|---|---|
| `prose-fixes` | LOW | off | 3 | 8 | 780 s | 7,739 s | 11,376 | 122,035 | 72,792 |
| `guarded-low` | LOW | refuse | 3 | 8 | 738 s | 8,449 s | 11,292 | 121,829 | 72,713 |
| `guarded-first-write` | until first write | refuse | 3 | 8 | 630 s | 6,832 s | 10,373 | 100,234 | 45,159 |
| `prose-nothink` | none | off | 3 | 6 | 404 s | 4,926 s | 6,323 | 73,802 | 0 |
| `guarded-nothink` | none | refuse | 3 | 7 | 505 s | 5,831 s | 5,577 | 70,552 | 0 |
| `rethink-first-write` | until first write, again after a failure | refuse, escalate | 3 | 8 | 677 s | 6,847 s | 10,474 | 99,531 | 45,189 |

Record directories (under `.ds4/overnight-domains/item0/records/`):
`overnight-prose-fixes-20261109-015902`, `overnight-guarded-low-20261109-123141`,
`overnight-guarded-first-write-20261109-145248`, `overnight-prose-nothink-20261109-040814`,
`overnight-guarded-nothink-20261109-164654`, `overnight-rethink-first-write-20261110-102239`, `overnight-loop-nothink-h1-20261110-101639`; pilots on E3 seed 1:
`overnight-pilot-rethink-20261110-100905`, `overnight-pilot-escalate-nothink-20261110-101320`.

"Pass but the two unstated tests" also counts a run whose only hidden failures are
`test_schedule_missing_customer_raises_model_does_not_exist` (H2) or
`test_archive_rejects_naive_timestamp_without_mutation` (H3). The task briefs do not state
either behavior, so every thinking setting fails them on every seed; they cap the full-pass
count at 3 of 9 (the three H1 runs) and hide every difference between the thinking arms.

- **Thinking until the first write keeps the score and cuts about a fifth of the cost.**
  Against `guarded-low`, the same 3 full passes and the same 8 of 9 on the stated behavior,
  with 19% less total wall time (6,832 s against 8,449 s), 18% fewer generated tokens
  (100,234 against 121,829) and 38% fewer thinking deltas. Koudai's 19–22% replicates on a
  different harness (Pydantic AI tools over ds4-py rather than the engine's host), a different
  project, and a hidden-test grade.
- **No thinking is cheaper but may lose on the stated behavior.** 6 and 7 of 9, against 8, and
  its H1 seed 1 looped in both batches (below). But a third no-thinking H1 seed 1 run, the
  loop check, passed every hidden test: the loop is one path the model can take, not a fixed
  cost of turning thinking off. n = 9 cannot separate 7 from 8; the loss is a direction, not proof.
- **The refusal-only guard changed nothing where it mattered.** `guarded-low` matches
  `prose-fixes` run for run. In no-thinking H1 seed 1 the guard refused 43 identical rewrites of
  `app/crm/queries.py` and the model kept writing the same file until Pydantic AI's 50-request
  limit; unguarded, the same run generated exactly the same 26,510 tokens. The refusal text
  did not change a single sampled token. It did break the no-thinking H3 seed 1 read loop
  (4 refusals, then the run wrote and finished).

## Where the thinking went (the survey's step 1)

`probe/split.py`, counting thinking deltas in replies before the run's first `write_file`
call and after it:

| Batch | Before first write | After first write | Thinking replies | Replies at the 4,096 budget |
|---|---|---|---|---|
| `prose-fixes` | 45,159 | 27,633 | 123 | 11 |
| `guarded-low` | 45,159 | 27,554 | 122 | 11 |
| `guarded-first-write` | 45,159 | 0 | 77 | 8 |
| `rethink-first-write` | 45,159 | 30 | 78 | 8 |

- **Same seed, same run, up to the first write.** Each of the nine runs thought exactly the
  same number of tokens before its first write in all four batches (H1 seed 1: 4,653 in each;
  H3 seed 2: 2,514). The batches are separate processes on different days, but with the same
  seed and the same prefix they replay token for token until the prompt first differs. So up
  to the first write these batches are paired, not independent samples, and every difference
  between them comes after it.
- **The replay ends at the first visible gate, even with no policy difference.** The gate's
  output includes pytest's timing line (`1 failed in 0.05s`), which differs from run to run.
  The loop check repeated no-thinking H1 seed 1 with the same settings as `guarded-nothink`; it
  matched that run token for token until just after its first gate, then sampled a different
  token (4,356 tokens in) and went on to pass. Same-seed runs past the first gate are close,
  not identical: `rethink-first-write` and `guarded-first-write` differ by up to 1% in tokens
  in runs where no policy fired.
- **What first-write removes is exactly the after-write thinking**: 27.6k deltas, 38% of all
  thinking; in `guarded-low` a median of 1,335 a run (48 to 10,583). The rest of the saving is
  the shorter path that follows: fewer replies, fewer rewrites.
- **Most of the thinking that remains is runaway, in one reply.** The read replies think briefly
  (mostly 15–200 deltas each). Then, in 7 of 9 runs, the reply that makes the first write thinks
  into the budget and is closed by force (4,114–4,119 deltas, the closing sentence included);
  H3 seed 1 does it twice, once on a re-read. Those 8 replies hold about 32.9k of the 45.2k
  deltas before the first write (73%). Koudai's close-path spike (`pauleveritt/ds4-engine#272`)
  replayed chat sessions that barely overthought (median thought 25 tokens, none at the
  budget); in these tool-using runs the thinking left after first-write is mostly a thought the
  budget had to cut, just before the model writes the code.
- **That thought drafts the code.** All 8 capped thoughts hold fenced code (6 to 14 blocks,
  15–18k characters each), and three are cut off mid-template (`<title>Customers</title>\n
  </head`). The model writes the files in its thought, the budget closes it, and it writes them
  again as tool calls. This is the "drafted the answer inside the thought" pattern from #272,
  but at the budget rather than near a close. A crude count (fence markers, code-like lines),
  not a judged reading of how much of each thought is planning.

## The guard's escalation

New in this round, TDD in `test_ds4_adapter.py` and `test_runner.py`. When the guard refuses
a call and the model's very next call repeats that same refused call (same tool and path; for
a write, content identical to the file), the tool raises `ModelResponseFailure("tool_loop")`.
That is the prose arm's existing model-failure path: the runner restores the workspace and the
pre-attempt boundary, gives one retry, and passes the failure's text as visible feedback. The
text names the looping call and carries the last visible gate's output. A run that loops twice
ends `failed`, not `harness_fault`. Refusals of different calls in a row do not escalate:
no-thinking H3 seed 1 refused three different reads back to back and then recovered.

Why this design rather than closing tools: it needs no runner change and one new reason in the
contract, while closing tools would mean banning Qwen's `<tool_call>` token in a logits hook and
relying on the model to answer in prose rather than write the call as text until `max_tokens`.
Its cost is that the looping attempt's work is thrown away.

**The escalation has not fired in a live run.** The E3 pilot with thinking off had no loop.
The loop check reran no-thinking H1 seed 1, the run that looped in both earlier batches: it
replayed that run until just after its first visible gate, then the gate's timing line changed
the prompt, the model sampled a different token and the run passed every hidden test in 357 s
(4,852 tokens), with no refusal. None of the nine runs in the batch below looped either. The
escalation's evidence is the unit tests and one end-to-end test that drives a scripted write
loop through the real adapter and tool loop; that a real loop ends there, and that the retry
then recovers, is untested.

## Rethinking after a failure

Also new, behind `rethink_after_failure` (requires `think_until_first_write`): a failed visible
gate or a guard refusal lets the model think again until its next write. The adapter records
each trigger.

- **E3 pilot.** It replayed `pilot-first-write` exactly to the first write (663 thinking
  deltas), its visible gate failed, the rethink fired and the model thought 211 more deltas
  before the passing fix: 252 s and 4,032 tokens against 283 s and 3,827 tokens. One run.
- **The H1–H3 batch.** Predicted before it ran (shared notes, `thinking-control-prediction.md`):
  `guarded-first-write` had no failed visible gate and one refusal (H2 seed 2), so 8 of 9 runs
  should replay it and only H2 seed 2 can differ. That held. The same 3 full passes and 8 of 9
  on the stated behavior, with the same hidden failures run for run; no visible gate failed
  and no tool loop occurred, so the gate-failure rethink was not exercised in the batch. Eight
  runs match `guarded-first-write` in thinking exactly and in tokens within 1%.
- **H2 seed 2, the one rethink.** Both batches reach the same refusal: the model tries to
  rewrite `customer_detail.html` with the content it already holds. Without rethinking it wrote
  the template twice more before running its gate. With it, the model thought 30 deltas
  ("I need to fix the leftover fragment `({{ follow_up_statuses|default:"" }}`. Let me rewrite
  the file with a clean version."), wrote it once and ran the gate. The run took 947 s and
  14,658 tokens against 1,092 s and 15,665, with the same hidden result. One run, and past its
  first gate the two runs are not a replay, so this is an example, not a measured saving.
- **The batch overall** matches `guarded-first-write` within noise: 6,847 s against 6,832 s,
  99,531 tokens against 100,234. Rethinking cost nothing measurable here, and on these seeds
  it had almost nothing to do.

## What would falsify this

- A batch on these settings in which first-write's stated-behavior count falls below LOW's,
  or its total wall time is not lower.
- A same-seed batch whose thinking before the first write differs from these without a policy
  difference before that point: then the batches were not replays, and the pairing claim fails.
- Another tool loop that the escalation does not end before the request limit.

## Risks and caveats

- **Three seeds, and near-replays.** The same seed replays a run up to the first prompt
  difference, so seeds 1–3 are three trajectories, not three samples per batch; another batch on
  the same seeds adds almost nothing up to its first divergence. New seeds are the next sample.
- **Unpaired after the first write.** Beyond it the batches diverge freely, and past the first
  visible gate even identical settings diverge (the timing line); wall time also depends on the
  machine's load on the day.
- **The escalation is untested live.** No run looped once it existed (above).
- **The two unstated hidden tests** cap the full-pass count, so all thinking arms tie at 3 of 9.
  The stated-behavior count is the only place a difference can show, and at n = 9 it cannot
  show one with confidence.
- **The rethink path was barely exercised.** These seeds never failed a visible gate with
  first-write thinking; the batch rethought once (after a refusal), and the gate-failure path
  ran only in the E3 pilot. The batch tests replay more than it tests rethinking.
- One model, one project, one machine (an M5 Max; Koudai's runs were on an M4 Max).
