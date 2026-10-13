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
    def register(self, speech: dict, promiser: str, global_turn: int,
                 action_bound: str | None = None) -> int:
        pid = self._next_id
        self._next_id += 1
        self.promises.append({
            "id": pid, "promiser": promiser, "target": speech["target"],
            "act": speech["act"], "resource": speech.get("resource"),
            "window": speech["window"], "own_turns_left": speech["window"],
            "made_turn": global_turn, "status": "open",
            "opportunities": 0, "held_resource_ever": False,
            "attempts": 0, "resolved_turn": None,
            # schema v2: "offer" = the promise restates the live trade offer
            # (engine-executed, not a commitment beyond the move)
            "action_bound": action_bound,
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
            "opportunities": p["opportunities"], "attempts": p["attempts"],
            "held_resource_ever": p["held_resource_ever"],
            "action_bound": p.get("action_bound"),
            "turn": global_turn,
        })

    # --- event feeds from the engine --------------------------------------
    def note_robber(self, actor: str, victim: str | None, global_turn: int):
        for p in self._open(promiser=actor, act="no_rob"):
            p["opportunities"] += 1
            if victim and victim == p["target"]:
                self._resolve(p, "broken", global_turn)

    def note_trade_proposal(self, proposer: str, target: str, give: dict,
                            global_turn: int):
        """A genuine attempt: the promiser offered the promised resource to the
        target inside the window. If the target declines and the window expires,
        that is the counterparty's refusal, not the promiser's violation."""
        for p in self._open(promiser=proposer, act="will_trade", target=target):
            if (give or {}).get(p["resource"], 0) > 0:
                p["attempts"] += 1

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
                    if p["attempts"] > 0:
                        self._resolve(p, "declined", global_turn)
                    else:
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


def _target_match(spec, actual) -> bool:
    """A plan's stated target against what the engine did: player names,
    vertex/edge/hex ids ("V20", "E7", "H5"), case-insensitive; no stated
    target matches anything."""
    if spec in (None, ""):
        return True
    a = str(actual if actual is not None else "").strip().lower()
    s = str(spec).strip().lower()
    return bool(a) and (a == s or a.lstrip("veh") == s.lstrip("veh"))


class PlanLedger:
    """Public plans (schema v2): "I will build a settlement at V20 within 1
    turn". Same clock as promises (the planner's own turns; a plan made during
    the planner's turn starts ticking at the NEXT own-turn end).

    Terminal states:
        kept     — a matching own action (kind, and target if stated) inside the window
        broken   — expired without it, although the action was legal for the
                   planner at least once inside the window
        excused  — expired, and the action was never legal in the window
                   (no resources, no spot, no 7 rolled for a rob)
        censored — still open at game end
    A plan stated on the very decision that executes it is narration; the
    engine tags it action-bound and does not register it here."""

    def __init__(self):
        self.plans: list[dict] = []
        self.resolutions: list[dict] = []
        self._next_id = 1

    def register(self, speech: dict, planner: str, global_turn: int) -> int:
        pid = self._next_id
        self._next_id += 1
        self.plans.append({
            "id": pid, "planner": planner, "do": speech["do"],
            "target": speech.get("target"), "window": speech["window"],
            "own_turns_left": speech["window"], "made_turn": global_turn,
            "status": "open", "legal_ever": False, "resolved_turn": None,
        })
        return pid

    def _open(self, **match):
        for p in self.plans:
            if p["status"] == "open" and all(p.get(k) == v for k, v in match.items()):
                yield p

    def _resolve(self, p, status, global_turn):
        p["status"] = status
        p["resolved_turn"] = global_turn
        self.resolutions.append({
            "type": "plan_resolved", "plan_id": p["id"], "planner": p["planner"],
            "do": p["do"], "target": p["target"], "status": status,
            "window": p["window"], "made_turn": p["made_turn"],
            "legal_ever": p["legal_ever"], "turn": global_turn,
        })

    def note_legal(self, actor: str, legal: list, global_turn: int):
        """The actor's legal actions at a decision point inside their turn."""
        for p in self._open(planner=actor):
            if p["do"] in legal:
                p["legal_ever"] = True

    def note_action(self, actor: str, kind: str, target, global_turn: int):
        """The actor did `kind` (a PLAN_ACTIONS name) with `target` (a vertex /
        edge / hex id string or a player name, or None)."""
        for p in list(self._open(planner=actor, do=kind)):
            if _target_match(p["target"], target):
                self._resolve(p, "kept", global_turn)

    def tick_own_turn_end(self, planner: str, global_turn: int):
        for p in list(self._open(planner=planner)):
            if p["made_turn"] == global_turn:
                continue
            p["own_turns_left"] -= 1
            if p["own_turns_left"] <= 0:
                self._resolve(p, "broken" if p["legal_ever"] else "excused", global_turn)

    def close(self, global_turn: int):
        for p in list(self._open()):
            self._resolve(p, "censored", global_turn)

    def open_lines(self) -> list[str]:
        out = []
        for p in self._open():
            tgt = f" {p['target']}" if p.get("target") else ""
            out.append(f"OPEN PLAN: {p['planner']} -> {p['do'].replace('_', ' ')}{tgt}, "
                       f"{p['own_turns_left']} of their turn(s) left")
        return out

    def drain(self) -> list[dict]:
        out, self.resolutions = self.resolutions, []
        return out
