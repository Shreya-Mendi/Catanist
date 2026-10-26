# Deploying the MARA: Deception console on AWS

The console is a single lightweight Python process (stdlib web server, SQLite,
worker threads that call model APIs). It is I/O-bound, not CPU-bound: five
users and four parallel games sit far below one vCPU.

## Instance
- **t3.small (2 vCPU, 2 GB), Ubuntu 24.04 LTS, 20 GB gp3** — the right default.
  Running a few hours a day ≈ $2-3/month compute + ~$1.60/month storage.
- Use **t3.medium** only if you raise CONSOLE_WORKERS past ~8.
- Attach an **Elastic IP** so the URL never changes across stop/start (small
  hourly fee only while the instance is stopped).
- Security group: TCP 8756 **restricted to the team's IPs** (the whitelist),
  TCP 22 to the admin only. Nothing else open.

## Install
```bash
git clone https://github.com/duke-trust-lab/mara-deception.git && cd mara-deception
sudo bash deploy/setup.sh
sudo nano /opt/mara/.env        # OPENAI_API_KEY=... GOOGLE_API_KEY=... TINKER_API_KEY=...
cd /opt/mara && sudo -u mara .venv/bin/python run.py adduser shreya   # repeat per teammate
sudo systemctl start mara-console
```

## Persistence (what survives stop/start)
Everything that matters lives on the EBS volume under /opt/mara: the SQLite
index (logs/arena.db, WAL mode — fine for a 5-person lab), every game log and
replay (logs/*.json, *_scene.html), labels, annotations, exports. Stopping the
instance or the service loses nothing; runs interrupted mid-game re-queue
automatically at the next start (boot recovery).

Optional nightly backup (root crontab):
```
15 3 * * * tar -czf /opt/mara/backups/mara-$(date +\%F).tgz -C /opt/mara logs research/battery-v1.md && ls -t /opt/mara/backups/*.tgz | tail -n +15 | xargs -r rm
```

## A-few-hours-a-day operation
Stop the *instance* when done (cheapest, persistence is on disk) or just
`systemctl stop mara-console`. On start, the service comes up by itself,
requeues any orphaned runs, and the team logs back in with the same accounts.

## Knobs
- `CONSOLE_WORKERS` (systemd unit): parallel games; 1 = strictly serial.
- `CATAN_PACE_S`: per-call pacing floor if a provider ever rate-limits.

## Frozen
Game rules, speech schema, and the violation battery (research/battery-v1.md,
with dated addenda). Rule changes are battery-version conversations, not edits.

## Per-user API keys (2026-10-14)

Runs are billed to the console user who queued them when that user has a key in
`/opt/mara/.env`: `OPENAI_API_KEY_<USER>` with the user name upper-cased and
non-alphanumerics replaced by `_`, for example
`OPENAI_API_KEY_DECEPTION_PERCEPTION=sk-...`. Without one, the shared
`OPENAI_API_KEY` is used. The queue is fair across users: the user with the
fewest games in flight goes next. New keys are read when a worker process
starts: either `sudo systemctl restart mara-console` (interrupts games in
flight; they are requeued) or start sidecar workers that join the live server:

```
cd /opt/mara && sudo -u mara env CONSOLE_RECOVER=0 CONSOLE_WORKERS=2 \
  .venv/bin/python -c "from arena.runner import load_env; load_env(); from arena import jobs; import time; jobs.start_workers(); [time.sleep(60) for _ in iter(int, 1)]"
```

## Reasoning models (2026-10-24)

gpt-5 family seats send `reasoning_effort` (default `low`) and a 3,000-token completion cap. Set `OPENAI_REASONING_EFFORT=minimal|low|medium|high` in `.env` to change it for every gpt-5 call; hidden reasoning is billed as output, so pilot 3 seeds and read the ledger before scaling.

## Platform round of 2026-10-25

- New tables and columns (overrides, run_scores, groups, group_members, group_files, activity;
  labels.reason, experiments.group_id/prereg, runs.excluded/exclude_reason/metrics_corrected/cost_usd)
  migrate themselves on the first `db.connect()` after the ship. Nothing to run.
- Group files live under `logs/groups/<id>/` (outside git, next to the game logs).
- Prices changed (Tinker priced, gpt-6 family added). Re-price finished games once after the ship:
  `cd /opt/mara && sudo -u mara .venv/bin/python -c "from arena import db, costs; print(costs.backfill_costs(db.connect(), force=True))"`
- Fonts load from api.fontshare.com (Satoshi, Clash Display); the console falls back to system fonts offline.
- Seed the E1 package group on the box with the local research files (they stay out of git):
  copy `research/e1/*`, `research/research-notes.md`, `research/budget-2026-10-25.md` to the box's
  `research/` first, then `python research/pilot/seed_e1_group.py --root /opt/mara`.

## Data layout and the ship order (2026-10-25)

Game logs now live in `logs/<hypothesis>/<experiment>/` (for example
`logs/H1-instrument-E1/exp24-E1-main-typed-vs-free-30-seeds-schema-v2/`), with each game's
extraction and replay beside it; `logs/unfiled/` holds games with no experiment and
`logs/groups/<id>/` the files attached to hypothesis pages. `runs.log_path` is the path from the
repo root, so the console, rescore and bundle scripts follow it. New games are saved there by
the queue. Nothing in the ship touches `logs/`.

Ship order, so no run data is ever at risk:
1. `sudo -u mara bash /opt/mara/deploy/backup.sh` (database copy + logs.tgz under /opt/mara/backups/).
2. Push, rsync the code (never logs or .env), restart the service in a quiet window.
3. `python research/pilot/organize_logs.py --root /opt/mara --experiments 21,22,23,24,25,27,28,29,30`
   (dry run, prints the plan), then the same with `--apply` for H1; then without `--experiments` for the rest.
4. Re-price: `.venv/bin/python -c "from arena import db, costs; print(costs.backfill_costs(db.connect(), force=True))"`.
5. Seed the E1 package group (files copied to the box's research/ first), then the box rescore.
