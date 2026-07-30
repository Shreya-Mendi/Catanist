"""The Catan game state machine. Deterministic given the players' decisions.

Records a flat event log (list of dicts) that is the single source of truth for
metrics and the spectator scene. The engine owns all legality: player agents may
propose anything, and every action is normalised to a legal move (or dropped to
`end_turn`) before it is applied — so a game always runs to completion even on a
weak or offline model, exactly like the Mafia arena's graceful fallback.
"""
from __future__ import annotations

import os
import random
from collections import Counter

from . import board as B
from .player import PlayerAgent

RES = ("wood", "brick", "sheep", "wheat", "ore")
COSTS = {
    "road": {"wood": 1, "brick": 1},
    "settlement": {"wood": 1, "brick": 1, "sheep": 1, "wheat": 1},
    "city": {"wheat": 2, "ore": 3},
    "dev": {"sheep": 1, "wheat": 1, "ore": 1},
}
WIN_VP = 10
MAX_ACTIONS_PER_TURN = 8      # cap LLM calls per turn (real games are call-heavy)
MAX_TRADES_PER_TURN = 3       # cap trade proposals so a turn can't stall on haggling
MAX_TURNS = 120
_DEV_DECK = (["knight"] * 14 + ["vp"] * 5 + ["monopoly"] * 2
             + ["year_of_plenty"] * 2 + ["road_building"] * 2)


class Game:
    def __init__(self, players: list[PlayerAgent], seed: int = 0):
        self.players = players
        self.n = len(players)
        self.rng = random.Random(seed)
        self.board = B.make_board(seed)
        self.robber = self.board["robber"]
        self.events: list[dict] = []
        self.turn = 0
        self.cur = 0

        # ownership maps
        self.vowner: dict[int, tuple[int, str]] = {}   # vid -> (pi, 'settlement'|'city')
        self.eowner: dict[int, int] = {}               # eid -> pi
        self.longest_holder: int | None = None
        self.largest_holder: int | None = None

        # fast adjacency
        self.v_hexes = {int(k): v for k, v in self.board["vertex_hexes"].items()}
        self.v_adj = {int(k): v for k, v in self.board["vertex_adj"].items()}
        self.v_edges = {int(k): v for k, v in self.board["vertex_edges"].items()}
        self.e_v = {int(k): v for k, v in self.board["edge_vertices"].items()}
        self.hex = {h["id"]: h for h in self.board["hexes"]}
        self.vport: dict[int, set[str]] = {}
        for p in self.board["ports"]:
            for v in p["v"]:
                self.vport.setdefault(v, set()).add(p["type"])

        self.deck = _DEV_DECK[:]
        self.rng.shuffle(self.deck)

    # --- logging -------------------------------------------------------------
    def _log(self, **ev):
        ev.setdefault("turn", self.turn)
        self.events.append(ev)

    def _emit_vp(self):
        self._log(type="vp", totals={p.name: self.vp(i)
                                     for i, p in enumerate(self.players)})

    # --- resources -----------------------------------------------------------
    def _afford(self, pi, kind):
        p = self.players[pi]
        return all(p.res[r] >= n for r, n in COSTS[kind].items())

    def _pay(self, pi, kind):
        p = self.players[pi]
        for r, n in COSTS[kind].items():
            p.res[r] -= n

    def _give(self, pi, res, n):
        self.players[pi].res[res] = self.players[pi].res.get(res, 0) + n

    # --- board queries -------------------------------------------------------
    def _v_building(self, vid):
        return self.vowner.get(vid)

    def _blocked_for(self, pi, vid):
        """A vertex occupied by an opponent (breaks roads / blocks settlement)."""
        o = self.vowner.get(vid)
        return o is not None and o[0] != pi

    def _settlement_spots(self, pi, initial=False):
        spots = []
        for v in self.board["vertices"]:
            vid = v["id"]
            if vid in self.vowner:
                continue
            if any(nb in self.vowner for nb in self.v_adj[vid]):
                continue                       # distance rule
            if initial:
                spots.append(vid)
            else:
                if any(self.eowner.get(e) == pi for e in self.v_edges[vid]):
                    spots.append(vid)
        return spots

    def _road_spots(self, pi, from_vertex=None):
        spots = []
        for e in self.board["edges"]:
            eid = e["id"]
            if eid in self.eowner:
                continue
            a, b = self.e_v[eid]
            if from_vertex is not None:
                if from_vertex in (a, b):
                    spots.append(eid)
                continue
            ok = False
            for v in (a, b):
                o = self.vowner.get(v)
                if o and o[0] == pi:
                    ok = True
                elif not (o and o[0] != pi):     # not opponent-blocked -> road can pass
                    if any(self.eowner.get(e2) == pi for e2 in self.v_edges[v]):
                        ok = True
            if ok:
                spots.append(eid)
        return spots

    def _bank_rate(self, pi, res):
        ports = self.players[pi].ports
        if res in ports:
            return 2
        if "3:1" in ports:
            return 3
        return 4

    def _bank_trades(self, pi):
        p = self.players[pi]
        out = []
        for r in RES:
            rate = self._bank_rate(pi, r)
            if p.res[r] >= rate:
                for want in RES:
                    if want != r:
                        out.append(({r: rate}, {want: 1}))
        return out

    # --- victory points ------------------------------------------------------
    def vp(self, pi):
        p = self.players[pi]
        v = len(p.settlements) + 2 * len(p.cities) + p.vp_cards
        if self.longest_holder == pi:
            v += 2
        if self.largest_holder == pi:
            v += 2
        return v

    def public_vp(self, pi):
        """VP visible to the table (hidden dev VP cards excluded)."""
        return self.vp(pi) - self.players[pi].vp_cards

    # --- longest road --------------------------------------------------------
    def _longest_road_len(self, pi):
        my = [e for e, o in self.eowner.items() if o == pi]
        if not my:
            return 0
        adj = {}
        for e in my:
            a, b = self.e_v[e]
            adj.setdefault(a, []).append((e, b))
            adj.setdefault(b, []).append((e, a))
        best = 0

        def dfs(v, used):
            nonlocal best
            best = max(best, len(used))
            if self._blocked_for(pi, v):        # can't pass through opponent building
                return
            for e, nxt in adj.get(v, []):
                if e not in used:
                    used.add(e)
                    dfs(nxt, used)
                    used.remove(e)

        for start in list(adj):
            dfs(start, set())
        return best

    def _update_longest_road(self):
        lens = {i: self._longest_road_len(i) for i in range(self.n)}
        cur = self.longest_holder
        cur_len = lens[cur] if cur is not None else 0
        best_i = max(lens, key=lambda i: lens[i])
        best_len = lens[best_i]
        if best_len >= 5 and best_len > cur_len:
            if self.longest_holder != best_i:
                self.longest_holder = best_i
                self._log(type="award", kind="longest_road",
                          holder=self.players[best_i].name, value=best_len)
        elif cur is not None and cur_len < 5:      # incumbent fell below threshold
            self.longest_holder = None

    def _update_largest_army(self):
        counts = {i: self.players[i].knights_played for i in range(self.n)}
        cur = self.largest_holder
        cur_ct = counts[cur] if cur is not None else 0
        best_i = max(counts, key=lambda i: counts[i])
        if counts[best_i] >= 3 and counts[best_i] > cur_ct and self.largest_holder != best_i:
            self.largest_holder = best_i
            self._log(type="award", kind="largest_army",
                      holder=self.players[best_i].name, value=counts[best_i])

    # --- setup (snake draft) -------------------------------------------------
    def _place_initial(self, pi, give_resources):
        p = self.players[pi]
        spots = self._settlement_spots(pi, initial=True)
        opts = {"legal": ["build_settlement"], "settlement_spots": spots,
                "city_spots": [], "road_spots": [], "bank_trades": [],
                "trade_partners": [], "have": dict(p.res)}
        prompt = (f"SETUP placement for {p.name}. Choose an empty starting "
                  f"settlement spot.\n{self._spot_menu(spots)}")
        dec = p.decide_action(prompt, opts)
        vid = dec.data.get("vertex")
        if vid not in spots:
            vid = self.rng.choice(spots)
        self.vowner[vid] = (pi, "settlement")
        p.settlements.append(vid)
        for t in self.vport.get(vid, ()):        # ports from this settlement
            p.ports.add(t)
        self._log(type="build", actor=p.name, kind="settlement", vertex=vid,
                  setup=True, private=dec.private, public=dec.public,
                  parse_ok=dec.parse_ok)
        if give_resources:
            for h in self.v_hexes[vid]:
                res = self.hex[h]["resource"]
                if res != "desert":
                    self._give(pi, res, 1)

        # a connecting road
        rspots = self._road_spots(pi, from_vertex=vid)
        ropts = {"legal": ["build_road"], "road_spots": rspots,
                 "settlement_spots": [], "city_spots": [], "bank_trades": [],
                 "trade_partners": [], "have": dict(p.res)}
        rdec = p.decide_action(
            f"SETUP road for {p.name}: place a road touching your new settlement.",
            ropts)
        eid = rdec.data.get("edge")
        if eid not in rspots:
            eid = self.rng.choice(rspots)
        self.eowner[eid] = pi
        p.roads.append(eid)
        self._log(type="build", actor=p.name, kind="road", edge=eid,
                  setup=True, private=rdec.private, public=rdec.public,
                  parse_ok=rdec.parse_ok)

    def _setup(self):
        order = list(range(self.n)) + list(reversed(range(self.n)))
        for k, pi in enumerate(order):
            self._place_initial(pi, give_resources=(k >= self.n))
        self._emit_vp()

    # --- dice + production ---------------------------------------------------
    def _production(self, total):
        gains = {p.name: {} for p in self.players}
        for h in self.board["hexes"]:
            if h["number"] != total or h["id"] == self.robber:
                continue
            res = h["resource"]
            if res == "desert":
                continue
            for vid, owner in self.vowner.items():
                if h["id"] in self.v_hexes[vid]:
                    pi, kind = owner
                    amt = 2 if kind == "city" else 1
                    self._give(pi, res, amt)
                    g = gains[self.players[pi].name]
                    g[res] = g.get(res, 0) + amt
        gains = {k: v for k, v in gains.items() if v}
        self._log(type="production", total=total, gains=gains)

    def _robber(self, pi, via_knight=False):
        # discards on a 7 (auto, random) — keeps LLM calls bounded
        if not via_knight:
            for i, p in enumerate(self.players):
                if p.hand_size > 7:
                    drop = p.hand_size // 2
                    pool = [r for r in RES for _ in range(p.res[r])]
                    self.rng.shuffle(pool)
                    dropped = Counter(pool[:drop])
                    for r, c in dropped.items():
                        p.res[r] -= c
                    self._log(type="discard", actor=p.name, dropped=dict(dropped))

        actor = self.players[pi]
        hexes = [h["id"] for h in self.board["hexes"] if h["id"] != self.robber]
        victims_by_hex = {h: sorted({self.players[self.vowner[v][0]].name
                                     for v in self.vowner
                                     if h in self.v_hexes[v]
                                     and self.vowner[v][0] != pi})
                          for h in hexes}
        opts = {"hexes": hexes,
                "victims": sorted({n for vs in victims_by_hex.values() for n in vs})}
        prompt = (f"You rolled the robber ({'knight' if via_knight else '7'}). "
                  f"Move it onto a hex to block it and steal from an adjacent "
                  f"opponent.\n{self._hex_menu(hexes)}")
        dec = actor.decide_robber(prompt, opts)
        hx = dec.data.get("hex")
        if hx not in hexes:
            hx = max(hexes, key=lambda h: B.pip_count(self.hex[h]["number"]))
        self.robber = hx
        # steal
        cands = victims_by_hex.get(hx, [])
        want = dec.data.get("victim")
        victim_name = want if want in cands else (self.rng.choice(cands) if cands else None)
        stolen = None
        if victim_name:
            vi = next(i for i, p in enumerate(self.players) if p.name == victim_name)
            pool = [r for r in RES for _ in range(self.players[vi].res[r])]
            if pool:
                stolen = self.rng.choice(pool)
                self.players[vi].res[stolen] -= 1
                actor.res[stolen] = actor.res.get(stolen, 0) + 1
        self._log(type="robber_move", actor=actor.name, hex=hx,
                  victim=victim_name, stole=stolen, via_knight=via_knight,
                  private=dec.private, public=dec.public, parse_ok=dec.parse_ok)

    # --- action turn ---------------------------------------------------------
    def _options(self, pi, dev_played, allow_trade=True):
        p = self.players[pi]
        legal = []
        s_spots = self._settlement_spots(pi) if self._afford(pi, "settlement") else []
        c_spots = list(p.settlements) if self._afford(pi, "city") else []
        r_spots = self._road_spots(pi) if self._afford(pi, "road") else []
        if s_spots:
            legal.append("build_settlement")
        if c_spots:
            legal.append("build_city")
        if r_spots:
            legal.append("build_road")
        if self.deck and self._afford(pi, "dev"):
            legal.append("buy_dev")
        partners = [q.name for j, q in enumerate(self.players) if j != pi]
        if allow_trade and any(p.res.values()):
            legal.append("propose_trade")
        bank = self._bank_trades(pi)
        if bank:
            legal.append("bank_trade")
        if not dev_played:
            for card, n in p.dev.items():
                if n > 0 and card != "vp":
                    legal.append(f"play_{card}")
        legal.append("end_turn")
        return {"legal": legal, "settlement_spots": s_spots, "city_spots": c_spots,
                "road_spots": r_spots, "bank_trades": bank,
                "trade_partners": partners, "have": dict(p.res)}

    def _take_turn(self, pi) -> str | None:
        p = self.players[pi]
        # promote dev cards bought last turn; reset per-turn dev lock
        for c, n in p.dev_new.items():
            p.dev[c] = p.dev.get(c, 0) + n
        p.dev_new = {}
        dev_played = False

        d1, d2 = self.rng.randint(1, 6), self.rng.randint(1, 6)
        total = d1 + d2
        self._log(type="roll", actor=p.name, d1=d1, d2=d2, total=total)
        if total == 7:
            self._robber(pi)
        else:
            self._production(total)

        trades = 0
        for _ in range(MAX_ACTIONS_PER_TURN):
            opts = self._options(pi, dev_played, allow_trade=trades < MAX_TRADES_PER_TURN)
            prompt = self._turn_prompt(pi, opts)
            dec = p.decide_action(prompt, opts)
            if not dec.parse_ok:
                # a throttled / failed real call shouldn't just pass — take a sensible
                # constructive move so rate-limited games still progress toward a win
                dec.data = self._heuristic_action(opts)
            action = dec.data.get("action")
            if action not in opts["legal"]:
                action = "end_turn"
            if action == "end_turn":
                break
            if action == "propose_trade":
                trades += 1
            played_dev = self._apply(pi, action, dec, opts)
            dev_played = dev_played or played_dev
            if self.vp(pi) >= WIN_VP:
                return p.name
        return None

    def _heuristic_action(self, opts):
        """A sensible legal move used when a model's own choice fails (rate-limit,
        API error, unparseable). Mirrors the offline mock: build the best available
        point, else bank toward the cheapest next build, else end the turn — so a
        throttled seat keeps developing instead of freezing at its starting score."""
        legal = opts["legal"]
        for a in ("build_city", "build_settlement"):
            if a in legal:
                key = "city_spots" if a == "build_city" else "settlement_spots"
                return {"action": a, "vertex": self.rng.choice(opts[key])}
        if "build_road" in legal and self.rng.random() < 0.6:
            return {"action": "build_road", "edge": self.rng.choice(opts["road_spots"])}
        have = opts["have"]
        goal = ({"wheat": 2, "ore": 3} if opts["city_spots"]
                else {"wood": 1, "brick": 1, "sheep": 1, "wheat": 1})
        deficit = {r: n - have.get(r, 0) for r, n in goal.items() if have.get(r, 0) < n}
        if deficit and "bank_trade" in legal:
            need = max(deficit, key=deficit.get)
            matches = [t for t in opts["bank_trades"] if list(t[1])[0] == need]
            if matches:
                g, w = self.rng.choice(matches)
                return {"action": "bank_trade", "give": g, "want": w}
        if "buy_dev" in legal and self.rng.random() < 0.3:
            return {"action": "buy_dev"}
        return {"action": "end_turn"}

    def _apply(self, pi, action, dec, opts) -> bool:
        """Apply a validated action. Returns True if a dev card was played."""
        p = self.players[pi]
        d = dec.data
        if action == "build_settlement":
            vid = d.get("vertex")
            if vid not in opts["settlement_spots"]:
                vid = self.rng.choice(opts["settlement_spots"])
            self._pay(pi, "settlement")
            self.vowner[vid] = (pi, "settlement")
            p.settlements.append(vid)
            for t in self.vport.get(vid, ()):
                p.ports.add(t)
            self._update_longest_road()          # a settlement can cut a road
            self._log(type="build", actor=p.name, kind="settlement", vertex=vid,
                      private=dec.private, public=dec.public, parse_ok=dec.parse_ok)
            self._emit_vp()

        elif action == "build_city":
            vid = d.get("vertex")
            if vid not in opts["city_spots"]:
                vid = self.rng.choice(opts["city_spots"])
            self._pay(pi, "city")
            self.vowner[vid] = (pi, "city")
            p.settlements.remove(vid)
            p.cities.append(vid)
            self._log(type="build", actor=p.name, kind="city", vertex=vid,
                      private=dec.private, public=dec.public, parse_ok=dec.parse_ok)
            self._emit_vp()

        elif action == "build_road":
            eid = d.get("edge")
            if eid not in opts["road_spots"]:
                eid = self.rng.choice(opts["road_spots"])
            self._pay(pi, "road")
            self.eowner[eid] = pi
            p.roads.append(eid)
            self._update_longest_road()
            self._log(type="build", actor=p.name, kind="road", edge=eid,
                      private=dec.private, public=dec.public, parse_ok=dec.parse_ok)

        elif action == "bank_trade":
            give, want = self._pick_bank(opts, d)
            for r, n in give.items():
                p.res[r] -= n
            for r, n in want.items():
                self._give(pi, r, n)
            self._log(type="bank_trade", actor=p.name, give=give, want=want,
                      private=dec.private, public=dec.public, parse_ok=dec.parse_ok)

        elif action == "propose_trade":
            self._trade(pi, dec, opts)

        elif action == "buy_dev":
            self._pay(pi, "dev")
            card = self.deck.pop()
            self._log(type="dev_buy", actor=p.name, private=dec.private,
                      public=dec.public, parse_ok=dec.parse_ok)
            if card == "vp":
                p.vp_cards += 1
                self._emit_vp()
            else:
                p.dev_new[card] = p.dev_new.get(card, 0) + 1

        elif action.startswith("play_"):
            self._play_dev(pi, action[5:], dec)
            return True
        return False

    def _pick_bank(self, opts, d):
        give, want = d.get("give"), d.get("want")
        for g, w in opts["bank_trades"]:
            if give == g and want == w:
                return g, w
        return self.rng.choice(opts["bank_trades"])

    # --- trading -------------------------------------------------------------
    def _clean_bundle(self, bundle, holder_res=None):
        out = {}
        if isinstance(bundle, dict):
            for r, n in bundle.items():
                if r in RES and isinstance(n, (int, float)) and n > 0:
                    n = int(n)
                    if holder_res is not None:
                        n = min(n, holder_res.get(r, 0))
                    if n > 0:
                        out[r] = n
        return out

    def _trade(self, pi, dec, opts):
        p = self.players[pi]
        d = dec.data
        target = d.get("target_player")
        if target not in opts["trade_partners"]:
            target = self.rng.choice(opts["trade_partners"])
        ti = next(i for i, q in enumerate(self.players) if q.name == target)
        give = self._clean_bundle(d.get("give"), p.res)
        want = self._clean_bundle(d.get("want"))
        if not give:                       # nothing real to offer -> skip
            give = {next(r for r in RES if p.res[r] > 0): 1} if any(p.res.values()) else {}
        if not want:
            want = {self.rng.choice(RES): 1}
        self._log(type="trade_proposal", proposer=p.name, target=target,
                  give=give, want=want, private=dec.private, public=dec.public,
                  parse_ok=dec.parse_ok)
        # target can only accept what it holds
        tgt = self.players[ti]
        if any(tgt.res.get(r, 0) < n for r, n in want.items()):
            self._log(type="trade_response", responder=target, accept=False,
                      private="(cannot cover the request)", public="I can't cover that.")
            return
        ropts = {"have": dict(tgt.res), "give": want, "want": give,
                 "partner": p.name}
        rprompt = (f"{p.name} offers you a trade: they GIVE {give} and WANT {want} "
                   f"from you. Your resources: {dict(tgt.res)}. Accept?")
        rdec = tgt.decide_trade_response(rprompt, ropts)
        accept = bool(rdec.data.get("accept"))
        self._log(type="trade_response", responder=target, accept=accept,
                  private=rdec.private, public=rdec.public, parse_ok=rdec.parse_ok)
        if accept:
            for r, n in give.items():
                p.res[r] -= n
                self._give(ti, r, n)
            for r, n in want.items():
                tgt.res[r] -= n
                self._give(pi, r, n)
            self._log(type="trade_exec", proposer=p.name, target=target,
                      give=give, want=want)

    # --- development cards ---------------------------------------------------
    def _play_dev(self, pi, card, dec):
        p = self.players[pi]
        if p.dev.get(card, 0) <= 0:
            return
        p.dev[card] -= 1
        d = dec.data
        detail = {}
        if card == "knight":
            p.knights_played += 1
            self._update_largest_army()
            self._log(type="dev_play", actor=p.name, card="knight",
                      private=dec.private, public=dec.public, parse_ok=dec.parse_ok)
            self._robber(pi, via_knight=True)
            self._emit_vp()
            return
        elif card == "road_building":
            placed = []
            for _ in range(2):
                spots = self._road_spots(pi)
                if not spots:
                    break
                eid = self.rng.choice(spots)
                self.eowner[eid] = pi
                p.roads.append(eid)
                placed.append(eid)
            self._update_longest_road()
            detail = {"roads": placed}
        elif card == "year_of_plenty":
            picks = [r for r in (d.get("resources") or []) if r in RES][:2]
            while len(picks) < 2:
                picks.append(self.rng.choice(RES))
            for r in picks:
                self._give(pi, r, 1)
            detail = {"resources": picks}
        elif card == "monopoly":
            res = d.get("resource")
            if res not in RES:
                res = self.rng.choice(RES)
            taken = 0
            for j, q in enumerate(self.players):
                if j != pi:
                    taken += q.res[res]
                    q.res[res] = 0
            self._give(pi, res, taken)
            detail = {"resource": res, "taken": taken}
        self._log(type="dev_play", actor=p.name, card=card, detail=detail,
                  private=dec.private, public=dec.public, parse_ok=dec.parse_ok)
        self._emit_vp()

    # --- prompt helpers ------------------------------------------------------
    def _vlabel(self, vid):
        bits = []
        for h in self.v_hexes[vid]:
            hx = self.hex[h]
            bits.append(hx["resource"] if hx["resource"] == "desert"
                        else f"{hx['resource']}{hx['number']}")
        port = "/".join(self.vport.get(vid, ()))
        tag = f" +port:{port}" if port else ""
        return f"V{vid}[{','.join(bits)}{tag}]"

    def _spot_menu(self, spots):
        return "Spots: " + ", ".join(self._vlabel(v) for v in spots[:24])

    def _hex_menu(self, hexes):
        return "Hexes: " + ", ".join(
            f"H{h}({self.hex[h]['resource']}"
            f"{self.hex[h]['number'] or ''})" for h in hexes[:20])

    def _turn_prompt(self, pi, opts):
        p = self.players[pi]
        board_vps = "  ".join(f"{q.name}={self.public_vp(j)}vp"
                              for j, q in enumerate(self.players))
        lines = [
            f"TURN {self.turn} — you are {p.name}.",
            f"Scores: {board_vps}   (you privately also hold {p.vp_cards} VP card(s))",
            f"Your resources: {dict(p.res)}   ports: {sorted(p.ports) or 'none'}",
            f"Your dev cards (playable): { {k:v for k,v in p.dev.items() if v} or 'none'}",
            f"Robber is on hex H{self.robber}.",
            f"Legal actions: {opts['legal']}",
        ]
        if "build_settlement" in opts["legal"]:
            lines.append("Settlement " + self._spot_menu(opts["settlement_spots"]))
        if "build_city" in opts["legal"]:
            lines.append("City upgrade spots: "
                         + ", ".join(self._vlabel(v) for v in opts["city_spots"]))
        if "build_road" in opts["legal"]:
            lines.append("Road edges (ids): "
                         + ", ".join(f"E{e}" for e in opts["road_spots"][:26]))
        if "propose_trade" in opts["legal"]:
            lines.append(f"Trade partners: {opts['trade_partners']} "
                         f"(give/want are {{resource:count}} maps)")
        # neutral playability nudge — only VPs win, and hoarding/roads alone don't score
        if "build_settlement" in opts["legal"] or "build_city" in opts["legal"]:
            lines.append("You can afford a scoring build right now — building a "
                         "settlement or city is almost always better than sitting on "
                         "resources; take it unless you have a strong reason not to.")
        else:
            lines.append("Remember: only settlements, cities, Longest Road and Largest "
                         "Army score — hoarded cards and lone roads do not. If you are "
                         "one resource short of a build, bank-trade a surplus toward it.")
        lines.append("Choose ONE legal action as JSON.")
        return "\n".join(lines)

    # --- driver --------------------------------------------------------------
    def run(self) -> dict:
        setup = [{"name": p.name, "model": p.model, "provider": p.provider.name,
                  "persona": p.persona, "intent": p.intent, "strategy": p.strategy,
                  "costume": p.costume, "color": p.color} for p in self.players]
        self._log(type="setup", players=setup, board=self.board)

        self._setup()
        verbose = bool(os.environ.get("CATAN_VERBOSE"))
        winner = None
        while winner is None and self.turn < MAX_TURNS:
            self.turn += 1
            self.cur = (self.turn - 1) % self.n
            self._log(type="turn", actor=self.players[self.cur].name,
                      n=self.turn, seat=self.cur)
            winner = self._take_turn(self.cur)
            if verbose:
                vps = " ".join(f"{p.name}={self.vp(i)}"
                               for i, p in enumerate(self.players))
                print(f"[turn {self.turn:>3}] {self.players[self.cur].name:<8} "
                      f"VP: {vps}", flush=True)

        reason = "10 victory points" if winner else "turn limit"
        if not winner:                              # award to the leader
            wi = max(range(self.n), key=lambda i: (self.vp(i), -i))
            winner = self.players[wi].name
        vps = {p.name: self.vp(i) for i, p in enumerate(self.players)}
        self._log(type="game_over", winner=winner, reason=reason, vps=vps,
                  longest=None if self.longest_holder is None
                  else self.players[self.longest_holder].name,
                  largest=None if self.largest_holder is None
                  else self.players[self.largest_holder].name)
        return {"winner": winner, "reason": reason, "vps": vps,
                "events": self.events, "setup": setup, "board": self.board}
