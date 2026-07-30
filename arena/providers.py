"""Multi-provider LLM adapters behind one interface.

Every provider exposes ``complete(system, user, model, options) -> str`` and
returns raw text (expected to contain a JSON object). ``options`` describes the
current legal choices; real backends ignore it (they read the prompt) while the
offline MockProvider uses it to fabricate a schema-valid, legal move — so the
whole pipeline runs with no API keys.

Adapters are the same family as the Mafia arena: GitHub Models is the headline
free/low-cost backend that exposes many model families under one token.
"""
from __future__ import annotations

import json
import os
import random
import re


class Provider:
    name = "base"

    def complete(self, system: str, user: str, model: str, options: dict) -> str:
        raise NotImplementedError


class MockProvider(Provider):
    """Offline stand-in. Emits schema-valid, *legal* JSON so games run with no keys.

    It plays a plausible-but-simple settler: builds when it can afford to,
    occasionally proposes a trade, otherwise banks or ends the turn. The point is
    a populated log + watchable scene before you spend a cent on real models.
    """

    name = "mock"

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def complete(self, system, user, model, options):
        kind = (options or {}).get("kind", "action")
        intent = _sniff(system, "INTENT:")
        name = _sniff(system, "NAME:")
        if kind == "robber":
            hexes = options.get("hexes") or [None]
            victims = options.get("victims") or [None]
            v = self.rng.choice(victims) if victims else None
            reason = (
                f"A 7 hands me the robber, so I want the tile that hurts the table "
                f"most while I'm not producing anyway. I'll block a high-pip number and "
                f"steal from {v or 'no one reachable'} to chip at their build. "
                f"Playing {intent}, that pressure fits how I want this game to go.")
            return json.dumps({
                "private_reasoning": reason,
                "public_statement": self.rng.choice(
                    ["The robber rides.", "Sorry, nothing personal.",
                     "Blocking the good numbers."]),
                "hex": self.rng.choice(hexes), "victim": v,
            })
        if kind == "trade_response":
            accept = self.rng.random() < (0.3 if "greedy" in intent else 0.55)
            give, want = options.get("give", {}), options.get("want", {})
            reason = (
                f"They're offering {give or 'something'} for my {want or 'goods'}. "
                f"I check whether that advances my next build more than theirs — "
                f"{'it does enough to say yes' if accept else 'it helps them more, so no'}. "
                f"Playing {intent}, I {'take the deal' if accept else 'hold my resources'}.")
            return json.dumps({
                "private_reasoning": reason,
                "public_statement": ("Deal." if accept else "I'll pass on that."),
                "accept": accept,
            })

        # generic action turn
        legal = options.get("legal", ["end_turn"])
        choice = self._pick(legal, options)
        pub = self.rng.choice([
            "Building out my corner.", "Anyone need sheep?",
            "Watch that road.", "I'll take the long way round.",
            "Robber's ugly this turn."])
        out = {
            "private_reasoning": self._reason(choice["action"], options, intent, model),
            "public_statement": pub,
        }
        out.update(choice)
        return json.dumps(out)

    def _reason(self, action, options, intent, model):
        """A detailed, state-aware reasoning trace so 'peek at thoughts' reads as
        real strategic thinking even offline."""
        have = options.get("have", {})
        total = sum(have.values())
        owned = ", ".join(f"{v} {r}" for r, v in have.items() if v) or "almost nothing"
        legal = [a for a in options.get("legal", []) if a != "end_turn"]
        goal = ("upgrade a settlement to a city (ore+wheat)" if "build_city" in legal
                else "found a new settlement on a strong number" if "build_settlement" in legal
                else "extend a road toward open land" if "build_road" in legal
                else "trade for the resource I'm short on")
        act = action.replace("_", " ")
        return (
            f"Board read: I'm holding {owned} ({total} cards); my open moves are "
            f"{legal or ['end turn']}. "
            f"My priority is to {goal}, and weighing the options, {act} gets me closest "
            f"without overcommitting resources I'll need next turn. "
            f"No one looks about to reach 10 yet, so I can keep developing rather than "
            f"purely blocking. "
            f"Playing {intent}, I'll {act} now and reassess after the next roll.")

    def _pick(self, legal, options):
        """Purposeful-but-simple: bank/trade toward the next build's deficit, then
        take the highest-value build available. Enough to climb toward 10 VP."""
        have = options["have"]
        # 1) cash in an affordable build — city > settlement > road
        for a in ("build_city", "build_settlement"):
            if a in legal:
                key = "city_spots" if a == "build_city" else "settlement_spots"
                return {"action": a, "vertex": self.rng.choice(options[key])}

        # 2) what is the cheapest next point, and what does it lack?
        goal = ({"wheat": 2, "ore": 3} if options["city_spots"]
                else {"wood": 1, "brick": 1, "sheep": 1, "wheat": 1})
        deficit = {r: n - have.get(r, 0) for r, n in goal.items() if have.get(r, 0) < n}

        # 3) bank-trade a surplus straight into the biggest deficit
        if deficit and "bank_trade" in legal:
            need = max(deficit, key=deficit.get)
            matches = [t for t in options["bank_trades"] if list(t[1])[0] == need]
            if matches:
                give, want = self.rng.choice(matches)
                return {"action": "bank_trade", "give": give, "want": want}

        # 4) build roads to open new settlement spots when none are reachable yet
        if "build_road" in legal and not options["settlement_spots"] \
                and self.rng.random() < 0.7:
            return {"action": "build_road", "edge": self.rng.choice(options["road_spots"])}
        if "build_road" in legal and self.rng.random() < 0.3:
            return {"action": "build_road", "edge": self.rng.choice(options["road_spots"])}

        # 5) ask a neighbour for a missing resource, paying with a surplus
        if deficit and "propose_trade" in legal:
            need = max(deficit, key=deficit.get)
            surplus = [r for r in RES if have.get(r, 0) >= 2 and r not in deficit]
            if surplus:
                return {"action": "propose_trade",
                        "target_player": self.rng.choice(options["trade_partners"]),
                        "give": {self.rng.choice(surplus): 1}, "want": {need: 1}}

        if "buy_dev" in legal and self.rng.random() < 0.4:
            return {"action": "buy_dev"}
        return {"action": "end_turn"}


RES = ("wood", "brick", "sheep", "wheat", "ore")


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self):
        import anthropic  # lazy
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def complete(self, system, user, model, options):
        msg = self.client.messages.create(
            model=model, max_tokens=900, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self):
        import openai  # lazy
        self.client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def complete(self, system, user, model, options):
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=900,
        )
        return resp.choices[0].message.content or ""


class GitHubModelsProvider(Provider):
    """GitHub Models — free/low-cost inference, OpenAI-compatible.

    Endpoint: https://models.github.ai/inference  (chat/completions spec)
    Auth:     a GitHub PAT with the `models:read` permission, in $GITHUB_TOKEN.
    Model ids are namespaced, e.g. "openai/gpt-4o", "meta/Llama-3.3-70B-Instruct",
    "deepseek/DeepSeek-V3-0324", "mistral-ai/Mistral-Large-2411".
    """

    name = "github"
    BASE_URL = "https://models.github.ai/inference"
    RETRIES = 3
    BACKOFF = (4, 10, 20)

    def __init__(self):
        import openai  # lazy; the OpenAI SDK speaks this endpoint
        tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
        if not tok:
            raise RuntimeError(
                "GitHub Models needs a token. Create a GitHub PAT with the "
                "'models:read' scope and run:  export GITHUB_TOKEN=github_pat_...\n"
                "(Preview with no key using a 'mock' config, e.g. configs/demo.json.)")
        self.client = openai.OpenAI(base_url=self.BASE_URL, api_key=tok)

    def complete(self, system, user, model, options):
        import time
        for attempt in range(self.RETRIES):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    max_tokens=1100, temperature=0.8,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                # only back off on genuinely transient errors (rate-limit / timeout /
                # 5xx). Bad model ids, auth, or bad requests fail fast to a fallback.
                status = getattr(e, "status_code", None)
                nm = type(e).__name__
                transient = ("RateLimit" in nm or "Timeout" in nm or "Connection" in nm
                             or (isinstance(status, int) and status >= 500))
                if not transient or attempt == self.RETRIES - 1:
                    raise
                time.sleep(self.BACKOFF[min(attempt, len(self.BACKOFF) - 1)])
        return ""


class GoogleProvider(Provider):
    name = "google"

    def __init__(self):
        import google.generativeai as genai  # lazy
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self._genai = genai

    def complete(self, system, user, model, options):
        m = self._genai.GenerativeModel(model, system_instruction=system)
        return m.generate_content(user).text


# provider-name -> factory. Add rows here to support more backends.
_REGISTRY = {
    "mock": MockProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "github": GitHubModelsProvider,
    "google": GoogleProvider,
}


def get_provider(name: str, **kw) -> Provider:
    if name not in _REGISTRY:
        raise KeyError(f"unknown provider {name!r}; have {list(_REGISTRY)}")
    return _REGISTRY[name](**kw)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(raw: str) -> dict | None:
    """Best-effort extraction of the decision JSON from a model reply."""
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _sniff(text: str, tag: str) -> str:
    for line in (text or "").splitlines():
        if line.strip().startswith(tag):
            return line.split(tag, 1)[1].strip()
    return "unknown"
