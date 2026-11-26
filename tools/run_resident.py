#!/usr/bin/env python3
"""Page-cache residency runs: one untraced replay per task from a cold page cache, then a mincore scan of the
image files (replay.py --mode resident). Serial on one worker, because dropping the cache is host-wide."""
import os, subprocess, sys, time

ROOT = "/home/claude/research/asio"
tasks = open(sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/resident_set.txt").read().split()
for i, inst in enumerate(tasks):
    if os.path.exists(f"{ROOT}/runs_resident/{inst}/resident.jsonl.gz"):
        continue
    t0 = time.time()
    r = subprocess.run([sys.executable, f"{ROOT}/tools/replay.py", inst, "--worker", "4", "--mode", "resident"],
                       capture_output=True, text=True)
    print(time.strftime("%H:%M:%S"), i, inst, r.returncode, round(time.time() - t0), flush=True)
print("DONE", flush=True)
