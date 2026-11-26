#!/usr/bin/env python3
"""Share of failed lookups and metadata operations that are probes for missing .gitattributes files (all included tasks)."""
import csv, glob, gzip, json
ROOT = "/home/claude/research/asio"
inc = {r["instance"]: r for r in csv.DictReader(open(f"{ROOT}/results/instances.csv"))}
fail = attr = 0
for p in glob.glob(f"{ROOT}/runs/*/files.jsonl.gz"):
    if p.split("/")[-2] not in inc:
        continue
    for l in gzip.open(p, "rt"):
        r = json.loads(l); f = r.get("stat_fail", 0) + r.get("open_fail", 0)
        fail += f
        if r["path"].endswith("/.gitattributes"):
            attr += f
meta = sum(float(r["meta_ops"]) for r in inc.values())
fl = sum(float(r["failed_lookups"]) for r in inc.values())
out = {"attr_failed": attr, "failed_files_sum": fail, "failed_instances_sum": fl, "meta_ops": meta,
       "attr_share_of_failed": attr / fl, "attr_share_of_meta": attr / meta}
json.dump(out, open(f"{ROOT}/results/gitattr_trace.json", "w"), indent=1); print(out)
