#!/usr/bin/env python3
"""Measured page-cache footprint per task and a co-location scenario built from it.

Input: runs_resident/<task>/resident.jsonl.gz (pages of image files resident after a cold-cache, untraced replay;
includes memory-mapped and read-ahead pages). Files written during the replay are excluded.
Scenario: page cache needed by N co-located sandboxes under three sharing regimes
  private      every sandbox caches its own copy (e.g., separate microVM page caches)
  containers   what layered container images already share: runtime, system and virtualenv pages are shared by
               sandboxes built from the same image layers; repository and .git pages are private per task image
  version_base a per-version base image with the task's commit checked out in the upper layer (O1): .git and the
               repository files that equal the base image's version are shared by tasks of the same version
  content      version_base plus content addressing: identical repository files (same git blob) share pages everywhere
Outputs: results/resident_tasks.csv, results/sharing_measured.csv, results/sharing_measured.json
"""
import csv, glob, gzip, json, os, random
import numpy as np

ROOT = "/home/claude/research/asio"; RES = f"{ROOT}/results"
PS = 4096
inst = json.load(open(f"{ROOT}/data/instances.json"))
inc = {r["instance"]: r for r in csv.DictReader(open(f"{RES}/instances.csv"))}

import subprocess
base_blob = {}  # (repo_dir, version) -> {path: blob}
for line in open(f"{RES}/setup_base_commits.txt"):
    name, commit = line.split()
    rd, ver = name[len("base-"):].split("-", 1)
    out = subprocess.run(["git", "-C", f"{ROOT}/repos_full/{rd}", "ls-tree", "-r", commit], capture_output=True, text=True).stdout
    base_blob[(rd, ver)] = {l.split("\t", 1)[1]: l.split()[2] for l in out.splitlines() if "\t" in l}
tasks = {}
for p in sorted(glob.glob(f"{ROOT}/runs_resident/*/resident.jsonl.gz")):
    t = p.split("/")[-2]
    if t not in inc:
        continue
    pages = {}  # key -> set of page indices, per regime computed later
    recs = [json.loads(l) for l in gzip.open(p, "rt")]
    tasks[t] = [r for r in recs if not r["written"]]

rows = []
for t, recs in tasks.items():
    by = {c: sum(r["resident"] for r in recs if r["cls"] == c) * PS for c in ("repo", "git", "env", "runtime", "system")}
    img = sum(by[c] for c in ("repo", "git", "env", "runtime"))
    I = inc[t]
    rows.append({"instance": t, "repo": inst[t]["repo_dir"], **{f"res_{c}": v for c, v in by.items()}, "res_image": img,
                 "image_bytes": float(I["image_bytes"]), "trace_ws": float(I["ws_total"]),
                 "trace_mapped": float(I["mapped_total"]) if I.get("mapped_total") not in (None, "") else 0.0})
with open(f"{RES}/resident_tasks.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def keyed_pages(t, regime):
    out = []
    grp = (inst[t]["repo_dir"], inst[t]["version"])
    bb = base_blob.get(grp, {})
    for r in tasks[t]:
        c = r["cls"]
        if regime == "private":
            k = (t, c, r["path"])
        elif c in ("runtime", "system"):
            k = (c, r["path"])
        elif c == "env":
            k = (c, inst[t]["env"], r["path"])
        elif c == "git" and regime in ("version_base", "content"):
            k = ("git",) + grp + (r["path"],)
        elif c == "repo" and regime == "content" and r.get("blob"):
            k = ("blob", r["blob"])
        elif c == "repo" and regime == "version_base" and r.get("blob") and bb.get(r["path"]) == r["blob"]:
            k = ("vb",) + grp + (r["path"],)
        else:  # private per task: per-commit image layer, or a file copied up by the checkout delta
            k = (t, c, r["path"])
        if c == "system":
            continue  # host-wide libraries; outside the sandbox image
        for s, n in r["runs"]:
            out.append((k, s, n))
    return out


def union_bytes(ts, regime):
    seen = {}
    for t in ts:
        for k, s, n in keyed_pages(t, regime):
            seen.setdefault(k, set()).update(range(s, s + n))
    return sum(len(v) for v in seen.values()) * PS


rng = random.Random(1)
curves = []
pools = {"mixed": sorted(tasks), "django": sorted(t for t in tasks if inst[t]["repo_dir"] == "django")}
for pool_name, pool in pools.items():
    for N in (1, 2, 4, 8, 16, 32, 64):
        if N > len(pool):
            continue
        vals = {"private": [], "containers": [], "version_base": [], "content": []}
        for trial in range(20 if N < len(pool) else 1):
            ts = rng.sample(pool, N)
            for reg in vals:
                vals[reg].append(union_bytes(ts, reg))
        curves.append({"pool": pool_name, "n": N, **{reg: float(np.median(v)) for reg, v in vals.items()}})
with open(f"{RES}/sharing_measured.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(curves[0])); w.writeheader(); w.writerows(curves)

R = rows
med = lambda xs: float(np.median(xs))
summary = {
    "n_tasks": len(R),
    "res_image_MiB_med": med([r["res_image"] / 2**20 for r in R]),
    "res_frac_image_med": med([r["res_image"] / r["image_bytes"] for r in R]),
    "trace_ws_MiB_med": med([r["trace_ws"] / 2**20 for r in R]),
    "trace_frac_image_med": med([r["trace_ws"] / r["image_bytes"] for r in R]),
    "res_over_trace_med": med([r["res_image"] / r["trace_ws"] for r in R if r["trace_ws"] > 0]),
    "res_system_MiB_med": med([r["res_system"] / 2**20 for r in R]),
    "curves": curves,
}
json.dump(summary, open(f"{RES}/sharing_measured.json", "w"), indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != "curves"}, indent=1))
for c in curves:
    print(c["pool"], c["n"], {k: round(c[k] / 2**30, 2) for k in ("private", "containers", "version_base", "content")})
