"""Pilot analysis: mechanics per seed (typed vs free), speech split with the action-bound
split, talk catalogue per arm, extraction summary.  python research/pilot/analyze_pilot.py <exp id>"""
import sys, json, re, collections, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
EID = int(sys.argv[1])
con = db.connect()
rows = con.execute("SELECT id,condition,seed,status,log_path,metrics,error FROM runs WHERE experiment_id=? ORDER BY id", (EID,)).fetchall()
FLAGS = {
 "question/request": lambda s: "?" in s or re.search(r"\banyone\b|\bwho has\b|\bdoes anyone\b|\binterested\b", s, re.I),
 "conditional": lambda s: re.search(r"\bif\b|\bunless\b|\bonly if\b|\bas long as\b|\bprovided\b", s, re.I),
 "about another's hand/needs": lambda s: re.search(r"\b(you|isolde|merlin|roland|vesper)\b[^.!?]*\b(have|has|hold|holding|need|needs|got|leading|ahead)\b", s, re.I),
 "own-hand statement": lambda s: re.search(r"\bi have\b|\bi've got\b|\bi hold\b|\bi'm holding\b|\bi have no\b|\bi don't have\b|\bi'm out of\b|\bno resources\b|\bshort on\b", s, re.I),
 "future commitment": lambda s: re.search(r"\bnext turn\b|\bnext round\b|\blater\b|\bsoon\b|\bi'll (send|give|get) you\b|\bi will (send|give|get) you\b|\bpromise\b|\bwon't rob\b|\bwill not rob\b", s, re.I),
 "robber/block/alliance": lambda s: re.search(r"\brob\b|\bblock\b|\bally\b|\balliance\b|\btogether\b|\bteam up\b", s, re.I),
 "counter-offer wording": lambda s: re.search(r"\binstead\b|\bhow about\b|\bwhat about\b|\bcounter\b|\brather\b", s, re.I),
 "plan announcement": lambda s: re.search(r"\b(building|placing|going for|aiming|expanding|heading|will build|plan to)\b", s, re.I),
}
print(f"{'cond':26} {'seed':>4} {'status':>7} {'dec':>4} {'prop':>4} {'rep':>3} {'acc':>3} {'auto':>4} {'exec':>4} {'bank':>4} {'build':>5} {'resmp':>5} {'vps':>18}  speech / extracted")
talk = collections.defaultdict(list)
for r in rows:
    if r["status"] != "done":
        print(f"{r['condition']:26} {r['seed']:>4} {r['status']:>7}  {(r['error'] or '')[:80]}"); continue
    log = json.loads((ROOT / r["log_path"]).read_text()); ev = log["events"]
    dec = [e for e in ev if "parse_ok" in e]
    props = [e for e in ev if e["type"] == "trade_proposal"]; dup = 0; prev = None
    for e in props:
        key = (e["turn"], e["proposer"], e["target"], json.dumps(e["give"], sort_keys=True), json.dumps(e["want"], sort_keys=True)); dup += key == prev; prev = key
    resp = [e for e in ev if e["type"] == "trade_response"]
    acc = sum(1 for e in resp if e.get("accept")); auto = sum(1 for e in resp if e.get("private") == "(cannot cover the request)")
    m = json.loads(r["metrics"] or "{}")
    if "typed" in r["condition"]:
        sp = collections.Counter((e.get("speech") or {}).get("type") for e in dec if e.get("speech") and e.get("speech_ok", True))
        extra = dict(sp)
        # schema v2: the engine tags action-bound statements; headline promises exclude restated offers
        pr = collections.Counter(e["status"] for e in ev if e["type"] == "promise_resolved" and not e.get("action_bound"))
        if pr: extra["promises"] = dict(pr)
        pl = collections.Counter(e["status"] for e in ev if e["type"] == "plan_resolved")
        if pl: extra["plans"] = dict(pl)
        extra["false claims"] = sum(1 for e in dec if e.get("claim_true") is False and not e.get("action_bound"))
        extra["about others"] = sum(1 for e in dec if (e.get("speech") or {}).get("about"))
        extra["public≠private plan"] = sum(1 for e in dec if e.get("plan_private_match") is False)
        ab = collections.Counter(e.get("action_bound") for e in dec if e.get("action_bound"))
        beyond = sum(1 for e in dec if (e.get("speech") or {}).get("type") in ("claim", "promise", "plan") and e.get("speech_ok", True) and not e.get("action_bound"))
        extra["action-bound"] = dict(ab); extra["beyond-action"] = beyond
        for e in dec:
            if e.get("speech") and e["speech"].get("type") == "announce": talk[r["condition"]].append(e["speech"].get("text", ""))
    else:
        x = m.get("extracted") or {}
        extra = {s: f"c{b['claims']}(f{b['false_claims']}) p{b['promises']}(b{b['broken']}) pl{b.get('plans', 0)}(k{b.get('plans_kept', 0)}/b{b.get('plans_broken', 0)})" for s, b in x.items()} or {"extracted": m.get("extraction_error", "none")}
        extra["public_fail"] = sum(1 for e in dec if e.get("public_ok") is False)
        for e in dec:
            if e.get("public") and e.get("speech") is None: talk[r["condition"]].append(e["public"])
    vps = ",".join(f"{k[:2]}{v}" for k, v in log["vps"].items())
    print(f"{r['condition']:26} {r['seed']:>4} {r['status']:>7} {len(dec):>4} {len(props):>4} {dup:>3} {acc:>3} {auto:>4} {sum(1 for e in ev if e['type']=='trade_exec'):>4} {sum(1 for e in ev if e['type']=='bank_trade'):>4} {sum(1 for e in ev if e['type']=='build' and not e.get('setup')):>5} {sum(1 for e in dec if e.get('resampled')):>5} {vps:>18}  {extra}")
print("\n== talk catalogue (lines per game, mean over the arm's finished games) ==")
conds = sorted(talk)
ngames = {c: sum(1 for r in rows if r['condition'] == c and r['status'] == 'done') for c in conds}
print(f"{'behaviour':28}" + "".join(f"{c[6:]:>26}" for c in conds))
for k, fn in FLAGS.items():
    print(f"{k:28}" + "".join(f"{sum(1 for s in talk[c] if fn(s)) / max(1, ngames[c]):>26.1f}" for c in conds))
print(f"{'distinct / lines':28}" + "".join(f"{len(set(talk[c]))}/{len(talk[c])}".rjust(26) for c in conds))


# == paired comparison per model: free minus typed on trades executed and beyond-action statements ==
import itertools, statistics as st
by = {}
for r in rows:
    if r["status"] != "done": continue
    log = json.loads((ROOT / r["log_path"]).read_text()); ev = log["events"]
    model = r["condition"].split()[0][6:]; arm = "typed" if "typed" in r["condition"] else "free"
    by.setdefault(model, {}).setdefault(r["seed"], {})[arm] = {
        "trades": sum(1 for e in ev if e["type"] == "trade_exec"),
        "max_vp": max(log["vps"].values()) if log.get("vps") else None,
        "finished": log.get("reason") != "turn limit"}
print("\n== paired, per model (free minus typed) ==")
for model, seeds in sorted(by.items()):
    d = [v["free"]["trades"] - v["typed"]["trades"] for v in seeds.values() if "free" in v and "typed" in v]
    if len(d) < 2: print(f"  {model}: {len(d)} complete pair(s)"); continue
    n = len(d); obs = abs(st.mean(d)); cnt = 0
    for signs in itertools.product((1, -1), repeat=n):
        cnt += abs(sum(sg * x for sg, x in zip(signs, d)) / n) >= obs - 1e-9
    fin = sum(1 for v in seeds.values() for a in v.values() if a["finished"]); tot = sum(len(v) for v in seeds.values())
    print(f"  {model}: pairs {n} | trades free-typed mean {st.mean(d):+.1f} sd {st.stdev(d):.1f} | sign-flip p {cnt / 2 ** n:.3f} | games finished {fin}/{tot} | max VP per game {sorted(a['max_vp'] for v in seeds.values() for a in v.values())}")
