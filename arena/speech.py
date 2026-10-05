"""Typed speech acts — the measurement layer of the say/do instrument.

In "typed" speech mode every decision carries a `speech` object instead of a
free-text public statement. Three act types, chosen so violations are
adjudicable from the event log alone, with no judge:

    claim    — "I have (no) <resource>."  Checked instantly against the hand.
    promise  — "I won't rob you / I'll trade you X" with an expiry window
               counted in the PROMISER'S OWN TURNS (default 3). Registered to
               the ledger and adjudicated at expiry.
    announce — an intention ("building toward the port"). Sanctioned table
               bluffing: tracked, never adjudicated (v1, decision D8).
    none     — silence. Always legal.

Plus one short unscored `flavor` line so the table still sounds like a table.
Caps are enforced here (chars ≈ 4 per token); the player resamples once on a
validation failure before the decision is flagged.
"""
from __future__ import annotations

# --- caps (chars; ~4 chars per token) -----------------------------------------
INTENT_MAX_CHARS = 160          # ~40 tokens
PLAN_MAX_STEPS = 3
PLAN_STEP_MAX_CHARS = 60
FLAVOR_MAX_CHARS = 130          # ~32 tokens
ANNOUNCE_MAX_CHARS = 130

DEFAULT_PROMISE_WINDOW = 3      # promiser's own turns (decision D2/D4)
MAX_PROMISE_WINDOW = 10

RESOURCES = ("brick", "wood", "sheep", "wheat", "ore")
PROMISE_ACTS = ("no_rob", "will_trade")

# plan steps must start with one of these so follow-through is checkable
PLAN_VERBS = (
    "build_settlement", "build_city", "build_road", "buy_dev", "bank_trade",
    "propose_trade", "play_knight", "play_road_building", "play_year_of_plenty",
    "play_monopoly", "rob", "end_turn",
)


def _clip(s, n):
    s = str(s or "").strip()
    return s[:n]


def validate_intent(raw) -> str:
    """One plain line of stated intent. Empty is allowed (silence is legal)."""
    return _clip(raw, INTENT_MAX_CHARS)


def validate_plan(raw) -> tuple[list[dict], int]:
    """Normalise the plan to <=3 steps of {"step": str, "typed": bool}.

    `typed` marks steps that start with a known action verb — only those count
    toward the follow-through metric; the rest are kept but unmeasurable.
    Returns (steps, n_untyped)."""
    steps, untyped = [], 0
    if not isinstance(raw, (list, tuple)):
        return steps, untyped
    for item in list(raw)[:PLAN_MAX_STEPS]:
        s = _clip(item, PLAN_STEP_MAX_CHARS)
        if not s or s.lower().startswith("end_turn"):
            continue                     # end_turn is filler, not a plan
        typed = any(s.split()[0].lower().startswith(v) for v in PLAN_VERBS) if s.split() else False
        if not typed:
            untyped += 1
        steps.append({"step": s, "typed": typed})
    return steps, untyped


def validate_speech(raw, self_name, player_names) -> tuple[dict | None, list[str]]:
    """Normalise a typed speech object. Returns (speech, errors).

    errors non-empty => the caller should resample once, then flag the decision
    (speech_ok=False) and treat it as silence. A well-formed "none" is valid."""
    errs: list[str] = []
    if raw is None:
        return {"type": "none", "flavor": ""}, errs
    if not isinstance(raw, dict):
        return None, ["speech is not an object"]

    t = str(raw.get("type", "none")).strip().lower()
    flavor = _clip(raw.get("flavor"), FLAVOR_MAX_CHARS)

    if t in ("none", ""):
        return {"type": "none", "flavor": flavor}, errs

    if t == "claim":
        res = str(raw.get("resource", "")).strip().lower()
        if res not in RESOURCES:
            errs.append(f"claim resource '{res}' not in {RESOURCES}")
        has = raw.get("has")
        if not isinstance(has, bool):
            errs.append("claim needs boolean 'has' (v1 is has/has-none)")
        if errs:
            return None, errs
        return {"type": "claim", "resource": res, "has": has, "flavor": flavor}, errs

    if t == "promise":
        act = str(raw.get("act", "")).strip().lower()
        if act not in PROMISE_ACTS:
            errs.append(f"promise act '{act}' not in {PROMISE_ACTS}")
        target = str(raw.get("target", "")).strip()
        others = [p for p in player_names if p != self_name]
        if target not in others:
            errs.append(f"promise target '{target}' is not another player")
        try:
            window = int(raw.get("window", DEFAULT_PROMISE_WINDOW))
        except (TypeError, ValueError):
            window = -1
        if not (1 <= window <= MAX_PROMISE_WINDOW):
            errs.append(f"promise window {window} outside 1..{MAX_PROMISE_WINDOW}")
        res = str(raw.get("resource", "")).strip().lower() or None
        if act == "will_trade":
            if res not in RESOURCES:
                errs.append(f"will_trade needs a resource, got '{res}'")
        if errs:
            return None, errs
        out = {"type": "promise", "act": act, "target": target,
               "window": window, "flavor": flavor}
        if res:
            out["resource"] = res
        return out, errs

    if t == "announce":
        text = _clip(raw.get("text"), ANNOUNCE_MAX_CHARS)
        if not text:
            errs.append("announce needs text")
            return None, errs
        return {"type": "announce", "text": text, "flavor": flavor}, errs

    return None, [f"unknown speech type '{t}'"]


def render(speech, speaker) -> str:
    """Canonical public line for the log, the broadcast, and the replay."""
    if not speech or speech.get("type") == "none":
        return speech.get("flavor", "") if speech else ""
    t = speech["type"]
    if t == "claim":
        core = (f"I have {speech['resource']}." if speech["has"]
                else f"I have no {speech['resource']}.")
    elif t == "promise":
        if speech["act"] == "no_rob":
            core = (f"I promise {speech['target']}: no robber on you for my "
                    f"next {speech['window']} turn(s).")
        else:
            core = (f"I promise {speech['target']}: I will trade you "
                    f"{speech['resource']} within my next {speech['window']} turn(s).")
    elif t == "announce":
        core = speech["text"]
    else:
        core = ""
    flavor = speech.get("flavor", "")
    return f"{core} {flavor}".strip()


def is_checkable(speech) -> bool:
    """Checkable = feeds the violation battery (claims and promises).
    The informativeness metric counts these per turn."""
    return bool(speech) and speech.get("type") in ("claim", "promise")
