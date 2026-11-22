# Mellum 2.1 support implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run JetBrains Mellum 2.1 through the `satyrn-agent` command on Metal — same ds4-py agent, tools, history, persistence, TUI and footer as today — on Macs that cannot hold the 27B Qwen model.

**Architecture:** Six engine patches under `patches/mellum/` port the fork's model config, tokenizer/chat, Q8 graph, rewind, optimized Q8, MXFP4 experts and SSD streaming onto the existing pin, keeping the order `pin → common → mellum → qwen35`. Two generic ds4-py companions add Hermes parsing/rendering and an `auto|native|pi` tool profile; neither contains a Satyrn identifier. Satyrn keeps only model policy: recommended sampling, DFlash/footer behavior, think budget, persistence and the physical acceptance evidence.

**Tech Stack:** C (ds4 engine, Metal), Bash patch tooling (`ds4-sync`, `ds4-export`, `ds4-check`), Python 3.14, ds4-py agent/harness, pydantic-ai-harness 0.59.0, pytest model-free E2E, devenv + uv.

**Spec:** `docs/specs/2026-11-16-mellum-model-design.md` (spec PR #26, branch `docs/mellum-design`). Executors read the spec section named in each task alongside the task.

**Delivery split.** Part A (tasks 1–9) is a handoff to Koudai for the two generic ds4-py PRs: different repo, different conventions (`docs/plans/`, `uv run --frozen --extra agent`). Part B (tasks 10–22) is the satyrn-agent branch `feat/mellum-support`. Both parts ship separately; the plan is one document because task 18 consumes the two companion commits.

## Current checkpoint and open acceptance

Reviewed on 2026-11-21 at satyrn-agent `862ff0b`, against main `eed5c4f` and published
PR #29 head `8ccc4fc`. See the [deep review](../../reports/2026-11-21-mellum-review.md)
for findings, verification and the effect of the approvals.

**Delivery split:** PR #29 is the engine checkpoint (Tasks 10–17); the Satyrn harness
integration, controls, tool comparison and final physical acceptance ship separately.
Approval of the checkpoint does not complete the spec's full acceptance.

| Work | Current status | Remaining gate |
| --- | --- | --- |
| Engine 0001–0006 | Implemented/exported; published-model numerical and tokenizer results recorded | Fix missing Make dependencies for the restored `.inc` files before merge |
| Exact-prefill placement and reference layout | Koudai's decisions implemented; 0003 exact oracle recorded | Preserve the original measured trees; no new design ruling needed |
| Task 17 | All 18 qwen35 patches rebased and exported; common/Mellum/full targets reconstruct | Fresh CI after push; focused review of the unreviewed relocation and conflict resolutions |
| Published-Q8 per-prefix evidence | Recorded; older different-hash measurements remain historical | Reconcile provenance rather than repeat every unchanged gate |
| Task 15 MXFP4 performance | Current-0005 pair measured on the absorbed export under Nix SDK 26: 4,071 vs 4,063 t/s prefill, 151.38 vs 150.70 decode (n=6); Q8 0004→0006 flat within 0.28% of the reference, decode 0.42–0.72% above | Physical M4 Max row still required |
| Resident/streamed 512-token parity | Final combined-stack runs recorded: 3+3 per quant on `23df126b`/`4d987745`, ids identical within and across modes (Q8 979 slots, MXFP4 652); older `8b8ef87a`/`ece0d5fe` runs keep their measured trees | None |
| Physical 36/24/16/8 GB matrix | Pending; M4 Max n=1 screen is supplemental | Koudai: 36/24/16 GB; Paul: 8 GB; all spec thresholds still apply |
| Qwen live suite | Recorded 48 pass, 1 failure after `/switch`, also reported on main's engine | Track the baseline failure explicitly; do not call the full live gate green |
| ds4-py companions A/B | Not present among the current PRs in `rochecompaan/ds4-py` | Koudai authors, Roché reviews/merges; then Task 18 can consume one reviewed descendant containing both |

Current engine identities are Mellum commit `f2c40f41`, tree `ca243153`, and combined
commit `320627f2`, tree `ee45405c`. A commit ID is not a tree ID. Record both, plus
model/prompt hashes, backend, machine, context, command, repetitions and raw artifacts.
These IDs will change when the build-dependency fix is exported.

Fresh review checks on the combined tree pass: all-files static gate, 50 shell
tests, 290 model-free cases at 100% coverage, real-model config/chat/tokenizer,
56 stream checks, 4 trace-stream checks, 992 kernels and the published-Q8 oracle
(29/1,100/2,200 inputs, 64/64 greedy decode IDs with equal logits). The optimized
prefill oracle uses tolerance bounds at long prompts; it is not byte-identical
to the reference there and permits two sampled near-tie top-1 changes at 1,100.
See the review report for the commands, identities and numerical limits.

The shared-code relocation from `8b8ef87a` to `ca243153` changes only `ds4.c` and
`ds4_mellum_graph.inc`. Expanding the Mellum includes produces byte-identical `ds4.c`
(SHA-256 `391d3ba992b840d6669c48af69b6df1c10ea1d6c61a9d6ab8b78c2b58ba22c25`).
Older results remain useful with their original provenance; this is not a rerun on
the new export or proof of the later combined qwen35 stack.

Roché explicitly requested proceeding without waiting for CUDA on 2026-11-20.
PR #24 has since merged as `eed5c4f`. Notify both owners that Task 17 is complete;
do not schedule another qwen35 rebase unless main changes again. The PR approvals
remove the need to reopen the settled design decisions. GitHub currently imposes
no branch-protection review gate; focused review of later changes is a technical
recommendation, not a requirement to obtain permission again.

The immediate sequence is the engine closure checklist after Task 17, then push,
fresh CI and the engine checkpoint merge. Run the independent physical/evidence
work alongside the companion handoff, rather than queueing all of it behind merge.
The full product acceptance remains open until all required rows and live gates pass.

## Global Constraints

- Metal is the only supported backend. No CUDA, ROCm, CPU inference, distributed, multi-GPU, or multi-session server work.
- The engine pin does not move: `upstream.pin` keeps `UPSTREAM_COMMIT=5379c1c9ac315f1540371b06a3db88491d4059ff`.
- Patch order is fixed: `pin → common → mellum → qwen35`. Model directories apply in `LC_ALL=C` lexical order, so `mellum` precedes `qwen35`.
- Accepted GGUFs are Q8_0 and MXFP4_MOE only: `Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf` (12,925,417,760 bytes, sha256 `69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f`) and `Mellum2.1-12B-A2.5B-Thinking-MXFP4_MOE.gguf` (7,029,537,056 bytes, sha256 `cf09584a30423f6f80b0c9fe2f42e152520dabf08fecd1cad641ce21a7588166`). Other or mixed quants fail by name.
- No Mellum DFlash drafter, speculative decoding, native KV/file payload, in-memory snapshot, or `/compact` support. `/dflash` stays visible and reports `accept — (0/0)`.
- No Satyrn identifier or policy appears in ds4-py production code or tests. Native chat belongs to `patches/mellum`; generic protocol and tool profiles to ds4-py; sampling/DFlash/think/persistence policy to Satyrn.
- Recommended Mellum client sampling is temperature 0.6, top-p 0.95, top-k 20. Native Mellum defaults are 1.0, 1.0, 0, 0. Precedence is `native → Mellum recommendation → project → CLI → request`, preserving explicit zero and `min_p=0`.
- Every patch message carries `Upstream:`, `Retire-when:` and `Carried-commits:` trailers, with the ledger expanded from the spec's `git rev-list` command.
- Verify the actual model SHA-256 before building/running the real-model gates. The existing `~/models/...Q8_0.gguf`
  has a different hash; use a verified published file such as the matching HF cache blob. Equal byte size is insufficient.
- Commands run inside `devenv shell` with `uv --frozen`. No second Python environment and no second hook runner.
- Before any build or model run: `pgrep -fl "ds4|dogfood"` must show no model process. Never use `--raw-prompt`.
- Record the command, commit, machine, `n`, and raw output for every measurement. A pending row is not a pass.
- Model-free coverage stays at 100% line and branch; portable tests are never claimed as live parity.

## Review Focus

- **A libds4 built before this work has no `ds4_engine_is_mellum`.** A user pointing Satyrn at an older library must get today's families, not a missing-symbol failure at open. Task 1 tests absence explicitly.
- **Mellum reports `is_qwen4=True` because its graph is Qwen-shaped.** Protocol selection must check Mellum first; if Qwen wins, every tool call is silently mis-parsed while the model still looks like it is working. Task 2 pins the precedence.
- **Truncated, duplicate-`arguments`, backticked, or NUL-containing `<tool_call>` JSON.** A partial call must be rejected, never executed with the arguments parsed so far. Task 2 pins each rejection form.
- **`--nothink` reasoning arrives as plain text outside a think block.** The soft budget must not bias or count it; a user asking for no thinking must not get budget-driven marker injection. Task 18 pins it.
- **A user passes a drafter path with a Mellum model.** They must get a Mellum-specific error before any mutation, with history and the footer unchanged — not a misleading Qwen/DFlash message and not a half-applied state. Task 18 pins it.
- **Q8 attempted resident on 16 GB, or any quant on 8 GB without streaming.** The run must not walk into swap; the gate records swap before/after and fails the row. Tasks 15, 16 and 20 pin it.

---

# Part A — ds4-py companions (handoff to Koudai)

Repo `rochecompaan/ds4-py`. The original plan used `95d52cbb9f189c9a940e777e9fab6baa15eac622`; Satyrn now pins `7d80c7c62a36d536521c657fe15d6b4aca28e1dd`. Reconcile these file/API references against the current reviewed companion base before implementation. Tasks 1–6 are companion PR A (Hermes), tasks 7–9 companion PR B (tool profiles). Both PRs use ds4-py's own conventions: plans in `docs/plans/`, devenv, `uv run --frozen --extra agent`, and the portable gate `uv run --frozen --extra agent pytest -m "not build and not live" -q`.

### Task 1: Mellum identity and family precedence

**Files:**
- Modify: `src/ds4py/_native/protocol.py:36-56`
- Modify: `src/ds4py/_native/bindings.py:34-45`
- Modify: `src/ds4py/_native/api.py:228-245`
- Test: `tests/native/test_api.py`, `tests/engine/tool_syntax/test_qwen.py` (unchanged-behavior guard)

**Interfaces:**
- Consumes: `Library.has(name)` (`_native/loader.py:92`) and existing `CORE_BINDINGS`.
- Produces: `EngineInfo(... , is_mellum: bool = False)` appended last so positional fixtures keep working; `family_of(*, deepseek41, glm, qwen, mellum=False) -> str` returning `"hermes"` when `mellum`, else the current chain; `EngineInfo.family == "hermes"` with `is_qwen4` still `True` for Mellum.

- [ ] **Step 1: Write the failing identity tests**

In `tests/native/test_api.py`: an`api_stub.c` build without `ds4_engine_is_mellum` yields `info.is_mellum is False` and an unchanged `family`; the same stub with the symbol returning true yields `is_mellum is True` and `family == "hermes"`.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/native/test_api.py -q`
Expected: FAIL — `EngineInfo` has no `is_mellum`.

- [ ] **Step 3: Implement**

Add `Binding("ds4_engine_is_mellum", "bool ds4_engine_is_mellum(ds4_engine *e)")` to `CORE_BINDINGS`, keeping it callable only when present. In `_read_info`, compute `mellum = get("is_mellum") if self._lib.has("ds4_engine_is_mellum") else False` and pass it to `family_of(mellum=mellum)` and `EngineInfo(is_mellum=mellum)`.

- [ ] **Step 4: Run and verify GREEN, plus the family guard**

Run: `uv run --frozen --extra agent pytest tests/native tests/engine/tool_syntax -q`
Expected: PASS, and every existing `deepseek41`/`glm`/`qwen`/`deepseek4` case unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/ds4py/_native/protocol.py src/ds4py/_native/bindings.py src/ds4py/_native/api.py tests/native/test_api.py
git commit -m "feat(native): identify Mellum and select the hermes protocol family"
```

### Task 2: Strict Hermes tool-call parser

**Files:**
- Create: `src/ds4py/engine/tool_syntax/hermes.py`
- Create: `tests/engine/tool_syntax/test_hermes.py`
- Create: `tests/engine/tool_syntax/fixtures/hermes_cases.json`
- Modify: `src/ds4py/engine/tool_syntax/base.py:278-290`

**Interfaces:**
- Consumes: `ToolParser` (`base.py:95`) capture/restore/fork/freeze contract and `freeze_calls`; `EngineInfo.is_mellum` from Task 1.
- Produces: `class Hermes(ToolParser)`; `make_parser()` returns `Hermes()` when `info.is_mellum` is true, before the `is_qwen4` branch.

- [ ] **Step 1: Generate fixtures from the C reference**

From `~/projects/pauleveritt/ds4-mellum` at `d2d9338`, read the Hermes cases in `tests/ds4_agent_test.c` and `tests/test_mellum_frontends_agent`, and write each case into `tests/engine/tool_syntax/fixtures/hermes_cases.json` as `{"name", "chunks", "calls", "error"}`. Keep prose, multiple calls, markers inside JSON strings, typed nested values, a JSON-string arguments object, duplicate `arguments` (later wins), and the malformed forms: NUL, trailing comma, backticks, incomplete call.

- [ ] **Step 2: Write the failing parser tests**

In `tests/engine/tool_syntax/test_hermes.py`, drive every fixture at chunk sizes 1, 7 and 4096, assert the parsed `ToolCall` args and `raw`, assert each malformed case raises the fixture's error, and assert `capture()`/`restore()`/`fork()` round-trip mid-call.

- [ ] **Step 3: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/engine/tool_syntax/test_hermes.py -q`
Expected: FAIL — no module `hermes`.

- [ ] **Step 4: Implement `Hermes` and register it**

Subclass `DelimiterParser` if its form machinery covers `<tool_call>`…`</tool_call>`; otherwise implement `ToolParser` directly, reusing `freeze_calls`, `_pending`/`_marker_tail` buffering and `wants_greedy_sampling`. Parse one RFC 8259 JSON object per call with `json.loads(..., parse_constant=...)` rejecting `NaN`/`Infinity`, require `name: str` and `arguments: object`, and keep prose outside calls as content.

- [ ] **Step 5: Run and verify GREEN**

Run: `uv run --frozen --extra agent pytest tests/engine/tool_syntax -q`
Expected: PASS at all three chunk sizes; no DSML or Qwen fallback for a Mellum `EngineInfo`.

- [ ] **Step 6: Commit**

```bash
git add src/ds4py/engine/tool_syntax/hermes.py src/ds4py/engine/tool_syntax/base.py tests/engine/tool_syntax/test_hermes.py tests/engine/tool_syntax/fixtures/hermes_cases.json
git commit -m "feat(tool-syntax): parse Hermes tool calls strictly"
```

### Task 3: Bounded quote repair for write/edit

**Files:**
- Modify: `src/ds4py/engine/tool_syntax/hermes.py`
- Create: `tests/engine/tool_syntax/test_hermes_repair.py`

**Interfaces:**
- Consumes: `Hermes` from Task 2.
- Produces: `repair_hermes_quotes(text: str) -> str | None` applied only to `arguments` values of `write` and `edit`; `None` means "not repairable, reject".

- [ ] **Step 1: Write the failing repair tests**

Assert the exact forms from `agent_hermes_repair_quotes` repair to the C vectors, and assert a path value, an ambiguous value, a member-folding value, a backticked value, a NUL and a truncated call are all rejected.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/engine/tool_syntax/test_hermes_repair.py -q`
Expected: FAIL — no repair.

- [ ] **Step 3: Implement the bounded repair**

Port only the evidenced forms, keyed by tool name; never repair a key named `path`, and never repair inside a JSON string that already parses.

- [ ] **Step 4: Run and verify GREEN, then commit**

Run: `uv run --frozen --extra agent pytest tests/engine/tool_syntax -q`

```bash
git add src/ds4py/engine/tool_syntax/hermes.py tests/engine/tool_syntax/test_hermes_repair.py
git commit -m "feat(tool-syntax): repair the bounded Hermes quote forms"
```

### Task 4: Hermes tool prompt and the single initial system turn

**Files:**
- Modify: `src/ds4py/engine/tool_prompt.py:34-70`
- Modify: `src/ds4py/engine/prompt.py:36-80`
- Create: `tests/engine/tool_syntax/fixtures/hermes_prompt.json`
- Test: `tests/engine/test_tool_prompt.py`, `tests/engine/test_prompt.py`

**Interfaces:**
- Consumes: `ToolPromptGenerator(family)`, `ToolPromptSpan(text, rendered)`.
- Produces: `ToolPromptGenerator._hermes(schemas) -> list[ToolPromptSpan]`; `PromptBuilder.begin` emits exactly one system turn for `family == "hermes"` containing instructions and the tools block.

- [ ] **Step 1: Write the failing prompt tests**

Assert `ToolPromptGenerator("hermes").spans(...)` reproduces the reference block from `ds4_agent_mellum_prompt.inc:8-70` byte for byte, with `json.dumps(..., ensure_ascii=False)` and `", "`/`": "` separators, insertion order, the `{"type":"function","function":...}` wrapper, and schema text as `rendered=False` spans.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/engine/test_tool_prompt.py -q`
Expected: FAIL — `unknown tool prompt family: hermes`.

- [ ] **Step 3: Implement the generator and the begin path**

Add `_hermes` to `spans()`; in `PromptBuilder.begin`, open one system turn with `<|im_start|>system` as a trusted span, append instructions and the tools block as plain payloads, and close with `<|im_end>`. Emit no separate unwrapped tools fragment.

- [ ] **Step 4: Run and verify GREEN against the reference token ids**

Run: `uv run --frozen --extra agent pytest tests/engine/test_tool_prompt.py tests/engine/test_prompt.py -q`
Expected: PASS, including token-id equality with the generated reference fixture.

- [ ] **Step 5: Commit**

```bash
git add src/ds4py/engine/tool_prompt.py src/ds4py/engine/prompt.py tests/engine/test_tool_prompt.py tests/engine/test_prompt.py tests/engine/tool_syntax/fixtures/hermes_prompt.json
git commit -m "feat(prompt): render the Hermes tools block in one system turn"
```

### Task 5: Hermes assistant and tool history

**Files:**
- Modify: `src/ds4py/engine/prompt.py:96-190`
- Modify: `src/ds4py/engine/tool_syntax/render.py:114-134`
- Create: `tests/engine/fixtures/hermes_history.json`
- Test: `tests/engine/test_prompt.py`, `tests/engine/tool_syntax/test_call_raw.py`

**Interfaces:**
- Consumes: `PromptBuilder.message`, `_tool_message`, `tool_results`, `restored_assistant`.
- Produces: `render_tool_call("hermes", name, args) -> str`; consecutive results rendered as one user turn with one `<tool_response>` each; first `</think>` splits reasoning from content; earlier imported reasoning dropped.

- [ ] **Step 1: Write the failing history tests**

Round-trip every case in `tests/mellum_chat_ids.inc` through `message`/`tool_results`/`restored_assistant`, assert bytewise equality with the fixture, and assert a restored non-sampled history parses.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/engine/test_prompt.py -q`
Expected: FAIL — Hermes falls through to the native tool renderer.

- [ ] **Step 3: Implement**

Add the `hermes` branches to `message`, `_tool_message` and `render_tool_call`, keep sampled raw calls intact, escape `</tool_response>` in payloads with the existing `escape_tool_text`, and split assistant text at the first `</think>`.

- [ ] **Step 4: Run and verify GREEN, then commit**

Run: `uv run --frozen --extra agent pytest tests/engine/test_prompt.py tests/engine/tool_syntax -q`

```bash
git add src/ds4py/engine/prompt.py src/ds4py/engine/tool_syntax/render.py tests/engine/test_prompt.py tests/engine/fixtures/hermes_history.json
git commit -m "feat(prompt): render Hermes assistant and grouped tool history"
```

### Task 6: Generic regression gate for Hermes

**Files:**
- Modify: `src/ds4py/engine/compaction.py:43-105`
- Test: `tests/engine/tool_syntax/test_stream_equivalence.py`, `tests/engine/test_compaction.py`

**Interfaces:**
- Consumes: tasks 1–5.
- Produces: `_HERMES_TOOL_MARKERS = ("<tool_call>", "</tool_call>")` included in the compaction mask for `family == "hermes"`; no Satyrn identifier anywhere in the diff.

- [ ] **Step 1: Write the failing mask test**

Assert a Hermes summary decode masks the dedicated `<tool_call>`/`</tool_call>` tokens and sanitizes their literal spellings, mirroring the Qwen marker case.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/engine/test_compaction.py -q`
Expected: FAIL — no Hermes markers.

- [ ] **Step 3: Implement, then run the whole gate**

Run: `uv run --frozen --extra agent prek run --all-files --show-diff-on-failure && uv run --frozen --extra agent pytest -m "not build and not live" -q && grep -rn -i "satyrn" src tests`

Expected: PASS, and the `grep` finds nothing.

- [ ] **Step 4: Commit**

```bash
git add src/ds4py/engine/compaction.py tests/engine/test_compaction.py
git commit -m "feat(compaction): mask Hermes tool markers in summaries"
```

### Task 7: `tool_profile` plumbing

**Files:**
- Modify: `src/ds4py/agent.py:44-108`
- Modify: `src/ds4py/agent_composition.py:22-37`
- Modify: `src/ds4py/agent_cli.py:52-80`
- Test: `tests/agent/test_agent_composition.py`, `tests/agent/test_agent_factory.py`

**Interfaces:**
- Consumes: existing `build_agent_components`, `EngineOpenOptions`, `AgentOptions`.
- Produces: `EngineOpenOptions.tool_profile: str = "auto"`; `--tool-profile auto|native|pi` on the CLI; `build_agent_components(..., tool_profile: Literal["auto", "native", "pi"] = "auto")`.

- [ ] **Step 1: Write the failing plumbing tests**

Assert the default and an explicit value reach `build_agent_components` unchanged, and that `native` output for an existing model is byte-identical to today's toolset.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/agent/test_agent_composition.py -q`
Expected: FAIL — unexpected keyword `tool_profile`.

- [ ] **Step 3: Implement the plumbing**

Thread the value through options, runtime and composition. Existing families keep `auto -> native`; explicit `native` and `pi` enable the comparison on Mellum. Planning choice: retain the existing native fallback for provisional Mellum `auto` behavior until the ruling; run the comparison with explicit profiles. This is not the accepted Mellum default: Koudai decides it after the comparison, per spec §6/§11.

- [ ] **Step 4: Run and verify GREEN, then commit**

Run: `uv run --frozen --extra agent pytest tests/agent -q`

```bash
git add src/ds4py/agent.py src/ds4py/agent_composition.py src/ds4py/agent_cli.py tests/agent/test_agent_composition.py
git commit -m "feat(agent): thread a generic tool profile through composition"
```

### Task 8: Four Pi adapters

**Files:**
- Create: `src/ds4py/capabilities/pi_profile.py`
- Create: `src/ds4py/agent_prompt_pi.py`
- Modify: `src/ds4py/agent.py:44-108`
- Test: `tests/agent/test_pi_profile.py`

**Interfaces:**
- Consumes: `FileSystemToolset.read_file` / `write` / `edit` and `ShellToolset.run_command` from installed harness 0.59.0; `Replacement` list edits.
- Produces: exactly four tools named `read`, `bash`, `edit`, `write` in that order, with the reference argument names, descriptions and order; `PI_CODING_AGENT_INSTRUCTIONS` naming only those four.

- [ ] **Step 1: Write the failing definition and behavior tests**

Assert the four definitions equal `ds4_agent_mellum_prompt.inc:8-25` except the two documented description changes (`50,000 characters` for read; `defaults to the configured ds4-py timeout of 30 seconds` for bash). Assert the 1-indexed `offset` conversion (`0` and `1` both read line 1), `limit=2000` when omitted, one atomic batch edit for `edits[]`, ambiguity/overlap rejected before writing, explicit timeout forwarded, omitted timeout using the 30-second default, and workspace/read-only enforcement.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/agent/test_pi_profile.py -q`
Expected: FAIL — no module `pi_profile`.

- [ ] **Step 3: Implement the adapters**

Wrap the existing toolsets; do not fork filesystem or shell execution, result text, retries, events or output limits.

- [ ] **Step 4: Run a real round trip**

Run: `uv run --frozen --extra agent pytest tests/agent/test_pi_profile.py -q -k roundtrip`
Expected: PASS for read, write, edit and bash in a temporary workspace.

- [ ] **Step 5: Commit**

```bash
git add src/ds4py/capabilities/pi_profile.py src/ds4py/agent_prompt_pi.py src/ds4py/agent.py tests/agent/test_pi_profile.py
git commit -m "feat(agent): expose read, bash, edit and write for the pi profile"
```

### Task 9: Profile selection gate

**Files:**
- Modify: `src/ds4py/agent.py:44-108`
- Test: `tests/agent/test_pi_profile.py`, `tests/agent/test_conformance.py`

**Interfaces:**
- Consumes: tasks 7–8.
- Produces: explicit `native`/`pi` selection for Mellum and unchanged `auto -> native` for existing families. The permanent Mellum `auto` mapping and its regression assertion are completed only after Koudai's measured ruling in the tool-comparison task.

- [ ] **Step 1: Write the failing selection tests**

Assert a Mellum fixture exposes exactly the four Pi names under explicit `pi`, explicit `native` selects the native tools, and `auto` with a Qwen fixture keeps the native names. Add the final Mellum `auto` assertion after the measured ruling.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --frozen --extra agent pytest tests/agent/test_pi_profile.py -q -k auto`
Expected: FAIL — `auto` always native.

- [ ] **Step 3: Implement, then run the whole gate**

Run: `uv run --frozen --extra agent prek run --all-files --show-diff-on-failure && uv run --frozen --extra agent pytest -m "not build and not live" -q && grep -rn -i "satyrn" src tests`

Expected: PASS, and the `grep` finds nothing.

- [ ] **Step 4: Commit**

```bash
git add src/ds4py/agent.py tests/agent/test_pi_profile.py
git commit -m "feat(agent): resolve the auto tool profile per family"
```

---

# Part B — satyrn-agent port

Work in the task worktree on `feat/mellum-support`. Engine work happens in the disposable scratch tree `.ds4/tree`; the committed `patches/` directory is the artifact. Because `ds4-check` and `ds4-export` require an existing model directory, task 10 bootstraps `patches/mellum/` with `git format-patch`; from task 11 on, `ds4-export` regenerates the directory.

### Task 10: Engine patch 0001 — model config, memory and host contract

**Status:** Implemented/exported. Published-Q8 config, binding and host-refusal results are recorded at prefix tree `d607f0f0`; the earlier different-hash runs remain historical.

**Files:**
- Create: `patches/mellum/0001-mellum-model-config-memory-and-host-contract.patch`
- Reference: `ds4_mellum_config.inc`, `ds4_mellum_plan.inc`, `ds4.c`, `ds4.h` from `pauleveritt/ds4-mellum` at `d2d9338`
- Test: `tests/test_mellum_config.c`, `Makefile` target in `.ds4/tree`

**Interfaces:**
- Consumes: `.ds4/tree` at `refs/ds4/common` produced by `ds4-sync --common-only`.
- Produces: `ds4_engine_is_mellum` returning true for `general.architecture = mellum` while `ds4_engine_is_qwen4` stays true and payload support stays false; Q8 binding and memory plan; Mellum sampling defaults of 1.0/1.0/0/0; patch trailer `Upstream: not offered, fork only` / `Retire-when: upstream runs Mellum 2.1 with this host contract`.

- [ ] **Step 1: Bootstrap the scratch tree**

```bash
devenv shell -- ds4-sync --common-only
git -C .ds4/tree switch -c mellum-port
git -C .ds4/tree remote add fork "$HOME/projects/pauleveritt/ds4-mellum"
git -C .ds4/tree fetch --quiet fork
git -C .ds4/tree checkout d2d9338 -- <the files this patch carries>
```

Select host hunks by hand from immutable reads only: `git -C .ds4/tree show d2d9338:ds4.c`, `git diff c97964b..d2d9338 -- <paths>`, and `git show <commit>`. Never read the moving `fork/mellum` branch, which has advanced past `d2d9338`.

- [ ] **Step 2: Port the model-free test first**

Copy the reference `tests/test_mellum_config.c` cases that do not need a model and its `Makefile` target into `.ds4/tree`; run `make tests/test_mellum_config && ./tests/test_mellum_config` and watch it fail before the host code exists.

- [ ] **Step 3: Implement until the model-free test passes**

Write the recognition, hyperparameter and tensor validation, Q8 binding, memory plan and session allocation, `ds4_engine_is_mellum`, sampling defaults, and the false payload predicate. Re-run the step 2 command: PASS.

- [ ] **Step 4: Run the real-model acceptance**

```bash
: "${Q8:?Set Q8 to the SHA-verified published Q8_0 GGUF}"
shasum -a 256 "$Q8"  # require 69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f
mkdir -p "$OUT"
pgrep -fl "ds4|dogfood"
make tests/test_mellum_config && DS4_TEST_MELLUM_MODEL="$Q8" ./tests/test_mellum_config > "$OUT/patch-0001-real.log" 2>&1
```

Require real validation/binding and the startup memory line; the log must contain no skip message for those sections. A host test proves `ds4_engine_is_mellum && ds4_engine_is_qwen4` and payload support false.

- [ ] **Step 5: Export and prove reconstruction**

```bash
mkdir -p patches/mellum
git -C .ds4/tree format-patch --no-signature -o "$PWD/patches/mellum" refs/ds4/common..HEAD
devenv shell -- ds4-sync --model mellum --force
devenv shell -- ds4-check --model mellum --build
```

Expected: `ds4-check` reports matching tree ids and a successful build. Then build and run the patch's own tests — `make tests/test_mellum_config ds4_test && ./tests/test_mellum_config` — because `--build` links `libds4` and never compiles the test sources. Commit the patch file with its trailers.

- [ ] **Step 6: Commit**

```bash
git add patches/mellum
git commit -m "feat(ds4): carry the Mellum model config and host contract"
```

### Task 11: Engine patch 0002 — tokenizer, chat and thinking

**Status:** Implemented/exported. Published-Q8 config, chat and 30/30 tokenizer results are recorded at prefix tree `9974c264`.

**Files:**
- Create: `patches/mellum/0002-mellum-tokenizer-chat-and-thinking.patch`
- Reference: `ds4_mellum_tokenizer.inc`, `ds4_mellum_unicode.inc`, `ds4_cli.c`, `ds4_prompt_prefix.h`, native chat hunks in `ds4.c`/`ds4.h`, `ds4_server_mellum_template.inc:190-274`
- Test: `tests/test_mellum_tokenizer.c`, `tests/test_mellum_config.c`, `tests/mellum_chat_ids.inc`

**Interfaces:**
- Consumes: patch 0001 applied by `ds4-sync --model mellum`.
- Produces: `mellum2` tokenizer and Unicode tables; special-token and stop classes pinning `<think>=23`, `</think>=24`, EOS=28; native system/assistant/tool-response rendering; think on/off; imported-history rules.

- [ ] **Step 1: Port the tests and watch them fail**

Add the reference tokenizer and chat/history cases to `.ds4/tree`, then run `make tests/test_mellum_config tests/test_mellum_tokenizer && DS4_TEST_MELLUM_MODEL="$Q8" ./tests/test_mellum_tokenizer`. Expected: FAIL.

- [ ] **Step 2: Implement**

Bring in the tokenizer, Unicode tables, token/stop classes, native chat rendering and CLI text/cap handling. Re-run step 1: 30/30 real tokenizer cases and every generated chat/history/tool-result case pass, with no `skip ids` line.

- [ ] **Step 3: Confirm the pinned ids**

```bash
DS4_TEST_MELLUM_MODEL="$Q8" ./tests/test_mellum_config > "$OUT/patch-0002-config.log" 2>&1
DS4_TEST_MELLUM_MODEL="$Q8" ./tests/test_mellum_tokenizer > "$OUT/patch-0002-tokenizer.log" 2>&1
```

Require the `<think>=23`, `</think>=24`, EOS=28 assertions to run rather than skip, and neither log to contain a skip message.

- [ ] **Step 4: Export, prove, commit**

```bash
devenv shell -- ds4-export
devenv shell -- ds4-check --model mellum --build
git add patches/mellum && git commit -m "feat(ds4): carry the Mellum tokenizer, chat template and thinking"
```

### Task 12: Engine patch 0003 (part 1) — exact Q8 Metal graph

**Status:** Implemented/exported with Task 13. Per-prefix acceptance at the 0003 clone (current tree `dc4d8de4`) passes: config, 509 kernel checks, `ds4_test --mellum-rewind` OK. The published-Q8 oracle is recorded in `docs/reports/mellum-engine-evidence.md`.

**Files:**
- Create: `patches/mellum/0003-mellum-exact-q8-metal-graph-and-rewind.patch`
- Reference: `ds4_mellum_graph_alloc.inc`, `ds4_mellum_graph.inc`, `ds4_mellum_test_hooks.inc`, `metal/mellum.metal`, guarded hunks in `metal/qwen4.metal`, `ds4_gpu.h`, `ds4_metal.m`
- Test: `tests/test_mellum_kernels.c`, `tests/mellum_trace`
- Note: the `DS4_MELLUM_EXACT_PREFILL` diagnostic (`73544c91`) and its long-prefill test land with Task 14, because the diagnostic disables that task's fast-path thresholds and cannot exist before them.

**Interfaces:**
- Consumes: patch 0002.
- Produces: exact Q8 graph, allocation, sliding/full attention, 64 routed experts with top 8, MoE, logits, and trace diagnostics. Rewind lands in task 13 and is squashed into this same patch file. The exact-prefill switch and fast-path target land in Task 14; Koudai accepted this placement and spec §4/§9 now match it.

- [ ] **Step 1: Port the model-free kernel and oracle tests first**

`make test-mellum-kernels` must fail before the graph exists.

- [ ] **Step 2: Implement the exact graph only**

No tiling, no fused decode, no Metal 4 opt-in. Re-run `make test-mellum-kernels`: PASS, and exact prefill/decode plus 64 greedy tokens match the reference oracle at `d2d9338`.

- [ ] **Step 3: Export and checkpoint**

```bash
devenv shell -- ds4-export
devenv shell -- ds4-check --model mellum --build
git add patches/mellum && git commit -m "feat(ds4): run an exact Mellum Q8 Metal graph"
```

### Task 13: Engine patch 0003 (part 2) — rewind and frontier

**Status:** Implemented/exported; published-Q8 rewind/frontier and exact-oracle results are recorded. The current prefix is `dc4d8de4`; retain the measured tree and relocation equivalence separately.

**Files:**
- Modify: `patches/mellum/0003-mellum-exact-q8-metal-graph-and-rewind.patch`
- Reference: `ds4_mellum_test_hooks.inc`, rewind/frontier hunks in `ds4.c`
- Test: `ds4_test --mellum-rewind`

**Interfaces:**
- Consumes: task 12 in `.ds4/tree`.
- Produces: session rewind and frontier with zero differing logit words; a deep rewind that cannot keep the caches resets and replays; stripped persistence behavior recorded for task 18.

- [ ] **Step 1: Implement rewind and frontier**

Add the hooks and host changes to `.ds4/tree`.

- [ ] **Step 1b: Cover the replay path**

Add `test_mellum_rewind_replay_case` to `tests/ds4_test.c` and call it with `(31, 3, 32)` and `(1100, 40, 1040)`: after a rewind that cannot keep the caches the graph resets, and the next eval equals a fresh session synced to the kept tokens. At this patch the straight-run comparison also holds; Task 14 keeps only the fresh equality.

- [ ] **Step 2: Build and run the rewind check**

```bash
make ds4_test && DS4_TEST_MELLUM_MODEL="$Q8" ./ds4_test --mellum-rewind
```

Expected: zero differing logit words at the frontier. The build is chained so a stale binary cannot pass.

- [ ] **Step 3: Squash into one patch and re-export**

```bash
devenv shell -- ds4-export
devenv shell -- ds4-check --model mellum --build
```

Expected: `patches/mellum/` still contains exactly `0001`–`0003`, with rewind inside `0003`.

- [ ] **Step 4: Commit**

```bash
git add patches/mellum && git commit -m "feat(ds4): rewind Mellum sessions to the exact frontier"
```

### Task 14: Engine patch 0004 — optimized Q8 prefill and decode

**Status:** Implemented/exported. Published-Q8 numerical reruns pass (fast paths 45/45, kernels 662 at this prefix, oracle PASS) and the corrected-harness Q8 pair is recorded; the physical M4 Max Mac Studio row remains pending on that machine.

**Files:**
- Create: `patches/mellum/0004-mellum-optimized-q8-prefill-and-decode.patch`
- Reference: tiled/batched/fused commits selected by the spec's `git log --grep` ledger
- Reference tools: `tests/mellum_cli_prefill_abba.sh`, `tests/mellum_cli_decode_abba.sh`, `tests/test_mellum_runners.sh`, `tests/mellum_prompts/prompt_2048.txt` (the prefill runner landed with T1 in `518ee06`, the decode runner in `385fbd2`, both before streaming)
- Test: `tests/test_mellum_fastpath.c`, `tests/test_mellum_runners.sh`

**Interfaces:**
- Consumes: task 13.
- Produces: tiled Q8 prefill experts/projections/attention, Metal 4 opt-in, sliding decode loads, fused small kernels; fast paths 45/45.

- [ ] **Step 1: Run the fast-path suite and watch it fail**

`DS4_TEST_MELLUM_MODEL="$Q8" make test-mellum-fastpath` fails before the kernels exist.

- [ ] **Step 2: Implement the fast paths**

Re-run: 45/45 pass and the numerical caps from `MELLUM.md` hold.

- [ ] **Step 2b: Port the A/B/B/A CLI runners**

The §2.3 and §8 rows are produced by `tests/mellum_cli_prefill_abba.sh` (108 lines) and `tests/mellum_cli_decode_abba.sh` (74), with `tests/test_mellum_runners.sh` as the model-free contract and `tests/mellum_prompts/prompt_2048.txt` as the decode input. Port them with this patch; they are the commands Task 20 runs. Do not port `tools/mellum_s4_measure.py` or its GGUF helpers — the spec's measurement command uses the C binary only.

Run: `bash tests/test_mellum_runners.sh`
Expected: PASS model-free; the scripts accept `ARMS=AA … OUT MODEL 2048`.

- [ ] **Step 3: Measure the Q8 pair on the 36 GB Mac Studio**

`pgrep -fl "ds4|dogfood"` shows nothing. On the physical 36 GB M4 Max Mac Studio, repeat the §2.3 n=6 **Q8** pair with the verified published model, immutable `d2d9338` reference and port. Each engine runs from its own tree with fresh output directories. Require port medians within 10% of the same-machine reference; another host is supplemental evidence. The MXFP4 pair belongs to Task 15. Record command, model hash, commit, machine and raw output.

- [ ] **Step 3b: Qwen kernel regression**

The fast paths touch shared attention and projection kernels. Before exporting:

```bash
make test-qwen4-kernels
```

Expected: PASS. A failure here means a Mellum path changed Qwen arithmetic, not just speed.

- [ ] **Step 4: Export, prove, commit**

```bash
devenv shell -- ds4-export && devenv shell -- ds4-check --model mellum --build
git add patches/mellum && git commit -m "feat(ds4): add the Mellum Q8 fast paths"
```

### Task 15: Engine patch 0005 — MXFP4_MOE experts

**Status:** Implemented/exported. The required current-0005 n=6 comparison is closed on the absorbed export under Nix SDK 26: MXFP4 4,071 t/s prefill / 151.38 decode against the Nix-rebuilt `d2d9338` reference's 4,063 / 150.70 (+0.20% / +0.45%), every arm `tensor_matmul=on`. Q8 across 0004→0005→0006 is 3,968 / 3,968 / 3,974 prefill and 128.23 / 128.61 / 128.28 decode against 3,979 / 127.69 (prefill within 0.28% of the reference, decode 0.42–0.72% above). The old 4,085/4,074 row was measured at 0006 on a superseded tree with a different toolchain and is history only. Physical rows remain pending.

**Files:**
- Create: `patches/mellum/0005-mellum-mxfp4-moe-experts.patch`
- Reference: MXFP4 commits from the spec's `git log --grep='MXFP4\|mxfp4'` ledger
- Test: `tests/test_mellum_config.c`, numerical fixtures

**Interfaces:**
- Consumes: task 14.
- Produces: resident MXFP4_MOE expert loading and kernels, uniform-expert validation and numeric fixtures; unsupported or mixed quants fail by name. Streamed slot sizing and the S6-era tiled kernel tests land in Task 16 with their address-table dependencies. Python expert-index/pack tooling is excluded.

- [ ] **Step 1: Write the failing quant-identity tests**

Both SHA-verified files load; a mixed or unknown quant fails by name; MXFP4 reference logits are pinned.

- [ ] **Step 2: Run and verify RED, then implement**

Re-run until MXFP4 reference logits pass.

- [ ] **Step 3: Prove Q8 did not regress, and measure the MXFP4 pair**

Repeat the published-Q8 resident n=6 pair on the same machine before/after 0005: medians must not regress by more than 10%. Then run the SHA-verified MXFP4 pair through the ported runners against immutable `d2d9338` on that same machine and require medians within 10% of the reference. Each engine uses its own working directory/shaders and fresh output directories. The physical Mac Studio row remains required by §8.

- [ ] **Step 4: Export, prove, commit**

```bash
devenv shell -- ds4-export && devenv shell -- ds4-check --model mellum --build
git add patches/mellum && git commit -m "feat(ds4): load Mellum MXFP4_MOE experts"
```

### Task 16: Engine patch 0006 — SSD expert streaming

**Status:** Implemented/exported. Both quants' 3/3 resident/streamed parity is reported at `8b8ef87a`; the JSON currently relabels it as `ca243153` without new raw runs. Correct that provenance and record final combined-stack parity. Physical 16 GB / 8 GB gates remain open. See [evidence](../../reports/mellum-engine-evidence.md).

**Files:**
- Create: `patches/mellum/0006-mellum-ssd-expert-streaming.patch`
- Reference: `ds4_mellum_stream.c`, `ds4_mellum_stream.h`, streaming hunks in `ds4.c`, `ds4.h`, `ds4_metal.m`, `ds4_mellum_graph.inc`
- Reference tool: `tools/mellum_s4_measure.c`
- Test: `make test-mellum-stream`

**Interfaces:**
- Consumes: task 15.
- Produces: stream config, uncached descriptor, slot cache, stop/resume decode, overlapped loads, grouped layer-major prefill, read-fault handling.

- [x] **Step 1: Run the stream suite and watch it fail**

`make test-mellum-stream` fails before the scheduler exists.

- [x] **Step 2: Implement, then prove exactness**

Streamed and resident greedy ids agree for 512 tokens in 3/3 runs per quant.

- [x] **Step 3b: Port the resident-versus-streamed measure driver**

`tools/mellum_s4_measure.c` (237 lines) is what the spec's §2.5 and §8 32K rows are measured with, and it consumes the streaming and Metal-allocation hooks this patch adds. Add it and its `tools/mellum_s4_measure` Makefile target; it is not part of `make all`. The Python orchestrator (`mellum_s4_measure.py` and its GGUF helpers) is not required by the spec's command and stays out.

Run: `make tools/mellum_s4_measure`
Expected: the binary exists and accepts `--model … --prompt … --gen 512 --context 32768 --out …`.

- [ ] **Step 3: Run the physical gates**

16 GB Mac mini: MXFP4 resident first, then Q8 with `--ssd-streaming --ssd-streaming-cache-experts 6GB`. 8 GB case: MXFP4 with `--ssd-streaming --ssd-streaming-cache-experts 2GB`, context 32768. Record the Metal limit, planned bytes, Metal peak, host footprint, swap before/after, first token, prefill, generation, command, commit and `n`. No row passes with swap growth or 2.5 GiB.

- [x] **Step 4: Export, prove, commit**

```bash
devenv shell -- ds4-export && devenv shell -- ds4-check --model mellum --build
git add patches/mellum && git commit -m "feat(ds4): stream Mellum experts from the SSD"
```

### Task 17: Qwen prefix after PR #24

**Files:**
- Modify: `patches/qwen35/*.patch` (re-exported, not edited by hand)

**Interfaces:**
- Consumes: patches 0001–0006 from tasks 10–16; satyrn-agent PR #24 merged.
- Produces: the complete qwen35 series rebased after `mellum`, with unchanged Qwen behavior.
- Prerequisite: per spec §2.2 and §10, PR #24 merges **before** Mellum implementation and both owners are told. It changes qwen35 0001–0008, adds 0009–0018, and changes `tools/ds4-check.sh`, so the rebase covers the then-current 18-patch series, not the eight files we have today.

**Status:** implementation done on 2026-11-21 against `eed5c4f` (PR #24 plus #32, merged 08:25:48Z). The eighteen
commits rebase onto `f2c40f41` without merge commits; the export reconstructs every boundary and ends at
tip `320627f2`. Two semantic conflicts are resolved in the qwen35 patches, where the newer series wins:
0002 restores #24's rendering of a system turn's `<tool_call>` and of the `<tool_response>` wrapper as
the template's added tokens for every qwen4 shape (the Mellum prefix narrows that to Mellum only, which
predates qwen35 0002 and was never meant to override it), and 0004 keeps the Qwen family's
0.6 / 20 / 0.95 / 0 defaults. Both changes touch `tests/test_mellum_config.c`, whose Flash Next sibling
and generic-shape assertions described the Mellum-only prefix; they are updated in the same patches.

- [x] **Step 1: Confirm the qwen35 prefix breaks before the rebase**

Observed on the pre-rebase tree: `ds4-tools` failed applying qwen35 0001 after the Mellum prefix.

- [x] **Step 2: Rebase and re-export the whole series**

`ds4-sync --model qwen35` cannot be the first move: it applies the whole prefix, and Qwen's first patch already fails after Mellum. Instead:

```bash
# 1. in ONE scratch repository, materialize the old common+qwen stack and keep its refs
DS4_PATCHES_DIR=<patches without mellum> DS4_TREE_DIR=.ds4/qwen-old devenv shell -- ds4-sync --model qwen35
git -C .ds4/qwen-old update-ref refs/port/qwen-old refs/ds4/model/qwen35
# 2. fetch that ref into the Mellum tree, and cherry-pick the range onto the Mellum tip
git -C .ds4/tree fetch ../qwen-old refs/port/qwen-old:refs/port/qwen-old
git -C .ds4/tree cherry-pick refs/ds4/common..refs/port/qwen-old
```

Resolve textual and semantic conflicts, then export the candidate series and prove pristine reconstruction before replacing `patches/qwen35/`. Do not hand-edit patch files.

- [x] **Step 2b: Re-run the tooling against #24's check script**

```bash
bash tests/ds4_tools_test.sh
```

Expected: PASS with #24's `ds4-check.sh` in the tree, before any boundary result is trusted. Result: 50 passed, 0 failed.

- [x] **Step 3: Prove every boundary**

```bash
devenv shell -- ds4-check --model qwen35 --build && devenv shell -- ds4-check --build
```

Expected: PASS for the qwen35 prefix and every boundary, including the full tree. Result: the pristine
reconstruction equals the tree at every boundary and all three builds (`common`, `mellum`, `qwen35`) pass.

- [x] **Step 4: Run the Qwen regressions**

`make test-qwen4-kernels` passes (all qwen4 kernel tests), `make test-mellum-kernels` passes (992 checks,
0 failures), and `pytest tests/abnormal tests/e2e/live` gave 48 passed, 1 failed at the time. The failure was
`test_harness_tui`'s `error: model response ended with max_tokens` on the round after `/switch`; it also
reproduced on a `ds4py build` of `eed5c4f`'s own qwen35 series. It is now **fixed** (#34): the harness put
the wall clock into a system note, so the round's length was date-dependent; PR #40 pins the clock
(`e032345`, `4e56bdf`) and the live suite is 49/49 with the original 256-token caps. My earlier cap raise
(`3a30dd3`) was superseded and is reverted here; the restore itself was verified identical (3,906 tokens,
36 segments, 7 user turns) throughout.
of every Qwen behavior. Preserve both build identities and track the failing acceptance explicitly.
The recorded DFlash parity and metric cases pass.

Run the existing Qwen live DFlash and kernel checks and require the recorded numbers to hold. Commit the re-exported series.

### Engine closure before pushing PR #29

This checklist is the current execution order; earlier task steps describe the
original implementation procedure. The spec's Task 19 (controls and stripped
save/rendered switch) is included in this plan's Task 18. The plan's Task 19 is
the spec's Task 21 (tool comparison); keep these names in handoffs.

- [x] **Fix the missing include dependencies, with a failing regression first.**

In the scratch engine, cover changes to `ds4_mellum_config.inc`, `plan.inc`,
`tokenizer.inc`, `unicode.inc`, `graph_alloc.inc`, `graph.inc` and `test_hooks.inc`
for every object that compiles or directly includes `ds4.c`, including CPU and
test-hook objects. With otherwise up-to-date objects, `make -n -W INCLUDE OBJECT`
must schedule compilation; the review reproducer currently reports "up to date".
Add dependencies at their introducing patch boundaries, keep `all` as the default
Make target, re-export the owned Mellum and dependent qwen35 series, and verify
the six Mellum prefixes still build from pristine trees.

Result: `tests/ds4_series_deps_test.sh` reproduces the review's four cases as
failures on the old export (every boundary) and passes after the fix. Each
Mellum patch adds its includes to `MELLUM_DS4_INCS` at its introducing boundary
(0001 config/plan, 0002 tokenizer/unicode, 0003 graph_alloc/graph/test_hooks);
the group rule names every `ds4.c` consumer, the two qwen35 test objects join it
in the patches that add them, and `.DEFAULT_GOAL` stays `all`. Exports: Mellum
tip `9892cc0a`, combined tip `b4a71c81`. `ds4-check --build` passes for common,
Mellum and qwen35; the shell suite is 53/53; `make test-mellum`,
`test-mellum-kernels` (992 checks) and `test-qwen4-kernels` pass.

- [ ] **Fix the common Metal pin's math mode before trusting any performance number.**

`patches/common` 0002/0003 set `MTLCompileOptions.languageVersion` without `mathMode`, so every
patched build compiles shaders at strict IEEE-754 and loses ~43% prefill (port 2,330 t/s against the
reference's 4,135 t/s on the same MXFP4 prompt). Adding `options.mathMode = MTLMathModeFast;` restores
4,081 / 4,078 t/s and the current-0005 MXFP4 gate passes (prefill +0.07%, decode -2.3%). Evidence and
the ablation table are in [mellum-engine-evidence.md](../../reports/mellum-engine-evidence.md#common-layer-metal-math-mode-regression-2026-11-21).
Changing common re-exports common → Mellum → qwen35, so re-run the oracle, the 992 kernels, the shell
and static gates, and the prefix performance pairs, and disclose the change in the PR body. Main
carries the same cost until this lands.

- [x] **Reconcile the evidence before claiming current acceptance.**

Keep raw `ece0d5fe`/`8b8ef87a` runs attached to those measured trees; record any
source-equivalence claim separately. Capture the current-0005 MXFP4/reference
n=6 comparison. Result: historical runs keep their measured identities (`ece0d5fe`/`8b8ef87a`); the canonical series is
on the absorbed export (`d7b36619`/`fff1d8f9`, combined `db39d137`/`4d987745`) under the Nix toolchain
with `apple-sdk_26`, where every arm reports `tensor_matmul=on`. Current-0005 MXFP4 is 4,071 t/s prefill
and 151.38 t/s decode against the Nix-rebuilt reference's 4,063 / 150.70 (+0.20% / +0.45%); Q8 is flat
within 0.3% across 0004→0006 and against the reference. Streaming parity is exact on 512 ids for both
quants (Q8 3+3, 979 slots; MXFP4 3+3, 652 slots). The oracle passes against the Nix-SDK-26 reference
(exact prefill byte-equal, optimized 63/65 at 1,100 with permitted near-ties and 65/65 at 2,200, greedy
64/64 equal logits). Qwen's live suite is **49/49** after #40's clock pin (`e032345`, `4e56bdf`); the old
48/49 was date-dependent generation length, not a restore defect. The cap raise (`3a30dd3`) was reverted
in favour of the pinned clock.

On the final combined export, rebuild the test executables and
run Mellum config/tokenizer, 992 kernels, rewind, fast paths, the published-Q8
oracle and 512-token parity (3 resident + 3 streamed per quant), retaining raw
IDs and exact commit/tree/model/prompt identities. Run Qwen kernel/DFlash/live
regressions; carry the existing `/switch` failure as an explicit baseline issue
with the old/new build identities rather than reporting all live tests passing.

- [ ] **Make PR #29 describe the reviewable result, then push without force.**

Base the description on main `eed5c4f`; describe the engine plus Task 17, new
prefix IDs, the shared-code relocation, the two qwen35 semantic resolutions,
and the build-dependency fix. Remove the obsolete design questions, "not a
merge request", and "qwen35 not in this PR" language. Name each pending physical
or harness acceptance item and its owner. Check the actual remote head remains
an ancestor before pushing; the inspected local branch descends from `8ccc4fc`.

- [ ] **Require fresh CI for the pushed head before merging the engine checkpoint.**

All checks must describe that head; the existing red result belongs to `8ccc4fc`.
In particular verify Linux CPU builds as well as local Metal gates. Seek focused
technical review of the post-approval changes without reopening the accepted
layout/placement decisions. Notify Koudai and Roché that the full 18-patch rebase
is complete; notification requires the user's instruction to post. After the
description is accurate and checks pass, make ready and merge with the existing
merge-commit convention. Do not claim Tasks 10–16 fully accepted while physical
or per-prefix performance gates remain open.

Run the physical matrix/current-0005 measurement and companion A/B handoff as
independent workstreams. Follow with Task 18, the 120-run tool comparison and
Koudai's default-profile ruling, then full product acceptance. Waiting for the
small machines need not block preparing the companion or harness work.

### Task 18: Companion pin, recommended sampling and Mellum control behavior

**Files:**
- Modify: `pyproject.toml:11`
- Modify: `src/satyrn_agent/capabilities/sampling.py`
- Modify: `src/satyrn_agent/engine.py:52-72`
- Modify: `src/satyrn_agent/controller.py`
- Create: `tests/e2e/scenarios/mellum-plain-footer.json`, `tests/e2e/scenarios/mellum-drafter-rejected.json`, `tests/e2e/scenarios/mellum-nothink-budget.json`, `tests/e2e/scenarios/mellum-stripped-persistence.json`
- Create: `tests/e2e/corpus-mellum.json`
- Modify: `tests/e2e/corpus.py`
- Test: `tests/e2e/model_free/test_engine.py`, `tests/e2e/model_free/test_harness_commands.py`

**Interfaces:**
- Consumes: the two ds4-py companion commits (tasks 1–9) for `--tool-profile`, `is_mellum`, and the Hermes protocol; `merge_sampling`.
- Blocked by: companion PRs A and B reviewed and merged into `rochecompaan/ds4-py`, as required by spec §10. Use one reviewed dependency commit containing both companions, and record both PR/commit identities. PR #29 approval does not unblock this dependency.
- Produces: `MELLUM_RECOMMENDED: SamplingPolicy` (0.6 / 0.95 / 20); `merge_sampling(base, native, recommended, overrides, seed)` with the order `native → recommendation → overrides`; `DFlashUnavailable("Mellum has no DFlash drafter; unset drafter_path")` raised before mutation; `corpus.py` honouring `SATYRN_TEST_CORPUS`.

- [ ] **Step 1: Write the failing sampling-precedence test**

Assert `native → Mellum recommendation → project → CLI → request`, that an explicit `temperature=0.0` and `min_p=0.0` survive, and that a Qwen fixture still reports its own native defaults.

- [ ] **Step 2: Run and verify RED**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free/test_engine.py -q`

- [ ] **Step 3: Implement the sampling layer and pin the companions**

Insert the recommendation between native defaults and overrides in `SatyrnEngine.session()`, and update the `ds4py[agent]` pin to one reviewed descendant containing both merged companions.

- [ ] **Step 3b: Define the no-drafter fixture and corpus**

The live fixture requires and validates `SATYRN_TEST_DRAFTER`, and `corpus.json` always supplies a drafter path, so "run the live controls without a drafter" is not executable as written. Add an explicit no-drafter contract: a `tests/e2e/corpus-mellum.json` target with no drafter block, a live fixture that accepts a missing drafter for a hermes engine, and the control cases (`/dflash` off/auto/on, think budget on/off/off-then-reset, stripped save/switch). Changing only the corpus filename does not deliver this gate.

- [ ] **Step 4: Write the four failing scenario tests**

`mellum-plain-footer` (hermes `EngineInfo` records with scripted no-drafter config → `dflash: auto/off, accept — (0/0)` and no offered/accepted drafts), `mellum-drafter-rejected` (drafter path plus hermes family → Mellum error, history and footer unchanged), `mellum-nothink-budget` (reasoning outside a think block is not biased), `mellum-stripped-persistence` (`payload_bytes=0`, no KV file; `/compact` reports its existing unsupported error).

- [ ] **Step 5: Implement until the scenarios pass**

Run: `devenv shell -- uv run --frozen pytest tests/e2e/model_free -q --cov=satyrn_agent --cov-branch --cov-fail-under=100`
Expected: PASS at 100% line and branch.

- [ ] **Step 6: Run the real Metal control acceptance**

With `SATYRN_TEST_MODEL` and `SATYRN_TEST_LIB` set and no drafter, run the live control tests plus the new Mellum corpus. Require `/dflash` off/on behavior, think-budget on/off, and a real stripped save/switch.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/satyrn_agent tests/e2e
git commit -m "feat(satyrn): add Mellum sampling, DFlash and persistence behavior"
```

### Task 19: Tool-profile comparison (spec Task 21)

**Files:**
- Create: `tests/e2e/live/mellum_tool_bakeoff.py`
- Create: `tests/e2e/live/fixtures/tool_bakeoff/` (`hello.py`, `main.py`, `helper.py`, `test_main.py`)
- Create: `docs/reports/mellum-tool-bakeoff.md`

**Interfaces:**
- Consumes: `--tool-profile` from task 7, the ds4-py agent runtime, `SATYRN_TEST_MODEL`.
- Produces: 120 runs (6 task types × 5 seeds × 2 profiles × 2 quants), every JSONL record kept, Wilson 95% intervals and a paired exact test in the report.

- [ ] **Step 1: Build the runner and the fixture workspace**

Six graders: read `hello.py` and report output; write `hello.py` with `greet()`; change the greeting exactly once; run `python3 hello.py`; read → edit → run in one session; change `main.py` and `helper.py` so `test_main.py` passes. Reset the fixture before every run; grade file bytes and process output, never the model's self-report.

- [ ] **Step 2: Run one smoke pair per profile**

Run: `devenv shell -- uv run --frozen python tests/e2e/live/mellum_tool_bakeoff.py --model "$Q8" --profiles native,pi --repetitions 1 --out /tmp/bakeoff-smoke`
Expected: 12 records, fixture reset between runs.

- [ ] **Step 3: Run the full comparison on the 36 GB Mac Studio**

```bash
devenv shell -- uv run --frozen python tests/e2e/live/mellum_tool_bakeoff.py --model "$Q8" --profiles native,pi --order alternating --repetitions 5 --out RESULTS_Q8
devenv shell -- uv run --frozen python tests/e2e/live/mellum_tool_bakeoff.py --model "$MXFP4" --profiles native,pi --order alternating --repetitions 5 --out RESULTS_MXFP4
```

Every run pins context 32768, the recommended sampling (0.6 / 0.95 / 20), resident execution with both quants, a fresh session per task, and records all required metrics (completed-task rate, valid-call rate, malformed calls, retries, wrong-tool calls, turns, generated tokens, wall time). 15 native-first and 15 Pi-first starts per quant. The order alternates on **grader parity**: odd grader numbers run native then Pi, even numbers the reverse. It also alternates on **seed parity**, so `--order alternating` must implement both and the aggregate must come out 15/15 for each quant. Add a model-free test over seeds 1–5 that asserts each pair's order from the JSONL records and the 15/15 split.

- [ ] **Step 4: Report and record the ruling**

Write `docs/reports/mellum-tool-bakeoff.md` with the reproducible table, every run, the intervals and the paired test. Add the model-free test that pins whichever `auto` mapping Koudai rules on; do not select on speed alone.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/live/mellum_tool_bakeoff.py tests/e2e/live/fixtures/tool_bakeoff docs/reports/mellum-tool-bakeoff.md
git commit -m "test(e2e): compare native and pi tool profiles on Mellum"
```

### Task 20: Memory matrix on physical targets (spec Task 20)

**Files:**
- Create: `docs/reports/mellum-memory-acceptance.md`

**Interfaces:**
- Consumes: patches 0001–0006 and a built `libds4`.
- Produces: one row per target with command, commit and tree, model/prompt hashes, machine, `n`, Metal limit, planned bytes, Metal peak, host footprint, swap before/after, first token, prefill and generation. Koudai owns 36/24/16 GB; Paul owns 8 GB. This task consumes the engine and can run independently of Task 18. Capture the limit/startup plan from stderr and swap before/after separately: the C driver JSON does not contain every required field.

- [ ] **Step 0: Pin the inputs**

The 2,686-token request is pinned in the fork's evidence, not in §8: `workload-request.json` (`73cd5f77…`), flattened by `flatten.py` into `workload-prompt.txt` (`2f34a817…`, 8,770 B, 2,686 rendered tokens) on branch `mellum-evidence-2026-10-31` (`docs/superpowers/research/2026-10-28-mellum-s6-c-preregistration.md:70-75`). Vendor that exact artifact as `tests/mellum_prompts/prompt_2686.txt`, verify its full SHA-256 and rendered token count, and feed the same file to the `ds4-mellum` reference and the port runs. Do not write a new request and name it after the count.

- [ ] **Step 1: 36 GB Mac Studio**

Both quants resident at context 32768. Repeat §2.3 at context 3072 with n=6 through the ported runners:

```bash
ARMS=AA tests/mellum_cli_prefill_abba.sh "$OUT/mxfp4-prefill" "$MXFP4" 2048
ARMS=AA tests/mellum_cli_decode_abba.sh "$OUT/mxfp4-decode" "$MXFP4" tests/mellum_prompts 2048
```

Then measure `ds4-mellum` `d2d9338` and the port at 32768 with the pinned request, n=3 per quant:

```bash
tools/mellum_s4_measure --model "$MODEL" --prompt tests/mellum_prompts/prompt_2686.txt \
  --gen 512 --context 32768 --out "$OUT/QUANT-RUN.json"
```

Port medians within 10%, exact greedy ids, peak no more than 5% above the same-machine reference, no swap growth.

- [ ] **Step 2: 24 GB MacBook Air**

Both quants resident at 32768, n=3 each. 13.032 GiB Q8 and 7.317 GiB MXFP4 are the reference observations, not the requirement: record the port's measured Metal limit, planned bytes and peak, require the peak below the machine's actual limit with no swap growth and exact ids. The reference run's 596.87 MiB swap growth is not a pass.

- [ ] **Step 3: 16 GB Mac mini**

MXFP4 resident first, then Q8 streamed with a 6GB expert cache (`--stream-bytes 6442450944` in the C driver). Copy only the quant under test; touch nothing else. Record the measured Metal limit, planned bytes and peak, require the peak below that limit, no swap growth, and exact ids against a resident baseline captured on a machine that fits the same model/prompt/context. Do not run resident Q8 on the 16 GB machine to obtain that baseline.

- [ ] **Step 4: 8 GB streaming case**

Paul runs MXFP4 only, 2GB cache (`--stream-bytes 2147483648` in the C driver), context 32768, apps closed, n=3. Require no swap, peak below the measured Metal limit, exact ids against the same-input resident baseline from a larger machine, and generation at least 5.0 t/s. Do not run a resident baseline on the 8 GB machine.

- [ ] **Step 5: Publish and commit**

Mark the Air's controlled no-swap gate open until it passes, and the 8 GB row pending if unrun. Commit the report.

### Task 21: Final repository gates (spec Task 22)

**Files:**
- Modify: any file a gate failure implicates

**Interfaces:**
- Consumes: tasks 10–20.
- Produces: a green static gate, portable shell suite, model-free coverage and live Mellum+Qwen acceptance.

- [ ] **Step 1: Static and portable gates**

```bash
devenv shell -- uv run --frozen prek run --all-files --show-diff-on-failure
bash tests/ds4_tools_test.sh
devenv shell -- uv run --frozen pytest tests/e2e/model_free --cov=satyrn_agent --cov-branch --cov-report=term-missing --cov-fail-under=100
actionlint .github/workflows/ci.yml .github/workflows/ds4-tools.yml
```

Expected: all pass.

- [ ] **Step 2: Reconstruction gates**

```bash
devenv shell -- ds4-check --model mellum --build
devenv shell -- ds4-check --model qwen35 --build
devenv shell -- ds4-check --build
```

Expected: PASS at every boundary.

- [ ] **Step 3: Live acceptance**

Run the live Mellum and Qwen suites with no skipped branches. No model-free result is reported as live parity.

- [ ] **Step 4: Commit and request review**

```bash
git add -A && git commit -m "chore: final Mellum acceptance"
```

The engine checkpoint is PR #29. Open the follow-up Satyrn integration PR from a new branch based on the merged engine checkpoint, link the remaining acceptance artifacts, and run `pr-review-loop`.
