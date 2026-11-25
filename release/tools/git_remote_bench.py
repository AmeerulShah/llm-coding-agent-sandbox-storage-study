#!/usr/bin/env python3
"""O3 on an emulated remote image layer: history searches with git's default attribute lookup and with
attr.tree=HEAD, with the repository served by tools/remotefs.py under the 'short' cache (misses not cached) and the
'long' cache (misses cached), with no added delay and with an added round-trip delay. Run inside `unshare -m`.
Rows go to results/git_remote_bench.csv."""
import csv, json, os, random, re, subprocess, sys, time

ROOT = "/home/claude/research/asio"; FZ = "/work/fuse/g"
DELAY = os.environ.get("NOMINAL_DELAY_US", "100")
inst = json.load(open(f"{ROOT}/data/instances.json"))
G = [r for r in csv.DictReader(open(f"{ROOT}/results/git_attr_bench.csv")) if r["config"] == "default"]
H = re.compile(r"git\s+log\b.*(-S|-G|-p\b|--patch)")
cands = sorted([r for r in G if H.search(r["cmd"]) and r["instance"].startswith("django")], key=lambda r: -int(r["failed"]))
calls, seen = [], set()
for r in cands:
    if r["instance"] not in seen:
        calls.append(r); seen.add(r["instance"])
    if len(calls) == 4:
        break
ATTR = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "attr.tree", "GIT_CONFIG_VALUE_0": "HEAD"}
BASE = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8", "PAGER": "cat", "GIT_PAGER": "cat"}
sbx = "/work/w0/sbx-django"
os.makedirs(f"{FZ}/repo", exist_ok=True); os.makedirs("/testbed", exist_ok=True)
rng = random.Random(3)
f = open(f"{ROOT}/results/git_remote_bench.csv", "w", newline=""); w = csv.writer(f)
w.writerow(["instance", "cmd", "cache", "delay_us", "attr_tree", "seconds", "requests", "lookups", "rc"])
for r in calls:
    subprocess.run(f"git -C {sbx} checkout -q -f {inst[r['instance']]['base_commit']} && git -C {sbx} clean -q -fdx", shell=True)
    cfgs = [(c, d, a) for c in ("short", "long") for d in ("0", DELAY) for a in (False, True)]; rng.shuffle(cfgs)
    for cache, delay, attr in cfgs:
        st = f"{FZ}/stats.json"
        p = subprocess.Popen([f"{ROOT}/envs/tool/bin/python", f"{ROOT}/tools/remotefs.py", sbx, f"{FZ}/repo", delay, cache, st],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.ismount(f"{FZ}/repo"):
                break
            time.sleep(0.05)
        subprocess.run(f"mount --bind {FZ}/repo /testbed", shell=True)
        t0 = time.perf_counter()
        q = subprocess.run(["bash", "-c", r["cmd"]], cwd="/testbed", env={**BASE, **(ATTR if attr else {})}, capture_output=True)
        dt = time.perf_counter() - t0
        subprocess.run(f"umount /testbed; fusermount3 -u {FZ}/repo", shell=True); p.wait(timeout=60)
        n = json.load(open(st))
        w.writerow([r["instance"], r["cmd"][:120], cache, delay, int(attr), round(dt, 3), sum(n.values()), n.get("lookup", 0), q.returncode]); f.flush()
        print(time.strftime("%H:%M:%S"), r["instance"], cache, delay, attr, round(dt, 1), sum(n.values()), flush=True)
print("DONE", flush=True)
