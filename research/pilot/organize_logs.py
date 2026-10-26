"""Move game logs into logs/<hypothesis>/<experiment>/ folders and keep the
database pointing at them.
  python research/pilot/organize_logs.py [--root <console root>] [--experiments 21,22] [--apply]
Without --apply it prints the plan. Take a backup first (deploy/backup.sh)."""
import argparse, pathlib, sys, json
ap = argparse.ArgumentParser()
ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[2]))
ap.add_argument("--experiments", default="")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
root = pathlib.Path(a.root).resolve()
sys.path.insert(0, str(root))
from arena import db, groups, datafiles   # noqa: E402
con = db.connect()
groups.ensure_hypothesis_groups(con)
ids = [int(x) for x in a.experiments.split(",") if x.strip()] or None
rep = datafiles.organize_logs(con, root, ids, apply=a.apply)
if not a.apply:
    for s in rep["steps"][:12]:
        print(f"  run {s['run']}: {s['status']} {s['from']} -> {s.get('to', '')}")
    if len(rep["steps"]) > 12:
        print(f"  ... {len(rep['steps']) - 12} more")
print(json.dumps({k: v for k, v in rep.items() if k != "steps"}))
print("verify:", json.dumps(datafiles.verify(con, root)))
