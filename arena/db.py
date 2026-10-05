"""SQLite layer for the experiment console.

The JSON game logs stay the source of truth; this database is the index over
them: who ran what, under which condition, plus labels and notes. One file at
logs/arena.db (WAL mode) so the whole lab state rides along with the logs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "arena.db"
SECRET_PATH = ROOT / ".console_secret"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  salt BLOB NOT NULL, pwhash BLOB NOT NULL,
  is_admin INTEGER DEFAULT 0, created REAL);
CREATE TABLE IF NOT EXISTS experiments(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT,
  hypothesis TEXT DEFAULT '', notes TEXT DEFAULT '',
  battery TEXT DEFAULT 'v1', created REAL);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, experiment_id INTEGER, owner TEXT,
  config TEXT NOT NULL, condition TEXT DEFAULT '', seed INTEGER DEFAULT 0,
  status TEXT DEFAULT 'queued',           -- queued|running|done|failed
  progress_turn INTEGER DEFAULT 0, progress_vps TEXT,
  max_turns INTEGER DEFAULT 120,
  log_path TEXT, metrics TEXT, error TEXT,
  created REAL, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS labels(
  id INTEGER PRIMARY KEY, run_id INTEGER, event_idx INTEGER,
  statement TEXT, context TEXT, label TEXT, labeler TEXT, created REAL,
  UNIQUE(run_id, event_idx, labeler));
CREATE TABLE IF NOT EXISTS annotations(
  id INTEGER PRIMARY KEY, experiment_id INTEGER, author TEXT,
  text TEXT, created REAL);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    # self-migrations for databases created by older schemas
    cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    if "progress_vps" not in cols:
        con.execute("ALTER TABLE runs ADD COLUMN progress_vps TEXT")
        con.commit()
    return con


# --- auth ----------------------------------------------------------------------
def _secret() -> bytes:
    if not SECRET_PATH.exists():
        SECRET_PATH.write_bytes(os.urandom(32))
    return SECRET_PATH.read_bytes()


def create_user(name: str, password: str, is_admin: bool = False):
    salt = os.urandom(16)
    pw = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    con = connect()
    with con:
        con.execute("INSERT OR REPLACE INTO users(name,salt,pwhash,is_admin,created) "
                    "VALUES(?,?,?,?,?)", (name, salt, pw, int(is_admin), time.time()))
    con.close()


def verify_user(name: str, password: str) -> bool:
    con = connect()
    row = con.execute("SELECT salt,pwhash FROM users WHERE name=?", (name,)).fetchone()
    con.close()
    if not row:
        return False
    pw = hashlib.scrypt(password.encode(), salt=row["salt"], n=2**14, r=8, p=1)
    return hmac.compare_digest(pw, row["pwhash"])


def make_token(name: str, days: int = 14) -> str:
    exp = str(int(time.time() + days * 86400))
    sig = hmac.new(_secret(), f"{name}|{exp}".encode(), "sha256").hexdigest()
    return f"{name}|{exp}|{sig}"


def check_token(token: str) -> str | None:
    try:
        name, exp, sig = token.split("|")
    except ValueError:
        return None
    want = hmac.new(_secret(), f"{name}|{exp}".encode(), "sha256").hexdigest()
    if hmac.compare_digest(sig, want) and time.time() < float(exp):
        return name
    return None


# --- backfill ------------------------------------------------------------------
def backfill_logs():
    """Index any log JSON not yet in the runs table (legacy + CLI games)."""
    con = connect()
    known = {r["log_path"] for r in con.execute("SELECT log_path FROM runs")}
    n = 0
    for f in sorted((ROOT / "logs").glob("*.json")):
        rel = f"logs/{f.name}"
        if rel in known:
            continue
        try:
            d = json.loads(f.read_text())
            if "events" not in d:
                continue
        except Exception:
            continue
        from .metrics import game_metrics
        try:
            m = json.dumps(game_metrics(d))
        except Exception:
            m = None
        with con:
            con.execute(
                "INSERT INTO runs(experiment_id,owner,config,condition,status,"
                "log_path,metrics,created,finished) VALUES(NULL,'legacy',?,?,'done',?,?,?,?)",
                (json.dumps({"name": d.get("config_name", f.stem)}),
                 "legacy", rel, m, f.stat().st_mtime, f.stat().st_mtime))
        n += 1
    con.close()
    return n
