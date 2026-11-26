import gzip, json, os, re, sys, glob
root = sys.argv[1]; out = sys.argv[2]
rows = {}
for d in sorted(glob.glob(os.path.join(root, "logs", "*"))):
    inst = os.path.basename(d)
    p = os.path.join(d, "test_output.txt.gz")
    if not os.path.exists(p):
        continue
    txt = gzip.open(p, "rt", errors="replace").read()
    m = re.search(r"git checkout ([0-9a-f]{40}) ", txt) or re.search(r"diff ([0-9a-f]{40})", txt)
    py = re.search(r"Python (3\.\d+)\.\d+", txt)
    rows[inst] = {"base_commit": m.group(1) if m else None, "python_hint": py.group(1) if py else None}
json.dump(rows, open(out, "w"), indent=1)
ok = sum(1 for r in rows.values() if r["base_commit"])
print(len(rows), "instances,", ok, "with base_commit")
from collections import Counter
print(Counter(r["python_hint"] for r in rows.values()).most_common())
