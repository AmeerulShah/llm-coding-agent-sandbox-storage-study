#!/usr/bin/env python3
"""Fresh-commit sandbox setup for every included task (run inside `unshare -m`).

For each task, at its exact base commit, in randomized order:
  clone        git clone --local --no-checkout + checkout <commit>   (common harness practice; also what
               building a per-commit image costs once)
  warm_mount   overlayfs mount over an existing per-commit image (the clone above serves as that image)
  base_delta   overlayfs mount over a per-(repo, version) base image checked out at the group's newest task
               commit, then `git checkout <commit>` inside the mount: only changed files are copied up
Time is wall-clock; bytes are new data written (du, hard-linked objects excluded).
Usage: unshare -m python3 setup_bench.py
"""
import csv, json, os, random, subprocess, time

ROOT = "/home/claude/research/asio"
B = "/work/setup"
inst = json.load(open(f"{ROOT}/data/instances.json"))
inc = [r["instance"] for r in csv.DictReader(open(f"{ROOT}/results/instances.csv"))]
random.seed(20261121)
N = int(os.environ.get("SETUP_N", "0"))
if N:
    inc = random.sample(inc, N)  # uniform random sample of tasks, in random order


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True)


def du(*paths):
    out = sh("du -sbc " + " ".join(paths)).stdout.strip().split("\n")
    return [int(l.split()[0]) for l in out]


def new_bytes(path):
    """Bytes in regular files under path that are not hard links to existing files (link count 1)."""
    out = sh(f"find {path} -type f -links 1 -printf '%s\\n' | awk '{{s+=$1}} END {{print s+0}}'").stdout.strip()
    return int(out or 0)


def commit_time(repo_dir, c):
    return int(sh(f"git -C {ROOT}/repos_full/{repo_dir} show -s --format=%ct {c}").stdout.strip() or 0)


# per-(repo, version) base image at the group's newest task commit
groups = {}
for i in inc:
    v = inst[i]; groups.setdefault((v["repo_dir"], v["version"]), []).append(i)
base = {}
os.makedirs(B, exist_ok=True)
for (rd, ver), ids in sorted(groups.items()):
    newest = max(ids, key=lambda i: commit_time(rd, inst[i]["base_commit"]))
    img = f"{B}/base-{rd}-{ver}"
    if not os.path.isdir(img):
        sh(f"git clone -q --local {ROOT}/repos_full/{rd} {img}")
        sh(f"git -C {img} checkout -q -f {inst[newest]['base_commit']}")
    base[(rd, ver)] = img

out = open(f"{ROOT}/results/setup_bench.csv", "w", newline="")
w = csv.writer(out); w.writerow(["instance", "repo", "version", "strategy", "seconds", "new_bytes", "rc"])
for n, i in enumerate(inc):
    v = inst[i]; rd, c = v["repo_dir"], v["base_commit"]
    sh(f"git -C {ROOT}/repos_full/{rd} cat-file -t {c}")  # warm the object store equally for all strategies
    order = ["clone", "base_delta"]; random.shuffle(order)
    for strat in order:
        d = f"{B}/t"
        sh(f"umount {d}/m 2>/dev/null; umount {d}/m2 2>/dev/null; rm -rf {d}"); os.makedirs(d)
        if strat == "clone":
            t0 = time.perf_counter()
            r = sh(f"git clone -q --local --no-checkout {ROOT}/repos_full/{rd} {d}/repo && git -C {d}/repo checkout -q {c}")
            dt = time.perf_counter() - t0
            nb = new_bytes(f"{d}/repo")
            w.writerow([i, rd, v["version"], "clone", f"{dt:.4f}", nb, r.returncode])
            for x in ("u", "w", "m"):
                os.makedirs(f"{d}/{x}")
            t0 = time.perf_counter()
            r = sh(f"mount -t overlay overlay -o lowerdir={d}/repo,upperdir={d}/u,workdir={d}/w {d}/m")
            dt = time.perf_counter() - t0
            nb = du(f"{d}/u", f"{d}/w")[-1]
            w.writerow([i, rd, v["version"], "warm_mount", f"{dt:.4f}", nb, r.returncode])
        else:
            img = base[(rd, v["version"])]
            for x in ("u2", "w2", "m2"):
                os.makedirs(f"{d}/{x}")
            t0 = time.perf_counter()
            r = sh(f"mount -t overlay overlay -o lowerdir={img},upperdir={d}/u2,workdir={d}/w2 {d}/m2 && git -C {d}/m2 checkout -q -f {c}")
            dt = time.perf_counter() - t0
            nb = du(f"{d}/u2", f"{d}/w2")[-1]
            w.writerow([i, rd, v["version"], "base_delta", f"{dt:.4f}", nb, r.returncode])
    out.flush()
    print(n, i, flush=True)
sh(f"umount {B}/t/m 2>/dev/null; umount {B}/t/m2 2>/dev/null; rm -rf {B}/t")
# one-time base image sizes
with open(f"{ROOT}/results/setup_base_images.csv", "w", newline="") as f:
    ww = csv.writer(f); ww.writerow(["repo", "version", "tasks", "image_bytes"])
    for (rd, ver), ids in sorted(groups.items()):
        ww.writerow([rd, ver, len(ids), du(base[(rd, ver)])[0]])
