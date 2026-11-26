#!/usr/bin/env python3
"""Emulated remote image layer (replay.py --mode remote with tools/remotefs.py): replay a task sample untraced under
three client-caching regimes, each with no added delay and with an added round-trip delay, plus a local baseline.
Configurations run in random order per task, one at a time. Rows go to results/remote_bench.csv."""
import csv, json, os, random, subprocess, sys, time
ROOT = "/home/claude/research/asio"
TASKS = open(f"{ROOT}/data/remote_set.txt").read().split()
DELAY = os.environ.get("NOMINAL_DELAY_US", "100")
CONFIGS = [("local", None, None)] + [(f"{c}_{d}", c, d) for c in ("none", "short", "long") for d in ("0", DELAY)]
rng = random.Random(11)
out = f"{ROOT}/results/remote_bench.csv"
done = {(r["instance"], r["config"]) for r in csv.DictReader(open(out))} if os.path.exists(out) else set()
f = open(out, "a", newline=""); w = csv.writer(f)
if not done:
    w.writerow(["instance", "config", "cache", "delay_us", "tool_s", "rc_match", "req_repo", "req_env", "req_runtime", "lookups", "getattrs"])
for t in TASKS:
    cfgs = CONFIGS[:]; rng.shuffle(cfgs)
    for name, cache, delay in cfgs:
        if (t, name) in done:
            continue
        env = {**os.environ, "RUNS_SUFFIX": f"_{name}"}
        mode = "untraced" if cache is None else "remote"
        if cache is not None:
            env.update({"REMOTE_CACHE": cache, "REMOTE_DELAY_US": delay})
        subprocess.run([sys.executable, f"{ROOT}/tools/replay.py", t, "--worker", "2", "--mode", mode], env=env,
                       capture_output=True, text=True, timeout=7200)
        d = f"{ROOT}/runs_{mode}_{name}/{t}"
        sm = json.load(open(f"{d}/summary.json"))
        tool = sum(json.loads(l)["dur_traced_s"] for l in open(f"{d}/commands.jsonl"))
        req = (sm.get("remote") or {}).get("requests", {})
        tot = lambda k: sum(v for v in req.get(k, {}).values() if isinstance(v, (int, float)))
        lk = sum(req.get(k, {}).get("lookup", 0) for k in req); ga = sum(req.get(k, {}).get("getattr", 0) for k in req)
        w.writerow([t, name, cache or "", delay or "", round(tool, 3), sm["rc_match"], tot("repo"), tot("env"), tot("runtime"), lk, ga]); f.flush()
        print(time.strftime("%H:%M:%S"), t, name, round(tool, 1), flush=True)
print("DONE", flush=True)
