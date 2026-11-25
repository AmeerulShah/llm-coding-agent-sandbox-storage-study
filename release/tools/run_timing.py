"""Untraced timing pass, one worker, variants interleaved per task so drift affects all variants alike."""
import os, subprocess, sys, time
ROOT = "/home/claude/research/asio"
timing = open(f"{ROOT}/data/ablation_subset.txt").read().split()
abl = set(open(f"{ROOT}/data/ablation_subset.txt").read().split())
log = open(f"{ROOT}/runs_untraced/_timing.log", "a")
for k in timing:
    for mode in (["untraced", "untraced_nopyc", "untraced_precompiled"] if k in abl else ["untraced"]):
        outd = f"{ROOT}/runs_{mode}"
        if os.path.exists(f"{outd}/{k}/summary.json"):
            continue
        t = time.time()
        r = subprocess.run([f"{ROOT}/envs/tool/bin/python", f"{ROOT}/tools/replay.py", k, "--worker", "5", "--mode", mode],
                           capture_output=True, text=True, timeout=3600)
        log.write(f"{time.strftime('%H:%M:%S')} {mode} {k} rc={r.returncode} {time.time()-t:.0f}s\n"); log.flush()
log.write("DONE\n")
