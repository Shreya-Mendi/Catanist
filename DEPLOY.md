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
