"""File every experiment under its canonical hypothesis group (2026-10-25):
demo and smoke games, H1 instrument (E1), H2, H3, H4, H5. Name rules first,
then explicit overrides for the box's ids. Custom groups are left alone.
  python research/pilot/organize_groups.py [--root <console root>]"""
import sys, pathlib, argparse
ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[2]))
a = ap.parse_args()
root = pathlib.Path(a.root).resolve(); sys.path.insert(0, str(root))
from arena import db, groups   # noqa: E402
con = db.connect()
# the box database (and its mirror): ids 1-20 are September smokes and pilots; 21-30 are E1;
# 26, 32, 33 are deception_perception's E3 engineering runs; 31 is mid-catanist's E4 pilot
BOX = {**{i: "Demo and smoke games" for i in range(1, 24)}, **{i: "H1 instrument (E1)" for i in (24, 25, 27, 28, 29, 30)},   # 21-23 are pre-schema-v2 pilots
       26: "H2 emergence and contagion (E2, E3)", 32: "H2 emergence and contagion (E2, E3)", 33: "H2 emergence and contagion (E2, E3)",
       31: "H3 steerability (E4, E5)"}
names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM experiments")}
looks_like_box = names.get(24, "").startswith("E1 main") and names.get(33, "").startswith("E3")
placed = groups.organize(con, BOX if looks_like_box else {})
for g, ids in placed.items():
    print(f"{g}: {ids}")
print("legacy groups left:", [r[0] for r in con.execute("SELECT name FROM groups WHERE kind='hypothesis'") if r[0] not in {c[0] for c in groups.CANONICAL_GROUPS}])
