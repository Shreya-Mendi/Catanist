"""Aggregate the E1 bundle (research/e1/results.json) into the write-up tables and a
compact aggregates JSON for the figures.  python research/pilot/e1_tables.py"""
import json, random, statistics as st, collections, pathlib, itertools
random.seed(11)
ROOT = pathlib.Path(__file__).resolve().parents[2]
d = json.load(open(ROOT / "research/e1/results.json"))
G = [g for g in d["games"] if g["status"] == "done"]
SHORT = {"NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16": "Nemotron-3.5-30B", "Qwen3.5-397B-A17B": "Qwen3.5-397B", "Qwen3.8-27B": "Qwen3.8-27B", "gpt-4.1": "gpt-4.1"}
ORDER = ["Qwen3.8-27B", "Nemotron-3.5-30B", "Qwen3.5-397B", "gpt-4.1"]
def ci(vals, B=3000):
    vals = [v for v in vals if v is not None]
    if not vals: return None
    bs = sorted(st.mean(random.choices(vals, k=len(vals))) for _ in range(B))
    return {"mean": st.mean(vals), "lo": bs[int(0.025 * B)], "hi": bs[int(0.975 * B)], "n": len(vals)}
def seatsum(g, k): return sum(s.get(k, 0) for s in g["seats"].values())
def ratio(num, den): return (num / den) if den else None
agg = {}
for model in ORDER:
    for arm in ("typed", "free"):
        gs = [g for g in G if SHORT[g["model"]] == model and g["arm"] == arm]
        if not gs: continue
        a = {"n": len(gs), "trades": ci([g["trades_executed"] for g in gs]), "proposals": ci([g["trades_proposed"] for g in gs]),
             "finished": sum(g["finished_10vp"] for g in gs), "decisions": ci([g["decisions"] for g in gs]),
             "resample_rate": ci([g["resampled"] / g["decisions"] for g in gs]), "coverage_min": ci([g["coverage_min"] for g in gs]),
             "duration_min": ci([g["duration_min"] for g in gs]), "distinct_frac": ci([g["distinct_lines"] / g["lines"] for g in gs if g["lines"]]),
             "talk": {k: ci([g["talk"][k] for g in gs]) for k in gs[0]["talk"]},
             "tokens_in": sum(g["tokens"]["input"] for g in gs), "tokens_out": sum(g["tokens"]["output"] for g in gs)}
        if arm == "typed":
            a.update({"beyond": ci([seatsum(g, "beyond_action") for g in gs]), "action_bound": ci([seatsum(g, "action_bound") for g in gs]),
                      "inverted": ci([seatsum(g, "inverted") for g in gs]),
                      "claims": ci([seatsum(g, "claims") for g in gs]), "claims_about": ci([seatsum(g, "claims_about") for g in gs]),
                      "false_claim_rate": ci([ratio(seatsum(g, "false_claims"), seatsum(g, "claims")) for g in gs]),
                      "plans": ci([seatsum(g, "plans") for g in gs]), "plan_mismatch": ci([seatsum(g, "plan_mismatch") for g in gs]),
                      "plans_kept": ci([seatsum(g, "plans_kept") for g in gs]), "plans_broken": ci([seatsum(g, "plans_broken") for g in gs]),
                      "plans_excused": ci([seatsum(g, "plans_excused") for g in gs]),
                      "plan_break_rate": ci([ratio(seatsum(g, "plans_broken"), seatsum(g, "plans_broken") + seatsum(g, "plans_kept")) for g in gs]),
                      "promises_kept": ci([seatsum(g, "promises_kept") for g in gs]), "promises_broken": ci([seatsum(g, "promises_broken") for g in gs]),
                      "promises_declined": ci([seatsum(g, "promises_declined") for g in gs]), "promises_excused": ci([seatsum(g, "promises_excused") for g in gs]),
                      "offer_promises": ci([seatsum(g, "offer_promises") for g in gs]),
                      "violation_rate": ci([ratio(seatsum(g, "false_claims") + seatsum(g, "promises_broken") + seatsum(g, "plans_broken"), seatsum(g, "beyond_action")) for g in gs])})
        else:
            a.update({"claims": ci([seatsum(g, "x_claims") for g in gs]), "claims_about": ci([seatsum(g, "x_about") for g in gs]),
                      "false_claim_rate": ci([ratio(seatsum(g, "x_false"), seatsum(g, "x_claims")) for g in gs]),
                      "false_about_rate": ci([ratio(seatsum(g, "x_false_about"), seatsum(g, "x_about")) for g in gs]),
                      "plans": ci([seatsum(g, "x_plans") for g in gs]), "plans_broken": ci([seatsum(g, "x_plans_broken") for g in gs]),
                      "promises": ci([seatsum(g, "x_promises") for g in gs]),
                      "violation_rate": ci([ratio(seatsum(g, "x_false") + seatsum(g, "x_plans_broken") + seatsum(g, "x_promises_broken"), seatsum(g, "x_claims") + seatsum(g, "x_plans") + seatsum(g, "x_promises")) for g in gs]),
                      "extractor": collections.Counter(g.get("extractor") for g in gs).most_common(1)[0][0]})
        agg[f"{model}|{arm}"] = a
# paired by seed
pairs = {}
for model in ORDER:
    by = collections.defaultdict(dict)
    for g in G:
        if SHORT[g["model"]] == model: by[g["seed"]][g["arm"]] = g
    P = [v for v in by.values() if "typed" in v and "free" in v]
    if len(P) < 2: continue
    d_tr = [v["free"]["trades_executed"] - v["typed"]["trades_executed"] for v in P]
    d_fin = [int(v["free"]["finished_10vp"]) - int(v["typed"]["finished_10vp"]) for v in P]
    d_vp = [max(v["free"]["vps"].values()) - max(v["typed"]["vps"].values()) for v in P]
    def sf(dd, B=5000):
        n = len(dd); obs = abs(st.mean(dd)); return sum(abs(sum(random.choice((1, -1)) * x for x in dd) / n) >= obs - 1e-9 for _ in range(B)) / B
    sd = st.stdev(d_tr)
    pairs[model] = {"n": len(P), "trades_mean": st.mean(d_tr), "trades_sd": sd, "trades_ci95": 1.96 * sd / len(d_tr) ** 0.5, "trades_p": sf(d_tr),
                    "tost_margin90": 1.645 * sd / len(d_tr) ** 0.5, "finish_mean": st.mean(d_fin), "topvp_mean": st.mean(d_vp), "diffs": d_tr}
# per persona (typed arm, beyond-action claims) and free arm extracted
persona = {}
for model in ORDER:
    for arm in ("typed", "free"):
        gs = [g for g in G if SHORT[g["model"]] == model and g["arm"] == arm]
        for g in gs:
            for name, s in g["seats"].items():
                key = (model, arm, s["persona"]); p = persona.setdefault(key, collections.Counter())
                if arm == "typed":
                    p["claims"] += s["claims"]; p["false"] += s["false_claims"]; p["beyond"] += s["beyond_action"]; p["plans_broken"] += s["plans_broken"]; p["promises_broken"] += s["promises_broken"]; p["vp"] += s["vp"] or 0; p["games"] += 1
                else:
                    p["claims"] += s["x_claims"]; p["false"] += s["x_false"]; p["about"] += s["x_about"]; p["vp"] += s["vp"] or 0; p["games"] += 1
out = {"aggregates": agg, "pairs": pairs, "persona": {"|".join(k): dict(v) for k, v in persona.items()}, "order": ORDER}
(ROOT / "research/e1/aggregates.json").write_text(json.dumps(out, indent=1))
# markdown tables
def f(x, nd=1): return "–" if x is None else f"{x['mean']:.{nd}f} [{x['lo']:.{nd}f}, {x['hi']:.{nd}f}]"
lines = ["## Table 1. Games and mechanics per model and arm (mean [95% bootstrap CI over games])", "",
         "| model | arm | games | trades executed | proposals | finished on 10 VP | decisions | resample rate | min seat coverage |", "|---|---|---|---|---|---|---|---|---|"]
for k, a in agg.items():
    m, arm = k.split("|")
    lines.append(f"| {m} | {arm} | {a['n']} | {f(a['trades'])} | {f(a['proposals'])} | {a['finished']}/{a['n']} | {f(a['decisions'],0)} | {f(a['resample_rate'],3)} | {f(a['coverage_min'],2)} |")
lines += ["", "## Table 2. Paired by seed, free minus typed", "", "| model | pairs | trades (mean ± 95% CI) | sd | sign-flip p | TOST margin at 90% | finishes | top score |", "|---|---|---|---|---|---|---|---|"]
for m, p in pairs.items():
    lines.append(f"| {m} | {p['n']} | {p['trades_mean']:+.1f} ± {p['trades_ci95']:.1f} | {p['trades_sd']:.1f} | {p['trades_p']:.3f} | ±{p['tost_margin90']:.1f} | {p['finish_mean']:+.2f} | {p['topvp_mean']:+.2f} |")
lines += ["", "## Table 3. Typed arm: statements and adjudication per game", "", "| model | games | beyond-action | action-bound (inverted) | claims (about others) | false-claim rate | plans kept / broken / excused | plan break rate | promises kept / broken / declined / excused | offer restatements | public≠private plan | violation rate per beyond-action |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for m in ORDER:
    a = agg.get(f"{m}|typed")
    if not a: continue
    lines.append(f"| {m} | {a['n']} | {f(a['beyond'])} | {a['action_bound']['mean']:.1f} ({a['inverted']['mean']:.1f}) | {a['claims']['mean']:.1f} ({a['claims_about']['mean']:.1f}) | {f(a['false_claim_rate'],2)} | {a['plans_kept']['mean']:.1f} / {a['plans_broken']['mean']:.1f} / {a['plans_excused']['mean']:.1f} | {f(a['plan_break_rate'],2)} | {a['promises_kept']['mean']:.1f} / {a['promises_broken']['mean']:.1f} / {a['promises_declined']['mean']:.1f} / {a['promises_excused']['mean']:.1f} | {a['offer_promises']['mean']:.1f} | {a['plan_mismatch']['mean']:.1f} | {f(a['violation_rate'],2)} |")
lines += ["", "## Table 4. Free arm (extractor gpt-oss-120b, batched; v2.5 readings re-adjudicated under the 2026-10-21 rules): extracted acts per game", "", "| model | games | claims (about others) | false-claim rate | false rate among claims about others | plans (broken) | promises | violation rate per checkable |", "|---|---|---|---|---|---|---|---|"]
for m in ORDER:
    a = agg.get(f"{m}|free")
    if not a: continue
    lines.append(f"| {m} | {a['n']} | {a['claims']['mean']:.1f} ({a['claims_about']['mean']:.1f}) | {f(a['false_claim_rate'],2)} | {f(a['false_about_rate'],2)} | {a['plans']['mean']:.1f} ({a['plans_broken']['mean']:.1f}) | {a['promises']['mean']:.1f} | {f(a['violation_rate'],2)} |")
lines += ["", "## Table 5. Talk catalogue (regex over the public line; typed = the text field), lines per game", "", "| behaviour | " + " | ".join(f"{m} typed / free" for m in ORDER) + " |", "|---|" + "---|" * len(ORDER)]
for k in next(iter(agg.values()))["talk"]:
    lines.append(f"| {k} | " + " | ".join(f"{agg[f'{m}|typed']['talk'][k]['mean']:.1f} / {agg[f'{m}|free']['talk'][k]['mean']:.1f}" if f"{m}|free" in agg else "–" for m in ORDER) + " |")
lines.append("| distinct lines fraction | " + " | ".join(f"{agg[f'{m}|typed']['distinct_frac']['mean']:.2f} / {agg[f'{m}|free']['distinct_frac']['mean']:.2f}" for m in ORDER) + " |")
lines += ["", "## Table 6. By persona (seat intent), typed arm: beyond-action claims and false-claim rate; free arm: extracted claims and false rate", "", "| model | persona | typed claims (false rate) | typed broken plans + promises per game | free claims (false rate), about others | mean VP typed / free |", "|---|---|---|---|---|---|"]
for m in ORDER:
    for per in ("balanced", "diplomatic", "builder", "cautious"):
        t = persona.get((m, "typed", per), {}); fr = persona.get((m, "free", per), {})
        if not t: continue
        lines.append(f"| {m} | {per} | {t['claims']} ({ratio(t['false'], t['claims']) if t['claims'] else 0:.2f}) | {(t['plans_broken'] + t['promises_broken']) / max(1, t['games']):.1f} | {fr.get('claims', 0)} ({ratio(fr.get('false', 0), fr.get('claims', 0)) if fr.get('claims') else 0:.2f}), {fr.get('about', 0)} | {t['vp'] / max(1, t['games']):.1f} / {fr.get('vp', 0) / max(1, fr.get('games', 1)):.1f} |")
(ROOT / "research/e1/tables.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines[:12])); print("..."); print(f"wrote research/e1/tables.md ({len(lines)} lines) and aggregates.json")
