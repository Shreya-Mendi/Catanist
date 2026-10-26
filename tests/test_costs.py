"""Cost model (2026-10-24): estimates before a run, ledger after, budget cap."""
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arena import costs  # noqa: E402
from arena.metrics import game_metrics  # noqa: E402


def test_prices_and_profile():
    assert costs.price_key("openai/gpt-4.1-2025-04-14") == "gpt-4.1" and costs.price_key("Qwen/Qwen3.8-27B") == "Qwen3.8-27B"
    assert costs.list_price("gpt-4.1", 1e6, 1e6) == 10.0 and costs.list_price("Qwen/Qwen3.8-27B", 1e6, 1e6) == round(0.6975 + 5.595, 2)
    batch = [{"config": {"max_turns": 100, "players": [{"provider": "openai", "model": "gpt-4.1"}] * 4}}]
    e = costs.estimate_batch(batch)
    g = e["per_model"]["gpt-4.1"]
    assert 6.0 <= e["usd_total"] <= 9.0 and g["calls"] == 534 and "default profile" in g["profile"], e
    mock = costs.estimate_batch([{"config": {"max_turns": 60, "players": [{"provider": "mock", "model": "x"}] * 3}}])
    assert mock["usd_total"] == 0.0 and not mock["priced"]
    tink = costs.estimate_batch([{"config": {"max_turns": 100, "players": [{"provider": "tinker", "model": "Qwen/Qwen3.8-27B"}] * 4}}])
    assert 1.5 <= tink["usd_total"] <= 3.5 and tink["unpriced_tokens"] == 0, tink   # Tinker is priced now
    print(f"estimate: 4 x gpt-4.1 at 100 turns = ${e['usd_total']} (flat $0.0006/call said $0.35)")


def test_estimated_tokens_in_metrics():
    ev = [
        {"type": "setup", "players": [{"name": "Merlin", "model": "gpt-4.1"}, {"name": "Isolde", "model": "gpt-4.1"}]},
        {"type": "turn", "n": 1, "actor": "Merlin", "turn": 1},
        {"type": "pass", "actor": "Merlin", "turn": 1, "parse_ok": True, "public": "Passing.", "speech": {"type": "announce"},
         "prompt": "x" * 8200, "raw": "y" * 400},
        {"type": "turn", "n": 2, "actor": "Isolde", "turn": 2},
        {"type": "pass", "actor": "Isolde", "turn": 2, "parse_ok": True, "public": "Me too.", "speech": {"type": "announce"},
         "prompt": "x" * 8200, "raw": "y" * 400, "usage": {"input": 3000, "output": 120}},
    ]
    m = game_metrics({"events": ev, "setup": ev[0]["players"], "winner": "Merlin", "vps": {}})
    merlin, isolde = m["players"]["Merlin"]["tokens"], m["players"]["Isolde"]["tokens"]
    assert merlin == {"input": int(8200 / 3.9) + 1516, "output": int(400 / 3.9), "decisions_reported": 0, "estimated_decisions": 1}, merlin
    assert isolde == {"input": 3000, "output": 120, "decisions_reported": 1, "estimated_decisions": 0}, isolde
    c = costs.run_cost(m)
    tin = int(8200 / 3.9) + 1516 + 3000; tout = int(400 / 3.9) + 120
    assert c["usd"] == round((tin / 1e6) * 2 + (tout / 1e6) * 8, 2) and c["estimated"] is True
    print(f"ledger: estimated tokens fill the gap, game cost ${c['usd']}")


def test_budget_guard():
    from arena.db import _SCHEMA, _MIGRATIONS
    con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    have = {}
    for table, col, ddl in _MIGRATIONS:
        have.setdefault(table, {r[1] for r in con.execute(f"PRAGMA table_info({table})")})
        if col not in have[table]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"); have[table].add(col)
    con.execute("INSERT INTO experiments(id,name,owner,budget_usd) VALUES(1,'x','shreya',10.0)")
    for i, (st, c) in enumerate([("done", 6.0), ("done", 3.0), ("queued", None), ("queued", None), ("held", None)], 1):
        con.execute("INSERT INTO runs(id,experiment_id,owner,config,status,cost_usd) VALUES(?,?,?,?,?,?)", (i, 1, "shreya", "{}", st, c))
    g = costs.budget_guard(con, 1)
    assert g == {"spent": 9.0, "cap": 10.0, "held": 0}
    con.execute("UPDATE runs SET cost_usd=2.0 WHERE id=3"); con.execute("UPDATE runs SET status='done' WHERE id=3")
    g = costs.budget_guard(con, 1)
    assert g["spent"] == 11.0 and g["held"] == 1
    assert con.execute("SELECT status, error FROM runs WHERE id=4").fetchone()[0] == "held"
    assert costs.budget_guard(con, 99) is None
    con.execute("UPDATE experiments SET budget_usd=NULL WHERE id=1")
    assert costs.budget_guard(con, 1) is None
    # no experiment cap: the hypothesis group's OpenAI cap applies across the group
    con.execute("INSERT INTO groups(id,name,kind,cap_openai) VALUES(5,'H2','hypothesis',8.0)")
    con.execute("UPDATE experiments SET group_id=5 WHERE id=1")
    con.execute("UPDATE runs SET config=? WHERE experiment_id=1", ('{"players":[{"provider":"openai"}]}',))
    con.execute("UPDATE runs SET status='queued' WHERE id=4")
    g = costs.budget_guard(con, 1)
    assert g["cap"] == 8.0 and g["spent"] == 11.0 and g["held"] == 1, g
    print("budget guard: holds the queue at the cap, idle without one")


def test_reasoning_request_params(monkeypatch=None):
    from arena.providers import _request_kwargs
    import os
    os.environ.pop("OPENAI_REASONING_EFFORT", None)
    assert _request_kwargs("gpt-4.1") == {"max_tokens": 1100, "temperature": 0.8}
    kw = _request_kwargs("gpt-5")
    assert kw == {"max_completion_tokens": 3000, "reasoning_effort": "minimal"}, kw
    assert _request_kwargs("gpt-6-luna")["reasoning_effort"] == "none" and _request_kwargs("gpt-5.4-mini")["reasoning_effort"] == "none"
    os.environ["OPENAI_REASONING_EFFORT"] = "minimal"
    assert _request_kwargs("openai/gpt-5-mini")["reasoning_effort"] == "minimal"
    assert _request_kwargs("gpt-5", {"reasoning_effort": "medium", "max_completion_tokens": 5000}) == \
        {"max_completion_tokens": 5000, "reasoning_effort": "medium"}
    os.environ.pop("OPENAI_REASONING_EFFORT", None)
    e = costs.estimate_batch([{"config": {"max_turns": 100, "players": [{"provider": "openai", "model": "gpt-5"}] * 4}}])
    assert e["unmeasured_reasoning"] == ["gpt-5"] and e["shutdowns"] == {"gpt-5": "2026-12-11"} and 5.0 <= e["usd_total"] <= 7.0, e
    print(f"reasoning models: wide completion cap, effort none/minimal by default; estimate flags unmeasured reasoning (${e['usd_total']} before it)")


if __name__ == "__main__":
    test_prices_and_profile(); test_estimated_tokens_in_metrics(); test_budget_guard(); test_reasoning_request_params()
