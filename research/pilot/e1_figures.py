"""E1 figures in the reference style (SwarmWorld, arXiv 2608.26081): lettered panels,
thin lines, capped error bars, muted green/orange/purple/slate, one legend row below."""
import json, pathlib, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.colors import LinearSegmentedColormap
ROOT = pathlib.Path(__file__).resolve().parents[2]; OUT = ROOT / "research/e1"
A = json.load(open(OUT / "aggregates.json")); agg, pairs, order = A["aggregates"], A["pairs"], A["order"]
GREEN, ORANGE, PURPLE, SLATE = "#1f7f6d", "#e8703a", "#8e5ab6", "#5f6f88"
INK, MUTED, LIGHT = "#222222", "#555555", "#d9dde3"
TYPED, FREE = GREEN, ORANGE
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
                     "axes.edgecolor": "#444444", "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
                     "axes.spines.top": False, "axes.spines.right": False, "legend.fontsize": 7, "svg.fonttype": "none", "text.color": INK, "axes.labelcolor": INK,
                     "xtick.color": INK, "ytick.color": INK})
LABELS = {"Qwen3.8-27B": "Qwen3.8-27B", "Nemotron-3.5-30B": "Nemotron-3.5-30B", "Qwen3.5-397B": "Qwen3.5-397B", "gpt-4.1": "gpt-4.1"}
def letter(ax, s, dx=-0.18, dy=1.08):
    ax.text(dx, dy, s, transform=ax.transAxes, fontsize=10, fontweight="bold", va="bottom", ha="left", color=INK)
def save(fig, name):
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight"); fig.savefig(OUT / f"{name}.png", dpi=240, bbox_inches="tight"); plt.close(fig); print("wrote", name)
def eb(ax, x, y, lo, hi, color, marker, label=None, ms=4.2):
    ax.errorbar(x, y, xerr=[[x - lo], [hi - x]], fmt=marker, color=color, ms=ms, mfc=color, mec=color, elinewidth=1.0, capsize=2.2, capthick=1.0, label=label, zorder=3)
ys = np.arange(len(order))
# ---------------- Figure 2: results, panels A-F ----------------
fig = plt.figure(figsize=(7.2, 6.6))
gs = fig.add_gridspec(3, 2, hspace=0.75, wspace=0.55, left=0.17, right=0.98, top=0.95, bottom=0.11)
axA, axB, axC, axD, axE, axF = [fig.add_subplot(gs[i // 2, i % 2]) for i in range(6)]
# A claims per game
for i, m in enumerate(order):
    t, f = agg.get(f"{m}|typed"), agg.get(f"{m}|free")
    if t: eb(axA, t["claims"]["mean"], i + 0.17, t["claims"]["lo"], t["claims"]["hi"], TYPED, "o")
    if f: eb(axA, f["claims"]["mean"], i - 0.17, f["claims"]["lo"], f["claims"]["hi"], FREE, "s")
axA.set_yticks(ys); axA.set_yticklabels([LABELS[m] for m in order]); axA.invert_yaxis(); axA.set_xlabel("Explicit hand claims per game"); axA.set_xlim(0, 80); letter(axA, "A")
# B false-claim rate
for i, m in enumerate(order):
    t, f = agg.get(f"{m}|typed"), agg.get(f"{m}|free")
    if t and t["false_claim_rate"]: eb(axB, t["false_claim_rate"]["mean"], i + 0.17, t["false_claim_rate"]["lo"], t["false_claim_rate"]["hi"], TYPED, "o")
    if f and f["false_claim_rate"]: eb(axB, f["false_claim_rate"]["mean"], i - 0.17, f["false_claim_rate"]["lo"], f["false_claim_rate"]["hi"], FREE, "s")
axB.set_yticks(ys); axB.set_yticklabels([LABELS[m] for m in order]); axB.invert_yaxis(); axB.set_xlabel("False-claim rate"); axB.set_xlim(0, 0.65); letter(axB, "B")
axB.text(0.53, 1.42, "tags invalid", fontsize=6.3, color=MUTED, ha="center", va="top")
# C paired trades
for i, m in enumerate(order):
    p = pairs.get(m)
    if not p: continue
    axC.errorbar(p["trades_mean"], i, xerr=p["trades_ci95"], fmt="o", color=SLATE, ms=4.2, elinewidth=1.0, capsize=2.2, capthick=1.0, zorder=3)
    axC.text(15.5, i, f"n={p['n']}", va="center", ha="right", fontsize=6.5, color=MUTED)
axC.axvline(0, color="#444444", lw=0.6); axC.axvspan(-3.5, 3.5, color=LIGHT, alpha=0.5, lw=0)
axC.set_yticks(ys); axC.set_yticklabels([LABELS[m] for m in order]); axC.invert_yaxis(); axC.set_xlim(-16, 16); axC.set_xlabel("Trades executed, free − typed (same seed)"); letter(axC, "C")
# D plan outcomes
for i, m in enumerate(order):
    t = agg.get(f"{m}|typed"); left = 0
    for key, col in (("plans_kept", GREEN), ("plans_broken", ORANGE), ("plans_excused", SLATE)):
        v = t[key]["mean"]; axD.barh(i, v, left=left, height=0.55, color=col, edgecolor="white", linewidth=1.0); left += v
    axD.text(left + 0.3, i, f"{t['plan_mismatch']['mean']:.1f} ≠ private", va="center", fontsize=6.3, color=MUTED)
axD.set_yticks(ys); axD.set_yticklabels([LABELS[m] for m in order]); axD.invert_yaxis(); axD.set_xlabel("Announced plans per typed game"); axD.set_xlim(0, 16); letter(axD, "D")
# E tags split
for i, m in enumerate(order):
    t = agg.get(f"{m}|typed")
    axE.barh(i, t["action_bound"]["mean"], height=0.55, color=LIGHT, edgecolor="white", linewidth=1.0)
    axE.barh(i, t["beyond"]["mean"], left=t["action_bound"]["mean"], height=0.55, color=PURPLE, edgecolor="white", linewidth=1.0)
    axE.text(t["action_bound"]["mean"] + t["beyond"]["mean"] + 3, i, f"{t['beyond']['mean']:.0f} scored", va="center", fontsize=6.3, color=MUTED)
axE.set_yticks(ys); axE.set_yticklabels([LABELS[m] for m in order]); axE.invert_yaxis(); axE.set_xlabel("Tagged statements per typed game"); axE.set_xlim(0, 230); letter(axE, "E")
# F summary heatmap: rows metrics, cols model x arm, normalised per row (purple), printed raw values
rows = [("Trades per game", lambda a: a["trades"]["mean"], "{:.0f}"), ("Hand claims per game", lambda a: a["claims"]["mean"], "{:.1f}"),
        ("False-claim rate", lambda a: a["false_claim_rate"]["mean"] if a["false_claim_rate"] else np.nan, "{:.2f}"),
        ("Violation rate", lambda a: a["violation_rate"]["mean"] if a["violation_rate"] else np.nan, "{:.2f}"),
        ("Finished on 10 VP", lambda a: a["finished"] / a["n"], "{:.2f}")]
cols = [(m, arm) for m in order for arm in ("typed", "free")]
M = np.array([[r[1](agg[f"{m}|{arm}"]) for (m, arm) in cols] for r in rows], dtype=float)
norm = np.array([(row - np.nanmin(row)) / (np.nanmax(row) - np.nanmin(row) + 1e-9) for row in M])
cmap = LinearSegmentedColormap.from_list("pur", ["#f4eef8", "#8e5ab6", "#3b1f5e"])
axF.imshow(norm, cmap=cmap, aspect="auto", vmin=0, vmax=1)
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        v = M[i, j]; axF.text(j, i, rows[i][2].format(v), ha="center", va="center", fontsize=6.2, color="white" if norm[i, j] > 0.55 else INK)
ABBR = {"Qwen3.8-27B": "Q3.8-27B", "Nemotron-3.5-30B": "Nem-30B", "Qwen3.5-397B": "Q3.5-397B", "gpt-4.1": "gpt-4.1"}
axF.set_xticks(range(len(cols))); axF.set_xticklabels([arm for m, arm in cols], fontsize=6)
for k, m in enumerate(order):                     # model name once, centred over its typed/free pair
    axF.text(2 * k + 0.5, -0.9, ABBR[m], ha="center", va="bottom", fontsize=6.3, color=INK)
    if k: axF.axvline(2 * k - 0.5, color="white", lw=2)
axF.set_yticks(range(len(rows))); axF.set_yticklabels([r[0] for r in rows], fontsize=6.5); axF.tick_params(length=0)
for s in axF.spines.values(): s.set_visible(False)
letter(axF, "F", dx=-0.62, dy=1.16)
# legend row
handles = [Line2D([0], [0], marker="o", color=TYPED, lw=1, ms=4.2, label="Typed arm (speaker's own tag)"),
           Line2D([0], [0], marker="s", color=FREE, lw=1, ms=4.2, label="Free arm (extractor)"),
           Line2D([0], [0], marker="o", color=SLATE, lw=1, ms=4.2, label="Paired difference, 95% CI"),
           Patch(color=GREEN, label="plan kept"), Patch(color=ORANGE, label="plan broken"), Patch(color=SLATE, label="plan excused (never legal)"),
           Patch(color=LIGHT, label="action-bound tag"), Patch(color=PURPLE, label="scored tag (beyond the move)")]
fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.55, 0.0), handlelength=1.6, columnspacing=1.4)
save(fig, "fig2_results")
# ---------------- Figure 3: talk catalogue small multiples ----------------
cats = list(next(iter(agg.values()))["talk"].keys())
fig, axes = plt.subplots(1, len(order), figsize=(7.2, 2.9), sharey=True, gridspec_kw={"wspace": 0.12, "left": 0.2, "right": 0.99, "top": 0.86, "bottom": 0.24})
for k, (ax, m) in enumerate(zip(axes, order)):
    t, f = agg.get(f"{m}|typed"), agg.get(f"{m}|free")
    for j, c in enumerate(cats):
        tv, fv = t["talk"][c]["mean"], f["talk"][c]["mean"]
        ax.plot([tv, fv], [j, j], color=LIGHT, lw=1.2, zorder=1)
        ax.plot(tv, j, "o", ms=4, color=TYPED, zorder=3); ax.plot(fv, j, "s", ms=4, color=FREE, zorder=3)
    ax.set_xscale("symlog", linthresh=1); ax.set_xlim(0, 400); ax.set_xticks([0, 1, 10, 100]); ax.set_xticklabels(["0", "1", "10", "100"]); ax.set_title(LABELS[m], fontsize=7.5, loc="left", pad=3); ax.set_xlabel("Lines per game")
    letter(ax, "ABCD"[k], dx=-0.08 if k else -0.95, dy=1.06)
axes[0].set_yticks(range(len(cats))); axes[0].set_yticklabels(cats); axes[0].invert_yaxis()
fig.legend(handles=[Line2D([0], [0], marker="o", color=TYPED, lw=0, ms=4, label="Typed arm (text field)"), Line2D([0], [0], marker="s", color=FREE, lw=0, ms=4, label="Free arm")],
           loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.6, 0.0))
save(fig, "fig3_talk_catalogue")
