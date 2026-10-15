"""E1 result figures from research/e1/aggregates.json -> research/e1/fig_*.svg|png"""
import json, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = pathlib.Path(__file__).resolve().parents[2]; OUT = ROOT / "research/e1"
A = json.load(open(OUT / "aggregates.json")); agg, pairs, order = A["aggregates"], A["pairs"], A["order"]
TYPED, FREE, KEPT, BROKEN, NEUTRAL, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#b9b8b2", "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK, "svg.fonttype": "none"})
def save(fig, name):
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight"); fig.savefig(OUT / f"{name}.png", dpi=220, bbox_inches="tight"); plt.close(fig); print("wrote", name)
def dot_ci(ax, y, c, color, label=None, marker="o"):
    ax.plot([c["lo"], c["hi"]], [y, y], color=color, lw=2, solid_capstyle="round", zorder=2)
    ax.plot([c["mean"]], [y], marker=marker, ms=7, color=color, mec="white", mew=1.5, zorder=3, label=label, ls="none")
ylab = [m for m in order]
# --- Figure A: claims per game and false-claim rate, typed vs free ---
fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.0), gridspec_kw={"wspace": 0.45})
for ax, key, title, xlab in ((axes[0], "claims", "Explicit hand claims per game", "claims per game (beyond the move)"),
                             (axes[1], "false_claim_rate", "False-claim rate", "share of hand claims that are false")):
    for i, m in enumerate(order):
        t, f = agg.get(f"{m}|typed"), agg.get(f"{m}|free")
        if t and t.get(key): dot_ci(ax, i + 0.16, t[key], TYPED, "typed (speaker's own tag)" if i == 0 else None)
        if f and f.get(key): dot_ci(ax, i - 0.16, f[key], FREE, "free text (extractor)" if i == 0 else None, marker="s")
    ax.set_yticks(range(len(order))); ax.set_yticklabels(ylab, color=INK); ax.set_ylim(-0.6, len(order) - 0.4); ax.invert_yaxis()
    ax.set_xlabel(xlab); ax.set_title(title, loc="left"); ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    if key == "false_claim_rate": ax.set_xlim(0, 0.6)
    else: ax.set_xlim(0, None)
axes[0].legend(frameon=False, loc="lower right", fontsize=8)
fig.text(0.0, -0.08, "Mean over games with 95% bootstrap intervals. Nemotron's typed tags are largely invalid (see text); gpt-4.1 free arm n=10, Qwen3.5-397B n=13.", color=MUTED, fontsize=7.5)
save(fig, "fig_claims_false_rates")
# --- Figure B: paired trade difference per model ---
fig, ax = plt.subplots(figsize=(5.4, 2.6))
for i, m in enumerate(order):
    p = pairs.get(m)
    if not p: continue
    ax.plot([p["trades_mean"] - p["trades_ci95"], p["trades_mean"] + p["trades_ci95"]], [i, i], color=TYPED, lw=2, solid_capstyle="round", zorder=2)
    ax.plot([p["trades_mean"]], [i], "o", ms=7, color=TYPED, mec="white", mew=1.5, zorder=3)
    ax.text(p["trades_mean"] + p["trades_ci95"] + 0.8, i, f"n={p['n']}  p={p['trades_p']:.2f}", va="center", fontsize=7.5, color=MUTED)
ax.axvline(0, color=INK, lw=1); ax.axvspan(-3.5, 3.5, color=NEUTRAL, alpha=0.18, lw=0, zorder=0)
ax.set_yticks(range(len(order))); ax.set_yticklabels(ylab, color=INK); ax.invert_yaxis(); ax.set_ylim(len(order) - 0.4, -0.6)
ax.set_xlabel("trades executed, free minus typed, same seed (mean ± 95% CI)"); ax.set_title("The format does not change the game", loc="left")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True); ax.set_xlim(-16, 16)
ax.text(3.7, len(order) - 0.55, "±3.5 trades: margin defendable at 30 pairs", fontsize=7.5, color=MUTED, va="bottom")
save(fig, "fig_paired_trades")
# --- Figure C: plan outcomes per typed game (stacked, with gaps) and public/private mismatch ---
fig, ax = plt.subplots(figsize=(5.6, 2.6))
for i, m in enumerate(order):
    t = agg.get(f"{m}|typed")
    if not t: continue
    left = 0
    for key, col, lab in (("plans_kept", KEPT, "kept"), ("plans_broken", BROKEN, "broken"), ("plans_excused", NEUTRAL, "excused (never legal)")):
        v = t[key]["mean"]
        ax.barh(i, v, left=left, height=0.5, color=col, edgecolor="white", linewidth=2, label=lab if i == 0 else None)
        left += v
    ax.text(left + 0.15, i, f"{t['plan_mismatch']['mean']:.1f} contradict the private plan", va="center", fontsize=7.5, color=MUTED)
ax.set_yticks(range(len(order))); ax.set_yticklabels(ylab, color=INK); ax.invert_yaxis()
ax.set_xlabel("announced plans per typed game"); ax.set_title("Announced plans: mostly excused or broken, rarely contradicted privately", loc="left")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True); ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=3); ax.set_xlim(0, 16)
save(fig, "fig_plan_outcomes")
# --- Figure D: talk catalogue, typed vs free, small multiples ---
cats = list(next(iter(agg.values()))["talk"].keys())
fig, axes = plt.subplots(1, len(order), figsize=(10.5, 3.2), sharey=True, gridspec_kw={"wspace": 0.12})
for ax, m in zip(axes, order):
    t, f = agg.get(f"{m}|typed"), agg.get(f"{m}|free")
    for j, c in enumerate(cats):
        if t: ax.plot(t["talk"][c]["mean"], j, "o", ms=6, color=TYPED, mec="white", mew=1.2, zorder=3)
        if f: ax.plot(f["talk"][c]["mean"], j, "s", ms=6, color=FREE, mec="white", mew=1.2, zorder=3)
        if t and f: ax.plot([t["talk"][c]["mean"], f["talk"][c]["mean"]], [j, j], color=NEUTRAL, lw=1.5, zorder=2)
    ax.set_title(m, loc="left", fontsize=9); ax.set_xscale("symlog", linthresh=5); ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    ax.set_xlabel("lines per game (symlog)")
axes[0].set_yticks(range(len(cats))); axes[0].set_yticklabels(cats, color=INK); axes[0].invert_yaxis()
axes[0].plot([], [], "o", color=TYPED, label="typed (text field)"); axes[0].plot([], [], "s", color=FREE, label="free text"); fig.legend(frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=2)
fig.suptitle("What gets said: the same catalogue in both arms within a model", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
save(fig, "fig_talk_catalogue")
# --- Figure E: checkable content per typed game, action-bound vs beyond-action ---
fig, ax = plt.subplots(figsize=(5.6, 2.4))
for i, m in enumerate(order):
    t = agg.get(f"{m}|typed")
    if not t: continue
    ax.barh(i, t["action_bound"]["mean"], height=0.5, color=NEUTRAL, edgecolor="white", linewidth=2, label="action-bound (restates the move)" if i == 0 else None)
    ax.barh(i, t["beyond"]["mean"], left=t["action_bound"]["mean"], height=0.5, color=TYPED, edgecolor="white", linewidth=2, label="beyond the move (scored)" if i == 0 else None)
    ax.text(t["action_bound"]["mean"] + t["beyond"]["mean"] + 1.5, i, f"{t['beyond']['mean']:.0f} scored", va="center", fontsize=7.5, color=MUTED)
ax.set_yticks(range(len(order))); ax.set_yticklabels(ylab, color=INK); ax.invert_yaxis(); ax.set_xlabel("tagged statements per typed game"); ax.set_title("Tags per game: most restate the move; the rest are scored", loc="left")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True); ax.legend(frameon=False, fontsize=8, loc="lower right")
save(fig, "fig_tags_split")
