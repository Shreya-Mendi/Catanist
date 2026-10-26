"""Console rendering (2026-10-21): the compare page on schema v2 logs, the
lazy transcript, the fallback reason behind a low-coverage game, and the
handler guard that turns a crash into a 500 JSON instead of an empty reply."""
import http.client
import json
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Row(dict):
    """sqlite3.Row stand-in: missing keys read as None."""
    def __getitem__(self, k):
        return dict.get(self, k)


def _mock_game(max_turns=40, seed=11):
    from arena.runner import build_players, _provider_cache
    from arena.engine import Game
    cfg = json.load(open(ROOT / "configs/demo.json"))
    cfg["speech_mode"] = "typed"
    players = build_players(cfg, _provider_cache())
    return cfg, Game(players, seed=seed, speech_mode="typed", max_turns=max_turns).run()


def test_compare_v2():
    """The compare page used to die on the first plan tag (KeyError: 'plan')."""
    from viz.compare import render, arm_summary
    cfg, res = _mock_game()
    ra = Row(id=1, condition="model=mock arm=typed", seed=11, log_path="a.json", config=json.dumps(cfg), experiment_id=1, metrics="{}")
    rb = Row(id=2, condition="model=mock arm=free", seed=11, log_path="b.json", config=json.dumps(cfg), experiment_id=1, metrics="{}")
    html = render(ra, rb, res, res, None, None, [], {}, {})
    st = arm_summary(res, None, {})
    assert st["plans"] > 0 and st["checkable"] >= st["plans"], st
    assert "k-plan" in html and "Where it happened" in html and "hand had" in html
    assert ("KEPT" in html or "BROKEN" in html), "resolved promises/plans carry their fate"
    print(f"compare v3: statements {st['statements']} checkable {st['checkable']} broken {st['broken']} kept {st['kept']}")


def test_transcript_lazy():
    """Prompts and boards load on open; ?full=1 inlines them again."""
    import serve
    cfg, res = _mock_game()
    row = Row(id=7, condition="arm=typed", seed=11, log_path="a.json", config=json.dumps(cfg))
    lite = serve._transcript_html(row, res, None)
    full = serve._transcript_html(row, res, None, full=True)
    assert "<svg" not in lite and "data-src='/api/run/7/board/" in lite
    assert "<svg" in full and "data-src=" not in full
    tidx = next(i for i, e in enumerate(res["events"]) if e.get("type") == "turn")
    assert serve._board_at(res, tidx).lstrip().startswith("<svg")
    pidx = next((i for i, e in enumerate(res["events"]) if e.get("prompt")), None)
    if pidx is not None:
        assert "data-src='/api/run/7/prompt/" in lite
        assert serve._event_prompt(res, pidx) == res["events"][pidx]["prompt"]
    assert serve._event_prompt(res, 10 ** 6) is None and serve._board_at(res, -1) is None
    print(f"transcript: lite {len(lite)/1e3:.0f} KB vs full {len(full)/1e3:.0f} KB, prompts logged: {pidx is not None}")


def test_fallback_reason():
    """A game the model never played reports why, per seat and in one line."""
    from arena.metrics import game_metrics
    cfg, res = _mock_game(max_turns=12)
    for e in res["events"]:
        if "parse_ok" in e:
            e["private"] = "<provider error: AuthenticationError>"
            e["played_by"] = "heuristic"
            e["parse_ok"] = False
    m = game_metrics(res)
    assert m["fallback_summary"].startswith("AuthenticationError on "), m["fallback_summary"]
    assert all(pd["coverage"] == 0 for pd in m["players"].values())
    assert all(pd["fallback_reasons"] == {"AuthenticationError": pd["decisions"]} for pd in m["players"].values())
    clean = game_metrics(_mock_game(max_turns=12)[1])
    assert clean["fallback_summary"] is None or "engine fallback" in clean["fallback_summary"]
    print(f"fallback: {m['fallback_summary']} · clean game: {clean['fallback_summary']}")


def test_handler_guard():
    """A handler exception answers 500 JSON instead of closing the socket."""
    import serve
    from arena import db
    srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        tok = db.make_token("guard-test")            # signature only; no user row needed
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/api/run/not-a-number/transcript", headers={"Cookie": f"s={tok}"})
        r = c.getresponse(); body = json.loads(r.read())
        assert r.status == 500 and "ValueError" in body["err"] and body["where"], (r.status, body)
        c.request("GET", "/compare?a=999999&b=999998", headers={"Cookie": f"s={tok}"})
        r = c.getresponse(); body = json.loads(r.read())
        assert r.status == 404 and "err" in body
        c.request("GET", "/api/run/999999/board/0", headers={"Cookie": f"s={tok}"})
        r = c.getresponse(); body = json.loads(r.read())
        assert r.status == 404, (r.status, body)
        print("handler guard: 500 JSON on a crash, 404 JSON on missing runs")
    finally:
        srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    test_compare_v2(); test_transcript_lazy(); test_fallback_reason(); test_handler_guard()
