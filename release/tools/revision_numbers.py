# Revision analyses (executed by paper_numbers.py before numbers.tex is written; shares its namespace:
# M, RES, PAPER, ROOT, pd, np, json, os, pc, f0, f1).
# Fidelity sensitivity, fresh-commit setup, measured page-cache footprint and co-location scenario,
# randomized bytecode timing.
from scipy.stats import wilcoxon

# ---------------- replay fidelity: all calls vs matching calls ----------------
if os.path.exists(f"{RES}/fidelity.csv"):
    F = pd.read_csv(f"{RES}/fidelity.csv").set_index("finding"); FJ = json.load(open(f"{RES}/fidelity.json"))
    M["FidNMatchCalls"] = f"{FJ['n_match_calls']:,}"; M["FidNCleanTasks"] = str(FJ["n_clean_tasks"])
    M["FidTestMis"] = pc(FJ["test_mismatch_share"]); M["FidTestAgree"] = pc(FJ["test_call_agreement"])
    M["FidBytesMatch"] = pc(FJ["bytes_read_by_matching_calls"]); M["FidMetaOpsMatch"] = pc(FJ["meta_by_matching_calls"])
    _sh = [abs(F.loc[k, "matching_calls"] - F.loc[k, "all"]) for k in ("Test runs, % of bytes read", "Test runs, % of bytes written")]
    M["FidTestShift"] = f0(max(_sh))
    short = {"Metadata ops per read/write call, median task": "Meta", "Failed lookups, % of metadata ops (pooled)": "Fail",
             "Test runs, % of bytes read": "TestRead", "Test runs, % of bytes written": "TestWrite",
             "Searches, % of bytes read": "SearchRead", "Calls that change nothing, %": "Zero"}
    for k, s in short.items():
        for col, suf in (("all", "All"), ("matching_calls", "Match"), ("clean_tasks", "Clean")):
            v = F.loc[k, col]
            M[f"Fid{s}{suf}"] = f1(v) if s == "Meta" else pc(v / 100)
    lines = []
    for k in F.index:
        a, m, c = F.loc[k, "all"], F.loc[k, "matching_calls"], F.loc[k, "clean_tasks"]
        fmt = (lambda x: "--" if pd.isna(x) else f"{x:.1f}") if ("ops" in k or "MiB" in k) else (lambda x: "--" if pd.isna(x) else f"{x:.0f}")
        lab = k.replace("%", "\\%")
        lines.append(f"{lab} & {fmt(a)} & {fmt(m)} & {fmt(c)} \\\\")
    open(f"{PAPER}/tables/fidelity.tex", "w").write(
        "\\begin{tabular}{p{0.44\\columnwidth}rrr}\n\\toprule\n"
        "Finding & All & Matching & Clean \\\\\n & calls & calls & tasks \\\\\n\\midrule\n"
        + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

# ---------------- fresh-commit setup ----------------
if os.path.exists(f"{RES}/setup_bench.csv"):
    SB = pd.read_csv(f"{RES}/setup_bench.csv")
    SB = SB[SB.rc == 0]
    M["NSetup"] = str(SB.instance.nunique())
    g = SB.groupby(["strategy"]).agg(s=("seconds", "median"), b=("new_bytes", "median"))
    gd = SB[SB.repo == "django"].groupby("strategy").agg(s=("seconds", "median"), b=("new_bytes", "median"))
    M["SetupWarmMs"] = f"{g.loc['warm_mount', 's'] * 1000:.0f}"
    M["SetupWarmMsMax"] = f"{SB[SB.strategy == 'warm_mount'].seconds.quantile(0.99) * 1000:.0f}"
    M["SetupCloneS"] = f"{g.loc['clone', 's']:.1f}"; M["SetupCloneMiB"] = f"{g.loc['clone', 'b'] / 2**20:.0f}"
    M["SetupDeltaS"] = f"{g.loc['base_delta', 's']:.2f}"; M["SetupDeltaMiB"] = f"{g.loc['base_delta', 'b'] / 2**20:.1f}"
    M["SetupCloneSDj"] = f"{gd.loc['clone', 's']:.1f}"; M["SetupCloneMiBDj"] = f"{gd.loc['clone', 'b'] / 2**20:.0f}"
    M["SetupDeltaSDj"] = f"{gd.loc['base_delta', 's']:.2f}"; M["SetupDeltaMiBDj"] = f"{gd.loc['base_delta', 'b'] / 2**20:.1f}"
    pv = SB.pivot_table(index="instance", columns="strategy", values=["seconds", "new_bytes"])
    M["SetupDeltaFasterShare"] = pc(float((pv["seconds"]["base_delta"] < pv["seconds"]["clone"]).mean()))
    M["SetupDeltaTimeRatio"] = f1(float((pv["seconds"]["clone"] / pv["seconds"]["base_delta"]).median()))
    M["SetupDeltaByteRatio"] = f0(float((pv["new_bytes"]["clone"] / pv["new_bytes"]["base_delta"].clip(lower=1)).median()))
    clone_s = g.loc["clone", "s"]; warm = g.loc["warm_mount", "s"]
    M["SetupBreakEvenN"] = f0(clone_s / (g.loc["base_delta", "s"] - warm))
    for n, w_ in ((2, "Two"), (8, "Eight"), (32, "ThirtyTwo")):
        M[f"SetupAmort{w_}"] = f"{(clone_s + n * warm) / n:.2f}"
    BI = pd.read_csv(f"{RES}/setup_base_images.csv") if os.path.exists(f"{RES}/setup_base_images.csv") else None
    if BI is not None:
        M["SetupNBase"] = str(len(BI)); M["SetupBaseGiB"] = f"{BI.image_bytes.sum() / 2**30:.1f}"
    rows_t = [("Clone + checkout (per sandbox)", "clone"), ("Per-commit image, warm mount", "warm_mount"),
              ("Per-version base image + checkout delta", "base_delta")]
    fs = lambda x: f"{x:.3f}" if x < 0.1 else f"{x:.2f}" if x < 1 else f"{x:.1f}"
    fb = lambda b: f"{b / 2**20:.1f}"
    lines = [f"{lab} & {fs(gd.loc[k, 's'])} & {fb(gd.loc[k, 'b'])} & {fs(g.loc[k, 's'])} & {fb(g.loc[k, 'b'])} \\\\" for lab, k in rows_t]
    open(f"{PAPER}/tables/setup.tex", "w").write(
        "\\begin{tabular}{lrrrr}\n\\toprule\n & \\multicolumn{2}{c}{Django} & \\multicolumn{2}{c}{All tasks} \\\\\n"
        "Strategy at the task's commit & Time (s) & Written (MiB) & Time (s) & Written (MiB) \\\\\n\\midrule\n"
        + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

# ---------------- measured page-cache footprint and co-location scenario ----------------
if os.path.exists(f"{RES}/sharing_measured.json"):
    SJ = json.load(open(f"{RES}/sharing_measured.json"))
    M["NRes"] = str(SJ["n_tasks"]); M["ResMiBMed"] = f0(SJ["res_image_MiB_med"])
    M["ResFracMed"] = f1(100 * SJ["res_frac_image_med"]); M["ResTraceFracMed"] = f1(100 * SJ["trace_frac_image_med"])
    M["ResOverTrace"] = f1(SJ["res_over_trace_med"]); M["ResTraceMiBMed"] = f0(SJ["trace_ws_MiB_med"])
    cv = pd.DataFrame(SJ["curves"])
    def at(pool, n, reg):
        r = cv[(cv.pool == pool) & (cv.n == n)]
        return float(r[reg].iloc[0]) if len(r) else float("nan")
    for pool, P in (("django", "Dj"), ("mixed", "Mx")):
        n = 32
        pr, co, vb, ct = (at(pool, n, r) for r in ("private", "containers", "version_base", "content"))
        M[f"Share{P}Private"] = f1(pr / 2**30); M[f"Share{P}Containers"] = f1(co / 2**30)
        M[f"Share{P}VB"] = f1(vb / 2**30); M[f"Share{P}Content"] = f1(ct / 2**30)
        M[f"Share{P}ContainersSaving"] = pc(1 - co / pr); M[f"Share{P}VBSaving"] = pc(1 - vb / co)
        M[f"Share{P}ContentSaving"] = pc(1 - ct / vb)

# ---------------- randomized bytecode timing ----------------
import glob as _glob
_bt = sorted(_glob.glob(f"{RES}/bytecode_timing_random_r*.csv"))
if _bt:
    BT = pd.concat([pd.read_csv(x) for x in _bt], ignore_index=True)
    BT.to_csv(f"{RES}/bytecode_timing_random.csv", index=False)
    P = BT.pivot_table(index=["instance", "rep"], columns="variant", values="tool_s").dropna()
    T2 = P.groupby("instance").median()  # median over repetitions per task
    M["NTimingR"] = str(len(T2)); M["NRunsR"] = str(len(BT)); M["NRepsR"] = str(BT.rep.nunique())
    sg = lambda x: ("+" if x >= 0 else "$-$") + f"{abs(100 * x):.0f}"
    rn = T2.nopyc / T2.default - 1; rp = T2.precompiled / T2.default - 1
    M["NoPycTimeR"] = sg(float(rn.median())); M["PreTimeR"] = sg(float(rp.median()))
    M["NoPycSlowerR"] = str(int((rn > 0).sum())); M["PreFasterR"] = str(int((rp < 0).sum()))
    pn, pp = wilcoxon(T2.nopyc, T2.default).pvalue, wilcoxon(T2.precompiled, T2.default).pvalue
    fp = lambda p: "$p<0.001$" if p < 0.001 else f"$p={p:.2f}$"
    M["NoPycPR"] = fp(pn); M["PrePR"] = fp(pp)
    # bootstrap 95% CI of the median ratio
    rng = np.random.default_rng(0)
    def ci(x):
        b = [np.median(rng.choice(x, len(x))) for _ in range(2000)]
        return np.percentile(b, [2.5, 97.5])
    lo, hi = ci(rp.values); M["PreTimeRCI"] = f"{sg(lo)} to {sg(hi)}"
    lo, hi = ci(rn.values); M["NoPycTimeRCI"] = f"{sg(lo)} to {sg(hi)}"
    # order check: tool time relative to the task's mean, by position in the run order
    BT["rel"] = BT.tool_s / BT.groupby(["instance", "rep"]).tool_s.transform("mean")
    pos = BT.groupby("position").rel.median()
    M["OrderEffect"] = pc(float(pos.max() - pos.min()))
    # repeatability between repetitions (default variant)
    if BT.rep.nunique() > 1:
        d = BT[BT.variant == "default"].pivot_table(index="instance", columns="rep", values="tool_s").dropna()
        M["RepCV"] = pc(float((d.std(axis=1) / d.mean(axis=1)).median()))
    lo_p, hi_p = ci(rp.values)
    if lo_p <= 0 <= hi_p:
        M["PreTimeAbstractR"] = "with no measurable change in tool execution time"
    elif hi_p < 0:
        M["PreTimeAbstractR"] = f"and cuts tool execution time by {pc(float(-rp.median()))}\\%"
    else:
        M["PreTimeAbstractR"] = f"at the cost of {pc(float(rp.median()))}\\% more tool execution time"

# ---------------- snapshot sizes at file level (baseline) vs block level ----------------
SS = pd.read_csv(f"{RES}/snapshot_steps.csv")
M["SnapFilePninety"] = f0(float(SS.file_level.quantile(0.9)) / 1024)
M["SnapBlockPninetyChk"] = f0(float(SS.block_level.quantile(0.9)) / 1024)
nz = SS[SS.file_level > 0]
M["SnapBlockOverFile"] = pc(float(nz.block_level.sum() / nz.file_level.sum()))

# ---------------- git attribute lookups: trace shares and the attr.tree benchmark ----------------
import re as _re
_C = pd.read_csv(f"{RES}/commands.csv", low_memory=False)
_C = _C[_C.instance.isin(set(pd.read_csv(f"{RES}/instances.csv").instance))]
_C["fail"] = _C.open_fail.fillna(0) + _C.stat_fail.fillna(0)
_H = _re.compile(r"git\s+log\b.*(-S|-G|-p\b|--patch)|git\s+log\s+-[A-Za-z]*p")
_h = _C[(_C.cat == "vcs") & _C.cmd.fillna("").apply(lambda c: bool(_H.search(c)))]
M["GitHistCalls"] = str(len(_h)); M["GitHistTasks"] = str(_h.instance.nunique())
M["GitHistFailShare"] = pc(float(_h.fail.sum() / _C.fail.sum()))
if os.path.exists(f"{RES}/gitattr_trace.json"):
    GJ = json.load(open(f"{RES}/gitattr_trace.json"))
    M["AttrShareFail"] = pc(GJ["attr_share_of_failed"]); M["AttrShareMeta"] = pc(GJ["attr_share_of_meta"])
if os.path.exists(f"{RES}/git_attr_bench.csv"):
    GB = pd.read_csv(f"{RES}/git_attr_bench.csv")
    GB["ishist"] = GB.cmd.fillna("").apply(lambda c: bool(_H.search(c)))
    a_ = GB[GB.config == "default"].set_index(["instance", "step"])
    b_ = GB[GB.config == "attr_tree"].set_index(["instance", "step"]).rename(columns={"failed": "fa", "meta_ops": "ma", "seconds": "sa"})
    J = a_[["failed", "meta_ops", "seconds", "same_output", "ishist", "stratum"]].join(b_[["fa", "ma", "sa"]], how="inner")
    M["GitBenchCalls"] = f"{len(J):,}"
    M["GitBenchHistTasks"] = str(J[J.stratum == "history"].reset_index().instance.nunique())
    M["GitBenchRandTasks"] = str(J[J.stratum == "random"].reset_index().instance.nunique())
    M["GitAttrFailRed"] = pc(float(1 - J.fa.sum() / J.failed.sum()))
    M["GitMetaRed"] = pc(float(1 - J.ma.sum() / J.meta_ops.sum()))
    M["GitSame"] = pc(float(J.same_output.mean()), 1)
    JH = J[J.ishist].dropna(subset=["seconds", "sa"])
    M["GitNHistTimed"] = str(len(JH))
    M["GitHistSlowdown"] = pc(float((JH.sa / JH.seconds).median() - 1))
    avoided = (JH.failed - JH.fa)
    M["GitHistAvoidedK"] = f0(float(avoided.median()) / 1000)
    added = (JH.sa - JH.seconds)
    M["GitHistAddedS"] = f1(float(added.median()))
    M["GitBreakEvenUs"] = f0(float(added.sum() / avoided.sum() * 1e6))  # pooled over the timed history searches
    JO = J[~J.ishist].dropna(subset=["seconds", "sa"])
    M["GitOtherSlowdown"] = pc(float((JO.sa / JO.seconds).median() - 1))
for k in ("GitBenchCalls", "GitBenchHistTasks", "GitBenchRandTasks", "GitAttrFailRed", "GitMetaRed", "GitSame", "GitHistSlowdown", "GitHistAvoidedK", "GitHistAddedS", "GitBreakEvenUs"):
    M.setdefault(k, "??")
if "NoPycTimeR" in M:
    M["NoPycTimeRAbs"] = M["NoPycTimeR"].replace("+", "").replace("$-$", "")

for k in ("NTimingR", "NRunsR", "NRepsR", "NoPycTimeR", "PreTimeR", "NoPycSlowerR", "PreFasterR", "NoPycPR", "PrePR",
          "PreTimeRCI", "NoPycTimeRCI", "OrderEffect", "RepCV", "PreTimeAbstractR", "NoPycTimeRAbs"):
    M.setdefault(k, "??")

# ---------------- O3 break-even with and without negative-lookup caching; O5 restricted to image layers ----------------
if os.path.exists(f"{RES}/git_attr_distinct.json") and "GitHistAddedS" in M and M["GitHistAddedS"] != "??":
    GD = json.load(open(f"{RES}/git_attr_distinct.json"))
    d = float(np.median([c["distinct"] for c in GD["calls"]])); tot = float(np.median([c["total"] for c in GD["calls"]]))
    M["GitHistDistinctK"] = f1(d / 1000); M["GitHistRepeat"] = f0(tot / d)
    added_med = float(JH.sa.sub(JH.seconds).median())
    M["GitBreakEvenCachedUs"] = f0(added_med / d * 1e6)
if os.path.exists(f"{RES}/latency_image.json"):
    LI = json.load(open(f"{RES}/latency_image.json"))
    M["LatFiveNoCacheFrac"] = pc(LI["nocache_500"]); M["LatFiveCacheFrac"] = f1(100 * LI["cache_500"])
    M["LatHundredNoCacheFrac"] = pc(LI["nocache_100"]); M["DistinctPaths"] = f"{LI['distinct_med']:,.0f}"
    M["LatImageOpsK"] = f0(LI["ops_med"] / 1000)

# ---------------- combined stack (O1 base image + O2 precompiled + O3 attr.tree), measured ----------------
_sp = sorted(_glob.glob(f"{ROOT}/runs_stack/*/summary.json"))
if _sp and os.path.exists(f"{RES}/ablation_overlay.csv") and os.path.exists(f"{RES}/setup_bench.csv"):
    AO = pd.read_csv(f"{RES}/ablation_overlay.csv").set_index("instance")
    SBc = pd.read_csv(f"{RES}/setup_bench.csv"); SBc = SBc[(SBc.rc == 0) & (SBc.strategy == "clone")]
    clone_b = SBc.groupby("repo").new_bytes.median(); clone_s = SBc.groupby("repo").seconds.median()
    rows_s = []
    for sp in _sp:
        sm = json.load(open(sp)); i = sm["instance"]
        if sm.get("stack") is None or sm.get("overlay_upper") is None or i not in AO.index:
            continue
        st = sm["stack"]; rd = sm["repo_dir"]
        rows_s.append({"instance": i, "repo": rd, "rc": sm["rc_match"], "checkout_s": st["checkout_s"], "compile_s": st["compile_s"],
                       "install_s": st["install_s"], "delta": st["delta_bytes"], "delta_pyc": st["delta_pyc_bytes"],
                       "setup_upper": st["setup_upper_bytes"], "total_upper": sm["overlay_upper"]["du_bytes"],
                       "base_clone_b": clone_b.get(rd, np.nan), "base_clone_s": clone_s.get(rd, np.nan),
                       "base_upper": AO.loc[i, "upper_default"]})
    SS_ = pd.DataFrame(rows_s); SS_.to_csv(f"{RES}/stack.csv", index=False)
    if len(SS_):
        MiB_ = 2**20
        SS_["base_total"] = SS_.base_clone_b + SS_.base_upper
        M["NStack"] = str(len(SS_))
        M["StackCheckoutS"] = f"{SS_.checkout_s.median():.2f}"; M["StackCompileS"] = f"{SS_.compile_s.median():.2f}"
        M["StackCloneS"] = f"{SS_.base_clone_s.median():.1f}"
        M["StackDeltaMiB"] = f1(SS_.delta.median() / MiB_); M["StackDeltaPycMiB"] = f1(SS_.delta_pyc.median() / MiB_)
        M["StackSetupMiB"] = f1(SS_.setup_upper.median() / MiB_); M["StackTotalMiB"] = f1(SS_.total_upper.median() / MiB_)
        M["StackTaskKiB"] = f0((SS_.total_upper - SS_.setup_upper).median() / 1024)
        M["StackBaseMiB"] = f1(SS_.base_total.median() / MiB_)
        M["StackReduction"] = pc(float(1 - SS_.total_upper.sum() / SS_.base_total.sum()))
        M["StackRc"] = pc(float(SS_.rc.median()))
for k in ("NStack", "StackCheckoutS", "StackCompileS", "StackCloneS", "StackDeltaMiB", "StackDeltaPycMiB", "StackSetupMiB",
          "StackTotalMiB", "StackTaskKiB", "StackBaseMiB", "StackReduction", "StackRc"):
    M.setdefault(k, "??")

# ---------------- .git fidelity: reachable history and all-refs calls ----------------
_m = _C.cmd.fillna("").str.contains(r"git\s+(?:log|branch|tag|show-ref|rev-list)[^|;&]*(?:--all|-a\b|--remotes|-r\b)", regex=True)
M["GitAllRefCalls"] = str(int(_m.sum())); M["GitAllRefTasks"] = str(_C[_m].instance.nunique())
if os.path.exists(f"{RES}/git_reach.csv"):
    GR = pd.read_csv(f"{RES}/git_reach.csv")
    M["NGitReach"] = str(len(GR)); M["GitReachShare"] = pc(float((GR.reachable_bytes / GR.all_bytes).median()))
for k in ("NGitReach", "GitReachShare"):
    M.setdefault(k, "??")

# ---------------- wording helpers (copyedit) ----------------
_w = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
try:
    _nf = int(nf); _nc = int(ncalls)
    if _nf > 0:
        M["FsyncTasksText"] = (f"across all {M['NInc']} tasks there is a single \\texttt{{fsync}}-family call, in one task" if _nc == 1
                               else f"across all {M['NInc']} tasks there are {_w.get(_nc, _nc)} \\texttt{{fsync}}-family calls, in {_w.get(_nf, _nf)} task{'s' if _nf != 1 else ''}")
except NameError:
    pass
if M.get("AblRcDef") == M.get("AblRcNoPyc") == M.get("AblRcPre"):
    M["AblRcText"] = f"{M['AblRcDef']}\\% in each"
else:
    M["AblRcText"] = f"{M.get('AblRcDef')}\\%, {M.get('AblRcNoPyc')}\\% and {M.get('AblRcPre')}\\%"
if "GitSame" in M and M["GitSame"] != "??":
    _n = int(M["GitBenchCalls"].replace(",", ""))
    _k = int(round(float(M["GitSame"]) / 100 * _n))
    M["GitSameText"] = f"all {M['GitBenchCalls']}" if _k == _n else f"{_k:,} of {M['GitBenchCalls']}"
M.setdefault("GitSameText", "??")

# ---------------- O5 measured on an emulated remote image layer ----------------
if os.path.exists(f"{RES}/remote_bench.csv"):
    RB = pd.read_csv(f"{RES}/remote_bench.csv")
    RB["req"] = RB.req_repo + RB.req_env + RB.req_runtime
    TP = RB.pivot_table(index="instance", columns="config", values="tool_s")
    RQ = RB.pivot_table(index="instance", columns="config", values="req")
    dly = [c for c in TP.columns if c.startswith("none_") and c != "none_0"][0].split("_")[1]
    eff = ((TP[f"none_{dly}"] - TP["none_0"]) / RQ[f"none_{dly}"]) * 1e6
    M["NRemote"] = str(len(TP)); M["RemoteEffUs"] = f0(float(eff.median()))
    Tm = pd.read_csv(f"{RES}/instances.csv").set_index("instance")
    LI_ = pd.read_csv(f"{RES}/latency_image.csv"); LI_ = LI_[LI_.rtt_us == 500].set_index("instance")
    adds = {}
    for c in ("none", "short", "long"):
        add = TP[f"{c}_{dly}"] - TP[f"{c}_0"]
        adds[c] = add
        M[f"RemoteReq{c.title()}K"] = f0(float(RQ[f"{c}_{dly}"].median()) / 1000)
        M[f"RemoteAdd{c.title()}S"] = f1(float(add.median()))
        M[f"RemoteAdd{c.title()}Pct"] = pc(float((add / Tm.loc[add.index, "task_wall_s"]).median()))
    e = eff.reindex(TP.index) / 1e6
    model_up = LI_.loc[TP.index, "ops"] * e; model_lo = LI_.loc[TP.index, "distinct"] * e
    M["RemoteAmp"] = f1(float((RQ[f"none_{dly}"] / LI_.loc[TP.index, "ops"]).median()))
    M["RemoteVsUpper"] = f1(float((adds["none"] / model_up).median()))
    M["RemoteVsLower"] = f1(float((adds["long"] / model_lo).median()))
    M["RemoteLocalS"] = f1(float(TP["local"].median())); M["RemoteNoneZeroS"] = f1(float(TP["none_0"].median()))
    M["RemoteLongVsShort"] = pc(float((1 - adds["long"] / adds["short"]).median()))
    M["RemoteShortVsNone"] = pc(float((1 - adds["short"] / adds["none"]).median()))
    M["RemoteRcSame"] = "yes" if (RB.groupby("instance").rc_match.nunique() == 1).all() else "no"

# ---------------- O3 on the emulated remote layer ----------------
if os.path.exists(f"{RES}/git_remote_bench.csv"):
    GRB = pd.read_csv(f"{RES}/git_remote_bench.csv")
    if len(GRB):
        dmax = GRB.delay_us.max()
        for cache, C_ in (("short", "Short"), ("long", "Long")):
            for a, A_ in ((0, "Off"), (1, "On")):
                sub = GRB[(GRB.cache == cache) & (GRB.attr_tree == a) & (GRB.delay_us == dmax)]
                if len(sub):
                    M[f"GitRem{C_}{A_}S"] = f1(float(sub.seconds.median()))
                    M[f"GitRemReq{C_}{A_}K"] = f1(float(sub.requests.median()) / 1000)
        M["NGitRem"] = str(GRB.instance.nunique())
for k in ("GitRemShortOffS", "GitRemShortOnS", "GitRemLongOffS", "GitRemLongOnS", "GitRemReqShortOffK", "GitRemReqShortOnK",
          "GitRemReqLongOffK", "GitRemReqLongOnK", "NGitRem"):
    M.setdefault(k, "??")
if M.get("GitRemShortOffS", "??") != "??":
    M["GitRemSpeedup"] = f1(float(M["GitRemShortOffS"]) / float(M["GitRemShortOnS"]))
M.setdefault("GitRemSpeedup", "??")
