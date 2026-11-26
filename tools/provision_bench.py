#!/usr/bin/env python3
"""Measure sandbox provisioning strategies on this host (run inside `unshare -m`).

For each repository image (a prepared checkout with its .git, plus its virtualenv) we time
four ways to create a fresh, isolated sandbox and measure the new bytes each writes:
  copy      cp -a of repository and virtualenv
  clone     git clone --local (objects hard-linked) + checkout; virtualenv shared read-only
  worktree  git worktree add (object store shared); virtualenv shared read-only
  overlay   overlayfs mount with the image as lower layer; empty upper layer
Usage: unshare -m python3 provision_bench.py <trials>
"""
import json, os, shutil, statistics, subprocess, sys, time

ROOT = "/home/claude/research/asio"
B = "/work/prov"
TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
inst = json.load(open(f"{ROOT}/data/instances.json"))


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True)


def new_bytes(src, dst):
    """Bytes under dst not hard-linked to src (du counts each inode once per invocation)."""
    out = sh(f"du -sb {src} {dst}").stdout.split("\n")
    return int(out[1].split()[0]) if len(out) > 1 and out[1] else 0


def drop():
    sh("sync")


rows = []
for repo_dir in ("django", "sympy", "sphinx", "pytest", "requests"):
    # image = worker-2 sandbox clone checked out at a representative base commit, plus its env
    cands = sorted((k, v) for k, v in inst.items() if v["repo_dir"] == repo_dir)
    k, v = cands[len(cands) // 2]
    img = f"{B}/img-{repo_dir}"
    if not os.path.isdir(img):
        sh(f"git clone -q --local {ROOT}/repos_full/{repo_dir} {img}")
    sh(f"git -C {img} checkout -q -f {v['base_commit']} && git -C {img} clean -q -fdx")
    env = f"{ROOT}/envs/{v['env']}"
    if not os.path.isdir(env):
        cand_envs = sorted(e for e in os.listdir(f"{ROOT}/envs") if e.startswith(repo_dir + "-") and os.path.isdir(f"{ROOT}/envs/{e}"))
        env = f"{ROOT}/envs/{cand_envs[0]}"
    img_bytes = int(sh(f"du -sb {img}").stdout.split()[0]); env_bytes = int(sh(f"du -sb {env}").stdout.split()[0])
    for strat in ("copy", "clone", "worktree", "overlay"):
        for t in range(TRIALS):
            dst = f"{B}/dst"
            sh(f"umount {dst}/merged 2>/dev/null; rm -rf {dst}; git -C {img} worktree prune"); os.makedirs(dst)
            drop()
            t0 = time.perf_counter()
            if strat == "copy":
                r = sh(f"cp -a {img} {dst}/repo && cp -a {env} {dst}/env")
            elif strat == "clone":
                r = sh(f"git clone -q --local --no-checkout {img} {dst}/repo && git -C {dst}/repo checkout -q {v['base_commit']}")
            elif strat == "worktree":
                r = sh(f"git -C {img} worktree add -q --detach {dst}/repo {v['base_commit']}")
            else:
                os.makedirs(f"{dst}/upper"); os.makedirs(f"{dst}/work"); os.makedirs(f"{dst}/merged")
                r = sh(f"mount -t overlay overlay -o lowerdir={img},upperdir={dst}/upper,workdir={dst}/work {dst}/merged")
            dt = time.perf_counter() - t0
            if strat == "copy":
                nb = int(sh(f"du -sb {dst}").stdout.split()[0])
            elif strat in ("clone", "worktree"):
                nb = new_bytes(img, f"{dst}/repo")
            else:
                nb = int(sh(f"du -sb {dst}/upper {dst}/work").stdout.split()[0])
            rows.append({"repo": repo_dir, "strategy": strat, "trial": t, "seconds": dt, "new_bytes": nb, "rc": r.returncode,
                         "image_repo_bytes": img_bytes, "env_bytes": env_bytes})
            print(repo_dir, strat, t, f"{dt:.3f}s", nb, r.returncode, flush=True)
    sh(f"umount {B}/dst/merged 2>/dev/null; git -C {img} worktree prune; rm -rf {B}/dst")
    # one-time image cost of O2: bytecode compiled into the image
    before = int(sh(f"du -sb {img}").stdout.split()[0])
    sh(f"{env}/bin/python -m compileall -q -j 2 {img}")
    after = int(sh(f"du -sb {img}").stdout.split()[0])
    rows.append({"repo": repo_dir, "strategy": "precompile_image_growth", "trial": 0, "seconds": 0, "new_bytes": after - before,
                 "rc": 0, "image_repo_bytes": before, "env_bytes": env_bytes})
    sh(f"git -C {img} clean -q -fdx")
json.dump(rows, open(f"{ROOT}/results/provisioning_raw.json", "w"), indent=1)
