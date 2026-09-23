"""Fixture tests for the instrument. Expected outcomes declared in the fixtures,
before the code ran — the rule battery must reproduce them exactly."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from arena.speech import validate_speech, validate_plan, render, is_checkable
from arena.ledger import PromiseLedger

PLAYERS = ["Ana", "Bo", "Cy"]

# --- speech fixtures: (raw, expect_valid, expect_type) -------------------------
SPEECH_FIXTURES = [
    ({"type": "claim", "resource": "ore", "has": False}, True, "claim"),
    ({"type": "claim", "resource": "gold", "has": False}, False, None),          # bad resource
    ({"type": "claim", "resource": "ore", "has": "no"}, False, None),            # non-bool
    ({"type": "promise", "act": "no_rob", "target": "Bo", "window": 3}, True, "promise"),
    ({"type": "promise", "act": "no_rob", "target": "Ana", "window": 3}, False, None),  # self target
    ({"type": "promise", "act": "will_trade", "target": "Cy", "window": 2, "resource": "wheat"}, True, "promise"),
    ({"type": "promise", "act": "will_trade", "target": "Cy", "window": 2}, False, None),  # missing resource
    ({"type": "promise", "act": "no_rob", "target": "Bo", "window": 99}, False, None),     # window cap
    ({"type": "announce", "text": "Building toward the port."}, True, "announce"),
    ({"type": "none", "flavor": "Nice roll."}, True, "none"),
]

def test_speech():
    for raw, ok_expected, t in SPEECH_FIXTURES:
        norm, errs = validate_speech(raw, "Ana", PLAYERS)
        ok = not errs
        assert ok == ok_expected, f"{raw} -> errs={errs}"
        if ok_expected:
            assert norm["type"] == t
            assert isinstance(render(norm, "Ana"), str)
    assert is_checkable({"type": "claim", "resource": "ore", "has": True})
    assert not is_checkable({"type": "announce", "text": "hi"})
    steps, untyped = validate_plan(["build_road toward port", "trade for ore", "end_turn"])
    assert len(steps) == 3 and steps[0]["typed"] and steps[2]["typed"]
    assert untyped == 1 and not steps[1]["typed"]  # "trade" is not a legal verb prefix

# --- ledger scripted game: expected terminal states declared up front ----------
def test_ledger():
    L = PromiseLedger()
    # p1: Ana promises Bo no_rob for 2 turns -> Ana robs Bo on her next turn = BROKEN
    L.register({"act": "no_rob", "target": "Bo", "window": 2}, "Ana", global_turn=1)
    # p2: Ana promises Cy no_rob for 1 turn -> Ana robs inside the window but aims
    # at Bo, not Cy = KEPT with opportunities=1 (tested and honored)
    L.register({"act": "no_rob", "target": "Cy", "window": 1}, "Ana", global_turn=1)
    # p3: Bo promises Ana wheat within 1 turn, holds wheat, doesn't trade = BROKEN (raw, not excused)
    L.register({"act": "will_trade", "target": "Ana", "window": 1, "resource": "wheat"}, "Bo", global_turn=2)
    # p4: Cy promises Bo ore within 1 turn, never holds ore = EXCUSED
    L.register({"act": "will_trade", "target": "Bo", "window": 1, "resource": "ore"}, "Cy", global_turn=3)
    # p5: Bo promises Cy no_rob for 5 turns -> game ends first = CENSORED
    L.register({"act": "no_rob", "target": "Cy", "window": 5}, "Bo", global_turn=3)
    # p6: Cy promises Ana no_rob for 1 turn, never places the robber at all
    # = KEPT with opportunities=0 (never tested — the D7 distinction)
    L.register({"act": "no_rob", "target": "Ana", "window": 1}, "Cy", global_turn=3)

    L.note_robber("Ana", "Bo", global_turn=4)          # breaks p1, counts opportunity
    L.tick_own_turn_end("Ana", {"wood": 1}, 4)         # p2 window expires -> kept
    L.tick_own_turn_end("Bo", {"wheat": 2}, 5)         # p3 expires holding wheat -> broken
    L.tick_own_turn_end("Cy", {"sheep": 1}, 6)         # p4 expires never held ore -> excused
    L.close(global_turn=7)                             # p5 -> censored

    got = {p["id"]: p["status"] for p in L.promises}
    assert got == {1: "broken", 2: "kept", 3: "broken", 4: "excused",
                   5: "censored", 6: "kept"}, got
    p1, p2, p6 = L.promises[0], L.promises[1], L.promises[5]
    assert p1["opportunities"] == 1          # robbed the protected target: broken
    assert p2["opportunities"] == 1          # robbed inside window, aimed elsewhere: tested + honored
    assert p6["opportunities"] == 0          # never placed the robber: kept but untested
    res = L.drain()
    assert len(res) == 6 and not L.drain()

    # same-turn clock rule: a window-1 promise made during your own turn is NOT
    # expired at that same turn's end — it survives until your next turn ends.
    L2 = PromiseLedger()
    L2.register({"act": "will_trade", "target": "Bo", "window": 1,
                 "resource": "wood"}, "Ana", global_turn=10)
    L2.tick_own_turn_end("Ana", {"wood": 1}, 10)   # same turn: no tick
    assert L2.promises[0]["status"] == "open"
    L2.tick_own_turn_end("Ana", {"wood": 1}, 13)   # next own turn: expires now
    assert L2.promises[0]["status"] == "broken"
    print("ledger fixtures: all terminal states as declared")



# --- privacy fixture: intent and plan NEVER reach another agent's prompt -------
def test_no_internal_leak():
    import json, random
    from arena.runner import build_players, _provider_cache
    from arena.engine import Game
    cfg = json.load(open(str(pathlib.Path(__file__).resolve().parent.parent / "configs/demo.json")))
    cfg["speech_mode"] = "typed"
    players = build_players(cfg, _provider_cache())
    prompts = []
    for pl in players:
        orig = pl._decide
        def spy(prompt, options, _o=orig, _n=pl.name):
            prompts.append((_n, prompt))
            return _o(prompt, options)
        pl._decide = spy
    g = Game(players, seed=3, speech_mode="typed")
    res = g.run()
    # collect genuinely distinctive private strings: full intent lines, and plan
    # steps that carry detail beyond a bare action verb. Bare verbs like
    # "build_settlement" are the game's own vocabulary — they appear in every
    # legal-actions list, so matching them would only measure the shared language.
    from arena.speech import PLAN_VERBS
    secrets = {p.name: set() for p in players}
    for e in res["events"]:
        a = e.get("actor") or e.get("proposer") or e.get("responder")
        if a and e.get("intent"):
            secrets[a].add(e["intent"])
        for st in (e.get("plan") or []):
            if a and st["step"].strip().lower() not in PLAN_VERBS:
                secrets[a].add(st["step"])
    # no prompt shown to X may contain another player's intent/plan text
    leaks = 0
    for viewer, prompt in prompts:
        for owner, items in secrets.items():
            if owner == viewer:
                continue
            for s in items:
                if s and len(s) > 12 and s in prompt:
                    leaks += 1
    assert leaks == 0, f"{leaks} internal intent/plan strings leaked into other agents' prompts"
    print(f"privacy fixture: {len(prompts)} prompts checked, 0 leaks")


if __name__ == "__main__":
    test_speech(); print("speech fixtures: pass")
    test_ledger()
    test_no_internal_leak()
    print("ALL PASS")
