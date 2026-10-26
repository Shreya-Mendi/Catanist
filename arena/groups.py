"""Hypothesis groups (2026-10-25): the unit teammates organise by. A group has
member experiments, attached files (write-ups, figures, tables, notes), caps,
and shows spend against them. One group per hypothesis tag is created on
demand; custom groups are allowed."""
from __future__ import annotations

import json
import mimetypes
import re
import time
from pathlib import Path

from .costs import price_key, LIST_PRICES_USD_PER_M

MAX_FILE_BYTES = 25 * 1024 * 1024
TINKER_MODELS = {k for k in LIST_PRICES_USD_PER_M if not k.startswith(("gpt", "o1", "o3", "o4"))}


# the lab's hypotheses, in the order the archive shows them (2026-10-25)
CANONICAL_GROUPS = [
    ("Demo and smoke games", "pilots, smoke tests and explorations; nothing here enters a result"),
    ("H1 instrument (E1)", "the instrument itself: typed vs free on the same boards, extractor and hand labels"),
    ("H2 emergence and contagion (E2, E3)", "baseline violations and their payoff; what a deceptive partner does to the others"),
    ("H3 steerability (E4, E5)", "does an honesty rule hold under pressure and after optimising to win"),
    ("H4 auditor", "can an auditor price trust from the public record"),
    ("H5 scheming", "scheming under the same instrument (design in progress)"),
]
# free-text tags the launch form used before, and names of old groups, to the canonical group
ALIASES = {
    "h0": "Demo and smoke games", "exploratory": "Demo and smoke games", "demo": "Demo and smoke games",
    "h1": "H1 instrument (E1)", "h1 instrument": "H1 instrument (E1)",
    "h2 emergence+contagion": "H2 emergence and contagion (E2, E3)", "h2": "H2 emergence and contagion (E2, E3)",
    "h3 steerability": "H3 steerability (E4, E5)", "h3": "H3 steerability (E4, E5)",
    "h4 auditor": "H4 auditor", "h4": "H4 auditor", "h5 scheming": "H5 scheming", "h5": "H5 scheming",
}


def canonical_name(tag: str | None) -> str | None:
    if not tag:
        return None
    t = tag.strip()
    if any(t == c[0] for c in CANONICAL_GROUPS):
        return t
    return ALIASES.get(t.lower(), t)


def ensure_hypothesis_groups(con) -> None:
    """The canonical groups exist; experiments without a group join the one
    their hypothesis tag maps to (legacy tags through ALIASES)."""
    with con:
        for name, desc in CANONICAL_GROUPS:
            con.execute("INSERT OR IGNORE INTO groups(name,kind,owner,description,created) VALUES(?,?,?,?,?)",
                        (name, "hypothesis", None, desc, time.time()))
        for r in con.execute("SELECT id, hypothesis FROM experiments WHERE group_id IS NULL AND hypothesis IS NOT NULL AND hypothesis!=''").fetchall():
            name = canonical_name(r["hypothesis"])
            g = con.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()
            if not g:
                con.execute("INSERT OR IGNORE INTO groups(name,kind,owner,created) VALUES(?,?,?,?)", (name, "hypothesis", None, time.time()))
                g = con.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()
            con.execute("UPDATE experiments SET group_id=? WHERE id=?", (g["id"], r["id"]))
            con.execute("INSERT OR IGNORE INTO group_members(group_id,experiment_id) VALUES(?,?)", (g["id"], r["id"]))
        for r in con.execute("SELECT id, group_id FROM experiments WHERE group_id IS NOT NULL").fetchall():
            con.execute("INSERT OR IGNORE INTO group_members(group_id,experiment_id) VALUES(?,?)", (r["group_id"], r["id"]))
        # legacy tags on old experiments become the canonical name, and empty
        # hypothesis groups with old names go away (the Run Lab lists only real ones)
        canon = {c[0] for c in CANONICAL_GROUPS}
        for r in con.execute("SELECT id, hypothesis FROM experiments WHERE hypothesis IS NOT NULL").fetchall():
            c = canonical_name(r["hypothesis"])
            if c in canon and c != r["hypothesis"]:
                con.execute("UPDATE experiments SET hypothesis=? WHERE id=?", (c, r["id"]))
        for g in con.execute("SELECT id, name FROM groups WHERE kind='hypothesis'").fetchall():
            if g["name"] not in canon and not con.execute("SELECT 1 FROM group_members WHERE group_id=?", (g["id"],)).fetchone():
                con.execute("DELETE FROM groups WHERE id=?", (g["id"],))


def classify_by_name(name: str, hypothesis: str | None) -> str:
    """Where an experiment belongs, from its name first, then its tag."""
    n = (name or "").lower()
    if any(k in n for k in ("smoke", "test", "watch", "verify", "first real", "wiring", "r1", "trigger", "coaching freeze",
                            "friendly table", "scarcity", "raw-logging", "grid")):
        return "Demo and smoke games"
    if "e1" in n or "typed vs free" in n:
        return "H1 instrument (E1)"
    if "e3" in n or "e2" in n or "contagion" in n or "deceptive" in n:
        return "H2 emergence and contagion (E2, E3)"
    if "e4" in n or "e5" in n or "steer" in n or "honesty" in n:
        return "H3 steerability (E4, E5)"
    if "audit" in n:
        return "H4 auditor"
    if "schem" in n:
        return "H5 scheming"
    return canonical_name(hypothesis) or "Demo and smoke games"


def organize(con, overrides: dict | None = None) -> dict:
    """File every experiment under a canonical hypothesis group (name rules, then
    the explicit id overrides), fold legacy hypothesis groups away, keep custom
    groups untouched. Returns {group name: [experiment ids]}."""
    ensure_hypothesis_groups(con)
    overrides = overrides or {}
    ids = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM groups WHERE kind='hypothesis'")}
    placed = {}
    for r in con.execute("SELECT id, name, hypothesis FROM experiments ORDER BY id").fetchall():
        target = overrides.get(r["id"]) or classify_by_name(r["name"], r["hypothesis"])
        gid = ids[target]
        set_member(con, gid, r["id"], True)
        placed.setdefault(target, []).append(r["id"])
    canon = {c[0] for c in CANONICAL_GROUPS}
    with con:
        for name, gid in ids.items():
            if name not in canon and not con.execute("SELECT 1 FROM group_members WHERE group_id=?", (gid,)).fetchone():
                con.execute("DELETE FROM groups WHERE id=?", (gid,))
    return placed


def _provider_of(config_json: str) -> str:
    try:
        cfg = json.loads(config_json or "{}")
        provs = {p.get("provider") for p in cfg.get("players", [])}
    except Exception:
        provs = set()
    if "openai" in provs:
        return "openai"
    if "tinker" in provs:
        return "tinker"
    return "other"


def spend(con, experiment_ids: list) -> dict:
    out = {"openai": 0.0, "tinker": 0.0, "other": 0.0, "games_done": 0}
    if not experiment_ids:
        return out
    q = ",".join("?" * len(experiment_ids))
    for r in con.execute(f"SELECT config, cost_usd, status FROM runs WHERE experiment_id IN ({q})", experiment_ids):
        if r["cost_usd"]:
            out[_provider_of(r["config"])] += float(r["cost_usd"])
        if r["status"] in ("done", "low_coverage"):
            out["games_done"] += 1
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in out.items()}


def list_groups(con) -> list:
    ensure_hypothesis_groups(con)
    groups = []
    order = {name: i for i, (name, _d) in enumerate(CANONICAL_GROUPS)}
    rows = sorted(con.execute("SELECT * FROM groups").fetchall(),
                  key=lambda g: (0 if g["kind"] == "hypothesis" else 1, order.get(g["name"], 99), g["name"]))
    for g in rows:
        members = [dict(r) for r in con.execute(
            "SELECT e.id, e.name, e.owner, e.hypothesis, e.created, e.budget_usd, "
            "SUM(CASE WHEN r.status='done' THEN 1 ELSE 0 END) done, COUNT(r.id) total, ROUND(SUM(r.cost_usd),2) spend_usd "
            "FROM group_members gm JOIN experiments e ON e.id=gm.experiment_id LEFT JOIN runs r ON r.experiment_id=e.id "
            "WHERE gm.group_id=? GROUP BY e.id ORDER BY e.id", (g["id"],))]
        files = [dict(r) for r in con.execute("SELECT id,name,mime,size,uploader,created FROM group_files WHERE group_id=? ORDER BY name", (g["id"],))]
        notes = [dict(r) for r in con.execute("SELECT author,text,created FROM annotations WHERE experiment_id=? ORDER BY id", (-g["id"],))]
        groups.append({**dict(g), "members": members, "files": files, "notes": notes,
                       "spend": spend(con, [m["id"] for m in members])})
    return groups


def public_view(g: dict) -> dict:
    """The group without money: teammates see members, files and notes; spend
    and caps are for admins (2026-10-25)."""
    out = {k: v for k, v in g.items() if k not in ("spend", "cap_openai", "cap_tinker")}
    out["members"] = [{k: v for k, v in m.items() if k not in ("spend_usd", "budget_usd")} for m in g.get("members", [])]
    return out


def create(con, name: str, owner: str, kind: str = "custom", description: str = "") -> int:
    with con:
        cur = con.execute("INSERT INTO groups(name,kind,owner,description,created) VALUES(?,?,?,?,?)",
                          (name.strip(), kind, owner, description, time.time()))
    return cur.lastrowid


def set_member(con, gid: int, eid: int, add: bool = True) -> None:
    """An experiment has one hypothesis group (experiments.group_id) and may sit
    in any number of custom groups (a paper section, the E1 package). Adding to
    a hypothesis group moves it; adding to a custom group only adds."""
    kind = (con.execute("SELECT kind FROM groups WHERE id=?", (gid,)).fetchone() or {"kind": "custom"})["kind"]
    with con:
        if add:
            if kind == "hypothesis":
                con.execute("DELETE FROM group_members WHERE experiment_id=? AND group_id IN (SELECT id FROM groups WHERE kind='hypothesis')", (eid,))
                con.execute("UPDATE experiments SET group_id=? WHERE id=?", (gid, eid))
            con.execute("INSERT OR IGNORE INTO group_members(group_id,experiment_id) VALUES(?,?)", (gid, eid))
        else:
            con.execute("DELETE FROM group_members WHERE group_id=? AND experiment_id=?", (gid, eid))
            con.execute("UPDATE experiments SET group_id=NULL WHERE id=? AND group_id=?", (eid, gid))


def update(con, gid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("description", "cap_openai", "cap_tinker", "name")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with con:
        con.execute(f"UPDATE groups SET {sets} WHERE id=?", (*allowed.values(), gid))


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip("-.") or "file"
    return n[:120]


def save_file(con, root: Path, gid: int, name: str, data: bytes, uploader: str) -> dict:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"file over {MAX_FILE_BYTES // (1024 * 1024)} MB")
    name = safe_name(name)
    d = root / "logs" / "groups" / str(gid)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    mime = mimetypes.guess_type(name)[0] or ("text/markdown" if name.endswith(".md") else "application/octet-stream")
    with con:
        con.execute("INSERT OR REPLACE INTO group_files(group_id,name,path,mime,size,uploader,created) VALUES(?,?,?,?,?,?,?)",
                    (gid, name, f"logs/groups/{gid}/{name}", mime, len(data), uploader, time.time()))
    return {"name": name, "mime": mime, "size": len(data), "path": f"logs/groups/{gid}/{name}"}


def file_path(con, root: Path, gid: int, name: str):
    r = con.execute("SELECT path, mime FROM group_files WHERE group_id=? AND name=?", (gid, safe_name(name))).fetchone()
    if not r:
        return None, None
    p = root / r["path"]
    return (p if p.exists() else None), r["mime"]
