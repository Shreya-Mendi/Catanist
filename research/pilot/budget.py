"""Budget for the remaining experiments, from measured tokens and published prices.
  python research/pilot/budget.py [profile json] > research/budget-<date>.md

Every number is games x tokens x price, with the tokens taken from
research/pilot/token_profile.json (exact o200k counts over the E1 logs: calls per
turn, input and output tokens per call, system-prompt tokens) and the prices from
the tables below (OpenAI developers.openai.com/api/docs/pricing and Tinker
thinkingmachines.ai/tinker/pricing, both read 2026-10-25). Edit DESIGNS, MODELS or
SCENARIOS and rerun; nothing is hidden in the code."""
import json, pathlib, sys, math, collections, datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROFILE = json.load(open(sys.argv[1] if len(sys.argv) > 1 else ROOT / "research/pilot/token_profile.json"))
S = PROFILE["summary"]

# ---- prices per 1M tokens -----------------------------------------------------
OPENAI = {   # input, cached input, output. Standard tier, read 2026-10-25
    "gpt-5":        (1.25, 0.125, 10.00),   # marked Deprecated on its model page (replacement named: GPT-6 Astra)
    "gpt-5-mini":   (0.25, 0.025, 2.00),    # marked Deprecated (replacement named: GPT-5.6 Terra)
    "gpt-5-nano":   (0.05, 0.005, 0.40),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),    # Ammy's current choice; reasoning effort none..xhigh
    "gpt-5.4":      (2.50, 0.25, 15.00),
    "gpt-6-luna":   (0.10, 0.01, 0.50),
    "gpt-6-sol":    (2.00, 0.20, 10.00),
    "gpt-6.1-sol":  (2.00, 0.10, 10.00),
    "gpt-4.1":      (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
}
TINKER = {   # prefill, cached prefill, sample, train (64K context rows), read 2026-10-25
    "Qwen3.8-27B":                     (0.6975, 0.1395, 5.595, 4.103),
    "NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16": (0.184, 0.0368, 0.495, 0.44),
    "Qwen3.5-397B-A17B":               (1.65, 0.33, 7.50, 6.60),
    "gpt-oss-120b":                    (0.33, 0.066, 0.84, 0.737),
    "Qwen3.6-35B-A3B":                 (0.45, 0.09, 1.335, 1.177),
}

# ---- measured game shape ------------------------------------------------------
def profile(model_like: str, arm: str = "typed") -> dict:
    """The measured profile for this model, else the closest: OpenAI models take
    gpt-4.1's (same tokenizer, same prompt), open models their own E1 row."""
    for key in (f"{model_like}|{arm}", f"gpt-4.1|{arm}"):
        if key in S:
            return dict(S[key], source=key)
    raise KeyError(model_like)

def game_tokens(model: str, arm: str, turns_cap: int, reasoning_per_call: float = 0.0) -> dict:
    """Central estimate: measured per-game tokens scaled by turns_cap/100 (E1 ran at
    a 100-turn cap). Max: every game runs to the cap at the measured calls per turn."""
    p = profile(model, arm)
    scale = turns_cap / 100.0
    calls = p["calls_mean"] * scale
    sys_tok = p["system_tokens"]
    tin_total = p["tokens_in_mean"] * scale
    cached = calls * sys_tok * 0.9          # the system prompt (>1,024 tokens) is a cached prefix; 90% hit rate assumed
    uncached = tin_total - cached
    tout = p["tokens_out_mean"] * scale + calls * reasoning_per_call
    calls_max = p["calls_per_turn"] * turns_cap
    return {"calls": calls, "in_cached": cached, "in_uncached": uncached, "in_total": tin_total, "out": tout,
            "calls_max": calls_max, "in_max": calls_max * p["in_per_call"],
            "out_max": calls_max * (p["out_per_call"] + reasoning_per_call), "profile": p["source"]}

def game_cost(model: str, arm: str, turns_cap: int, reasoning_per_call: float = 0.0) -> dict:
    t = game_tokens(model, arm, turns_cap, reasoning_per_call)
    if model in OPENAI:
        pi, pc, po = OPENAI[model]
        usd = (t["in_uncached"] * pi + t["in_cached"] * pc + t["out"] * po) / 1e6
        usd_nocache = (t["in_total"] * pi + t["out"] * po) / 1e6
        usd_max = (t["in_max"] * pi + t["out_max"] * po) / 1e6
        return {**t, "usd": usd, "usd_nocache": usd_nocache, "usd_max": usd_max, "provider": "openai"}
    if model in TINKER:
        pp, pcp, ps, _ = TINKER[model]
        usd = (t["in_uncached"] * pp + t["in_cached"] * pcp + t["out"] * ps) / 1e6
        usd_nocache = (t["in_total"] * pp + t["out"] * ps) / 1e6
        usd_max = (t["in_max"] * pp + t["out_max"] * ps) / 1e6
        return {**t, "usd": usd, "usd_nocache": usd_nocache, "usd_max": usd_max, "provider": "tinker"}
    raise KeyError(model)

def training_cost(model: str, decisions: int) -> dict:
    """SFT on winners' decisions: each decision is one (prompt, reply) example of
    in_per_call + out_per_call tokens, at the model's training price."""
    p = profile(model, "typed")
    tokens = decisions * (p["in_per_call"] + p["out_per_call"])
    return {"tokens": tokens, "usd": tokens * TINKER[model][3] / 1e6}

# ---- the designs as written by the researchers (2026-10-25) --------------------
# games per stage; model and turns are the knobs a scenario changes
DESIGNS = [
 # Ammy, H2
 {"owner": "Ammy", "exp": "E3/E2", "stage": "engineering checks", "games": 10, "turns": 120, "note": "8-12 planned"},
 {"owner": "Ammy", "exp": "E3/E2", "stage": "formal pilot", "games": 48, "turns": 120, "note": "3 boards x 4 focal seats x 4 conditions"},
 {"owner": "Ammy", "exp": "E3/E2", "stage": "main study", "games": 320, "turns": 120, "note": "10 boards x 4 seats x 4 conditions x 2 reps; E2 reuses the 80 C1 games"},
 # Aesha, H3 / E4
 {"owner": "Aesha", "exp": "E4", "stage": "engineering checks", "games": 2, "turns": 120, "note": "+18 mock games, free"},
 {"owner": "Aesha", "exp": "E4", "stage": "formal pilot", "games": 18, "turns": 120, "note": "6 conditions x 3 boards"},
 {"owner": "Aesha", "exp": "E4", "stage": "main study", "games": 120, "turns": 120, "note": "6 conditions x 20 boards (range 60-180)"},
 {"owner": "Aesha", "exp": "E4", "stage": "cutthroat follow-up", "games": 40, "turns": 120, "note": "rule off/strict x 20 boards"},
 # Aesha, H3 / E5 (Tinker only)
 {"owner": "Aesha", "exp": "E5", "stage": "training games", "games": 1000, "turns": 120, "note": "800-1,200: 2 arms x 2-3 rounds x ~200", "tinker_only": True},
 {"owner": "Aesha", "exp": "E5", "stage": "capability check", "games": 120, "turns": 120, "note": "1 trained vs 3 base, x 2 models", "tinker_only": True},
 {"owner": "Aesha", "exp": "E5", "stage": "honesty re-test", "games": 120, "turns": 120, "note": "80 up to 240", "tinker_only": True},
 # Shreya + Maitreyee, H5 (placeholder design until written)
 {"owner": "Shreya/Maitreyee", "exp": "H5 scheming", "stage": "pilot", "games": 12, "turns": 120, "note": "placeholder: 3 conditions x 4"},
 {"owner": "Shreya/Maitreyee", "exp": "H5 scheming", "stage": "main", "games": 60, "turns": 120, "note": "placeholder: 3 conditions x 20 boards"},
]
E5_TRAINING_DECISIONS = 20000 * 2.5 * 2     # ~20k winners' decisions per round x 2-3 rounds x 2 arms

SCENARIOS = {
 "A. as the researchers wrote it": {"Ammy": "gpt-5.4-mini", "Aesha": "Qwen3.8-27B", "Shreya/Maitreyee": "gpt-5", "reasoning": {"gpt-5.4-mini": 0, "gpt-5": 300}},
 "B. gpt-5 for the OpenAI arms, chosen Tinker models": {"Ammy": "gpt-5", "Aesha": "Qwen3.8-27B", "Shreya/Maitreyee": "gpt-5", "reasoning": {"gpt-5": 300}},
 "C. lean: gpt-6-luna on OpenAI, Nemotron-Lightning on Tinker": {"Ammy": "gpt-6-luna", "Aesha": "NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16", "Shreya/Maitreyee": "gpt-6-luna", "reasoning": {"gpt-6-luna": 300}},
 "D. recommended: gpt-6-luna at reasoning effort none on OpenAI; E4 on Qwen27B; E5 behind a gate":
     {"Ammy": "gpt-6-luna", "Aesha": "Qwen3.8-27B", "Shreya/Maitreyee": "gpt-6-luna", "Shreya": "gpt-6-luna", "reasoning": {},
      "designs": "gated"},
 "E. as D, but H3 on Qwen3.6-35B-A3B (MoE, 4x cheaper than Qwen27B; play quality unmeasured, the 18-game pilot decides)":
     {"Ammy": "gpt-6-luna", "Aesha": "Qwen3.6-35B-A3B", "Shreya/Maitreyee": "gpt-6-luna", "Shreya": "gpt-6-luna", "reasoning": {},
      "designs": "gated"},
}
HYPOTHESIS = {"Ammy": "H2 (E2, E3)", "Aesha": "H3 (E4, E5)", "Shreya/Maitreyee": "H5 (scheming)", "Shreya": "H1 (E1 anchor)"}
CAP_OPENAI = 500.0      # per hypothesis, set 2026-10-25
CAP_TINKER = 600.0      # per hypothesis, "a little higher than that"

# the trimmed design set behind scenario D: same structure, fewer repetitions, E5 behind a gate
DESIGNS_TRIMMED = [
 {"owner": "Ammy", "exp": "E3/E2", "stage": "engineering checks", "games": 10, "turns": 120, "note": "as planned"},
 {"owner": "Ammy", "exp": "E3/E2", "stage": "formal pilot", "games": 48, "turns": 120, "note": "as planned, 3 boards x 4 seats x 4 conditions"},
 {"owner": "Ammy", "exp": "E3/E2", "stage": "main study", "games": 320, "turns": 120, "note": "as planned, 80 per condition (160 would do statistically)"},
 {"owner": "Aesha", "exp": "E4", "stage": "engineering checks", "games": 2, "turns": 120, "note": "+18 mock, free"},
 {"owner": "Aesha", "exp": "E4", "stage": "formal pilot", "games": 18, "turns": 120, "note": "as planned"},
 {"owner": "Aesha", "exp": "E4", "stage": "main study", "games": 120, "turns": 120, "note": "as planned, 6 x 20"},
 {"owner": "Aesha", "exp": "E4", "stage": "cutthroat follow-up", "games": 40, "turns": 120, "note": "as planned"},
 {"owner": "Aesha", "exp": "E5 gate", "stage": "round 0 + one training round, social arm only", "games": 200, "turns": 120, "note": "decide on the full E5 after this", "tinker_only": True},
 {"owner": "Aesha", "exp": "E5 gate", "stage": "capability check + honesty re-test", "games": 80, "turns": 120, "note": "40 + 40, one trained model", "tinker_only": True},
 {"owner": "Shreya/Maitreyee", "exp": "H5 scheming", "stage": "pilot", "games": 12, "turns": 120, "note": "placeholder"},
 {"owner": "Shreya/Maitreyee", "exp": "H5 scheming", "stage": "main", "games": 60, "turns": 120, "note": "placeholder, 3 conditions x 20 boards"},
 {"owner": "Shreya", "exp": "E1 anchor", "stage": "10 seed pairs typed vs free on the chosen OpenAI model", "games": 20, "turns": 100, "note": "replaces the parked gpt-5 pairs"},
]
E5_GATE_DECISIONS = 20000     # one training round, one arm

def fmt(x): return f"${x:,.2f}"
def M(x): return f"{x/1e6:.2f}M"

out = []
out.append(f"# Budget for the remaining experiments, computed {datetime.date.today().isoformat()}\n")
out.append("Source of every token count: research/pilot/token_profile.json (o200k_base over the E1 logs). "
           "Prices: developers.openai.com/api/docs/pricing and thinkingmachines.ai/tinker/pricing, read 2026-10-25. "
           "Cached = the system prompt billed at the cached-input rate on 90 percent of calls (it exceeds the 1,024-token prefix threshold). "
           "Reasoning = assumed hidden reasoning tokens per call for reasoning models at low effort; nothing is measured there yet.\n")
out.append("## Measured game shape (E1, 100-turn cap)\n")
out.append("| model, arm | games | mean turns | finished 10 VP | calls/game | calls/turn | in/call | out/call | in/game | out/game |")
out.append("|---|---|---|---|---|---|---|---|---|---|")
for k, p in S.items():
    out.append(f"| {k} | {p['games']} | {p['turns_mean']} | {p['finished_10vp']} | {p['calls_mean']} | {p['calls_per_turn']} | {p['in_per_call']:,} | {p['out_per_call']:,} | {M(p['tokens_in_mean'])} | {M(p['tokens_out_mean'])} |")
out.append(f"\nSystem prompt: {PROFILE['system_tokens']['typed'][0]} tokens typed, {PROFILE['system_tokens']['free'][0]} free (exact).\n")

out.append("## One game at a 120-turn cap, typed arm\n")
out.append("| model | provider | calls | in tokens (cached part) | out tokens | reasoning/call | cost, cached | cost, no cache | cost if every game runs to the cap |")
out.append("|---|---|---|---|---|---|---|---|---|")
for model, r in [("gpt-5", 300), ("gpt-5", 0), ("gpt-5-mini", 300), ("gpt-5.4-mini", 0), ("gpt-6-luna", 0), ("gpt-6-luna", 300), ("gpt-6-sol", 300), ("gpt-4.1", 0),
                 ("Qwen3.8-27B", 0), ("NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16", 0), ("Qwen3.5-397B-A17B", 0), ("gpt-oss-120b", 0), ("Qwen3.6-35B-A3B", 0)]:
    try:
        c = game_cost(model, "typed", 120, r)
    except KeyError:
        continue
    out.append(f"| {model} | {c['provider']} | {c['calls']:.0f} | {M(c['in_total'])} ({M(c['in_cached'])}) | {M(c['out'])} | {r} | {fmt(c['usd'])} | {fmt(c['usd_nocache'])} | {fmt(c['usd_max'])} |")

grand = {}
for sname, sc in SCENARIOS.items():
    out.append(f"\n## Scenario {sname}\n")
    out.append("| owner | experiment | stage | games | model | per game | stage cost | OpenAI | Tinker |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    tot = collections.defaultdict(float); per_owner = collections.defaultdict(lambda: collections.defaultdict(float))
    designs = DESIGNS_TRIMMED if sc.get("designs") == "gated" else DESIGNS
    train_decisions = E5_GATE_DECISIONS if sc.get("designs") == "gated" else int(E5_TRAINING_DECISIONS)
    for d in designs:
        model = sc.get(d["owner"]) or sc["Shreya/Maitreyee"]
        if d.get("tinker_only") and model in OPENAI:
            model = "Qwen3.8-27B" if sc["Aesha"] in OPENAI else sc["Aesha"]
        r = sc["reasoning"].get(model, 0)
        c = game_cost(model, "typed", d["turns"], r)
        stage = c["usd"] * d["games"]
        prov = c["provider"]
        tot[prov] += stage; per_owner[d["owner"]][prov] += stage
        out.append(f"| {d['owner']} | {d['exp']} | {d['stage']} ({d['note']}) | {d['games']} | {model} | {fmt(c['usd'])} | {fmt(stage)} | {fmt(stage) if prov=='openai' else ''} | {fmt(stage) if prov=='tinker' else ''} |")
    # E5 training compute
    tmodel = sc["Aesha"] if sc["Aesha"] in TINKER else "Qwen3.8-27B"
    tr = training_cost(tmodel, train_decisions)
    tot["tinker"] += tr["usd"]; per_owner["Aesha"]["tinker"] += tr["usd"]
    out.append(f"| Aesha | E5 | SFT training compute ({train_decisions:,} decisions x {profile(tmodel)['in_per_call']+profile(tmodel)['out_per_call']:,} tokens at ${TINKER[tmodel][3]}/M) | | {tmodel} | | {fmt(tr['usd'])} | | {fmt(tr['usd'])} |")
    out.append("")
    for owner, v in per_owner.items():
        flag_o = "" if v["openai"] <= CAP_OPENAI else f" OVER the ${CAP_OPENAI:.0f} cap by {fmt(v['openai']-CAP_OPENAI)}"
        flag_t = "" if v["tinker"] <= CAP_TINKER else f" OVER the ${CAP_TINKER:.0f} cap by {fmt(v['tinker']-CAP_TINKER)}"
        out.append(f"- {HYPOTHESIS.get(owner, owner)}, {owner}: OpenAI {fmt(v['openai'])}{flag_o}; Tinker {fmt(v['tinker'])}{flag_t}")
    out.append(f"- **Total: OpenAI {fmt(tot['openai'])}, Tinker {fmt(tot['tinker'])}, all {fmt(tot['openai']+tot['tinker'])}**")
    grand[sname] = dict(tot)

out.append("\n## Totals side by side\n")
out.append("| scenario | OpenAI | Tinker | all |")
out.append("|---|---|---|---|")
for sname, t in grand.items():
    out.append(f"| {sname} | {fmt(t.get('openai',0))} | {fmt(t.get('tinker',0))} | {fmt(t.get('openai',0)+t.get('tinker',0))} |")
print("\n".join(out))
