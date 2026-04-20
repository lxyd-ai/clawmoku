#!/usr/bin/env bash
# Clawmoku — Migrate SQLite DB from old server to new server.
#
# Usage (run from LOCAL machine):
#   OLD_HOST=... OLD_PASSWORD=... NEW_HOST=... NEW_PASSWORD=... \
#     bash deploy/migrate_db.sh
#
# Required env:
#   OLD_HOST, OLD_PASSWORD   — source server (must already have Clawmoku running)
#   NEW_HOST, NEW_PASSWORD   — destination server (clawmoku-api systemd unit present)
#
# Optional env:
#   REMOTE_DIR=/srv/clawmoku
#   DB_ABS_PATH=/var/lib/clawmoku/clawmoku.db   # destination DB absolute path
#
# Note: credentials are NEVER defaulted or checked into git (this repo is public).
# Put them in ./.env.deploy (gitignored) or pass via env on the command line.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env.deploy ]; then
  set -a; . ./.env.deploy; set +a
fi

: "${OLD_HOST:?OLD_HOST is required}"
: "${OLD_PASSWORD:?OLD_PASSWORD is required}"
: "${NEW_HOST:?NEW_HOST is required}"
: "${NEW_PASSWORD:?NEW_PASSWORD is required}"

REMOTE_DIR="${REMOTE_DIR:-/srv/clawmoku}"
DB_ABS_PATH="${DB_ABS_PATH:-/var/lib/clawmoku/clawmoku.db}"
# Old layout stored DB under $REMOTE_DIR/data; fall back to that on source side.
OLD_DB_PATH="${OLD_DB_PATH:-$REMOTE_DIR/data/clawmoku.db}"
TMP_DB="/tmp/clawmoku-migrate-$(date +%Y%m%dT%H%M%S).db"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass not found. Install via: brew install sshpass" >&2
  exit 1
fi

echo "==> [1/4] Hot-backup DB on old server ($OLD_HOST)  src=$OLD_DB_PATH"
sshpass -p "$OLD_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$OLD_HOST" \
  "sqlite3 $OLD_DB_PATH \".backup '$TMP_DB'\" && echo 'backup ok: '\$(du -h $TMP_DB | cut -f1)"

echo "==> [2/4] Download DB from old server"
LOCAL_TMP="$(mktemp /tmp/clawmoku-XXXXXX.db)"
sshpass -p "$OLD_PASSWORD" scp -o StrictHostKeyChecking=no \
  "root@$OLD_HOST:$TMP_DB" "$LOCAL_TMP"
echo "    downloaded: $LOCAL_TMP ($(du -h "$LOCAL_TMP" | cut -f1))"

echo "==> [3/4] Stop API on new server, upload DB, fix ownership  dst=$DB_ABS_PATH"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "systemctl stop clawmoku-api 2>/dev/null || true; mkdir -p $(dirname "$DB_ABS_PATH")"
sshpass -p "$NEW_PASSWORD" scp -o StrictHostKeyChecking=no \
  "$LOCAL_TMP" "root@$NEW_HOST:$DB_ABS_PATH"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "chown clawmoku:clawmoku $DB_ABS_PATH && chmod 640 $DB_ABS_PATH && \
   sqlite3 $DB_ABS_PATH 'SELECT COUNT(*) || \" agents\" FROM agents; SELECT COUNT(*) || \" matches\" FROM matches;'"

echo "==> [4/4] Start services on new server"
sshpass -p "$NEW_PASSWORD" ssh -o StrictHostKeyChecking=no "root@$NEW_HOST" \
  "systemctl start clawmoku-api clawmoku-web && sleep 3 && \
   systemctl is-active clawmoku-api clawmoku-web"

rm -f "$LOCAL_TMP"
echo "==> DB migration complete. Check: curl http://$NEW_HOST:9001/healthz"
