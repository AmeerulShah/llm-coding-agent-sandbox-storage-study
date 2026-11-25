#!/usr/bin/env python3
"""On-disk size of git objects reachable from a task's base commit versus all objects of the repository clone, for a
stratified sample of tasks (what SWE-bench images keep after removing later history and repacking, approximately).
Writes results/git_reach.csv."""
import csv, json, random, subprocess
ROOT = "/home/claude/research/asio"
inst = json.load(open(f"{ROOT}/data/instances.json"))
inc = [r["instance"] for r in csv.DictReader(open(f"{ROOT}/results/instances.csv"))]
random.seed(5)
by = {}
for i in inc:
    by.setdefault(inst[i]["repo_dir"], []).append(i)
sample = [t for rd, ts in sorted(by.items()) for t in random.sample(ts, min(4, len(ts)))]
def du(rd, args):
    r = subprocess.run(["git", "-C", f"{ROOT}/repos_full/{rd}", "rev-list", "--objects", "--disk-usage"] + args,
                       capture_output=True, text=True)
    return int(r.stdout.strip() or 0)
with open(f"{ROOT}/results/git_reach.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["instance", "repo", "reachable_bytes", "all_bytes"])
    alls = {}
    for t in sample:
        rd = inst[t]["repo_dir"]
        if rd not in alls:
            alls[rd] = du(rd, ["--all"])
        w.writerow([t, rd, du(rd, [inst[t]["base_commit"]]), alls[rd]]); f.flush(); print(t, flush=True)
