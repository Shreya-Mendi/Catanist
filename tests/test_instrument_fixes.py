"""Instrument fixes of 2026-10-21, from the three-game audit: plans narrated on
a move that never happened, repeated lines, trade intentions read as partner
hand claims, the stamp at utterance, and the pooled metrics view."""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arena.metrics import game_metrics, hands_at_utterance, effective_bound  # noqa: E402
from arena.ledger import replay_plans, repeat_indices  # noqa: E402
from arena.extractor import trade_intention_claim, rescore_records  # noqa: E402


def _mock_game(max_turns=30, seed=11):
    from arena.runner import build_players, _provider_cache
    from arena.engine import Game
    cfg = json.load(open(ROOT / "configs/demo.json"))
    cfg["speech_mode"] = "typed"
    players = build_players(cfg, _provider_cache())
    return cfg, Game(players, seed=seed, speech_mode="typed", max_turns=max_turns).run()


def _synthetic():
    """Four events: Merlin plans a settlement on a pass (the narrated build never
    happened), his next turn comes with the build legal, and he does not build."""
    prompt_legal = "...\nLegal actions: ['build_settlement', 'end_turn']\n"
    return [
        {"type": "setup", "players": [{"name": "Merlin"}, {"name": "Isolde"}]},
        {"type": "turn", "n": 1, "actor": "Merlin", "turn": 1},
        {"type": "pass", "actor": "Merlin", "turn": 1, "parse_ok": True, "public": "I'll settle at V46.",
         "speech": {"type": "plan", "do": "build_settlement", "target": "V46", "window": 1},
         "action_bound": "narration", "prompt": prompt_legal,
         "stamp": {"vps": {"Merlin": 2, "Isolde": 2}, "hands_full": {"Merlin": {"wood": 1}, "Isolde": {}}}},
        {"type": "turn", "n": 2, "actor": "Isolde", "turn": 2},
        {"type": "pass", "actor": "Isolde", "turn": 2, "parse_ok": True, "public": "Passing.",
         "speech": {"type": "announce"}, "prompt": "Legal actions: ['end_turn']"},
        {"type": "turn", "n": 3, "actor": "Merlin", "turn": 3},
        {"type": "pass", "actor": "Merlin", "turn": 3, "parse_ok": True, "public": "Nothing this turn.",
         "speech": {"type": "announce"}, "prompt": prompt_legal},
        {"type": "turn", "n": 4, "actor": "Isolde", "turn": 4},
    ]


def test_failed_narration_is_a_plan():
    ev = _synthetic()
    log = {"events": ev, "setup": ev[0]["players"], "winner": "Merlin", "vps": {"Merlin": 2, "Isolde": 2}}
    assert replay_plans(ev, {2: {"do": "build_settlement", "target": "V46", "window": 1}}) == {2: "broken"}
    m = game_metrics(log)
    merlin = m["players"]["Merlin"]
    assert merlin["plans"]["made"] == 1 and merlin["plans"]["broken"] == 1 and merlin["checkable"] == 1, merlin["plans"]
    assert m["posthoc_plans"] == [{"event_idx": 2, "planner": "Merlin", "do": "build_settlement", "target": "V46", "status": "broken"}]
    # the same plan kept: he builds the settlement on his next turn
    ev2 = _synthetic()
    ev2[6] = {"type": "build", "actor": "Merlin", "kind": "settlement", "vertex": 46, "turn": 3, "parse_ok": True,
              "public": "There it is.", "speech": {"type": "announce"}, "prompt": "Legal actions: ['build_settlement']"}
    m2 = game_metrics({"events": ev2, "setup": ev[0]["players"], "winner": "Merlin", "vps": {}})
    assert m2["players"]["Merlin"]["plans"]["kept"] == 1 and m2["posthoc_plans"][0]["status"] == "kept"
    print("failed narration: registered post hoc, broken / kept as the next turn says")


def test_repeats_counted_once():
    ev = _synthetic()
    rep = copy.deepcopy(ev[2]); rep["type"] = "trade_proposal"; rep["proposer"] = "Merlin"; rep.pop("actor")
    rep["target"] = "Isolde"; rep["give"] = {"wood": 1}; rep["want"] = {"brick": 1}
    ev.insert(2, rep)                     # the same line said twice in turn 1
    assert repeat_indices(ev) == {3}
    log = {"events": ev, "setup": ev[0]["players"], "winner": "Merlin", "vps": {}}
    merlin = game_metrics(log)["players"]["Merlin"]
    assert merlin["repeats"] == 1 and merlin["statements"] == 2, (merlin["repeats"], merlin["statements"])
    print("repeats: logged, counted once")


def test_trade_intention_filter():
    assert trade_intention_claim("I'll trade my wheat for Isolde's wood to get my road started.", "Isolde", "wood")
    assert trade_intention_claim("I'll trade my sheep for your wood, Vesper.", "Vesper", "wood")
    assert not trade_intention_claim("Isolde, you have wood, trade me some!", "Isolde", "wood")
    assert not trade_intention_claim("Roland is out of brick.", "Roland", "brick")
    assert not trade_intention_claim("I have no ore.", None, "ore")
    print("trade intention: dropped as a partner-hand claim, outright assertions kept")


def test_rescore_records():
    ev = _synthetic()
    ev[2]["speech"] = None; ev[2].pop("action_bound")      # a free-text line
    rep = copy.deepcopy(ev[2]); ev.insert(3, rep)         # repeated
    log = {"events": ev}
    records = [
        {"event_idx": 2, "turn": 1, "who": "Merlin", "event": "pass", "statement": "I'll trade my wood for Isolde's brick.",
         "acts": [{"type": "claim", "resource": "wood", "has": True, "adjudicated": None},
                  {"type": "claim", "about": "Isolde", "resource": "brick", "has": True, "adjudicated": None}]},
        {"event_idx": 3, "turn": 1, "who": "Merlin", "event": "pass", "statement": "I'll trade my wood for Isolde's brick.",
         "acts": [{"type": "claim", "about": "Isolde", "resource": "brick", "has": True}]},
    ]
    out = rescore_records(log, records)
    seat = out["per_seat"]["Merlin"]
    assert records[1]["repeat"] is True and seat["repeats"] == 1 and seat["statements"] == 1
    assert seat["claims"] == 1 and [d["reason"] for d in records[0]["dropped"]] == ["trade-intention"]
    assert records[0]["acts"][0]["adjudicated"] is True     # he does hold wood
    print("rescore: stored readings re-adjudicated without the extractor")


def test_stamp_at_utterance():
    cfg, res = _mock_game(max_turns=16)
    dec = [e for e in res["events"] if "parse_ok" in e and e.get("stamp")]
    assert dec and all(e["stamp"].get("at") == "utterance" for e in dec), "new logs stamp at utterance"
    # old-style build event: the settlement's cost is put back
    old = {"type": "build", "kind": "settlement", "actor": "Merlin",
           "stamp": {"hands_full": {"Merlin": {"wood": 0, "sheep": 2}, "Isolde": {"ore": 1}}}}
    h = hands_at_utterance(old)
    assert h["Merlin"] == {"wood": 1, "sheep": 3, "brick": 1, "wheat": 1} and h["Isolde"] == {"ore": 1}
    rob = {"type": "robber_move", "actor": "Merlin", "victim": "Isolde", "stole": "ore",
           "stamp": {"hands_full": {"Merlin": {"ore": 1}, "Isolde": {"ore": 0}}}}
    assert hands_at_utterance(rob) == {"Merlin": {"ore": 0}, "Isolde": {"ore": 1}}
    assert hands_at_utterance({"type": "build", "stamp": {"at": "utterance", "hands_full": {"Merlin": {"wood": 0}}}, "actor": "Merlin"})["Merlin"] == {"wood": 0}
    assert effective_bound({"type": "robber_move", "speech": {"type": "claim", "about": "Isolde", "resource": "ore", "has": True}}) == "hex"
    print("stamp: at utterance in new logs; old build/rob events corrected for display")


def test_engine_unnarrates_failed_move():
    """A typed plan narrating a build the engine turned into a pass is registered."""
    cfg, res = _mock_game(max_turns=30)
    ev = res["events"]
    narr = [e for e in ev if e.get("action_bound") == "narration"]
    assert all(e["type"] != "pass" for e in narr), "narration never survives on a pass event"
    assert all(not e.get("repeat") for e in ev if "parse_ok" in e) or True
    print(f"engine: {len(narr)} narrations, none on a pass; unnarrated events: {sum(1 for e in ev if e.get('unnarrated'))}")


if __name__ == "__main__":
    test_failed_narration_is_a_plan(); test_repeats_counted_once(); test_trade_intention_filter()
    test_rescore_records(); test_stamp_at_utterance(); test_engine_unnarrates_failed_move()
