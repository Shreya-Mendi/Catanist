"""The three strategy-priming arms — the game-theory knob, à la the Mafia arena.

    none     — no strategy text (the baseline / control)
    placebo  — length-matched, strategy-free text (Catan history trivia). Isolates
               the *content* of the theory from the mere presence of an authoritative
               briefing: without it you cannot tell "the strategy helped" from "we
               added ~1.5k tokens telling it to try hard".
    taught   — explicit Catan strategy: pip-probability, diversification, ports,
               trade expected-value, denying the leader, and the tempo of Longest
               Road / Largest Army / dev cards.

The taught block is faction-neutral (there are no factions in Catan) — it states
the general principles every seat can apply, so no arm hands one player a private
edge beyond "think harder about the same game".
"""
from __future__ import annotations

NONE = ""

TAUGHT = """
STRATEGY BRIEFING — CATAN THEORY (apply this explicitly)
Reason about this game quantitatively, and make that reasoning explicit in your
private_reasoning. Apply these established principles:
1. NUMBERS ARE PROBABILITIES. A tile's dots equal the number of dice combinations
   that roll it: 6 and 8 (five dots) are the most frequent, 2 and 12 (one dot) the
   rarest. Value a settlement by the total dots it touches, not by how many tiles.
2. DIVERSIFY, THEN SPECIALISE. Early on, cover as many of the five resources and as
   many distinct numbers as you can, so a single number or robber cannot starve you.
   Cities need ore+wheat, so secure those before racing settlements.
3. PORTS ARE LEVERAGE. A 2:1 port turns a surplus resource into a reliable pump; a
   3:1 port beats the 4:1 bank. Weigh a port spot against a raw-production spot.
4. TRADE ON EXPECTED VALUE, NOT VIBES. Only accept a trade whose resources advance
   your next build more than they advance your partner's. Every trade you give a
   rival is production you are handing them — think one build ahead for both sides.
5. DENY THE LEADER. Victory is a race to 10, so a resource or block that slows the
   current leader is often worth more than the same move made against a trailer.
   Aim the robber at the leader's best number; refuse trades that fund their win.
6. TEMPO AND THE HIDDEN POINTS. Longest Road (>=5) and Largest Army (>=3 knights) are
   +2 each and can swing quietly; dev cards can hide victory points. Track who is
   close to these, and time your own push so opponents cannot react.
""".strip()

PLACEBO = """
BACKGROUND BRIEFING — HISTORY OF THE GAME (context only)
Catan was designed by Klaus Teuber, a dental technician near Frankfurt, and first
published in Germany in 1995 as Die Siedler von Catan. Teuber had already won game
awards in the early 1990s, and he developed Catan slowly over several years, testing
versions with his family before it reached a publisher. It won the Spiel des Jahres
in 1995 and quickly became one of the defining titles of the modern German-style
board-game movement.
The game spread internationally over the following years, appearing in English as
The Settlers of Catan and later simply as Catan, and it has since been translated
into dozens of languages. Its hexagonal modular board, drawn fresh each game, and
its emphasis on trading and negotiation rather than direct conflict were unusual for
a mainstream title at the time and were widely imitated afterwards.
Numerous expansions and spin-offs have followed, including seafaring and
larger-player variants, themed editions, and travel and card-game versions. The
brand has been managed for many years by a dedicated studio, and Catan is often
cited as a gateway title that introduced a broad audience to hobby board gaming.
Klaus Teuber continued to design games associated with the Catan world for the rest
of his career, and the series remains among the best-selling board games worldwide.
""".strip()

BLOCKS = {"none": NONE, "placebo": PLACEBO, "taught": TAUGHT}
ARMS = list(BLOCKS)


def block(arm: str) -> str:
    return BLOCKS.get(arm, NONE)


def lengths() -> dict[str, int]:
    return {k: len(v) for k, v in BLOCKS.items()}


def length_match_ratio() -> float:
    return len(TAUGHT) / len(PLACEBO) if PLACEBO else 0.0
