#!/usr/bin/env python3
"""Replay one mini-SWE-agent trajectory under strace in a private mount namespace.

Usage (outer):  python3 replay.py <instance_id> --worker N
The script re-executes itself under `unshare -m`. Inside the namespace it
bind-mounts a fresh sandbox clone at /testbed, a fresh home at /root and a
fresh /tmp, prepares the SWE-bench environment (untraced), then replays every
tool call in order with `bash -c`, exactly as mini-SWE-agent does, and traces
file-system syscalls with strace. Per-command logs are parsed immediately and
deleted; only aggregates are kept.

Outputs in runs/<instance_id>/:
  summary.json      instance-level totals, sizes, fidelity
  commands.jsonl    one row per replayed tool call
  files.jsonl.gz    one row per (file, class) touched, with op counts
"""
import argparse, collections, difflib, fcntl, glob, gzip, json, os, re, shlex, shutil, signal, subprocess, sys, time

ROOT = "/home/claude/research/asio"
TRAJ_DIR = f"{ROOT}/data/20260901_mini-v2.4.2_gemini-3-5-flash/trajs"
PY = {"3.9": "/opt/py39/bin/python3.9", "3.11": "/usr/bin/python3.11"}
sys.path.insert(0, f"{ROOT}/envs/tool/lib/python3.13/site-packages")
sys.path.insert(0, f"{ROOT}/tools")

TRACE = ("open,openat,openat2,creat,stat,lstat,fstat,newfstatat,statx,access,faccessat,faccessat2,"
         "readlink,readlinkat,getdents64,mkdir,mkdirat,rmdir,unlink,unlinkat,rename,renameat,renameat2,"
         "link,linkat,symlink,symlinkat,chmod,fchmod,fchmodat,utimensat,truncate,ftruncate,"
         "read,pread64,readv,preadv,preadv2,write,pwrite64,writev,pwritev,pwritev2,sendfile,copy_file_range,"
         "mmap,fsync,fdatasync,sync,syncfs,sync_file_range,msync,execve")
CMD_TIMEOUT = 300  # original agent timeout was 60 s; strace inflates run time

READS = {"read", "pread64", "readv", "preadv", "preadv2"}
WRITES = {"write", "pwrite64", "writev", "pwritev", "pwritev2"}
OPENS = {"open", "openat", "openat2", "creat"}
STATS = {"stat", "lstat", "newfstatat", "statx", "access", "faccessat", "faccessat2", "readlink", "readlinkat"}
FSTAT = {"fstat"}
MUT = {"mkdir": "mkdir", "mkdirat": "mkdir", "rmdir": "rmdir", "unlink": "unlink", "unlinkat": "unlink",
       "rename": "rename", "renameat": "rename", "renameat2": "rename", "link": "link", "linkat": "link",
       "symlink": "link", "symlinkat": "link", "chmod": "chmod", "fchmod": "chmod", "fchmodat": "chmod",
       "utimensat": "utime", "truncate": "truncate", "ftruncate": "truncate"}
SYNCS = {"fsync", "fdatasync", "sync", "syncfs", "sync_file_range", "msync"}

LINE = re.compile(r"^(\d+\.\d+) (\w+)\((.*)\) += (.*)$")
FDPATH = re.compile(r"^(?:-?\d+|AT_FDCWD)<([^>]*)>")
STRARG = re.compile(r'"((?:[^"\\]|\\.)*)"')
RETFD = re.compile(r"^(-?\d+)(?:<([^>]*)>)?")


def classify_path(p, env_dir, runtime_dir):
    if not p or not p.startswith("/"):
        return None
    if p.startswith("/testbed/.git/") or p == "/testbed/.git":
        return "git"
    if p.startswith("/testbed"):
        return "repo"
    if p.startswith(env_dir):
        return "env"
    if p.startswith(runtime_dir) or p.startswith("/usr/lib/python3"):
        return "runtime"
    if p.startswith("/tmp") or p.startswith("/var/tmp") or p.startswith("/dev/shm"):
        return "tmp"
    if p.startswith("/root"):
        return "home"
    if p.startswith(("/proc", "/sys", "/dev")):
        return "pseudo"
    return "system"


def norm_path(p, cls, env_dir, runtime_dir):
    if cls == "env":
        return "ENV" + p[len(env_dir):]
    if cls == "runtime" and p.startswith(runtime_dir):
        return "RUNTIME" + p[len(runtime_dir):]
    return p


def join(base, rel):
    if rel.startswith("/"):
        return os.path.normpath(rel)
    return os.path.normpath(os.path.join(base or "/", rel))


def unescape(s):
    try:
        return bytes(s, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    except Exception:
        return s


def parse_logs(logfiles, step, files, env_dir, runtime_dir):
    """Aggregate strace -ff logs of one command into `files` (dict) and return command totals."""
    tot = collections.Counter()
    step_reads = set()
    step_writes = collections.Counter()
    pids = set()
    tmin, tmax = None, None
    for lf in logfiles:
        pids.add(lf.rsplit(".", 1)[-1])
        with open(lf, errors="replace") as fh:
            for line in fh:
                m = LINE.match(line.rstrip("\n"))
                if not m:
                    continue
                ts, name, args, ret = float(m.group(1)), m.group(2), m.group(3), m.group(4)
                tmin = ts if tmin is None else min(tmin, ts)
                tmax = ts if tmax is None else max(tmax, ts)
                fail = ret.startswith("-1")
                path = None
                if name in READS or name in WRITES or name in FSTAT or name in SYNCS or name == "getdents64" or name == "ftruncate" or name == "fchmod":
                    fm = FDPATH.match(args)
                    path = fm.group(1) if fm else None
                elif name == "mmap":
                    parts = args.split(", ")
                    if len(parts) >= 5:
                        fm = FDPATH.match(parts[4])
                        path = fm.group(1) if fm else None
                        if path and not fail:
                            try:
                                length = int(parts[1])
                            except ValueError:
                                length = 0
                        else:
                            path = None
                elif name in OPENS:
                    rm = RETFD.match(ret)
                    if rm and rm.group(2):
                        path = rm.group(2)
                    else:
                        sm = STRARG.search(args)
                        dm = FDPATH.match(args)
                        if sm:
                            path = join(dm.group(1) if dm else None, unescape(sm.group(1)))
                elif name == "execve":
                    sm = STRARG.search(args)
                    path = unescape(sm.group(1)) if sm else None
                else:
                    sm = STRARG.search(args)
                    dm = FDPATH.match(args)
                    if sm:
                        path = join(dm.group(1) if dm else None, unescape(sm.group(1)))
                    elif dm and name in ("fchmodat", "utimensat"):
                        path = dm.group(1)
                if path is None:
                    if name in ("sync", "syncfs"):
                        tot["sync_ops"] += 1
                    continue
                cls = classify_path(path, env_dir, runtime_dir)
                if cls is None:
                    continue
                key = (norm_path(path, cls, env_dir, runtime_dir), cls)
                f = files.get(key)
                if f is None:
                    f = files[key] = collections.Counter()
                    f["first_step"] = step
                f["last_step"] = step
                if name in READS:
                    if not fail and cls != "pseudo":
                        n = int(RETFD.match(ret).group(1))
                        f["read_calls"] += 1; f["read_bytes"] += n
                        tot[f"read_bytes_{cls}"] += n; tot["read_calls"] += 1
                        if "first_read_step" not in f:
                            f["first_read_step"] = step
                        if f["first_read_step"] < step:
                            tot["reread_bytes"] += n
                            if key not in step_reads:
                                tot["reread_files"] += 1
                        if key not in step_reads:
                            step_reads.add(key); tot["read_files"] += 1
                elif name in WRITES:
                    if not fail and cls != "pseudo":
                        n = int(RETFD.match(ret).group(1))
                        f["write_calls"] += 1; f["write_bytes"] += n
                        tot[f"write_bytes_{cls}"] += n; tot["write_calls"] += 1
                        step_writes[key] += n
                elif name == "mmap":
                    f["mmap_bytes"] += length; tot[f"mmap_bytes_{cls}"] += length
                elif name in OPENS:
                    wr = any(x in args for x in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC")) or name == "creat"
                    if fail:
                        f["open_fail"] += 1; tot["open_fail"] += 1
                    else:
                        f["open_w" if wr else "open_r"] += 1; tot["open_w" if wr else "open_r"] += 1
                        if "O_CREAT" in args or name == "creat":
                            f["open_creat"] += 1
                        if "O_TRUNC" in args:
                            f["open_trunc"] += 1
                        if wr and key not in step_writes:
                            step_writes[key] += 0
                    tot[f"opens_{cls}"] += 1
                elif name in STATS:
                    f["stat_fail" if fail else "stat"] += 1
                    tot["stat_fail" if fail else "stat"] += 1; tot[f"stats_{cls}"] += 1
                elif name in FSTAT:
                    f["fstat"] += 1; tot["fstat"] += 1
                elif name == "getdents64":
                    if not fail:
                        f["getdents"] += 1; tot["getdents"] += 1; tot[f"getdents_{cls}"] += 1
                elif name in SYNCS:
                    f["fsync"] += 1; tot["fsync"] += 1; tot[f"fsync_{cls}"] += 1
                elif name == "execve":
                    if not fail:
                        tot["execve"] += 1
                elif name in MUT:
                    kind = MUT[name]
                    if not fail:
                        f[kind] += 1; tot[kind] += 1; tot[f"mut_{cls}"] += 1
    tot["write_files"] = len(step_writes)
    tot["wfiles"] = [[k[0], k[1], b] for k, b in step_writes.most_common(400)]
    tot["processes"] = len(pids)
    tot["trace_span_s"] = round((tmax - tmin), 3) if tmin is not None else 0
    return tot


def recorded_steps(traj):
    """Return [(command, recorded_returncode, recorded_output, created_ts)] in order."""
    msgs = traj["messages"]
    results = {}
    for m in msgs:
        if m.get("role") == "tool":
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            rc = re.search(r"<returncode>(-?\d+)</returncode>", c)
            raw = (m.get("extra") or {}).get("raw_output")
            if raw is None:
                om = re.search(r"<output>\n?(.*)</output>", c, re.S)
                raw = om.group(1) if om else c
            results[m.get("tool_call_id")] = (int(rc.group(1)) if rc else None, raw)
    steps = []
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        created = ((m.get("extra") or {}).get("response") or {}).get("created")
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            cmd = a.get("command")
            if not cmd:
                continue
            rc, out = results.get(tc.get("id"), (None, None))
            steps.append((cmd, rc, out, created))
    return steps


NORM = [(re.compile(r"0x[0-9a-fA-F]+"), "0x"), (re.compile(r"\d+\.\d+s\b"), "Ts"), (re.compile(r"in \d+\.\d+ ?s"), "in Ts"),
        (re.compile(r"/tmp/[\w./-]+"), "/tmp/X"), (re.compile(r"\s+"), " ")]


def norm_out(s):
    s = (s or "")[:20000]
    for rx, rep in NORM:
        s = rx.sub(rep, s)
    return s.strip()


def similarity(a, b):
    a, b = norm_out(a), norm_out(b)
    if a == b:
        return 1.0
    sm = difflib.SequenceMatcher(None, a[:4000], b[:4000], autojunk=False)
    return round(sm.ratio(), 4)


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True, **kw)


def du_bytes(path):
    r = sh(f"du -sb {shlex.quote(path)}")
    try:
        return int(r.stdout.split()[0])
    except Exception:
        return 0


def tree_sizes(repo_dir, commit):
    r = subprocess.run(["git", "-C", repo_dir, "ls-tree", "-r", "-l", commit], capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 4 and parts[1] == "blob":
            try:
                out[path] = (parts[2], int(parts[3]))
            except ValueError:
                pass
    return out


def build_env(inst, spec, env_dir, py):
    """Create the shared virtualenv for this env key (untraced, once)."""
    log = open(f"{env_dir}.build.log", "a")
    def run(c, t=900):
        log.write(f"$ {c}\n"); log.flush()
        try:
            r = subprocess.run(c, shell=True, cwd="/testbed", stdout=log, stderr=subprocess.STDOUT, timeout=t)
            return r.returncode
        except subprocess.TimeoutExpired:
            log.write("TIMEOUT\n"); return -9
    run(f"{PY[py]} -m venv {env_dir}")
    pip = f"{env_dir}/bin/python -m pip"
    run(f"{pip} install -q --upgrade 'pip<24.1' 'setuptools<70' wheel")
    pkgs = spec.get("pip_packages") or []
    if isinstance(pkgs, str):
        pkgs = json.loads(pkgs.replace("'", '"'))
    if pkgs:
        run(f"{pip} install -q " + " ".join(shlex.quote(p) for p in pkgs))
    p2 = spec.get("packages")
    if p2 and p2 != "requirements.txt" and p2 != "environment.yml":
        run(f"{pip} install -q {p2}")
    if inst["repo"] == "django/django":
        req = "/testbed/tests/requirements/py3.txt"
        if os.path.exists(req):
            for line in open(req):
                line = line.split("#")[0].strip()
                if line and not line.startswith("-"):
                    run(f"{pip} install -q {shlex.quote(line)}", t=300)
    install = spec.get("install", "python -m pip install -e .").replace("python -m pip", pip).replace("python setup.py install", f"{pip} install .")
    run(install, t=1200)
    log.close()


def prepare_sandbox(inst, spec, env_dir, clean=True):
    """Reset /testbed to the base commit and run the SWE-bench pre-install and install (untraced)."""
    c = inst["base_commit"]
    sh(f"git -C /testbed checkout -q -f {c}" + (" && git -C /testbed clean -q -fdx" if clean else ""), timeout=600)
    for pre in spec.get("pre_install") or []:
        if pre.startswith("apt-get") or "locale-gen" in pre:
            continue
        sh(pre, cwd="/testbed", timeout=300)
    pip = f"{env_dir}/bin/python -m pip"
    install = spec.get("install", "python -m pip install -e .")
    install = install.replace("python -m pip", pip).replace("python setup.py install", f"{pip} install .")
    install = re.sub(r"(\.\[[^\]]*\])", ".", install)
    r = sh(f"{install} --no-deps --no-build-isolation -q", cwd="/testbed", timeout=900)
    return r.returncode


def scan_residency(out, sbx, env_dir, runtime_dir, tree, t_start):
    """Record which pages of each image file are resident in the page cache (mincore), per file.
    Covers the repository tree, .git, the virtualenv, the Python runtime and system libraries/binaries.
    Files modified during the replay are recorded separately (their pages are writes, not reads)."""
    import ctypes, ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
    PS = os.sysconf("SC_PAGE_SIZE")
    roots = [("repo", "/testbed"), ("env", env_dir), ("runtime", runtime_dir if runtime_dir != "/usr" else "/usr/lib/python3.11"),
             ("system", "/usr/lib/x86_64-linux-gnu"), ("system", "/usr/bin"), ("system", "/usr/lib/git-core")]
    recs = []
    for cls0, root in roots:
        for dp, dns, fns in os.walk(root):
            for fn in fns:
                fp = os.path.join(dp, fn)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if (st.st_mode & 0o170000) != 0o100000 or st.st_size == 0:
                    continue
                cls = cls0
                rel = None
                if cls0 == "repo":
                    rel = fp[len("/testbed/"):]
                    cls = "git" if rel.startswith(".git/") or rel == ".git" else "repo"
                try:
                    fd = os.open(fp, os.O_RDONLY | os.O_NOATIME)
                except OSError:
                    try:
                        fd = os.open(fp, os.O_RDONLY)
                    except OSError:
                        continue
                n = (st.st_size + PS - 1) // PS
                addr = libc.mmap(None, st.st_size, 1, 1, fd, 0)  # PROT_READ, MAP_SHARED
                if addr in (None, ctypes.c_void_p(-1).value):
                    os.close(fd); continue
                vec = ctypes.create_string_buffer(n)
                libc.mincore(addr, st.st_size, vec)
                libc.munmap(addr, st.st_size); os.close(fd)
                raw = vec.raw
                res = [k for k in range(n) if raw[k] & 1]
                if not res:
                    continue
                runs = []
                for k in res:
                    if runs and runs[-1][0] + runs[-1][1] == k:
                        runs[-1][1] += 1
                    else:
                        runs.append([k, 1])
                blob = tree.get(rel, (None, None))[0] if rel else None
                recs.append({"path": fp if cls0 != "repo" else rel, "cls": cls, "size": st.st_size, "pages": n,
                             "resident": len(res), "runs": runs, "blob": blob, "written": st.st_mtime >= t_start})
    with gzip.open(f"{out}/resident.jsonl.gz", "wt") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def inside(args):
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS as SPECS
    instances = json.load(open(f"{ROOT}/data/instances.json"))
    inst = instances[args.instance]
    spec = SPECS[inst["repo"]].get(inst["spec_version"], {})
    w = f"/work/w{args.worker}"
    out = f"{ROOT}/runs/{args.instance}" if args.mode == "trace" else f"{ROOT}/runs_{args.mode}{os.environ.get('RUNS_SUFFIX', '')}/{args.instance}"
    os.makedirs(out, exist_ok=True)
    env_dir = f"{ROOT}/envs/{inst['env']}"
    runtime_dir = os.path.dirname(os.path.dirname(os.path.realpath(PY[inst['python']])))  # /opt/py39 or /usr

    stack = None
    if args.mode == "stack":
        # Recommended stack: per-version base image with bytecode compiled in (O1 + O2), the task's commit checked out
        # in an overlayfs upper layer, and git reading attributes from the tree (O3, set in the environment below).
        sbx = None
        for d in (f"{w}/home", f"{w}/tmp", f"{w}/logs", f"{w}/upper", f"{w}/owork"):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        grp = f"{inst['repo_dir']}-{inst['version']}"
        base_commit = dict(l.split() for l in open(f"{ROOT}/results/setup_base_commits.txt"))[f"base-{grp}"]
        base = f"/work/stackbase/{grp}"
        os.makedirs("/work/stackbase", exist_ok=True)
        lock = open(f"{env_dir}.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(f"{base}.ready"):
            shutil.rmtree(base, ignore_errors=True)
            sh(f"git clone -q --local {ROOT}/repos_full/{inst['repo_dir']} {base}", timeout=1200)
            sh(f"git -C {base} checkout -q -f {base_commit}", timeout=600)
            sh(f"{env_dir}/bin/python -m compileall -q -j 2 {base}", cwd=base, timeout=900)
            open(f"{base}.ready", "w").write(time.ctime())
        t0s = time.time()
        r = sh(f"mount -t overlay overlay -o lowerdir={base},upperdir={w}/upper,workdir={w}/owork /testbed")
        if r.returncode != 0:
            print("overlay mount failed", r.stderr, file=sys.stderr); sys.exit(3)
        sh(f"git -C /testbed checkout -q -f {inst['base_commit']}", timeout=600)
        t1s = time.time(); delta_bytes = du_bytes(f"{w}/upper")
        sh(f"{env_dir}/bin/python -m compileall -q -j 2 /testbed", cwd="/testbed", timeout=900)  # writes only stale bytecode
        t2s = time.time(); pyc_bytes = du_bytes(f"{w}/upper") - delta_bytes
        install_rc = prepare_sandbox(inst, spec, env_dir, clean=False)
        t3s = time.time()
        stack = {"checkout_s": round(t1s - t0s, 3), "compile_s": round(t2s - t1s, 3), "install_s": round(t3s - t2s, 3),
                 "delta_bytes": delta_bytes, "delta_pyc_bytes": pyc_bytes, "setup_upper_bytes": du_bytes(f"{w}/upper"),
                 "base_commit": base_commit}
        fcntl.flock(lock, fcntl.LOCK_UN)
    else:
        # Sandbox clone per worker per repo (hard-linked objects; .git lives inside /testbed as in SWE-bench images).
        sbx = f"{w}/sbx-{inst['repo_dir']}"
        if not os.path.isdir(f"{sbx}/.git"):
            shutil.rmtree(sbx, ignore_errors=True)
            sh(f"git clone -q --local {ROOT}/repos_full/{inst['repo_dir']} {sbx}", timeout=1200)
        for d in (f"{w}/home", f"{w}/tmp", f"{w}/logs"):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        sh(f"mount --bind {sbx} /testbed")

        # Environment build and per-instance install run before /root and /tmp are replaced,
        # so pip keeps the workspace proxy settings. Nothing here is traced.
        lock = open(f"{env_dir}.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
        sh(f"git -C /testbed checkout -q -f {inst['base_commit']} && git -C /testbed clean -q -fdx", timeout=600)
        if not os.path.exists(f"{env_dir}/.built"):
            build_env(inst, spec, env_dir, inst["python"])
            open(f"{env_dir}/.built", "w").write(time.ctime())
        install_rc = prepare_sandbox(inst, spec, env_dir)
        if args.mode in ("precompiled", "overlay_precompiled", "untraced_precompiled"):
            # Variant: bytecode for the repository is built into the base image before the agent starts.
            sh(f"{env_dir}/bin/python -m compileall -q -j 2 /testbed", cwd="/testbed", timeout=900)
        fcntl.flock(lock, fcntl.LOCK_UN)
        if args.mode.startswith("overlay"):
            # Real copy-on-write sandbox: the prepared checkout becomes a read-only lower layer.
            for d in (f"{w}/upper", f"{w}/owork"):
                shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
            sh("umount /testbed")
            r = sh(f"mount -t overlay overlay -o lowerdir={sbx},upperdir={w}/upper,workdir={w}/owork /testbed")
            if r.returncode != 0:
                print("overlay mount failed", r.stderr, file=sys.stderr); sys.exit(3)
    remote = None
    if args.mode == "remote":
        # Emulated remote image layer (tools/remotefs.py): the prepared checkout, the virtual environment and the
        # Python runtime are served through FUSE with an injected round-trip time; the writable layer stays local.
        delay, cache = os.environ.get("REMOTE_DELAY_US", "0"), os.environ.get("REMOTE_CACHE", "none")
        fz = f"/work/fuse/w{args.worker}"
        sh(f"umount {fz}/repo {fz}/env {fz}/rt 2>/dev/null; umount /testbed")
        for d in (f"{fz}/repo", f"{fz}/env_src", f"{fz}/rt_src", f"{w}/upper", f"{w}/owork"):
            shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        rt = runtime_dir if runtime_dir != "/usr" else "/usr/lib/python3.11"
        sh(f"mount --bind {env_dir} {fz}/env_src && mount --bind {rt} {fz}/rt_src")
        py = f"{ROOT}/envs/tool/bin/python"
        daemons = []
        for src, mnt, tag in ((sbx, f"{fz}/repo", "repo"), (f"{fz}/env_src", env_dir, "env"), (f"{fz}/rt_src", rt, "runtime")):
            daemons.append((tag, mnt, subprocess.Popen([py, f"{ROOT}/tools/remotefs.py", src, mnt, delay, cache, f"{fz}/{tag}.stats.json"],
                                                       stdout=subprocess.DEVNULL, stderr=open(f"{fz}/{tag}.log", "w"))))
        for _ in range(100):
            if all(os.path.ismount(m) for _, m, _ in daemons):
                break
            time.sleep(0.05)
        r = sh(f"mount -t overlay overlay -o lowerdir={fz}/repo,upperdir={w}/upper,workdir={w}/owork /testbed")
        if r.returncode != 0:
            print("overlay over remotefs failed", r.stderr, file=sys.stderr); sys.exit(3)
        remote = {"delay_us": float(delay), "cache": cache, "daemons": daemons, "fz": fz}
    sh(f"mount --bind {w}/home /root && mount --bind {w}/tmp /tmp")

    # Minimal analogue of the image's BASH_ENV activation script.
    with open("/root/.bashrc", "w") as fh:
        fh.write(f"export PATH={env_dir}/bin:$PATH\nexport VIRTUAL_ENV={env_dir}\n")
    env = {"PATH": f"{env_dir}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           "HOME": "/root", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PAGER": "cat", "MANPAGER": "cat",
           "LESS": "-R", "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1", "BASH_ENV": "/root/.bashrc",
           "VIRTUAL_ENV": env_dir, "PIP_NO_INDEX": "1"}
    if args.mode in ("nopyc", "untraced_nopyc"):
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.mode == "stack":
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "attr.tree", "GIT_CONFIG_VALUE_0": "HEAD"})

    tree = tree_sizes("/testbed", inst["base_commit"])
    time.sleep(1.1)  # mtime granularity guard between setup and replay
    base = {"repo_tree_bytes": sum(s for _, s in tree.values()), "repo_tree_files": len(tree),
            "git_dir_bytes": du_bytes("/testbed/.git"), "env_bytes": du_bytes(env_dir),
            "runtime_bytes": du_bytes(runtime_dir if runtime_dir != "/usr" else "/usr/lib/python3.11"),
            "worktree_bytes_after_install": du_bytes("/testbed") - du_bytes("/testbed/.git")}

    traj = json.load(open(f"{TRAJ_DIR}/{args.instance}.traj.json"))
    steps = recorded_steps(traj)
    files = {}
    rows = []
    if args.mode == "resident":
        # Cold page cache: only what the tool calls touch will be resident afterwards.
        sh("sync"); open("/proc/sys/vm/drop_caches", "w").write("3\n")
    t_start = time.time()
    for i, (cmd, rec_rc, rec_out, created) in enumerate(steps):
        for f in glob.glob(f"{w}/logs/*"):
            os.remove(f)
        argv = ["strace", "-ff", "--seccomp-bpf", "-qq", "-ttt", "-y", "-s", "0", "-e", f"trace={TRACE}",
                "-o", f"{w}/logs/c", "bash", "-c", cmd]
        if args.mode in ("untraced", "overlay", "overlay_precompiled", "untraced_nopyc", "untraced_precompiled", "resident", "stack", "remote"):
            argv = ["bash", "-c", cmd]
        t0 = time.time()
        timed_out = False
        p = subprocess.Popen(argv, cwd="/testbed", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            outb, _ = p.communicate(timeout=CMD_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(p.pid, signal.SIGKILL)
            outb, _ = p.communicate()
        dt = time.time() - t0
        out_s = outb.decode("utf-8", "replace")
        tot = parse_logs(sorted(glob.glob(f"{w}/logs/c.*")), i, files, env_dir, runtime_dir)
        rows.append({"step": i, "cmd": cmd[:500], "rc": None if timed_out else p.returncode, "rec_rc": rec_rc,
                     "timed_out": timed_out, "sim": similarity(out_s, rec_out), "dur_traced_s": round(dt, 3),
                     "created": created, **tot})
    wall = time.time() - t_start
    if remote is not None:
        stats = {}
        sh("umount /testbed")
        for tag, mnt, proc in remote.pop("daemons"):
            sh(f"fusermount3 -u {mnt}")
            try:
                proc.wait(timeout=60)
                stats[tag] = json.load(open(f"{remote['fz']}/{tag}.stats.json"))
            except Exception as e:  # noqa: BLE001
                stats[tag] = {"error": str(e)}
        remote["requests"] = stats
        remote["tool_s"] = round(sum(r["dur_traced_s"] for r in rows), 3)
    if args.mode == "resident":
        scan_residency(out, sbx, env_dir, runtime_dir, tree, t_start)

    # Final write set relative to the base commit (what a copy-on-write upper layer would hold).
    st = sh("git -C /testbed status --porcelain --ignored --untracked-files=all", timeout=300).stdout.splitlines()
    final = []
    for line in st:
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        full = f"/testbed/{path}"
        if os.path.isfile(full) and os.path.getmtime(full) < t_start:
            continue  # created by the untraced setup/install, i.e. part of the base image
        size = os.path.getsize(full) if os.path.isfile(full) else 0
        orig = tree.get(path, (None, 0))[1]
        final.append({"path": path, "code": code, "size": size, "orig_size": orig, "in_tree": path in tree})

    with open(f"{out}/commands.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    with gzip.open(f"{out}/files.jsonl.gz", "wt") as fh:
        for (path, cls), c in files.items():
            rel = path[len("/testbed/"):] if path.startswith("/testbed/") else None
            blob = tree.get(rel, (None, None)) if rel else (None, None)
            fh.write(json.dumps({"path": path, "cls": cls, "blob": blob[0], "orig_size": blob[1], **c}) + "\n")
    upper = None
    if args.mode.startswith("overlay") or args.mode == "stack":
        tot_b = 0; n_f = 0; n_wh = 0; pyc_b = 0; n_dir = 0
        for dp, dns, fns in os.walk(f"{w}/upper"):
            n_dir += len(dns)
            for fn in fns:
                fp = os.path.join(dp, fn)
                st = os.lstat(fp)
                if (st.st_mode & 0o170000) == 0o020000:  # character device = whiteout
                    n_wh += 1; continue
                n_f += 1; tot_b += st.st_size
                if fn.endswith(".pyc"):
                    pyc_b += st.st_size
        upper = {"bytes": tot_b, "files": n_f, "whiteouts": n_wh, "dirs": n_dir, "pyc_bytes": pyc_b,
                 "du_bytes": du_bytes(f"{w}/upper")}
    rc_known = [r for r in rows if r["rec_rc"] is not None and not r["timed_out"]]
    summary = {"instance": args.instance, **inst, "mode": args.mode, "t_start": t_start, "install_rc": install_rc, "n_steps": len(steps),
               "replay_wall_s": round(wall, 1), "base": base, "final_writeset": final,
               "rc_match": round(sum(1 for r in rc_known if r["rc"] == r["rec_rc"]) / max(1, len(rc_known)), 4),
               "sim_mean": round(sum(r["sim"] for r in rows) / max(1, len(rows)), 4),
               "timeouts": sum(1 for r in rows if r["timed_out"]), "overlay_upper": upper, "stack": stack, "remote": remote}
    json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
    print(json.dumps({k: summary[k] for k in ("instance", "n_steps", "replay_wall_s", "rc_match", "sim_mean", "timeouts", "install_rc")}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--inside", action="store_true")
    ap.add_argument("--mode", default="trace", choices=["trace", "untraced", "nopyc", "precompiled", "overlay", "overlay_precompiled", "untraced_nopyc", "untraced_precompiled", "resident", "stack", "remote"])
    args = ap.parse_args()
    if args.inside:
        return inside(args)
    os.makedirs(f"/work/w{args.worker}", exist_ok=True)
    cmd = ["unshare", "-m", "-p", "--fork", "--mount-proc", "--propagation", "private", sys.executable, os.path.abspath(__file__), args.instance,
           "--worker", str(args.worker), "--inside", "--mode", args.mode]
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
