"""Exact token volumes per game from stored logs, with the OpenAI tokenizer
(o200k_base: gpt-4o, gpt-4.1, gpt-5 family). Input per call = the seat's system
prompt + the stored turn prompt; output = the stored reply. Resamples count as a
second call with the same prompt plus the fix line. Writes a JSON profile the
budget script reads.
  python research/pilot/token_profile.py <logs dir> <out json>"""
import glob, json, re, statistics as st, sys, pathlib, collections
import tiktoken
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena.runner import build_players, _provider_cache

enc = tiktoken.get_encoding("o200k_base")
logs_dir, out = sys.argv[1], sys.argv[2]

# exact system prompt per speech mode (persona lines differ by a few tokens per seat)
cfg = json.load(open(ROOT / "configs/demo.json"))
SYS = {}
for mode in ("typed", "free"):
    c = dict(cfg, speech_mode=mode, players=[dict(p, provider="mock") for p in cfg["players"]])
    SYS[mode] = [len(enc.encode(p._system())) for p in build_players(c, _provider_cache())]

games = []
for f in sorted(glob.glob(logs_dir.rstrip("/") + "/*.json")):
    if f.endswith("_extracted.json") or "arena" in pathlib.Path(f).name:
        continue
    name = pathlib.Path(f).name
    m = re.match(r"main-(.+?)-(typed|free)_run(\d+)_", name)
    if not m:
        continue
    model, mode, rid = m.group(1), m.group(2), int(m.group(3))
    log = json.load(open(f)); ev = log["events"]
    dec = [e for e in ev if "parse_ok" in e]
    sys_tok = st.mean(SYS[mode])
    tin = tout = 0; calls = 0; per_call_in = []; per_call_out = []
    for e in dec:
        p = enc.encode(e.get("prompt") or ""); r = enc.encode(e.get("raw") or "")
        n = 2 if e.get("resampled") else 1          # a resample is a second call on the same prompt
        calls += n
        tin += n * (len(p) + sys_tok) + (60 if e.get("resampled") else 0)
        tout += n * len(r)
        per_call_in.append(len(p) + sys_tok); per_call_out.append(len(r))
    turns = max((e.get("turn", 0) for e in ev), default=0)
    games.append({"run": rid, "model": model, "arm": mode, "turns": turns, "finished_10vp": log.get("reason") != "turn limit",
                  "decisions": len(dec), "calls": calls, "tokens_in": round(tin), "tokens_out": tout,
                  "in_per_call": round(st.mean(per_call_in)) if per_call_in else 0,
                  "out_per_call": round(st.mean(per_call_out)) if per_call_out else 0,
                  "system_tokens": round(sys_tok)})
    print(f"{name[:60]:<60} turns {turns:>3} calls {calls:>4} in {tin/1e6:.2f}M out {tout/1e3:.0f}k", flush=True)

prof = collections.defaultdict(list)
for g in games:
    prof[(g["model"], g["arm"])].append(g)
summary = {}
for (model, arm), gs in sorted(prof.items()):
    def mean(k): return st.mean(x[k] for x in gs)
    def sd(k): return st.pstdev([x[k] for x in gs]) if len(gs) > 1 else 0
    summary[f"{model}|{arm}"] = {
        "games": len(gs), "turns_mean": round(mean("turns"), 1), "finished_10vp": sum(g["finished_10vp"] for g in gs),
        "calls_mean": round(mean("calls"), 1), "calls_per_turn": round(sum(g["calls"] for g in gs) / sum(g["turns"] for g in gs), 3),
        "in_per_call": round(sum(g["tokens_in"] for g in gs) / sum(g["calls"] for g in gs)),
        "out_per_call": round(sum(g["tokens_out"] for g in gs) / sum(g["calls"] for g in gs)),
        "tokens_in_mean": round(mean("tokens_in")), "tokens_in_sd": round(sd("tokens_in")),
        "tokens_out_mean": round(mean("tokens_out")), "tokens_out_sd": round(sd("tokens_out")),
        "system_tokens": gs[0]["system_tokens"]}
pathlib.Path(out).write_text(json.dumps({"tokenizer": "o200k_base", "system_tokens": SYS, "summary": summary, "games": games}, indent=1))
print(json.dumps(summary, indent=1))
