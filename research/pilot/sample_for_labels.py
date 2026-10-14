"""Draw a stratified labeling sample across finished runs and save it as a label task.

  python research/pilot/sample_for_labels.py <task-name> --experiments 24,25,28,29,30 --per-cell 25 [--seed 7]

Cells = model x arm x kind, where kind is the speaker's tag type for typed games
(claim / promise / plan / announce) and "free" for free-text lines. Items are
(run_id, event_idx) pairs; the console serves a task through
/api/labelqueue?task=<name> so two labelers see the same statements.
"""
import sys, json, random, argparse, pathlib, collections
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
ap = argparse.ArgumentParser()
ap.add_argument("task"); ap.add_argument("--experiments", required=True); ap.add_argument("--per-cell", type=int, default=25)
ap.add_argument("--seed", type=int, default=7)
a = ap.parse_args()
rng = random.Random(a.seed)
con = db.connect()
eids = [int(x) for x in a.experiments.split(",")]
cells = collections.defaultdict(list)
for r in con.execute(f"SELECT id, condition, log_path FROM runs WHERE status='done' AND experiment_id IN ({','.join('?' * len(eids))})", eids):
    log = json.loads((ROOT / r["log_path"]).read_text())
    model = r["condition"].split()[0][6:] if r["condition"].startswith("model=") else r["condition"]
    arm = "typed" if "typed" in r["condition"] else "free"
    for i, e in enumerate(log["events"]):
        if "parse_ok" not in e or not e.get("public"):
            continue
        sp = e.get("speech")
        kind = "free" if arm == "free" else ((sp or {}).get("type") or "announce")
        if arm == "typed" and e.get("action_bound"):
            kind += "-action-bound"
        cells[(model, arm, kind)].append({"run_id": r["id"], "event_idx": i})
task = []
for key in sorted(cells):
    items = cells[key]; rng.shuffle(items)
    take = items[:a.per_cell]; task += [dict(x, cell="|".join(key)) for x in take]
    print(f"  {key[0]:28} {key[1]:5} {key[2]:22} {len(items):5} available -> {len(take)} sampled")
out = ROOT / "research" / "exports" / f"labeltask_{a.task}.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({"task": a.task, "seed": a.seed, "per_cell": a.per_cell, "items": task}, indent=1))
print(f"task {a.task}: {len(task)} statements -> {out}")
