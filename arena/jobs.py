"""Background run queue for the console.

A small pool of worker threads claims queued runs from the DB, executes them
with live per-turn progress, saves the JSON log + illustrated scene, computes
the battery metrics, and marks the row done/failed. Sequential-by-default is
rate-limit insurance; CONSOLE_WORKERS raises parallelism on funded keys.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback

from . import db
from .metrics import game_metrics
from .runner import run_one, save_result, _provider_cache

_providers = _provider_cache()
_started = False


def _claim(con):
    """Next run to play. Fair across console users (2026-10-14): the user
    with the fewest games in flight goes first, ties in queue order, so a
    teammate's single run does not wait behind a 180-game batch."""
    with con:
        rows = con.execute("SELECT id, owner, COALESCE(priority, 0) AS priority FROM runs "
                           "WHERE status='queued' ORDER BY id").fetchall()
        if not rows:
            return None
        running = dict(con.execute("SELECT owner, COUNT(*) FROM runs WHERE status='running' "
                                   "GROUP BY owner").fetchall())
        # fairness across users first, then 'run next' priority, then queue order
        best = min(rows, key=lambda r: (running.get(r["owner"], 0), r["priority"], r["id"]))
        got = con.execute("UPDATE runs SET status='running', started=? "
                          "WHERE id=? AND status='queued'",
                          (time.time(), best["id"])).rowcount
        return best["id"] if got else None


def _work(worker_id: int):
    con = db.connect()
    while True:
        rid = _claim(con)
        if rid is None:
            time.sleep(1.5)
            continue
        row = con.execute("SELECT config, owner FROM runs WHERE id=?", (rid,)).fetchone()
        cfg = json.loads(row["config"])
        cfg["_owner"] = row["owner"]                  # per-user API keys (providers.owner_key_name)
        from .runner import LOG_DIR
        live = LOG_DIR / f".live_run{rid}.json"
        cfg["_live_path"] = str(live)
        def tick(turn, vps, _rid=rid):
            import json as _j
            con.execute("UPDATE runs SET progress_turn=?, progress_vps=? WHERE id=?",
                        (turn, _j.dumps(vps), _rid))
            con.commit()
        try:
            result = run_one(cfg, _providers, progress_cb=tick)
            path = save_result(result, tag=f"run{rid}")
            try:                                  # replay + gallery, best effort
                from viz.scene import render as render_scene
                from viz.gallery import build_gallery
                render_scene(result, path.with_name(path.stem + "_scene.html"))
                build_gallery()
            except Exception as e:
                print(f"[jobs] scene render failed for {path.name}: "
                      f"{type(e).__name__}: {e}", flush=True)
            mdict = game_metrics(result)
            # free arm: the typed battery reads nothing, so score the free text
            # with the extractor (LLM proposes acts, engine adjudicates) and keep
            # the per-seat result under "extracted" (CONSOLE_EXTRACT=0 disables)
            if cfg.get("speech_mode") == "free" and \
                    os.environ.get("CONSOLE_EXTRACT", "1") != "0":
                try:
                    from .extractor import attach_extraction, extractor_choice
                    pname, pmodel = extractor_choice()
                    out = attach_extraction(result, path, _providers(pname), pmodel)
                    mdict["extracted"] = out["per_seat"]
                    mdict["extracted_model"] = out["model"]
                    mdict["extracted_version"] = out["version"]
                except Exception as e:
                    print(f"[jobs] extraction failed for {path.name}: "
                          f"{type(e).__name__}: {e}", flush=True)
                    mdict["extraction_error"] = f"{type(e).__name__}: {e}"[:300]
            # coverage gate (battery v1 rule, enforced 2026-10-14): a game in which
            # any seat played fewer than 95% of its decisions itself (provider
            # errors -> engine fallback) is kept but marked, and requeued once
            covs = [pd.get("coverage") for pd in (mdict.get("players") or {}).values()]
            low = [c for c in covs if c is not None and c < 0.95]
            if low:
                mdict["low_coverage"] = min(low)
                row = con.execute("SELECT config, condition, seed, max_turns, owner, experiment_id, error "
                                  "FROM runs WHERE id=?", (rid,)).fetchone()
                already = "requeue of run" in (row["error"] or "")
                with con:
                    if not already:
                        con.execute("INSERT INTO runs(experiment_id,owner,config,condition,seed,max_turns,"
                                    "status,error,created) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (row["experiment_id"], row["owner"], row["config"], row["condition"],
                                     row["seed"], row["max_turns"], "queued",
                                     f"requeue of run {rid} (coverage {min(low):.2f})", time.time()))
                print(f"[jobs] run {rid}: low coverage {min(low):.2f}"
                      + ("" if already else ", requeued once"), flush=True)
            metrics = json.dumps(mdict)
            with con:
                con.execute("UPDATE runs SET status=?, finished=?, "
                            "log_path=?, metrics=? WHERE id=?",
                            ("low_coverage" if low else "done", time.time(), f"logs/{path.name}", metrics, rid))
            live.unlink(missing_ok=True)
        except Exception as e:
            live.unlink(missing_ok=True)
            with con:
                con.execute("UPDATE runs SET status='failed', finished=?, error=? "
                            "WHERE id=?",
                            (time.time(), f"{type(e).__name__}: {e}\n"
                             + traceback.format_exc()[-800:], rid))


def start_workers():
    global _started
    if _started:
        return
    _started = True
    # boot recovery: a run left 'running' by a stopped server has no worker —
    # requeue it so nothing is stranded (it restarts from scratch).
    # CONSOLE_RECOVER=0 skips this — required for sidecar workers that join a
    # live server, whose 'running' rows have real workers behind them.
    if os.environ.get("CONSOLE_RECOVER", "1") == "0":
        n = int(os.environ.get("CONSOLE_WORKERS", "1") or 1)
        for i in range(n):
            threading.Thread(target=_work, args=(i,), daemon=True).start()
        return
    con = db.connect()
    with con:
        n_orphan = con.execute(
            "UPDATE runs SET status='queued', started=NULL, progress_turn=0, "
            "progress_vps=NULL WHERE status='running'").rowcount
    con.close()
    if n_orphan:
        print(f"[jobs] requeued {n_orphan} orphaned run(s) from a previous server")
    # serial by default (one game at a time, in queue order); raise with
    # CONSOLE_WORKERS=2+ when parallel throughput matters more than watchability
    n = int(os.environ.get("CONSOLE_WORKERS", "1") or 1)
    for i in range(n):
        threading.Thread(target=_work, args=(i,), daemon=True).start()
