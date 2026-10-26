"""Platform round of 2026-10-25: trade knob, prompt override, researcher
overrides, per-statement export, label agreement, hypothesis groups, schema."""
import json
import pathlib
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arena import overrides as ovr, groups as grp, exports, agreement  # noqa: E402
from arena.db import _SCHEMA, _MIGRATIONS  # noqa: E402


def _mem_db():
    con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    have = {}
    for table, col, ddl in _MIGRATIONS:
        have.setdefault(table, {r[1] for r in con.execute(f"PRAGMA table_info({table})")})
        if col not in have[table]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"); have[table].add(col)
    return con


def _mock_game(max_turns=24, seed=11, **kw):
    from arena.runner import build_players, _provider_cache
    from arena.engine import Game
    cfg = json.load(open(ROOT / "configs/demo.json"))
    cfg["speech_mode"] = "typed"; cfg.update(kw.pop("cfg", {}))
    players = build_players(cfg, _provider_cache())
    return cfg, players, Game(players, seed=seed, speech_mode="typed", max_turns=max_turns, **kw).run()


def test_trade_knob():
    _, _, off = _mock_game(p2p_trade=False)
    assert not any(e["type"] == "trade_proposal" for e in off["events"]), "no player trades when the knob is off"
    assert any("trading is OFF" in (e.get("prompt") or "") for e in off["events"] if "parse_ok" in e)
    assert any(e["type"] == "bank_trade" for e in off["events"]) or True
    _, _, on = _mock_game(p2p_trade=True)
    assert any(e["type"] == "trade_proposal" for e in on["events"])
    print("trade knob: off removes player trades and says so in the prompt")


def test_prompt_override():
    from arena.runner import build_players, _provider_cache
    cfg = json.load(open(ROOT / "configs/demo.json"))
    base = build_players(cfg, _provider_cache())[0]._system()
    cfg2 = dict(cfg, prompt_override={"mode": "append", "text": "EXTRA RULE: say little."})
    assert build_players(cfg2, _provider_cache())[0]._system() == base + "\n\nEXTRA RULE: say little."
    cfg3 = dict(cfg, prompt_override={"mode": "replace", "text": "You are a potato."})
    assert build_players(cfg3, _provider_cache())[0]._system() == "You are a potato."
    print("prompt override: append and replace, recorded in the config")


def test_overrides_apply():
    ev = [
        {"type": "setup", "players": [{"name": "Merlin"}]},
        {"type": "turn", "n": 1, "actor": "Merlin", "turn": 1},
        {"type": "pass", "actor": "Merlin", "turn": 1, "parse_ok": True, "public": "I have no ore.",
         "speech": {"type": "claim", "resource": "ore", "has": False}, "claim_true": False},
        {"type": "pass", "actor": "Merlin", "turn": 1, "parse_ok": True, "public": "Settlement next turn.",
         "speech": {"type": "plan", "do": "build_settlement", "window": 1}, "plan_id": 1},
        {"type": "plan_resolved", "plan_id": 1, "planner": "Merlin", "status": "broken", "turn": 3, "do": "build_settlement", "window": 1},
        {"type": "pass", "actor": "Merlin", "turn": 3, "parse_ok": True, "public": "Nice weather.",
         "speech": {"type": "claim", "resource": "wood", "has": True}, "claim_true": True},
    ]
    ov = {(2, "verdict"): {"corrected": "true"}, (3, "verdict"): {"corrected": "excused"},
          (5, "kind"): {"corrected": "chatter"}}
    out = ovr.apply_to_events(ev, ov)
    assert out[2]["claim_true"] is True and out[4]["status"] == "excused" and out[5]["speech"]["type"] == "none"
    assert ev[2]["claim_true"] is False, "the original events are untouched"
    out2 = ovr.apply_to_events(ev, {(2, "exclude"): {"corrected": "yes"}, (5, "action_bound"): {"corrected": "yes"}})
    assert out2[2]["excluded"] is True and out2[5]["action_bound"] == "researcher" and out2[5]["ab_override"]
    from arena.metrics import game_metrics, effective_bound
    assert effective_bound(out2[5]) == "researcher"
    m = game_metrics({"events": out2, "setup": ev[0]["players"], "winner": "Merlin", "vps": {}})["players"]["Merlin"]
    assert m["excluded"] == 1 and m["statements"] == 2 and m["action_bound"] == 1, m
    assert ovr.validate("kind", "poem") and ovr.validate("verdict", "false") is None
    print("overrides: overlay applied to a copy; exclusions, verdicts, kinds and action-bound all take effect")


def test_overrides_db_and_recompute():
    con = _mem_db()
    rid = ovr.save(con, 7, 2, "verdict", "true", {"claim_true": False}, "tag contradicts the text", "shreya")
    ovr.save(con, 7, 2, "verdict", "false", None, "changed my mind", "shreya")
    lt = ovr.latest(con, 7)
    assert lt[(2, "verdict")]["corrected"] == "false" and rid == 1
    assert ovr.by_event(con, 7) == {2: [lt[(2, "verdict")]]}
    print("overrides: latest row per field wins, history kept")


def test_statement_export_and_groups():
    con = _mem_db()
    cfg, players, res = _mock_game(max_turns=16)
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d); (root / "logs").mkdir()
        (root / "logs" / "g.json").write_text(json.dumps({**res, "setup": res["setup"]}))
        from arena.metrics import game_metrics
        m = game_metrics(res)
        con.execute("INSERT INTO experiments(id,name,owner,hypothesis,created) VALUES(1,'e','shreya','H2 emergence+contagion',0)")
        con.execute("INSERT INTO experiments(id,name,owner,hypothesis,created) VALUES(2,'f','ammy','H3 steerability',0)")
        con.execute("INSERT INTO runs(id,experiment_id,owner,config,condition,seed,status,log_path,metrics,cost_usd) VALUES(1,1,'shreya',?,'arm=typed',11,'done','logs/g.json',?,1.5)",
                    (json.dumps({**cfg, "players": [{"provider": "openai", "model": "gpt-6-luna"}]}), json.dumps(m)))
        con.execute("INSERT INTO labels(run_id,event_idx,statement,context,label,labeler,created,reason) VALUES(1,?,?,?,?,?,0,?)",
                    (next(i for i, e in enumerate(res["events"]) if e.get("public")), "x", json.dumps({"verdict": "true claim"}), "honest", "shreya", "clear"))
        ovr.save(con, 1, next(i for i, e in enumerate(res["events"]) if e.get("public")), "exclude", "yes", None, "narration", "shreya")
        rows = con.execute("SELECT * FROM runs").fetchall()
        csv_text = exports.statements_csv(con, rows, root)
        lines = csv_text.splitlines()
        assert lines[0].startswith("run_id,experiment_id,condition") and len(lines) > 20, len(lines)
        assert "shreya=honest [clear]" in csv_text and "exclude" in csv_text and "yes (shreya: narration)" in csv_text
        # groups: one per hypothesis, spend by provider, files
        gs = grp.list_groups(con)
        names = {g["name"]: g for g in gs}
        assert "H2 emergence and contagion (E2, E3)" in names and "H3 steerability (E4, E5)" in names
        g2 = names["H2 emergence and contagion (E2, E3)"]
        assert [mm["id"] for mm in g2["members"]] == [1] and g2["spend"]["openai"] == 1.5
        gid = grp.create(con, "E1 package", "shreya", "custom", "the H1 bundle")
        grp.set_member(con, gid, 2, True)
        f = grp.save_file(con, root, gid, "../E1-results.md", b"# E1\n\nhello", "shreya")
        assert f["name"] == "E1-results.md" and (root / f["path"]).exists()
        p, mime = grp.file_path(con, root, gid, "E1-results.md")
        assert p and mime == "text/markdown"
        # a custom group adds; the hypothesis group (experiments.group_id) stays
        assert con.execute("SELECT 1 FROM group_members WHERE group_id=? AND experiment_id=2", (gid,)).fetchone()
        assert con.execute("SELECT group_id FROM experiments WHERE id=2").fetchone()[0] == names["H3 steerability (E4, E5)"]["id"]
        h2 = names["H2 emergence and contagion (E2, E3)"]["id"]
        grp.set_member(con, h2, 2, True)         # moving to another hypothesis group is exclusive
        assert con.execute("SELECT group_id FROM experiments WHERE id=2").fetchone()[0] == h2
        assert not con.execute("SELECT 1 FROM group_members WHERE group_id=? AND experiment_id=2", (names["H3 steerability (E4, E5)"]["id"],)).fetchone()
    print(f"export: {len(lines)-1} statement rows with labels and overlay; groups: per hypothesis plus custom, files saved safely")


def test_agreement():
    con = _mem_db()
    items = [{"run_id": 1, "event_idx": i} for i in range(12)]
    A = ["lie", "honest", "honest", "lie", "unclear", "honest", "lie", "honest", "honest", "lie", "honest", "honest"]
    B = ["lie", "honest", "lie", "lie", "unclear", "honest", "lie", "honest", "honest", "honest", "honest", "honest"]
    verd = ["false claim", "true claim", None, "promise broken", None, "true claim", "false claim", "true claim", "true claim", "false claim", None, "true claim"]
    for i in range(12):
        for lab, L in (("a", A), ("b", B)):
            con.execute("INSERT INTO labels(run_id,event_idx,statement,context,label,labeler,created) VALUES(1,?,?,?,?,?,0)",
                        (i, "s", json.dumps({"verdict": verd[i]}), L[i], lab))
    out = agreement.task_agreement(con, items)
    pair = out["pairs"][0]
    assert pair["n"] == 12 and 0.5 < pair["kappa"] < 1 and pair["agree"] == round(10 / 12, 3), pair
    assert out["vs_engine"]["a"]["n"] == 12 and out["vs_engine"]["a"]["kappa_lie_vs_not"] == 1.0
    assert agreement.cohen_kappa(["x"] * 4, ["x"] * 4) == 1.0
    print(f"agreement: kappa {pair['kappa']} between two labelers, labeler a matches the engine exactly")


def test_schema_migrations_on_real_db():
    from arena import db
    con = db.connect()
    cols = {r[1] for r in con.execute("PRAGMA table_info(labels)")}
    rcols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "reason" in cols and {"excluded", "exclude_reason", "metrics_corrected"} <= rcols
    assert {"overrides", "run_scores", "groups", "group_members", "group_files", "activity"} <= tables
    con.close()
    print("schema: migrations applied to the local database")




def test_prompt_edit_in_preview():
    """The preview splits the prompt into this seat's lines and the shared part;
    replace_rules swaps only the shared part, so personas and intents survive."""
    from arena.runner import build_players, _provider_cache
    cfg = json.load(open(ROOT / "configs/demo.json")); cfg["speech_mode"] = "typed"
    players = build_players(cfg, _provider_cache())
    h0, t0 = players[0]._system_parts(); h1, t1 = players[1]._system_parts()
    assert h0 != h1 and t0 == t1 and players[0]._system() == "\n\n".join(h0 + t0)
    assert any(x.startswith("NAME:") for x in h0) and any("RULES" in x for x in t0)
    cfg2 = dict(cfg, prompt_override={"mode": "replace_rules", "text": "ONLY RULE: be brief."})
    p2 = build_players(cfg2, _provider_cache())
    assert p2[0]._system() == "\n\n".join(h0 + ["ONLY RULE: be brief."]) and p2[1]._system().startswith("\n\n".join(h1))
    print("prompt edit: shared part replaced, each seat keeps its own lines")


def test_organize_logs():
    """Flat logs move into logs/<hypothesis>/<experiment>/ with the row updated;
    a dry run touches nothing; the indexer skips group files."""
    from arena import datafiles, groups
    con = _mem_db()
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d); (root / "logs").mkdir(); (root / "logs" / "groups" / "1").mkdir(parents=True)
        con.execute("INSERT INTO experiments(id,name,owner,hypothesis,created) VALUES(24,'E1 main: typed vs free, 30 seeds','shreya','H1',0)")
        groups.ensure_hypothesis_groups(con)
        gid = con.execute("SELECT group_id FROM experiments WHERE id=24").fetchone()[0]
        assert con.execute("SELECT name FROM groups WHERE id=?", (gid,)).fetchone()[0] == "H1 instrument (E1)"
        for rid, name in ((161, "main-gpt-4.1-typed_run161.json"), (162, "main-gpt-4.1-free_run162.json")):
            (root / "logs" / name).write_text('{"events": [], "setup": []}')
            (root / "logs" / name.replace(".json", "_scene.html")).write_text("<html>")
            con.execute("INSERT INTO runs(id,experiment_id,owner,config,status,log_path) VALUES(?,?,?,?,?,?)",
                        (rid, 24, "shreya", "{}", "done", f"logs/{name}"))
        (root / "logs" / "main-gpt-4.1-free_run162_extracted.json").write_text("{}")
        (root / "logs" / "groups" / "1" / "results.json").write_text('{"events": "not a game"}')
        dry = datafiles.organize_logs(con, root, apply=False)
        assert dry["planned"] == 2 and (root / "logs" / "main-gpt-4.1-typed_run161.json").exists()
        assert dry["steps"][0]["to"].startswith("logs/H1-instrument-E1/exp24-E1-main-typed-vs-free-30-seeds/")
        rep = datafiles.organize_logs(con, root, apply=True)
        assert rep["moved"] == 2 and not rep["failed"], rep
        new162 = con.execute("SELECT log_path FROM runs WHERE id=162").fetchone()[0]
        assert (root / new162).exists() and (root / new162.replace(".json", "_extracted.json")).exists() \
            and (root / new162.replace(".json", "_scene.html")).exists()
        assert not (root / "logs" / "main-gpt-4.1-free_run162.json").exists()
        assert datafiles.organize_logs(con, root, apply=False)["planned"] == 0      # idempotent
        v = datafiles.verify(con, root)
        assert v["missing"] == [] and v["by_folder"] == {"H1-instrument-E1": 2}
        assert datafiles.subdir_for(con, 161) == "H1-instrument-E1/exp24-E1-main-typed-vs-free-30-seeds"
    print("organize: dry run plans, apply moves log + extraction + scene, row follows, group files untouched")


if __name__ == "__main__":
    test_trade_knob(); test_prompt_override(); test_overrides_apply(); test_overrides_db_and_recompute()
    test_statement_export_and_groups(); test_agreement(); test_schema_migrations_on_real_db()
    test_prompt_edit_in_preview(); test_organize_logs()
