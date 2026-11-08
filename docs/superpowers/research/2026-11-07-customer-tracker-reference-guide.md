# Django customer-tracker reference guide

This guide describes the isolated reference project at
`references/customer-tracker/`. It demonstrates a small Django app with
function views, frozen plain-Python domain objects, explicit ORM conversion,
and focused tests. It does not modify the ds4 patch tooling or implement typed
packets.

## Contents and evaluation boundary

- `app/` is the completed E3 example app: directory/detail, create customer,
  and contact editing.
- `examples/E1`–`E3` contain task descriptions and frozen start/completion
  snapshots. E1 teaches directory/detail, E2 creation, and E3 contact editing.
- `tasks/H1`–`H3` contain visible task specifications and independent starts:
  search/pagination, follow-ups, and archiving.
- `evaluation/` contains held-out solutions, protected tests, and checker
  fixtures. These files are not included in worker exports.
- `host_tools/` builds exact path/hash manifests, exports allowlisted files,
  runs host-owned baseline and protected tests in a host-controlled subprocess,
  and reports mechanical style findings.

The exporter rejects an existing destination, unsafe paths, symlink sources,
changed source hashes, and output trees that differ from the manifest. The
grader collects the frozen E3 regression tests and protected task tests from a
host-owned temporary test directory. It supplies its own pytest configuration,
disables automatic plugin loading, and never collects tests or `conftest.py`
from the worker workspace. Protected solutions, tests, and E3 regression tests
are checked against hashes before and after grading.

`evaluation/protected_fingerprints.json` is independent of the worker manifest.
It pins the E3 baseline, each held-out start, solution and protected test, plus
the trusted baseline tests. It records exact hashes for solution-only files and
AST fingerprints for solution-only function/class definitions; definitions
already present in E3 or that task's own start are explicitly shared. Both
manifest rebuilding and export reject these protected fingerprints, so changing
worker manifest hashes alone cannot approve copied solution content. These
checks detect exact copies and matching definitions, not obfuscation or semantic
equivalents. Any intentional change to pinned sources requires a separate
review and update of the fingerprint policy; provenance refresh does not update
it.

These are packaging and workflow checks, **not an OS sandbox**: executing
arbitrary generated Python can access host resources. Do not treat an exported
workspace as safe isolation for an untrusted agent.

## CPU-only development

The repository's devenv supplies Python and uv. Use the isolated project and
retain the lockfile:

```bash
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv sync --project references/customer-tracker
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker pytest references/customer-tracker/app/tests references/customer-tracker/tests -q
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker python references/customer-tracker/app/manage.py check
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker python references/customer-tracker/app/manage.py makemigrations --check --dry-run
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker ruff check references/customer-tracker
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker ruff format --check references/customer-tracker
```

Each snapshot should be tested in its own process and temporary database, so
Django settings and imported modules cannot leak between phases. The three
trusted held-out solutions are also exercised by the host tests. The observed
CPU proxy runs previously recorded 41 combined E3/H1 tests, 45 E3/H2 tests,
41 E3/H3 tests, and 23 host export, baseline, style, and protected-grader
tests. After adding host-collection isolation and leakage regressions, the full
isolated project suite passes 56 tests. These are local implementation checks,
not evidence of model capability.

After intentionally changing snapshots or protected evaluation files, review
and explicitly update `evaluation/protected_fingerprints.json` if any pinned
source changes. `refresh_provenance.py` does not update the independent
fingerprint policy. Then refresh provenance, rebuild the exact worker allowlist,
and review all resulting diffs:

```bash
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker python references/customer-tracker/host_tools/refresh_provenance.py
~/.nix-profile/bin/devenv shell -- env -u UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS=never uv run --locked --project references/customer-tracker python references/customer-tracker/host_tools/build_manifests.py
```

The output is `references/customer-tracker/manifests/worker_files.json`.
`host_tools.export.export(task_id, destination)` accepts only a task ID present
in that manifest and a destination that does not already exist. Example tasks
may include their completed teaching snapshot; held-out exports contain only
the task text, provenance, and start workspace. Protected solutions, protected
tests, checker fixtures, and host tools are excluded.

## Diagnostics and review

The AST style diagnostic currently checks two mechanical conventions:

- direct Django imports in `app/crm/domain.py`, including aliased imports;
- class-based view registrations using `.as_view()`, including supported local
  route imports, aliases, and assignments in `crm.views`.

Unresolved, cyclic, or dynamic route expressions are reported as inconclusive,
not clean. The checker cannot detect indirect Django imports, dynamic
registrations that evade its supported patterns, or whether the domain model
and helper boundaries are useful. It deliberately does not score alias count,
line count, or domain quality. Behavioral tests, diagnostic findings, and
manual style review must remain separate. Human review of whether this is
Paul's preferred style and whether the held-out scaffolds are semantically
independent is still required.

The H3 start has a minimal follow-up table and seeded history, but no H2
scheduling, completion, or status implementation. Its archive and
follow-up-creation operations coordinate through the same customer-row lock
inside transactions where the database supports `select_for_update`. SQLite
tests do not establish production concurrency guarantees.

## Deferred AgentClinic Hard calibration

Do not run live-model or GPU calibration under this reference project without
separate explicit approval. When approved, use three **unaided** attempts with
frozen task text, model/runtime settings, and scoring criteria. Keep hidden
scores unavailable to the model. Record pass/fail results, invalid imports,
invented APIs, and repair time for each attempt; preserve the raw score and
manual style judgment as separate results. Do not tune the checker against
those held-out outputs after seeing them. This procedure remains deferred and
has not been executed.