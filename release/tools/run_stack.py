#!/usr/bin/env python3
"""O1-O3 combined: replay the overlay subset with replay.py --mode stack, one task at a time."""
import csv, os, subprocess, sys, time
ROOT = "/home/claude/research/asio"
tasks = [r["instance"] for r in csv.DictReader(open(f"{ROOT}/results/ablation_overlay.csv"))]
for i, t in enumerate(tasks):
    if os.path.exists(f"{ROOT}/runs_stack/{t}/summary.json"):
        continue
    t0 = time.time()
    r = subprocess.run([sys.executable, f"{ROOT}/tools/replay.py", t, "--worker", "3", "--mode", "stack"], capture_output=True, text=True)
    print(time.strftime("%H:%M:%S"), i, t, r.returncode, round(time.time() - t0), r.stderr[-200:].replace("\n", " ") if r.returncode else "", flush=True)
print("DONE", flush=True)
