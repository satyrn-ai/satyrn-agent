"""Import-mask cost screen: per-step logits-hook cost on the configured 27B.

Arms (same prompt, temperature 0, seed 1, fresh session each):
  none     no hook
  copyset  hook copies logits and sets them back (batched-mask floor)
  mask     hook masks to a cached allowed token set on EVERY step (worst case;
           a real import mask fires only at a few name positions per file)
"""

import importlib
import statistics
import sys
import time
from array import array

import ds4py
from ds4py.engine.events import Stopped, Token
from ds4py.engine.sampling import SamplingPolicy

MODEL, LIB = sys.argv[1], sys.argv[2]
N_TOKENS, REPS = 128, 2
PROMPT = "# A small FastAPI app for a clinic complaints board.\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n"
MODULES = ["collections", "os", "pathlib", "typing", "dataclasses", "functools", "itertools", "json", "re", "datetime"]


def build_allowed(engine):
    names = sorted({n for m in MODULES for n in dir(importlib.import_module(m)) if not n.startswith("_")})
    t0 = time.perf_counter()
    first = {engine.tokenize(" " + n)[0] for n in names} | {engine.tokenize(n)[0] for n in names}
    return names, first, time.perf_counter() - t0


def run(arm, allowed_ids):
    # ds4-py allows one session per engine; the model loads in about 2 s.
    with ds4py.open(MODEL, ctx=4096, seed=1, lib=LIB) as engine:
        sampling = SamplingPolicy.for_engine(engine.info, temperature=0.0, seed=1)
        return _run(engine, sampling, arm, allowed_ids)


def _run(engine, sampling, arm, allowed_ids):
    hook_times: list[float] = []
    neg_inf = array("f", [float("-inf")])
    session = engine.session()
    session.append_tokens(engine.tokenize(PROMPT), "user")

    def copyset(view):
        t0 = time.perf_counter()
        buf = view.logits()
        view.set_logits(buf)
        hook_times.append(time.perf_counter() - t0)

    def mask(view):
        t0 = time.perf_counter()
        buf = view.logits()
        out = neg_inf * len(buf)
        for tid in allowed_ids:
            out[tid] = buf[tid]
        view.set_logits(out)
        hook_times.append(time.perf_counter() - t0)

    if arm == "copyset":
        session.add_logits_hook(copyset)
    elif arm == "mask":
        session.add_logits_hook(mask)

    stamps: list[float] = []
    for event in session.run_round(max_tokens=N_TOKENS, sampling=sampling):
        if isinstance(event, Token):
            stamps.append(time.perf_counter())
        elif isinstance(event, Stopped):
            break
    session.close()
    decode = (stamps[-1] - stamps[0]) / (len(stamps) - 1) if len(stamps) > 1 else float("nan")
    hook_ms = statistics.mean(hook_times) * 1000 if hook_times else 0.0
    return len(stamps), decode * 1000, hook_ms


def main():
    t0 = time.perf_counter()
    with ds4py.open(MODEL, ctx=4096, seed=1, lib=LIB) as engine:
        print(f"load {time.perf_counter() - t0:.1f} s", flush=True)
        names, allowed, build_s = build_allowed(engine)
        print(f"allowed set: {len(names)} names -> {len(allowed)} first tokens, built in {build_s * 1000:.1f} ms", flush=True)
    allowed_ids = sorted(allowed)
    run("none", allowed_ids)  # warm-up, discarded
    for rep in range(REPS):
        for arm in ("none", "copyset", "mask"):
            n, ms_tok, hook_ms = run(arm, allowed_ids)
            print(f"rep={rep} arm={arm:8s} tokens={n:4d} ms/token={ms_tok:6.1f} hook_ms={hook_ms:6.3f}", flush=True)
    print(f"total {time.perf_counter() - t0:.1f} s")


main()
