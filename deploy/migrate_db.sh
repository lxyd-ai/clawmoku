#!/usr/bin/env bash
# Clawmoku — Migrate SQLite DB from old server to new server.
#
# Usage (run from LOCAL machine):
#   bash deploy/migrate_db.sh
#
# Env overrides:
#   OLD_HOST=47.243.182.151   OLD_PASSWORD=***REMOVED***
#   NEW_HOST=8.217.39.83      NEW_PASSWORD=***REMOVED***
#   REMOTE_DIR=/srv/clawmoku
set -euo pipefail

OLD_HOST="${OLD_HOST:-47.243.182.151}"
OLD_PASSWORD="${OLD_PASSWORD:-***REMOVED***}"
NEW_HOST="${NEW_HOST:-8.217.39.83}"
NEW_PASSWORD="${NEW_PASSWORD:-***REMOVED***}"
REMOTE_DIR="${REMOTE_DIR:-/srv/clawmoku}"
DB_PATH="$REMOTE_DIR/data/clawmoku.db"
TMP_DB="/tmp/clawmoku-migrate-$(date +%Y%m%dT%H%M%S).db"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass not found. Install via: brew install sshpass" >&2
  exit 1
fi

echo "==> [1/4] Hot-backup DB on old server ($OLD_HOST)"
sshpass -p "$OLD_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$OLD_HOST" \
  "sqlite3 $DB_PATH \".backup '$TMP_DB'\" && echo 'backup ok: $(du -h $TMP_DB | cut -f1)'"

echo "==> [2/4] Download DB from old server"
LOCAL_TMP="$(mktemp /tmp/clawmoku-XXXXXX.db)"
sshpass -p "$OLD_PASSWORD" scp -o StrictHostKeyChecking=no \
  "root@$OLD_HOST:$TMP_DB" "$LOCAL_TMP"
echo "    downloaded: $LOCAL_TMP ($(du -h "$LOCAL_TMP" | cut -f1))"

echo "==> [3/4] Stop API on new server, upload DB, fix ownership"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "systemctl stop clawmoku-api 2>/dev/null || true; mkdir -p $REMOTE_DIR/data"
sshpass -p "$NEW_PASSWORD" scp -o StrictHostKeyChecking=no \
  "$LOCAL_TMP" "root@$NEW_HOST:$DB_PATH"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "chown clawmoku:clawmoku $DB_PATH && chmod 640 $DB_PATH && \
   sqlite3 $DB_PATH 'SELECT COUNT(*) || \" agents\" FROM agents; SELECT COUNT(*) || \" matches\" FROM matches;'"

echo "==> [4/4] Start services on new server"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "systemctl start clawmoku-api clawmoku-web && sleep 3 && \
   systemctl is-active clawmoku-api clawmoku-web"

rm -f "$LOCAL_TMP"
echo "==> DB migration complete. Check: curl http://$NEW_HOST:9001/healthz"
