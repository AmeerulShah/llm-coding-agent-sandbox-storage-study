#!/usr/bin/env python3
"""Reproducibility record for the release: host and tool versions, the package list of every replay environment,
the run logs, and SHA-256 checksums of every released file. Writes release/reproducibility/ENVIRONMENT.md,
release/reproducibility/envs.tar.gz, release/reproducibility/logs/ and release/reproducibility/MANIFEST.sha256."""
import glob, gzip, hashlib, io, os, platform, shutil, subprocess, tarfile

ROOT = "/home/claude/research/asio"; REL = f"{ROOT}/release"; REP = f"{REL}/reproducibility"


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()


for old in ("envs", "logs", "ENVIRONMENT.md", "MANIFEST.sha256", "envs.tar.gz"):  # earlier flat layout
    q = f"{REL}/{old}"
    shutil.rmtree(q) if os.path.isdir(q) else (os.remove(q) if os.path.exists(q) else None)
os.makedirs(f"{REP}/logs", exist_ok=True)
cpu = sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip()
lines = ["# Measurement environment", "",
         "All experiments ran on one cloud virtual machine, one experiment at a time unless stated in the paper.", "",
         "| Item | Value |", "|---|---|",
         f"| CPU | {cpu} ({os.cpu_count()} vCPUs) |",
         f"| Memory | {int(open('/proc/meminfo').readline().split()[1]) / 2**20:.1f} GiB |",
         f"| OS | {sh('. /etc/os-release; echo $PRETTY_NAME')} |",
         f"| Kernel | {platform.release()} |",
         f"| strace | {sh('strace -V | head -1')} |",
         f"| git | {sh('git --version')} |",
         f"| CPython 3.9 (built from source) | {sh('/opt/py39/bin/python3.9 -V 2>&1')} |",
         f"| CPython 3.11 (system) | {sh('python3.11 -V 2>&1')} |",
         f"| Analysis Python | {sh(ROOT + '/envs/tool/bin/python -V')} |",
         f"| FUSE (remote-layer emulation) | fusermount3 {sh('fusermount3 -V | cut -d: -f2').strip()}, pyfuse3 {sh(ROOT + '/envs/tool/bin/python -c \"import pyfuse3; print(pyfuse3.__version__)\"')}, trio {sh(ROOT + '/envs/tool/bin/python -c \"import trio; print(trio.__version__)\"')} |",
         f"| swebench (specifications) | {sh(ROOT + '/envs/tool/bin/python -m pip show swebench 2>/dev/null | grep Version')} |",
         "", "Replay environments: one virtual environment per repository version; package lists in `envs.tar.gz`.", ""]
envs = {}
for e in sorted(glob.glob(f"{ROOT}/envs/*/bin/python")):
    name = e.split("/")[-3]
    if name == "tool":
        continue
    envs[name] = (sh(f"{e} -m pip freeze 2>/dev/null") + "\n").encode()
buf = io.BytesIO()  # deterministic archive: fixed names, order and timestamps, so its checksum is stable
with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
    for name in sorted(envs):
        ti = tarfile.TarInfo(f"envs/{name}.txt"); ti.size = len(envs[name]); ti.mtime = 0; ti.mode = 0o644
        tf.addfile(ti, io.BytesIO(envs[name]))
with gzip.GzipFile(f"{REP}/envs.tar.gz", "wb", mtime=0) as gz:
    gz.write(buf.getvalue())
open(f"{REP}/ENVIRONMENT.md", "w").write("\n".join(lines) + "\n")
logs = ["results/setup_bench.log", "results/git_attr_bench.log", "results/timing_r0.log", "results/timing_r1.log",
        "results/timing_r2.log", "results/provision_bench.log", "runs_resident/_run.log", "runs_untraced/_timing.log",
        "results/stack.log", "results/remote_bench.log", "results/git_remote_bench.log"]
for l in logs:
    if os.path.exists(f"{ROOT}/{l}"):
        shutil.copy(f"{ROOT}/{l}", f"{REP}/logs/{l.replace('/', '__')}")
with open(f"{REP}/MANIFEST.sha256", "w") as fh:
    for p in sorted(glob.glob(f"{REL}/**/*", recursive=True)):
        if os.path.isfile(p) and not p.endswith("MANIFEST.sha256") and "/archive/" not in p:
            fh.write(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {os.path.relpath(p, REL)}\n")
    for p in sorted(glob.glob("/home/claude/research/archive/*")):
        fh.write(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  archive/{os.path.basename(p)}\n")
print(open(f"{REP}/ENVIRONMENT.md").read())
