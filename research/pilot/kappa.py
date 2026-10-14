"""Agreement on a label task: Cohen's kappa between two labelers, and each labeler
against the engine's verdict (typed) or the extractor (free).

  python research/pilot/kappa.py <task-name> <labeler1> <labeler2>
Label mapping to a binary "violation" for the engine comparison:
  human: lie -> 1; honest / allowed bluff -> 0; unclear -> excluded
  engine: false claim / promise broken / plan broken -> 1; true claim / kept / declined / excused -> 0; none -> excluded
"""
import sys, json, pathlib, collections
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
task, l1, l2 = sys.argv[1], sys.argv[2], sys.argv[3]
items = json.loads((ROOT / "research" / "exports" / f"labeltask_{task}.json").read_text())["items"]
con = db.connect()
def labels_of(user):
    out = {}
    for it in items:
        row = con.execute("SELECT label, context FROM labels WHERE run_id=? AND event_idx=? AND labeler=?", (it["run_id"], it["event_idx"], user)).fetchone()
        if row:
            out[(it["run_id"], it["event_idx"])] = (row["label"], json.loads(row["context"] or "{}"))
    return out
def kappa(pairs):
    pairs = [p for p in pairs if p[0] is not None and p[1] is not None]
    if not pairs: return None, 0
    n = len(pairs); cats = sorted({x for p in pairs for x in p})
    po = sum(1 for a, b in pairs if a == b) / n
    pa = collections.Counter(a for a, _ in pairs); pb = collections.Counter(b for _, b in pairs)
    pe = sum(pa[c] * pb[c] for c in cats) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, n
A, B = labels_of(l1), labels_of(l2)
both = [(A[k][0], B[k][0]) for k in A if k in B and A[k][0] != "unclear" and B[k][0] != "unclear"]
k, n = kappa(both); print(f"{l1} vs {l2}: kappa {k if k is None else round(k, 3)} on {n} statements (unclear excluded)")
def to_bin_h(l): return None if l == "unclear" else int(l == "lie")
def to_bin_e(v):
    if not v: return None
    v = v.lower()
    if "false" in v or "broken" in v: return 1
    if "true" in v or "kept" in v or "declined" in v or "excused" in v: return 0
    return None
for user, L in ((l1, A), (l2, B)):
    pairs = [(to_bin_h(l), to_bin_e(ctx.get("verdict"))) for l, ctx in L.values()]
    k, n = kappa(pairs); print(f"{user} vs engine verdict: kappa {k if k is None else round(k, 3)} on {n} adjudicable statements")
print("coverage:", {u: len(L) for u, L in ((l1, A), (l2, B))}, "of", len(items))
