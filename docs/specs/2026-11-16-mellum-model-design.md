# Mellum 2.1 model support design

| | |
| --- | --- |
| Date | 2026-11-16 |
| Status | Draft for review; this specification does not approve implementation |
| Spec PR branch | `docs/mellum-design` |
| Implementation branch | `feat/mellum-support` in `satyrn-ai/satyrn-agent` |
| Implementation owner | Paul Everitt ports; Koudai Aono reviews |
| Engine reference | `pauleveritt/ds4-mellum` `mellum` at `d2d9338b9b28bd8a51b0f938f2dc1dea33954493` |
| Satyrn engine pin | `antirez/ds4` `5379c1c9ac315f1540371b06a3db88491d4059ff` |
| Harness reference | `ds4-py` `95d52cbb9f189c9a940e777e9fab6baa15eac622`, also used by satyrn-agent PR #25 |

## 1. Intent

Run JetBrains' Mellum 2.1 12B-A2.5B thinking coding model through the
`satyrn-agent` command on Metal, including Macs that cannot hold the Qwen 27B
model. Preserve the existing ds4-py agent, tools, session history, persistence,
TUI, slash commands, and footer. Do not create a second agent or server.

The result must be small enough for Paul to plan with Kimi K3 and implement
with DeepSeek V4 Flash. Each task below has one deliverable and an executable
acceptance check. This document is the spec; Paul writes the implementation
plan from it before changing product code.

### Goals

1. Add `patches/mellum` on the existing pin and keep the full model order
   `pin -> common -> mellum -> qwen35`.
2. Reuse Mellum's Metal graph, Q8_0 and MXFP4_MOE support, and SSD streaming.
3. Add generic Hermes support to ds4-py where the current harness cannot
   represent Mellum. No Satyrn identifiers or policy enter ds4-py.
4. Present ds4-py's existing workspace operations with both its native tool
   names and a Pi-compatible profile, then choose Mellum's default from a
   measured comparison with a declared `n`.
5. Preserve useful Satyrn behavior without pretending that a Mellum DFlash
   drafter or native session payload exists.
6. Establish resident and streamed memory/performance gates at 36, 24, 16,
   and 8 GB.

### Non-goals and anti-goals

- No implementation in the spec PR.
- No CUDA, ROCm, CPU-inference, distributed, multi-GPU, or multi-session
  server work. Metal is the only supported backend.
- No port of `ds4-agent`, `ds4-server`, their C Hermes parsers, or the C Pi
  tool implementations. They are references for ds4-py, not a second runtime.
- No new quant formats. Q8_0 and MXFP4_MOE are the only accepted GGUFs;
  Q4_K_M and mixed expert formats remain errors.
- No Mellum DFlash drafter, speculative decoding, native KV/file payload, or
  in-memory snapshot implementation. M4 native compaction is therefore not a
  Mellum acceptance feature.
- No upstream pin migration in this work.
- No claim that a model-free test proves live numerical or tool-use parity.

## 2. Evidence and current state

Evidence roots used below are `~/work/ds4-mellum` at the reference commit,
`~/work/ds4-py` at the harness reference commit, the installed
`pydantic-ai-harness==0.59.0` package under
`~/work/ds4-py/.venv/lib/python3.14/site-packages/pydantic_ai_harness/`, and
this repository. All baseline commands used `./ds4`; none used `--raw-prompt`.

### 2.1 What ds4-mellum changes against its own upstream base

The merge base is not the older Satyrn pin. The branch started at `5379c1c`
but later merged upstream through `c97964b`:

```console
$ cd ~/work/ds4-mellum
$ git fetch https://github.com/antirez/ds4.git main
$ git rev-parse HEAD FETCH_HEAD
d2d9338b9b28bd8a51b0f938f2dc1dea33954493
b3f50180ec2c7324892be1f50bc83555ccb8d5e7
$ git merge-base HEAD FETCH_HEAD
c97964b8aa77034a8e17afb10ca7a686c40ab511
$ git merge-base HEAD 5379c1c9ac315f1540371b06a3db88491d4059ff
5379c1c9ac315f1540371b06a3db88491d4059ff
$ git rev-list --left-right --count c97964b...HEAD
0       840
$ git rev-list --count --no-merges c97964b..HEAD
833
$ git diff --shortstat c97964b..HEAD
464 files changed, 51593 insertions(+), 483 deletions(-)
```

`MELLUM.md:1-5` records the original `5379c1c` starting point. The current
merge-base result governs the port. Reconstruct topics from `c97964b`, then
rebase their content onto Satyrn's `5379c1c`; do not cherry-pick all 840 commits
or move the pin.

These commands reproduce the area counts:

```console
$ git diff --shortstat c97964b..HEAD -- ds4_mellum_*.inc ds4.c ds4.h ds4_gpu.h ds4_metal.m metal/
13 files changed, 5398 insertions(+), 139 deletions(-)
$ git diff --shortstat c97964b..HEAD -- ds4_mellum_stream.c ds4_mellum_stream.h
2 files changed, 193 insertions(+)
$ git diff --shortstat c97964b..HEAD -- ds4_cli.c ds4_server.c ds4_server_hermes.inc ds4_server_mellum_template.inc ds4_help.c ds4_json.h
5 files changed, 983 insertions(+), 298 deletions(-)
$ git diff --shortstat c97964b..HEAD -- ds4_agent.c ds4_agent_hermes.inc ds4_agent_mellum_prompt.inc ds4_agent_pi_tools.inc ds4_tool_text.h
4 files changed, 2352 insertions(+), 36 deletions(-)
$ git diff --shortstat c97964b..HEAD -- tests/
81 files changed, 17957 insertions(+)
$ git diff --shortstat c97964b..HEAD -- Makefile
1 file changed, 194 insertions(+), 8 deletions(-)
```

The read sets below include `ds4_help.c` and `ds4_tool_text.h` for context,
although those two files have no diff. The divergence by requested area is:

| Area | Evidence and size | Contents to understand |
| --- | --- | --- |
| Mellum graph and kernels | `git diff --shortstat c97964b..HEAD -- ds4_mellum_*.inc ds4.c ds4.h ds4_gpu.h ds4_metal.m metal/`: 13 files, +5,398/-139 | Config/binding and memory plan; tokenizer; exact and tiled graph; sliding/full attention; 64 routed experts with top 8; fused decode; `metal/mellum.metal`; guarded changes to `metal/qwen4.metal` |
| Streaming | Dedicated `ds4_mellum_stream.[ch]`: 2 files, +193; integration also touches `ds4.c`, `ds4.h`, `ds4_metal.m`, and `ds4_mellum_graph.inc` | Slot sizing, uncached reads, stop/resume decode, overlapped loads, grouped layer-major prefill, Q8 and MXFP4 slot sizes |
| CLI and server | `ds4_cli.c ds4_server.c ds4_server_hermes.inc ds4_server_mellum_template.inc ds4_help.c ds4_json.h`: 5 files, +983/-298 | CLI speed/cap reporting; Hermes output parsing; Mellum chat rendering and tool tail; server refusal rules and rewind reuse. Only CLI/host behavior is in this port's scope |
| Agent | `ds4_agent.c ds4_agent_hermes.inc ds4_agent_mellum_prompt.inc ds4_agent_pi_tools.inc ds4_tool_text.h`: 4 files, +2,352/-36 | Hermes parser and bounded quote repair; Pi schemas/preamble; `read`, `write`, `edit`, `bash` behavior and result texts; grouped tool responses. Reference only for the ds4-py companion |
| Tests | `tests/`: 81 files, +17,957 | Generated tokenizer/chat fixtures, model-free kernels/frontend/stream tests, oracle and fast-path checks, benchmark runners, real-use grading |
| Build | `Makefile`: +194/-8 | Mellum objects, test targets, `.inc` prerequisites |

Useful entry points are `ds4_mellum_config.inc`,
`ds4_mellum_plan.inc:8-214`, `ds4_mellum_graph_alloc.inc:47`,
`ds4_mellum_graph.inc:410-531`, `metal/mellum.metal`,
`ds4_agent_hermes.inc:1-634`, `ds4_agent_mellum_prompt.inc:1-70`,
`ds4_agent_pi_tools.inc:1-1103`, `ds4_server_hermes.inc:1-152`, and
`ds4_server_mellum_template.inc:190-274`. `MELLUM.md` and `ROADMAP.md` are the
measurement and known-divergence ledgers, not optional background.

### 2.2 What the Satyrn pin already has, and what conflicts

SSD streaming exists as reusable infrastructure, not as a Mellum engine.
At the pin, `docs/SSD_STREAMING.md:6-11` describes a bounded routed expert
cache and explicitly limits Metal support to DeepSeek and GLM.
`ds4_ssd.h:17-36` provides byte-budget parsing, automatic cache planning, and
memory locking. In contrast, Mellum has a model-specific stop/resume scheduler
and 64-expert minimum slot rule in `ds4_mellum_stream.h:11-69` and
`ds4_mellum_stream.c:16-112`.

The reference branch leaves `ds4_ssd.c` and `ds4_ssd.h` unchanged from its
merge base:

```console
$ git diff --stat c97964b..d2d9338 -- ds4_ssd.c ds4_ssd.h
# empty
$ git diff --shortstat 5379c1c..c97964b -- ds4.c ds4.h ds4_ssd.c ds4_ssd.h ds4_metal.m docs/SSD_STREAMING.md
3 files changed, 167 insertions(+), 25 deletions(-)
```

Therefore reuse the pin's CLI parsing, byte-budget, and memory helpers where
they fit, but port Mellum's scheduler and graph integration. Do not substitute
the generic GLM/DeepSeek execution path and do not add a second copy of
`ds4_ssd.[ch]`.

| Existing series | Overlap | Required resolution |
| --- | --- | --- |
| `common/0001` host extensions | Adds `ds4_engine_sampling_defaults`; Mellum adds its own defaults and `ds4_engine_is_mellum` | Extend the one existing API. Native Mellum defaults are temperature 1.0, top-p 1.0, top-k 0, min-p 0 (`ds4.c:73808-73820`; `ds4.h:312-317`) |
| `common/0001` payload predicate | It returns true for every non-distributed qwen4 (`patches/common/0001...patch:20-22`); Mellum is also qwen4 but all payload/snapshot operations refuse | `patches/mellum` must make the predicate false for Mellum and test stripped save/rendered switch. This is a semantic conflict, not optional hardening |
| `common/0002-0003` Metal versions | `ds4_metal.m` also changes substantially | Preserve the 3.2/4.0 language-version hunks while rebasing Mellum kernels and streaming |
| `qwen35/0001-0008` dense Qwen | Same `ds4.c`, `ds4.h`, `ds4_gpu.h`, `ds4_metal.m`, `metal/qwen4.metal`, `Makefile`, and Qwen tests | Follow the accepted order `common -> mellum -> qwen35`; rebase and re-export qwen35 after Mellum. Guard shared predicates with `!ds4_model_is_mellum()` where Qwen behavior is not valid for Mellum |
| `qwen35/0002,0004` chat and sampling | Qwen special-token rendering and default restoration touch Mellum's native chat/default functions | Keep Mellum's `<|im_start|>`, `<|im_end|>`, think, tool-response, and min-p behavior distinct; run both families' fixtures |
| `qwen35/0005-0008` verify/DFlash | Multi-row and drafter hooks are Qwen-specific; Mellum has no `NEXTN` drafter | Keep DFlash unavailable on Mellum and run Qwen verify/DFlash regressions on the full tree |

### 2.3 Reference GGUFs and measured Mac Studio baseline

Both files were downloaded from the README's Hugging Face repository into
`~/models`. Sizes and hashes match `README.md:53-56` exactly:

| File | Bytes | Verified SHA-256 |
| --- | ---: | --- |
| `Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf` | 12,925,417,760 | `69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f` |
| `Mellum2.1-12B-A2.5B-Thinking-MXFP4_MOE.gguf` | 7,029,537,056 | `cf09584a30423f6f80b0c9fe2f42e152520dabf08fecd1cad641ce21a7588166` |

Verification used `shasum -a 256 FILE...` and `stat -f '%N %z bytes' FILE...`.
Before building and before running models, `pgrep -fl "ds4|dogfood"` found no
model process. The machine is an Apple M4 Max Mac Studio with 38,654,705,664
bytes (36 GiB) of RAM, on AC power with no thermal/performance warning.

The current reference `Makefile` declares `ds4.o` prerequisites before `all`,
so plain `make` selects only `ds4.o`, the first rule's first target. The
unmodified reference was therefore built with `make all`. The first attempted runner
failure is retained in `~/ds4-runs/mellum-design-mac-studio/`; the valid
baseline is in `~/ds4-runs/mellum-design-mac-studio-baseline/`.

Commands, once per quant:

```bash
cd ~/work/ds4-mellum
OUT="$HOME/ds4-runs/mellum-design-mac-studio-baseline"
Q8="$HOME/models/Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf"
MXFP4="$HOME/models/Mellum2.1-12B-A2.5B-Thinking-MXFP4_MOE.gguf"
ARMS=AA tests/mellum_cli_prefill_abba.sh "$OUT/mxfp4-prefill" "$MXFP4" 2048
ARMS=AA tests/mellum_cli_decode_abba.sh "$OUT/mxfp4-decode" \
  "$MXFP4" tests/mellum_prompts 2048
ARMS=AA tests/mellum_cli_prefill_abba.sh "$OUT/q8-prefill" "$Q8" 2048
ARMS=AA tests/mellum_cli_decode_abba.sh "$OUT/q8-decode" "$Q8" tests/mellum_prompts 2048
```

Each cell has `PER=4`, two A blocks, and drops the first process in each block:
n=6. The prompt is 2,056 tokens and generation is 256 greedy tokens. These
are reference measurements at `d2d9338`, not promises for the port:

| Quant, resident | Prefill median (range) | Generation median (range) | Planned memory at context 3072 |
| --- | ---: | ---: | ---: |
| MXFP4_MOE | 1,550 t/s (1,546-1,556) | 94.48 t/s (93.93-95.14) | 6.92 GiB |
| Q8_0 | 1,515 t/s (1,452-1,549) | 88.19 t/s (86.01-89.57) | 12.41 GiB |

Representative logs are `mxfp4-decode/l2048_b1A_p2.err` and
`q8-decode/l2048_b1A_p2.err`; `setup.txt`, `runs.txt`, and `events.txt` preserve
commit, machine, raw values, and power state.

## 3. Selected architecture and ownership

```text
patches/mellum (native model, graph, streaming, native chat primitives)
        |
        v
libds4 -> ds4-py generic native family detection
        |-> Hermes parser + prompt/history rendering (generic companion PR A)
        |-> native or Pi tool profile             (generic companion PR B)
        |
        v
satyrn-agent -> model sampling policy, DFlash/think controls, footer,
                persistence, live acceptance and memory/tool measurements
```

Native chat template belongs in `patches/mellum`, not ds4-py. The existing
`ds4_chat_append_message`, `ds4_chat_append_assistant_prefix`, tokenization,
stop classes, and EOS APIs already cross the native boundary. Port their Mellum
behavior and the imported-history rules from `ds4.c:44749-45084` and
`ds4_server_mellum_template.inc:190-274`.

Python-owned tool protocol and agent composition belong in ds4-py. Current
`family_of()` returns only deepseek41/glm/qwen/deepseek4
(`src/ds4py/_native/protocol.py:41-56`), and `make_parser()` falls through to
DSML (`engine/tool_syntax/base.py:278-290`). Mellum also sets `is_qwen4`, so
without checking `ds4_engine_is_mellum` first it would incorrectly select the
Qwen parser. The native predicate already exists at `ds4.h:312` and
`ds4.c:73803-73806`.

Model-specific Satyrn policy stays downstream. Recommended sampling,
DFlash/think controls, and the final measured tool-profile choice are Satyrn
work. ds4-py gets reusable Hermes and tool-profile mechanisms with no Satyrn
names in production code or tests.

## 4. `patches/mellum` series

Create this layout on `feat/mellum-support`:

```text
patches/
  common/
  mellum/
    0001-mellum-model-config-memory-and-host-contract.patch
    0002-mellum-tokenizer-chat-and-thinking.patch
    0003-mellum-exact-q8-metal-graph-and-rewind.patch
    0004-mellum-optimized-q8-prefill-and-decode.patch
    0005-mellum-mxfp4-moe-experts.patch
    0006-mellum-ssd-expert-streaming.patch
  qwen35/  # rebased and re-exported after mellum
```

Every patch message carries `Upstream:`, `Retire-when:`, and
`Carried-commits:`. The table defines the first two trailers verbatim and the
source ledger for the third. During export, replace the ledger description
with the complete space-separated hashes from the stated `git rev-list`
command; do not invent an abbreviated or incomplete trailer.

| Patch | Contents and order | `Upstream:` / `Retire-when:` | `Carried-commits:` source ledger |
| --- | --- | --- | --- |
| 0001 | Recognition, hyperparameter/tensor validation, Q8 binding, memory plan/session allocation, `ds4_engine_is_mellum`, sampling defaults, payload refusal and false support predicate | `not offered, fork only` / `upstream runs Mellum 2.1 with this host contract` | `git rev-list --reverse c97964b..d2d9338 -- ds4_mellum_config.inc ds4_mellum_plan.inc` plus host hunks selected from `ds4.c ds4.h` |
| 0002 | `mellum2` tokenizer and Unicode tables, special-token/stop classes, native system/assistant/tool-response rendering, think on/off, imported-history behavior, CLI text/cap handling | `not offered, fork only` / `upstream renders and stops Mellum 2.1 chats` | `git rev-list --reverse c97964b..d2d9338 -- ds4_mellum_tokenizer.inc ds4_mellum_unicode.inc ds4_cli.c ds4_prompt_prefix.h` plus native-chat hunks from `ds4.c ds4.h` |
| 0003 | Exact Q8 Metal graph, allocation, sliding/full attention, MoE, logits, exact-prefill diagnostic, session rewind and frontier | `not offered, fork only` / `upstream runs an exact Mellum 2.1 Metal graph` | `git rev-list --reverse c97964b..d2d9338 -- ds4_mellum_graph_alloc.inc ds4_mellum_graph.inc ds4_mellum_test_hooks.inc metal/mellum.metal` plus exact-graph/rewind hunks from `ds4.c ds4.h ds4_gpu.h ds4_metal.m metal/qwen4.metal` |
| 0004 | Tiled Q8 prefill experts/projections/attention, Metal 4 opt-in, sliding decode loads and fused small kernels, fast-path tests | `not offered, fork only` / `upstream has equivalent Mellum fast paths` | Topic commits selected by `git log --reverse --format=%H --grep='tiled\|batched\|fused\|two keys\|tensor.tile' c97964b..d2d9338` plus their review fixes |
| 0005 | MXFP4_MOE expert loading and kernels, uniform-expert validation, half-size slot arithmetic, numerical fixtures | `not offered, fork only` / `upstream supports JetBrains MXFP4_MOE` | `git log --reverse --format=%H --grep='MXFP4\|mxfp4' c97964b..d2d9338` limited to product/test commits, excluding research-only notes |
| 0006 | Stream config, uncached descriptor, slot cache, stop/resume and overlapped loads, grouped prefill, read-fault handling | `not offered, fork only` / `upstream streams Mellum experts with equivalent behavior` | `git rev-list --reverse c97964b..d2d9338 -- ds4_mellum_stream.c ds4_mellum_stream.h` plus streaming hunks from `ds4.c ds4.h ds4_metal.m ds4_mellum_graph.inc` |

The ledger commands select evidence; they do not authorize dropping required
review fixes. Paul must compare the final content against the reference files
and append any missing product commit to the relevant trailer.

### What `ds4-check --model mellum` proves

`tools/ds4-check.sh:152-186` recreates a pristine clone at the pin, and
`tools/ds4-lib.sh:239-274` applies common then model directories in lexical
order with plain `git am`. With a matching `.ds4/tree`, it also compares common,
model-boundary, and final Git tree IDs. Thus:

```bash
ds4-check --model mellum
```

proves that committed common+Mellum reconstructs deterministically without the
fork object store. It does not build or run tests by itself. Use:

```bash
ds4-check --model mellum --build
ds4-check --model qwen35 --build
ds4-check --build
```

The first builds common+Mellum, the second catches qwen35-after-Mellum prefix
breakage, and the third checks every boundary. These checks do not replace
`make test-mellum`, Qwen regressions, live numerical tests, or the memory/tool
acceptance below.

### Patch acceptance checks

| Patch | Acceptance before moving to the next patch |
| --- | --- |
| 0001 | `make tests/test_mellum_config && ./tests/test_mellum_config` passes model-free; with `DS4_TEST_MELLUM_MODEL=Q8`, the same binary performs real validation/binding and prints the startup memory line; a host test proves `ds4_engine_is_mellum && ds4_engine_is_qwen4` and payload support is false |
| 0002 | `make tests/test_mellum_config tests/test_mellum_tokenizer && ./tests/test_mellum_config && ./tests/test_mellum_tokenizer` passes: 30/30 tokenizer cases and every generated chat/history/tool-result case; token ids pin `<think>=23`, `</think>=24`, EOS=28 (`tests/test_mellum_config.c:565-622`) |
| 0003 | `make test-mellum-kernels && DS4_TEST_MELLUM_MODEL="$Q8" make test-mellum-fastpath` passes; exact prefill/decode and 64 greedy tokens match the reference oracle; `DS4_TEST_MELLUM_MODEL="$Q8" ./ds4_test --mellum-rewind` has zero differing logit words at the frontier |
| 0004 | Fast-path 45/45 and numerical caps from `MELLUM.md` pass; the Mac Studio n=6 baseline medians are within 10% of §2.3 and Qwen kernel tests pass |
| 0005 | Both SHA-verified files load, unsupported/mixed quants fail by name, MXFP4 reference logits pass, and Q8 resident medians do not regress by more than 10% (n=6) |
| 0006 | `make test-mellum-stream` passes; streamed and resident greedy ids agree for 512 tokens in 3/3 runs per quant; the 16 GB and 8 GB physical gates in §8 pass |

Port the relevant model-free tests with each patch rather than deferring all
tests to the end. Do not port C server/agent-only cases.

## 5. Generic ds4-py companion PR A: Hermes engine/harness support

Paul's assumption "ds4-mellum will not touch ds4-py" is not viable for
Satyrn. ds4-mellum itself need not change ds4-py, but Satyrn needs a separate
generic ds4-py companion because the current parser, family selection, prompt
construction, and history renderer cannot handle Hermes.

### Parser and family detection

Add an optional core binding for `ds4_engine_is_mellum`, with absence mapping
to false for older libraries, and add `is_mellum` to `EngineInfo`. Check Mellum
before qwen in `NativeEngine._read_info()` (`_native/api.py:228-245`) and
`family_of()`. Use `family="hermes"` for the protocol; retain `is_qwen4=True`
because that describes the native graph, not the tool syntax.

Add `engine/tool_syntax/hermes.py` and select it before the Qwen branch in
`make_parser()`. Port the streaming contract evidenced by
`ds4_agent_hermes.inc` and `ds4_server_hermes.inc:18-152`:

- `<tool_call>{"name": STRING, "arguments": OBJECT}</tool_call>`;
- prose and multiple calls; markers inside JSON strings remain content;
- typed nested values and a JSON-string containing the arguments object;
- strict RFC 8259 values, duplicate `arguments` replacing the earlier value,
  NUL/trailing commas/backticks/incomplete calls rejected;
- immutable capture/restore/fork and structural greedy-sampling behavior like
  the existing parsers;
- bounded write/edit bare-quote repair only in the exact forms in
  `agent_hermes_repair_quotes`, never in a path or an ambiguous/member-folding
  value.

Generate fixtures from the C tests and run every case with chunk sizes 1, 7,
and 4096. Do not weaken strict parsing to improve the tool benchmark.

### Prompt and history rendering

Extend `ToolPromptGenerator` with the Hermes block shown in
`ds4_agent_mellum_prompt.inc:8-70`: Python `json.dumps(...,
ensure_ascii=False)` formatting with `", "` and `": "` separators, insertion
order, a `{"type":"function","function":...}` wrapper, and the exact tool-call
example. Keep caller schemas outside trusted markup.

Update `PromptBuilder` (`engine/prompt.py:36-160`) for Hermes:

- render one initial system turn containing instructions and the tools block,
  not instructions in one system turn followed by an unwrapped tools fragment;
- tokenize `<|im_start|>`, `<|im_end|>`, think and tool markers as trusted
  rendered spans, while instructions, schemas, user text, and tool results stay
  plain payloads;
- render consecutive results in one user turn with one `<tool_response>` per
  result, matching `tests/mellum_chat_ids.inc` and
  `ds4_server_mellum_template.inc:190-230`;
- preserve sampled raw calls and render restored calls through a new Hermes
  branch of `render_tool_call()`; the current allow-list rejects every family
  except deepseek4/deepseek41/glm/qwen (`tool_syntax/render.py:114-134`);
- close restored assistant turns and keep the first `</think>` as the
  reasoning/content boundary; earlier imported reasoning is dropped as the
  template requires.

Include Hermes markers in compaction's tool masking instead of falling back to
DSML-only masking (`engine/compaction.py:90-105`). Native compaction remains
unsupported for Mellum in this slice, but the generic renderer must not teach a
future summary job to emit another family's protocol.

### Thinking and sampler defaults

No new Python thinking format is needed. `RoundStream` and `Decoder` already
track `<think>`/`</think>` (`engine/stream.py:41-56`,
`engine/decoder.py:8-78`). The CLI prints reasoning as plain text because it
suppresses those markers; the token stream still contains ids 23 and 24.
`ds4_server_hermes.inc:1-16` is additional evidence for the same split.

The engine defaults and Satyrn defaults are deliberately different:

- native engine: temperature 1.0, top-p 1.0, top-k 0, min-p 0
  (`ds4.c:73808-73820`);
- recommended client sampling: temperature 0.6, top-p 0.95, top-k
  20 (`README.md:94-107`).

Do not hard-code the recommended values into generic ds4-py. In Satyrn's
session setup, insert the recommended values between native defaults and
explicit project/CLI overrides, preserving explicit zero and `min_p=0`. Add a
test that proves precedence `native -> Mellum recommendation -> project -> CLI
-> request`.

## 6. Generic ds4-py companion PR B: tool profiles and measurement

### Reference and current mismatch

Mellum was trained on Pi's `read`, `write`, `edit`, and `bash`
(`ds4_agent_pi_tools.inc:1-14`), with schemas in
`ds4_agent_mellum_prompt.inc:8-25`. ds4-py currently exposes `read_file`,
`write_file`, `edit_file`, other filesystem tools, and `run_command` plus
background-command tools through the harness `Shell` capability
(`src/ds4py/agent.py:45-108` and harness `shell/_toolset.py:365`). Its default
instructions explicitly describe `read_file` and `edit_file`
(`agent_prompt.py:3-31`). There is no evidence yet that either naming scheme
is better for Mellum, so implement both and measure.

### Generic profile mechanism

Add `tool_profile = auto | native | pi` to the generic agent composition and
CLI, propagate it through `EngineOpenOptions`/runtime into
`build_agent_components`, and default to `auto`. Existing models map to
`native`. Mellum's `auto` mapping is decided by the measurement gate below;
until then it is `pi` only as a development hypothesis, not a claimed result.
The option is generic and contains no Satyrn name.

The `pi` profile exposes exactly four operations with the reference names,
argument names, descriptions, and order: `read`, `bash`, `edit`, `write`.
Implement them as adapters over the existing `FileSystemToolset` and
`ShellToolset`; do not fork filesystem/shell execution or bypass workspace
containment, read-only policy, events, retries, or output limits.

| Pi operation | Adapter contract |
| --- | --- |
| `read(path, offset?, limit?)` | Convert Pi's 1-indexed offset to the filesystem tool's zero-based offset (`0` and `1` both read the first line). Pass `limit=2000` when the caller omits it, which replaces the native profile's 160-line default. Use the existing read method (`FileSystemToolset.read_file`, installed harness 0.59.0 `filesystem/_toolset.py:901`) |
| `write(path, content)` | Call the existing write method (installed harness 0.59.0 `filesystem/_toolset.py:1006`) with no optimistic hash argument |
| `edit(path, edits[{oldText,newText}])` | Convert to the existing `Replacement` list and use one atomic edit operation; add a ds4-py batch wrapper around the existing edit tool rather than applying a sequence of public single-edit calls. Reject ambiguity/overlap before writing |
| `bash(command, timeout?)` | Call `ShellToolset.run_command` (installed harness 0.59.0 `shell/_toolset.py:365`) with `timeout_seconds=timeout` when supplied. With no timeout retain ds4-py's configured default and document this difference from Pi's no-deadline behavior |

The Pi profile emits its own four definitions. It does not reuse
`DS4FileSystem`'s prepared definitions, which rewrite the read-limit
description for the native 160-line default
(`capabilities/file_system.py:12-24`). The Pi read budget is 2000 lines and
50,000 characters, replacing the native 160-line budget. The output cap remains
ds4-py's character-based cap, not Pi's byte-based 50 KiB cap.

The initial adapter keeps ds4-py's result text, including numbered read
output and labelled shell output. Do not claim byte-for-byte Pi result parity;
`ds4_agent_pi_tools.inc` is the behavioral reference for a later decision if
the comparison exposes a result-text problem. Use a Pi-specific instruction
preamble so no `read_file`/`edit_file` instructions contradict the exposed
schemas.

Tests must prove schema equality with the four reference definitions, offset
and argument conversion, a real read/write/edit/bash round trip, multi-edit
atomicity, workspace/read-only enforcement, and unchanged `native` behavior.

### Required live comparison

Run after the engine and both ds4-py companions work, on the 36 GB Mac Studio,
with both quants resident, context 32768, recommended sampling, fresh session
per task, and the same prompt+seed pairs in an A/B/B/A order.

- n=30 independent tasks per profile per quant (six task types x five
  paired repetitions): read, write, edit, bash, read-edit-bash, and a small
  multi-file change. This is 60 runs per quant, 120 total.
- Add `tests/e2e/live/mellum_tool_bakeoff.py` and a small fixture workspace.
  The six graders check: (1) reading `hello.py` and reporting its output;
  (2) writing `hello.py` with the requested `greet()` function; (3) changing
  the greeting exactly once; (4) running `python3 hello.py` and reporting its
  output; (5) read-edit-run in one session; and (6) changing `main.py` and
  `helper.py` so the existing test passes. Use seeds 1 through 5 for each
  grader and reset the fixture for every run. File bytes, process output, and
  test results determine success, not a model's self-report.
- Run the comparison with
  `uv run --frozen python tests/e2e/live/mellum_tool_bakeoff.py --model "$Q8"
  --profiles native,pi --order ABBA --repetitions 5 --out RESULTS_Q8`, then
  repeat with `--model "$MXFP4" --out RESULTS_MXFP4`. Keep every JSONL record
  and the summary in the implementation PR's evidence directory.
- Primary measures: completed task rate and valid tool-call/schema rate.
  Secondary: malformed calls, retries, wrong-tool calls, turns, generated
  tokens, and wall time.
- Report every run, paired outcomes, Wilson 95% intervals for proportions, and
  a paired exact test for task success. `n=30` is an engineering comparison,
  not proof of a universal model ranking.
- Koudai rules on `auto -> pi` versus `auto -> native` after seeing the table.
  Do not silently select the profile with higher speed alone, and do not claim
  an effect without its `n`.

## 7. Satyrn behavior and acceptance

### DFlash and footer

Mellum has no DFlash drafter. Keep `/dflash` visible; do not hide it or invent
a generic speculative mode. With the normal no-drafter configuration:

- startup and `/dflash auto` install `PlainStep`, explicitly leave native
  verify OFF when that optional binding exists, and show
  `dflash: auto/off, accept — (0/0)`;
- `/dflash off` shows `dflash: off, accept — (0/0)`;
- `/dflash on` fails before mutation with `DFlash requires a drafter path` and
  preserves history and the previous footer;
- `/dflash` queries return the same state; off rounds add no offered/accepted
  drafts.

This follows the existing policy in PR #25's `controller.py:46-84` and footer
format at `controller.py:190-222`. Do not pass the Qwen drafter to Mellum. A
user-supplied drafter path must fail native open with a Mellum-specific error,
not a misleading Qwen message.

### Think budget

The existing hook works without a new algorithm. `resolve_end_think()` requires
one rendered token, and Mellum's `</think>` is token 24
(`tests/test_mellum_config.c:565-622`). The hook biases only after
`view.in_think && view.think_tokens >= max_tokens`
(`capabilities/think_budget.py:28-39`). It remains a soft budget: no
truncation, injected marker, or guaranteed closure.

Test `/think-budget`, a changed budget/bias, `off`, session reset/fork, and
continued real generation. Also test `--nothink`: reasoning emitted as plain
text outside a think block is not budgeted, matching the reference divergence
in `MELLUM.md:550-560`.

### Persistence and unsupported native state

Prove that common+Mellum's payload predicate is false. `/save` writes a complete
stripped record with `payload_bytes=0` and no KV file; `/switch` uses rendered
restore with the existing validation. Native in-memory snapshots and `/compact`
are outside this slice and must report their existing unsupported error rather
than claiming success. These behaviors need model-free public-flow tests plus a
real Metal save/switch test.

## 8. Memory targets and physical acceptance

All memory gates use context 32768, one model process at a time, AC power where
available, no other GPU workload, and the SHA-verified files. Record the actual
Metal recommended working-set limit, planned bytes, Metal peak, host footprint,
swap before/after, first token, prefill, generation, command, commit, and `n`.
Never treat a startup plan alone as a peak measurement.

| Target | Required configuration and test | Acceptance |
| --- | --- | --- |
| 36 GB, Mac Studio M4 Max (this machine) | Both quants resident. Repeat §2.3 at its measured context 3072 with prefill/decode n=6, then use context 32768 for a 2,686-token coding request n=3 with Metal peak | Port medians within 10% of the reference on the same machine; exact greedy ids match; peak no more than 5% above the reference; no swap growth |
| 24 GB, MacBook Air | Both quants resident at 32768; Q8 and MXFP4 n=3 each | Reference peaks are Q8 12.78 GiB and MXFP4 7.29 GiB (`README.md:143-144`), so both are candidates. Require measured peak below the machine's limit, no swap growth, and exact ids. No 24 GB measurement exists yet; mark the gate pending until run |
| 16 GB, Mac mini M1, `the Mac mini` | MXFP4 resident first; then Q8 streamed with `--ssd-streaming --ssd-streaming-cache-experts 6GB`. Copy only the quant currently tested; remove nothing else on the machine | MXFP4's 7.29 GiB reference peak fits below the estimated 10.67 GiB limit and is the resident choice. Q8's 12.78 GiB does not fit and needs streaming (`ROADMAP.md:181-191`). Require measured limit/peak/no swap and resident-vs-streamed exact ids. Do not intentionally run resident Q8 into swap |
| 8 GB streaming case | MXFP4 only, `--ssd-streaming --ssd-streaming-cache-experts 2GB`, context 32768, apps closed | The reference is 5.85 t/s, 19.4 s first token, 3.86 GiB Metal peak, no swap growth, n=3 (`README.md:217`; `ROADMAP.md:323-327`). Require no swap, peak below the physical limit, exact resident/streamed ids, and generation at least 5.0 t/s. Do not use 2.5 GiB; it exceeds the measured limit by 68,976,640 bytes (`ROADMAP.md:331-332`) |

The 16 GB build and baseline use the same commands as §2.3, MXFP4 first. Copy
the source or a bundle, build with `make all`, and copy only
`Mellum2.1-12B-A2.5B-Thinking-MXFP4_MOE.gguf` for the resident run. If Q8 is
subsequently tested, copy only that file for that run. Keep every unrelated
file on the Mac mini untouched.

The 24 GB and 8 GB rows are required acceptance runs on their physical target
class, not claims that this design session measured those machines. Existing
reference numbers are cited as baselines only.

## 9. Small implementation tasks for Paul

Paul writes the implementation plan from this section before product changes.
Keep each task in its own commit or small commit group, write a focused failing
test first for behavior changes, and run its check before starting the next.

### Companion PR A (generic ds4-py)

1. Native identity. Add optional `ds4_engine_is_mellum`, `EngineInfo` and
   precedence. Check: absent-symbol compatibility plus a Mellum+qwen fixture
   selects Hermes, while all existing family tests are unchanged.
2. Strict Hermes parser. Add parser, selection, capture/restore/fork and
   fixtures. Check: all C-derived valid/malformed cases pass at all three chunk
   sizes and no DSML fallback remains for Mellum.
3. Bounded repair. Add only the evidenced write/edit repairs. Check:
   path/member-folding/backtick/NUL/truncated cases fail, and repaired calls
   reproduce the C vectors exactly.
4. Tool prompt and initial system turn. Add Hermes generator and
   `PromptBuilder.begin`. Check: exact text/token ids equal the generated
   reference, including plain-payload boundaries and one system turn.
5. Assistant/tool history. Add Hermes renderer, grouped tool responses,
   sampled raw preservation and reasoning split. Check: all generated history
   fixtures round-trip bytewise and restored non-sampled histories parse.
6. Generic regression gate. Include Hermes compaction markers and run the
   complete ds4-py static and model-free suites. Check: no Satyrn identifier
   appears in the diff and every existing family passes.

### Companion PR B (generic ds4-py)

7. Profile plumbing. Add `auto/native/pi` through parser/options/runtime.
   Check: defaults and explicit choices reach agent construction unchanged;
   native output is byte-identical for existing models.
8. Four Pi adapters. Add schemas, instructions and execution adapters.
   Check: reference schemas match; real tool round trips, offset conversion,
   atomic edits, timeout forwarding and workspace policy pass.
9. Profile model-free gate. Add auto-selection tests and run the complete
   ds4-py suites. Check: no Satyrn identifier appears and native coverage is
   not weakened.

### satyrn-agent implementation branch

10. Engine patch 0001. Config, memory, host APIs, payload predicate.
    Check: §4 patch 0001 plus `ds4-check --model mellum --build`.
11. Engine patch 0002. Tokenizer/chat/thinking. Check: §4 patch 0002.
12. Engine patch 0003a. Exact Q8 allocation/attention/MoE/forward. Check:
    model-free kernels and exact oracle before optimization.
13. Engine patch 0003b. Rewind/frontier and stripped persistence behavior.
    Check: zero-logit-difference rewind plus real stripped save/rendered switch.
14. Engine patch 0004. Optimized Q8. Check: numerical caps, 45/45 fast
    paths, and Mac Studio n=6 performance.
15. Engine patch 0005. MXFP4. Check: both GGUF identities, reference logits,
    and Q8 non-regression.
16. Engine patch 0006. SSD streaming. Check: scheduler unit tests, 3/3
    exact streamed runs, and physical 16/8 GB gates.
17. Qwen prefix. Rebase/re-export qwen35. Check: `ds4-check --model qwen35
    --build`, `ds4-check --build`, and Qwen kernel/DFlash live regressions.
18. Harness pin and sampling. Pin the two ds4-py companion commits and add
    Satyrn's recommended-sampling layer. Check: precedence test and real native
    default report match §5.
19. Satyrn controls. Add Mellum DFlash/footer, think-budget and persistence
    scenarios. Check: model-free 100% line+branch gate and real Metal controls.
20. Memory matrix. Run §8 on physical targets. Check: publish command/raw
    output/n for each row; pending rows do not count as passes.
21. Tool comparison. Run §6's 120 tasks and record Koudai's auto-profile
    ruling. Check: reproducible table includes every run and the selected
    default has a model-free test.
22. Final repository gates. Run the complete static gate, portable shell
    suite, model-free coverage, and live Mellum+Qwen acceptance. Check: all
    required rows green before requesting human review.

## 10. PR sequence and how to work

1. ds4-py companion A, generic Hermes support. Author: decision needed
   from Koudai (Roché or Paul). Roché reviews/merges ds4-py.
2. ds4-py companion B, generic tool profiles. Author: decision needed
   from Koudai (Roché or Paul). Roché reviews/merges ds4-py.
3. satyrn-agent `feat/mellum-support`. Paul ports the engine series,
   rebases qwen35, pins the companion commits, integrates controls and runs
   acceptance. Koudai reviews. Keep engine patch commits separate from harness
   behavior commits.
4. Open the ds4-mellum tracking issue "Port Mellum 2.1 to satyrn-agent"
   with the spec PR link. Paul tracks the work there; do not push to
   `pauleveritt/ds4-mellum`.

The spec itself is delivered on `docs/mellum-design` in satyrn-agent.
Implementation is also a satyrn-agent branch, `feat/mellum-support`, with
`patches/mellum` as above. No Patchmill workflow is used.

### How to work

- Follow Superpowers in order: accepted spec -> implementation plan -> plan
  review -> small TDD implementation tasks -> final review. Paul plans with
  Kimi K3 and implements with DeepSeek V4 Flash.
- Work from the repository root in the task worktree. Keep devenv + `uv
  --frozen`; do not create another Python environment or hook runner.
- Run `ds4-check --model mellum` for reconstruction, with `--build` for the
  build gate; also run the qwen35 prefix and full checks after rebasing it.
- Before every build/model run use `pgrep -fl "ds4|dogfood"` and inspect the
  result. Stop if another model process is active. Never use `--raw-prompt`.
- Run `uv run --frozen prek run --all-files --show-diff-on-failure`, `bash
  tests/ds4_tools_test.sh`, and `uv run --frozen pytest tests/e2e/model_free
  --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100`
  after relevant changes. Run actionlint for workflow changes.
- Use `make all` for the current reference checkout because its default target
  is `ds4.o`.
- Model locations: the 36 GB Mac Studio has both SHA-verified GGUFs in
  `~/models`; the 16 GB Mac mini receives only MXFP4 first; the 24 GB Air has
  no verified local copy yet; the 8 GB case uses MXFP4 only. Do not assume a
  model is present on another machine.
- Run `pr-review-loop` before requesting human review and after pushing changes
  to a reviewed PR. Use fresh reviewers, alternating
  `deepseek/deepseek-v4-pro` and `kimi-coding/k3.1-pro`; ask Koudai for every
  decline/defer ruling. Do not amend, squash, or force-push during the loop.
- Delivery includes implementation, required verification, commits, branch
  push, and PR. The two ds4-py PRs are generic companions; this design's spec
  PR remains on satyrn-agent.

## 11. Decisions needed

1. Koudai/Roché: who authors generic ds4-py companion PRs A and B? Paul is
   already the named owner for the satyrn-agent port; Roché reviews ds4-py.
2. Koudai: after the n=30/profile/quant comparison, choose `auto -> pi` or
   `auto -> native` for Mellum.
3. Koudai: provide working SSH authentication for
   `the Mac mini` or an alternate way to run the required 16 GB
   baseline. All three existing local keys were denied during design research;
   no 16 GB number is claimed here.
4. Koudai: identify who supplies the physical 24 GB MacBook Air and 8 GB
   streaming acceptance runs. They remain pending, not silently waived.
