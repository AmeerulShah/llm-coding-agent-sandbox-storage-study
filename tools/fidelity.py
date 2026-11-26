#!/usr/bin/env python3
"""Replay-fidelity sensitivity: main findings over all calls, over calls whose exit code matches the
recording, and over tasks whose test calls all match. Writes results/fidelity.csv and fidelity.json."""
import json
import pandas as pd

ROOT = "/home/claude/research/asio"; RES = f"{ROOT}/results"
I = pd.read_csv(f"{RES}/instances.csv")
C = pd.read_csv(f"{RES}/commands.csv", low_memory=False)
C = C[C.instance.isin(set(I.instance))].copy()
S = pd.read_csv(f"{RES}/snapshot_steps.csv")
num = lambda c: C[c].fillna(0) if c in C else 0
C["meta"] = sum(num(k) for k in ("open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents"))
C["fail"] = num("open_fail") + num("stat_fail")
C["data"] = num("read_calls") + num("write_calls")
C["rb"] = sum(num(c) for c in C.columns if c.startswith("read_bytes_") and c != "read_bytes_pseudo")
C["wb"] = sum(num(c) for c in C.columns if c.startswith("write_bytes_"))
C["match"] = C.rc == C.rec_rc
C = C.merge(S[["instance", "step", "block_level"]], on=["instance", "step"], how="left")

tests = C[C.cat == "test"]
clean = set(tests.groupby("instance").match.all().loc[lambda s: s].index) | (set(I.instance) - set(tests.instance))


def calls_findings(D):
    t = D.groupby("instance")[["meta", "data", "fail"]].sum()
    t = t[t.data > 0]
    return {
        "Metadata ops per read/write call, median task": (t.meta / t.data).median(),
        "Metadata ops per read/write call, pooled": D.meta.sum() / D.data.sum(),
        "Failed lookups, % of metadata ops (pooled)": 100 * D.fail.sum() / D.meta.sum(),
        "Test runs, % of tool calls": 100 * (D.cat == "test").mean(),
        "Test runs, % of bytes read": 100 * D[D.cat == "test"].rb.sum() / D.rb.sum(),
        "Test runs, % of bytes written": 100 * D[D.cat == "test"].wb.sum() / D.wb.sum(),
        "Searches, % of bytes read": 100 * D[D.cat == "search"].rb.sum() / D.rb.sum(),
        "Calls that change nothing, %": 100 * (D.block_level.fillna(0) == 0).mean(),
    }


def task_findings(T):
    return {
        "Trace-estimated read footprint, % of image (median task)": 100 * (T.ws_total / T.image_bytes).median(),
        "Writable layer at end, MiB (median task)": T.final_bytes.median() / 2**20,
        "Bytecode, % of writable layer (pooled)": 100 * T.final_pyc_bytes.sum() / T.final_bytes.sum(),
    }


rows = []
a, m, c = calls_findings(C), calls_findings(C[C.match]), calls_findings(C[C.instance.isin(clean)])
for k in a:
    rows.append({"finding": k, "all": a[k], "matching_calls": m[k], "clean_tasks": c[k]})
ta, tc = task_findings(I), task_findings(I[I.instance.isin(clean)])
for k in ta:
    rows.append({"finding": k, "all": ta[k], "matching_calls": None, "clean_tasks": tc[k]})
F = pd.DataFrame(rows); F.to_csv(f"{RES}/fidelity.csv", index=False)
meta = {"n_tasks": len(I), "n_calls": len(C), "n_match_calls": int(C.match.sum()), "n_clean_tasks": len(clean),
        "test_calls": len(tests), "test_mismatch_share": float(1 - tests.match.mean()),
        "max_rel_change_calls": float(((F.matching_calls - F["all"]).abs() / F["all"].abs()).max()),
        "test_call_agreement": float(tests.match.mean()),
        "bytes_read_by_matching_calls": float(C[C.match].rb.sum() / C.rb.sum()),
        "meta_by_matching_calls": float(C[C.match].meta.sum() / C.meta.sum()),
        }
json.dump(meta, open(f"{RES}/fidelity.json", "w"), indent=1)
pd.set_option("display.width", 200); print(F.round(2).to_string(index=False)); print(meta)
