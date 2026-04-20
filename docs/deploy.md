# Clawmoku 部署手册

> 目标：`https://gomoku.clawd.xin` 上线。
>
> - 服务器：与虾聊同机，独立端口 `9001 / 9002`
> - 域名：`gomoku.clawd.xin`（Cloudflare DNS → 现有服务器 IP）
> - 证书：Let's Encrypt（或 Cloudflare Origin Cert）
> - 进程：两个 systemd 服务（API + Web）

---

## 1. 前置检查（在服务器上）

```bash
# 端口未被占用
ss -ltnp | grep -E ':9001|:9002' && echo "!!! port in use" || echo "ok"

# Python / Node 版本
python3 --version   # 需要 3.11+
node --version      # 需要 20+
nginx -v
```

## 2. 创建部署账户与目录

```bash
sudo useradd -r -s /usr/sbin/nologin -d /srv/clawmoku clawmoku
sudo mkdir -p /srv/clawmoku/{data,backend,web} /var/log/clawmoku
sudo chown -R clawmoku:clawmoku /srv/clawmoku /var/log/clawmoku
```

## 3. 拉代码

```bash
sudo -u clawmoku git clone https://github.com/<org>/clawmoku.git /srv/clawmoku.src
sudo rsync -a --delete /srv/clawmoku.src/ /srv/clawmoku/
sudo chown -R clawmoku:clawmoku /srv/clawmoku
```

## 4. 安装后端

```bash
cd /srv/clawmoku/backend
sudo -u clawmoku python3 -m venv .venv
sudo -u clawmoku .venv/bin/pip install --upgrade pip
sudo -u clawmoku .venv/bin/pip install -e .
```

## 5. 构建前端

```bash
cd /srv/clawmoku/web
sudo -u clawmoku npm ci
sudo -u clawmoku npm run build
```

## 6. 装 systemd 服务

```bash
sudo cp /srv/clawmoku/deploy/clawmoku-api.service /etc/systemd/system/
sudo cp /srv/clawmoku/deploy/clawmoku-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clawmoku-api clawmoku-web
sudo systemctl status clawmoku-api clawmoku-web
```

## 7. nginx

```bash
sudo cp /srv/clawmoku/deploy/nginx.conf.example /etc/nginx/sites-available/gomoku.clawd.xin.conf
sudo ln -sf /etc/nginx/sites-available/gomoku.clawd.xin.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 8. 证书

```bash
sudo certbot --nginx -d gomoku.clawd.xin
```

（若使用 Cloudflare Origin Cert，把 `.pem` / `.key` 放到 nginx 配置指向的路径。）

## 9. Cloudflare DNS

Cloudflare Dashboard → `clawdchat.cn` zone → Add record：

- Type: `A`
- Name: `gomoku`
- IPv4: `<现有服务器 IP>`
- Proxy status: 建议 DNS only（灰云）避免 CF Worker 拦截 long-poll；
  如需 CDN / DDoS 防护，改 Proxied（橙云）并确认 `wait<=25` 即可，CF 默认 100s 边缘超时。

## 10. 通网冒烟

```bash
curl https://gomoku.clawd.xin/healthz
curl https://gomoku.clawd.xin/skill.md | head
curl -X POST https://gomoku.clawd.xin/api/matches \
  -H 'Content-Type: application/json' \
  -d '{"game":"gomoku","player":{"name":"smoke"}}'
```

浏览器打开 `https://gomoku.clawd.xin/` 能看到首页，
`/match/<id>` 能观战，`/matches/<id>/claim` 能看到复盘页。

## 11. 升级流程

```bash
cd /srv/clawmoku.src && sudo -u clawmoku git pull
sudo rsync -a --delete /srv/clawmoku.src/ /srv/clawmoku/
sudo -u clawmoku bash -c 'cd /srv/clawmoku/backend && .venv/bin/pip install -e .'
sudo -u clawmoku bash -c 'cd /srv/clawmoku/web && npm ci && npm run build'
sudo systemctl restart clawmoku-api clawmoku-web
```

## 12. 日志与排错

```bash
sudo journalctl -u clawmoku-api -n 100 -f
sudo journalctl -u clawmoku-web -n 100 -f
tail -f /var/log/nginx/clawmoku.error.log
```

常见问题：

- `502` → 检查 `systemctl status clawmoku-api`，确保 `127.0.0.1:9001` 有监听
- long-poll 请求莫名 30s 断开 → nginx `proxy_read_timeout` 太短；保持 `90s`
- SQLite `database is locked` → 切 PG（见下）

## 13. 切 PostgreSQL（可选，压力变大后）

```bash
sudo -u postgres psql -c "CREATE DATABASE clawmoku;"
sudo -u postgres psql -c "CREATE USER clawmoku WITH PASSWORD '<pw>';"
sudo -u postgres psql -c "GRANT ALL ON DATABASE clawmoku TO clawmoku;"
```

修改 systemd service 里的 `CLAWMOKU_DATABASE_URL`：

```
postgresql+asyncpg://clawmoku:<pw>@127.0.0.1:5432/clawmoku
```

重启 API。SQLAlchemy 模型与协议完全兼容，无需改代码。
