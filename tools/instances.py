"""Build the replay instance table: repo, base commit, SWE-bench version, env and python policy."""
import json, re, subprocess, sys
sys.path.insert(0, "/home/claude/research/asio/envs/tool/lib/python3.13/site-packages")
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS as SPECS

ROOT = "/home/claude/research/asio"
REPOS = {"django": "django/django", "sympy": "sympy/sympy", "sphinx-doc": "sphinx-doc/sphinx",
         "pytest-dev": "pytest-dev/pytest", "psf": "psf/requests"}
DIRS = {"django/django": "django", "sympy/sympy": "sympy", "sphinx-doc/sphinx": "sphinx",
        "pytest-dev/pytest": "pytest", "psf/requests": "requests"}

def show(repo_dir, commit, path):
    r = subprocess.run(["git", "-C", repo_dir, "show", f"{commit}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""

def describe(repo_dir, commit):
    r = subprocess.run(["git", "-C", repo_dir, "describe", "--tags", "--abbrev=0", commit], capture_output=True, text=True)
    return r.stdout.strip()

def mm(s):
    m = re.search(r"(\d+)\.(\d+)", s or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None

def version(repo, d, c):
    if repo == "django/django":
        m = re.search(r"VERSION\s*=\s*\((\d+),\s*(\d+)", show(d, c, "django/__init__.py"))
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if repo == "sympy/sympy":
        txt = show(d, c, "sympy/release.py") or show(d, c, "sympy/__init__.py")
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", txt)
        return mm(m.group(1)) if m else None
    if repo == "sphinx-doc/sphinx":
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", show(d, c, "sphinx/__init__.py"))
        return mm(m.group(1)) if m else None
    if repo == "psf/requests":
        txt = show(d, c, "requests/__version__.py") or show(d, c, "requests/__init__.py")
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", txt)
        return mm(m.group(1)) if m else None
    if repo == "pytest-dev/pytest":
        return mm(describe(d, c))

def nearest(repo, v):
    vs = list(SPECS[repo])
    if v in vs:
        return v
    key = lambda s: tuple(int(x) for x in s.split("."))
    try:
        vv = key(v)
    except Exception:
        return vs[-1]
    below = [s for s in vs if key(s) <= vv]
    return max(below, key=key) if below else min(vs, key=key)

def pyfor(spec_py):
    return "3.11" if spec_py and tuple(map(int, spec_py.split("."))) >= (3, 10) else "3.9"

def main():
    meta = json.load(open(f"{ROOT}/data/meta_v242.json"))
    out = {}
    for inst, m in meta.items():
        owner = inst.split("__")[0]
        if owner not in REPOS:
            continue
        repo = REPOS[owner]
        d = f"{ROOT}/repos_full/{DIRS[repo]}"
        v = version(repo, d, m["base_commit"])
        sv = nearest(repo, v) if v else None
        spec = SPECS[repo].get(sv, {})
        py = pyfor(spec.get("python"))
        out[inst] = {"repo": repo, "repo_dir": DIRS[repo], "base_commit": m["base_commit"], "version": v,
                     "spec_version": sv, "spec_python": spec.get("python"), "python": py,
                     "env": f"{DIRS[repo]}-{sv}-py{py}"}
    json.dump(out, open(f"{ROOT}/data/instances.json", "w"), indent=1)
    from collections import Counter
    print(len(out), "instances")
    print(Counter(o["env"] for o in out.values()).most_common())
    print("missing version:", [k for k, o in out.items() if not o["version"]][:10])

if __name__ == "__main__":
    main()
