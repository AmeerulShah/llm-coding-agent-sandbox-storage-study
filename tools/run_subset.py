"""Sequentially replay a subset in one mode on one worker id: run_subset.py <mode> <subset_file> <worker> [<mode2> ...]"""
import json, os, subprocess, sys, time
ROOT = "/home/claude/research/asio"
subset = open(sys.argv[2]).read().split(); worker = sys.argv[3]
modes = [sys.argv[1]] + sys.argv[4:]
for mode in modes:
    outd = f"{ROOT}/runs_{mode}" if mode != "trace" else f"{ROOT}/runs"
    os.makedirs(outd, exist_ok=True)
    log = open(f"{outd}/_subset_w{worker}.log", "a")
    for k in subset:
        if os.path.exists(f"{outd}/{k}/summary.json"):
            continue
        t = time.time()
        r = subprocess.run([f"{ROOT}/envs/tool/bin/python", f"{ROOT}/tools/replay.py", k, "--worker", worker, "--mode", mode],
                           capture_output=True, text=True, timeout=3600)
        log.write(f"{time.strftime('%H:%M:%S')} {k} rc={r.returncode} {time.time()-t:.0f}s {(r.stdout.strip().splitlines() or [''])[-1][:160]}\n"); log.flush()
    log.write("DONE\n"); log.flush()
