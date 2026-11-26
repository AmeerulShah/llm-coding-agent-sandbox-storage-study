#!/usr/bin/env python3
"""Bytecode timing, counterbalanced: for each task of the ablation subset, run the three untraced variants (default,
disabled bytecode, precompiled) once per repetition; over repetitions 0-2 each variant takes each run position once
per task. Usage: run_timing2.py <rep>, run one repetition at a time on an otherwise idle machine.
Rows go to results/bytecode_timing_random_r<rep>.csv."""
import csv, json, os, random, subprocess, sys, time

ROOT = "/home/claude/research/asio"
REP = int(sys.argv[1])            # repetition index; one worker per repetition
WORKER = str(5 + REP)
SUFFIX = f"_r{REP}"
MODES = {"default": "untraced", "nopyc": "untraced_nopyc", "precompiled": "untraced_precompiled"}
inc = {r["instance"] for r in csv.DictReader(open(f"{ROOT}/results/instances.csv"))}
subset = [x for x in open(f"{ROOT}/data/ablation_subset.txt").read().split() if x in inc]
rng = random.Random(20261122)
out_p = f"{ROOT}/results/bytecode_timing_random_r{REP}.csv"
done = set()
if os.path.exists(out_p):
    done = {(r["instance"], r["rep"], r["variant"]) for r in csv.DictReader(open(out_p))}
f = open(out_p, "a", newline=""); w = csv.writer(f)
if not done:
    w.writerow(["instance", "rep", "position", "variant", "tool_s", "rc_match", "t"])
# Repetition 0 uses a random order per task; repetitions 1 and 2 rotate that order by one and two places, so across
# the three repetitions every variant runs once in every position for every task (a Latin square per task).
first = {}
if REP > 0:
    for r in csv.DictReader(open(f"{ROOT}/results/bytecode_timing_random_r0.csv")):
        first.setdefault(r["instance"], {})[int(r["position"])] = r["variant"]
for rep in (REP,):
    rng = random.Random(20261122 + REP)
    for inst in (subset if REP % 2 == 0 else subset[::-1]):
        order = list(MODES); rng.shuffle(order)
        if REP > 0 and len(first.get(inst, {})) == 3:
            base = [first[inst][k] for k in range(3)]
            order = base[REP % 3:] + base[:REP % 3]
        for pos, var in enumerate(order):
            if (inst, str(rep), var) in done:
                continue
            mode = MODES[var]
            r = subprocess.run([sys.executable, f"{ROOT}/tools/replay.py", inst, "--worker", WORKER, "--mode", mode],
                               capture_output=True, text=True, env={**os.environ, "RUNS_SUFFIX": SUFFIX})
            d = f"{ROOT}/runs_{mode}{SUFFIX}/{inst}"
            tool = sum(json.loads(l)["dur_traced_s"] for l in open(f"{d}/commands.jsonl"))
            rc = json.load(open(f"{d}/summary.json"))["rc_match"]
            w.writerow([inst, rep, pos, var, round(tool, 3), rc, time.strftime("%H:%M:%S")]); f.flush()
            print(time.strftime("%H:%M:%S"), rep, pos, var, inst, round(tool, 1), flush=True)
print("DONE", flush=True)
