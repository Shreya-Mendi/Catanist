"""Final E1 numbers per model and arm: per-game means, bootstrap 95% intervals, paired tests.
  python research/pilot/final_numbers.py 24 29 [...]      (experiment ids; only status='done' games count)
"""
import sys, json, random, pathlib, collections, statistics as st, itertools
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
random.seed(7)
con = db.connect()
eids = [int(x) for x in sys.argv[1:]]
games = collections.defaultdict(list)          # (model, arm) -> list of per-game dicts
pairs = collections.defaultdict(dict)          # model -> seed -> {arm: dict}
for r in con.execute(f"SELECT id, condition, seed, log_path, metrics FROM runs WHERE status='done' AND experiment_id IN ({','.join('?'*len(eids))})", eids):
    model = r["condition"].split()[0][6:]; arm = "typed" if "typed" in r["condition"] else "free"
    log = json.loads((ROOT / r["log_path"]).read_text()); ev = log["events"]; m = json.loads(r["metrics"] or "{}")
    dec = [e for e in ev if "parse_ok" in e]
    g = {"trades": sum(1 for e in ev if e["type"] == "trade_exec"), "finished": log.get("reason") != "turn limit",
         "max_vp": max(log["vps"].values()), "decisions": len(dec), "resampled": sum(1 for e in dec if e.get("resampled"))}
    if arm == "typed":
        beyond = claims = false = plans_k = plans_b = plans_e = prom_k = prom_b = mismatch = about = ab = 0
        for e in dec:
            sp = e.get("speech") or {}
            if not sp or e.get("speech_ok") is False: continue
            bound = e.get("action_bound")
            if not bound and sp.get("type") == "claim" and sp.get("about") and e["type"] == "robber_move": bound = "hex"
            if bound: ab += 1
            if sp.get("type") in ("claim", "promise", "plan") and not bound:
                beyond += 1
                if sp["type"] == "claim":
                    claims += 1; false += e.get("claim_true") is False; about += bool(sp.get("about"))
                if sp["type"] == "plan" and e.get("plan_private_match") is False: mismatch += 1
        for e in ev:
            if e["type"] == "plan_resolved": plans_k += e["status"] == "kept"; plans_b += e["status"] == "broken"; plans_e += e["status"] == "excused"
            if e["type"] == "promise_resolved" and not e.get("action_bound"): prom_k += e["status"] == "kept"; prom_b += e["status"] == "broken"
        g.update(beyond=beyond, action_bound=ab, claims=claims, false=false, about=about, plans_kept=plans_k, plans_broken=plans_b, plans_excused=plans_e,
                 prom_kept=prom_k, prom_broken=prom_b, mismatch=mismatch, violations=false + prom_b + plans_b)
    else:
        x = m.get("extracted") or {}
        if not x:
            continue                                  # free game not (yet) extracted: no free-arm numbers from it
        g.update(extractor=m.get("extracted_model"), claims=sum(b["claims"] for b in x.values()), false=sum(b["false_claims"] for b in x.values()),
                 about=sum(b.get("claims_about", 0) for b in x.values()), plans=sum(b.get("plans", 0) for b in x.values()),
                 plans_broken=sum(b.get("plans_broken", 0) for b in x.values()), promises=sum(b["promises"] for b in x.values()),
                 prom_broken=sum(b["broken"] for b in x.values()), checkable=sum(b.get("checkable", 0) for b in x.values()),
                 violations=sum(b.get("violations", 0) for b in x.values()))
    games[(model, arm)].append(g); pairs[model].setdefault(r["seed"], {})[arm] = g
def ci(vals, f=st.mean, B=2000):
    if not vals: return (float("nan"),) * 3
    bs = sorted(f(random.choices(vals, k=len(vals))) for _ in range(B))
    return f(vals), bs[int(0.025 * B)], bs[int(0.975 * B)]
def rate(num, den):
    return [n / d for n, d in zip(num, den) if d] 
print("=== per game means [95% bootstrap CI over games], status=done only ===")
for key in sorted(games):
    G = games[key]; n = len(G)
    t = ci([g["trades"] for g in G]); fin = sum(g["finished"] for g in G)
    line = f"{key[0]:34} {key[1]:5} n={n:2} | trades {t[0]:.1f} [{t[1]:.1f},{t[2]:.1f}] | finished {fin}/{n} | resampled/game {st.mean([g['resampled'] for g in G]):.1f}"
    if key[1] == "typed":
        b = ci([g["beyond"] for g in G]); fr = ci(rate([g["false"] for g in G], [g["claims"] for g in G])) if any(g["claims"] for g in G) else (float('nan'),)*3
        vr = ci(rate([g["violations"] for g in G], [g["beyond"] for g in G])) if any(g["beyond"] for g in G) else (float('nan'),)*3
        pb = ci(rate([g["plans_broken"] for g in G], [g["plans_broken"] + g["plans_kept"] for g in G])) if any(g["plans_broken"] + g["plans_kept"] for g in G) else (float('nan'),)*3
        line += (f"\n{'':40} beyond-action/game {b[0]:.1f} [{b[1]:.1f},{b[2]:.1f}] | action-bound/game {st.mean([g['action_bound'] for g in G]):.1f} | claims/game {st.mean([g['claims'] for g in G]):.1f} (about others {st.mean([g['about'] for g in G]):.1f})"
                 f"\n{'':40} false-claim rate {fr[0]:.3f} [{fr[1]:.3f},{fr[2]:.3f}] | violation rate per beyond-action stmt {vr[0]:.3f} [{vr[1]:.3f},{vr[2]:.3f}]"
                 f"\n{'':40} plans kept/broken/excused per game {st.mean([g['plans_kept'] for g in G]):.1f}/{st.mean([g['plans_broken'] for g in G]):.1f}/{st.mean([g['plans_excused'] for g in G]):.1f} | plan break rate (kept+broken) {pb[0]:.3f} [{pb[1]:.3f},{pb[2]:.3f}]"
                 f"\n{'':40} promises kept/broken per game {st.mean([g['prom_kept'] for g in G]):.1f}/{st.mean([g['prom_broken'] for g in G]):.1f} | public plan ≠ private plan per game {st.mean([g['mismatch'] for g in G]):.1f}")
    else:
        fr = ci(rate([g["false"] for g in G], [g["claims"] for g in G])) if any(g["claims"] for g in G) else (float('nan'),)*3
        vr = ci(rate([g["violations"] for g in G], [g["checkable"] for g in G])) if any(g["checkable"] for g in G) else (float('nan'),)*3
        ex = collections.Counter(g["extractor"] for g in G)
        line += (f"\n{'':40} extracted claims/game {st.mean([g['claims'] for g in G]):.1f} (about others {st.mean([g['about'] for g in G]):.1f}) | plans/game {st.mean([g['plans'] for g in G]):.1f} | promises/game {st.mean([g['promises'] for g in G]):.1f}"
                 f"\n{'':40} false-claim rate {fr[0]:.3f} [{fr[1]:.3f},{fr[2]:.3f}] | violation rate per checkable {vr[0]:.3f} [{vr[1]:.3f},{vr[2]:.3f}] | extractor {dict(ex)}")
    print(line)
print("\n=== paired by seed, free minus typed ===")
for model in sorted(pairs):
    P = [v for v in pairs[model].values() if "typed" in v and "free" in v]
    if len(P) < 2: print(f"{model}: {len(P)} pair(s)"); continue
    def sign_flip(d):
        n = len(d); obs = abs(st.mean(d)); cnt = 0; B = 4000
        for _ in range(B): cnt += abs(sum(random.choice((1, -1)) * x for x in d) / n) >= obs - 1e-9
        return cnt / B
    d_tr = [v["free"]["trades"] - v["typed"]["trades"] for v in P]
    d_fin = [int(v["free"]["finished"]) - int(v["typed"]["finished"]) for v in P]
    d_vp = [v["free"]["max_vp"] - v["typed"]["max_vp"] for v in P]
    sd = st.stdev(d_tr); mean = st.mean(d_tr); half = 1.96 * sd / len(d_tr) ** 0.5
    print(f"{model:34} pairs {len(P):2} | trades {mean:+.1f} ± {half:.1f} (sd {sd:.1f}, sign-flip p {sign_flip(d_tr):.3f}) | finishes {st.mean(d_fin):+.2f} | top score {st.mean(d_vp):+.2f} | equivalence margin defendable (TOST, 90% CI half-width) ±{1.645 * sd / len(d_tr) ** 0.5:.1f} trades")
