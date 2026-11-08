# Django customer tracker: reference app design

Date: 2026-11-07

Branch: `research/overnight-domains`

Status: approved in conversation on 2026-11-07; implementation plan is the active gate.

## Goal

Give Paul's local Qwen 27B concrete examples of code written his way, plus
held-out tasks that test whether that style transfers to new behavior. This
is the reference-app part of roadmap item 1, not the typed-packet subsystem.

The app is a small Django customer tracker. Paul selected Django, the customer
domain, lightweight domain-first architecture, three example phases, three
held-out phases, and the evaluation rules below. There is no existing personal
code sample to copy: Paul's review establishes this reference style.

Context:

- [Overnight domains roadmap](../research/2026-11-07-overnight-domains-roadmap.md)
- [Research survey](../research/2026-11-07-overnight-domains-survey.md)
- [Item 0 smoke-test note](../research/2026-11-07-27b-worker-smoke-test.md)

## Evidence and limits

The session handoff reports the latest item 0 full harness result as **22
passed in 13.16s**, inside devenv. This is reported existing-fake evidence,
not a rerun in this session. The retained smoke-test note has older counts.
It does not establish app quality or model performance.

All four real-27B checks remain unverified: tool loop, native checkpoint
restore without re-prefill, FIM, and logits-based short answers. The reference
app and its CPU tests do not depend on resolving those checks.

Failed-branch/cancellation hardening remains explicitly stopped. Normal stream
exhaustion skips reconciliation; interrupted cleanup may reach native
`rewind()`. Qwen35 support is unverified, not proven broken. The handoff reports
this as [ds4-py #20](https://github.com/rochecompaan/ds4-py/issues/20); this design
does not claim a maintainer response or resolution, or authorize further work.

## Scope and non-goals

Deliverables for a later approved implementation:

- A runnable Django reference app with example tasks, code, templates, and tests.
- Three independent held-out task packages with protected solutions and grading
  tests, separate from worker-visible material.
- Explicit export manifests and leakage-boundary tests.
- A small style diagnostic checker with positive and negative fixtures.
- A documented, deferred AgentClinic Hard calibration procedure.

Not included:

- Authentication, multi-tenancy, external services, or a frontend framework.
- Typed packet schemas, packet compilation, symbol indexes, or model routing.
- Changes to ds4-py, item 0, cancellation handling, checkpoints, or decoding.
- FIM, masks, thinking policies, DFlash, or model-backed experiments.
- A generic repository/service framework or a claim that style can be fully
  judged automatically.

## Architecture and style

Use function views, plain domain objects, explicit persistence conversion,
testable helpers, and meaningful semantic aliases such as
`type FirstName = str`. Aliases communicate meaning; they are not distinct
runtime types or substitutes for validation.

The logical Django app modules are:

| Module | Responsibility | Dependencies |
| --- | --- | --- |
| `domain.py` | Small domain objects, aliases, pure rules | Python standard library only |
| `models.py` | Persistence fields, relations, database constraints | Django ORM |
| `queries.py` | ORM reads and explicit conversion to domain objects | Models and domain |
| `operations.py` | Writes and transaction boundaries; invoke domain rules | Models and domain |
| `forms.py` | Web input parsing and validation | Django forms and relevant domain rules |
| `views.py` | Thin function views coordinating requests and responses | Forms, queries, operations, Django HTTP/rendering |
| `urls.py`, templates | Routing and server-rendered presentation | Django |

Introduce modules only when a phase needs them. Use concrete functions and
objects rather than repository protocols, dependency injection infrastructure,
or a generic service layer. ORM models do not own business workflows. Domain
objects do not receive ORM instances, lazy querysets, requests, or forms.
No database access occurs during template rendering through domain objects.

Reads flow from a function view through a query, with explicit ORM-to-domain
conversion, into template context. Writes flow through form validation into an
operation, which applies domain rules and owns any necessary transaction,
then redirects after success. Keep pure rule calculations independently
testable; the view is not the business-rule implementation.

Invalid input redisplays useful errors without partial writes. Missing
customers return 404. Rejected state transitions leave stored data unchanged.
Only successful writes redirect. Database constraints complement, rather than
replace, the user-facing validation and domain rules.

## Reference phases

Each example includes a task description, a starting state, completed code,
and tests. Examples teach structure and testing discipline, not the held-out
business rules.

### E1: directory and detail

Show customer directory and detail pages using typed names, explicit conversion
from persistence to domain objects, function views, and templates. Test empty
and populated directories and missing-customer behavior.

### E2: add a customer

Add a customer through a form, a domain validation rule, and a write operation.
Show useful invalid-input feedback and confirm rejection does not persist data.
The implementation plan must give the exact field and rule contracts, not
leave those choices to the worker.

### E3: edit contact details

Update contact details while preserving customer identity and unrelated data.
Include focused tests for the successful update and rejection paths. This
completes the shared example baseline for held-out tasks.

## Held-out phases

Each held-out task has a visible task specification and starting scaffold,
plus a solution and protected grading tests that are never exported to the
worker. The task specification states every required behavior; hidden tests
do not introduce secret requirements.

### H1: search and pagination

Search and paginate customers, including stable ordering and explicitly
specified empty-result and invalid-input behavior. Tests cover page boundaries,
ordering ties, and preservation of directory/detail behavior.

### H2: follow-ups

Schedule and complete follow-ups. Pure due/overdue calculations take an explicit
clock value rather than reading the system clock. Tests cover time boundaries,
completion transitions, rejected input, and persistence.

### H3: archive customers

Archive customers while preserving their history and rejecting new follow-ups
for archived customers. Tests cover both allowed and rejected transitions and
verify that existing history is not deleted or rewritten.

### Independent starting states

Each held-out phase starts from a frozen copy of the E3 example app plus only
its required schema, data, and unfinished interfaces. It does not start from
another model attempt or a completed held-out solution.

In particular, H3 may need minimal history/follow-up schema and seeded records,
but its baseline must not contain H2's scheduling/completion implementation.
The visible H3 task can require the archive restriction on its unfinished
follow-up creation entry point without supplying H2's full workflow. H1's
solution is likewise absent from H2 and H3.

Exact fields, function signatures, pagination conventions, time boundaries,
and transition contracts belong in the written implementation plan and frozen
task specifications before coding or evaluation. They must be consistent
across scaffolds, task descriptions, reference solutions, and grading tests.

## Packaging and leakage boundary

Keep authored materials under one reference-app root, with separate example,
task-scaffold, and evaluation trees. The implementation plan selects exact
paths after checking repository conventions. Evaluation material includes
held-out solutions, grading tests, expected outputs, and checker mutation
fixtures; none belongs in a worker export.

A manifest declares:

- Distinct example and held-out task IDs.
- Exact worker-visible files for each task, without broad directory globs.
- The provenance of each starting snapshot and any allowed scaffold additions.
- Protected grading and solution paths outside each worker-visible workspace.

Build worker workspaces from an explicit allowlist into a separate directory.
Do not merely tell the worker not to read evaluation files. Do not mount or
offer the authored reference root as a worker tool root.

Tests reject overlapping example/held-out task IDs, evaluation paths or
symlinks escaping the export boundary, unexpected exported files, and known
target-solution files/content in starting snapshots. Check the actual exported
tree against its manifest, not just the manifest against itself. Review
scaffold provenance to catch solution leakage that byte comparisons cannot
establish semantically.

The architecture and general testing techniques intentionally overlap between
examples and held-out tasks. The disallowed overlap is task answers and
target-specific solution/grading material, not shared concepts or public
requirements.

This is a tested packaging/tool-access boundary, not an adversarial OS sandbox.
Executing generated Python can access host resources. Any future model-backed
work must use a separately approved isolation arrangement; this design alone
does not make it safe to run untrusted code or expose the authored checkout.

## Evaluation

### Behavioral correctness

Use pytest functions, fast pure-domain tests, database integration tests, and
Django request tests. Test invalid input and preservation of existing behavior
as well as success. Grading tests are protected from worker edits; workers may
write their own tests. Run protected tests through a host-owned entry point.

Before trusting a gate, introduce deliberate defects in disposable fixtures
and verify the relevant checks fail. Never weaken a failed assertion merely
to obtain a pass. Verify the trusted solutions pass from each frozen baseline.
Report local gate results separately from held-out grading results.

### Style diagnostics and human review

Initially check only two agreed mechanical properties:

- App routes use function views rather than class-based views.
- The domain module has no Django imports.

Use AST-aware checks with clean examples and deliberately violating fixtures.
Document the supported patterns and blind spots; these checks do not prove
absence of all coupling or indirect imports.

Human review judges whether aliases add meaning, helpers expose useful
boundaries, domain objects carry appropriate behavior, and views remain thin.
Do not turn those judgments into arbitrary naming/line-count rules or claim
that a clean diagnostic report means Paul would have written the code.

The checker is a proxy, never the oracle. Tune it on examples and dedicated
checker fixtures, not on held-out model outputs or desired hidden scores.
Freeze task requirements and checks before any deciding model run.

### Deferred external calibration

Keep AgentClinic Hard as the outside judge, separate from the Django app.
Document an unaided 27B screen of three attempts, with frozen tasks and run
settings. Record hidden-check results, invalid imports, invented APIs, and
time spent repairing those errors. Do not infer this model's headroom from
Mellum results or synthetic outputs.

No calibration is executed under this design's approval. GPU/live-model use
requires explicit approval and resolution or explicit acceptance of the
relevant entry-point safety prerequisites. Passing all three Hard attempts
would remove that benchmark's demonstrated headroom; held-out app phases would
still be a separate test, not evidence of improvement by themselves.

## Acceptance and review gates

The later implementation is ready for human review when:

- All example tasks are runnable, tested, and reviewed by Paul for style.
- Each of three held-out tasks has a frozen specification, independent
  starting state, protected solution, and passing protected checks.
- Leakage tests exercise actual exports and the H3 baseline contains no H2
  solution implementation.
- Planted behavioral defects and style violations fail their intended checks.
- Correctness scores, diagnostic findings, and human style judgments remain
  distinct in reports.
- Documentation explains local CPU validation and marks live calibration as
  deferred, with no claimed model result.

Next gate: Paul reviews this written design. Only after approval does a
separate implementation plan specify paths, dependencies, exact contracts,
tests, and commands. No app implementation starts at the design-review stage.

## Operational constraints

- Work in devenv. In this session it is available as
  `~/.nix-profile/bin/devenv`, although the initial PATH omitted it.
- No GPU or live-model use without explicit approval.
- Do not resume cancellation hardening without Paul's permission.
- Do not source `ds4-py/.envrc.local`, use OpenRouter, or publish raw artifacts.
- No commits or pushes unless Paul asks. In particular, saving this design
  does not authorize committing it.
- Leave pre-existing item 0 changes and local artifacts untouched.

## Risks and falsification

Three held-out tasks are a small screen, not a success-rate estimate. If the
27B solves them unaided with the desired style, they offer no demonstrated
quality headroom for packet compilation; harder work needs its own review.
If the domain-first examples introduce ceremony without useful separation,
Paul's review should reject them before they become teaching material.

The largest evaluation risks are leaked solutions, checker overfitting,
ambiguous task contracts, and false-green gates. Explicit exports, independent
baselines, contract freezing, planted defects, and human review address those
risks without claiming to eliminate them.