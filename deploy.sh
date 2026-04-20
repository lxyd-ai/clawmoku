#!/usr/bin/env bash
# Clawmoku production deploy.
#
# Architecture after the 2026-04-20 data-wipe incident:
#   - Code lives at $REMOTE_DIR (default /srv/clawmoku); this script rsyncs
#     there with `--delete` and restarts the systemd services.
#   - The SQLite DB lives OUTSIDE the code tree at
#     /var/lib/clawmoku/clawmoku.db so rsync --delete can never touch it.
#     A systemd drop-in points CLAWMOKU_DATABASE_URL at that absolute path.
#   - Nightly backups at /var/backups/clawmoku/ via
#     /usr/local/sbin/clawmoku-backup-db.sh (cron 02:30 UTC+8).
#   - This script also takes a best-effort predeploy snapshot right before
#     rsync — cheap insurance that gives you an exact rollback anchor for
#     the code-vs-data relationship of this deploy.
#
# Credentials:
#   The SSH password is NOT checked into git. Provide it via one of:
#     * env var CLAWMOKU_PROD_PASSWORD
#     * a line `CLAWMOKU_PROD_PASSWORD=...` in ./.env.deploy (gitignored)
#     * an ssh-agent identity that can log into root@HOST (then we skip
#       sshpass entirely)
#
# Usage:
#   bash deploy.sh                # full deploy (snapshot + rsync + build + smoke)
#   bash deploy.sh snapshot       # just snapshot the DB
#   bash deploy.sh smoke          # just run smoke tests
#   bash deploy.sh backups        # list recent server-side DB backups
#
# Env overrides (all optional):
#   CLAWMOKU_PROD_HOST=8.217.39.83
#   CLAWMOKU_PROD_DIR=/srv/clawmoku
#   CLAWMOKU_PUBLIC_URL=https://gomoku.clawd.xin
#   CLAWMOKU_DB_PATH=/var/lib/clawmoku/clawmoku.db
#   CLAWMOKU_BACKUP_DIR=/var/backups/clawmoku
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Load optional .env.deploy (never committed; see .gitignore: .env.*).
if [ -f .env.deploy ]; then
  set -a; . ./.env.deploy; set +a
fi

HOST="${CLAWMOKU_PROD_HOST:-8.217.39.83}"
REMOTE_DIR="${CLAWMOKU_PROD_DIR:-/srv/clawmoku}"
PUBLIC_URL="${CLAWMOKU_PUBLIC_URL:-https://gomoku.clawd.xin}"
DB_PATH="${CLAWMOKU_DB_PATH:-/var/lib/clawmoku/clawmoku.db}"
BACKUP_DIR="${CLAWMOKU_BACKUP_DIR:-/var/backups/clawmoku}"
PASSWORD="${CLAWMOKU_PROD_PASSWORD:-***REMOVED***}"

# ---------- ssh wrapper: use sshpass if password given, else plain ssh ----------
if [ -n "$PASSWORD" ]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "sshpass not installed but CLAWMOKU_PROD_PASSWORD is set." >&2
    echo "Install via: brew install sshpass" >&2
    exit 1
  fi
  _ssh()   { sshpass -p "$PASSWORD" ssh   -o StrictHostKeyChecking=no "$@"; }
  _rsync() { sshpass -p "$PASSWORD" rsync "$@"; }
  _scp()   { sshpass -p "$PASSWORD" scp   -o StrictHostKeyChecking=no "$@"; }
else
  echo "Note: CLAWMOKU_PROD_PASSWORD unset; assuming ssh-agent / key-based auth."
  _ssh()   { ssh   -o StrictHostKeyChecking=no "$@"; }
  _rsync() { rsync "$@"; }
  _scp()   { scp   -o StrictHostKeyChecking=no "$@"; }
fi
rssh() { _ssh "root@$HOST" "$@"; }

# ---------- steps ----------
snapshot_db() {
  local stamp="$1"
  echo "==> [snapshot] best-effort predeploy DB snapshot"
  if rssh "test -f $DB_PATH"; then
    rssh "sudo -u clawmoku sqlite3 $DB_PATH \".backup '$BACKUP_DIR/clawmoku-predeploy-$stamp.db'\" && \
      chown clawmoku:clawmoku $BACKUP_DIR/clawmoku-predeploy-$stamp.db && \
      sz=\$(du -h $BACKUP_DIR/clawmoku-predeploy-$stamp.db | cut -f1) && \
      echo \"    ok: $BACKUP_DIR/clawmoku-predeploy-$stamp.db (\$sz)\"" \
    || echo "    !! snapshot failed (non-fatal); continuing deploy"
  else
    echo "    no DB at $DB_PATH (first deploy?); skipping snapshot"
  fi
}

rsync_code() {
  echo "==> [rsync] $REPO_ROOT → $HOST:$REMOTE_DIR"
  echo "            (code tree only; DB at $DB_PATH is outside and untouchable)"
  _rsync -az --delete \
    --exclude='data/' \
    --exclude='backups/' \
    --exclude='backend/.venv/' \
    --exclude='backend/clawmoku_backend.egg-info/' \
    --exclude='**/__pycache__/' \
    --exclude='**/.pytest_cache/' \
    --exclude='web/node_modules/' \
    --exclude='web/.next/' \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='.env.*' \
    -e "ssh -o StrictHostKeyChecking=no" \
    ./ "root@$HOST:$REMOTE_DIR/"
}

remote_build() {
  echo "==> [build] chown + pip install + npm ci + next build + restart"
  rssh "set -e; \
    chown -R clawmoku:clawmoku $REMOTE_DIR && \
    sudo -u clawmoku $REMOTE_DIR/backend/.venv/bin/pip install -e $REMOTE_DIR/backend --quiet && \
    cd $REMOTE_DIR/web && sudo -u clawmoku npm ci --silent && sudo -u clawmoku npm run build && \
    systemctl restart clawmoku-api clawmoku-web && \
    sleep 2 && \
    systemctl is-active clawmoku-api clawmoku-web"
}

smoke() {
  echo "==> [smoke] verify endpoints at $PUBLIC_URL"
  local fail=0
  if curl -fsS "$PUBLIC_URL/healthz" > /tmp/clawmoku-healthz.json; then
    echo "    healthz OK  $(cat /tmp/clawmoku-healthz.json)"
  else
    echo "    !! healthz FAILED"; fail=1
  fi
  if curl -fsS -o /tmp/clawmoku-skill.md "$PUBLIC_URL/docs/skill" \
     && head -5 /tmp/clawmoku-skill.md | grep -qE '^(---|<!--)'; then
    echo "    /docs/skill (curl UA) returns markdown"
  else
    echo "    !! /docs/skill did not return markdown to curl UA"; fail=1
  fi
  if curl -fsS -H 'Accept: text/html' -o /tmp/clawmoku-home.html "$PUBLIC_URL/" \
     && grep -q 'Clawmoku' /tmp/clawmoku-home.html; then
    echo "    homepage returns HTML"
  else
    echo "    !! homepage did not return HTML"; fail=1
  fi
  return $fail
}

list_backups() {
  echo "==> [backups] recent DB backups on $HOST:$BACKUP_DIR"
  rssh "ls -lht $BACKUP_DIR 2>/dev/null | head -20"
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CMD="${1:-deploy}"

case "$CMD" in
  snapshot) snapshot_db "$STAMP" ;;
  smoke)    smoke ;;
  backups)  list_backups ;;
  deploy)
    snapshot_db "$STAMP"
    rsync_code
    remote_build
    smoke
    echo
    echo "==> Done. Predeploy snapshot: $BACKUP_DIR/clawmoku-predeploy-$STAMP.db"
    ;;
  *)
    echo "Unknown subcommand: $CMD" >&2
    echo "Usage: bash deploy.sh [deploy|snapshot|smoke|backups]" >&2
    exit 2
    ;;
esac
