"""Agreement between two extractors on the same free games, at the statement level.

  python research/pilot/extractor_agreement.py <run_id> [<run_id> ...]
Re-extracts each run with the deployment's current extractor choice (ROOT/.extractor)
into a scratch sidecar and compares with the stored sidecar (whatever model made it):
per statement, the set of checkable acts (claims with resource/has/about, promises,
plans) with and without adjudication. Reports exact agreement on "has any checkable
act", act-set agreement, and Cohen's kappa on the binary "false or broken" verdict.
"""
import sys, json, pathlib, collections
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
from arena.runner import load_env
from arena.extractor import extract_run, extractor_choice
from arena.providers import get_provider
load_env()
pname, pmodel = extractor_choice()
provider = get_provider(pname)
con = db.connect()
def acts(rec):
    out = set()
    for a in rec.get("acts", []):
        if a["type"] == "claim": out.add(("claim", a.get("about") or "self", a["resource"], a["has"]))
        elif a["type"] == "promise": out.add(("promise", a.get("act"), a.get("target"), a.get("resource")))
        elif a["type"] == "plan": out.add(("plan", a.get("do"), a.get("target")))
    return out
def viol(rec):
    return int(any((a["type"] == "claim" and a.get("adjudicated") is False) or
                   (a["type"] in ("promise", "plan") and a.get("adjudicated") == "broken") for a in rec.get("acts", [])))
def kappa(pairs):
    n = len(pairs); po = sum(a == b for a, b in pairs) / n
    pa = collections.Counter(a for a, _ in pairs); pb = collections.Counter(b for _, b in pairs)
    pe = sum(pa[c] * pb[c] for c in set(pa) | set(pb)) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 1.0
tot = collections.Counter(); pairs = []
for rid in map(int, sys.argv[1:]):
    row = con.execute("SELECT log_path FROM runs WHERE id=?", (rid,)).fetchone()
    log = json.loads((ROOT / row["log_path"]).read_text())
    stored = json.loads((ROOT / row["log_path"].replace(".json", "_extracted.json")).read_text())
    fresh = extract_run(log, provider, pmodel)
    A = {r["event_idx"]: r for r in stored["records"]}; B = {r["event_idx"]: r for r in fresh["records"]}
    for i in A.keys() & B.keys():
        a, b = acts(A[i]), acts(B[i])
        tot["statements"] += 1; tot["both_none"] += (not a and not b); tot["any_agree"] += (bool(a) == bool(b)); tot["set_equal"] += (a == b)
        pairs.append((viol(A[i]), viol(B[i])))
    print(f"run {rid}: stored by {stored.get('model')} ({stored.get('version')}), fresh by {pmodel}; {len(A)} statements")
n = tot["statements"]
print(f"statements {n} | agree on 'has a checkable act' {tot['any_agree']/n:.2f} | identical act sets {tot['set_equal']/n:.2f} | both none {tot['both_none']/n:.2f}")
print(f"kappa on the per-statement 'false or broken' verdict: {kappa(pairs):.3f} | violations stored {sum(a for a,_ in pairs)}, fresh {sum(b for _,b in pairs)}")
