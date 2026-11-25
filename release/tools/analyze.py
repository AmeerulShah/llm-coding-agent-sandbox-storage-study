#!/usr/bin/env python3
"""Aggregate replay outputs into tables, key numbers and figures.

Usage: envs/tool/bin/python tools/analyze.py
Reads runs/<instance>/{summary.json,commands.jsonl,files.jsonl.gz}; writes
results/*.csv, results/key_numbers.json and paper/figs/*.pdf.
"""
import collections, glob, gzip, json, math, os, random, re, statistics, sys
import numpy as np
import pandas as pd

ROOT = "/home/claude/research/asio"
sys.path.insert(0, f"{ROOT}/tools")
from command_stats import split_simple, classify  # noqa: E402

RES = f"{ROOT}/results"; FIG = f"{ROOT}/paper/figs"
os.makedirs(RES, exist_ok=True); os.makedirs(FIG, exist_ok=True)
CLASSES = ["repo", "git", "env", "runtime", "system", "tmp", "home"]
BLOCK = 4096
FID_RC = 0.8  # inclusion: >= 80% of commands reproduce the recorded exit code

STAT_CACHE = {}


def real_size(path, env):
    """Size of a lower-layer (base image) file outside /testbed, by stat-ing the persistent copy."""
    if path.startswith("/testbed/.git"):
        repo_dir = env.split("-")[0]
        for w in (0, 1):
            c = f"/work/w{w}/sbx-{repo_dir}" + path[len("/testbed"):]
            if os.path.isfile(c):
                return os.path.getsize(c)
        return None
    if path.startswith("ENV/"):
        p = f"{ROOT}/envs/{env}" + path[3:]
    elif path.startswith("RUNTIME/"):
        p = None
    else:
        p = path
    key = p or path
    if key in STAT_CACHE:
        return STAT_CACHE[key]
    size = None
    cands = [p] if p else ["/opt/py39" + path[7:], "/usr" + path[7:]]
    for c in cands:
        try:
            if c and os.path.isfile(c):
                size = os.path.getsize(c); break
        except OSError:
            pass
    STAT_CACHE[key] = size
    return size


def cmd_category(cmd):
    """Dominant category of a tool call: the most I/O-relevant simple command it contains."""
    order = ["test", "script", "env", "vcs", "edit", "search", "read", "echo", "other"]
    cats = {classify(s) for s in split_simple(cmd)} or {"other"}
    for c in order:
        if c in cats:
            return c
    return "other"


def load():
    inst_rows, cmd_rows, file_rows = [], [], {}
    for sp in sorted(glob.glob(f"{ROOT}/runs/*__*/summary.json")):
        d = os.path.dirname(sp)
        s = json.load(open(sp))
        cmds = [json.loads(l) for l in open(f"{d}/commands.jsonl")]
        if not cmds or "wfiles" not in cmds[0]:
            continue
        files = [json.loads(l) for l in gzip.open(f"{d}/files.jsonl.gz", "rt")]
        inst_rows.append(s); file_rows[s["instance"]] = files
        for c in cmds:
            c["instance"] = s["instance"]; c["repo"] = s["repo_dir"]; c["cat"] = cmd_category(c["cmd"])
            cmd_rows.append(c)
    return inst_rows, cmd_rows, file_rows


def cs(df, k):
    return float(df[k].sum()) if k in df else 0.0


def pct(xs, q):
    return float(np.percentile(xs, q)) if len(xs) else float("nan")


def main():
    insts, cmds, files = load()
    C = pd.DataFrame(cmds).fillna(0)
    I = pd.DataFrame([{k: v for k, v in s.items() if k not in ("final_writeset", "base")} for s in insts])
    I = I.join(pd.DataFrame([s["base"] for s in insts]))
    keep = set(I[(I.install_rc == 0) & (I.rc_match >= FID_RC)].instance)
    K = {"n_replayed": len(I), "n_included": len(keep),
         "rc_match_median": float(I.rc_match.median()), "sim_mean_median": float(I.sim_mean.median()),
         "rc_match_p10": pct(I.rc_match, 10)}
    I = I[I.instance.isin(keep)].copy(); C = C[C.instance.isin(keep)].copy()
    K["n_commands"] = int(len(C)); K["repos"] = I.repo_dir.value_counts().to_dict()
    K["timeouts"] = int(C.timed_out.sum())

    # ---- per-instance metrics ----
    rows = []
    for s in insts:
        if s["instance"] not in keep:
            continue
        inst = s["instance"]; env = s["env"]
        F = files[inst]
        c = C[C.instance == inst]
        r = {"instance": inst, "repo": s["repo_dir"], "steps": s["n_steps"]}
        for cl in CLASSES:
            r[f"rb_{cl}"] = cs(c, f"read_bytes_{cl}")
            r[f"wb_{cl}"] = cs(c, f"write_bytes_{cl}")
        r["rb_total"] = sum(r[f"rb_{cl}"] for cl in CLASSES)
        r["wb_total"] = sum(r[f"wb_{cl}"] for cl in CLASSES)
        r["meta_ops"] = float(sum(cs(c, k) for k in ("open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents")))
        r["fstat_ops"] = cs(c, "fstat")
        r["failed_lookups"] = cs(c, "open_fail") + cs(c, "stat_fail")
        r["data_calls"] = cs(c, "read_calls") + cs(c, "write_calls")
        r["mutations"] = float(sum(cs(c, k) for k in ("mkdir", "rmdir", "unlink", "rename", "link", "chmod", "utime", "truncate")))
        r["fsync"] = cs(c, "fsync")
        r["fsync_repo"] = cs(c, f"fsync_repo") + cs(c, f"fsync_git")
        r["execve"] = cs(c, "execve")
        r["reread_bytes"] = cs(c, "reread_bytes")
        # working set and write set from per-file records
        ws = collections.Counter(); wsf = collections.Counter(); wr_f = collections.Counter(); mapped = collections.Counter()
        copyup_overlay = 0; cow_block = 0; new_bytes = 0; pyc_bytes = 0; pyc_files = 0
        for f in F:
            cl = f["cls"]
            if cl == "pseudo":
                continue
            size = f.get("orig_size") if cl == "repo" else None
            if size is None and cl in ("env", "runtime", "system", "git"):
                size = real_size(f["path"], env)
            rbytes = f.get("read_bytes", 0)
            if rbytes > 0:
                uniq = min(rbytes, size) if size else rbytes
                ws[cl] += uniq; wsf[cl] += 1
            if f.get("mmap_bytes", 0) > 0:
                mapped[cl] += min(f["mmap_bytes"], size) if size else f["mmap_bytes"]
            written = f.get("write_bytes", 0) > 0 or f.get("open_w", 0) > 0 or f.get("truncate", 0) > 0
            if written:
                wr_f[cl] += 1
                lower = (cl == "repo" and f.get("blob")) or (cl in ("env", "runtime", "system") and size is not None and f.get("open_creat", 0) == 0)
                if lower:
                    copyup_overlay += size or 0
                    cow_block += math.ceil(f.get("write_bytes", 0) / BLOCK) * BLOCK
                else:
                    new_bytes += f.get("write_bytes", 0)
                if f["path"].endswith(".pyc"):
                    pyc_bytes += f.get("write_bytes", 0); pyc_files += 1
        for cl in CLASSES:
            r[f"ws_{cl}"] = ws[cl]; r[f"wsf_{cl}"] = wsf[cl]; r[f"wf_{cl}"] = wr_f[cl]
        r["ws_total"] = sum(ws.values()); r["ws_files"] = sum(wsf.values()); r["mapped_total"] = sum(mapped.values())
        for cl in CLASSES:
            r[f"mapped_{cl}"] = mapped[cl]
        r["copyup_overlay"] = copyup_overlay; r["cow_block"] = cow_block; r["new_bytes"] = new_bytes
        r["pyc_bytes"] = pyc_bytes; r["pyc_files"] = pyc_files
        b = s["base"]
        r["image_bytes"] = b["repo_tree_bytes"] + b["git_dir_bytes"] + b["env_bytes"] + b["runtime_bytes"]
        r["repo_tree_bytes"] = b["repo_tree_bytes"]; r["git_dir_bytes"] = b["git_dir_bytes"]; r["env_bytes"] = b["env_bytes"]
        r["full_copy_bytes"] = b["repo_tree_bytes"] + b["git_dir_bytes"] + b["env_bytes"]
        fw = s["final_writeset"]
        r["final_files"] = len(fw); r["final_bytes"] = sum(x["size"] for x in fw)
        r["final_tracked_mod"] = sum(1 for x in fw if x["in_tree"])
        r["final_pyc_bytes"] = sum(x["size"] for x in fw if x["path"].endswith(".pyc") or "__pycache__" in x["path"])
        r["final_src_bytes"] = r["final_bytes"] - r["final_pyc_bytes"]
        # time: LLM step gaps from recorded response timestamps
        ts = [x for x in c.created.tolist() if x]
        gaps = [b2 - a2 for a2, b2 in zip(ts, ts[1:]) if b2 >= a2]
        r["step_gap_median_s"] = statistics.median(gaps) if gaps else float("nan")
        r["task_wall_s"] = (ts[-1] - ts[0]) if len(ts) > 1 else float("nan")
        rows.append(r)
    T = pd.DataFrame(rows)
    T.to_csv(f"{RES}/instances.csv", index=False)
    C.drop(columns=["wfiles"]).to_csv(f"{RES}/commands.csv", index=False)

    MiB = 2 ** 20
    def q(col, scale=1):
        x = T[col] / scale
        return {"p50": round(float(x.median()), 3), "p90": round(pct(x, 90), 3), "mean": round(float(x.mean()), 3), "max": round(float(x.max()), 3)}
    K["per_task"] = {
        "steps": q("steps"), "read_MiB": q("rb_total", MiB), "write_MiB": q("wb_total", MiB),
        "meta_ops": q("meta_ops"), "failed_lookups": q("failed_lookups"), "execve": q("execve"),
        "ws_MiB": q("ws_total", MiB), "ws_files": q("ws_files"), "final_MiB": q("final_bytes", MiB),
        "final_src_MiB": q("final_src_bytes", MiB), "copyup_overlay_MiB": q("copyup_overlay", MiB),
        "cow_block_MiB": q("cow_block", MiB), "new_MiB": q("new_bytes", MiB), "image_MiB": q("image_bytes", MiB),
        "full_copy_MiB": q("full_copy_bytes", MiB), "fsync": q("fsync"), "mutations": q("mutations"),
        "step_gap_s": q("step_gap_median_s"), "task_wall_s": q("task_wall_s"),
    }
    K["shares"] = {
        "read_by_class": {cl: round(float(T[f"rb_{cl}"].sum() / T.rb_total.sum()), 4) for cl in CLASSES},
        "write_by_class": {cl: round(float(T[f"wb_{cl}"].sum() / max(1, T.wb_total.sum())), 4) for cl in CLASSES},
        "ws_by_class": {cl: round(float(T[f"ws_{cl}"].sum() / T.ws_total.sum()), 4) for cl in CLASSES},
        "meta_to_data_ops": round(float(T.meta_ops.sum() / T.data_calls.sum()), 3),
        "failed_lookup_share_of_meta": round(float(T.failed_lookups.sum() / T.meta_ops.sum()), 4),
        "ws_fraction_of_image_median": round(float((T.ws_total / T.image_bytes).median()), 4),
        "ws_fraction_of_image_p90": round(pct(T.ws_total / T.image_bytes, 90), 4),
        "tasks_with_any_fsync": round(float((T.fsync > 0).mean()), 4),
        "tasks_with_repo_fsync": round(float((T.fsync_repo > 0).mean()), 4),
        "pyc_share_of_final_bytes": round(float(T.final_pyc_bytes.sum() / max(1, T.final_bytes.sum())), 4),
        "reread_share_of_read_bytes": round(float(T.reread_bytes.sum() / T.rb_total.sum()), 4),
        "copyup_vs_block": round(float(T.copyup_overlay.sum() / max(1, T.cow_block.sum())), 2),
        "full_copy_vs_final": round(float(T.full_copy_bytes.sum() / max(1, T.final_bytes.sum())), 1),
    }
    # ---- command-category breakdown ----
    for cl in CLASSES:
        if f"read_bytes_{cl}" not in C:
            C[f"read_bytes_{cl}"] = 0
        if f"write_bytes_{cl}" not in C:
            C[f"write_bytes_{cl}"] = 0
    C["rb"] = sum(C[f"read_bytes_{cl}"] for cl in CLASSES)
    C["wb"] = sum(C[f"write_bytes_{cl}"] for cl in CLASSES)
    for k in ("open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents", "fstat", "execve"):
        if k not in C:
            C[k] = 0
    C["meta"] = sum(C[k] for k in ("open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents"))
    G = C.groupby("cat").agg(n=("cmd", "size"), rb=("rb", "sum"), wb=("wb", "sum"), meta=("meta", "sum"),
                             fail=("stat_fail", "sum"), execve=("execve", "sum"))
    G["share_cmds"] = G.n / G.n.sum(); G["share_rb"] = G.rb / G.rb.sum(); G["share_wb"] = G.wb / max(1, G.wb.sum())
    G["share_meta"] = G.meta / G.meta.sum()
    G.sort_values("share_rb", ascending=False).to_csv(f"{RES}/by_category.csv")
    K["by_category"] = {k: {"share_cmds": round(v.share_cmds, 4), "share_read": round(v.share_rb, 4),
                            "share_write": round(v.share_wb, 4), "share_meta": round(v.share_meta, 4)}
                        for k, v in G.iterrows()}
    # ---- snapshot-per-step model ----
    snap = []
    for inst, c in C.groupby("instance"):
        tree_sizes = {f["path"]: f.get("orig_size") for f in files[inst] if f["cls"] == "repo"}
        for _, r in c.iterrows():
            wf = r["wfiles"] if isinstance(r["wfiles"], list) else []
            persist = [x for x in wf if x[1] in ("repo", "git", "tmp", "home", "env")]
            file_level = sum((tree_sizes.get(p) or 0) if tree_sizes.get(p) else b for p, cl, b in persist)
            block_level = sum(math.ceil(b / BLOCK) * BLOCK for _, _, b in persist)
            snap.append({"instance": inst, "step": r["step"], "files": len(persist), "file_level": file_level, "block_level": block_level})
    S = pd.DataFrame(snap); S.to_csv(f"{RES}/snapshot_steps.csv", index=False)
    K["snapshot"] = {"steps_with_no_writes": round(float((S.files == 0).mean()), 4),
                     "block_delta_KiB_p50": round(pct(S.block_level, 50) / 1024, 2),
                     "block_delta_KiB_p90": round(pct(S.block_level, 90) / 1024, 2),
                     "block_delta_KiB_p99": round(pct(S.block_level, 99) / 1024, 2),
                     "file_delta_KiB_p90": round(pct(S.file_level, 90) / 1024, 2)}
    # ---- fleet sharing model: page-cache demand of N concurrent sandboxes ----
    keyed = {}
    for inst in T.instance:
        env = I.set_index("instance").loc[inst, "env"]
        ks = {}
        for f in files[inst]:
            if f["cls"] == "pseudo" or f.get("read_bytes", 0) == 0:
                continue
            cl = f["cls"]
            if cl == "repo":
                if not f.get("blob"):
                    continue
                k = ("blob", f["blob"]); size = f.get("orig_size") or 0
            elif cl == "env":
                k = ("env", env, f["path"]); size = real_size(f["path"], env) or f.get("read_bytes", 0)
            elif cl in ("runtime", "system"):
                k = ("sys", f["path"]); size = real_size(f["path"], env) or f.get("read_bytes", 0)
            elif cl == "git":
                # pack files and loose objects are immutable and identical across clones of a repository;
                # the index and refs are per-sandbox state
                shared_obj = "/objects/" in f["path"]
                k = ("git", env.split("-")[0], f["path"]) if shared_obj else ("gitpriv", inst, f["path"])
                size = real_size(f["path"], env) or f.get("read_bytes", 0)
            else:
                continue
            ks[k] = min(size, f.get("read_bytes", 0)) or size
        keyed[inst] = ks
    rng = random.Random(7); fleet = []
    insts_l = list(keyed)
    for n in (1, 2, 4, 8, 16, 32, 64, 128):
        for rep in range(20 if n < 128 else 5):
            sample = rng.sample(insts_l, min(n, len(insts_l)))
            private = sum(sum(keyed[i].values()) for i in sample)
            union = {}
            for i in sample:
                union.update(keyed[i])
            fleet.append({"n": n, "rep": rep, "private": private, "shared": sum(union.values())})
    Fl = pd.DataFrame(fleet).groupby("n").mean().reset_index()
    Fl["saving"] = 1 - Fl.shared / Fl.private
    Fl.to_csv(f"{RES}/fleet_sharing.csv", index=False)
    K["fleet"] = {int(r.n): {"private_MiB": round(r.private / MiB, 1), "shared_MiB": round(r.shared / MiB, 1), "saving": round(r.saving, 3)} for r in Fl.itertuples()}
    # same-repo fleet (all-Django): the case of many agents working on one codebase
    dj = [i for i in insts_l if i.startswith("django__")]
    fleet2 = []
    for n in (1, 2, 4, 8, 16, 32, 64, 128):
        for rep in range(20 if n < 128 else 5):
            sample = rng.sample(dj, min(n, len(dj)))
            private = sum(sum(keyed[i].values()) for i in sample)
            union = {}
            for i in sample:
                union.update(keyed[i])
            fleet2.append({"n": n, "rep": rep, "private": private, "shared": sum(union.values())})
    Fl2 = pd.DataFrame(fleet2).groupby("n").mean().reset_index(); Fl2["saving"] = 1 - Fl2.shared / Fl2.private
    Fl2.to_csv(f"{RES}/fleet_sharing_django.csv", index=False)
    K["fleet_django"] = {int(r.n): {"private_MiB": round(r.private / MiB, 1), "shared_MiB": round(r.shared / MiB, 1), "saving": round(r.saving, 3)} for r in Fl2.itertuples()}

    # ---- working-set growth over the trajectory ----
    grow = []
    for inst in T.instance:
        n = int(T.set_index("instance").loc[inst, "steps"])
        byfirst = collections.Counter()
        tot = 0
        for f in files[inst]:
            if f["cls"] in ("pseudo",) or "first_read_step" not in f:
                continue
            b = f.get("read_bytes", 0)
            byfirst[f["first_read_step"]] += b; tot += b
        if tot == 0 or n < 2:
            continue
        acc = 0
        for st in range(n):
            acc += byfirst.get(st, 0)
            grow.append({"instance": inst, "frac_steps": (st + 1) / n, "frac_ws": acc / tot})
    Gr = pd.DataFrame(grow); Gr.to_csv(f"{RES}/ws_growth.csv", index=False)
    Gr["bin"] = (Gr.frac_steps * 10).clip(upper=9.999).astype(int)
    gb = Gr.groupby("bin").frac_ws.median()
    K["ws_growth_median_at"] = {f"{(b+1)*10}%": round(float(v), 3) for b, v in gb.items()}

    # ---- storage latency budget per step ----
    Cm = C.copy()
    Cm["meta_rtt_ops"] = Cm[["open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents"]].sum(axis=1)
    per_task = Cm.groupby("instance").meta_rtt_ops.sum()
    distinct = {inst: sum(1 for f in files[inst] if f["cls"] not in ("pseudo",) and (f.get("stat", 0) + f.get("stat_fail", 0) + f.get("open_r", 0) + f.get("open_w", 0) + f.get("open_fail", 0) + f.get("getdents", 0)) > 0) for inst in T.instance}
    lat = []
    for inst in T.instance:
        row = T.set_index("instance").loc[inst]
        for rtt_us in (10, 50, 100, 250, 500, 1000, 2000):
            lat.append({"instance": inst, "rtt_us": rtt_us, "steps": row.steps, "wall_s": row.task_wall_s,
                        "nocache_s": per_task[inst] * rtt_us / 1e6, "cache_s": distinct[inst] * rtt_us / 1e6})
    L = pd.DataFrame(lat); L["nocache_frac"] = L.nocache_s / L.wall_s; L["cache_frac"] = L.cache_s / L.wall_s
    L.to_csv(f"{RES}/latency_model.csv", index=False)
    K["latency"] = {int(r): {"nocache_s_p50": round(float(g.nocache_s.median()), 2), "cache_s_p50": round(float(g.cache_s.median()), 2),
                             "nocache_frac_p50": round(float(g.nocache_frac.median()), 3), "cache_frac_p50": round(float(g.cache_frac.median()), 3)}
                    for r, g in L.groupby("rtt_us")}
    K["meta_ops_per_step_p50"] = round(float((per_task / T.set_index("instance").steps).median()), 1)
    K["distinct_paths_per_task_p50"] = float(np.median(list(distinct.values())))
    json.dump(K, open(f"{RES}/key_numbers.json", "w"), indent=1)
    print(json.dumps(K, indent=1)[:6000])


if __name__ == "__main__":
    main()
