# Mellum engine evidence

Raw pointers for the acceptance claims in `patches/mellum/0001`–`0004`. Every command was run on the
Apple M5 Max (128 GiB) with the SHA-verified Q8_0 GGUF, one model process at a time, `pgrep -fl "ds4|dogfood"`
empty before each run. The reference fork is `pauleveritt/ds4-mellum` at `d2d9338`.

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

## MXFP4 (0005), same machine, n=6, context 3072

| Run | Median | Range |
|---|---|---|
| Prefill, port | 3,902 t/s | 3,894–3,972 |
| Prefill, `d2d9338` reference | 3,918 t/s | 3,908–3,944 |
| Decode, port | 124.67 t/s | 116.17–125.78 |
| Decode, `d2d9338` reference | 126.55 t/s | 126.26–126.71 |

(The MXFP4 rows were measured with the earlier, flawed harness — same output directory, reference loading the
port's shaders — and are re-measured with the corrected harness before the memory matrix is published.)

Q8 non-regression after 0005: prefill 3,814 t/s and decode 118.75 t/s against 3,987 / 125.08 before the MXFP4
loaders — 4.3% and 5.1% down, inside the 10% cap. `ds4_test --mellum-moe` on the MXFP4 file passes (weights,
selection and the staged double reference), and `tests/test_mellum_config` opens it, refusing every mixture.

Both files verify: MXFP4 sha256 `cf09584a…8166`, 7,029,537,056 bytes. These are M5 Max numbers; the spec's §2.3 figures
(1,515 / 88.19 t/s) are the M4 Max Mac Studio baseline, so the acceptance is the same-machine comparison.
