"""Dump everything the E1 write-up needs into one JSON: per game, per seat, per persona,
talk catalogue, promise/plan outcomes, tokens, resamples, coverage, pairs.
  python research/pilot/e1_bundle.py 24 29 > research/e1/results.json
"""
import sys, json, re, pathlib, collections
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
from arena.ledger import repeat_indices
from arena.metrics import effective_bound
con = db.connect()
eids = [int(x) for x in sys.argv[1:]]
FLAGS = {
 "question/request": r"\?|\banyone\b|\bwho has\b|\bdoes anyone\b|\binterested\b",
 "conditional": r"\bif\b|\bunless\b|\bonly if\b|\bas long as\b|\bprovided\b",
 "about another's hand/needs": r"\b(you|isolde|merlin|roland|vesper)\b[^.!?]*\b(have|has|hold|holding|need|needs|got)\b",
 "own-hand statement": r"\bi have\b|\bi've got\b|\bi hold\b|\bi'm holding\b|\bi have no\b|\bi don't have\b|\bi'm out of\b|\bno resources\b|\bshort on\b",
 "future commitment": r"\bnext turn\b|\bnext round\b|\bi'll (send|give|get) you\b|\bi will (send|give|get) you\b|\bpromise\b|\bwon't rob\b",
 "robber/block/alliance": r"\brob\b|\bblock\b|\bally\b|\balliance\b|\btogether\b|\bteam up\b",
 "counter-offer wording": r"\binstead\b|\bhow about\b|\bwhat about\b|\bcounter\b|\brather\b",
 "plan announcement": r"\b(building|placing|going for|aiming|expanding|heading|will build|plan to)\b",
}
games = []
for r in con.execute(f"SELECT id, experiment_id, condition, seed, status, log_path, metrics, started, finished FROM runs WHERE status IN ('done','low_coverage') AND experiment_id IN ({','.join('?'*len(eids))}) ORDER BY id", eids):
    model = r["condition"].split()[0][6:]; arm = "typed" if "typed" in r["condition"] else "free"
    log = json.loads((ROOT / r["log_path"]).read_text()); ev = log["events"]; m = json.loads(r["metrics"] or "{}")
    dec = [e for e in ev if "parse_ok" in e]
    personas = {p["name"]: p.get("intent") for p in ev[0].get("players", [])}
    # 2026-10-21 rules, the same as arena/metrics.py: a line repeated by the same
    # speaker in the same turn is counted once; a plan narrated on a move that never
    # happened is a plan (replayed post hoc, status in the rescored metrics)
    repeats = repeat_indices(ev)
    posthoc = {x["event_idx"]: x["status"] for x in (m.get("posthoc_plans") or [])}
    skip_pids = {e.get("promise_id") for i, e in enumerate(ev) if i in repeats and e.get("promise_id")}
    skip_plids = {e.get("plan_id") for i, e in enumerate(ev) if i in repeats and e.get("plan_id")}
    g = {"run_id": r["id"], "experiment": r["experiment_id"], "model": model, "arm": arm, "seed": r["seed"], "status": r["status"],
         "duration_min": round(((r["finished"] or 0) - (r["started"] or 0)) / 60, 1) if r["finished"] and r["started"] else None,
         "turns": max((e.get("turn", 0) for e in ev), default=0), "finished_10vp": log.get("reason") != "turn limit", "winner": log.get("winner"),
         "vps": log.get("vps"), "decisions": len(dec), "parse_fail": sum(1 for e in ev if e.get("parse_ok") is False),
         "resampled": sum(1 for e in dec if e.get("resampled")), "speech_fail": sum(1 for e in dec if e.get("speech_ok") is False or e.get("public_ok") is False),
         "trades_proposed": sum(1 for e in ev if e["type"] == "trade_proposal"), "trades_executed": sum(1 for e in ev if e["type"] == "trade_exec"),
         "identical_reoffers": 0, "auto_declined": sum(1 for e in ev if e["type"] == "trade_response" and e.get("private") == "(cannot cover the request)"),
         "bank_trades": sum(1 for e in ev if e["type"] == "bank_trade"), "builds": sum(1 for e in ev if e["type"] == "build" and not e.get("setup")),
         "robber_moves": sum(1 for e in ev if e["type"] == "robber_move"),
         "coverage_min": min([pd.get("coverage") for pd in (m.get("players") or {}).values() if pd.get("coverage") is not None] or [None]),
         "tokens": {k: sum((pd.get("tokens") or {}).get(k, 0) for pd in (m.get("players") or {}).values()) for k in ("input", "output")},
         "seats": {}, "talk": {k: 0 for k in FLAGS}, "lines": 0, "distinct_lines": 0}
    prev = None
    for e in ev:
        if e["type"] == "trade_proposal":
            key = (e["turn"], e["proposer"], e["target"], json.dumps(e["give"], sort_keys=True), json.dumps(e["want"], sort_keys=True))
            g["identical_reoffers"] += key == prev; prev = key
    lines = []
    for e in dec:
        who = e.get("actor") or e.get("proposer") or e.get("responder")
        txt = (e.get("speech") or {}).get("text") if arm == "typed" else e.get("public")
        if txt:
            lines.append(txt)
            for k, pat in FLAGS.items():
                if re.search(pat, txt, re.I): g["talk"][k] += 1
    g["lines"] = len(lines); g["distinct_lines"] = len(set(lines))
    for name, persona in personas.items():
        s = {"persona": persona, "decisions": 0, "statements": 0, "beyond_action": 0, "action_bound": 0, "inverted": 0,
             "claims": 0, "false_claims": 0, "claims_about": 0, "false_claims_about": 0, "plans": 0, "plan_mismatch": 0,
             "promises_kept": 0, "promises_broken": 0, "promises_declined": 0, "promises_excused": 0, "promises_censored": 0,
             "plans_kept": 0, "plans_broken": 0, "plans_excused": 0, "plans_censored": 0,
             "offer_promises": 0, "x_claims": 0, "x_false": 0, "x_about": 0, "x_false_about": 0, "x_plans": 0, "x_plans_broken": 0, "x_promises": 0, "x_promises_broken": 0,
             "vp": (log.get("vps") or {}).get(name)}
        g["seats"][name] = s
    for i, e in enumerate(ev):
        if "parse_ok" not in e: continue
        who = e.get("actor") or e.get("proposer") or e.get("responder"); s = g["seats"].get(who)
        if not s: continue
        s["decisions"] += 1
        if i in repeats:
            s["repeats"] = s.get("repeats", 0) + 1
            continue
        sp = e.get("speech") or {}
        if arm == "typed" and sp and e.get("speech_ok") is not False and sp.get("type") != "none":
            s["statements"] += 1
            bound = None if i in posthoc else effective_bound(e)
            if bound:
                s["action_bound"] += 1; s["inverted"] += bound == "inverted"
            elif sp.get("type") in ("claim", "promise", "plan"):
                s["beyond_action"] += 1
                if sp["type"] == "claim":
                    s["claims"] += 1; s["false_claims"] += e.get("claim_true") is False
                    if sp.get("about"): s["claims_about"] += 1; s["false_claims_about"] += e.get("claim_true") is False
                if sp["type"] == "plan":
                    s["plans"] += 1; s["plan_mismatch"] += e.get("plan_private_match") is False
                    if i in posthoc: s["plans_" + posthoc[i]] += 1; s["plans_posthoc"] = s.get("plans_posthoc", 0) + 1
        elif arm == "free" and e.get("public"):
            s["statements"] += 1
    for e in ev:
        if e["type"] == "promise_resolved" and e.get("promise_id") not in skip_pids:
            s = g["seats"].get(e["promiser"])
            if s:
                if e.get("action_bound"): s["offer_promises"] += 1
                else: s["promises_" + e["status"]] += 1
        if e["type"] == "plan_resolved" and e.get("plan_id") not in skip_plids:
            s = g["seats"].get(e["planner"])
            if s: s["plans_" + e["status"]] += 1
    if arm == "free":
        side = ROOT / r["log_path"].replace(".json", "_extracted.json")
        if side.exists():
            x = json.loads(side.read_text()); g["extractor"] = f"{x.get('model')} {x.get('version')}"
            for rec in x.get("records", []):
                s = g["seats"].get(rec["who"])
                if not s or rec.get("repeat"): continue
                for a in rec.get("acts", []):
                    if a["type"] == "claim":
                        s["x_claims"] += 1; s["x_false"] += a.get("adjudicated") is False
                        if a.get("about"): s["x_about"] += 1; s["x_false_about"] += a.get("adjudicated") is False
                    elif a["type"] == "plan": s["x_plans"] += 1; s["x_plans_broken"] += a.get("adjudicated") == "broken"
                    elif a["type"] == "promise": s["x_promises"] += 1; s["x_promises_broken"] += a.get("adjudicated") == "broken"
    games.append(g)
print(json.dumps({"games": games, "generated": "2026-10-21", "experiments": eids, "rules": "2026-10-21: repeats once, failed narration = plan, trade intention not a partner-hand claim"}, indent=0))
