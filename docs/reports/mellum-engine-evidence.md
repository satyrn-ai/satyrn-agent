# Mellum engine evidence

Historical evidence for `patches/mellum/0001`–`0005`, followed by fresh 0006 validation.
The machine is an Apple M5 Max (128 GiB); the immutable reference is `pauleveritt/ds4-mellum` at `d2d9338`.

**Model provenance correction (2026-11-18):** the Q8 path used in the older commands below currently hashes
to `ea1e4ec737bb259ac2ffe1f20d412f458fd52dd230f42dce9e944f111093c29b`, not the spec's published
`69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f`. Its size matches, so size alone
missed the difference. Those historical commands do not establish acceptance against the published file;
the affected oracle and performance gates need repeating. Fresh 0006 runs use the SHA-verified published
blob already in the Hugging Face cache. The existing file in `~/models` was not changed.

## 64 greedy token ids match the fork (0003)

```bash
Q8="$HOME/models/Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf"
PROMPT="Write a Python function that adds two integers."   # 29 tokens
./ds4 -m "$Q8" --metal -c 4096 --temp 0 -n 64 --seed 1 --dump-logprobs /tmp/ours.json -p "$PROMPT"
cd ~/projects/pauleveritt/ds4-mellum && ./ds4 -m "$Q8" --metal -c 4096 --temp 0 -n 64 --seed 1 --dump-logprobs /tmp/ref.json -p "$PROMPT"
python3 -c "import json;a=[s[\"selected\"][\"id\"] for s in json.load(open(\"/tmp/ours.json\"))[\"steps\"]];b=[s[\"selected\"][\"id\"] for s in json.load(open(\"/tmp/ref.json\"))[\"steps\"]];print(len(a),a==b)"
```

Result: `64 True` — zero id mismatches. First twelve ids: 23, 233, 2116, 895, 333, 6246, 434, 255, 99, 2717, 669, 410.

## Exact prefill and the fast paths (0004)

```bash
DS4_TEST_MELLUM_MODEL="$Q8" ./ds4_test --mellum-exact-prefill --mellum-rewind
DS4_TEST_MELLUM_MODEL="$Q8" make test-mellum-fastpath
```

- exact prefill vs decode: 0 of 98,304 logit words differ under `DS4_MELLUM_EXACT_PREFILL=1`, 98,301 without.
- rewind: 500/1 and 1100/1 keep both caches (0 differ); 1100/3 restores from the sync end (0 of 294,912);
  the frontier case and the one-token-onto-the-frontier case differ in 0; a replay equals a fresh sync.
- fast paths: 45 checks, 0 failures.

## Kernels, trace, tokenizer

- `make test-mellum-kernels`: 509 checks, 0 failures.
- `DS4_TEST_MELLUM_MODEL="$Q8" sh tests/test_mellum_trace.sh`: PASS (untraced = fully traced at chunk 1024 and 2).
- `DS4_TEST_MELLUM_MODEL="$Q8" ./tests/test_mellum_tokenizer`: 30/30 ids equal the reference encode.
- `tests/gen_mellum_chat_ids.py` (fork version) regenerates `tests/mellum_chat_ids.inc` with no diff.

## Same-machine performance (0004, Q8, resident, context 3072, n=6)

```bash
ARMS=AA tests/mellum_cli_prefill_abba.sh "$OUT/prefill" "$Q8" 2048
ARMS=AA tests/mellum_cli_decode_abba.sh "$OUT/decode" "$Q8" tests/mellum_prompts 2048
```

The reference binary is built from the immutable commit (`git -C ~/projects/pauleveritt/ds4-mellum worktree add
/tmp/ds4-ref d2d9338 && make -C /tmp/ds4-ref ds4`), not from the fork's moving `mellum` branch. Each engine runs
**from its own tree** — the port with cwd `.ds4/tree`, the reference with cwd `/tmp/ds4-ref` — because the shaders
are loaded from `metal/*.metal` relative to the working directory, and each invocation writes a fresh output
directory, so no two runs share `setup.txt`, stderr files or `runs.txt`.

| Run | n | Median | Range |
|---|---|---|---|
| Prefill, port | 6 | 3,902 t/s | 3,894–3,972 |
| Prefill, `d2d9338` reference | 6 | 3,918 t/s | 3,908–3,944 |
| Decode, port | 6 | 124.67 t/s | 116.17–125.78 |
| Decode, `d2d9338` reference | 6 | 126.55 t/s | 126.26–126.71 |

Both pairs are within 1.5% of the same-machine reference, each engine loading its own shaders.

## MXFP4 (0005), historical validation

A valid same-machine MXFP4 performance comparison is still pending. The previous table repeated the Q8
values, and the earlier harness reused output directories and loaded the port's shaders in the reference
process. Those timings cannot establish the 0005 performance gate. Repeat it with the corrected harness
and verified model files before publishing the memory matrix.

Q8 non-regression after 0005: prefill 3,814 t/s and decode 118.75 t/s against 3,987 / 125.08 before the MXFP4
loaders — 4.3% and 5.1% down, inside the 10% cap. `ds4_test --mellum-moe` on the MXFP4 file passes (weights,
selection and the staged double reference), and `tests/test_mellum_config` opens it, refusing every mixture.

The MXFP4 file verifies: sha256 `cf09584a…8166`, 7,029,537,056 bytes. These are M5 Max numbers; the spec's §2.3 figures
(1,515 / 88.19 t/s) are the M4 Max Mac Studio baseline, so the acceptance is the same-machine comparison.

## SSD streaming (0006), fresh reconstructed-artifact validation

Engine `fd27653b490993a878eb3e445937d1ee19171345`; tree `3130743ca6021711109b4a2248ffbb2e5acc9ef9`.
Context 32768, 512 greedy tokens, three fresh resident/streamed process pairs per quant. A fixed
source-review prompt has SHA-256 `9ffb86b1daf612005f004fc77a495ebb2f7f4ed2b6d2ed758847690403daad8a`.
Resident and streamed IDs match at all 512 positions in all three pairs for each quant; all three
repetitions also agree. The prompt has 3431 rendered tokens. Context capacity is 32768 tokens.

Q8 uses the published SHA-verified HF cache blob; MXFP4 uses the SHA-verified file in `~/models`.
One inference executable ran at a time, from its own reconstructed checkout, with a unique output
file per run. Run order was resident/streamed, streamed/resident, resident/streamed.

| Quant | Resident/streamed agreement | Stream cache | Effective slots |
|---|---|---|---|
| Q8_0 | 512/512 IDs, 3/3 pairs | 6 GiB | 979 |
| MXFP4_MOE | 512/512 IDs, 3/3 pairs | 2 GiB | 652 |

Verification:

- `ds4-check --model mellum --build`: exact source/reconstructed tree match and libds4 build.
- `make test-mellum`: model-free config, tokenizer, scheduler (56 checks), trace setting (4 checks), and non-Apple shared-engine syntax check pass.
- `make test-mellum-kernels`: 992 checks pass with `tensor_matmul=on`; Qwen kernel regressions pass.
- All ten native streaming tests pass on each quant: identity, prefill, slabs, read fault, stopped scratch, failed load/cancel, close(NULL), grouped memory, grouped prefill, grouped events.
- C driver smoke: three tests pass on Q8, including warm-session append and effective-slot reporting. Its hardcoded 979-slot expectation is Q8-specific; do not run that smoke unchanged on MXFP4.
- Metal tensor lifetime: retained-buffer regression RED, then all access arms return to starting allocation GREEN.
- Old-SDK host compatibility: SDK 14.2 host selected Metal 3.1 RED, then explicit Metal 3.2 GREEN under SDK 15. Apple SDK 27.2 retains Metal 4.0.
- Non-Apple GPU compile: eight undeclared globals RED, then GREEN after guarding the Apple test hooks.
- Final portable gates: static checks pass; 49 shell tests pass; 116 model-free Python tests pass at 100% line and branch coverage.

The pinned devenv SDK 15 exercises the fallback build. GPU gates and model runs use Apple clang from
Xcode 27.2 after entering devenv, explicitly setting `DEVELOPER_DIR` and `SDKROOT`; `/usr/bin/clang`
alone redirects through devenv and does not select Apple’s toolchain.

The 0004 artifact also had an accidental generated Mach-O test binary. It has been removed from that
topic and descendants; its source remains. The common Metal 3.2/4.0 helper is preserved. No Python
measurement orchestrator, GGUF reader, or C frontend cases were added.

Commands, per-run ID hashes, RSS/physical footprint/Metal allocation peaks, timing, slot counts and
swap snapshots are in [mellum-task16-summary.json](mellum-task16-summary.json). Raw driver JSON,
complete native logs, the frozen prompt and validation scripts remain in
`.superpowers/sdd/2026-11-16-mellum-support/task16-evidence/` (ignored build/diagnostic evidence).

**Acceptance still pending:** physical 16 GB / 8 GB rows and their no-swap/working-set/speed requirements remain Task 20 gates. These 128 GiB host runs establish local exactness, not target memory fit. Historical Q8 oracle/performance and the invalid MXFP4 timing rows above also need rerunning. Task 17 cannot begin its Qwen rebase until PR [#24](https://github.com/satyrn-ai/satyrn-agent/pull/24) merges; it was OPEN when checked.
