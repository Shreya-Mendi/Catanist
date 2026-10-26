"""Seed the E1 package group: the H1 experiments plus the write-up, tables,
figures and notes, attached through the same path the console's upload uses.
  python research/pilot/seed_e1_group.py [--root <console root>] [--experiments 21,22,...]
Files come from this repo's research/e1 and research/research-notes.md (local,
never pushed); they land under <root>/logs/groups/<id>/."""
import sys, pathlib, argparse, json
HERE = pathlib.Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser()
ap.add_argument("--root", default=str(HERE))
ap.add_argument("--experiments", default="21,22,23,24,25,27,28,29,30")
ap.add_argument("--name", default="H1 E1 package: typed vs free")
a = ap.parse_args()
root = pathlib.Path(a.root).resolve()
sys.path.insert(0, str(root))
from arena import db, groups   # noqa: E402  (the target root's code)
con = db.connect()
groups.ensure_hypothesis_groups(con)
g = con.execute("SELECT id FROM groups WHERE name=?", (a.name,)).fetchone()
gid = g["id"] if g else groups.create(con, a.name, "shreya", "custom",
    "Experiment 1, the instrument validation (H1): the same seeds played typed and free on four models; "
    "write-up, tables, figures, results bundle and the research notes.")
for eid in [int(x) for x in a.experiments.split(",") if x.strip()]:
    if con.execute("SELECT 1 FROM experiments WHERE id=?", (eid,)).fetchone():
        groups.set_member(con, gid, eid, True)
src = HERE / "research"
files = [src / "e1" / n for n in ("E1-results.md", "tables.md", "fig1_overview.svg", "fig2_results.png", "fig2_results.svg",
                                  "fig3_talk_catalogue.png", "fig3_talk_catalogue.svg", "results.json", "aggregates.json")]
files += [src / "research-notes.md", src / "battery-v1.md", src / "budget-2026-10-25.md"]
n = 0
for f in files:
    if f.exists():
        groups.save_file(con, root, gid, f.name, f.read_bytes(), "shreya"); n += 1
groups.update(con, gid, cap_openai=500.0, cap_tinker=600.0)
db.log_activity(con, "shreya", "group.seed", f"group:{gid}", f"{n} files attached")
print(f"group {gid} '{a.name}' at {root}: members {a.experiments}, {n} files")
