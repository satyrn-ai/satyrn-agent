# Import mask: review of the "don't build it" rationale

An independent agent reviewed the roadmap's reasons for not building an import
mask for the 27B (2026-11-07). This note records its findings, the corrected
rationale, and the backlog entry. Roadmap:
[2026-11-07-overnight-domains-roadmap.md](2026-11-07-overnight-domains-roadmap.md).

**What is measured:** the cited records below, re-read by the reviewer. The
484.054 ms figure was recomputed from all 208 retained mask records.
A cost screen on the 27B (section 4) measured about 0.1 ms per masked step
for a cached, batched mask.
**What is conjecture:** any claim about the mask's benefit, and the cost of a
multi-token trie walk, which the screen did not include.

## The question

An import mask constrains tokens at `from X import Y` name positions to names
that exist, using an `ast` export index and ds4-py's logits hook. The roadmap
said: don't build it, because it's expensive and the 27B has no import errors
to fix.

## Verdict

**Keep it deferred, but for a different reason.** Its benefit under this
harness is unmeasured. The evidence does not show the 27B never makes import
or API errors, and 484 ms is not a measured cost for this mask design.

## Claim 1: "it's expensive" — unsupported for this design

| Claim | Finding | Source |
| --- | --- | --- |
| Masks cost 484 ms each | Confirmed for that implementation, on Laguna S 2.1, not the 27B. 480.293 ms (99.22%) was building the allowed set by CPU-side vocabulary enumeration; sampling was 3.722 ms. It measures that implementation, not a floor for a cached import-name mask. | ds4-engine `docs/superpowers/research/2026-09-17-p16-mask-cost-finding.md:77`, `:128` |
| `bias()` copies and sets the whole vocabulary | Confirmed. A mask should batch its changes into one copy, update and set per constrained step. This is avoidable work, not a latency figure. | ds4-py `src/ds4py/engine/logits.py:80`, `:91-99` |
| QW.2 was negative | Confirmed, but weak evidence here. Different model (Qwen3.8 Flash Next Q4). Constrained 8/12 vs 12/12, and all four losses came from grammar rules blocking valid root-level file creation: a warning about wrong constraints, not a test of import masking. | ds4-engine `docs/superpowers/research/2026-09-21-qwen-rehearsal-finding.md:14`, `:93` |

## Claim 2: "the 27B has nothing for it to fix" — wrong as stated

| Record | What happened | Caveat |
| --- | --- | --- |
| Wrong `from` import | Base 27B wrote `from collections import frozendict`, got `ImportError`, found it is a builtin, fixed it, passed. | oMLX 8-bit, not ds4 Q4. Right error shape, already recoverable. satyrn-evals `evidence/2026-10-29-py315-agentic-sft/v1-overnight/sft-agentic.jsonl:32` |
| Invented module/API | Base 27B imported nonexistent `profiling.stats` (`ModuleNotFoundError`) and described a nonexistent `TracingProfiler`. | Same oMLX experiment; broader than a from-name mask. Same file `:29`; `factpass.jsonl:29` |
| Nonexistent method under ds4 | The 27B built `Starlette()` and called `app.post(...)` → `AttributeError`. | A probe during a spiral, not a surviving defect; an import mask wouldn't catch it. ds4-engine `docs/superpowers/research/2026-10-14-doc-tool-screen/on-s1/captures/run-1-1791951482087.json` |
| Invented project API | Pathology 107: nonexistent `ContextSnapshot`, `ds4.engine.snapshot`, `Engine.to_json`. | Attributed to the satyrn fine-tune, not base Qwen. ds4-engine `docs/pathologies.md:1470`; `docs/superpowers/research/2026-10-06-plain-qwen-27b.md:44` |

Satyrn-evals path: `/Users/pauleveritt/projects/pauleveritt/satyrn-evals`.

## Corrections to supporting claims

These also affect the roadmap and survey, which now carry them.

- **Pathology 103 is Ornith-1.5-9B**, not the 27B (`pathologies.md:1411`).
  The rest of the 27B failure list is confirmed.
- **Agent-gap 11/13 easy, 13/13 hard:** confirmed for the product harness,
  n = 1 per suite; upstream ds4-agent timed out on hard. These scores say
  nothing about an import-error rate (`agent-gap-screen.md:68`).
- **Mellum wrong imports in 9/9:** confirmed as a grouped finding covering
  `RedirectResponse` and `Jinja2Templates`; `RedirectResponse` alone in all
  nine is not supported. Seven sessions repaired the imports after importing
  or testing (mellum-worker `2026-11-06-medium-hard-failure-shapes.md:28`).
- **"Bare 27B 6/6 where every Mellum setup was 0/6": wrong.** Mellum's bare
  Jinja build also completed 6/6, and these are completed phases, not six
  independent trials (tainie `docs/research/2026-07-04-sp12-thesis-report-v5.md:191`).
- **"An export mask can't catch `allow_redirects`":** confirmed; that is a
  call-signature error (`pathologies.md:1596`).

## Backlog entry

**Import mask (deferred).** Benefit under this harness is unmeasured; cost of
a cached, batched mask on ds4-py is unmeasured.

- **Measure first:** during the item 1 calibration screen, count invalid
  imports and invented APIs, and the time and tokens spent repairing them,
  after skeleton generation and a write-time import check.
- **Reopen when** invalid imports impose meaningful failure *or repair* cost
  after the skeleton and the import check, on any model. Repairs count: a
  fixed import can still waste minutes. A Mellum port triggers this
  measurement, not construction.
- **Before building:** benchmark a cached, batched mask (section 4), then
  compare completed work and wall time against checks alone. A valid exported
  name can still be the wrong one, so zero `ImportError`s is not the success
  criterion.

## 4. Cost screen on the 27B (run 2026-11-07)

**Setup:** `Qwen3.8-27B-Q4_K_M.gguf`, ds4 upstream `5379c1c9` with
satyrn-agent's qwen35 patches (the e2e-built `libds4.dylib`, Metal), ds4-py
`5c98c6a`, M5 Max 128 GB. ctx 4096, temperature 0, seed 1, 128 tokens per run,
a fresh engine per run, one discarded warm-up. Script:
[`2026-11-07-import-mask-review/mask_cost.py`](2026-11-07-import-mask-review/mask_cost.py).
Whole run: 36.5 s.

**Arms:** `none` (no hook); `copyset` (hook copies the logits and sets them
back, the floor for any batched mask); `mask` (hook keeps only a cached
allowed set and sets everything else to `-inf`, on **every** step, the worst
case; a real import mask fires only at a few name positions per file).

| Rep | Arm | ms/token | Hook ms/step |
| --- | --- | ---: | ---: |
| 0 | none | 33.5 | — |
| 0 | copyset | 34.0 | 0.084 |
| 0 | mask | 34.9 | 0.090 |
| 1 | none | 35.5 | — |
| 1 | copyset | 37.3 | 0.069 |
| 1 | mask | 36.7 | 0.108 |

**Allowed set:** 677 exported names from 10 stdlib modules → 649 first
tokens, built by tokenizing each name in 17.5 ms, once.

**Reading:**

- The hook body costs **about 0.1 ms per masked step**, under 0.3% of a
  token. P16's 484 ms was the allowed-set construction; caching it removes
  that cost.
- Wall time per token differs between arms by less than the 2 ms swing
  between reps, so any extra cost of running a hook at all is within noise at
  n = 2.
- This settles the cost question for this design: a cached, batched mask is
  cheap on ds4-py. Benefit is still unmeasured.

**Limits:** first-token masking only. A real mask also walks a token trie for
multi-token names; that adds Python work per masked step, not measured here.
Larger allowed sets scale the copy loop linearly. ctx 4096 gives 28–30
tok/s here; the 18.5 tok/s figure elsewhere is from longer contexts.

## 4a. The cost test as proposed (before the run)

From the ds4-py code, not a measurement:

- `copy_logits` and `set_logits` use a reusable `array('f')` buffer through
  `from_buffer`, so a batched mask is two vocabulary-sized memory copies per
  constrained step, plus building a `-inf` array and copying the allowed
  logits into it.
- The allowed set comes from a token trie of exported names, built once per
  module and cached. That removes the step that was 99% of P16's cost.
- Masking applies only at name positions after `from X import`, a few steps
  per file. At 18.5 tok/s a token takes about 54 ms, so even a few
  milliseconds per constrained step would be small.

**Test design:** one script on the configured 27B
(`/Users/pauleveritt/models/Qwen3.8-27B-Q4_K_M.gguf`) with three arms on the
same prompt and seed: no hook; a hook that only copies and sets logits; the
full cached mask. Report per-step hook time, wall time per token, and the
one-off trie build time. n = 3 per arm reads a cost, not a benefit.

## What would falsify this

- The calibration screen shows no import errors and no repair time: the mask
  stays parked with nothing to fix.
- A trie-walking mask turns out to add tens of milliseconds per step: cost
  matters again. (The first-token screen measured about 0.1 ms.)

## Risks

- The 27B counterexamples are mostly from oMLX 8-bit or a fine-tune; their
  rate under ds4 Q4 is unknown.
- A correct-looking mask can still block valid code, as QW.2's grammar did.
