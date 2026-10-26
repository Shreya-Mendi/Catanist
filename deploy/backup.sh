#!/usr/bin/env bash
# Backup before a ship or a data reorganisation (2026-10-25): a consistent copy of the
# database and every game log, kept on the box under /opt/mara/backups/<stamp>/.
#   sudo -u mara bash /opt/mara/deploy/backup.sh
set -euo pipefail
ROOT=/opt/mara
STAMP=$(date -u +%Y%m%d-%H%M%S)
DEST=$ROOT/backups/$STAMP
mkdir -p "$DEST"
"$ROOT/.venv/bin/python" - "$ROOT" "$DEST" <<'PY'
import sqlite3, sys
root, dest = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"{root}/logs/arena.db"); dst = sqlite3.connect(f"{dest}/arena.db")
src.backup(dst); dst.close(); src.close()
print("database copied")
PY
tar czf "$DEST/logs.tgz" -C "$ROOT" --exclude='logs/arena.db*' logs
du -sh "$DEST"
echo "backup at $DEST"
