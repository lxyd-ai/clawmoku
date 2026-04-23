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
# DO NOT run as `bash deploy.sh | tail -N`. Pipeline buffering will hide
# every intermediate line — including the build progress and the OOM
# canaries — until after the deploy returns, which makes a stuck deploy
# look identical to a healthy one. Just run the script directly and let
# it stream to your terminal.
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
# `ServerAliveInterval=15 + CountMax=8` keeps the long-running build ssh
# session from getting reaped by NAT/firewall idle timers, which used to
# show up as "the deploy hung after 6 minutes" when the heredoc went
# silent during a slow `npm ci`. The values give us 15s × 8 = 2min of
# silence tolerance, which is more than the longest internal step.
SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=8
)
if [ -n "$PASSWORD" ]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "sshpass not installed but CLAWMOKU_PROD_PASSWORD is set." >&2
    echo "Install via: brew install sshpass" >&2
    exit 1
  fi
  _ssh()   { sshpass -p "$PASSWORD" ssh   "${SSH_OPTS[@]}" "$@"; }
  _rsync() { sshpass -p "$PASSWORD" rsync "$@"; }
  _scp()   { sshpass -p "$PASSWORD" scp   "${SSH_OPTS[@]}" "$@"; }
else
  echo "Note: CLAWMOKU_PROD_PASSWORD unset; assuming ssh-agent / key-based auth."
  _ssh()   { ssh   "${SSH_OPTS[@]}" "$@"; }
  _rsync() { rsync "$@"; }
  _scp()   { scp   "${SSH_OPTS[@]}" "$@"; }
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
  # Wipe any leftover staging dir from a previous interrupted deploy
  # before rsync runs. Otherwise --delete trips on `web.build/` because
  # it exists locally too only as a missing path → noisy "cannot delete
  # non-empty directory" warnings, plus a small risk of stale node_modules
  # surviving into the next staging cycle.
  rssh "rm -rf '$REMOTE_DIR/web.build' || true" 2>/dev/null || true
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
  # Strategy: keep the running clawmoku-web process happy during the slow
  # (~90s) `npm ci && next build` window. We used to run those in-place
  # inside $REMOTE_DIR/web, which meant:
  #   - npm ci blew away node_modules that the running `next start` was
  #     loading lazily for new requests
  #   - next build rewrote .next/ under the running process's feet
  # Either one takes prod to 502 for ~2 minutes. Fix: build inside a
  # side directory ($REMOTE_DIR/web.build/) that's a cheap hard-linked
  # copy of web/, and only swap .next/ + node_modules/ into place once
  # the new artifacts are complete. Then restart services as the
  # absolute last step, which is the only user-visible downtime window.
  #
  # Implementation note: we pipe the recipe into `bash -s` via heredoc
  # rather than stuffing it into a single-line `rssh "…"` call, because
  # the latter silently swallowed the `npm ci / next build` step in
  # practice (shell quoting + line-continuation interactions). Heredoc
  # is unambiguous and trivially readable.
  #
  # Robustness guard rails (added 2026-04-23 after a deploy OOM'd the
  # whole VM and took sshd / nginx down with it for ~5 minutes):
  #   - Cap node's heap (`NODE_OPTIONS=--max-old-space-size=1024`) so
  #     `next build` self-aborts before pushing the box into swap-thrash.
  #   - Wrap the build in `timeout 300` so a stuck process can't ride
  #     the ssh session into oblivion either.
  #   - Print `free -m` before & after the build so OOMs leave a paper
  #     trail in the deploy log instead of just "ssh hung at minute 6".
  #   - Each remote step is timestamped via STEP() — easy to spot which
  #     phase ran how long.
  echo "==> [build] staging build → swap → restart (prod stays up during build)"
  rssh "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE_SH'
set -euo pipefail
: "${REMOTE_DIR:?REMOTE_DIR unset}"
STAGE="$REMOTE_DIR/web.build"

STEP() { printf '  • [%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

STEP "chown code tree"
chown -R clawmoku:clawmoku "$REMOTE_DIR"

STEP "backend: pip install -e (safe — running process restarts at end)"
sudo -u clawmoku "$REMOTE_DIR/backend/.venv/bin/pip" install -e "$REMOTE_DIR/backend" --quiet

STEP "frontend: prepare staging at $STAGE (hard-linked copy)"
rm -rf "$STAGE"
sudo -u clawmoku cp -al "$REMOTE_DIR/web" "$STAGE"
# Break hard links to prod's node_modules/.next so the rebuild below
# can't accidentally mutate the tree the live process is serving from.
sudo -u clawmoku rm -rf "$STAGE/node_modules" "$STAGE/.next"

STEP "memory snapshot before build:"
free -m | sed 's/^/      /'

STEP "frontend: npm ci + next build (heap cap 1024M, 5min hard timeout)"
# - NODE_OPTIONS caps V8 heap so next build aborts itself on memory
#   pressure instead of hanging the whole box.
# - `timeout 300` is the brick wall — anything beyond 5min means
#   something is wrong, and we'd rather fail the deploy and keep prod
#   serving the old build than silently chew through swap.
# - `--no-audit --no-fund` shaves a few seconds off npm ci that we don't
#   need on a deploy machine.
if ! sudo -u clawmoku bash -lc "
  set -euo pipefail
  cd '$STAGE'
  npm ci --silent --no-audit --no-fund
  NODE_OPTIONS='--max-old-space-size=1024' timeout 300 npm run build
"; then
  echo "  !! build failed or timed out — leaving prod on its current .next" >&2
  STEP "memory snapshot at failure:"
  free -m | sed 's/^/      /'
  exit 1
fi

STEP "memory snapshot after build:"
free -m | sed 's/^/      /'

STEP "swap: atomic mv of node_modules/ and .next/ into prod web dir"
cd "$REMOTE_DIR/web"
[ -d node_modules ] && mv node_modules .node_modules.old
mv "$STAGE/node_modules" ./node_modules
[ -d .next ] && mv .next .next.old
mv "$STAGE/.next" ./.next
chown -R clawmoku:clawmoku node_modules .next
rm -rf "$STAGE" .next.old .node_modules.old

STEP "restart: clawmoku-api + clawmoku-web (only downtime, ~2s)"
systemctl restart clawmoku-api clawmoku-web
sleep 2
systemctl is-active clawmoku-api clawmoku-web
REMOTE_SH
}

smoke() {
  echo "==> [smoke] verify endpoints at $PUBLIC_URL"
  local fail=0
  if curl -fsS "$PUBLIC_URL/healthz" > /tmp/clawmoku-healthz.json; then
    echo "    healthz OK  $(cat /tmp/clawmoku-healthz.json)"
  else
    echo "    !! healthz FAILED"; fail=1
  fi
  # `skill.md` currently starts with `# Clawmoku · …` — accept YAML front
  # matter (`---`), HTML comments (`<!--`), or a leading markdown heading
  # (`# `) as "this is markdown, not an HTML redirect / error page".
  if curl -fsS -o /tmp/clawmoku-skill.md "$PUBLIC_URL/docs/skill" \
     && head -5 /tmp/clawmoku-skill.md | grep -qE '^(---|<!--|# )'; then
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
