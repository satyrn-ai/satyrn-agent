# satyrn-agent

🚧 *This repo is under active development.*

The downstream agent from the ds4-py design: a customisation of ds4-py that
runs against a patched [ds4](https://dwarfstar.sh/) engine (dense qwen35 on Metal, DFlash speculative
decode).

## Development status

Current status: patch-series tooling and the initial typed `satyrn_agent`
package. The package implements optional DFlash bindings, session policy,
native sampling defaults, a soft think budget, and host-driven speculative
decode. Real Metal/GGUF acceptance is a separate explicit gate; portable tests
do not establish live parity.

`ds4-sync`, `ds4-export`, and
`ds4-check` are registered as devenv commands and also run standalone from
`tools/`. The patch series is now the per-model layout: `patches/common/`
(model-independent host extensions and Metal language-version pins) plus
`patches/qwen35/` (the dense qwen35 policy and implementation). The migrated
series reconstructs the same Git tree and filesystem bytes as the former flat
ten-patch bootstrap series, and the tools are exercised against the repo's own
series in addition to the test suite.

## Agent package

The package uses the ds4-py companion APIs at commit
`5c98c6ac86cafef56780c3bcbb87c3ecaef52aef`. Installing it registers eight
optional bindings through `ds4py.bindings`. Rebuild the ds4 ABI manifest after
installing or updating the package so the new probes are recorded.

```python
from pathlib import Path

import satyrn_agent

model_dir = Path.home() / "models"
config = satyrn_agent.SatyrnConfig(
    dflash=satyrn_agent.DFlashMode.AUTO,
    drafter_path=model_dir / "dflash-Qwen3.8-27B-Q4_0.gguf",
    think_budget=satyrn_agent.ThinkBudgetConfig(max_tokens=256, bias=2.0),
)

with satyrn_agent.open(
    model_dir / "Qwen3.8-27B-Q4_K_M.gguf",
    config=config,
    lib="out/libds4.dylib",
    seed=1,
) as engine:
    session = engine.session()
    session.start_chat()
    session.append_user("Explain speculative decoding briefly.")
    events = list(session.run_round(max_tokens=64))
```

The first and only `session()` call applies native sampling defaults, explicit
overrides, the optional think hook, and one resolved `auto`/`on`/`off` decode
policy. It returns ds4-py's real `Session`. See `tests/e2e/README.md` for the
real patched-engine environment and acceptance commands. M3 CLI, TUI, and
persistence integration are not part of this package slice.

For a JSON-shaped external configuration, use `config_from_dict(data)`. The
versioned contract is `schemas/satyrn-config.schema.json`; datamodel-code-generator
generates the TypedDict DTOs, and handwritten runtime validation converts them
to the frozen domain config without Pydantic models or TypeAdapter. The E2E
scenario config references the same production schema.

## Models

Use the two models together when DFlash speculative decoding is enabled. The
drafter proposes tokens, and the target verifies them before the engine
publishes them. If you set `dflash=DFlashMode.OFF` or omit `drafter_path`,
Satyrn uses the target without the drafter.

This exact pair is the validated configuration for dense qwen35 on Metal. It
combines a Q4_K_M target with a smaller Q4_0 drafter. In the recorded timing
case on an Apple M4 Max, speculative decoding took 1.034129 seconds and serial
decoding took 3.140691 seconds. The
[validation report](docs/reports/agent-package-validation.md#serialspeculative-speed)
records the 3.037x speedup and the test conditions.

`tests/e2e/corpus.json` pins the SHA-256 hash of each GGUF file.

| Role | Hugging Face repository | File | Revision | SHA-256 |
|---|---|---|---|---|
| Target | `lmstudio-community/Qwen3.8-27B-GGUF` | `Qwen3.8-27B-Q4_K_M.gguf` | `5a7da681f60570ab5b439a587e912d2e5eddb582` | `e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520` |
| Drafter | `ggml-org/Qwen3.8-27B-GGUF` | `dflash-Qwen3.8-27B-Q4_0.gguf` | `a316ea527fde32c12487be7574e2db5ac2ad2a7e` | `0a994382adf17c720c9e5d4292f57344f3b445f058d3e9d5b0f601ae7d6ca3c4` |

The target is not the fine-tuned model in `satyrn-ai/Qwen3.8-27B-py3.15`.

Download both files with the Hugging Face CLI. The `--revision` option selects
the exact repository commit.

```bash
MODEL_DIR="$HOME/models"
mkdir -p "$MODEL_DIR"

hf download lmstudio-community/Qwen3.8-27B-GGUF Qwen3.8-27B-Q4_K_M.gguf \
  --revision 5a7da681f60570ab5b439a587e912d2e5eddb582 \
  --local-dir "$MODEL_DIR"
hf download ggml-org/Qwen3.8-27B-GGUF dflash-Qwen3.8-27B-Q4_0.gguf \
  --revision a316ea527fde32c12487be7574e2db5ac2ad2a7e \
  --local-dir "$MODEL_DIR"

printf '%s  %s\n' \
  'e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520' "$MODEL_DIR/Qwen3.8-27B-Q4_K_M.gguf" \
  '0a994382adf17c720c9e5d4292f57344f3b445f058d3e9d5b0f601ae7d6ca3c4' "$MODEL_DIR/dflash-Qwen3.8-27B-Q4_0.gguf" \
  | shasum -a 256 -c -
```

The `shasum` command must report `OK` for both files.

Do not download the drafter from the current `main` revision. `ggml-org`
updated `dflash-Qwen3.8-27B-Q4_0.gguf` on 2026-11-08. The new file has a
different SHA-256 hash and fails the corpus identity check. Revision
`a316ea527fde32c12487be7574e2db5ac2ad2a7e` contains the pinned drafter.

The example under *Agent package* passes the target path to
`satyrn_agent.open()`. It passes the drafter path through
`SatyrnConfig(drafter_path=...)`.

For the live acceptance tests, map the same files to these environment
variables:

```bash
export SATYRN_TEST_MODEL="$HOME/models/Qwen3.8-27B-Q4_K_M.gguf"
export SATYRN_TEST_DRAFTER="$HOME/models/dflash-Qwen3.8-27B-Q4_0.gguf"
```

See [tests/e2e/README.md](tests/e2e/README.md) for the other required inputs and
the test command.

## Layout

- `src/satyrn_agent/` — typed downstream engine factory, optional native
  adapter, DFlash decode step, and runtime capabilities.
- `patches/` — the ds4 patch series against `antirez/ds4` at the commit in
  `upstream.pin`. Split into `common/` plus one directory per model; apply
  `common/` first, then model directories in name order.
- `tools/` — the Bash patch-series tools (`ds4-sync`, `ds4-export`,
  `ds4-check`) and their shared library.
- `docs/specs/2026-10-24-ds4-patch-series-design.md` — the governing design,
  including the §6 workflow and the migration plan.
- `.ds4/` — gitignored scratch trees (upstream cache, editable tree, pristine
  check clones, export candidates) materialized by the tools.
- `upstream.pin` — the pinned upstream URL and commit.

## Develop

devenv provides the toolchain (C, Python + uv from Nix) and registers the
three tool entry points. After cloning:

```
direnv allow    # or: devenv shell
```

See [docs/development.md](docs/development.md) for locked Python dependencies,
the prek quality gate, ShellCheck, and portable regression tests.

The commands below are available inside the devenv shell and through
`devenv shell -- <command>`.

### Sync, edit, export

```
ds4-sync --common-only          # or --model NAME, or omit to materialize every model
# edit the checked-out tree under .ds4/tree
ds4-export                      # regenerate the owned patch directory
```

`ds4-sync` materializes `.ds4/tree` from the pinned upstream and applies the
selected patch target. `ds4-export` regenerates the owned patch directory from
the linear commits recorded in the tree; it refuses dirty or unexported work
unless `--force`.

### Check

```
ds4-check                       # common + every model prefix from pristine clones
ds4-check --model NAME          # a single target
```

`ds4-check` reconstructs each selected target from a pristine clone of the
pinned upstream. Run it before committing patch changes.

### Build

Building requires an external ds4-py checkout; ds4-py is not a dependency of
this repo. Select it with `DS4PY_PROJECT`, install its environment, and expose
its `ds4py` command:

```
export DS4PY_PROJECT=/path/to/ds4-py
devenv shell -- env -u UV_PROJECT_ENVIRONMENT uv sync --project "$DS4PY_PROJECT"
devenv shell
export PATH="$DS4PY_PROJECT/.venv/bin:$PATH"
ds4-check --build
```

`ds4-check --build` runs `ds4py build --src <tree>` for each checked tree, with
the Metal backend on macOS and the CPU backend elsewhere. Pass `--backend cuda`
or set `DS4_CHECK_BACKEND=cuda` to build for CUDA. The backend is a request, not
an inference from `PATH`: the tool builds every target, and an ambient `nvcc`
must not retarget an unrelated build.

### Model-backed end-to-end gate

`tests/ds4_e2e_test.sh` is the local release gate that exercises the
migrated implementation against a real dense qwen35 model. It first reads the
GGUF metadata and requires `general.architecture=qwen35`, then materializes
the full tree into an isolated `.ds4/e2e` scratch area (never the developer's
`.ds4/tree`), runs pristine checks, builds the library through ds4-py, checks
its ABI/load, verifies live sync plans and restore, and compares deterministic
raw generation (temp 0, seed 1, fixed token limit) between `ds4py raw` and
`ds4-agent --raw`. It is read-only with respect to the tracked patches.

```
export DS4PY_PROJECT=/path/to/ds4-py
export DS4_TEST_MODEL=/path/to/dense-qwen35.gguf
devenv shell -- bash tests/ds4_e2e_test.sh
```

`DS4PY_PROJECT` selects an external ds4-py checkout; the script puts
`$DS4PY_PROJECT/.venv/bin` on `PATH` (install it with `devenv shell -- env -u
UV_PROJECT_ENVIRONMENT uv sync --project "$DS4PY_PROJECT"` as described under
*Build*). `DS4_TEST_MODEL` may be absolute or relative; the script canonicalizes
it before any materialization. It must point at a dense qwen35 GGUF whose
`general.architecture` metadata is exactly `qwen35`. Ubuntu CI continues to run
only the no-model shell suite and CPU builds; this model-backed gate is run
explicitly on a machine with the model available.
