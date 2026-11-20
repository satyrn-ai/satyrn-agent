# Mellum engine evidence

Historical evidence for `patches/mellum/0001`–`0005`, followed by fresh 0006 validation.
The machine is an Apple M5 Max (128 GiB); the immutable reference is `pauleveritt/ds4-mellum` at `d2d9338`.

**Model provenance correction (2026-11-18):** the Q8 path used in the older commands below currently hashes
to `ea1e4ec737bb259ac2ffe1f20d412f458fd52dd230f42dce9e944f111093c29b`, not the spec's published
`69e0ac02a16586c2c9e991f1e3b8a1eb403882e7ab9e69ea01eb23dbbbc6841f`. Its size matches, so size alone
missed the difference. Those historical commands do not establish acceptance against the published file;
the affected oracle and performance gates need repeating. Fresh 0006 runs use the SHA-verified published
blob already in the Hugging Face cache. The existing file in `~/models` was not changed.

## Patch discipline checkpoint

Six patches export from commits `7d25b709`..`26081c49` (the current `From` headers), each exactly its own
delta, authored `pauleveritt <pauleveritt@me.com>`, with the three required trailers. Applying them in order
reconstructs tree `8b8ef87a` from a pristine clone, and `ds4-check --model mellum --build` passes. The
per-prefix table below is authoritative for the current export; older ledger entries that name `cd3911c3`,
`3130743c…` or `5e05d49a` describe superseded exports. Re-verified 2026-11-20 by materializing each prefix from
a pristine clone of the pin plus `patches/common` and patches `0001..N`: `d607f0f0`, `9974c264`, `3784419c`,
`a761e859`, `1808b824`, `8b8ef87a`.

The series now uses the reference's `.inc` layout, per Koudai's ruling: 0001 adds `ds4_mellum_config.inc` and
`ds4_mellum_plan.inc`, 0002 adds `ds4_mellum_tokenizer.inc` (and keeps `ds4_mellum_unicode.inc`), 0003 adds
`ds4_mellum_graph_alloc.inc`, `ds4_mellum_graph.inc` and `ds4_mellum_test_hooks.inc`, and 0004–0006 extend the
graph and hook files. About 1,700 lines moved out of `ds4.c`; the resulting patch file lists match the spec's §4
ledger.

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

## SSD streaming (0006) on the exported artifact

Tree `ece0d5fe`, context 32768, 512 greedy tokens, three resident and three streamed processes on Q8_0. The
current 0006 tree is `8b8ef87a`; its only deltas from `ece0d5fe` are the reference `.inc` relocation, removing
duplicate host-contract test lines from `tests/test_mellum_config.c`, and correcting the oracle-script header, so
the engine source is unchanged. The
prompt's SHA-256 is `f3b0e01b…6806`. Resident ids agree across all three runs, streamed ids agree across all
three, and resident equals streamed at all 512 positions. Raw runs and ids are in
`mellum-task16-summary.json`.

MXFP4 was rerun on the `.inc` tree `8b8ef87a`: three resident and three streamed 512-token runs, resident ids
agree 3/3, streamed ids agree 3/3, and resident equals streamed at all 512 positions. The streamed runs use 652
slots at 2 GiB; the summary records them in `mxfp4_resident_streamed_parity`.

## Per-prefix acceptance on the published Q8 model

Each prefix was rebuilt from the pinned upstream plus `patches/common` and patches `0001..N` in its own clone,
then built and tested. Model: the SHA-verified Q8_0 file (`69e0ac02…6841f`, 12,925,417,760 B) through
`DS4_TEST_MELLUM_MODEL`. "config" is `tests/test_mellum_config`; "kernels" is `make test-mellum-kernels`.

| Prefix | Tree | config | kernels | model-backed gates |
|---|---|---:|---:|---|
| 0001 | `d607f0f0` | ok | target absent | real-model config: keys validated, every tensor bound; a drafter path refused by name |
| 0002 | `9974c264` | ok | target absent | tokenizer with the real model: 30/30 ids equal the reference encode |
| 0003 | `3784419c` | ok | 509 | `ds4_test --mellum-rewind`: OK |
| 0004 | `a761e859` | ok | 662 | `make test-mellum-fastpath`: 45/45 |
| 0005 | `1808b824` | ok | 662 | MXFP4 config accepted; mixtures refused by name |
| 0006 | `8b8ef87a` | ok | 992 | `make test-mellum-stream`: 56 checks; S4 driver smoke OK on Q8 and MXFP4; rewind OK; fast paths 45/45 |

The check counts belong to their prefix: 0003 is 509, 0004 and 0005 are 662, 0006 is 992. `ds4-check --build`
links `libds4` only and never compiles the test sources, which is why each prefix above was also built and run
as a suite. The table was re-run after the `.inc` relocation, not carried over from the inline export. The six
patches applied in order reconstruct to tree `8b8ef87a` from a pristine clone (`ds4-check --model mellum --build`).

## Oracle against an immutable `d2d9338` build

`tests/mellum_oracle_compare.sh` with `ORACLE=/tmp/ds4-ref` (a fresh `make` of `d2d9338`), PASS at 29, 1,100 and
2,200 tokens, 64/64 greedy ids equal with equal logits at every step.

The same script run against the 0003 tree (the exact graph, before the 0004 fast paths and without the
`DS4_MELLUM_EXACT_PREFILL` diagnostic) also passes at all three lengths with 64/64 greedy ids; 0003 is exact, so
its release prefill and its "exact" run are the same bytes. This is the published-Q8 exact oracle Koudai asked
for on 0003.

Every run happens before any comparison, so the reference's exact-prefill output exists when it is compared.
All three cross-engine comparisons are byte-equal in fact at every length. The release `prefill` is held to the
near-tie rule at 1,100 and 2,200 only because both engines tile their attention there and a tie could flip; below
32 rows it is byte-equal too. In-engine, this port's exact prefill is compared to its own decode byte for byte and
passes at every length.

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

These were measured on the 0004–0006 trees of the previous export. The changes since (the Mellum open-check
regression fix, the drafter refusal, removing a test-only accessor and the oracle script) do not touch the
measured paths, and every per-prefix gate above was re-run on the exported patches.

Physical memory rows (36/24/16/8 GB) are pending: this machine is an M5 Max with 128 GiB, not the M4 Max Studio
the spec measures, and no 24 GB, 16 GB or 8 GB machine is reachable.
