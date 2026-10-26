"""Researcher overrides (2026-10-25): an overlay on the engine's reading of a
statement. The log and the model's own tag are never rewritten; an override
records who changed which reading, from what to what, and why. Metrics are
reported raw and corrected side by side (runs.metrics vs runs.metrics_corrected).

Fields a researcher can set per (run, event):
  kind          claim | promise | plan | announce | chatter   (what the line counts as)
  verdict       true | false | kept | broken | excused | not-checkable
  action_bound  yes | no                                      (restates the live move?)
  exclude       yes | no                                      (drop the statement from scoring)
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

FIELDS = {
    "kind": ["claim", "promise", "plan", "announce", "chatter"],
    "verdict": ["true", "false", "kept", "broken", "excused", "not-checkable"],
    "action_bound": ["yes", "no"],
    "exclude": ["yes", "no"],
}


def validate(field: str, value: str) -> str | None:
    if field not in FIELDS:
        return f"unknown field {field!r}; one of {list(FIELDS)}"
    if value not in FIELDS[field]:
        return f"{field} must be one of {FIELDS[field]}"
    return None


def save(con, run_id: int, event_idx: int, field: str, corrected: str, original, reason: str, author: str) -> int:
    with con:
        cur = con.execute(
            "INSERT INTO overrides(run_id,event_idx,field,original,corrected,reason,author,created) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (run_id, event_idx, field, json.dumps(original, default=str) if original is not None else None,
             corrected, reason or "", author, time.time()))
    return cur.lastrowid


def latest(con, run_id: int) -> dict:
    """{(event_idx, field): row} with the most recent override winning."""
    out = {}
    for r in con.execute("SELECT * FROM overrides WHERE run_id=? ORDER BY id", (run_id,)):
        out[(r["event_idx"], r["field"])] = dict(r)
    return out


def by_event(con, run_id: int) -> dict:
    """{event_idx: [override rows]} for display."""
    out = {}
    for (idx, _f), row in latest(con, run_id).items():
        out.setdefault(idx, []).append(row)
    return out


def apply_to_events(events: list, ov: dict) -> list:
    """A copy of the events with the overrides applied, ready for game_metrics."""
    ev = copy.deepcopy(events)
    res_by_pid = {}
    res_by_plid = {}
    for e in ev:
        if e.get("type") == "promise_resolved":
            res_by_pid[e.get("promise_id")] = e
        elif e.get("type") == "plan_resolved":
            res_by_plid[e.get("plan_id")] = e
    for (idx, field), row in ov.items():
        if not (0 <= idx < len(ev)):
            continue
        e = ev[idx]
        v = row["corrected"]
        if field == "exclude":
            e["excluded"] = (v == "yes")
        elif field == "action_bound":
            e["ab_override"] = True
            e["action_bound"] = "researcher" if v == "yes" else None
        elif field == "kind":
            sp = dict(e.get("speech") or {})
            if v == "chatter":
                e["speech"] = {**sp, "type": "none"}
                e.pop("claim_true", None)
            else:
                e["speech"] = {**sp, "type": v}
                if v != "claim":
                    e.pop("claim_true", None)
        elif field == "verdict":
            if v in ("true", "false"):
                e["claim_true"] = (v == "true")
            elif v == "not-checkable":
                e["excluded"] = True
            else:                                   # kept / broken / excused: the resolution event
                for key, table in ((e.get("promise_id"), res_by_pid), (e.get("plan_id"), res_by_plid)):
                    if key is not None and key in table:
                        table[key]["status"] = v
    return ev


def apply_to_records(records: list, ov: dict, verdicts_only: bool = False) -> list:
    """The free arm: overrides on the extractor's records. Called twice by
    corrected_metrics: structure before re-adjudication, verdicts after."""
    recs = copy.deepcopy(records)
    by_idx = {r["event_idx"]: r for r in recs}
    for (idx, field), row in ov.items():
        rec = by_idx.get(idx)
        if rec is None:
            continue
        v = row["corrected"]
        acts = rec.get("acts") or []
        if verdicts_only:
            if field == "verdict" and acts:
                if v in ("true", "false"):
                    acts[0]["adjudicated"] = (v == "true")
                elif v in ("kept", "broken", "excused"):
                    acts[0]["adjudicated"] = v
                elif v == "not-checkable":
                    rec["excluded"] = True
            continue
        if field == "exclude":
            rec["excluded"] = (v == "yes")
        elif field == "action_bound":
            if v == "yes":
                rec.setdefault("dropped", []).extend({**a, "reason": "researcher"} for a in acts
                                                      if a.get("type") in ("claim", "promise", "plan"))
                rec["acts"] = [a for a in acts if a.get("type") not in ("claim", "promise", "plan")] or [{"type": "announce", "text": rec.get("statement", "")[:120]}]
        elif field == "kind":
            if v == "chatter":
                rec["acts"] = [{"type": "other", "text": rec.get("statement", "")[:120]}]
            elif v == "announce":
                rec["acts"] = [{"type": "announce", "text": rec.get("statement", "")[:120]}]
            elif acts:
                acts[0]["type"] = v
            else:
                rec["acts"] = [{"type": v, "text": rec.get("statement", "")[:160]}]
    return recs


def corrected_metrics(con, run_row, log: dict, log_path: Path) -> dict:
    """Raw metrics recomputed with the run's overrides applied."""
    from .metrics import game_metrics
    ov = latest(con, run_row["id"])
    m = game_metrics({**log, "events": apply_to_events(log["events"], ov)})
    xp = Path(log_path).with_name(Path(log_path).stem + "_extracted.json")
    if xp.exists():
        from .extractor import rescore_records, per_seat, apply_verdict_overrides_hint  # noqa: F401
        x = json.loads(xp.read_text())
        recs = apply_to_records(x.get("records", []), ov)
        out = rescore_records(log, recs, x.get("model"))
        recs2 = apply_to_records(out["records"], ov, verdicts_only=True)
        m["extracted"] = per_seat(recs2, out.get("own_turns") or {})
        m["extracted_model"] = x.get("model"); m["extracted_version"] = f"{x.get('version')}+overrides"
    m["overrides"] = len(ov)
    return m


def recompute(con, run_id: int, root: Path) -> dict | None:
    row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row or not row["log_path"]:
        return None
    log = json.loads((root / row["log_path"]).read_text())
    m = corrected_metrics(con, row, log, root / row["log_path"])
    with con:
        con.execute("UPDATE runs SET metrics_corrected=? WHERE id=?", (json.dumps(m), run_id))
    return m
