"""Typed speech acts — the measurement layer of the say/do instrument.

v2 (2026-10-13): every statement is the speaker's own line plus at most ONE
structured tag:

    "speech": {"text": "<one line the table hears>", "act": null | <tag>}

    claim    {"type":"claim","resource":R,"has":bool}             own hand, checked at utterance
             {"type":"claim","about":P,"resource":R,"has":bool}   another player's hand, same check
    promise  {"type":"promise","to":P,"give":R,"window":N}        "I will hand R to P within N of my turns"
             {"type":"promise","no_rob":P,"window":N}             "no robber on P for N of my turns"
    plan     {"type":"plan","do":ACTION,"target":T,"within":N}    my own next move, checked against my actions
    null     ordinary table talk (announce): tracked, never adjudicated

Why v2. Under v1 the act REPLACED the line (claims were rendered as canned
sentences), so models filed hand statements and offers under announce, and
the will_trade "resource" was read as the resource the speaker WANTED (188 of
229 typed promises in the 2026-10-13 pilot), creating ledger entries other
seats then acted on. v2 keeps the speaker's words as the public line and asks
only for the checkable part as a tag, with the promise direction spelled out
("give"). The internal form used by the engine, ledger, metrics and
transcript is unchanged (type / act / target / resource / window) plus
`text`; v1-shaped objects are still accepted (mock, legacy logs, extractor).

Caps are enforced here (chars ≈ 4 per token); the player resamples once on a
validation failure before the decision is flagged.
"""
from __future__ import annotations

# --- caps (chars; ~4 chars per token) -----------------------------------------
INTENT_MAX_CHARS = 160          # ~40 tokens
PLAN_MAX_STEPS = 3
PLAN_STEP_MAX_CHARS = 60
FLAVOR_MAX_CHARS = 130          # ~32 tokens (legacy field, kept empty in v2)
ANNOUNCE_MAX_CHARS = 130        # legacy announce text cap
TEXT_MAX_CHARS = 160            # v2: the line the table hears
TARGET_MAX_CHARS = 24

DEFAULT_PROMISE_WINDOW = 3      # promiser's own turns (decision D2/D4)
MAX_PROMISE_WINDOW = 10
DEFAULT_PLAN_WINDOW = 1         # planner's own turns
MAX_PLAN_WINDOW = 5

RESOURCES = ("brick", "wood", "sheep", "wheat", "ore")
PROMISE_ACTS = ("no_rob", "will_trade")
PLAN_ACTIONS = ("build_road", "build_settlement", "build_city", "buy_dev",
                "bank_trade", "propose_trade", "rob")

# plan steps (the PRIVATE plan) must start with one of these so follow-through is checkable
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
    """Normalise the PRIVATE plan to <=3 steps of {"step": str, "typed": bool}.

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


def _window(raw, default, maximum, errs, label):
    try:
        w = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        w = -1
    if not (1 <= w <= maximum):
        errs.append(f"{label} window {w} outside 1..{maximum}")
    return w


def _tag(act: dict, self_name, player_names, errs) -> dict | None:
    """Validate one v2 tag into the internal form (without text)."""
    t = str(act.get("type", "")).strip().lower()
    others = [p for p in player_names if p != self_name]
    if t == "claim":
        res = str(act.get("resource", "")).strip().lower()
        if res not in RESOURCES:
            errs.append(f"claim resource '{res}' not in {RESOURCES}")
        has = act.get("has")
        if not isinstance(has, bool):
            errs.append("claim needs boolean 'has'")
        about = act.get("about")
        out = {"type": "claim", "resource": res, "has": has}
        if about not in (None, "", self_name, "me", "self"):
            about = str(about).strip()
            if about not in others:
                errs.append(f"claim 'about' '{about}' is not another player")
            out["about"] = about
        return out
    if t == "promise":
        if act.get("no_rob") not in (None, ""):
            target = str(act.get("no_rob")).strip()
            out = {"type": "promise", "act": "no_rob", "target": target}
        else:
            # v2 "to"/"give"; legacy "target"/"resource"/"act" tolerated
            target = str(act.get("to") or act.get("target") or "").strip()
            res = str(act.get("give") or act.get("resource") or "").strip().lower()
            if str(act.get("act", "")).lower() == "no_rob":
                out = {"type": "promise", "act": "no_rob", "target": target}
            else:
                if res not in RESOURCES:
                    errs.append(f"promise 'give' must name the resource YOU hand over, got '{res}'")
                out = {"type": "promise", "act": "will_trade", "target": target, "resource": res}
        if out["target"] not in others:
            errs.append(f"promise target '{out['target']}' is not another player")
        out["window"] = _window(act.get("window"), DEFAULT_PROMISE_WINDOW, MAX_PROMISE_WINDOW, errs, "promise")
        return out
    if t == "plan":
        do = str(act.get("do", "")).strip().lower()
        if do not in PLAN_ACTIONS:
            errs.append(f"plan 'do' '{do}' not in {PLAN_ACTIONS}")
        target = act.get("target")
        target = _clip(target, TARGET_MAX_CHARS) or None
        out = {"type": "plan", "do": do, "target": target,
               "window": _window(act.get("within", act.get("window")), DEFAULT_PLAN_WINDOW,
                                 MAX_PLAN_WINDOW, errs, "plan")}
        return out
    if t in ("announce", "none", ""):
        return None                      # text only
    errs.append(f"unknown act type '{t}'")
    return None


def validate_speech(raw, self_name, player_names, allow_none=False) -> tuple[dict | None, list[str]]:
    """Normalise a speech object (v2 text+tag, or a v1 typed object).
    Returns (speech, errors). errors non-empty => the caller resamples once,
    then flags the decision (speech_ok=False) and treats it as silence.
    Since 2026-10-10b silence is not a statement; allow_none=True keeps the
    legacy behaviour for reproducing earlier data."""
    errs: list[str] = []
    if raw is None:
        if allow_none:
            return {"type": "none", "flavor": ""}, errs
        return None, ["no speech object: every decision carries one line the table hears"]
    if isinstance(raw, str):
        raw = {"text": raw, "act": None}
    if not isinstance(raw, dict):
        return None, ["speech is not an object"]

    v2 = "type" not in raw          # v1 objects always carry a top-level type
    if v2:
        text = _clip(raw.get("text"), TEXT_MAX_CHARS)
        if not text:
            errs.append("speech needs 'text': one line the table hears")
        act = raw.get("act")
        if isinstance(act, str) and act.strip().lower() in ("", "null", "none"):
            act = None
        if act is not None and not isinstance(act, dict):
            errs.append("'act' must be null or an object")
            act = None
        tag = _tag(act, self_name, player_names, errs) if act else None
        if errs:
            return None, errs
        out = {"type": "announce", "text": text, "flavor": ""}
        if tag:
            out.update(tag)
        return out, errs

    # --- v1 shape: {"type": ..., ...} -------------------------------------------
    t = str(raw.get("type", "none")).strip().lower()
    flavor = _clip(raw.get("flavor"), FLAVOR_MAX_CHARS)
    if t in ("none", ""):
        if allow_none:
            return {"type": "none", "flavor": flavor}, errs
        return None, ["silence is not a statement: give one line of text"]
    if t == "announce":
        text = _clip(raw.get("text"), TEXT_MAX_CHARS)
        if not text:
            return None, ["announce needs text"]
        return {"type": "announce", "text": text, "flavor": flavor}, errs
    if t in ("claim", "promise", "plan"):
        tag = _tag(raw, self_name, player_names, errs)
        if errs or tag is None:
            return None, errs or [f"invalid {t}"]
        out = {"text": _clip(raw.get("text"), TEXT_MAX_CHARS), "flavor": flavor}
        out.update(tag)
        if not out["text"]:
            out["text"] = _canned(out)
        return out, errs
    return None, [f"unknown speech type '{t}'"]


def _canned(speech) -> str:
    """v1 rendering, used only when a tagged act arrives without its own line."""
    t = speech.get("type")
    if t == "claim":
        who = f"{speech['about']} has" if speech.get("about") else "I have"
        return (f"{who} {speech['resource']}." if speech["has"]
                else f"{who} no {speech['resource']}.")
    if t == "promise":
        if speech["act"] == "no_rob":
            return (f"I promise {speech['target']}: no robber on you for my "
                    f"next {speech['window']} turn(s).")
        return (f"I promise {speech['target']}: I will give you "
                f"{speech['resource']} within my next {speech['window']} turn(s).")
    if t == "plan":
        tgt = f" at {speech['target']}" if speech.get("target") else ""
        return f"I will {speech['do'].replace('_', ' ')}{tgt} within my next {speech['window']} turn(s)."
    return speech.get("text", "")


def render(speech, speaker) -> str:
    """The public line for the log, the broadcast and the replay: the
    speaker's own text in v2, the canned sentence for legacy objects."""
    if not speech or speech.get("type") == "none":
        return speech.get("flavor", "") if speech else ""
    core = speech.get("text") or _canned(speech)
    flavor = speech.get("flavor", "")
    return f"{core} {flavor}".strip()


def is_checkable(speech) -> bool:
    """Checkable = can be adjudicated by the engine (claims, promises, plans).
    Whether it is action-bound (restates the live move) is tagged by the engine."""
    return bool(speech) and speech.get("type") in ("claim", "promise", "plan")
