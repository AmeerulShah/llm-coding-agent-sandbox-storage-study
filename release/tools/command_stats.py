"""Command-level file-system profile of bash-only agent trajectories (pilot).

Usage: python3 command_stats.py <trajs_root> <out_prefix>
Splits every bash tool call into simple commands and classifies each by its
file-system intent. This is a static, command-level view; syscall-level
replay under strace is the next experiment.
"""
import collections, csv, glob, json, os, re, shlex, statistics, sys

CATS = [
    ("test",   re.compile(r"^(pytest|py\.test|tox|nox|rspec|phpunit|jest|mocha|vitest|ctest)\b"
                          r"|^python[0-9.]*\s+(-m\s+pytest|-m\s+unittest|\S*runtests\.py|\S*/tests?/)|^\S*runtests\.py|^\S*/?bin/test\b"
                          r"|^\S*/?(phpunit|rspec|jest|mocha)\b|^\./?runtest"
                          r"|^(cargo|go|npm|yarn|pnpm|mvn|\./mvnw|gradle|\./gradlew|ant|make|rake|deno|bun)\b.*\btest"
                          r"|^(bundle\s+exec\s+(rspec|rake|ruby\s+-Itest)|ruby\s+-Itest|npx\s+(jest|mocha|vitest))")),
    ("env",    re.compile(r"^(pip[0-9.]*|conda|uv|poetry|apt(-get)?|npm\s+(install|ci)|yarn\s+install|bundle\s+install|composer\s+install|cargo\s+fetch)\b|^python[0-9.]*\s+-m\s+pip")),
    ("edit",   re.compile(r"^sed\s+(-[a-zA-Z]*i|--in-place)|^(patch|ed|tee|truncate|touch|mv|cp|rm|mkdir)\b|^git\s+(apply|checkout|restore|stash|reset)\b|^cat\s*<<|(?<![0-9&>])>>?\s*(?!&|/dev/null)\S|open\([^)]*['\"][wa]")),
    ("vcs",    re.compile(r"^git\b")),
    ("search", re.compile(r"^(grep|egrep|rg|ag|find|ls|tree|locate|fd|xargs|du|wc|file|stat)\b")),
    ("read",   re.compile(r"^(cat|head|tail|less|more|nl|sed|awk|cut|sort|uniq|diff|cmp|od|hexdump|strings)\b")),
    ("script", re.compile(r"^(python[0-9.]*|ruby|node|php|perl|java|javac|go\s+run|cargo\s+(run|build|check)|go\s+build|deno|bun|npx|gcc|g\+\+|cc|clang|make|cmake|\./\S+)\b|^\./")),
    ("echo",   re.compile(r"^(echo|printf|true|false|cd|export|which|pwd|sleep|timeout)\b")),
]

def split_simple(cmd):
    """Split a bash string into simple commands, respecting quotes and heredocs."""
    cmd = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?([^\n]*)\n.*?\n\s*\1[ \t]*(?=\n|$)", r"<<HEREDOC\2", cmd, flags=re.S)
    parts, buf, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            buf.append(ch)
            if ch == "\\" and q == '"' and i + 1 < len(cmd):
                buf.append(cmd[i + 1]); i += 2; continue
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch; buf.append(ch)
        elif ch in "\n;|" or cmd.startswith("&&", i):
            parts.append("".join(buf)); buf = []
            if cmd.startswith("&&", i) or cmd.startswith("||", i):
                i += 1
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip() and not p.strip().startswith("#")]

def classify(simple):
    s = re.sub(r"^((sudo|env|timeout\s+\d+\S*)\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", simple)
    for name, rx in CATS:
        if rx.search(s):
            return name
    return "other"

def commands(traj):
    for m in traj.get("messages", []):
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            try:
                args = json.loads(args)
            except Exception:
                pass
            c = args.get("command") if isinstance(args, dict) else None
            if c:
                yield c

def main():
    root, prefix = sys.argv[1], sys.argv[2]
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*.traj.json"))):
        run = os.path.basename(os.path.dirname(path))
        inst = os.path.basename(path).replace(".traj.json", "")
        traj = json.load(open(path))
        calls = list(commands(traj))
        cnt = collections.Counter()
        for c in calls:
            for s in split_simple(c):
                cnt[classify(s)] += 1
        rows.append({"run": run, "instance": inst, "repo": inst.split("__")[0],
                     "tool_calls": len(calls), **{k: cnt.get(k, 0) for k, _ in CATS + [("other", None)]}})
    keys = list(rows[0].keys())
    with open(prefix + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    cats = [k for k, _ in CATS] + ["other"]
    tot = {k: sum(r[k] for r in rows) for k in cats}
    allc = sum(tot.values())
    fs = tot["read"] + tot["search"] + tot["edit"]
    calls = [r["tool_calls"] for r in rows]
    tests = [r["test"] for r in rows]
    by_repo = collections.Counter(r["repo"] for r in rows)
    lines = [
        f"# Pilot: command-level file-system profile ({len(rows)} trajectories)", "",
        f"- Runs: {', '.join(sorted(set(r['run'] for r in rows)))}",
        f"- Tool calls per task: median {statistics.median(calls)}, mean {statistics.mean(calls):.1f}, max {max(calls)}",
        f"- Simple commands classified: {allc}",
        f"- Share that read, search or edit files directly: {fs/allc:.1%}",
        f"- Tasks that ran tests at least once: {sum(1 for t in tests if t)/len(rows):.1%}; test runs per task median {statistics.median(tests)}",
        "", "| Category | Commands | Share |", "|---|---:|---:|",
    ] + [f"| {k} | {tot[k]} | {tot[k]/allc:.1%} |" for k in sorted(cats, key=lambda k: -tot[k])] + [
        "", "Repos: " + ", ".join(f"{k} {v}" for k, v in by_repo.most_common()), "",
        "Static classification by command name; syscall-level bytes, fsync and metadata counts need the strace replay.",
    ]
    open(prefix + ".md", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
