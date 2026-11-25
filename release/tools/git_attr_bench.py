#!/usr/bin/env python3
"""Attribute source for git in agent sandboxes (run inside `unshare -m`).

Replays the recorded read-only git calls of a random sample of tasks in the task's sandbox at its base commit,
with git's default attribute lookup (per-directory .gitattributes files in the working tree) and with
attr.tree=HEAD (attributes read from the commit's tree), set through GIT_CONFIG_* environment variables so it
applies to every git process a call starts. For each call and configuration: metadata system calls and failed
lookups under strace, untraced wall time, exit code and output. Writes results/git_attr_bench.csv.
Sample: every task that runs a history search (git log -S/-G/-p) plus n random other tasks.
Usage: unshare -m python3 git_attr_bench.py [n_random]
"""
import csv, json, os, random, re, subprocess, sys, time

ROOT = "/home/claude/research/asio"
W = "/work/w0"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
inst = json.load(open(f"{ROOT}/data/instances.json"))
inc = [r["instance"] for r in csv.DictReader(open(f"{ROOT}/results/instances.csv"))]
cmds = {}
for r in csv.DictReader(open(f"{ROOT}/results/commands.csv")):
    if r["cat"] == "vcs":
        cmds.setdefault(r["instance"], []).append((int(r["step"]), r["cmd"]))
READONLY = {"log", "show", "diff", "status", "blame", "grep", "ls-files", "rev-parse", "describe", "rev-list",
            "shortlog", "cat-file", "ls-tree", "whatchanged", "name-rev", "merge-base", "branch", "tag", "remote"}
WRITE_WORDS = re.compile(r"(^|\s)(stash|checkout|apply|commit|add|reset|restore|rm|mv|clean|cherry-pick|am|merge|rebase|switch|init|config|gc|fetch|pull|push|worktree|update-index)(\s|$)")


def readonly(cmd):
    subs = re.findall(r"\bgit\s+(?:-[Cc]\s+\S+\s+|--no-pager\s+|-P\s+)*([a-z-]+)", cmd)
    if not subs or any(s not in READONLY for s in subs):
        return False
    if re.search(r"(?<![0-9&])>(?!&)", cmd.replace("2>&1", "").replace(">/dev/null", "")):
        return False  # writes a file
    if WRITE_WORDS.search(cmd.replace("git log", "").replace("git show", "")) and "branch" not in subs:
        return False
    return "tee " not in cmd and "sed -i" not in cmd


TRACE = "openat,open,stat,lstat,newfstatat,statx,access,faccessat,faccessat2,readlink,readlinkat,getdents64"
ATTR = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "attr.tree", "GIT_CONFIG_VALUE_0": "HEAD"}
BASE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "PAGER": "cat", "GIT_PAGER": "cat", "MANPAGER": "cat"}


def run(cmd, env, traced):
    argv = ["bash", "-c", cmd]
    if traced:
        argv = ["strace", "-f", "-qq", "-e", f"trace={TRACE}", "-o", f"{W}/git.trace"] + argv
    t0 = time.perf_counter()
    try:
        p = subprocess.run(argv, cwd="/testbed", env=env, capture_output=True, timeout=300)
        rc, out = p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        rc, out = None, b""
    dt = time.perf_counter() - t0
    meta = fail = attr = 0
    if traced and os.path.exists(f"{W}/git.trace"):
        for line in open(f"{W}/git.trace", errors="replace"):
            if "(" not in line or "resumed>" in line:
                continue
            meta += 1
            if "= -1 E" in line:
                fail += 1
                if ".gitattributes" in line:
                    attr += 1
    return rc, out, dt, meta, fail, attr


random.seed(20261121)
HIST = re.compile(r"git\s+log\b.*(-S|-G|-p\b|--patch)|git\s+log\s+-[A-Za-z]*p")
hist = [i for i in inc if any(HIST.search(c) for _, c in cmds.get(i, []))]
rest = [i for i in inc if i not in set(hist) and any(readonly(c) for _, c in cmds.get(i, []))]
sample = hist + random.sample(rest, N)  # every task with a history search, plus N random others
os.makedirs("/testbed", exist_ok=True)
OUT = f"{ROOT}/results/git_attr_bench.csv"
COUNTS_ONLY = os.environ.get("COUNTS_ONLY") == "1"  # second pass: traced counts and output identity, no timing
done = set()
if os.path.exists(OUT):
    done = {r["instance"] for r in csv.DictReader(open(OUT))}
f = open(OUT, "a", newline=""); w = csv.writer(f)
if not done:
    w.writerow(["instance", "step", "cmd", "config", "rc", "same_output", "seconds", "meta_ops", "failed", "gitattributes_failed", "stratum"])
for n, i in enumerate(sample):
    if i in done:
        continue
    v = inst[i]; sbx = f"{W}/sbx-{v['repo_dir']}"
    if not os.path.isdir(f"{sbx}/.git"):
        subprocess.run(f"git clone -q --local {ROOT}/repos_full/{v['repo_dir']} {sbx}", shell=True)
    subprocess.run(f"git -C {sbx} checkout -q -f {v['base_commit']} && git -C {sbx} clean -q -fdx", shell=True)
    subprocess.run(f"mount --bind {sbx} /testbed", shell=True)
    subprocess.run("git -C /testbed status -s >/dev/null", shell=True)  # settle the index once
    for step, cmd in cmds[i]:
        if not readonly(cmd):
            continue
        res = {}
        for cfg in random.sample(["default", "attr_tree"], 2):
            env = {**BASE_ENV, **(ATTR if cfg == "attr_tree" else {})}
            if COUNTS_ONLY:
                rc, out, _, meta, fail, attr = run(cmd, env, True)  # traced counts; output is unaffected by tracing
                dt = float("nan")
            else:
                run(cmd, env, False)                                  # warm the page cache
                rc, out, dt, _, _, _ = run(cmd, env, False)           # untraced timing
                _, _, _, meta, fail, attr = run(cmd, env, True)       # traced counts
            res[cfg] = (rc, out, dt, meta, fail, attr)
        same = res["default"][1] == res["attr_tree"][1] and res["default"][0] == res["attr_tree"][0]
        for cfg, (rc, out, dt, meta, fail, attr) in res.items():
            w.writerow([i, step, cmd[:200], cfg, rc, int(same), "" if dt != dt else f"{dt:.4f}", meta, fail, attr, "history" if i in set(hist) else "random"])
        f.flush()
    subprocess.run("umount /testbed", shell=True)
    print(n, i, flush=True)
