"""Where a game's files live (2026-10-25): logs/<hypothesis>/<experiment>/.

    logs/H1-instrument-E1/exp24-E1-main-typed-vs-free-30-seeds-schema-v2/<game>.json
    logs/H1-instrument-E1/exp24-.../<game>_extracted.json, <game>_scene.html
    logs/unfiled/                       games with no experiment (legacy CLI runs)
    logs/groups/<id>/                   files attached to a hypothesis page

The database's runs.log_path is the path relative to the repo root, so every
reader (console, rescore, bundle) follows the move. `organize_logs` moves
existing flat files into this layout, one run at a time, updating the row only
after the files are in place; a dry run reports the plan without touching
anything."""
from __future__ import annotations

import os
import re
from pathlib import Path


def slug(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-")
    return (s[:limit].rstrip("-")) or "x"


def hypothesis_folder(group_name: str | None) -> str:
    if not group_name:
        return "unfiled"
    return slug(group_name.replace("(", "").replace(")", "").replace(",", ""), 40)


def subdir_for(con, run_id: int) -> str:
    """logs/<hypothesis>/<experiment> for a run, from its experiment's hypothesis group."""
    row = con.execute(
        "SELECT r.experiment_id, e.name, g.name gname FROM runs r "
        "LEFT JOIN experiments e ON e.id=r.experiment_id LEFT JOIN groups g ON g.id=e.group_id WHERE r.id=?",
        (run_id,)).fetchone()
    if not row or row["experiment_id"] is None:
        return "unfiled"
    return f"{hypothesis_folder(row['gname'])}/exp{row['experiment_id']}-{slug(row['name'])}"


def siblings(path: Path) -> list[Path]:
    """The game log and the files kept beside it (extraction, replay scene)."""
    out = [path]
    for suffix in ("_extracted.json", "_scene.html"):
        s = path.with_name(path.stem + suffix)
        if s.exists():
            out.append(s)
    return out


def plan(con, root: Path, experiment_ids: list | None = None) -> list[dict]:
    """What organize_logs would do: one entry per run whose log is not yet in
    its folder."""
    q = "SELECT id, experiment_id, log_path FROM runs WHERE log_path IS NOT NULL"
    args = ()
    if experiment_ids:
        q += f" AND experiment_id IN ({','.join('?' * len(experiment_ids))})"
        args = tuple(experiment_ids)
    out = []
    for r in con.execute(q + " ORDER BY id", args):
        src = root / r["log_path"]
        if not src.exists():
            out.append({"run": r["id"], "status": "missing", "from": r["log_path"]})
            continue
        sub = subdir_for(con, r["id"])
        target_dir = root / "logs" / sub
        if src.parent.resolve() == target_dir.resolve():
            continue
        out.append({"run": r["id"], "status": "move", "from": r["log_path"],
                    "to": f"logs/{sub}/{src.name}", "files": [p.name for p in siblings(src)]})
    return out


def organize_logs(con, root: Path, experiment_ids: list | None = None, apply: bool = False) -> dict:
    """Move each run's files into logs/<hypothesis>/<experiment>/ and update
    runs.log_path. Same filesystem, atomic renames, row updated after the files
    moved; a failure moves the files back and leaves the row as it was."""
    steps = plan(con, root, experiment_ids)
    report = {"planned": sum(1 for s in steps if s["status"] == "move"), "missing": [s["run"] for s in steps if s["status"] == "missing"],
              "moved": 0, "failed": [], "apply": apply}
    if not apply:
        report["steps"] = steps
        return report
    for s in steps:
        if s["status"] != "move":
            continue
        src = root / s["from"]
        dst_dir = root / Path(s["to"]).parent
        dst_dir.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for f in siblings(src):
                d = dst_dir / f.name
                if d.exists():
                    raise FileExistsError(str(d))
                os.replace(f, d)
                moved.append((f, d))
            with con:
                con.execute("UPDATE runs SET log_path=? WHERE id=?", (s["to"], s["run"]))
            report["moved"] += 1
        except Exception as e:
            for f, d in reversed(moved):
                try:
                    os.replace(d, f)
                except Exception:
                    pass
            report["failed"].append({"run": s["run"], "error": f"{type(e).__name__}: {e}"})
    return report


def verify(con, root: Path) -> dict:
    """Every run's log_path points at a file; counts by top folder."""
    by = {}
    missing = []
    for r in con.execute("SELECT id, log_path FROM runs WHERE log_path IS NOT NULL"):
        p = root / r["log_path"]
        top = Path(r["log_path"]).parts[1] if len(Path(r["log_path"]).parts) > 2 else "(flat)"
        by[top] = by.get(top, 0) + 1
        if not p.exists():
            missing.append(r["id"])
    return {"by_folder": by, "missing": missing}
