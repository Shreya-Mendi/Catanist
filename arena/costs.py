"""Cost model (2026-10-24): what a batch will cost before it runs, and what a
game cost after it ran.

Profiles come from the token ledger in the stored metrics: real usage where the
provider reported it, else tokens estimated from the stored prompts and replies
at four characters per token (`tokens.estimated_decisions` says how many). The
launch form once priced every call at a flat $0.0006, which said $0.31 for a
game that costs $6; this module replaces that with measured tokens per call and
calls per turn for the model in question, list price per million tokens.
Models without a list price (open models on Tinker) are reported in tokens."""
from __future__ import annotations

import json
from collections import defaultdict

# (input, output) per million tokens. OpenAI: developers.openai.com/api/docs/pricing,
# Tinker: thinkingmachines.ai/tinker/pricing (prefill as input, sample as output); read 2026-10-25.
LIST_PRICES_USD_PER_M = {
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6), "gpt-4.1-nano": (0.1, 0.4),
    "gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6),
    "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0), "gpt-5-nano": (0.05, 0.4), "gpt-5.1": (1.25, 10.0),
    "gpt-5.2": (1.75, 14.0), "gpt-5.4": (2.5, 15.0), "gpt-5.4-mini": (0.75, 4.5), "gpt-5.5": (5.0, 30.0),
    "gpt-5.6-sol": (4.0, 20.0), "gpt-6-astra": (10.0, 50.0), "gpt-6-sol": (2.0, 10.0), "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-luna": (0.1, 0.5),
    # Tinker open models (64K rows): prefill / sample
    "Qwen3.8-27B": (0.6975, 5.595), "NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16": (0.184, 0.495),
    "Qwen3.5-397B-A17B": (1.65, 7.5), "gpt-oss-120b": (0.33, 0.84), "Qwen3.6-35B-A3B": (0.45, 1.335),
    "Qwen3-8B": (0.195, 0.6), "GPT-OSS-20B": (0.18, 0.45),
}
# OpenAI deprecations page, read 2026-10-25: a study cannot run past these dates on these models
SHUTDOWN = {"gpt-5": "2026-12-11", "gpt-5-mini": "2026-12-11", "gpt-5-nano": "2026-12-11",
            "gpt-5.1": "2027-04-01", "gpt-4.1": "2027-01-14", "gpt-4.1-mini": "2027-01-14"}
# measured on E1 with the o200k tokenizer (research/pilot/token_profile.json): gpt-4.1
# typed, 100-turn cap: 5.34 calls per turn for four seats, 5,277 tokens in and 378 out per call
DEFAULT_PROFILE = {"in_per_call": 5277.0, "out_per_call": 378.0, "calls_per_turn": 5.34}
CHARS_PER_TOKEN = 3.9        # measured on the stored prompts (o200k)
SYSTEM_PROMPT_TOKENS = {"typed": 1516, "free": 971}   # exact; the system prompt is not stored on the event


def price_key(model: str | None) -> str | None:
    """'openai/gpt-4.1-2025-04-14' -> 'gpt-4.1' when a list price exists."""
    if not model:
        return None
    model = str(model).split("@tinker://")[0]          # a trained checkpoint is priced as its base model
    m = str(model).split("/")[-1]
    if m in LIST_PRICES_USD_PER_M:
        return m
    low = {k.lower(): k for k in LIST_PRICES_USD_PER_M}
    if m.lower() in low:
        return low[m.lower()]
    for k in sorted(LIST_PRICES_USD_PER_M, key=len, reverse=True):
        if m.startswith(k + "-") or m == k:
            return k
    return None


def list_price(model: str | None, tokens_in: float, tokens_out: float):
    k = price_key(model)
    pi, po = LIST_PRICES_USD_PER_M.get(k, (None, None)) if k else (None, None)
    if pi is None or po is None:
        return None
    return round(tokens_in / 1e6 * pi + tokens_out / 1e6 * po, 2)


def estimate_tokens(prompt: str, raw: str, speech_mode: str = "typed") -> tuple[int, int]:
    """Tokens of one decision from the stored prompt and reply, when the
    provider reported no usage: prompt and reply at the measured characters per
    token, plus the exact system prompt for the speech mode."""
    return (int(len(prompt or "") / CHARS_PER_TOKEN) + SYSTEM_PROMPT_TOKENS.get(speech_mode, 1516),
            int(len(raw or "") / CHARS_PER_TOKEN))


def run_cost(metrics: dict) -> dict:
    """Tokens and list-price cost of one finished game, per model and in total."""
    per = defaultdict(lambda: {"input": 0, "output": 0, "estimated_decisions": 0, "decisions_reported": 0})
    for pd in (metrics.get("players") or {}).values():
        tk = pd.get("tokens") or {}
        p = per[pd.get("model") or "?"]
        p["input"] += int(tk.get("input") or 0); p["output"] += int(tk.get("output") or 0)
        p["estimated_decisions"] += int(tk.get("estimated_decisions") or 0)
        p["decisions_reported"] += int(tk.get("decisions_reported") or 0)
    usd = 0.0; priced = False; unpriced = 0
    for model, p in per.items():
        c = list_price(model, p["input"], p["output"])
        p["usd"] = c
        if c is None:
            unpriced += p["input"] + p["output"]
        else:
            usd += c; priced = True
    return {"per_model": dict(per), "usd": round(usd, 2) if priced else None,
            "unpriced_tokens": unpriced,
            "estimated": any(p["estimated_decisions"] for p in per.values())}


def measured_profile(con, model: str) -> dict | None:
    """Tokens per call and calls per turn for `model`, from finished games whose
    seats ran it (ledger tokens, real or estimated)."""
    rows = con.execute("SELECT metrics, progress_turn, max_turns FROM runs WHERE metrics IS NOT NULL "
                       "AND status IN ('done','low_coverage') AND config LIKE ?", (f'%"{model}"%',)).fetchall()
    tin = tout = calls = 0.0; turns = 0.0; games = 0; est = 0
    for r in rows:
        m = json.loads(r["metrics"] or "{}")
        seats = [pd for pd in (m.get("players") or {}).values() if pd.get("model") == model]
        if not seats:
            continue
        t_in = sum(int((pd.get("tokens") or {}).get("input") or 0) for pd in seats)
        t_out = sum(int((pd.get("tokens") or {}).get("output") or 0) for pd in seats)
        dec = sum(int(pd.get("decisions") or 0) for pd in seats)
        if not dec or not t_in:
            continue
        games += 1; tin += t_in; tout += t_out; calls += dec
        turns += float(r["progress_turn"] or r["max_turns"] or 0) * len(seats) / max(1, len(m.get("players") or {}))
        est += sum(int((pd.get("tokens") or {}).get("estimated_decisions") or 0) for pd in seats)
    if not games or not calls:
        return None
    return {"in_per_call": tin / calls, "out_per_call": tout / calls,
            "calls_per_turn": (calls / turns) if turns else DEFAULT_PROFILE["calls_per_turn"],
            "games": games, "estimated_share": round(est / calls, 2)}


def estimate_batch(batch: list, con=None) -> dict:
    """Before launch: games, calls, tokens and list-price USD per model for the
    runs a launch would queue. `batch` items carry a config with players and
    max_turns (the launch form's shape)."""
    per = defaultdict(lambda: {"seat_games": 0, "calls": 0.0, "tokens_in": 0.0, "tokens_out": 0.0,
                               "profile": None})
    profiles = {}
    for item in batch:
        cfg = item.get("config") or item
        players = cfg.get("players") or []
        turns = float(cfg.get("max_turns") or 120)
        n = max(1, len(players))
        for p in players:
            model = p.get("model") or "?"
            if p.get("provider") == "mock":
                model = "mock"
            if model not in profiles:
                prof = (measured_profile(con, model) if con is not None and model != "mock" else None)
                profiles[model] = prof or dict(DEFAULT_PROFILE, games=0)
            prof = profiles[model]
            seat_calls = prof["calls_per_turn"] * turns / n
            e = per[model]
            e["seat_games"] += 1; e["calls"] += seat_calls
            e["tokens_in"] += seat_calls * prof["in_per_call"]; e["tokens_out"] += seat_calls * prof["out_per_call"]
            e["profile"] = ("measured on %d game(s)" % prof["games"]) if prof.get("games") else "default profile (gpt-4.1 on E1)"
    out = {"games": len(batch), "per_model": {}, "usd_total": 0.0, "unpriced_tokens": 0.0, "priced": False}
    for model, e in per.items():
        usd = 0.0 if model == "mock" else list_price(model, e["tokens_in"], e["tokens_out"])
        out["per_model"][model] = {**e, "calls": round(e["calls"]), "tokens_in": round(e["tokens_in"]),
                                   "tokens_out": round(e["tokens_out"]), "usd": usd}
        if usd is None:
            out["unpriced_tokens"] += e["tokens_in"] + e["tokens_out"]
        else:
            out["usd_total"] += usd; out["priced"] = out["priced"] or model != "mock"
    out["usd_total"] = round(out["usd_total"], 2); out["unpriced_tokens"] = round(out["unpriced_tokens"])
    # reasoning models bill hidden reasoning as output; until a game of that model is
    # in the ledger the estimate carries no reasoning tokens at all
    out["unmeasured_reasoning"] = sorted(m for m, p in profiles.items()
                                         if not p.get("games") and str(m).split("/")[-1].startswith(("gpt-5", "o1", "o3", "o4")))
    out["shutdowns"] = {m: SHUTDOWN[price_key(m)] for m in profiles if price_key(m) in SHUTDOWN}
    return out


def backfill_costs(con, force: bool = False) -> int:
    """cost_usd for every finished run that has metrics but no cost yet; force
    re-prices every run (after a price-table change, e.g. Tinker priced 2026-10-25)."""
    n = 0
    rows = con.execute("SELECT id, metrics FROM runs WHERE metrics IS NOT NULL" + ("" if force else " AND cost_usd IS NULL")).fetchall()
    with con:
        for r in rows:
            c = run_cost(json.loads(r["metrics"] or "{}"))
            if c["usd"] is not None or c["unpriced_tokens"]:
                con.execute("UPDATE runs SET cost_usd=? WHERE id=?", (c["usd"] if c["usd"] is not None else 0.0, r["id"]))
                n += 1
    return n


def budget_guard(con, eid: int) -> dict | None:
    """Hold the queued runs of an experiment once its priced spend reaches its
    cap. Returns what it did, or None when no cap is set."""
    row = con.execute("SELECT budget_usd, group_id FROM experiments WHERE id=?", (eid,)).fetchone()
    if not row:
        return None
    if row["budget_usd"] not in (None, 0):
        cap = float(row["budget_usd"])
        spent = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE experiment_id=?", (eid,)).fetchone()[0]
    else:
        # no experiment cap: the hypothesis group's OpenAI cap, set by an admin,
        # counted over every experiment in the group (2026-10-25)
        g = con.execute("SELECT cap_openai FROM groups WHERE id=?", (row["group_id"],)).fetchone() if row["group_id"] else None
        if not g or g["cap_openai"] in (None, 0):
            return None
        cap = float(g["cap_openai"])
        spent = con.execute("SELECT COALESCE(SUM(r.cost_usd), 0) FROM runs r JOIN experiments e ON e.id=r.experiment_id "
                            "WHERE e.group_id=? AND r.config LIKE '%openai%'", (row["group_id"],)).fetchone()[0]
    if spent < cap:
        return {"spent": round(spent, 2), "cap": cap, "held": 0}
    with con:
        held = con.execute("UPDATE runs SET status='held', error=? WHERE experiment_id=? AND status='queued'",
                           (f"budget cap ${cap:.2f} reached (${spent:.2f} spent at list price); raise the cap to continue", eid)).rowcount
    return {"spent": round(spent, 2), "cap": cap, "held": held}
