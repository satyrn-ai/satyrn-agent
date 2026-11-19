# Mellum engine evidence

Historical evidence for `patches/mellum/0001`–`0005`, followed by fresh 0006 validation.
The machine is an Apple M5 Max (128 GiB); the immutable reference is `pauleveritt/ds4-mellum` at `d2d9338`.

**Model provenance correction (2026-11-18):** the Q8 path used in the older commands below currently hashes
to `ea1e4ec737bb259ac2ffe1f20d412f458fd52dd230f42dce9e944f111093c29b`, not the spec's published
`69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f`. Its size matches, so size alone
missed the difference. Those historical commands do not establish acceptance against the published file;
the affected oracle and performance gates need repeating. Fresh 0006 runs use the SHA-verified published
blob already in the Hugging Face cache. The existing file in `~/models` was not changed.

## Patch discipline checkpoint (2026-11-18)

The current export is `71f694084a31f3b1f8773cc367bcbdb92dd1c255`. A commit-message cleanup regenerated the patches from real engine
commits with `ds4-export`; every one of the six source trees is identical to its pre-cleanup tree.
The final tree remains `3130743ca6021711109b4a2248ffbb2e5acc9ef9`. The fresh native results below
and `mellum-task16-summary.json` retain their original validated commit, `fd27653b`, rather than
pretending new model runs occurred after the metadata cleanup.

All six patches now have the three required trailers. The duplicate `f160af74` was removed from
0004's ledger and 0006 uses the specification's exact retirement condition. The restored 0005 ledger
contains eight resident MXFP4 product/test commits. Its old 13-entry list also named two kernel-test
commits now carried by 0006 (`fe2001bd`, `d49c06cb`) and three Python expert-index/pack commits excluded
from this port (`48c5b937`, `e2273c99`, `a9fd4f8e`). Those excluded tools are not claimed as carried.
The 0003–0005 messages now qualify historical numerical and performance evidence.

Two design discrepancies remain explicit:

- **Patch boundary:** the exact-prefill diagnostic and `test-mellum-fastpath` target land in 0004,
  alongside the fast-path thresholds they control. Specification §4 assigns them to 0003, so its
  0003 fast-path command cannot run at that prefix. This is a recorded deviation for Koudai's review;
  the specification has not been rewritten to imply approval. The 0003 exact graph, trace and rewind
  gates remain required; the diagnostic and fast-path gates remain required at 0004.
- **Integration sequence:** specification §2.2/§10 requires PR #24 to merge before Mellum implementation.
  Implementation proceeded before that prerequisite. PR #24 was still OPEN at this checkpoint, and
  Qwen's first patch fails a non-mutating apply check against the Mellum tip in `ds4.c` and
  `ds4_metal.m`. Common+Mellum reconstructs, but the complete model stack is not integrated or accepted.
  Task 17 must use the complete then-current Qwen series after #24 merges. Owner coordination is not
  claimed by this checkpoint.

| Acceptance item | Current status and remaining work |
| --- | --- |
| 0001–0002 real Q8 config/tokenizer/chat | Historical runs used the different Q8 hash; repeat each required real-model section at its own patch prefix using the published file, with no skips |
| 0003 oracle, exact graph and rewind | Repeat the published-file oracle/logit/rewind gates at the 0003 prefix; final 0006 resident/streamed parity does not replace them |
| 0004 fast paths and performance | Repeat published-file numerical checks and the n=6 same-machine reference/port comparison; the required physical M4 Max Mac Studio row is still pending |
| 0005 resident MXFP4 and Q8 non-regression | Published MXFP4 numerical results are recorded; repeat per-prefix published-Q8 n=6 non-regression and a valid same-machine MXFP4 comparison |
| 0006 streaming | Fresh final-tree local tests and 512-ID parity pass on both verified quants; physical 16 GB / 8 GB acceptance remains pending |
| Complete stack and overall acceptance | Qwen rebase/full-prefix/DFlash checks, physical 36 GB / 24 GB / 16 GB / 8 GB rows, ds4-py companions and downstream/tool acceptance remain required in their assigned tasks |

These statuses supersede historical completion lines in the implementation ledger. Pending acceptance
is not waived by an exported patch, a successful library build, or the 128 GiB host results.

## 64 greedy token ids match the fork (0003), historical

```bash
Q8="$HOME/models/Mellum2.1-12B-A2.5B-Thinking-Q8_0.gguf"
PROMPT="Write a Python function that adds two integers."   # 29 tokens
./ds4 -m "$Q8" --metal -c 4096 --temp 0 -n 64 --seed 1 --dump-logprobs /tmp/ours.json -p "$PROMPT"
cd ~/projects/pauleveritt/ds4-mellum && ./ds4 -m "$Q8" --metal -c 4096 --temp 0 -n 64 --seed 1 --dump-logprobs /tmp/ref.json -p "$PROMPT"
python3 -c "import json;a=[s[\"selected\"][\"id\"] for s in json.load(open(\"/tmp/ours.json\"))[\"steps\"]];b=[s[\"selected\"][\"id\"] for s in json.load(open(\"/tmp/ref.json\"))[\"steps\"]];print(len(a),a==b)"
```

Historical result on the different-hash Q8 file: `64 True` — zero id mismatches. First twelve ids: 23, 233, 2116, 895, 333, 6246, 434, 255, 99, 2717, 669, 410.

## Exact prefill and the fast paths (0004), historical

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

## Historical same-machine performance (0004, Q8, resident, context 3072, n=6)

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
| Prefill, port | 6 | 3,960 t/s | 3,885–3,968 |
| Prefill, `d2d9338` reference | 6 | 3,978 t/s | 3,939–4,010 |
| Decode, port | 6 | 127.45 t/s | 120.41–127.92 |
| Decode, `d2d9338` reference | 6 | 128.32 t/s | 126.64–128.87 |

These historical pairs are within 1.5% of the same-machine reference, each engine loading its own
shaders. The different Q8 hash and the M5 Max host mean they do not establish the published-model
or physical M4 Max Mac Studio acceptance gates.

## MXFP4 (0005), historical validation

A valid same-machine MXFP4 performance comparison is still pending. The previous table repeated the Q8
values, and the earlier harness reused output directories and loaded the port's shaders in the reference
process. Those timings cannot establish the 0005 performance gate. Repeat it with the corrected harness
and verified model files before publishing the memory matrix.

Historical Q8 comparison after 0005: prefill 3,814 t/s and decode 118.75 t/s against 3,987 / 125.08
before the MXFP4 loaders — 4.3% and 5.1% down. This is not a pass against the published model; the
non-regression gate needs repeating. `ds4_test --mellum-moe` on the MXFP4 file passes (weights,
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

## Per-prefix acceptance on the published Q8 model

Each prefix was rebuilt from the pinned upstream plus `patches/common` and patches `0001..N` in its own clone,
then built and tested. Model: the SHA-verified Q8_0 file (`69e0ac02…6841f`, 12,925,417,760 B) through
`DS4_TEST_MELLUM_MODEL`. "config" is `tests/test_mellum_config`; "kernels" is `make test-mellum-kernels`.

| Prefix | Tree | config | kernels | model-backed gates |
|---|---|---:|---:|---|
| 0001 | `b03fbcc0` | ok | target absent | real-model config: keys validated, every tensor bound; a drafter path refused by name |
| 0002 | `20a2fa32` | ok | target absent | tokenizer with the real model: 30/30 ids equal the reference encode |
| 0003 | `7e699217` | ok | 509 | `ds4_test --mellum-rewind`: OK |
| 0004 | `170a8435` | ok | 662 | `make test-mellum-fastpath`: 45/45 |
| 0005 | `0e221609` | ok | 662 | MXFP4 config accepted; mixtures refused by name |
| 0006 | `51bb56fb` | ok | 992 | `make test-mellum-stream`: 56 checks; S4 driver smoke OK on Q8 and MXFP4; rewind OK; fast paths 45/45 |

The check counts belong to their prefix: 0003 is 509, 0004 and 0005 are 662, 0006 is 992. `ds4-check --build`
links `libds4` only and never compiles the test sources, which is why each prefix above was also built and run
as a suite. The full six-patch series reconstructs to `4366cb64` from a pristine clone.

## Oracle against an immutable `d2d9338` build

`tests/mellum_oracle_compare.sh` with `ORACLE=/tmp/ds4-ref` (a fresh `make` of `d2d9338`), PASS at 31, 1,100 and
2,200 tokens, 64/64 greedy ids equal with equal logits at every step.

Every run happens before any comparison, so the reference's exact-prefill output exists when it is compared.
Cross-engine results: `prefill-exact` and `decode` are byte-equal at all three lengths; the release `prefill`
takes the near-tie rule at 1,100 and 2,200 because both engines tile their attention there, and byte-equal below
32 rows. In-engine, this port's exact prefill is byte-equal to its decode at every length.

## Performance, corrected harness

Each engine ran from its own tree and wrote a fresh output directory; context 3072, 2,056-token prompt, n=6.

Q8_0 non-regression series:

| Prefix | Prefill | Decode |
|---|---:|---:|
| 0004 | 3,956 t/s | 124.40 t/s |
| 0005 | 3,964 t/s | 127.78 t/s |
| 0006 | 3,994 t/s | 127.87 t/s |
| `d2d9338` reference | 3,978 t/s | 128.32 t/s |

MXFP4_MOE at 0006: port 4,085 / 151.99 t/s against the reference's 4,074 / 152.13 t/s.

These were measured before the last export; the changes since (the Mellum drafter refusal, removing a test-only
accessor, and the oracle script) do not touch the measured paths, and the per-prefix gates above were re-run on
the exported patches.

Physical memory rows (36/24/16/8 GB) are pending: this machine is an M5 Max with 128 GiB, not the M4 Max Studio
the spec measures, and no 24 GB, 16 GB or 8 GB machine is reachable.
