"""Rescore an experiment uniformly with the current code: recompute the typed
battery from every finished log and re-extract every free game.
  python research/pilot/rescore.py <experiment id> [--no-extract]"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
from arena.metrics import game_metrics
from arena.runner import load_env
EID = int(sys.argv[1]); extract = "--no-extract" not in sys.argv
load_env()
con = db.connect()
rows = con.execute("SELECT id, log_path, config, metrics FROM runs WHERE experiment_id=? AND status='done'", (EID,)).fetchall()
provider = None
n = 0
for r in rows:
    log = json.loads((ROOT / r["log_path"]).read_text())
    m = game_metrics(log)
    cfg = json.loads(r["config"] or "{}")
    if extract and cfg.get("speech_mode") == "free":
        if provider is None:
            from arena.providers import get_provider
            provider = get_provider("openai")
        from arena.extractor import attach_extraction
        out = attach_extraction(log, ROOT / r["log_path"], provider)
        m["extracted"] = out["per_seat"]; m["extracted_model"] = out["model"]; m["extracted_version"] = out["version"]
    else:
        old = json.loads(r["metrics"] or "{}")
        for k in ("extracted", "extracted_model", "extracted_version"):
            if k in old: m[k] = old[k]
    with con:
        con.execute("UPDATE runs SET metrics=? WHERE id=?", (json.dumps(m), r["id"]))
    n += 1
    print(f"run {r['id']}: rescored" + (" + re-extracted" if extract and cfg.get("speech_mode") == "free" else ""))
print(f"rescored {n} run(s) of experiment {EID}")
