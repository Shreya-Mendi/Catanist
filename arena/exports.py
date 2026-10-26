"""Per-statement export (2026-10-25): one row per public line, with the tag,
the engine's reading, the researcher overlay and every label, as CSV. This is
the table an analysis in R or Python starts from."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .ledger import repeat_indices, speaker_of
from .metrics import effective_bound, hands_at_utterance

COLUMNS = ["run_id", "experiment_id", "condition", "seed", "rotation", "arm", "event_idx", "turn", "speaker", "model", "intent",
           "event", "move_outcome", "statement", "tag_type", "tag", "action_bound", "claim_true", "resolution", "posthoc_plan",
           "repeat", "excluded", "overrides", "extractor_acts", "labels", "hand_at_utterance", "vps"]


def _move_outcome(ev, i):
    """For a trade offer: what came of it (accepted and executed, declined, no answer),
    with the bundle; for other moves the engine's own record. E2's 'immediate
    advantage' reads this column next to the statement."""
    e = ev[i]; t = e.get("type")
    if t == "trade_proposal":
        for x in ev[i + 1: i + 8]:
            if x.get("type") == "trade_response" and x.get("responder") == e.get("target"):
                if not x.get("accept"):
                    return f"declined by {e.get('target')}: offered {e.get('give')} for {e.get('want')}"
                for y in ev[i + 1: i + 10]:
                    if y.get("type") == "trade_exec":
                        return f"executed: gave {y.get('give')} got {y.get('want')}"
                return "accepted but not executed"
        return "no answer recorded"
    if t == "trade_response":
        return "accepted" if e.get("accept") else "declined"
    if t == "build":
        return f"built {e.get('kind')}"
    if t == "bank_trade":
        return f"bank: gave {e.get('give')} got {e.get('want')}"
    if t == "robber_move":
        return f"robber to hex {e.get('hex')}" + (f", stole {e.get('stole')} from {e.get('victim')}" if e.get("victim") else "")
    return t or """"""


def statement_rows(con, run_row, log: dict, root: Path) -> list:
    ev = log["events"]
    reps = repeat_indices(ev)
    cfg = json.loads(run_row["config"] or "{}")
    arm = cfg.get("speech_mode", "free")
    models = {p["name"]: p.get("model") for p in ev[0].get("players", [])}
    intents = {p["name"]: p.get("intent") for p in ev[0].get("players", [])}
    fate = {}
    for e in ev:
        if e.get("type") == "promise_resolved":
            fate[("promise", e.get("promise_id"))] = e.get("status")
        elif e.get("type") == "plan_resolved":
            fate[("plan", e.get("plan_id"))] = e.get("status")
    m = json.loads(run_row["metrics"] or "{}")
    posthoc = {p["event_idx"]: p["status"] for p in (m.get("posthoc_plans") or [])}
    ov = {}
    for r in con.execute("SELECT event_idx, field, corrected, author, reason FROM overrides WHERE run_id=? ORDER BY id", (run_row["id"],)):
        ov.setdefault(r["event_idx"], {})[r["field"]] = f"{r['corrected']} ({r['author']}: {r['reason']})"
    labels = {}
    for r in con.execute("SELECT event_idx, labeler, label, reason FROM labels WHERE run_id=?", (run_row["id"],)):
        labels.setdefault(r["event_idx"], []).append(f"{r['labeler']}={r['label']}" + (f" [{r['reason']}]" if r["reason"] else ""))
    xr = {}
    xp = root / str(run_row["log_path"]).replace(".json", "_extracted.json")
    if xp.exists():
        try:
            xr = {r["event_idx"]: r for r in json.loads(xp.read_text()).get("records", [])}
        except Exception:
            xr = {}
    rows = []
    for i, e in enumerate(ev):
        if "parse_ok" not in e or not e.get("public"):
            continue
        who = speaker_of(e)
        sp = e.get("speech") or {}
        res = None
        if sp.get("type") == "promise" and e.get("promise_id"):
            res = fate.get(("promise", e["promise_id"]))
        elif sp.get("type") == "plan" and e.get("plan_id"):
            res = fate.get(("plan", e["plan_id"]))
        acts = ""
        if i in xr:
            acts = "; ".join(f"{a.get('type')}" + (f":{a.get('resource')}" if a.get("resource") else "")
                             + (f"→{a.get('adjudicated')}" if a.get("adjudicated") is not None else "")
                             for a in xr[i].get("acts", []))
        rows.append([run_row["id"], run_row["experiment_id"], run_row["condition"], run_row["seed"], cfg.get("rotation", 0), arm, i, e.get("turn"),
                     who, models.get(who), intents.get(who), e.get("type"), _move_outcome(ev, i), e.get("public"),
                     sp.get("type") or ("free" if arm == "free" else ""),
                     json.dumps({k: v for k, v in sp.items() if k not in ("text", "flavor")}, ensure_ascii=False) if sp else "",
                     effective_bound(e) or "", e.get("claim_true"), res or "", posthoc.get(i, ""),
                     int(i in reps), int(bool(run_row["excluded"])) if "excluded" in run_row.keys() else 0,
                     json.dumps(ov.get(i, {}), ensure_ascii=False) if i in ov else "",
                     acts, " | ".join(labels.get(i, [])),
                     json.dumps(hands_at_utterance(e).get(who, {}), ensure_ascii=False),
                     json.dumps((e.get("stamp") or {}).get("vps", {}), ensure_ascii=False)])
    return rows


def statements_csv(con, run_rows, root: Path) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for r in run_rows:
        if not r["log_path"]:
            continue
        p = root / r["log_path"]
        if not p.exists():
            continue
        log = json.loads(p.read_text())
        w.writerows(statement_rows(con, r, log, root))
    return buf.getvalue()
