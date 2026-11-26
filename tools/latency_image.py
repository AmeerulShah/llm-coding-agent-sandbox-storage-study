#!/usr/bin/env python3
"""O5 bounds restricted to the image: metadata operations on the repository tree, .git, the virtualenv and the Python
runtime (the layers that would sit on remote storage); /tmp, the home directory, system files and pseudo files stay
local. Upper bound: every such operation is a round trip. Lower bound: each distinct path once per sandbox.
Writes results/latency_image.csv (per task and round-trip time) and results/latency_image.json (medians over tasks
of added time divided by the task's recorded duration)."""
import csv, glob, gzip, json
import numpy as np

ROOT = "/home/claude/research/asio"; RES = f"{ROOT}/results"
IMAGE = {"repo", "git", "env", "runtime"}
T = {r["instance"]: r for r in csv.DictReader(open(f"{RES}/instances.csv"))}
rows = []
for p in sorted(glob.glob(f"{ROOT}/runs/*/files.jsonl.gz")):
    t = p.split("/")[-2]
    if t not in T or not T[t].get("task_wall_s"):
        continue
    ops = distinct = 0
    for l in gzip.open(p, "rt"):
        r = json.loads(l)
        if r["cls"] not in IMAGE:
            continue
        n = sum(r.get(k, 0) for k in ("stat", "stat_fail", "open_r", "open_w", "open_fail", "getdents"))
        if n:
            ops += n; distinct += 1
    wall = float(T[t]["task_wall_s"])
    for rtt in (10, 50, 100, 250, 500, 1000, 2000):
        rows.append({"instance": t, "rtt_us": rtt, "wall_s": wall, "ops": ops, "distinct": distinct,
                     "nocache_frac": ops * rtt / 1e6 / wall, "cache_frac": distinct * rtt / 1e6 / wall})
with open(f"{RES}/latency_image.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
out = {"n": len({r["instance"] for r in rows})}
for rtt in (100, 500):
    sub = [r for r in rows if r["rtt_us"] == rtt]
    out[f"nocache_{rtt}"] = float(np.median([r["nocache_frac"] for r in sub]))
    out[f"cache_{rtt}"] = float(np.median([r["cache_frac"] for r in sub]))
sub = [r for r in rows if r["rtt_us"] == 500]
out["ops_med"] = float(np.median([r["ops"] for r in sub])); out["distinct_med"] = float(np.median([r["distinct"] for r in sub]))
json.dump(out, open(f"{RES}/latency_image.json", "w"), indent=1); print(out)
