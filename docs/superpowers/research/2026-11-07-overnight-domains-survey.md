# Overnight domains: survey

The full record behind
[2026-11-07-overnight-domains-roadmap.md](2026-11-07-overnight-domains-roadmap.md).
It comes from one long brainstorm on 2026-11-07 (Claude Code session
`213fe54b-1431-49f5-992e-d592db14aed5`, satyrn-agent, compacted twice). The
roadmap says what to do; this page records what was found, where, and how
sure we are.

**What is measured:** numbers given with a `path:line` or a run record. All of
them are from earlier projects. Nothing was run on this branch.
**What is conjecture:** every claim that an idea will help here, session
lengths, sessions per night, and anything marked *(unverified)*.

Repository shorthands used below:

| Short | Path |
| --- | --- |
| `E` | `/Users/pauleveritt/projects/pauleveritt/ds4-engine` |
| `P` | `/Users/pauleveritt/projects/satyrn/ds4-py` |
| `M` | `/Users/pauleveritt/projects/pauleveritt/mellum-worker` |
| `L` | `/Users/pauleveritt/projects/pauleveritt/local-ai-pi` |
| `T` | `/Users/pauleveritt/projects/t-strings` (`tainie`, `tainie-old`) |
| `S` | `/Users/pauleveritt/PycharmProjects/superpowers` |

## 1. How the conversation moved

1. Built and verified ds4-py and satyrn-agent end to end on the 27B.
2. Read the "Jev architecture review" session (Claude Code
   `local_89e686b3-ed52-43c5-b56a-6dba5d072cff`, cwd `E`) and had Fable
   propose a fast-path experiment (section 6).
3. Paul reframed the goal (section 2).
4. Digested tainie and its Pyrefly fork; asked about a Pyrefly + logits mashup
   (section 5).
5. Asked whether symbols-not-strings works without Pyrefly (section 5).
6. Fable gave a 30%-skeptical review of ideas A–G (section 7).
7. Brought in Superpowers spec → plan and mellum-worker's worker idea
   (sections 8, 9), and typed handoff packets (section 10).
8. Settled who plans: a big model for the roadmap, the local model for
   packets, the human out of domain.
9. Narrowed to a mini-roadmap; switched the worker from V4 Flash to the 27B.

## 2. Paul's goal, in his words where possible

- Help a small local agent write code "the way the human would have written
  it".
- "I also want the Python community to capture these and distribute them,
  including for frameworks like Django."
- "Find some synthesis between Jev-style and LLM-style that speeds up
  well-known operations by encoding them as 'domains'."
- "I'm hoping our unique architecture gives us some opportunity here to do
  something in a very different way than classic agents."
- Style examples: function views; Hynek's design pressure (domain objects
  apart from ORM models); testable helpers; semantic aliases
  (`type FirstName = str`); deterministic tools own the first and last steps.
- 1 + 1 = 3: output read by humans and small models; code lands in the right
  Django app with views, templates, maybe models, layered tests and docs;
  work happens inside Superpowers spec-driven development.
- Fast Mellum decode makes try/retry loops attractive, now that satyrn-agent
  controls the loop through Pydantic AI. Mellum itself waits for a port.
- A big model writes the roadmap only for big non-routine work, "with enough
  help that a smaller model can do 'planning' aka handoff packets". Out of
  domain, "we bring in the human".

## 3. The stack today

- **ds4 engine** pinned at upstream `5379c1c9`, with satyrn-agent patches
  `patches/common` and `patches/qwen35` (dense Qwen on Metal, DFlash
  exports). Merged in satyrn-agent #3 and #6.
- **ds4-py** (`P`): logits hook, checkpoints, rewind, prefix KV cache,
  Pydantic-AI agent, Qwen tool syntax (`src/ds4py/engine/tool_syntax/qwen.py`).
  - `LogitsView` (`src/ds4py/engine/logits.py`): `logits()` copies the full
    vocabulary; `bias(token_id, delta)` copies and sets the whole vocabulary
    per call (around lines 91–99); the view exposes `position`, `in_think`,
    `think_tokens`, `parser_state`, `sampled_tokens`.
  - `session.add_logits_hook` registers only between rounds and must not call
    engine APIs (session.py around 454).
  - `session.checkpoint` (around 608) restores with no prefill. `rewind`
    (around 410) is unverified on qwen35.
- **satyrn-agent PR #12** (open, stacked on #11): the `satyrn_agent` package
  with DFlash decode, Qwen sampling defaults and a soft think-budget hook.
  Unit tests at 100% coverage; its 17 live tests skipped for lack of a model.
- **27B on this Mac (M5 Max, 128 GB):** decode 18.5 tok/s serial; prefill
  about 452/409/365 tok/s at 2K/8K/16K; prefix hit 16–20 ms against a 4.7 s
  fill. DFlash about 58 tok/s in ds4, not yet in ds4-py. Model file:
  `/Users/pauleveritt/models/Qwen3.8-27B-Q4_K_M.gguf`.
- **V4 Flash** (parked): `P/docs/reports/2026-11-01-m3-functional-checkpoint.md`
  passed 12/12 tasks at about 37 tok/s overall, on an RTX PRO 6000 Blackwell
  with Q2 weights (80.76 GiB).

## 4. ds4-engine prior art (`E`)

- **BM25 file index** for the `@` picker (`src/ds4_engine/relevance.py`):
  files in 200-line runs, not symbols; no gain over 12 runs.
- **Path trie** for "symbol" masks (`crates/ds4-host/src/contract/trie.rs`):
  paths only; removed 2026-10-07 with the masks.
- **Grammar masks:** `docs/capability-map.md:92`. No advantage on any model
  but Flash; QW.2 (Qwen) 8/12 with the mask vs 12/12 without (n = 12). "Each
  mask cost 484.1 ms (n = 208)." These were tool-call grammar masks, not
  import masks; the cost is the closest measured figure.
- **`doc(name)` lookup (SC.2):** built, retired 2026-10-14. Its result showed
  the trap answer in 14 of 33 runs; it was called in 2 of 5 runs in the first
  screen; nudges reached at most 3/5; two copies of the same arm swung median
  21 vs 12 replies (`ROADMAP.md:168`).
- **Repository symbol index:** proposed as option D in
  `docs/superpowers/research/2026-10-14-search-design.md`, never built.
  Capability-map item 19 ("no index") is about cross-session memory, not a
  symbol index.
- **Capability-map item 20:** compare policies from identical state
  (snapshot plus two draws). This is the paired design in the roadmap.
- **Symbols-not-strings note:**
  `docs/superpowers/research/2026-09-24-symbols-not-strings.md`. Its open
  input was "the owner's Pyrefly fork", which turned out to be tainie's.
- **Thinking:** thinking only until the first write saved 110–126 s and
  about 2,000 tokens per session
  (`docs/superpowers/research/2026-10-03-qwen-thinking-finding.md:52`).
- **27B agent-gap screen:** AgentClinic easy 11/13, hard 13/13, one run each
  (`docs/superpowers/research/2026-10-12-agent-gap-screen.md:70-96`).
- **27B pathologies** (`docs/pathologies.md`): probing spirals (115, 122,
  124), a 12K-token think (114), stale kwarg `allow_redirects` (121), rewrite
  loops when only a host message changes (102, 103). Under no-think the 27B
  wrote the same file 22 times (102, around line 1398).
- **Related notes:** `2026-09-03-monty-task-compiled-workflows.md`,
  `2026-09-07-exemplar-priming-house-style.md`, and the Django TUI runs
  `2026-09-26-tui-chat-django*.md` (django-t001/-t003/-t014; source "SR";
  scores 3/3, 1–2/3, 3/3). Where those Django suites live is unknown.

## 5. Symbols, not strings

**tainie** (`T/tainie`, summer 2026) was a Pyrefly-backed refactoring agent.
Its fork is `~/PycharmProjects/pyrefly`, branch `tainie-fork` (about 36
commits): Glean xrefs, `overlay-check` (apply N edits in memory and diff
diagnostics against a baseline), `recognize`, `fanout`, `propagate`, t-string
typing. Its thesis: Pyrefly "finds, classifies, and proves; the model fills the
hole", and "the smaller the model, the larger the win"
(`T/tainie/docs/pyrefly.md:28-34`). Findings from the digest:

- Recipe tasks were already easy for a 12B model; 67% of real prompts were
  outside any recipe. *(The "Mode-3 NO-GO" record could not be located;
  unverified.)*
- The only thing that reliably worked was an ambient gate on every write, but
  that was a design argument, never a measured win.
- Two ideas were never built: a deterministic skeleton with the model filling
  holes, and intent typing.
- Every false green came from plumbing, so each gate needs a planted-bug
  self-test.
- None of the asks to the Pyrefly or Mellum teams got a recorded reply
  (`T/tainie/docs/pyrefly.md:135-165`).
- ds4-engine's note on tainie has errors: it read a 07-03 recovery snapshot,
  said the agent-clinic fixture was lost (it is intact), and called
  deepseek-v4-pro runs "Flash".

**Without Pyrefly:** Python's `ast` indexes definitions, signatures, imports
and `type` aliases for the repo and installed packages. Type inference is
lost, but annotated parameters recover much of it. Decisions:

- The index drives the harness (packet validation, the skeleton, write-time
  checks), never a tool the model chooses to call.
- Symbols move up to the plan: when the packet names `Customer`,
  `CustomerName`, `crm/views.py::list_customers`, most "which symbol?"
  questions are answered before decoding.
- Shrunk for the 27B: it shows no wrong imports or invented APIs, and an
  export index can't see its stale-kwarg error.
- No import mask: mask cost (above), `bias()` copies the vocabulary, and no
  27B import errors to fix. Reopen with a Mellum port, or if the 27B shows
  import errors that survive the skeleton and a write-time check.
- Pyrefly mid-decode checks parked. From a Python host Pyrefly would be a
  subprocess or a new PyO3 binding. First step if reopened: run Pyrefly over
  27B bodies and count unresolved names, wrong attributes and type errors.

## 6. Jev review and the fast path

Jev is TypeSafe's decision model (yes/no, choice, score). Fable's proposal for
a fast path on well-known tasks such as "add a Django view":

- **Fast path:** no thinking (or a small budget) plus a checkpointed Django
  playbook prefix of about 800 tokens.
- **Router:** a regex on the prompt plus checking `views.py`, `urls.py` and
  `templates/` is near-oracle, so the model's own yes/no must beat that to
  earn a place. The decision is load-bearing only if the fast path is cheaper
  when right, costly when wrong, and nothing deterministic separates the
  cases.
- **Rule:** adopt if median paired wall time B/A ≤ 0.75 and B passes ≥ A − 2
  of 32. A router (D) only if misrouting loses ≥ 3 off-domain pairs and D's
  composed passes ≥ C's + 2.
- **Pilot stop:** 4 in-domain tasks × 2 seeds; stop if B's median isn't
  ≤ 0.8× A or B loses 2 of 8 of A's passes.
- **Known risk:** pathology 102.

Later reframing: tainie found recipe tasks easy, so speed from recipes is
probably small. The value is style and correctness through examples in front
and checks at the back. The Jev part moves from run time to plan time: typed
choices in the packet, decided by deterministic analysis first and logits on
a short question second.

## 7. Fable's skeptical review of ideas A–G

| Idea | Verdict | Main objection |
| --- | --- | --- |
| A `ast` index | Shrink to exports and project defs | Information was never the bottleneck (pathology 115); Mellum-shaped |
| B write-time check + restore | Keep, re-aimed | Unique to in-process; cap at 2; escalate by reopening thinking; use checkpoint, not rewind |
| C skeleton prefill | Keep | The 27B may rewrite the file; the write tool must be body-only; a correct skeleton can hide spec misreads |
| D domain prefix in KV | Shrink | 4.7 s saved per ~25-minute session; keep a fixed exemplar prefix and tiered checks as a style oracle |
| E import mask | Drop | 484 ms per mask, QW.2 negative, `bias()` cost, no 27B evidence |
| F gates | Floor in every arm | Verify-own-tests is the floor, not an arm |
| G plan-time decisions | Adopt | Methodology, not an arm |

Its headline: the 27B doesn't show Mellum's failure shapes. Its recommended
design was paired per-write draws from identical state, with C-on vs C-off
under B's check. One error: it said the 110–126 s figure didn't exist; it is
at `E/docs/superpowers/research/2026-10-03-qwen-thinking-finding.md:52`.
Two claims of mine it corrected: the `doc` tool's "14 of 33" was about
results, not calls; tainie's ambient-gate win was a design argument.
*(Its claim that tainie's SP12 had the bare 27B at 6/6 where every Mellum
setup scored 0/6 is unverified.)*

## 8. mellum-worker (`M`)

- Mellum 2.1 12B-A2.5B, through Pi on llama.cpp or oMLX, on AgentClinic
  FastAPI suites with hidden graders. Easy 4, Medium 18, Hard 34 checks. No
  recorded setup passes Hard; every recorded setup is Mellum
  (`learn/challenge/index.md:52-71`).
- Verify-own-tests on Medium, n = 12 per arm: hidden checks 43/216 → 203/216,
  sessions scoring 0/18 from 9 to 0. It worked partly because Medium ships a
  starter test that imports the app; Hard has none. The same config scored
  69/108 in one batch and 43/216 in another.
- Mellum failure shapes: untyped `request` → 422; `from fastapi import
  RedirectResponse` in 9/9 sessions; settling on unverified builds;
  quote-pairing SyntaxError; loose spec reading; an invented sqlite-utils
  Migrations API; edit-miss loops. Its advisory Pyrefly report flagged the
  imports and the invented API, but nothing acted on it.
- Harness learnings (`docs/harness-learnings.md`): harness guarantees beat
  prompt rules; retries must carry the concrete failure; best-of-N doesn't fix
  systematic omissions; a build passed all its own gates and still scored
  31/34 hidden.
- Process (`docs/sdd.md`): screens first, preregistered runs decide;
  n = 1 settles a presence, a comparison needs n ≥ 3; research notes carry
  measured/conjecture headers.
- Do-not rules from its HANDOVER: don't change the LAN vLLM host; never commit
  or print the vast.ai token; renting needs Paul's approval; never commit raw
  traces, stdout or patches; never code to the eval.

## 9. Superpowers spec → plan as the source for packets

`S/skills/writing-plans/SKILL.md` already produces most of a packet. Each
task has exact Files, an Interfaces block (Consumes/Produces with exact
signatures), a failing test as code, the run command with expected FAIL, the
exact signature ("the implementer writes the body"), the run command with
expected PASS, and a commit. Plans add Global Constraints and a Review Focus.
"A plan is the set of decisions the implementer cannot make alone."

The risk for a small model: the skill assumes the implementer "will make a
reasonable choice wherever the plan leaves one open". Compiling closes that
gap: the harness writes the test, confirms it fails, prefills the signature,
lets the model write the body, runs the gate, restores on failure, and
commits. That is arm C in the roadmap.

## 10. Typed handoff packets

- **local-ai-pi** (`L`, last commit 2026-08-18): the
  `HandoffContract` interface in `extensions/implementer/handoff-contract.ts`
  has `task`, `writableFiles`, `readableFiles`, `acceptanceStrings`,
  `preservedBehavior`, `knownFacts`, `validation`, `removableSymbols?`. YAML
  frontmatter; checked before any model call; globs refused. On Gemma 12B,
  "Name the operation, not the intention" scored 8/8 vs 0/8; the cycle-7
  confirmatory run (64 attempts) won 1 of 4 tasks. Its skill says the small
  model "cannot plan… You are the planner. The contract is the recipe."
  (`.claude/skills/write-handoff-contract/SKILL.md`).
- **tainie-old** (June 2026): sectioned plain-text packets for Mellum2 —
  TASK / GATE / SIGNATURE / CONTRACT / EXEMPLAR / CONSTRAINTS / AFTER EDITING
  — with house rules: semantic `type` aliases, pydantic at boundaries, pytest
  functions, no `from __future__ import annotations` (`T/tainie-old/AGENTS.md`).

## 11. FIM

The 27B's tokenizer contains `<|fim_prefix|>`, `<|fim_suffix|>`,
`<|fim_middle|>`, `<|fim_pad|>` and `<|repo_name|>` (checked by scanning the
GGUF header on 2026-11-07). Whether this instruct/thinking model was trained
to use them is untested. tainie-old ran Mellum2 per-site FIM with a strong
driver choosing the route.

## 12. Open questions for the Superpowers cycles

- The reference app: Django (Paul's examples) or FastAPI (matches
  AgentClinic). Claude recommends Django.
- Where the Django suites from ds4-engine's TUI runs live, and whether they
  could carry a hidden grader.
- Whether the 27B keeps a prefilled skeleton or rewrites the file.
- Whether `session.checkpoint` restores cleanly mid-agent-loop on qwen35.
- Whether PR #12's DFlash and think budget pass live on the 27B.

## What would falsify this

- The 27B clears Hard unaided at 3/3: no headroom on the outside judge.
- Compiled packets show no paired gain over the prose plan.
- The 27B can't fill typed packet fields even with choices and logits.
- The fast-path pilot misses its 0.8× bar.

## Risks

- Most numbers here come from other models, harnesses or suites.
- Several summaries are second-hand (Fable, digest agents); the unverified
  ones are marked, others may still be wrong.
- The style checker and the reference app are ours; tuning one on the other
  risks grading what the model was shown.
