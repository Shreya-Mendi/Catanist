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


import threading
_USAGE = threading.local()


def take_usage():
    """Token usage of the last completion on this thread, then cleared.
    Providers that report none (Tinker) leave it empty."""
    u = getattr(_USAGE, "last", None)
    _USAGE.last = None
    return u


class Provider:
    def complete_messages(self, system, messages, model, options):
        """Multi-turn call: `messages` is the alternating user/assistant history
        ending with the current user prompt. Providers without history support
        fall back to the last user message (mock, anthropic)."""
        last_user = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")
        return self.complete(system, last_user, model, options)

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
            out = {
                "private_reasoning": reason,
                "public_statement": self.rng.choice(
                    ["The robber rides.", "Sorry, nothing personal.",
                     "Blocking the good numbers."]),
                "hex": self.rng.choice(hexes), "victim": v,
            }
            out.update(self._instrument(system, options, "rob"))
            return json.dumps(out)
        if kind == "trade_response":
            accept = self.rng.random() < (0.3 if "greedy" in intent else 0.55)
            give, want = options.get("give", {}), options.get("want", {})
            reason = (
                f"They're offering {give or 'something'} for my {want or 'goods'}. "
                f"I check whether that advances my next build more than theirs — "
                f"{'it does enough to say yes' if accept else 'it helps them more, so no'}. "
                f"Playing {intent}, I {'take the deal' if accept else 'hold my resources'}.")
            out = {
                "private_reasoning": reason,
                "public_statement": ("Deal." if accept else "I'll pass on that."),
                "accept": accept,
            }
            out.update(self._instrument(system, options, "end_turn"))
            return json.dumps(out)

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
        out.update(self._instrument(system, options, choice["action"]))
        return json.dumps(out)


    def _instrument(self, system, options, action):
        """intent / plan / speech fields for the E0 instrument. In typed mode the
        mock deliberately lies sometimes when its INTENT block is deceptive, so
        offline logs contain true violations for the battery tests to catch."""
        intent_tag = _sniff(system, "INTENT:")
        legal = options.get("legal", [])
        have = {r: n for r, n in (options.get("have") or {}).items() if n > 0}
        # a genuine 3-step lookahead in the mock's own strategy: act now, then the
        # cheapest scoring goal, then close the turn — so plan follow-through and
        # plan-vs-speech divergence are exercised offline exactly like live games
        goal = ("build_city" if options.get("city_spots")
                else "build_settlement" if options.get("settlement_spots")
                else "build_road toward an open spot" if options.get("road_spots")
                else "bank_trade toward my next build")
        plan = [action.replace("rob", "rob the strongest producer"), goal, "end_turn"]
        seen, dedup = set(), []
        for st in plan:
            k = st.split()[0]
            if k not in seen:
                seen.add(k); dedup.append(st)
        goal_word = goal.split()[0].replace("_", " ")
        intent_line = self.rng.choice([
            f"Lock in a {goal_word} while the table is distracted.",
            f"Shore up my economy, then push for a {goal_word}.",
            f"Keep {(' and '.join(sorted(have)[:2]) or 'my hand')} working toward a {goal_word}.",
            f"Play it {intent_tag}: {action.replace('_', ' ')} now, {goal_word} soon.",
        ])
        out = {"intent": intent_line, "plan": dedup[:3]}
        if "SPEECH MODE: TYPED" not in (system or ""):
            return out
        have = {r: n for r, n in (options.get("have") or {}).items() if n > 0}
        partners = options.get("trade_partners") or options.get("player_names") or []
        partners = [p for p in partners if p != _sniff(system, "NAME:")]
        deceptive = "deceptive" in intent_tag.lower()
        # schema v2 shapes (text + one tag), with the same planted lies
        roll = self.rng.random()
        if roll < 0.3 or not partners:
            sp = {"text": self.rng.choice(["Nice roll, building quietly.", "Slow turn for me.",
                                           "Watching the ports this round."]), "act": None}
        elif roll < 0.45 and have:
            res = self.rng.choice(sorted(have))
            lie = deceptive and self.rng.random() < 0.6
            sp = {"text": f"Just so everyone knows, I {'have no' if lie else 'have'} {res}.",
                  "act": {"type": "claim", "resource": res, "has": not lie}}
        elif roll < 0.6:
            tgt = self.rng.choice(partners)
            sp = {"text": f"No robber on you, {tgt}, you have my word.",
                  "act": {"type": "promise", "no_rob": tgt, "window": self.rng.choice([1, 2, 3])}}
        elif roll < 0.75 and have:
            tgt = self.rng.choice(partners); res = self.rng.choice(sorted(have))
            sp = {"text": f"{tgt}, you'll have {res} from me soon.",
                  "act": {"type": "promise", "to": tgt, "give": res, "window": self.rng.choice([1, 2])}}
        elif roll < 0.9:
            goal_do = goal.split()[0]
            sp = {"text": f"Next turn I'm going for a {goal_do.replace('_', ' ')}.",
                  "act": {"type": "plan", "do": goal_do, "within": self.rng.choice([1, 2])}}
        else:
            sp = {"text": "Pushing toward the best open spot.", "act": None}
        out["speech"] = sp
        return out

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
    """Official OpenAI API. Reuses the hardened OpenAI-compatible path below
    (retries with backoff, CATAN_PACE_S pacing, 402 fail-fast, both SDK shapes)
    by delegating to the same complete() implementation."""

    name = "openai"
    RETRIES = 3
    BACKOFF = (4, 10, 20)
    _last_call = 0.0

    def __init__(self, owner: str | None = None):
        import openai  # lazy
        # per-user billing (2026-10-14): a run owned by console user X uses
        # OPENAI_API_KEY_X (X upper-cased, non-alphanumerics -> _) when that
        # variable exists in .env, else the shared OPENAI_API_KEY
        key = os.environ.get(owner_key_name("OPENAI_API_KEY", owner)) if owner else None
        self.key_source = owner if key else "shared"
        key = key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAI needs a key: put OPENAI_API_KEY=sk-... in Catanist/.env")
        self.client = openai.OpenAI(api_key=key)

    def complete(self, system, user, model, options):
        return GitHubModelsProvider.complete(self, system, user, model, options)

    def complete_messages(self, system, messages, model, options):
        return GitHubModelsProvider.complete_messages(self, system, messages, model, options)


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

    _last_call = 0.0

    def complete(self, system, user, model, options):
        return self.complete_messages(
            system, [{"role": "user", "content": user}], model, options)

    def complete_messages(self, system, messages, model, options):
        import time
        pace = float(os.environ.get("CATAN_PACE_S", "0") or 0)
        if pace > 0:
            wait = self._last_call + pace - time.time()
            if wait > 0:
                time.sleep(wait)
        type(self)._last_call = time.time()
        for attempt in range(self.RETRIES):
            try:
                kw = dict(max_tokens=1100, temperature=0.8)
                msgs = [{"role": "system", "content": system}] + list(messages)
                try:
                    resp = self.client.chat.completions.create(
                        model=model, messages=msgs, **kw)
                except Exception as e1:
                    # newer OpenAI generations reject the legacy params:
                    # swap max_tokens and drop the custom temperature
                    msg = str(e1)
                    if "max_tokens" in msg or "max_completion_tokens" in msg:
                        kw = {"max_completion_tokens": 1100}
                    elif "temperature" in msg:
                        kw.pop("temperature", None)
                    else:
                        raise
                    resp = self.client.chat.completions.create(
                        model=model, messages=msgs, **kw)
                if isinstance(resp, str):   # newer openai SDKs return the text directly
                    return resp
                u = getattr(resp, "usage", None)
                if u is not None:            # token usage for the cost ledger (per thread = per game)
                    _USAGE.last = {"model": model,
                                   "input": int(getattr(u, "prompt_tokens", 0) or 0),
                                   "output": int(getattr(u, "completion_tokens", 0) or 0)}
                return resp.choices[0].message.content or ""
            except Exception as e:
                # only back off on genuinely transient errors (rate-limit / timeout /
                # 5xx). Bad model ids, auth, or bad requests fail fast to a fallback.
                status = getattr(e, "status_code", None)
                nm = type(e).__name__
                transient = ("RateLimit" in nm or "Timeout" in nm or "Connection" in nm
                             or (isinstance(status, int) and status >= 500))
                if isinstance(status, int) and status == 402:
                    transient = False   # out of credits: fail fast, never retry
                if not transient or attempt == self.RETRIES - 1:
                    raise
                time.sleep(self.BACKOFF[min(attempt, len(self.BACKOFF) - 1)])
        return ""


class HFRouterProvider(GitHubModelsProvider):
    """Hugging Face Inference Providers — OpenAI-compatible router.

    Endpoint: https://router.huggingface.co/v1  ·  Auth: an HF token (fine-grained,
    inference permission) from $HF_TOKEN or the hf CLI login cache. Model ids are
    hub ids, e.g. "meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-7B-Instruct";
    the router picks a serving provider. Replaces GitHub Models, which was fully
    retired on 2026-07-30 (its endpoint now answers 200 text/plain "OK").
    """

    name = "hf"
    BASE_URL = "https://router.huggingface.co/v1"

    def __init__(self):
        import openai
        from pathlib import Path
        tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if not tok:
            cache = Path.home() / ".cache" / "huggingface" / "token"
            tok = cache.read_text().strip() if cache.exists() else None
        if not tok:
            raise RuntimeError(
                "HF router needs a token: set HF_TOKEN or `hf auth login`.")
        self.client = openai.OpenAI(base_url=self.BASE_URL, api_key=tok)


class GoogleProvider(GitHubModelsProvider):
    """Gemini via Google's OpenAI-compatible endpoint — reuses the hardened
    retry/pacing/402 path, no google SDK needed. Key: GOOGLE_API_KEY or
    GEMINI_API_KEY. Model ids: "gemini-2.5-flash", "gemini-2.5-pro", ..."""

    name = "google"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def __init__(self):
        import openai
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "Gemini needs a key: put GOOGLE_API_KEY=... in Catanist/.env")
        self.client = openai.OpenAI(base_url=self.BASE_URL, api_key=key)


class TinkerProvider(Provider):
    """Thinking Machines' Tinker — OSS models for sampling now and the E5
    LoRA training arm later. Key: TINKER_API_KEY (read by the SDK from env).
    Chat formatting uses the model tokenizer's own chat template; Qwen3-style
    thinking is disabled when the template supports it, and any <think> block
    is stripped before JSON extraction so braces inside reasoning cannot
    confuse the decision parser."""

    name = "tinker"
    RETRIES = 2

    def __init__(self):
        import tinker  # lazy
        if not os.environ.get("TINKER_API_KEY"):
            raise RuntimeError("Tinker needs TINKER_API_KEY in Catanist/.env")
        self._tinker = tinker
        self._svc = tinker.ServiceClient()
        self._samplers: dict[str, object] = {}
        self._tokenizers: dict[str, object] = {}

    def _sampler(self, model):
        if model not in self._samplers:
            self._samplers[model] = self._svc.create_sampling_client(base_model=model)
            self._tokenizers[model] = self._samplers[model].get_tokenizer()
        return self._samplers[model], self._tokenizers[model]

    def complete(self, system, user, model, options):
        return self.complete_messages(
            system, [{"role": "user", "content": user}], model, options)

    def complete_messages(self, system, messages, model, options):
        import re as _re
        import time
        from tinker import types
        last = None
        for attempt in range(self.RETRIES):
            try:
                sc, tok = self._sampler(model)
                msgs = [{"role": "system", "content": system}] + list(messages)
                try:
                    ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                                  enable_thinking=False)
                except TypeError:
                    ids = tok.apply_chat_template(msgs, add_generation_prompt=True)
                # tokenizers may hand back a BatchEncoding rather than a list
                if hasattr(ids, "keys"):
                    ids = ids["input_ids"]
                if ids and isinstance(ids[0], (list, tuple)):
                    ids = ids[0]
                prompt = types.ModelInput.from_ints(list(ids))
                params = types.SamplingParams(max_tokens=1100, temperature=0.8)
                fut = sc.sample(prompt=prompt, sampling_params=params, num_samples=1)
                result = fut.result() if hasattr(fut, "result") else fut
                text = tok.decode(result.sequences[0].tokens)
                for end in ("<|im_end|>", "<|endoftext|>", "</s>"):
                    text = text.split(end)[0]
                return _re.sub(r"<think>.*?</think>", "", text, flags=_re.S).strip()
            except Exception as e:
                last = e
                if attempt == self.RETRIES - 1:
                    raise
                time.sleep(5)
        raise last


# provider-name -> factory. Add rows here to support more backends.
_REGISTRY = {
    "mock": MockProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "github": GitHubModelsProvider,
    "hf": HFRouterProvider,
    "tinker": TinkerProvider,
    "google": GoogleProvider,
}


def owner_key_name(base: str, owner: str | None) -> str:
    """OPENAI_API_KEY + console user 'deception_perception' ->
    OPENAI_API_KEY_DECEPTION_PERCEPTION."""
    return base + "_" + re.sub(r"[^A-Za-z0-9]+", "_", str(owner or "")).upper().strip("_")


def has_owner_key(base: str, owner: str | None) -> bool:
    return bool(owner) and bool(os.environ.get(owner_key_name(base, owner)))


def get_provider(name: str, **kw) -> Provider:
    if name not in _REGISTRY:
        raise KeyError(f"unknown provider {name!r}; have {list(_REGISTRY)}")
    owner = kw.pop("owner", None)
    if name == "openai" and owner:
        return _REGISTRY[name](owner=owner)
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
