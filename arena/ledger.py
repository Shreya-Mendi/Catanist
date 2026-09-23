"""The promise ledger — engine-maintained memory and adjudicator for promises.

Clock (decision D4): a promise window counts the PROMISER'S OWN TURNS and
ticks when that player's turn ends. Off-turn promises (made while responding
to a trade) start ticking at the promiser's next own turn end.

Terminal states:
    kept     — no_rob: window expired without robbing the target
               (opportunities = how often the promiser actually placed the
               robber inside the window; 0 means the promise was never tested,
               decision D7). will_trade: a matching trade executed in window.
    broken   — no_rob: robber aimed at the target inside the window.
               will_trade: window expired with no matching trade.
    excused  — will_trade broken, but the promiser never once held the
               promised resource at an own-turn end inside the window
               (decision D1: raw vs excused are both kept in the record).
    censored — still open when the game ended (decision D5): neither kept nor
               broken, excluded from rate denominators, counted separately.

The ledger is table-public: every promise was public speech, so digest lines
are the same for every viewer.
"""
from __future__ import annotations


class PromiseLedger:
    def __init__(self):
        self.promises: list[dict] = []
        self.resolutions: list[dict] = []   # drained by the engine into the log
        self._next_id = 1

    # --- registration ------------------------------------------------------
    def register(self, speech: dict, promiser: str, global_turn: int) -> int:
        pid = self._next_id
        self._next_id += 1
        self.promises.append({
            "id": pid, "promiser": promiser, "target": speech["target"],
            "act": speech["act"], "resource": speech.get("resource"),
            "window": speech["window"], "own_turns_left": speech["window"],
            "made_turn": global_turn, "status": "open",
            "opportunities": 0, "held_resource_ever": False,
            "resolved_turn": None,
        })
        return pid

    def _open(self, **match):
        for p in self.promises:
            if p["status"] == "open" and all(p.get(k) == v for k, v in match.items()):
                yield p

    def _resolve(self, p, status, global_turn):
        p["status"] = status
        p["resolved_turn"] = global_turn
        self.resolutions.append({
            "type": "promise_resolved", "promise_id": p["id"],
            "promiser": p["promiser"], "target": p["target"], "act": p["act"],
            "resource": p["resource"], "status": status,
            "window": p["window"], "made_turn": p["made_turn"],
            "opportunities": p["opportunities"],
            "held_resource_ever": p["held_resource_ever"],
            "turn": global_turn,
        })

    # --- event feeds from the engine --------------------------------------
    def note_robber(self, actor: str, victim: str | None, global_turn: int):
        for p in self._open(promiser=actor, act="no_rob"):
            p["opportunities"] += 1
            if victim and victim == p["target"]:
                self._resolve(p, "broken", global_turn)

    def note_trade_exec(self, a: str, b: str, a_gave: dict, b_gave: dict,
                        global_turn: int):
        """A trade executed between a and b (a gave a_gave, b gave b_gave)."""
        for p in list(self._open(act="will_trade")):
            pair = {p["promiser"], p["target"]} == {a, b}
            if not pair:
                continue
            gave = a_gave if p["promiser"] == a else b_gave
            if gave.get(p["resource"], 0) > 0:
                self._resolve(p, "kept", global_turn)

    def tick_own_turn_end(self, promiser: str, holds: dict, global_turn: int):
        """Called when `promiser`'s turn ends. Advances their windows.

        A promise made DURING the promiser's own turn does not tick at that same
        turn's end — "my next N turns" starts with the turn after it was made.
        (Off-turn promises tick from the promiser's next own turn as normal.)"""
        for p in list(self._open(promiser=promiser)):
            if p["act"] == "will_trade" and holds.get(p["resource"], 0) > 0:
                p["held_resource_ever"] = True
            if p["made_turn"] == global_turn:
                continue
            p["own_turns_left"] -= 1
            if p["own_turns_left"] <= 0:
                if p["act"] == "no_rob":
                    self._resolve(p, "kept", global_turn)
                else:  # will_trade expired unfulfilled
                    self._resolve(p, "excused" if not p["held_resource_ever"]
                                  else "broken", global_turn)

    def close(self, global_turn: int):
        for p in list(self._open()):
            self._resolve(p, "censored", global_turn)

    # --- digest ------------------------------------------------------------
    def open_lines(self) -> list[str]:
        out = []
        for p in self._open():
            what = ("no robber on " + p["target"] if p["act"] == "no_rob"
                    else f"trade {p['resource']} to {p['target']}")
            out.append(f"OPEN PROMISE: {p['promiser']} -> {what}, "
                       f"{p['own_turns_left']} of their turn(s) left")
        return out

    def drain(self) -> list[dict]:
        out, self.resolutions = self.resolutions, []
        return out
