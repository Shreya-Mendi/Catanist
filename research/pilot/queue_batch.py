"""Queue a typed-vs-free batch in the console DB of the machine this runs on.

  python research/pilot/queue_batch.py sanity   # 2 seeds x 2 arms x 4 models, 100 turns (16 games)
  python research/pilot/queue_batch.py main     # 30 seeds x 2 arms x 4 models, 100 turns (240 games)
  python research/pilot/queue_batch.py main --models gpt-4.1,Qwen/Qwen3.8-27B --seeds 100-129
"""
import sys, json, time, argparse, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from arena import db

SEATS = [{"name": "Merlin", "persona": "a pragmatic settler who trades when it helps", "intent": "balanced", "costume": "wizard", "color": "#7c5cff"},
         {"name": "Isolde", "persona": "a warm diplomat who keeps the economy moving", "intent": "diplomatic", "costume": "queen", "color": "#3d9bf2"},
         {"name": "Roland", "persona": "a steady builder focused on tempo", "intent": "builder", "costume": "knight", "color": "#e05c5c"},
         {"name": "Vesper", "persona": "a cautious planner who minimises risk", "intent": "cautious", "costume": "vampire", "color": "#b14b8a"}]
PROVIDER = {"gpt-4.1": "openai", "gpt-5.5": "openai", "gpt-5.2": "openai", "gpt-4o": "openai",
            "Qwen/Qwen3.8-27B": "tinker", "Qwen/Qwen3.5-397B-A17B": "tinker", "Qwen/Qwen3.6-27B": "tinker",
            "Qwen/Qwen3-8B": "tinker"}
DEFAULT_MODELS = ["gpt-4.1", "gpt-5.5", "Qwen/Qwen3.8-27B", "Qwen/Qwen3.5-397B-A17B"]

ap = argparse.ArgumentParser()
ap.add_argument("kind", choices=["sanity", "main"])
ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
ap.add_argument("--seeds", default=None, help="e.g. 100-129")
ap.add_argument("--turns", type=int, default=100)
ap.add_argument("--owner", default="shreya")
ap.add_argument("--hold", action="store_true", help="insert as held (released from the console or by status update)")
a = ap.parse_args()
models = [m.strip() for m in a.models.split(",") if m.strip()]
if a.seeds:
    lo, hi = a.seeds.split("-"); seeds = list(range(int(lo), int(hi) + 1))
else:
    seeds = [100, 101] if a.kind == "sanity" else list(range(100, 130))
name = ("Sanity: schema v2, typed vs free, 4 models" if a.kind == "sanity"
        else "E1 main: typed vs free, 30 seeds, schema v2")
notes = (f"2026-10-13. Seeds {seeds[0]}-{seeds[-1]}, typed and free, models {', '.join(models)}, {a.turns} turns, "
         "E1 seats, memory layer 3 as a prompt recap, decline feedback, schema v2 (text + one tag, give direction, plans, "
         "claims about others, action-bound tagging), extractor v2.4 on free games. Paired by seed across arms.")
con = db.connect()
with con:
    cur = con.execute("INSERT INTO experiments(name,owner,hypothesis,notes,created) VALUES(?,?,?,?,?)",
                      (name, a.owner, "H1", notes, time.time()))
    eid = cur.lastrowid
    n = 0
    for seed in seeds:                 # seed-major: every model/arm pair for a seed lands together
        for model in models:
            short = model.split("/")[-1]
            for arm in ("typed", "free"):
                cfg = {"scene": "harbor", "speech_mode": arm, "max_turns": a.turns, "seed": seed,
                       "name": f"{a.kind}-{short}-{arm}",
                       "players": [dict(s, provider=PROVIDER[model], model=model) for s in SEATS]}
                con.execute("INSERT INTO runs(experiment_id,owner,config,condition,seed,max_turns,status,created) VALUES(?,?,?,?,?,?,?,?)",
                            (eid, a.owner, json.dumps(cfg), f"model={short} arm={arm}", seed, a.turns,
                             "held" if a.hold else "queued", time.time()))
                n += 1
print(f"experiment {eid}: {n} runs {'held' if a.hold else 'queued'} ({len(seeds)} seeds x {len(models)} models x 2 arms, {a.turns} turns)")
