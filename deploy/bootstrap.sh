#!/usr/bin/env bash
# Clawmoku — New server bootstrap (one-time first-deploy setup)
#
# Prerequisites on target server:
#   - Ubuntu 22.04+ with Python 3.10+, nginx installed
#   - Root SSH access
#
# Run from LOCAL machine:
#   GITHUB_REPO=https://github.com/lxyd-ai/clawmoku.git \
#   JWT_SECRET=<secret> \
#   PROD_HOST=8.217.39.83 \
#   PROD_PASSWORD=***REMOVED*** \
#   bash deploy/bootstrap.sh
#
# Or SSH to the server and run directly (set env vars inline).
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-https://github.com/lxyd-ai/clawmoku.git}"
REMOTE_DIR="${REMOTE_DIR:-/srv/clawmoku}"
DOMAIN_PRIMARY="${DOMAIN_PRIMARY:-gomoku.clawd.xin}"
DOMAIN_ALIAS="${DOMAIN_ALIAS:-gomoku.clawdchat.cn}"
API_PORT="${API_PORT:-9001}"
WEB_PORT="${WEB_PORT:-9002}"
CLAWDCHAT_URL="${CLAWDCHAT_URL:-https://clawdchat.cn}"
JWT_SECRET="${JWT_SECRET:-REPLACE_ME_WITH_32BYTES_HEX}"

# ── If running locally, SSH to remote ─────────────────────────────────────────
if [[ -n "${PROD_HOST:-}" ]]; then
  PROD_HOST="${PROD_HOST}"
  PROD_PASSWORD="${PROD_PASSWORD:-}"
  echo "==> Bootstrapping remote $PROD_HOST via SSH"
  SSHPASS_CMD=""
  if [[ -n "$PROD_PASSWORD" ]]; then
    SSHPASS_CMD="sshpass -p '$PROD_PASSWORD'"
  fi
  eval "$SSHPASS_CMD ssh -o StrictHostKeyChecking=no root@$PROD_HOST" \
    "GITHUB_REPO='$GITHUB_REPO' REMOTE_DIR='$REMOTE_DIR' \
     DOMAIN_PRIMARY='$DOMAIN_PRIMARY' DOMAIN_ALIAS='$DOMAIN_ALIAS' \
     API_PORT='$API_PORT' WEB_PORT='$WEB_PORT' \
     CLAWDCHAT_URL='$CLAWDCHAT_URL' JWT_SECRET='$JWT_SECRET' \
     bash -s" < "${BASH_SOURCE[0]}"
  echo "==> Remote bootstrap complete."
  exit 0
fi

# ── Running on the server itself below ────────────────────────────────────────
echo "==> [1/9] Install system packages (Node.js 20, sqlite3, certbot)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Node.js 20 via NodeSource
if ! command -v node >/dev/null 2>&1 || [[ "$(node -e 'process.stdout.write(process.version.split(".")[0].slice(1))')" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
apt-get install -y -qq sqlite3 certbot python3-certbot-nginx python3-venv git 2>/dev/null || true
node --version && npm --version

echo "==> [2/9] Create clawmoku system user"
if ! id clawmoku &>/dev/null; then
  useradd -r -s /bin/bash -d "$REMOTE_DIR" clawmoku
fi

echo "==> [3/9] Clone repository"
if [[ -d "$REMOTE_DIR/.git" ]]; then
  echo "    repo already exists, pulling latest"
  git -C "$REMOTE_DIR" pull --ff-only
else
  mkdir -p "$(dirname $REMOTE_DIR)"
  git clone "$GITHUB_REPO" "$REMOTE_DIR"
fi

echo "==> [4/9] Create data / backups / log directories"
mkdir -p "$REMOTE_DIR/data" "$REMOTE_DIR/backups" /var/log/clawmoku
chown -R clawmoku:clawmoku "$REMOTE_DIR" /var/log/clawmoku

echo "==> [5/9] Python venv + install backend"
if [[ ! -d "$REMOTE_DIR/backend/.venv" ]]; then
  python3 -m venv "$REMOTE_DIR/backend/.venv"
fi
sudo -u clawmoku "$REMOTE_DIR/backend/.venv/bin/pip" install -e "$REMOTE_DIR/backend" --quiet

echo "==> [6/9] Next.js frontend build"
cd "$REMOTE_DIR/web"
sudo -u clawmoku npm ci --silent
sudo -u clawmoku npm run build

echo "==> [7/9] systemd services + env drop-in"
# Copy service unit files
cp "$REMOTE_DIR/deploy/clawmoku-api.service" /etc/systemd/system/clawmoku-api.service
cp "$REMOTE_DIR/deploy/clawmoku-web.service" /etc/systemd/system/clawmoku-web.service

# Update public base URL in service file
sed -i "s|CLAWMOKU_PUBLIC_BASE_URL=.*|CLAWMOKU_PUBLIC_BASE_URL=https://$DOMAIN_PRIMARY|g" \
  /etc/systemd/system/clawmoku-api.service

# Env drop-in with secrets
mkdir -p /etc/systemd/system/clawmoku-api.service.d
cat > /etc/systemd/system/clawmoku-api.service.d/auth.conf <<EOF
[Service]
Environment=CLAWMOKU_JWT_SECRET=$JWT_SECRET
Environment=CLAWMOKU_CLAWDCHAT_URL=$CLAWDCHAT_URL
Environment=CLAWMOKU_SESSION_COOKIE_SECURE=true
Environment=CLAWMOKU_SESSION_COOKIE_SAMESITE=lax
EOF

systemctl daemon-reload
systemctl enable clawmoku-api clawmoku-web

echo "==> [8/9] nginx config"
NGINX_CONF="/etc/nginx/sites-available/clawmoku"
cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    server_name $DOMAIN_PRIMARY $DOMAIN_ALIAS;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN_PRIMARY $DOMAIN_ALIAS;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN_PRIMARY/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN_PRIMARY/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    access_log /var/log/nginx/clawmoku.access.log;
    error_log  /var/log/nginx/clawmoku.error.log;

    proxy_read_timeout 90s;
    proxy_send_timeout 90s;
    proxy_connect_timeout 10s;
    proxy_buffering off;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;

    location /api/ {
        proxy_pass http://127.0.0.1:$API_PORT/api/;
    }
    location = /skill.md    { proxy_pass http://127.0.0.1:$API_PORT/skill.md; }
    location = /protocol.md { proxy_pass http://127.0.0.1:$API_PORT/protocol.md; }
    location ~ ^/matches/[^/]+/claim(\.txt)?$ {
        proxy_pass http://127.0.0.1:$API_PORT\$request_uri;
    }
    location = /healthz     { proxy_pass http://127.0.0.1:$API_PORT/healthz; }
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
    }
}
NGINX

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/clawmoku

# Obtain TLS cert (DNS must already point to this server, or use --staging for test)
echo "==> Requesting Let's Encrypt cert for $DOMAIN_PRIMARY (and $DOMAIN_ALIAS if DNS ready)"
if [[ ! -f "/etc/letsencrypt/live/$DOMAIN_PRIMARY/fullchain.pem" ]]; then
  # Try to get cert; if DOMAIN_ALIAS DNS isn't switched yet, get only primary
  certbot certonly --nginx \
    -d "$DOMAIN_PRIMARY" \
    --non-interactive --agree-tos --register-unsafely-without-email \
    2>&1 || {
    echo "    !! certbot failed — DNS may not point here yet."
    echo "    Run manually after DNS switch: certbot --nginx -d $DOMAIN_PRIMARY -d $DOMAIN_ALIAS"
    # Create self-signed cert so nginx can start
    mkdir -p "/etc/letsencrypt/live/$DOMAIN_PRIMARY"
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout "/etc/letsencrypt/live/$DOMAIN_PRIMARY/privkey.pem" \
      -out    "/etc/letsencrypt/live/$DOMAIN_PRIMARY/fullchain.pem" \
      -subj   "/CN=$DOMAIN_PRIMARY" 2>/dev/null
    echo "    Temporary self-signed cert created for nginx to start."
  }
fi

nginx -t && systemctl reload nginx

echo "==> [9/9] Start services (DB must exist first — run migrate_db.sh to copy from old server)"
echo "    To manually start after DB migration:"
echo "      systemctl start clawmoku-api clawmoku-web"
echo ""
echo "==> Bootstrap complete on $(hostname). Next steps:"
echo "    1. Copy DB from old server:  bash deploy/migrate_db.sh"
echo "    2. Start services:           systemctl start clawmoku-api clawmoku-web"
echo "    3. Get real SSL cert:        certbot --nginx -d $DOMAIN_PRIMARY -d $DOMAIN_ALIAS"
echo "    4. Verify:                   curl https://$DOMAIN_PRIMARY/healthz"
