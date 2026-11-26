#!/usr/bin/env python3
"""Extra analyses + LaTeX macros (paper/numbers.tex) and tables (paper/tables/*.tex).

Run after tools/analyze.py. Every number quoted in the paper comes from here.
"""
import collections, glob, gzip, json, os, re, statistics, sys
import numpy as np
import pandas as pd

ROOT = "/home/claude/research/asio"; RES = f"{ROOT}/results"; PAPER = f"{ROOT}/paper"
sys.path.insert(0, f"{ROOT}/tools")
from command_stats import split_simple, classify, commands as traj_commands  # noqa: E402
os.makedirs(f"{PAPER}/tables", exist_ok=True)
K = json.load(open(f"{RES}/key_numbers.json"))
T = pd.read_csv(f"{RES}/instances.csv")
C = pd.read_csv(f"{RES}/commands.csv", low_memory=False)
MiB = 2 ** 20
M = {}


def f0(x):
    return f"{x:,.0f}"


def f1(x):
    return f"{x:,.1f}"


def pc(x, d=0):
    return f"{100 * x:.{d}f}"


# ---------------- dataset / fidelity ----------------
inst_all = json.load(open(f"{ROOT}/data/instances.json"))
meta = json.load(open(f"{ROOT}/data/meta_v242.json"))
summ = {}
for sp in glob.glob(f"{ROOT}/runs/*__*/summary.json"):
    s = json.load(open(sp)); summ[s["instance"]] = s
inc = set(T.instance)
M["NTraj"] = str(len(meta)); M["NReplay"] = str(len(summ)); M["NInc"] = str(len(inc))
M["NReplayShare"] = pc(len(summ) / len(meta)); M["NIncShare"] = pc(len(inc) / max(1, len(summ)))
M["NCmds"] = f0(K["n_commands"]); M["NTimeouts"] = str(K["timeouts"])
rcs = [summ[i]["rc_match"] for i in inc]; sims = [summ[i]["sim_mean"] for i in inc]
M["RcMatch"] = pc(statistics.median(rcs)); M["SimMed"] = f"{statistics.median(sims):.2f}"
names = {"django": "Django", "sympy": "SymPy", "sphinx": "Sphinx", "pytest": "pytest", "requests": "Requests"}
rows = []
for rd, nm in names.items():
    rep = [s for s in summ.values() if s["repo_dir"] == rd]
    ii = [s for s in rep if s["instance"] in inc]
    if not rep:
        continue
    Tr = T[T.repo == rd]
    rows.append(f"{nm} & {len(rep)} & {len(ii)} & {statistics.median([s['n_steps'] for s in ii]) if ii else 0:.0f} & "
                f"{pc(statistics.median([s['rc_match'] for s in ii])) if ii else '--'} & {Tr.rb_total.median()/MiB:.0f} & {Tr.meta_ops.median()/1000:.0f} \\\\")
tot_line = (f"\\midrule All & {len(summ)} & {len(inc)} & {statistics.median([summ[i]['n_steps'] for i in inc]):.0f} & {M['RcMatch']} & {T.rb_total.median()/MiB:.0f} & {T.meta_ops.median()/1000:.0f} \\\\")
open(f"{PAPER}/tables/dataset.tex", "w").write(
    "\\begin{tabular}{lrrrrrr}\n\\toprule\n & & & Calls & Agreement & Read & Metadata ops \\\\\nRepository & Replayed & Included & per task & (\\%) & (MiB) & (thousands) \\\\\n\\midrule\n"
    + "\n".join(rows) + "\n" + tot_line + "\n\\bottomrule\n\\end{tabular}\n")
spec_sub = sum(1 for i in inc if inst_all[i]["spec_python"] not in ("3.9", "3.11"))
M["NPySub"] = str(spec_sub)

# ---------------- per-task table ----------------
pt = K["per_task"]
def row(label, key, scale_fmt=f1):
    d = pt[key]
    return f"{label} & {scale_fmt(d['p50'])} & {scale_fmt(d['p90'])} & {scale_fmt(d['max'])} \\\\"
lines = [row("Tool calls", "steps", f0), row("Processes started", "execve", f0), row("Bytes read (MiB)", "read_MiB"),
         row("Bytes written (MiB)", "write_MiB"), row("Metadata operations (thousands)", "meta_ops", lambda x: f1(x / 1000)),
         row("Failed lookups (thousands)", "failed_lookups", lambda x: f1(x / 1000)), row("Read footprint, trace estimate (MiB)", "ws_MiB"),
         row("Files read (trace estimate)", "ws_files", f0), row("Writable layer at end (MiB)", "final_MiB", f1),
         row("Namespace mutations", "mutations", f0), row("\\texttt{fsync}-family calls", "fsync", f0)]
open(f"{PAPER}/tables/pertask.tex", "w").write(
    "\\begin{tabular}{lrrr}\n\\toprule\nPer task & Median & P90 & Max \\\\\n\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

M["StepsMed"] = f0(pt["steps"]["p50"]); M["ExecveMed"] = f0(pt["execve"]["p50"])
M["ReadMed"] = f0(pt["read_MiB"]["p50"]) if pt["read_MiB"]["p50"] >= 10 else f1(pt["read_MiB"]["p50"])
M["ReadPninety"] = f0(pt["read_MiB"]["p90"]); M["WriteMed"] = f1(pt["write_MiB"]["p50"])
M["MetaMed"] = f0(pt["meta_ops"]["p50"]); M["MetaPerData"] = f1(K["shares"]["meta_to_data_ops"])
M["FailShare"] = pc(K["shares"]["failed_lookup_share_of_meta"])
M["WsMed"] = f0(pt["ws_MiB"]["p50"]); M["WsFilesMed"] = f0(pt["ws_files"]["p50"]); M["ImageMed"] = f0(pt["image_MiB"]["p50"])
M["WsFracMed"] = pc(float((T.ws_total / T.image_bytes).median()), 1); M["WsFracPninety"] = pc(float(np.percentile(T.ws_total / T.image_bytes, 90)), 0)
M["FinalMed"] = f"{pt['final_MiB']['p50']:.1f}"; M["PycShare"] = pc(K["shares"]["pyc_share_of_final_bytes"])
M["FinalSrcMed"] = f1(float((T.final_src_bytes / 1024).median()))
M["FinalFilesMed"] = f0(float(T.final_files.median())); M["TrackedModMed"] = f0(float(T.final_tracked_mod.median()))
M["MutMed"] = f0(pt["mutations"]["p50"])
M["FullCopyMed"] = f0(pt["full_copy_MiB"]["p50"]); M["FullVsFinal"] = f0(float((T.full_copy_bytes / T.final_bytes.clip(lower=1)).median()))
M["CopyupMed"] = f0(float((T.copyup_overlay / 1024).median())); M["CowBlockMed"] = f0(float((T.cow_block / 1024).median()))
M["NewMed"] = f1(float((T.new_bytes / MiB).median()))
M["RereadShare"] = pc(K["shares"]["reread_share_of_read_bytes"])
M["GrowThirty"] = pc(K["ws_growth_median_at"]["30%"]); M["GrowFifty"] = pc(K["ws_growth_median_at"]["50%"])
nf = int((T.fsync > 0).sum())
M["FsyncTasks"] = pc((T.fsync > 0).mean())
ncalls = int(T.fsync.sum())
M["FsyncCalls"] = str(ncalls); M["FsyncTaskCount"] = str(nf)
M["FsyncTasksText"] = ("not one of the " + M["NInc"] + " tasks issues \\texttt{fsync}, \\texttt{fdatasync} or \\texttt{sync}") if nf == 0 else \
    (f"across all {M['NInc']} tasks there {'is' if ncalls == 1 else 'are'} {ncalls} \\texttt{{fsync}}-family call{'s' if ncalls != 1 else ''}, in {nf} task{'s' if nf != 1 else ''}")
sh = K["shares"]
for cl, nm in (("repo", "Repo"), ("git", "Git"), ("env", "Env"), ("runtime", "Runtime"), ("tmp", "Tmp")):
    M[f"Read{nm}"] = pc(sh["read_by_class"][cl]); M[f"Write{nm}"] = pc(sh["write_by_class"][cl])
cat = K["by_category"]
for c, nm in (("test", "Test"), ("search", "Search"), ("read", "Read"), ("vcs", "Vcs"), ("edit", "Edit"), ("script", "Script")):
    d = cat.get(c, {"share_cmds": 0, "share_read": 0, "share_write": 0, "share_meta": 0})
    M[f"{nm}ShareCmds"] = pc(d["share_cmds"]); M[f"{nm}ShareRead"] = pc(d["share_read"], 1 if d["share_read"] < 0.01 else 0)
    M[f"{nm}ShareWrite"] = pc(d["share_write"]); M[f"{nm}ShareMeta"] = pc(d["share_meta"])
sn = K["snapshot"]
M["SnapZero"] = pc(sn["steps_with_no_writes"]); M["SnapPninety"] = f0(sn["block_delta_KiB_p90"]); M["SnapPnn"] = f0(sn["block_delta_KiB_p99"])
M["StepGapMed"] = f1(pt["step_gap_s"]["p50"]); M["TaskWallMed"] = f0(pt["task_wall_s"]["p50"])
lat = K["latency"]
M["LatFiveNoCacheFrac"] = pc(lat["500"]["nocache_frac_p50"]); M["LatFiveCacheFrac"] = pc(lat["500"]["cache_frac_p50"], 1)
M["LatHundredNoCacheFrac"] = pc(lat["100"]["nocache_frac_p50"]); M["LatFiveNoCache"] = f0(lat["500"]["nocache_s_p50"])
M["MetaPerStep"] = f0(K["meta_ops_per_step_p50"]); M["DistinctPaths"] = f0(K["distinct_paths_per_task_p50"])
fm, fd = K["fleet"]["32"], K["fleet_django"]["32"]
M["FleetPrivate"] = f1(fm["private_MiB"] / 1024); M["FleetMixedShared"] = f1(fm["shared_MiB"] / 1024)
M["FleetMixedSaving"] = pc(fm["saving"]); M["FleetRepoShared"] = f1(fd["shared_MiB"] / 1024); M["FleetRepoSaving"] = pc(fd["saving"])
M["FleetRepoPrivate"] = f1(fd["private_MiB"] / 1024)

# ---------------- failed lookups, write and mutation composition ----------------
def fail_kind(p, cls):
    b = os.path.basename(p)
    if b in (".gitattributes", ".gitignore") or "/.git/" in p:
        return "git"
    if "/locale/" in p or b.endswith(".mo") or "LC_MESSAGES" in p:
        return "locale"
    if (re.search(r"(\.py|\.pyc|\.so|\.pth|\.egg-link|\.egg-info|\.dist-info|entry_points\.txt|namespace_packages\.txt|pyvenv\.cfg|python3\d\.zip|pybuilddir\.txt|Setup\.local)$", p)
            or "__pycache__" in p or "<frozen" in p or cls in ("env", "runtime")):
        return "python"
    if re.search(r"^(/usr/local/sbin|/usr/local/bin|/usr/sbin|/usr/bin|/sbin|/bin)/[^/]+$", p) or p.startswith("ENV/bin/"):
        return "path"
    return "other"
fail_kinds = collections.Counter()
fail_tot = 0; fail_py = 0; fail_by_cls = collections.Counter()
wtop = {"tmp": collections.Counter(), "git": collections.Counter(), "repo": collections.Counter()}
mut = collections.Counter()
for i in inc:
    for line in gzip.open(f"{ROOT}/runs/{i}/files.jsonl.gz", "rt"):
        f = json.loads(line)
        nfail = f.get("stat_fail", 0) + f.get("open_fail", 0)
        if nfail:
            fail_tot += nfail; fail_by_cls[f["cls"]] += nfail
            fail_kinds[fail_kind(f["path"], f["cls"])] += nfail
        if f["cls"] in wtop and f.get("write_bytes", 0):
            p = f["path"]
            key = ("__pycache__/*.pyc" if p.endswith(".pyc") else
                   re.sub(r"/tmp/[^/]+", "/tmp/<dir>", p) if f["cls"] == "tmp" else
                   ".git/" + p.split("/.git/")[-1] if f["cls"] == "git" else "source/other")
            if f["cls"] == "git":
                key = ".git/index*" if "index" in p else ".git/" + p.split("/.git/")[-1].split("/")[0]
            if f["cls"] == "tmp":
                key = "/tmp/*.sqlite3" if "sqlite" in p else "/tmp/<other>"
            wtop[f["cls"]][key] += f["write_bytes"]
        for kind in ("unlink", "rename", "mkdir", "rmdir", "link", "chmod", "utime", "truncate"):
            if f.get(kind, 0):
                grp = "pyc" if (".pyc" in f["path"] or "__pycache__" in f["path"]) else ("git" if "/.git" in f["path"] else f["cls"])
                mut[(kind, grp)] += f[kind]
M["MetaShareOps"] = pc(float(T.meta_ops.sum() / (T.meta_ops.sum() + T.data_calls.sum())))
M["GitDiffMed"] = f0(float(C[C.cmd.astype(str).str.contains(r"git (?:status|diff)", regex=True)].groupby("instance").size().median()))
M["FailGitShare"] = pc(fail_kinds["git"] / max(1, fail_tot)); M["FailPyShare"] = pc(fail_kinds["python"] / max(1, fail_tot))
M["FailLocaleShare"] = pc(fail_kinds["locale"] / max(1, fail_tot)); M["FailPathShare"] = pc(fail_kinds["path"] / max(1, fail_tot), 1)
fc = C.copy(); fc["fail"] = fc.get("stat_fail", 0).fillna(0) + fc.get("open_fail", 0).fillna(0)
fg = fc.groupby("cat").fail.sum(); M["FailVcsCmdShare"] = pc(float(fg.get("vcs", 0) / fg.sum())); M["FailTestCmdShare"] = pc(float(fg.get("test", 0) / fg.sum()))
mut_tot = sum(mut.values()); mut_pyc = sum(v for (k, g), v in mut.items() if g == "pyc"); mut_git = sum(v for (k, g), v in mut.items() if g == "git")
extra = {"fail_by_cls": dict(fail_by_cls), "fail_kinds": dict(fail_kinds),
         "write_top": {k: v.most_common(6) for k, v in wtop.items()}, "mut_by_kind_group": {f"{k}|{g}": v for (k, g), v in mut.most_common(20)},
         "mut_pyc_share": mut_pyc / max(1, mut_tot), "mut_git_share": mut_git / max(1, mut_tot)}
M["MutPycShare"] = pc(extra["mut_pyc_share"]); M["MutGitShare"] = pc(extra["mut_git_share"])
mt = sum(v for (k, g), v in mut.items() if g == "tmp"); M["MutTmpShare"] = pc(mt / max(1, mut_tot))
rp = 0; rt = 0
for i in inc:
    for line in gzip.open(f"{ROOT}/runs/{i}/files.jsonl.gz", "rt"):
        f = json.loads(line)
        if f["cls"] == "repo" and f.get("write_bytes", 0):
            rt += f["write_bytes"]
            if ".pyc" in f["path"] or "__pycache__" in f["path"]:
                rp += f["write_bytes"]
M["RepoWritePyc"] = pc(rp / max(1, rt))

# tail tasks: what drives the top-decile readers
C["rb"] = C[[c for c in C.columns if c.startswith("read_bytes_") and c != "read_bytes_pseudo"]].sum(axis=1)
C["cat"] = C["cat"].astype(str)
top = T[T.rb_total >= T.rb_total.quantile(0.9)].instance
ct = C[C.instance.isin(top)].groupby("cat").rb.sum()
extra["top_decile_read_share_by_cat"] = (ct / ct.sum()).round(3).to_dict()
M["TailTestSearchShare"] = pc(float((ct.get("test", 0) + ct.get("search", 0)) / ct.sum()))

# first test run vs working-set growth
fr = []
for i in inc:
    ci = C[C.instance == i].sort_values("step")
    tests = ci[ci.cat == "test"].step
    if len(tests) == 0:
        continue
    t0 = int(tests.min()); n = len(ci)
    tot = 0; upto = 0
    for line in gzip.open(f"{ROOT}/runs/{i}/files.jsonl.gz", "rt"):
        f = json.loads(line)
        if "first_read_step" in f and f["cls"] != "pseudo":
            tot += f.get("read_bytes", 0)
            if f["first_read_step"] <= t0:
                upto += f.get("read_bytes", 0)
    if tot:
        fr.append({"first_test_frac": (t0 + 1) / n, "ws_by_first_test": upto / tot})
FR = pd.DataFrame(fr)
extra["first_test"] = {"tasks_with_tests": len(FR), "first_test_pos_med": float(FR.first_test_frac.median()),
                       "ws_by_first_test_med": float(FR.ws_by_first_test.median())}
M["FirstTestPos"] = pc(float(FR.first_test_frac.median())); M["WsByFirstTest"] = pc(float(FR.ws_by_first_test.median()))

# ---------------- review-round fixes: medians, attribution, substitution, resolution ----------------
T["fail_frac"] = T.failed_lookups / T.meta_ops.clip(lower=1); T["meta_per_data"] = T.meta_ops / T.data_calls.clip(lower=1)
M["FailShareMedTask"] = pc(float(T.fail_frac.median()), 1); M["MetaPerDataMedTask"] = f1(float(T.meta_per_data.median()))
topd = T.sort_values("failed_lookups", ascending=False).head(max(1, len(T) // 10))
M["FailTopDecileShare"] = pc(float(topd.failed_lookups.sum() / T.failed_lookups.sum()))
if "read_bytes_git" in C:
    gs = C.groupby("cat").read_bytes_git.sum(); M["GitReadFromSearch"] = pc(float(gs.get("search", 0) / max(1, gs.sum())), 1)
M["WsGitShare"] = pc(K["shares"]["ws_by_class"]["git"])
M["MappedMed"] = f0(float(T.mapped_total.median() / MiB)) if "mapped_total" in T else "??"
sub = [i for i in inc if inst_all[i]["spec_python"] not in ("3.9", "3.11")]
M["NPySub"] = str(len(sub)); M["NPySubShare"] = pc(len(sub) / len(inc))
M["RcSubMed"] = pc(statistics.median([summ[i]["rc_match"] for i in sub])) if sub else "--"
nat = [i for i in inc if i not in set(sub)]; M["RcNativeMed"] = pc(statistics.median([summ[i]["rc_match"] for i in nat]))
nres = 0
for i in inc:
    rp = f"{ROOT}/data/20260901_mini-v2.4.2_gemini-3-5-flash/logs/{i}/report.json"
    if os.path.exists(rp):
        r = json.load(open(rp)); nres += int(bool(list(r.values())[0].get("resolved")))
M["NResolved"] = str(nres)
M["NInstallFail"] = str(sum(1 for s in summ.values() if s["install_rc"] != 0))
M["EnvWriteTasks"] = str(int((T.wb_env > 0).sum()))

# ---------------- fidelity: where exit codes disagree ----------------
Ck = C[(C.rec_rc.astype(str) != "nan") & (C.timed_out.astype(str) != "True")].copy()
Ck = Ck[Ck.rec_rc.notna()]
Ck["mis"] = Ck.rc.astype(float) != Ck.rec_rc.astype(float)
mis = Ck[Ck.mis].groupby("cat").size(); allc_ = Ck.groupby("cat").size()
extra["mismatch_by_cat"] = (mis / mis.sum()).round(3).to_dict(); extra["mismatch_rate_by_cat"] = (mis / allc_).round(4).fillna(0).to_dict()
M["MisTestShare"] = pc(float(mis.get("test", 0) / mis.sum())); M["MisScriptShare"] = pc(float(mis.get("script", 0) / mis.sum()))
fs_cats = [c for c in ("read", "search", "vcs") if c in allc_.index]
M["FsCatAgree"] = pc(1 - float(mis.reindex(fs_cats).fillna(0).sum() / allc_.reindex(fs_cats).sum()), 1)
M["CallAgree"] = pc(1 - float(mis.sum() / allc_.sum()), 1)

# ---------------- static generality (both runs, no replay) ----------------
def static(run):
    rows = []
    for p in sorted(glob.glob(f"{ROOT}/data/{run}/trajs/*.traj.json")):
        tr = json.load(open(p)); cnt = collections.Counter()
        for c in traj_commands(tr):
            for s in split_simple(c):
                cnt[classify(s)] += 1
        rows.append(cnt)
    tot = collections.Counter()
    for r in rows:
        tot.update(r)
    allc = sum(tot.values())
    return {"n": len(rows), "fs_share": (tot["read"] + tot["search"] + tot["edit"]) / allc,
            "test_tasks": sum(1 for r in rows if r["test"]) / len(rows), "shares": {k: v / allc for k, v in tot.items()}}
sa = static("20260901_mini-v2.4.2_gemini-3-5-flash"); sb = static("20260902_mini-v2.4.6_gemini-3-5-flash")
extra["static"] = {"v242": sa, "v246": sb}
M["StaticNa"] = str(sa["n"]); M["StaticNb"] = str(sb["n"]); M["StaticFsA"] = pc(sa["fs_share"]); M["StaticFsB"] = pc(sb["fs_share"])
M["StaticTestA"] = pc(sa["test_tasks"]); M["StaticTestB"] = pc(sb["test_tasks"])
nk = 0; nt = 0
for run in ("20260901_mini-v2.4.2_gemini-3-5-flash", "20260902_mini-v2.4.6_gemini-3-5-flash"):
    for p in glob.glob(f"{ROOT}/data/{run}/trajs/*.traj.json"):
        nt += 1
        if any(re.search(r"\b(killall|pkill)\b|\bkill\s+(-9|-KILL|%|\$)", c) for c in traj_commands(json.load(open(p)))):
            nk += 1
M["KillTraj"] = str(nk); M["KillShare"] = pc(nk / nt, 1); M["StaticNall"] = str(nt)

# ---------------- untraced timing ----------------
ut = []
for sp in glob.glob(f"{ROOT}/runs_untraced/*__*/summary.json"):
    s = json.load(open(sp))
    if s["instance"] not in inc:
        continue
    rows_u = [json.loads(l) for l in open(os.path.dirname(sp) + "/commands.jsonl")]
    tool = sum(r["dur_traced_s"] for r in rows_u)
    wall = float(T.set_index("instance").loc[s["instance"], "task_wall_s"])
    if wall and wall == wall and wall > 0:
        ut.append({"instance": s["instance"], "tool_s": tool, "wall_s": wall, "share": tool / wall})
if ut:
    U = pd.DataFrame(ut); U.to_csv(f"{RES}/untraced_timing.csv", index=False)
    M["ToolShareMed"] = pc(float(U.share.clip(upper=1).median())); M["NUntraced"] = str(len(U))
    extra["untraced"] = {"n": len(U), "tool_s_med": float(U.tool_s.median()), "share_med": float(U.share.median())}
else:
    M["ToolShareMed"] = "??"; M["NUntraced"] = "0"

# ---------------- ablation ----------------
def ab_metrics(d, mode):
    out = []
    for sp in glob.glob(f"{d}/*__*/summary.json"):
        s = json.load(open(sp))
        cm = [json.loads(l) for l in open(os.path.dirname(sp) + "/commands.jsonl")]
        wb = sum(sum(v for k, v in r.items() if k.startswith("write_bytes_") and not k.endswith("pseudo")) for r in cm)
        rb = sum(sum(v for k, v in r.items() if k.startswith("read_bytes_") and not k.endswith("pseudo")) for r in cm)
        meta_ = sum(r.get(k, 0) for r in cm for k in ("open_r", "open_w", "open_fail", "stat", "stat_fail", "getdents"))
        out.append({"instance": s["instance"], "mode": mode, "final_MiB": sum(x["size"] for x in s["final_writeset"]) / MiB,
                    "write_MiB": wb / MiB, "read_MiB": rb / MiB, "meta": meta_, "rc_match": s["rc_match"]})
    return out
ab = []
abl_set = (set(open(f"{ROOT}/data/ablation_subset.txt").read().split()) & inc) if os.path.exists(f"{ROOT}/data/ablation_subset.txt") else set()
if abl_set:
    for mode, d in (("default", f"{ROOT}/runs"), ("no bytecode", f"{ROOT}/runs_nopyc"), ("precompiled", f"{ROOT}/runs_precompiled")):
        ab += [r for r in ab_metrics(d, mode) if r["instance"] in abl_set]
modes_present = {r["mode"] for r in ab}
if ab and modes_present >= {"default", "no bytecode", "precompiled"}:
    A = pd.DataFrame(ab)
    common = set.intersection(*[set(A[A["mode"] == m].instance) for m in A["mode"].unique()])
    A = A[A.instance.isin(common)]
if ab and modes_present >= {"default", "no bytecode", "precompiled"} and len(common) >= 5:
    G = A.groupby("mode")[["final_MiB", "write_MiB", "read_MiB", "meta", "rc_match"]].median().reindex(["default", "no bytecode", "precompiled"])
    G.reset_index().rename(columns={"mode": "variant"}).to_csv(f"{RES}/ablation.csv", index=False)
    M["NAbl"] = str(len(common))
    M["AblDefFinal"] = f"{G.loc['default','final_MiB']:.2f}"; M["AblNoPycFinal"] = f"{G.loc['no bytecode','final_MiB']:.2f}"
    M["AblPreFinal"] = f"{G.loc['precompiled','final_MiB']:.2f}"
    # paired per-task reductions
    P = A.pivot(index="instance", columns="mode")
    red_pre = 1 - (P["final_MiB"]["precompiled"].sum() / P["final_MiB"]["default"].sum())
    red_np_w = 1 - (P["write_MiB"]["no bytecode"].sum() / P["write_MiB"]["default"].sum())
    inc_np_r = P["read_MiB"]["no bytecode"].sum() / P["read_MiB"]["default"].sum() - 1
    inc_pre_r = P["read_MiB"]["precompiled"].sum() / P["read_MiB"]["default"].sum() - 1
    red_pre_w = 1 - (P["write_MiB"]["precompiled"].sum() / P["write_MiB"]["default"].sum())
    M["AblPreReduction"] = pc(red_pre); M["AblNoPycWriteRed"] = pc(red_np_w); M["AblNoPycReadInc"] = pc(inc_np_r)
    M["AblPreReadInc"] = pc(inc_pre_r); M["AblPreWriteRed"] = pc(red_pre_w)
    M["AblRc"] = pc(float(A.rc_match.median()))
    M["AblRcDef"] = pc(float(A[A["mode"] == "default"].rc_match.median())); M["AblRcNoPyc"] = pc(float(A[A["mode"] == "no bytecode"].rc_match.median()))
    M["AblRcPre"] = pc(float(A[A["mode"] == "precompiled"].rc_match.median()))
    extra["ablation"] = {"median": G.round(3).reset_index().to_dict("records"), "paired": {"red_pre_final": red_pre, "red_np_write": red_np_w,
                         "inc_np_read": inc_np_r, "inc_pre_read": inc_pre_r, "red_pre_write": red_pre_w}}
else:
    for k in ("NAbl", "AblDefFinal", "AblNoPycFinal", "AblPreFinal", "AblPreReduction", "AblNoPycWriteRed", "AblNoPycReadInc", "AblRc",
              "AblPreReadInc", "AblPreWriteRed", "AblRcDef", "AblRcNoPyc", "AblRcPre"):
        M[k] = "??"

# ---------------- O1 provisioning (measured) ----------------
pr = f"{ROOT}/results/provisioning_raw.json"
if os.path.exists(pr):
    PR = pd.DataFrame(json.load(open(pr)))
    PRr = PR[PR.strategy != "precompile_image_growth"].groupby(["repo", "strategy"]).agg(sec=("seconds", "median"), nb=("new_bytes", "median"))
    names_s = {"copy": "Full copy (\\texttt{cp -a})", "clone": "\\texttt{git clone} + checkout", "worktree": "\\texttt{git worktree}", "overlay": "overlayfs mount"}
    repos_o = ["django", "sympy", "sphinx", "pytest", "requests"]
    def cell(st, rd):
        sec = PRr.loc[(rd, st), "sec"]; nb = PRr.loc[(rd, st), "nb"]
        ts = f"{sec*1000:.0f}\\,ms" if sec < 1 else f"{sec:.1f}\\,s"
        bs = "0" if nb < 64 * 1024 else (f"{nb/MiB:.0f}" if nb >= 10 * MiB else f"{nb/MiB:.1f}")
        return f"{ts} / {bs}"
    lines = [f"{names_s[st]} & " + " & ".join(cell(st, rd) for rd in repos_o) + " \\\\" for st in ("copy", "clone", "worktree", "overlay")]
    open(f"{PAPER}/tables/provisioning.tex", "w").write(
        "\\begin{tabular}{lrrrrr}\n\\toprule\nStrategy & Django & SymPy & Sphinx & pytest & Requests \\\\\n\\midrule\n" + "\n".join(lines)
        + "\n\\bottomrule\n\\end{tabular}\n")
    dj = lambda st, col: PRr.loc[("django", st), col]
    M["ProvOverlayMs"] = f"{PRr.xs('overlay', level='strategy').sec.max()*1000:.0f}"; M["ProvOverlayKiB"] = f"{dj('overlay','nb')/1024:.0f}"
    M["ProvCopyS"] = f"{dj('copy','sec'):.1f}"; M["ProvCopyMiB"] = f"{dj('copy','nb')/MiB:.0f}"
    M["ProvCloneS"] = f"{dj('clone','sec'):.1f}"; M["ProvCloneMiB"] = f"{dj('clone','nb')/MiB:.0f}"
    M["ProvCloneThousandGiB"] = f"{dj('clone','nb')*1000/2**30:.0f}"
    G = PRr
    per_repo = PR[PR.strategy != "precompile_image_growth"].groupby(["repo", "strategy"]).agg(sec=("seconds", "median"), nb=("new_bytes", "median")).reset_index()
    per_repo.to_csv(f"{RES}/provisioning.csv", index=False)
    growth = PR[PR.strategy == "precompile_image_growth"].set_index("repo").new_bytes
    M["EEImageMiB"] = f"{growth.median()/MiB:.1f}"
    extra["provisioning"] = {"median": {f"{a}|{b}": v for (a, b), v in PRr.sec.round(4).items()}, "image_growth": growth.to_dict()}
else:
    per_repo = None
    for k in ("ProvOverlayMs", "ProvOverlayKiB", "ProvCopyS", "ProvCopyMiB", "ProvCloneS", "ProvCloneMiB", "ProvCloneThousandGiB", "EEImageMiB"):
        M[k] = "??"

# ---------------- O2 on real overlayfs + end-to-end ----------------
def ovl(d):
    out = {}
    for sp in glob.glob(f"{d}/*__*/summary.json"):
        s = json.load(open(sp))
        if s.get("overlay_upper"):
            out[s["instance"]] = s
    return out
OD, OP = ovl(f"{ROOT}/runs_overlay"), ovl(f"{ROOT}/runs_overlay_precompiled")
common_o = sorted(set(OD) & set(OP) & abl_set) if abl_set else []
if common_o:
    upd = np.array([OD[i]["overlay_upper"]["bytes"] for i in common_o]); upp = np.array([OP[i]["overlay_upper"]["bytes"] for i in common_o])
    M["NOvl"] = str(len(common_o))
    M["AblOvlDefFinal"] = f"{np.median(upd)/MiB:.2f}"; M["AblOvlPreFinal"] = f"{np.median(upp)/MiB:.2f}"
    M["AblOvlReduction"] = pc(1 - upp.sum() / upd.sum())
    # validation: overlay upper vs. trace-derived writable layer of the traced default replay
    match = 0; nval = 0
    for i in common_o:
        if i in summ:
            fw = sum(x["size"] for x in summ[i]["final_writeset"]); ub = OD[i]["overlay_upper"]["bytes"]
            nval += 1
            if abs(ub - fw) <= max(0.1 * max(ub, fw), 64 * 1024):
                match += 1
    M["OvlMatchShare"] = pc(match / max(1, nval))
    dif = [OD[i]["overlay_upper"]["bytes"] - sum(x["size"] for x in summ[i]["final_writeset"]) for i in OD if i in summ]
    M["OvlDiffKiB"] = f0(float(np.median(dif)) / 1024)
    M["OvlPycShare"] = pc(sum(OD[i]["overlay_upper"]["pyc_bytes"] for i in OD) / max(1, sum(OD[i]["overlay_upper"]["bytes"] for i in OD)))
    M["AblRcDef"] = pc(float(np.median([OD[i]["rc_match"] for i in common_o]))); M["AblRcPre"] = pc(float(np.median([OP[i]["rc_match"] for i in common_o])))
    pd.DataFrame({"instance": common_o, "upper_default": upd, "upper_precompiled": upp}).to_csv(f"{RES}/ablation_overlay.csv", index=False)
    # end-to-end per task: provisioning (repo median) + writable state at end
    if per_repo is not None:
        pmap = per_repo.set_index(["repo", "strategy"])
        base_b, opt_b, base_s, opt_s = [], [], [], []
        for i in common_o:
            rd = inst_all[i]["repo_dir"]
            base_b.append(pmap.loc[(rd, "clone"), "nb"] + OD[i]["overlay_upper"]["bytes"]); base_s.append(pmap.loc[(rd, "clone"), "sec"])
            opt_b.append(pmap.loc[(rd, "overlay"), "nb"] + OP[i]["overlay_upper"]["bytes"]); opt_s.append(pmap.loc[(rd, "overlay"), "sec"])
        M["EEBaseMiB"] = f"{np.median(base_b)/MiB:.0f}"; M["EEOptMiB"] = f"{np.median(opt_b)/MiB:.2f}"
        M["EEBaseS"] = f"{np.median(base_s):.1f}"; M["EEOptMs"] = f"{np.median(opt_s)*1000:.0f}"
        M["EEReduction"] = pc(1 - np.sum(opt_b) / np.sum(base_b), 1)
        extra["e2e"] = {"base_MiB_med": float(np.median(base_b) / MiB), "opt_MiB_med": float(np.median(opt_b) / MiB)}
else:
    for k in ("NOvl", "AblOvlDefFinal", "AblOvlPreFinal", "AblOvlReduction", "OvlMatchShare", "EEBaseMiB", "EEOptMiB", "EEBaseS", "EEOptMs", "EEReduction"):
        M.setdefault(k, "??")

# ---------------- bytecode timing trade-off (untraced, interleaved) ----------------
def tool_time(d, i):
    p = f"{d}/{i}/commands.jsonl"
    return sum(json.loads(l)["dur_traced_s"] for l in open(p)) if os.path.exists(p) else None
tt = []
for i in sorted(abl_set):
    a, b, c = tool_time(f"{ROOT}/runs_untraced", i), tool_time(f"{ROOT}/runs_untraced_nopyc", i), tool_time(f"{ROOT}/runs_untraced_precompiled", i)
    if a and b and c:
        tt.append({"instance": i, "default_s": a, "nopyc_s": b, "precompiled_s": c})
if tt:
    TT = pd.DataFrame(tt); TT.to_csv(f"{RES}/bytecode_timing.csv", index=False)
    M["NTiming"] = str(len(TT))
    sg = lambda x: ("+" if x >= 0 else "$-$") + f"{abs(100 * x):.0f}"
    M["NoPycTimeInc"] = pc(float((TT.nopyc_s / TT.default_s).median() - 1))
    M["NoPycTimeSigned"] = sg(float((TT.nopyc_s / TT.default_s).median() - 1))
    pre = float((TT.precompiled_s / TT.default_s).median() - 1)
    M["PreTimeChange"] = (pc(pre) + "\\%") if pre >= 0 else (pc(-pre) + "\\% less")
    M["PreTimeChangeSigned"] = sg(pre)
    M["PreTimeAbstract"] = "without slowing tool execution" if pre <= 0.02 else f"at the cost of {pc(pre)}\\% more tool time"
    from scipy.stats import wilcoxon
    M["NoPycSlowerN"] = str(int((TT.nopyc_s > TT.default_s).sum())); M["PreFasterN"] = str(int((TT.precompiled_s < TT.default_s).sum()))
    pmax = max(wilcoxon(TT.nopyc_s, TT.default_s).pvalue, wilcoxon(TT.precompiled_s, TT.default_s).pvalue)
    M["TimingP"] = "$p<0.001$" if pmax < 0.001 else f"$p={pmax:.3f}$"
    M["TimeDefMed"] = f1(float(TT.default_s.median())); M["TimeNoPycMed"] = f1(float(TT.nopyc_s.median())); M["TimePreMed"] = f1(float(TT.precompiled_s.median()))
else:
    for k in ("NoPycSlowerN", "PreFasterN", "TimingP", "NTiming", "NoPycTimeInc", "NoPycTimeSigned", "PreTimeChange", "PreTimeChangeSigned", "TimeDefMed", "TimeNoPycMed", "TimePreMed", "PreTimeAbstract"):
        M[k] = "??"

# ---------------- tracing overhead ----------------
slow = []
for sp in glob.glob(f"{ROOT}/runs_untraced/*__*/summary.json"):
    i = json.load(open(sp))["instance"]
    if i in summ:
        u = sum(json.loads(l)["dur_traced_s"] for l in open(os.path.dirname(sp) + "/commands.jsonl"))
        t = sum(json.loads(l)["dur_traced_s"] for l in open(f"{ROOT}/runs/{i}/commands.jsonl"))
        if u > 0:
            slow.append(t / u)
M["TraceSlowdown"] = f"{np.median(slow):.1f}" if slow else "??"
M["FsyncNone"] = "no task issues \\texttt{fsync}" if nf == 0 else (f"{ncalls} \\texttt{{fsync}}-family call{'s' if ncalls != 1 else ''} occur{'s' if ncalls == 1 else ''} across all {M['NInc']} tasks")

M["NTraceSyscalls"] = str(len(open(f"{ROOT}/tools/replay.py").read().split('TRACE = ("')[1].split('")')[0].replace('"\n         "', "").replace('" "', "").split(",")))
M["DataURL"] = "\\url{https://github.com/AmeerulShah/llm-coding-agent-sandbox-storage-study}"

for k in ("ProvOverlayMs", "ProvOverlayKiB", "ProvCopyS", "ProvCopyMiB", "ProvCloneS", "ProvCloneMiB", "ProvCloneThousandGiB", "EEImageMiB",
          "NOvl", "AblOvlDefFinal", "AblOvlPreFinal", "AblOvlReduction", "OvlMatchShare", "EEBaseMiB", "EEOptMiB", "EEBaseS", "EEOptMs", "EEReduction",
          "AblRcDef", "AblRcPre", "NAbl", "AblNoPycReadInc", "TraceSlowdown", "ToolShareMed", "OvlDiffKiB", "OvlPycShare"):
    M.setdefault(k, "??")
exec(open(f"{ROOT}/tools/revision_numbers.py").read())
# ---------------- implications table ----------------
impl = [
    ("O1 Sandbox setup at a fresh commit", f"Task touches {M.get('ResFracMed', '??')}\\% of its image", "Clone + checkout per sandbox", f"Base image + delta: {M.get('SetupDeltaS', '??')}\\,s vs.\\ {M.get('SetupCloneS', '??')}\\,s; warm mount {M.get('SetupWarmMs', '??')}\\,ms", "Measured"),
    ("O2 Bytecode built into the image", f"{M['PycShare']}\\% of writable layer is bytecode", "Bytecode written in sandbox", f"Upper layer {M['AblOvlReduction']}\\% smaller (pooled); tool time {M.get('PreTimeR', '??')}\\% (disabled: {M.get('NoPycTimeR', '??')}\\%)", "Measured"),
    ("O3 Git attributes read from the commit tree", f"{M.get('AttrShareFail', '??')}\\% of failed lookups are attribute-file probes", "Probe the working tree", f"{M.get('GitAttrFailRed', '??')}\\% fewer failed lookups in git calls; same output in {M.get('GitSameText', '??')} calls; history searches +{M.get('GitHistSlowdown', '??')}\\% time", "Measured"),
    ("O1--O3 combined", "", "Clone, bytecode written in sandbox", f"{M.get('StackTotalMiB', '??')} vs.\\ {M.get('StackBaseMiB', '??')}\\,MiB new data per sandbox (median)", "Measured"),
    ("O4 Per-step snapshots", f"{M['SnapZero']}\\% of calls change nothing", "Snapshot every step", f"Snapshot needed for {100 - int(M['SnapZero'])}\\% of calls; 90th-percentile change {M.get('SnapFilePninety', '??')}\\,KiB", "Trace-driven"),
    ("O5 Client metadata caching", f"{M['MetaPerStep']} metadata ops per call", "No client cache", f"Emulated remote layer ({M.get('RemoteEffUs', '??')}\\,\\textmu{{}}s per request): +{M.get('RemoteAddNonePct', '??')}\\% task time without caching, +{M.get('RemoteAddLongPct', '??')}\\% with long-lived caching", "Trace-driven, emulated"),
    ("O6 Page sharing among co-located sandboxes", "Same-repository tasks touch the same files", "Per-commit image layers", f"32 Django sandboxes: {M.get('ShareDjVB', '??')} vs.\\ {M.get('ShareDjContainers', '??')}\\,GiB", "Scenario"),
]
open(f"{PAPER}/tables/implications.tex", "w").write(
    "\\begin{tabular}{p{0.15\\textwidth}p{0.19\\textwidth}p{0.15\\textwidth}p{0.29\\textwidth}p{0.1\\textwidth}}\n\\toprule\nOptimization & Motivating finding & Baseline & Result & Evidence \\\\\n\\midrule\n"
    + "\n".join(" & ".join(r) + " \\\\" for r in impl) + "\n\\bottomrule\n\\end{tabular}\n")

with open(f"{PAPER}/numbers.tex", "w") as fh:
    fh.write("% Generated by tools/paper_numbers.py -- do not edit by hand\n")
    for k, v in sorted(M.items()):
        fh.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")
json.dump(extra, open(f"{RES}/extra_numbers.json", "w"), indent=1, default=str)
print(json.dumps({k: M[k] for k in sorted(M)}, indent=0)[:4000])
print(json.dumps(extra, indent=0, default=str)[:3000])
