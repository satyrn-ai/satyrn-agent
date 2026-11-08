# Masks, logits and Mellum: prior art and fresh ideas

A prior-art search (arXiv and the web, 2026-11-07) asking what we could do
with satyrn-agent's in-process machinery that classic agents can't, with an
eye on bringing Mellum in later. Related:
[roadmap](2026-11-07-overnight-domains-roadmap.md),
[survey](2026-11-07-overnight-domains-survey.md),
[import-mask review](2026-11-07-import-mask-review.md).

**What is measured:** the papers' own results (as stated in their
abstracts); the local Mellum GGUF's FIM tokens; the 0.1 ms first-token mask
cost from the import-mask review; tainie-old's Mellum2 per-site leaf result.
**What is conjecture:** every idea in section 3, and the claim that no one
has published idea 3. That claim comes from a short search, not a survey.

## 1. Prior art

| Work | Finding | For us |
| --- | --- | --- |
| Monitor-guided decoding, [2306.10763](https://arxiv.org/abs/2306.10763) (NeurIPS 2023) | A static-analysis monitor masks identifiers during decoding (Java). Small models with it beat larger ones: SantaCoder-1.1B beat text-davinci-003 on compilation rate and next-identifier match. | Direct prior art for masking names that must exist. Python tooling ([multilspy](https://pypi.org/project/multilspy/), jedi; [scubalspy](https://pypi.org/project/scubalspy/), Pyright) uses a language server; we would use an in-process `ast` index. |
| Type-constrained code generation, [2504.09246](https://arxiv.org/abs/2504.09246) | Prefix automata enforce well-typedness in TypeScript; compile errors cut by more than half. | The sound, heavy end. A signature index is the cheap end. |
| Grammar-aligned decoding, [2405.21047](https://arxiv.org/abs/2405.21047) | Masks distort the model's distribution: valid output with likelihood not proportional to the model's. Its fix (ASAp) had no strong downstream effect on task solving (per Fable, from the paper's text). | Distortion arises only where multi-token names share a prefix; see section 4. *(Corrected 2026-11-07; first read "lower quality … mask as rarely as possible".)* |
| Constrained decoding: harmful or beneficial?, [2610.35328](https://arxiv.org/abs/2610.35328) | Most apparent harm comes from prompting and format, not the mask. Validity constraints (masking invalid answers) improve reliability. | Mask only closed, valid-answer slots. |
| The Format Tax, [2604.03616](https://arxiv.org/abs/2604.03616) | Format instructions cost most of the accuracy; separating reasoning from formatting recovers it. | Never mask while thinking (`LogitsView.in_think`). |
| Uncertainty rollback, [2608.14653](https://arxiv.org/abs/2608.14653) | Rolling back to an earlier valid prefix beats equal-budget restart, up to +0.26 pass@1. | Rollback is worth having; we have it cheaply. |
| Uncertainty self-correction, [2608.14659](https://arxiv.org/abs/2608.14659) | On small code models, entropy-triggered regeneration lowered Pass@1 in 5 of 6 setups. | Entropy may choose *where* to check; a deterministic check decides. |
| Code uncertainty, [2606.09577](https://arxiv.org/abs/2606.09577) | Single-pass Top-K token entropy matched the best multi-pass baseline on Qwen3-14B. | A cheap signal for choosing where to spend checks. |
| Dynamic early exit, [2504.15895](https://arxiv.org/abs/2504.15895); CoT entropy change-points, [2606.02020](https://arxiv.org/abs/2606.02020) | Stop thinking once a trial answer is confident; about 19% shorter reasoning across 11 models. | Aimed at the 27B's 12K-token think (pathology 114). |
| SteerMoE, [2509.09660](https://arxiv.org/abs/2509.09660) | Turning behaviour-linked experts on or off steers MoE models without training. | Mellum is MoE (64 experts, 8 active). Needs routing access in a ds4 Mellum port. |

## 2. Mellum facts

- Mellum 2.1: 12B total, 2.5B active, 64 experts with 8 active, an RL-tuned
  thinking model ([NYU Shanghai RITS](https://rits.shanghai.nyu.edu/ai/jetbrains-ships-mellum2-1-a-12b-open-model-for-coding-agents/),
  [llmreference](https://www.llmreference.com/model/mellum2-1-12b-thinking);
  secondary sources, self-reported benchmarks).
- **FIM tokens are present.** The local
  `Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf` tokenizer contains `<fim_prefix>`,
  `<fim_suffix>`, `<fim_middle>`, `<fim_pad>` and `<filename>` (header scan,
  2026-11-07). No web source confirmed FIM *training* for 2.1.
- tainie-old measured Mellum2 (not 2.1) as a per-site leaf filler at 10/10
  (`T/tainie-old/docs/pyrefly-mellum.md:157-170`, cited in the survey).
- Mellum's recorded failures are what masks target: wrong FastAPI imports
  (grouped 9/9, seven later repaired), an invented sqlite-utils Migrations
  API, and a Pyrefly advisory report that "nothing acts on"
  (mellum-worker `2026-11-06-medium-hard-failure-shapes.md`).

## 3. Four ideas that stack

**1. Lazy, signature-aware monitor-guided decoding.** At identifier slots
(after `from X import`, after `.` on an annotated name, keyword-argument
names), the pre-sample hook checks whether the model's top choice is in the
trie. Valid: do nothing, so no distortion. Invalid: mask that one step. The
index covers keyword arguments from the callee's signature, not only
exports, which reaches pathology 121 (`allow_redirects`), the 27B error an
export index can't see. Off while `in_think`.

**2. Aim it at Mellum's FIM holes.** The harness writes the skeleton from the
packet; Mellum fills each body as a FIM hole under the lazy monitor, with
KV-checkpointed retries that carry the concrete failure. Mellum's fast decode
makes a small-hole try/retry loop cheap. This reverses the import-mask
verdict for Mellum: its failures are the ones the mask was built for.

**3. Per-slot counterfactuals from one checkpoint.** At each masked slot, fork
and decode masked and unmasked from identical state. This is capability-map
item 20 at the level of single decisions; a night yields thousands of paired
slot comparisons, which answers the "benefit unmeasured" question directly.

**4. A confidence probe to end thinking.** At a break in thinking, fork,
close thinking, prefill the skeleton, and read the confidence of the first
body tokens. High: exit thinking. Low: rewind and continue. Early exit with
the real code start as the trial answer, costing a few tokens and no
re-prefill. Targets pathology 114 and the 110–126 s per session measured in
ds4-engine.

Ideas 1, 3 and 4 are model-agnostic and testable on the 27B now. Idea 2 waits
for a ds4 Mellum port.

## 4. Mask distortion: Fable's review (2026-11-07)

Asked whether masks must distort the distribution, and how to avoid it with
our machinery. Fable read the grammar-aligned decoding paper's text; I
checked only that its two new citations exist and match.

**Mechanism.** Exact constrained sampling weights each token by its expected
future validity: the share of its continuations that end valid. A plain mask
treats every still-valid token as fully valid, so a prefix that mostly leads
to dead ends is oversampled.

**Consequence for our slots** (inference; the paper doesn't state it):

- **A slot decided by one token has zero distortion.** Masking and
  renormalising is the exact conditional there.
- **Distortion needs multi-token names that share a first token**, such as
  `Red` → `RedirectResponse` (valid) or `RedirectBase` (invalid). It stays
  inside that slot.
- So the variable that matters is prefix ambiguity at a slot, not how often a
  mask fires. "Mask as rarely as possible" was the wrong lesson.

**Ideas, ranked by Fable:**

| # | Idea | Distortion | Cost on the 27B (estimates) | Needs |
| --- | --- | --- | --- | --- |
| 1 | **Exact scoring.** When the lazy mask would intervene, force-decode each candidate name with real mass through the trie; take the argmax or sample by its probability. | Removes it | 5–30 forward passes, about 0.2–1 s per slot; a few slots per file | A way for the hook to stop and hand control to the harness, or slot-by-slot decoding from checkpoints |
| 2 | **Rejection sampling.** On an invalid name, restore the slot checkpoint and redraw unmasked. | Removes it | About name length ÷ P(valid); 3–6 passes when P(valid) is high | Mid-round restore. Breaks down when P(valid) is low (Mellum's imports); undefined at temperature 0 |
| 3 | **Synthesise imports.** Decode the body, resolve its names against the index, write the import block deterministically. | Removes the slot | Zero passes | Nothing new. Ambiguous names exported by two modules need a rule |
| 4 | **FIM suffix.** Let a later usage site condition the slot. | Reduces it | One suffix prefill per hole | FIM verified (item 0) or Mellum |
| 5 | **Valid names in context.** | Reduces it | Prefill, cacheable | Small models may skim lists, as with the `doc` tool |

**Dropped:** sequential Monte Carlo
([2504.13139](https://arxiv.org/abs/2504.13139)) suits open-ended constraints
such as a body under a checker. For a closed set of a few hundred names,
exact scoring is cheaper and exact.

**Test first:** at real slots, fork from one checkpoint and measure how often
the plain mask and exact scoring choose different names. Near zero on the
27B means distortion doesn't matter for our slots and ideas 2, 4 and 5 are
moot. Otherwise the same machinery is the fix.

**What this changes:**

- **Import slots are the weakest case for masking.** Idea 3 handles them
  deterministically. The remaining real targets are attribute and
  keyword-argument slots.
- **Token boundaries** are the problem DOMINO
  ([2403.06988](https://arxiv.org/abs/2403.06988)) addresses: the trie must
  include every tokenisation of a name (leading-space variants) and tokens
  that run past the name into legal following characters (`Response,`), or
  it blocks valid names, as QW.2's mask did.

## What would falsify this

- Per-slot counterfactuals (idea 3) show masked and unmasked slots finish
  equally often and equally fast: masks add nothing at this level.
- Mellum 2.1 can't fill FIM holes coherently despite the tokens.
- The thinking probe's confidence doesn't predict whether the body passes
  its gate.
- A trie-walking mask costs tens of milliseconds per step.

## Risks

- Monitor-guided decoding was measured on Java method completion, not agent
  loops.
- Token boundaries (names split across tokens, leading spaces) make trie
  masks error-prone; a wrong mask blocks valid code, as QW.2 showed. The trie
  must follow DOMINO's rules (section 4).
- Distortion at multi-token slots with shared prefixes is unmeasured; the
  disagreement test in section 4 measures it.
- With DFlash, the hook also sees staged draft rows; the mask must stay
  consistent across them.
- Entropy-only triggers made small models worse (2608.14659); every
  intervention here needs a deterministic check or a real probe behind it.
