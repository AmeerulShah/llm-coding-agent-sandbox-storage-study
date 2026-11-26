"""Run all replays with N workers; each worker owns a disjoint set of environments."""
import json, os, subprocess, sys, time
from collections import defaultdict
ROOT = "/home/claude/research/asio"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 2
MODE = sys.argv[2] if len(sys.argv) > 2 else "trace"
SUBSET = sys.argv[3] if len(sys.argv) > 3 else None
inst = json.load(open(f"{ROOT}/data/instances.json"))
if SUBSET:
    keepset = set(open(SUBSET).read().split())
    inst = {k: v for k, v in inst.items() if k in keepset}
OUTD = f"{ROOT}/runs" if MODE == "trace" else f"{ROOT}/runs_{MODE}"
os.makedirs(OUTD, exist_ok=True)
by_env = defaultdict(list)
for k, v in sorted(inst.items()):
    by_env[v["env"]].append(k)
loads = [0] * N; assign = [[] for _ in range(N)]
for env, ks in sorted(by_env.items(), key=lambda x: -len(x[1])):
    i = loads.index(min(loads)); assign[i] += ks; loads[i] += len(ks)

def worker(i):
    log = open(f"{OUTD}/_worker{i}.log", "a")
    for k in assign[i]:
        if os.path.exists(f"{OUTD}/{k}/summary.json"):
            continue
        t = time.time()
        try:
            r = subprocess.run([f"{ROOT}/envs/tool/bin/python", f"{ROOT}/tools/replay.py", k, "--worker", str(i), "--mode", MODE],
                               capture_output=True, text=True, timeout=3600)
            last = (r.stdout.strip().splitlines() or [""])[-1]
            log.write(f"{time.strftime('%H:%M:%S')} {k} rc={r.returncode} {time.time()-t:.0f}s {last[:200]}\n")
            if r.returncode != 0:
                log.write(r.stderr[-2000:] + "\n")
        except subprocess.TimeoutExpired:
            log.write(f"{time.strftime('%H:%M:%S')} {k} TIMEOUT\n")
        log.flush()
    log.write("WORKER DONE\n"); log.flush()

if __name__ == "__main__":
    pids = []
    for i in range(N):
        pid = os.fork()
        if pid == 0:
            worker(i); os._exit(0)
        pids.append(pid)
    for p in pids:
        os.waitpid(p, 0)
