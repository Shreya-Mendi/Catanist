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
    with con:
        row = con.execute("SELECT id FROM runs WHERE status='queued' "
                          "ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        got = con.execute("UPDATE runs SET status='running', started=? "
                          "WHERE id=? AND status='queued'",
                          (time.time(), row["id"])).rowcount
        return row["id"] if got else None


def _work(worker_id: int):
    con = db.connect()
    while True:
        rid = _claim(con)
        if rid is None:
            time.sleep(1.5)
            continue
        cfg = json.loads(con.execute("SELECT config FROM runs WHERE id=?",
                                     (rid,)).fetchone()["config"])
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
            metrics = json.dumps(game_metrics(result))
            with con:
                con.execute("UPDATE runs SET status='done', finished=?, "
                            "log_path=?, metrics=? WHERE id=?",
                            (time.time(), f"logs/{path.name}", metrics, rid))
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
