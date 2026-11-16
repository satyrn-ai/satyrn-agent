# Django house style: published practice as candidate rules (2026-11-10)

Research input for the house-style pack: "code the way my Django team would
write it", captured as something a harness can check. It is not a spec. It
merges four research passes (layout and modern Django, testing, typing and
tooling, where domain logic lives) into one rule list. Each rule is tagged by
how it can be checked, and the points where the team's stated preferences
part from published authors are marked for a decision.

**What is measured:** the tool versions and Django release facts (read from
PyPI and djangoproject.com on 2026-11-10), and the Ruff and Pyrefly behaviour
the typing pass probed in throwaway projects (scratchpad `pyrefly-probe/`,
`ruff-probe/`, not committed).
**What is conjecture:** that these rules make a small model's code closer to
the team's, and every check marked "custom" (not yet written).

## The team's stated preferences (Paul, 2026-11-10)

- Domain objects first, described in a basic, durable way.
- Flows and interactions in a recognised notation such as UML.
- Every entity and flow says how the result is checked: human, automated
  test, or other.
- Good type hints, plus semantic types named from the domain objects.
- The latest Django project standards and very modern Django throughout.
- Good tests, not coverage chasing: correct fixtures; mock only when
  necessary; careful `conftest.py`, plus a `fixtures` directory in the
  package with tests for the fixtures; unit tests and the test client first,
  Playwright and E2E last; testable code with big computations out of views;
  skinny templates.
- Published best practice (Will Vincent named as an example).
- Ruff and Pyrefly, with strong type hints that don't overdo it.

Two layers, as Paul framed them: a global **Django pack** (concepts, rules,
workflows; community-distributable) and an **in-house style pack** on top.

## Versions (read 2026-11-10)

| Item | Version |
|---|---|
| Django | 6.1.3 current (6.1 released 2026-08-05; Python 3.12–3.15); 5.2 is the LTS (5.2.19, to April 2028); 6.2 LTS due April 2027; then calendar versions ("Django 2028") |
| pytest / pytest-django | 9.2.0 / 4.14.0 |
| Ruff | 0.17.4 (0.16.0 raised the default set from 59 to 413 rules) |
| Pyrefly | 1.4.1 (Django support built in since 0.42) |
| django-stubs | 6.1.2 |

## Check tiers

- **Block:** a machine check that fails CI (Ruff, Pyrefly, an import ban, a
  custom AST check, a test).
- **Warn:** a machine check that flags candidates; a human decides.
- **Review:** human judgement only.

## Candidate rules

The tag after each title says how it is checked. "Fit" says how the rule
relates to the stated preferences: agrees, extends, or conflicts.

### Platform and layout (Django pack)

1. **Target the current Django release; plan the LTS move.** *Block:*
   `django.VERSION` test, `django-upgrade` in pre-commit. Pin `django~=6.1`
   now; move to 6.2 LTS in April 2027. Fit: agrees.
2. **One `config/` project package, one `settings.py` reading the
   environment, `pyproject.toml` with uv, flat apps.** *Block:* custom layout
   check. Only `settings.py` reads `os.environ`; nothing imports
   `config.settings` directly; settings never change at runtime outside
   `override_settings` (Adam Johnson, 2022-11-24). Fit: extends. Authors
   split on single vs split settings (Vincent and Johnson single;
   cookiecutter-django and Two Scoops split) and on the package name
   (`mysite`, `django_project`, `config`).
3. **Use the modern built-ins:** template partials (`page.html#row`, core
   since 6.0) instead of `django-template-partials`; `django.tasks` with a
   real backend; the built-in CSP middleware (report-only first);
   `TextChoices`/`IntegerChoices`; `pathlib`; `MAILERS` (6.1). *Block:*
   dependency bans, `django-upgrade`, Ruff `PTH`; `check --deploy`. Fit:
   extends.
4. **6.1 ORM idioms:** `fetch_mode(FETCH_PEERS)` for N+1;
   **`FETCH_RAISE` in tests** to catch lazy loads you didn't plan; name
   relations in `select_related()`. *Block:* test fixture setting
   `FETCH_RAISE`; custom check for argument-less `select_related()`. Fit:
   extends.
5. **Async views only for I/O fan-out or streaming.** *Review.* Fit: neutral.

### Views, templates and where logic lives

6. **Class-based views, chosen for testability and logic isolation**
   (Paul, 2026-11-10). Use Django's generic views (`ListView`, `DetailView`,
   `FormView`, `CreateView`, `UpdateView`) and put each concern in its
   documented hook (`get_queryset`, `get_context_data`, `form_valid`,
   `get_success_url`). Test a hook directly: build a request with
   `RequestFactory`, call `view.setup(request, **kwargs)`, then call the
   method (Django's "Testing class-based views" docs). Keep mixins few and
   project-owned. *Block:* custom AST check that every view in `views.py` is
   a class-based view (admin and DRF excepted); Ruff `DJ003`. *Review:*
   mixin use. Sources: Will Vincent (learndjango, "FBV vs CBV", 2026-04-16),
   who starts with generic class-based views. Fit: agrees. **Conflicts with**
   Django's design philosophies, Luke Plant and Carlton Gibson, who favour
   function views. **For a small model:** a class-based view puts logic in
   inherited hooks, which is more indirection to trace; but each hook has a
   fixed name and signature, which a packet can name and a skeleton can
   prefill.
7. **A view is an HTTP adapter:** its hooks parse with a form, call one
   operation or query function, build the context, and render or redirect.
   No model writes, `.save()` or business loops in view code. *Block:*
   custom AST check for `.save(`, `.delete(`, `.objects.create(`,
   `.update(` and model attribute assignment in views; tighter Ruff
   `C901`/`PLR0915` for `**/views.py`. Every camp agrees (HackSoft, Bennett,
   Plant, Gibson). Fit: agrees.
8. **Writes in named operations, reads in named queries.** Keyword-only,
   typed functions named `<entity>_<action>`; no business logic in `save()`,
   signals, forms or serializers. HackSoft calls these services and
   selectors; the reference app calls them `operations.py` and `queries.py`.
   *Block:* import contract: only operations, queries, admin, forms and tests
   import `models`. Fit: extends. **Conflicts with Bennett**, who puts logic
   in managers and querysets.
9. **Skinny templates.** Templates only branch and loop over values computed
   beforehand; context for a group of pages comes from plain helper
   functions; filters and tags only format and never query; components use
   partials or inclusion tags. *Block:* pytest-django
   `--fail-on-template-vars`; no model imports in `templatetags/`. *Warn:*
   template nesting limits; `django_coverage_plugin` for templates no test
   renders. *Review:* the templates. Fit: agrees.
10. **A Django-free domain package.** Entities, value objects and rules in
    `<app>/domain.py` as frozen dataclasses and pure functions, mapped at one
    seam (`_to_domain()` next to the queries). *Block:* Ruff `TID251` banning
    `django` with a negated per-file ignore, so the ban applies only to the
    domain package (verified in the probe); or an import-linter `forbidden`
    contract, which can only ban the root package `django`, not
    `django.db`. Sources: Percival and Gregory, Winterbottom, Gibson (April
    2026, once models overload). Fit: agrees. **Conflicts with mainstream
    Django**, which is Active Record: no mainstream Django author keeps a
    separate domain layer from the start. Even Cosmic Python's Django
    appendix calls the mapping "a lot of work".
11. **Layers enforced in CI, with a burndown list.** Import-linter `layers`
    (views → operations/queries → domain) and `independence` between apps;
    known violations listed and counted down. *Block.* Fit: extends.

### Types (in-house pack)

12. **Identifiers use `NewType`; descriptive names use `type` aliases;
    concepts with rules become value objects.** `CustomerId =
    NewType("CustomerId", int)` makes Pyrefly reject a swapped or bare ID
    (probe: `bad-argument-type`). `type FirstName = str` documents but is
    **not** checked as distinct (probe: a plain `str` passes). Money, email
    or a date range become `@dataclass(frozen=True, slots=True)` with
    validation. *Block:* Pyrefly; custom check flagging `*_id: int` in the
    domain. *Review:* alias vs `NewType` vs value object. **Decided (Paul,
    2026-11-10): identifiers use `NewType`.** Fit: conflicts with the
    reference app, whose `type CustomerId = int` gives no protection.
    `NewType` is a no-op at runtime, so callers passing a bare `int` still
    run; only the type checker objects. Authors disagree: Beránek recommends
    `NewType`; a Cosmic Python footnote dislikes it.
13. **Annotate every signature in application code; not obvious locals,
    tests or migrations.** *Block:* Ruff `ANN` with `mypy-init-return`,
    `suppress-dummy-args`, `allow-star-arg-any`; per-file ignores for tests
    and migrations. `object` or a `Protocol` over `Any` in the domain
    (`ANN401`). Fit: agrees ("strong but not overdone").
14. **Generic managers and querysets; declare cross-file reverse accessors.**
    Pyrefly has no app-registry plugin: cross-file reverse relations give
    `missing-attribute` and `.annotate()` fields are `Unknown` (probe).
    Declare `articles: RelatedManager[Article]`; map annotated rows into
    domain dataclasses. Needs `django-stubs-ext`. *Block:* Pyrefly. Fit:
    extends. mypy with the django-stubs plugin is still more precise here;
    Pyrefly trades that for zero setup.

### Tooling (in-house pack)

15. **Ruff: keep the 0.16+ defaults and add `B`, `SIM`, `C4`, `PT`, `DTZ`,
    `RUF`, `ANN`, `DJ`, `TID251`; ignore `RUF012`; leave `TC001`–`TC003`
    off; format with defaults plus `docstring-code-format`.** Only seven
    `DJ` rules exist (DJ001, 003, 006, 007, 008, 012, 013). `DTZ` flags
    naive datetimes. *Block.* Fit: agrees.
16. **Pyrefly: `default` preset project-wide; a stricter sub-config for the
    domain package (`implicit-any`, `missing-override-decorator` as errors,
    `explicit-any` as a warning); `unused-ignore` as an error.** `strict`
    project-wide would flag every Django override. *Block.* Fit: agrees.

A starting `pyproject.toml` block for 15 and 16 was verified in the typing
probe; carry it into the pack when it is written.

### Tests (in-house pack)

17. **Fixtures do one thing, tear down with `yield`, use the narrowest
    scope.** *Block:* Ruff `PT001`, `PT003`, `PT020`–`PT023`; custom
    allowlist for `module`/`session` scope. Fit: agrees.
18. **Data from typed factory functions wrapped as fixtures** ("factories as
    fixtures"); factory_boy only for deep model graphs. *Review.* Fit:
    extends.
19. **A package fixtures module loaded from the root conftest** with
    `pytest_plugins`; conftest files stay small; autouse only for global
    guards. *Block:* `pytest_plugins` only in the root conftest; autouse
    allowlist. Fit: extends. **Naming clash:** Django's `loaddata` already
    uses `<app>/fixtures/`; `<app>/testing/` avoids it. Shipping fixtures in
    the package brings test-only imports into it.
20. **Fixtures have tests.** Plain helper functions get unit tests; each
    public fixture gets one contract test (saved, `full_clean()` passes).
    *Block:* custom check that every fixture is requested by a fixture test.
    Fit: the team's own rule; no published author prescribes it.
21. **Database access explicit and fast:** rely on pytest-django's database
    block; `db` in fixtures; `transactional_db` only for transaction
    behaviour (prefer `django_capture_on_commit_callbacks`); MD5 hasher and
    `InMemoryStorage` in test settings. *Block:* banned-api on
    `django_db_blocker` outside conftest; a `--durations` budget. Fit: agrees.
22. **Fakes and real objects; mock only thin wrappers you own, at the
    boundary.** Use Django's fakes (`mailoutbox`, `settings`, locmem cache,
    `InMemoryStorage`, `tmp_path`, `monkeypatch.setenv`). *Block:* Ruff
    `TID251` on `unittest.mock` and `pytest_mock` with an allowlist; `PT008`.
    Fit: agrees.
23. **Views through the test client; assert behaviour, not markup:** status,
    redirects, `response.context`, `assertContains` for key content,
    `reverse()` for paths; `RequestFactory` when middleware doesn't matter.
    *Warn:* custom check for whole-HTML comparisons. Fit: agrees.
24. **Pyramid:** E2E (`live_server`, Playwright) only under `tests/e2e`,
    marked and deselected by default, about one per critical journey.
    *Block:* `--strict-markers`; those fixtures only in `tests/e2e`. Fit:
    agrees.
25. **One behaviour per test**, Arrange-Act-Assert, named after the
    behaviour, `parametrize` instead of loops. *Block:* Ruff `PT006`,
    `PT007`, `PT011`, `PT012`, `PT014`, `PT018`; a statement cap. Fit: agrees.
26. **Coverage as a signal:** branch coverage, a ratcheting `fail_under`,
    tests included in coverage, every `# pragma: no cover` reviewed.
    *Block:* coverage in CI. Fit: agrees. Adam Johnson aims for 100%.

### Specs (method)

27. **Entities first, then flows, every claim tagged with its check.**
    Paul (2026-11-10): something simpler than UML is fine for flow. So:
    - **Entities:** a short list per entity: its fields with their semantic
      types, its invariants, and how each invariant is checked.
    - **Flows:** a numbered list of steps per use case (who acts, which
      operation or query runs, which entity changes), not a diagram.
    - **Status fields:** a transition table (from, event, to, guard).
    - **Checks:** each claim tagged `[test: path::name]`, `[contract: name]`
      or `[review]`.
    *Block (proposed, not sourced):* a test that reads the transition table
    and compares it with the code's transitions; a check that every
    `[test: ...]` tag names a test that exists. An ORM diagram can still be
    generated deterministically (`django-model-info` `modelgraph -f
    mermaid`) if one is wanted. Fit: extends. No published Django practice
    pairs specs with UML or with check tags; only diagram generators exist.

## How the reference app compares today

`references/customer-tracker` already follows rules 2, 7, 8 and 10 in
spirit: a `config/` package with one settings file; thin typed views;
`operations.py` for writes and `queries.py` for reads with `_to_domain()`;
a `domain.py` of frozen dataclasses, `type` aliases and `RuleViolation`.
Gaps against this list: **function views rather than class-based views
(rule 6)**; Django 5.2 rather than 6.1; `type CustomerId = int` rather than
`NewType`; no Pyrefly, import contract or `DJ`/`PT`/`ANN` rules; no package
fixtures module or fixture tests; no entity lists, flow steps or check tags
in the briefs. The roadmap's intent section also says "function views";
it predates Paul's 2026-11-10 preference.

## Decisions for Paul

1. **Domain layer from the start, or extracted when models overload?**
   Every author who keeps a separate domain calls it heavy in Django; Gibson
   now adopts it only once models overload.
2. ~~**`NewType` for identifiers?**~~ Decided 2026-11-10: yes (rule 12).
   Also decided: class-based views (rule 6), and flows captured as numbered
   steps and transition tables rather than UML (rule 27).
3. **Fixtures directory name:** `fixtures/` as stated, or `testing/` to avoid
   Django's `loaddata` directory.
4. **Settings and package name:** one `settings.py` and `config/`, as in the
   reference app?
5. **Type checker:** Pyrefly with its Django gaps (cross-file reverse
   relations, `annotate()`), or mypy with the django-stubs plugin for
   precision.
6. **Which rules block and which only warn** for a model's output, as
   against a person's.

## Fit for a small local model

The rules that suit the 27B best are those with one explicit place per
role and predictable names: the view as adapter (7), `<entity>_<action>`
operations and queries (8), skinny templates with helper context (9), and
domain-named types (12). Each has a block-tier check. Class-based views
(6) add inheritance a small model has to trace, but their hooks are fixed
names with fixed signatures, so a compiled packet can name the hook and
prefill its signature, and the model writes only the body. The heavy
patterns (unit of work, project-wide mixin stacks, signals, manager chains)
add indirection without that benefit.

## Sources

Layout and modern Django: djangoproject.com download page and release notes
5.2, 6.0, 6.1; docs.djangoproject.com/en/6.1/misc/design-philosophies/;
learndjango.com (Vincent; tutorials updated 2026-04); adamj.eu (2022-11-24
settings patterns; 2025-12-03 what's new in 6.0; 2026-10-16); cookiecutter-django
(commit 2026-11-09); spookylukey.github.io/django-views-the-right-way/.

Domain logic: github.com/HackSoftware/Django-Styleguide;
b-list.org/weblog/2020/mar/16/no-service/ and /mar/23/still-no-service/;
cosmicpython.com (chapters 1–3, 5, epilogue, Django appendix);
codeinthehole.com/lists/why-your-models-are-fat (2017);
noumenal.es/stack-report (Gibson, 2024-06-30, 2024-07-31, 2026-04-12);
blog.europython.eu Kraken monolith post (2023-07-11);
django-model-info.readthedocs.io.

Testing: docs.pytest.org (fixtures, plugins; 9.2); pytest-django.readthedocs.io
(database, helpers, usage; 4.14); Django 6.1 testing docs; obeythetestinggoat.com
(updated 2025-10-27); hynek.me/articles/what-to-mock-in-5-mins/ (2022);
martinfowler.com/articles/mocksArentStubs.html; nedbatchelder.com (2012, 2020);
adamj.eu (2014, 2019, 2020, 2023, 2024); learndjango.com testing tutorial
(2026-10-09); Okken, *Python Testing with pytest*, 2nd ed. (2022, read via
snippets only); Google Testing Blog (2014-04-14).

Typing and tooling: pyrefly.org/en/docs/django/ and configuration;
github.com/facebook/pyrefly releases (1.3.0, 1.4.0); github.com/typeddjango/django-stubs;
astral.sh/blog/ruff-v0.16.0; docs.astral.sh/ruff/rules and default-rules;
typing.python.org aliases spec; kobzol.github.io (2023-05-20);
hynek.me/talks/abstractions/ and /design-pressure/ (2025-05-16);
adamj.eu/tech/2021/05/07; Google Python style guide §3.19; Zulip and
cookiecutter-django `pyproject.toml` (read 2026-11-10).

## Unverified

- Two Scoops of Django's current edition and its view stance.
- Boost Your Django DX's last confirmed update is 2024-11-18, before ruff
  and uv.
- Okken's book was read through snippets; an Adam Johnson podcast
  transcript (2025-07-22) was unreadable.
- Whether Ruff `TID251` banning `django.db` also blocks `django.db.models`;
  Tach's Django support.
- How noisy Pyrefly's `missing-override-decorator` is on real Django code.
- Pyrefly's Django docs page conflicts with its 1.3.0 release notes on
  reverse relations.
- ty was not assessed.
