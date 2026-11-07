# Overnight domains: mini-roadmap

Handoff from a long brainstorm (2026-11-07, branch `research/overnight-domains`)
into Superpowers. Each numbered item below is its own feature cycle:
brainstorm, spec, plan, execute. This page records the decisions so far and the
order. It is not a spec.

**What is measured:** the numbers cited with a source below.
**What is conjecture:** session lengths, sessions per night, and every claim
that an arm will help. Those are leads until a run backs them.

## Intent (Paul's)

Help a small local model write code **the way Paul would have written it**:
function views, domain objects kept apart from ORM models (design pressure),
testable helpers, semantic aliases such as `type FirstName = str`, and
deterministic tools owning the first and last steps. The output is read by
humans and by small models alike.

The intended shape, which is 1 + 1 = 3:

- A big model writes the high-level roadmap, and only for big non-routine work.
- Within a known **domain**, a smaller local model turns roadmap items into
  **typed handoff packets** (the plan).
- The local model executes packets under harness checks, in a loop that
  satyrn-agent controls through Pydantic AI.
- A request outside every known domain, or a packet that fails validation,
  goes to the human.
- The community distributes domains (Django and others): packet types,
  examples and tiered checks.

## Decisions

| Decision | Whose |
| --- | --- |
| Worker model is the dense **Qwen 27B** (qwen35) on this Mac, via ds4-py | Paul |
| Mellum is deferred until ds4 has a `mellum` port; it will join the family later | Paul |
| V4 Flash is parked (see below) | Paul |
| Yardstick: AgentClinic **Hard** (34 hidden checks), plus a style checker | Paul (Hard); Claude (style checker) |
| A reference sample app and roadmap with headroom come first | Paul raised it; Claude agreed |
| Plans and specs follow Superpowers; packets are compiled from plan tasks | Paul (Superpowers); Claude (compiling) |
| Masks are not part of this work | Paul |

## Measured facts this rests on

- 27B on this Mac (ds4 qwen35/Metal): decode 18.5 tok/s serial; prefill about
  452/409/365 tok/s at 2K/8K/16K; prefix-cache hit 16–20 ms against a 4.7 s
  fill. DFlash reaches about 58 tok/s in ds4. It is not yet bound in ds4-py;
  satyrn-agent PR #12 adds it, and its 17 live tests were skipped (no model).
- AgentClinic Hard: no setup on record passes it, but every recorded run is
  Mellum (`mellum-worker/learn/challenge/index.md`). The 27B has no Hard number.
- mellum-worker, Medium, n = 12 per arm: making the model verify its own tests
  moved hidden checks from 43/216 to 203/216. Retries help only when they carry
  the concrete failure. Best-of-N does not fix systematic omissions. A build
  that passed all its own gates still scored 31/34 hidden
  (`mellum-worker/docs/harness-learnings.md`).
- local-ai-pi typed contract on Gemma 12B: "name the operation, not the
  intention" scored 8/8 vs 0/8. The confirmatory cycle won 1 of 4 tasks.
- ds4-engine's `doc(name)` lookup tool was rarely called, and its result often
  showed the trap answer. That is why the index is not a model-facing tool here.

## Roadmap

### 0. Smoke-test the 27B as a worker (one evening)

Prove that ds4-py's tool loop drives the 27B through a multi-file build with
read, write and edit tools and a pytest tool, and that a git-checkpoint restore
works after a failed write. A presence check: n = 1 settles it.
*Watch for* the 27B failure shapes already recorded in ds4-engine: probing
spirals, 12K-token thinks, stale kwargs (`allow_redirects`) and rewrite loops.

### 1. Reference app and calibration

- **Reference app:** a small app written Paul's way, with two or three example
  phases and two or three held-out phases. Held-out solutions are written but
  never shown to the model.
- **Hard calibration screen:** the 27B, unaided, on AgentClinic Hard, n = 3.
  The score sets how much headroom there is.
- **Style checker:** tuned on the reference app. It is a proxy, never the
  oracle.
- **Hard wall:** example phases and held-out phases must not overlap, and a
  test enforces it. Otherwise we would be grading against our own answers.
- *Open:* the reference app in Django (Paul's examples) or FastAPI (to match
  AgentClinic). Claude recommends Django, with AgentClinic as the outside judge.

### 2. Typed packet v0 (no model)

A schema merging local-ai-pi's `HandoffContract`
(`writableFiles`, `readableFiles`, `validation`, `knownFacts`,
`acceptanceStrings`, `preservedBehavior`) with a writing-plans task's
Files/Interfaces/test/gate. Includes a validator backed by an `ast` symbol
index: paths exist, signatures parse, imports resolve. This is
symbols-not-strings applied to the plan, without Pyrefly.
*Risk:* a schema that fits one suite and nothing else.

### 3. Prose plan vs compiled plan (first overnight run)

Claude writes one frozen plan, which feeds two arms:

- **P:** the plan as prose; the 27B executes it.
- **C:** the plan compiled to packets. The harness writes the test, confirms it
  fails and prefills the signature; the 27B writes the body; the gate runs; on
  failure the harness restores and retries, at most twice, feeding back the
  concrete failure.

**Design:** paired same-state draws. Snapshot at each phase boundary and run
both arms from the same state, so each phase is one comparison. At 18.5 tok/s a
night holds only about 5–10 Hard sessions (conjecture), too few for
session-level arms. Record serial or DFlash in each run's metadata.
Preregister the arms, n and the decision rule before the deciding run.

### 4. The 27B as packet writer

Given a roadmap item and a domain, can the 27B write packets that pass
validation, and do the packets work? Compare packets Paul reviewed against
packets nobody reviewed. *Riskiest item:* local-ai-pi concluded that small
models "cannot plan".

### 5. Domain pack v0

Packet types, one example of each from the reference app, and tiered checks,
both mechanical and report-back.

## Parked, with reopen conditions

- **V4 Flash:** reopen if the 27B fails even with compiled packets, to tell a
  method failure from a model failure.
- **Mellum:** reopen when ds4 has a `mellum` architecture port.
- **Masks / constrained decoding:** reopen if style drift survives the
  examples and the signature prefill.
- **Thinking budget via `in_think`:** reopen if item 0 or 3 shows thinking
  runaways. The soft think-budget hook already exists in satyrn-agent PR #12.
- **Index as a model-facing tool:** dropped; models did not call the
  `doc` tool. The index serves the validator and the harness instead.

## Constraints carried forward

- Never code to the eval. Fixes must be general harness or test discipline.
- The hidden grader is the only oracle; report gate passes as proxy passes.
- Screens first, preregistered runs decide (mellum-worker `docs/sdd.md`).
- Do not commit raw traces, stdout or patches. No secrets in the repo.

## What would falsify this

- The 27B clears Hard unaided at 3/3: no headroom, so the reference app's
  held-out phases become the only test.
- Arm C shows no gain over P across paired phases: compiling adds cost for
  nothing, and the plan alone is enough.
- The 27B cannot write valid packets even within a domain: the planning split
  needs a bigger planner.

## Risks

- One night is small. Expect leads, not rates.
- The style checker is our own proxy. Tuning it on the reference app risks
  grading taste the model was shown.
- PR #12 is unverified on a real model. Until it is, the 27B runs serial.
