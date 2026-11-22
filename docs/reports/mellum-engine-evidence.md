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

Six patches export from commits `0e61bdb8`..`d7b36619` (the current `From` headers), each exactly its own
delta, authored `pauleveritt <pauleveritt@me.com>`, with the three required trailers. Applying them in order
reconstructs tree `71f9b64c` from a pristine clone, and `ds4-check --model mellum --build` passes. The `From` headers are now `def0de0f`..`86f044c1`; the earlier `0e61bdb8`..`d7b36619` range and the `ca243153` tree above are superseded exports (the last delta was moving the include-dependency block out of the Darwin-only Makefile branch). The
per-prefix table below is authoritative for the current export; older ledger entries that name `cd3911c3`,
`3130743c…`, `5e05d49a` or `8b8ef87a` describe superseded exports. Re-verified 2026-11-20 by materializing each prefix from
a pristine clone of the pin plus `patches/common` and patches `0001..N`: `d607f0f0`, `9974c264`, `dc4d8de4`,
`e7b75728`, `4fb50372`, `ca243153`.

The series now uses the reference's `.inc` layout, per Koudai's ruling: 0001 adds `ds4_mellum_config.inc` and
`ds4_mellum_plan.inc`, 0002 adds `ds4_mellum_tokenizer.inc` (and keeps `ds4_mellum_unicode.inc`), 0003 adds
`ds4_mellum_graph_alloc.inc`, `ds4_mellum_graph.inc` and `ds4_mellum_test_hooks.inc`, and 0004–0006 extend the
graph and hook files. About 1,700 lines moved out of `ds4.c`; `ds4_mellum_graph.inc` stays Mellum-only and the
shared Qwen4 graph functions stay in `ds4.c`, matching `d2d9338`. The patch file lists match the spec's §4 ledger.

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
measured 0006 tree there was `ca243153` (historical; the current export is `71f9b64c`); its only deltas from `ece0d5fe` are the reference `.inc` relocation, removing
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
| 0001 | `0b4d8a8b` | ok | target absent | real-model config: keys validated, every tensor bound; a drafter path refused by name |
| 0002 | `c7cd6d48` | ok | target absent | tokenizer with the real model: 30/30 ids equal the reference encode |
| 0003 | `10b1a73c` | ok | 509 | `ds4_test --mellum-rewind`: OK; published-Q8 oracle PASS (see below) |
| 0004 | `dfa685aa` | ok | 662 | `make test-mellum-fastpath`: 45/45 |
| 0005 | `27b4430b` | ok | 662 | MXFP4 config accepted; mixtures refused by name |
| 0006 | `71f9b64c` | ok | 992 | `make test-mellum-stream`: 56 checks; S4 driver smoke OK on Q8 and MXFP4; rewind OK; fast paths 45/45 |

The kernel counts were measured on the absorbed export immediately before the include-dependency
placement fix; the only delta between those trees and the current ones is `Makefile` prerequisites
(`git diff --stat` reports `Makefile` alone for every prefix), so the results carry. The check counts
belong to their prefix: 0003 is 509, 0004 and 0005 are 662, 0006 is 992. `ds4-check --build`
links `libds4` only and never compiles the test sources, which is why each prefix above was also built and run
as a suite. The table was re-run on the absorbed export — after the common fast-math patch, the Mellum
include-dependency fix and the macOS 26 SDK bump — under the Nix toolchain; the 509 and 662 counts for
0003/0004 were re-verified on that export, the 0006/combined 992, config, tokenizer, oracle and parity on the
combined tip. The six patches applied in order reconstruct to tree `71f9b64c` from a pristine clone
(`ds4-check --model mellum --build`).

## Oracle against an immutable `d2d9338` build

`tests/mellum_oracle_compare.sh` with `ORACLE=/tmp/ds4-ref` (a fresh `make` of `d2d9338`), PASS at 29, 1,100 and
2,200 tokens, 64/64 greedy ids equal with equal logits at every step.

The same script run against the 0003 tree (the exact graph, before the 0004 fast paths and without the
`DS4_MELLUM_EXACT_PREFILL` diagnostic) also passes at all three lengths with 64/64 greedy ids; 0003 is exact, so
its release prefill and its "exact" run are the same bytes. This is the published-Q8 exact oracle Koudai asked
for on 0003.

**Re-run on the SDK-26 0003 prefix (2026-11-21).** Tree `10b1a73c`, published Q8 (`69e0ac02…6841f`),
reference `/tmp/ds4-ref-nix` (`d2d9338` rebuilt with `apple-sdk_26`, `tensor_matmul=on`). The 0003 prefix
predates the oracle harness, so `tests/mellum_oracle_compare.sh`, `tests/mellum_logits_compare.py` and the
three `.tokens` fixtures were copied into a scratch checkout of that tree (harness only; the engine is
untouched): `sh tests/mellum_oracle_compare.sh /tmp/ds4-ref-nix "$Q8" 64` → PASS. Exact prefill is
byte-equal at 29, 1,100 and 2,200 (65/65 logits files each); decode is byte-equal; greedy is 64/64 with
equal logits. The release prefill is byte-equal at 29 and 1,100 and differs only in the permitted near-tie
form at 2,200 (0/65 byte-equal, 65/65 top-1, max |Δlogit| 8.563). The 509 kernel checks are the kernel
result, not a substitute for this oracle.

Every run happens before any comparison, so the reference's exact-prefill output exists when it is compared.
The exact-prefill and decode comparisons are byte-equal at every length. The release `prefill` is held to the
near-tie rule at 1,100 and 2,200 only because both engines tile their attention there and a tie could flip; below
32 rows it is byte-equal too. In-engine, this port's exact prefill is compared to its own decode byte for byte and
passes at every length.

## Performance on the absorbed export (Nix SDK 26.5, canonical)

Each engine from its own tree, `ARMS=AA`, context 3,072, 2,056-token prompt (`68132d36…65c1`),
`PER=4` with each block's first process dropped (n=6), fresh output directories. Every arm reported
`language=4.0 mathMode=fast mathFloatingPointFunctions=fast` and `tensor_matmul=on`.

| Arm | Engine commit | Prefill | Decode |
| --- | --- | ---: | ---: |
| 0004 (Q8) | `1e519c35` | 3,968 t/s | 128.23 t/s |
| 0005 (Q8) | `b3273aeb` | 3,968 t/s | 128.61 t/s |
| 0006 (Q8) | `d7b36619` | 3,974 t/s | 128.28 t/s |
| reference (Q8) | `d2d9338`, Nix SDK 26 rebuild | 3,979 t/s | 127.69 t/s |
| 0005 (MXFP4) | `b3273aeb` | 4,071 t/s | 151.38 t/s |
| reference (MXFP4) | `d2d9338`, Nix SDK 26 rebuild | 4,063 t/s | 150.70 t/s |

The current-0005 MXFP4 pair is +0.20% prefill and +0.45% decode. Q8 prefill is within 0.28% of the
reference and within 0.15% across 0004→0006; Q8 decode is within 0.25% across the port prefixes and
0.42–0.72% above the reference. All well inside the 10% gate. Binary sha256 (first 16): 0004 `cea4138316d1b0d6`, 0005
`ec85117cefac5e66`, 0006 `ce12609ed5556476`, reference `7c7cbb3436d0ff58`. Raw:
`/tmp/mellum-perf-sdk26/`.

The measured engine commits predate the include-dependency placement fix; the tree delta is `Makefile`
only, so the binaries and numbers stand, and the current export's equivalent trees are 0004
`dfa685aa`, 0005 `27b4430b`, 0006 `71f9b64c`.

The tables below are historical and were measured on superseded exports with other toolchains; they are
kept for provenance only.

## Performance, corrected harness (historical)

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

## Common-layer Metal math-mode regression (2026-11-21)

The Metal language-version pin in `patches/common` sets `MTLCompileOptions.languageVersion` without
setting `mathMode`. On this machine's SDK an explicit language version changes the default math mode
from fast to strict: every patched build compiled its shaders at strict IEEE-754 and lost about 43% of
prefill. The unpatched reference was unaffected, which made the port look slow at every prefix.

Isolation on the M5 Max, published MXFP4, 2,056-token prompt, context 3,072, `-n 1`, one process each:

| Build | Prefill |
|---|---:|
| port `f5463ed1` (0005), as shipped, own shaders | 2,331 / 2,365 / 2,367 t/s |
| same binary, reference's `metal/` | 2,338 / 2,367 / 2,357 t/s |
| reference `d2d9338`, own shaders | 4,135 / 4,152 / 4,124 t/s |
| same binary, port's `metal/` | 4,112 / 4,121 / 4,123 t/s |

Shaders are not the variable; the binary is. The only substantive difference in `ds4_metal.m` between
the two trees is `ds4_gpu_compile_options()` (common patch 0002/0003). Ablation on the 0006 tree,
same model and prompt:

| `ds4_gpu_compile_options` | Prefill |
|---|---:|
| `[MTLCompileOptions new]` (the reference's path) | 4,023 / 4,024 t/s |
| `languageVersion = 3.2` | 2,338 / 2,368 t/s |
| `languageVersion = 4.0` | 2,331 / 2,367 t/s |
| `languageVersion = 4.0; mathMode = MTLMathModeFast` | 4,132 / 4,144 t/s |

The pin is active in every build: Nix's SDK reports `__MAC_OS_X_VERSION_MAX_ALLOWED = __MAC_15_5`
(so the 3.2 branch), Xcode's reports `__MAC_27_2` (so the 4.0 branch); only a build with the macro
undefined compiles the pin out. The pin landed on 2026-10-26 (`9c7eb1f`), before every Mellum
measurement, so the recorded port-side numbers above (0004 3,956 / 0005 3,964 / 0006 3,994 /
MXFP4 4,085 t/s) cannot be reproduced with the common layer as exported. They match the reference
binary's numbers, which is consistent with the harness mix-up that the "corrected harness" section
replaced.

**Current-0005 MXFP4 comparison, with `mathMode = MTLMathModeFast` added to the pin.** Port `f5463ed1`
and reference `d2d9338`, tree `36b14b9c`, published MXFP4 (`cf09584a…8166`), one machine, each engine
from its own tree, `ARMS=AA`, n=6 after the per-block drop:

| Metric | Port 0005 | Reference | Delta |
|---|---:|---:|---:|
| Prefill | 4,081 t/s | 4,078 t/s | +0.07% |
| Decode | 148.12 t/s | 151.58 t/s | -2.3% |

Raw runs: `/tmp/mellum-step2-fixed/{port0005,ref}-{prefill,decode}/runs.txt`. The comparison passes
its 10% gate **only** with the math-mode fix; without it prefill is 2,254-2,330 t/s, 43% down.

**Superseding note (2026-11-21).** The pair above was measured with the Xcode toolchain. The
canonical toolchain is Nix with `apple-sdk_26` (see `2026-11-21-devenv-sdk-26.md`), whose build reports
`tensor_matmul=on` and `language=4.0 mathMode=fast`; the canonical performance series is the
"absorbed export" section below. The math-mode fix matters there: with Metal 4 compiled in, the 4.0 pin
applies, and without explicit fast math the shaders compile strict and lose ~43%.

The fix belongs in common patches 0002/0003: set `options.mathMode = MTLMathModeFast;` next to each
`languageVersion` assignment. That restores the reference's documented fast default (`fastMathEnabled`
defaults to YES) while keeping the language pin that the Python-host SDK case needs. Because common is
shared, every prefix tree changes and the oracle, kernel and performance gates must be re-run before
the numbers above replace the recorded ones. Main inherits the same ~43% prefill cost today.
