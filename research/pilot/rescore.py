"""Rescore an experiment uniformly with the current code.
  python research/pilot/rescore.py <experiment id> [--no-extract] [--force] [--with-low-coverage]
Typed games: the battery is recomputed from the log. Free games: the stored
extraction file is re-adjudicated with the current deterministic rules (repeats
counted once, trade intentions are not partner-hand claims, ledger replay) with
no extractor call; --force re-reads every line with the extractor; --no-extract
never calls an LLM (a game without an extraction file keeps its stored numbers).
Resumable: run it again after a crash."""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena import db
from arena.metrics import game_metrics
from arena.costs import run_cost
from arena.runner import load_env
from arena.extractor import attach_extraction, rescore_extraction, extractor_choice

EID = int(sys.argv[1])
allow_llm = "--no-extract" not in sys.argv
force = "--force" in sys.argv
load_env()
con = db.connect()
statuses = ("done", "low_coverage") if "--with-low-coverage" in sys.argv else ("done",)
rows = con.execute(f"SELECT id, log_path, config, metrics FROM runs WHERE experiment_id=? AND status IN ({','.join('?'*len(statuses))}) "
                   "AND log_path IS NOT NULL", (EID, *statuses)).fetchall()
provider = None
n = {"typed": 0, "readjudicated": 0, "extracted": 0, "kept": 0}
for r in rows:
    log = json.loads((ROOT / r["log_path"]).read_text())
    m = game_metrics(log)
    cfg = json.loads(r["config"] or "{}")
    old = json.loads(r["metrics"] or "{}")
    how = "typed"
    if cfg.get("speech_mode") == "free":
        out = None if force else rescore_extraction(log, ROOT / r["log_path"])
        if out is None and allow_llm:
            pname, pmodel = extractor_choice()
            if provider is None:
                from arena.providers import get_provider
                provider = get_provider(pname)
            out = attach_extraction(log, ROOT / r["log_path"], provider, pmodel)
            how = "extracted"
        elif out is not None:
            how = "readjudicated"
        if out is not None:
            m["extracted"] = out["per_seat"]; m["extracted_model"] = out["model"]; m["extracted_version"] = out["version"]
        else:
            how = "kept"
            for k in ("extracted", "extracted_model", "extracted_version", "extraction_error"):
                if k in old:
                    m[k] = old[k]
    cost = run_cost(m)
    with con:
        con.execute("UPDATE runs SET metrics=?, cost_usd=? WHERE id=?",
                    (json.dumps(m), cost["usd"] if cost["usd"] is not None else 0.0, r["id"]))
    n[how] += 1
    print(f"run {r['id']}: {how}", flush=True)
print(f"experiment {EID}: {n}")
