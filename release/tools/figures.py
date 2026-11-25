#!/usr/bin/env python3
"""Render paper figures from results/*.csv (vector PDF, print-safe validated palette)."""
import json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "/home/claude/research/asio"; RES = f"{ROOT}/results"; FIG = f"{ROOT}/paper/figs"
os.makedirs(FIG, exist_ok=True)
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#1f1f1e", "#5b5b57", "#e6e5e0"
CLASSES = ["repo", "git", "env", "runtime", "system", "tmp", "home"]
CLABEL = {"repo": "repository tree", "git": ".git", "env": "virtual env.", "runtime": "Python runtime",
          "system": "system files", "tmp": "/tmp", "home": "home directory"}
MiB = 2 ** 20

plt.rcParams.update({
    "font.family": "serif", "font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7.5,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.8, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6,
    "pdf.fonttype": 42, "legend.frameon": False, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
W1, W2 = 3.45, 7.0


def ecdf(ax, x, color, label):
    x = np.sort(np.asarray(x, dtype=float)); y = np.arange(1, len(x) + 1) / len(x)
    ax.step(x, y, where="post", color=color, label=label)


def fig_cdfs(T):
    fig, axs = plt.subplots(1, 3, figsize=(W2, 1.75))
    panels = [("rb_total", "Bytes read per task (MiB)", MiB), ("wb_total", "Bytes written per task (MiB)", MiB),
              ("meta_ops", "Metadata operations per task", 1)]
    for ax, (col, lab, sc) in zip(axs, panels):
        ecdf(ax, T[col] / sc, PAL[0], None)
        ax.set_xscale("log"); ax.set_xlabel(lab); ax.set_ylim(0, 1.01)
        med = float(np.median(T[col] / sc))
        ax.axvline(med, color=INK2, lw=0.7, ls=":")
        ax.annotate(f"median {med:,.0f}" if med >= 10 else f"median {med:.1f}", (med, 0.08), xytext=(4, 0),
                    textcoords="offset points", color=INK, fontsize=6.5)
    axs[0].set_ylabel("Fraction of tasks")
    fig.savefig(f"{FIG}/cdf_per_task.pdf"); plt.close(fig)


def fig_classes(T, final_shares):
    rows = [("Bytes read", {c: T[f"rb_{c}"].sum() for c in CLASSES}),
            ("Read footprint (trace est.)", {c: T[f"ws_{c}"].sum() for c in CLASSES}),
            ("Bytes written", {c: T[f"wb_{c}"].sum() for c in CLASSES})]
    fig, ax = plt.subplots(figsize=(W1, 1.45))
    for i, (name, d) in enumerate(rows):
        tot = sum(d.values()); left = 0
        for j, c in enumerate(CLASSES):
            v = d[c] / tot
            if v <= 0:
                continue
            ax.barh(i, v, left=left, color=PAL[j], height=0.62, edgecolor="white", linewidth=1.0,
                    label=CLABEL[c] if i == 0 else None)
            if v >= 0.07:
                ax.text(left + v / 2, i, f"{v:.0%}", ha="center", va="center", color="white", fontsize=6.3, fontweight="bold")
            left += v
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows]); ax.invert_yaxis()
    ax.set_xlim(0, 1); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); ax.grid(axis="y", visible=False)
    handles, labels = ax.get_legend_handles_labels()
    used = [c for c in CLASSES if any(r[1][c] > 0 for r in rows)]
    h2 = [plt.Rectangle((0, 0), 1, 1, color=PAL[CLASSES.index(c)]) for c in used]
    ax.legend(h2, [CLABEL[c] for c in used], ncol=4, loc="upper center", bbox_to_anchor=(0.45, -0.22), handlelength=1.0, columnspacing=0.9)
    fig.savefig(f"{FIG}/bytes_by_class.pdf"); plt.close(fig)


def fig_categories():
    G = pd.read_csv(f"{RES}/by_category.csv", index_col=0)
    order = [c for c in ["search", "read", "edit", "vcs", "script", "test", "echo", "other", "env"]
             if c in G.index and max(G.loc[c, ["share_cmds", "share_rb", "share_wb", "share_meta"]]) >= 0.01]
    labels = {"search": "search (grep, find, ls)", "read": "read (cat, sed -n, head)", "edit": "edit (sed -i, redirect)",
              "vcs": "git", "script": "script run", "test": "test run", "echo": "shell builtins", "other": "other", "env": "package install"}
    metrics = [("share_cmds", "tool calls"), ("share_rb", "bytes read"), ("share_wb", "bytes written"), ("share_meta", "metadata ops")]
    fig, ax = plt.subplots(figsize=(W1, 2.35))
    h = 0.19; y = np.arange(len(order))
    for k, (col, lab) in enumerate(metrics):
        ax.barh(y + (k - 1.5) * h, G.loc[order, col], height=h * 0.92, color=PAL[k], label=lab)
    ax.set_yticks(y); ax.set_yticklabels([labels[o] for o in order]); ax.invert_yaxis()
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of total")
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.38, -0.17), handlelength=1.0, columnspacing=0.8)
    fig.savefig(f"{FIG}/by_category.pdf"); plt.close(fig)


def fig_growth():
    Gr = pd.read_csv(f"{RES}/ws_growth.csv")
    Gr["b"] = (Gr.frac_steps * 20).round() / 20
    g = Gr.groupby("b").frac_ws.quantile([0.25, 0.5, 0.75]).unstack()
    fig, ax = plt.subplots(figsize=(W1, 1.75))
    ax.fill_between(g.index, g[0.25], g[0.75], color=PAL[0], alpha=0.18, lw=0, label="interquartile range")
    ax.plot(g.index, g[0.5], color=PAL[0], label="median task")
    ax.set_xlabel("Progress through the trajectory (fraction of tool calls)"); ax.set_ylabel("Fraction of bytes read\nfirst touched so far")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.02); ax.legend(loc="lower right")
    fig.savefig(f"{FIG}/ws_growth.pdf"); plt.close(fig)


def fig_snapshot():
    S = pd.read_csv(f"{RES}/snapshot_steps.csv")
    fig, ax = plt.subplots(figsize=(W1, 1.7))
    for col, lab, c in (("block_level", "block-level delta (4 KiB)", PAL[0]), ("file_level", "file-level delta (whole files)", PAL[1])):
        x = np.sort(S[col].values / 1024.0 + 1e-3); y = np.arange(1, len(x) + 1) / len(x)
        ax.step(x, y, where="post", color=c, label=lab)
    ax.set_xscale("log"); ax.set_xlim(left=0.5); ax.set_xlabel("Snapshot delta per tool call (KiB)"); ax.set_ylabel("Fraction of tool calls")
    z = float((S.files == 0).mean())
    ax.annotate(f"{z:.0%} of calls change nothing", (0.6, z), xytext=(0, -12), textcoords="offset points", fontsize=6.5, color=INK)
    ax.legend(loc="lower right")
    fig.savefig(f"{FIG}/snapshot_delta.pdf"); plt.close(fig)


def fig_latency():
    L = pd.read_csv(f"{RES}/latency_image.csv") if os.path.exists(f"{RES}/latency_image.csv") else pd.read_csv(f"{RES}/latency_model.csv")
    g = L.groupby("rtt_us")[["nocache_frac", "cache_frac"]].median()
    fig, ax = plt.subplots(figsize=(W1, 1.75))
    ax.plot(g.index, g.nocache_frac, marker="o", ms=3.5, color=PAL[1], label="every lookup goes remote")
    ax.plot(g.index, g.cache_frac, marker="s", ms=3.5, color=PAL[0], label="client caches each path once")
    ax.axhline(1.0, color=INK2, lw=0.7, ls=":")
    ax.annotate("added time = whole task time", (11, 1.0), xytext=(0, 3), textcoords="offset points", fontsize=6.3, color=INK, ha="left")
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("Metadata round-trip time (µs)")
    ax.set_ylabel("Added time / recorded\ntask wall time (median)"); ax.legend(loc="lower right")
    fig.savefig(f"{FIG}/latency_model.pdf"); plt.close(fig)


def fig_fleet():
    p = f"{RES}/sharing_measured.csv"
    if not os.path.exists(p):
        return
    S = pd.read_csv(p); D = S[S.pool == "django"]
    fig, ax = plt.subplots(figsize=(W1, 1.85))
    for reg, col, mk, lab in (("private", PAL[1], "o", "private caches"), ("containers", PAL[3], "s", "per-commit image layers"),
                              ("version_base", PAL[0], "D", "per-version base image (O1)"), ("content", PAL[2], "^", "plus content sharing")):
        ax.plot(D.n, D[reg] / 2**30, color=col, marker=mk, ms=3, label=lab)
    ax.set_xscale("log", base=2); ax.set_yscale("log"); ax.set_xlabel("Co-located Django sandboxes of distinct tasks")
    ax.set_ylim(top=ax.get_ylim()[1] * 12)
    ax.set_ylabel("Page cache (GiB)"); ax.legend(loc="upper left", fontsize=6.0, ncol=2, columnspacing=0.8, handlelength=1.6)
    fig.savefig(f"{FIG}/fleet_sharing.pdf"); plt.close(fig)


def fig_ablation():
    po, pa = f"{RES}/ablation_overlay.csv", f"{RES}/ablation.csv"
    if not (os.path.exists(po) and os.path.exists(pa)):
        return
    O = pd.read_csv(po); A = pd.read_csv(pa)
    fig, axs = plt.subplots(1, 2, figsize=(W1, 1.55), gridspec_kw={"width_ratios": [2, 3]})
    vals = [O.upper_default.median() / MiB, O.upper_precompiled.median() / MiB]
    axs[0].bar([0, 1], vals, color=[PAL[0], PAL[2]], width=0.6)
    for i, v in enumerate(vals):
        axs[0].text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=6.3, color=INK)
    axs[0].set_xticks([0, 1]); axs[0].set_xticklabels(["default", "pre-\ncompiled"]); axs[0].set_title("Upper layer at end (MiB)")
    axs[0].grid(axis="x", visible=False)
    import glob
    pts = sorted(glob.glob(f"{RES}/bytecode_timing_random_r*.csv"))
    if pts:
        B = pd.concat([pd.read_csv(x) for x in pts], ignore_index=True)
        TT = B.pivot_table(index=["instance", "rep"], columns="variant", values="tool_s").dropna().groupby("instance").median()
        vals2 = [TT["default"].median(), TT["nopyc"].median(), TT["precompiled"].median()]
        title2, fmt = "Tool execution time per task (s)", "{:.1f}"
    else:
        A = A.set_index("variant").reindex(["default", "no bytecode", "precompiled"])
        vals2 = list(A.read_MiB); title2, fmt = "Bytes read under tracing (MiB)", "{:.0f}"
    axs[1].bar(range(3), vals2, color=[PAL[0], PAL[1], PAL[2]], width=0.6)
    for i, v in enumerate(vals2):
        axs[1].text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=6.3, color=INK)
    axs[1].set_xticks(range(3)); axs[1].set_xticklabels(["default", "no\nbytecode", "pre-\ncompiled"]); axs[1].set_title(title2)
    axs[1].grid(axis="x", visible=False)
    fig.tight_layout(w_pad=1.0)
    fig.savefig(f"{FIG}/ablation.pdf"); plt.close(fig)


if __name__ == "__main__":
    T = pd.read_csv(f"{RES}/instances.csv")
    fig_cdfs(T); fig_classes(T, None); fig_categories(); fig_growth(); fig_snapshot(); fig_latency(); fig_fleet(); fig_ablation()
    print("figures:", sorted(os.listdir(FIG)))
