# Typed packet v0

`typed-packets` is a standalone Python package for validating one hand-authored
JSON packet per plan task. It checks the packet shape, declared file operations,
and only the interfaces explicitly referenced by that packet. It does not
execute application code, tests, or gate commands.

## Install and verify

The project targets Python 3.12 or newer and has no runtime dependencies. Its
development dependencies are pytest and Ruff. From the repository root, use
the repository's `devenv` and the package's own lockfile:

```bash
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/typed-packets pytest packages/typed-packets/tests
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/typed-packets ruff check packages/typed-packets
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv run --locked --project packages/typed-packets ruff format --check packages/typed-packets
```

## Public API

```python
from pathlib import Path

from typed_packets import SourceRoot, ValidationContext, validate_document

workspace = Path("/path/to/workspace")
context = ValidationContext(
    workspace=workspace,
    roots=(
        SourceRoot(
            root_id="workspace",
            path=workspace,
            kind="project",
            import_base="app",
        ),
    ),
)
report = validate_document(packet_json, context)
```

The package also exposes `decode_packet`, `encode_packet`, `build_index`,
`validate_packet`, and the frozen packet, context, index, diagnostic, and report
value objects. `decode_packet` raises `PacketDecodeError`; `validate_document`
converts packet decoding errors into invalid reports.

`ValidationContext` is trusted caller configuration, not packet data. Supply a
`SourceRoot` with ID `workspace` and add named project, dependency-source, or
stub roots as needed. `import_base` is a canonical directory path relative to
the root; `module_prefix` optionally prefixes discovered module names. Project
roots must resolve inside the workspace. Dependency and stub roots are
explicitly authorized read-only inputs. `.py` is indexed by default; include
`.pyi` in a root's `suffixes` only when that static source is explicitly
authorized. Distinct roots that provide the same requested module remain
ambiguous rather than being selected by search order.

`build_index` reads source bytes and parses them with `ast`; it does not import
modules, evaluate annotations/defaults/decorators, initialize Django, consult
`sys.path`, or install dependencies. It records direct top-level and
class-qualified declarations, assignments, imports, relative-import levels,
callable signatures, and semantic Python 3.12 `type` aliases. Function-local
definitions are not importable targets.

## Packet contract

Packets are UTF-8 JSON objects with `schema_version: 0`. All top-level fields
are required:

- `packet_id` and `task` identify the task.
- `readable_files` and `file_changes` declare exact workspace-relative file
  access and `create`, `modify`, or `delete` operations.
- `consumes` identifies existing symbols by `{root_id, path}` and qualified
  name. An optional `expected_signature` is a full `def` or `async def` header,
  for example `def lookup(key: str, *, strict: bool = False) -> Item:`. It is
  parsed and compared structurally: parameter names/order/kinds, annotations,
  defaults, async kind, and return annotation must match; formatting and source
  locations do not matter.
- `produces` describes planned definitions with an operation, kind, qualified
  name, and a declaration. Function and class entries use a header; type
  aliases use a complete `type Name = ...` statement. A produced `create` may
  be in a new file or be absent from an existing modified file. A produced
  `modify` must have a current binding in a modified file. Replacement
  declarations are not compared as current signatures.
- `imports` declares the importer's path, absolute module name, nullable
  imported name and alias, and `existing` or `planned` target. Planned imports
  are checked only against this packet's explicit produced declarations.
- `tests` holds complete proposed Python test-file text and must match a
  writable file change. The text is parsed but never installed or run.
- `gates` contains an argument vector, existing workspace-relative `cwd`, and
  explicit `before`/`after` exit-code expectations. It is a later execution
  specification, not evidence that the gate runs or fails for a particular
  reason.
- `known_facts`, `acceptance_criteria`, and `preserved_behavior` remain prose
  claims. Every report exposes them as `unverified_requirements`, including
  when the structural status is valid.

Duplicate JSON keys, unknown fields, non-finite numbers, wrong primitive
types, blank required strings, malformed declarations, and conflicting file,
symbol, test, or import declarations are rejected. Paths are checked before
normalization; absolute paths, traversal, globs, backslashes, symlink
components, wrong file kinds, collisions, and file/ancestor conflicts are
invalid.

## Results and limitations

`ValidationReport.status` is `valid`, `invalid`, or `inconclusive`; `ready` is
true only for `valid`. Diagnostics have stable codes, outcomes, JSON Pointer
fields, messages, and optional source path, symbol, and line. Invalid findings
take precedence over inconclusive ones, and either blocks readiness. Reports
are deterministically ordered and fingerprint the canonical packet, configured
roots, parser version, and indexed source bytes. `validate_packet` rebuilds the
index to reject context mismatches and stale source snapshots.

A uniquely mapped, fully inspected module with a definitely absent binding is
invalid. Conditional or competing definitions, dynamic/wildcard exports,
unavailable or unsupported source, import cycles, decorators that may change
an interface, inherited/generated attributes, and ambiguous module providers
are inconclusive when they affect a requested reference. Two decorators, bound
by unconditional top-level imports, count as preserving the interface: the
standard library's `dataclass` on a class and Django's `transaction.atomic` on a
function. Unrelated unresolved
imports do not invalidate a directly proven binding. Native or unavailable
dependencies require explicitly configured static stubs; there is no runtime
probing fallback.

File access declarations are not a sandbox and do not prevent hostile
concurrent filesystem changes. The validator does not infer types or arbitrary
call compatibility, execute gates, write skeletons, install tests, call a
model, retry work, or certify behavioral correctness. A valid report means
only that the declared structure and supported static references passed; the
later execution workspace must revalidate its own inputs.

## Examples

The hand-authored `examples/customer_tracker/E1.json`, `E2.json`, and
`E3.json` packets validate against their corresponding public
`references/customer-tracker/examples/E*/start/` workspaces with `app/` as the
import base. E2 spans the domain rules, a new operation module, and a test
file. `examples/plain_python.json` demonstrates the same contract without a
Django dependency. The examples and fixture contain no held-out solutions or
protected tests.