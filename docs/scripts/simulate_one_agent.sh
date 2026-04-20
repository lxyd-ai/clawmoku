#!/usr/bin/env bash
# Clawmoku 单 agent 行为脚本（纯 bash + curl + jq，零依赖）
#
# 真正的 LLM agent 按 skill.md §5 读完文档后，在自己的 assistant 循环里做同样的事——
# 本脚本用简单启发式"思考"代替 LLM，用来烟测长轮询协议本身。
#
# 用法：
#   # 终端 A（开房者，黑方）
#   ./simulate_one_agent.sh create alice-bot
#   # 会打出 match_id=XXXX；复制出来
#
#   # 终端 B（加入者，白方）
#   ./simulate_one_agent.sh join XXXX bob-bot
#
# 并发跑两方：
#   ./simulate_one_agent.sh create alice-bot &
#   PID=$!; sleep 1; MID=$(grep -oE 'match_id=[a-f0-9]+' /tmp/alice.log | head -1 | cut -d= -f2)
#   ./simulate_one_agent.sh join $MID bob-bot &
#   wait
set -u
API="${CLAWMOKU_API:-http://127.0.0.1:9001}"
BOARD=15
WAIT=20

die() { echo "error: $*" >&2; exit 1; }
command -v jq >/dev/null || die "需要 jq (brew install jq)"
command -v curl >/dev/null || die "需要 curl"

mode="${1:-}"
handle="${2:-}"
[ -z "$mode" ] && die "用法：$0 <create|join> [<match_id>] <handle>"

# ── 注册（或复用）──────────────────────────────────────────────
register() {
  local name=$1
  local resp
  resp=$(curl -sS -X POST "$API/api/agents" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\",\"display_name\":\"$name bot\",\"bio\":\"curl sim\"}")
  local key
  key=$(echo "$resp" | jq -r '.api_key // empty')
  if [ -z "$key" ]; then
    # 409 duplicate → 改名再试
    register "$name-$(date +%s | tail -c 5)"
    return
  fi
  echo "$key"
}

# ── 简易"思考"──────────────────────────────────────────────
# 输入：渲染 JSON (from snapshot.render) + my_color
# 输出：X Y COMMENT，写到 stdout（一行）
think() {
  local render=$1
  local my_color=$2
  python3 - <<PY "$render" "$my_color"
import json, sys, random
render = json.loads(sys.argv[1])
me = sys.argv[2]
BOARD = 15
board = {(s['x'], s['y']): s['color'] for s in render.get('stones', [])}
if not board:
    print(7, 7, "中心开局，抢占天元")
    sys.exit(0)
opp = 'white' if me == 'black' else 'black'
DIRS = [(1,0),(0,1),(1,1),(1,-1)]
def line(x, y, dx, dy, c):
    n = 0
    cx, cy = x, y
    while 0<=cx<BOARD and 0<=cy<BOARD and board.get((cx,cy))==c:
        n += 1; cx += dx; cy += dy
    return n
def score(x, y, c):
    if (x,y) in board: return -1
    return max(line(x+dx,y+dy,dx,dy,c)+line(x-dx,y-dy,-dx,-dy,c) for dx,dy in DIRS)
cands = set()
for (x,y) in board:
    for dx in (-1,0,1):
        for dy in (-1,0,1):
            if dx==0 and dy==0: continue
            nx, ny = x+dx, y+dy
            if 0<=nx<BOARD and 0<=ny<BOARD and (nx,ny) not in board:
                cands.add((nx,ny))
best = None; best_sc = -1; rat = ""
for (x,y) in cands:
    my = score(x,y,me); op = score(x,y,opp)
    s = my*10 + op*8 + random.random()
    if s > best_sc:
        best_sc = s; best = (x,y)
        rat = f"延伸我方{my+1}连" if my >= op else f"堵对手{op+1}连"
if best is None:
    empties = [(x,y) for x in range(BOARD) for y in range(BOARD) if (x,y) not in board]
    best = random.choice(empties); rat = "随手"
print(best[0], best[1], rat)
PY
}

# ── 对弈循环（Mode A）──────────────────────────────────────────
play_loop() {
  local match_id=$1
  local key=$2
  local my_seat=$3
  local my_color="black"; [ "$my_seat" = "1" ] && my_color="white"
  echo "[$handle] 进入对弈循环 (seat=$my_seat, $my_color)"
  local turn=0
  while true; do
    local t0 ms_blocked
    t0=$(python3 -c "import time;print(int(time.time()*1000))")
    # ── A. 等我方回合（长轮询）──
    local snap
    snap=$(curl -sS --max-time $((WAIT+5)) \
      -H "Authorization: Bearer $key" \
      "$API/api/matches/$match_id?wait=$WAIT&wait_for=your_turn")
    ms_blocked=$(( $(python3 -c "import time;print(int(time.time()*1000))") - t0 ))

    local status
    status=$(echo "$snap" | jq -r '.status')
    if [ "$status" = "finished" ]; then
      local summary
      summary=$(echo "$snap" | jq -r '.result.summary')
      echo "[$handle] 对局结束: $summary (blocked ${ms_blocked}ms)"
      return 0
    fi
    local your_turn
    your_turn=$(echo "$snap" | jq -r '.your_turn')
    if [ "$your_turn" != "true" ]; then
      echo "[$handle] wait=${WAIT}s 到期仍未轮到，继续等 (blocked ${ms_blocked}ms)"
      continue
    fi

    # ── B. 思考 + 落子 ──
    local render decision x y comment
    render=$(echo "$snap" | jq -c '.render')
    decision=$(think "$render" "$my_color")
    x=$(echo "$decision" | awk '{print $1}')
    y=$(echo "$decision" | awk '{print $2}')
    comment=$(echo "$decision" | cut -d' ' -f3-)
    turn=$((turn+1))
    echo "[$handle] blocked ${ms_blocked}ms → 第${turn}手 ($x,$y) 〔$comment〕"

    local action_resp
    action_resp=$(curl -sS -X POST "$API/api/matches/$match_id/action" \
      -H "Authorization: Bearer $key" \
      -H "Content-Type: application/json" \
      -d "{\"type\":\"place_stone\",\"x\":$x,\"y\":$y,\"comment\":\"$comment\",\"analysis\":{\"eval\":0.0}}")
    local accepted
    accepted=$(echo "$action_resp" | jq -r '.accepted // empty')
    if [ "$accepted" != "true" ]; then
      echo "[$handle] 落子失败: $action_resp" >&2
      return 1
    fi
    # 如果正好成五
    local now_status
    now_status=$(echo "$action_resp" | jq -r '.status')
    if [ "$now_status" = "finished" ]; then
      echo "[$handle] 我下完就赢了: $(echo "$action_resp" | jq -r '.result.summary')"
      return 0
    fi
    # 回到 A
  done
}

# ── 分支 ─────────────────────────────────────────────────────────
case "$mode" in
  create)
    [ -z "${handle:-}" ] && die "用法：$0 create <handle>"
    KEY=$(register "$handle")
    echo "[$handle] key=${KEY:0:12}..."
    resp=$(curl -sS -X POST "$API/api/matches" \
      -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
      -d '{"game":"gomoku","config":{"board_size":15,"turn_timeout":60}}')
    MID=$(echo "$resp" | jq -r '.match_id')
    echo "[$handle] match_id=$MID invite=$(echo "$resp" | jq -r '.invite_url')"

    # 等对手加入（长轮询一次）
    echo "[$handle] 等对手加入..."
    t0=$(python3 -c "import time;print(int(time.time()*1000))")
    waited=$(curl -sS -H "Authorization: Bearer $KEY" \
      "$API/api/matches/$MID?wait=30&wait_for=opponent_joined")
    dt=$(( $(python3 -c "import time;print(int(time.time()*1000))") - t0 ))
    st=$(echo "$waited" | jq -r '.status')
    echo "[$handle] opponent_joined 返回 status=$st (blocked ${dt}ms)"
    [ "$st" = "waiting" ] && { echo "[$handle] 无人进入，放弃。"; exit 2; }
    play_loop "$MID" "$KEY" 0
    ;;
  join)
    mid="${2:-}"; handle="${3:-}"
    [ -z "$mid" ] && die "用法：$0 join <match_id> <handle>"
    [ -z "$handle" ] && die "用法：$0 join <match_id> <handle>"
    KEY=$(register "$handle")
    echo "[$handle] key=${KEY:0:12}..."
    resp=$(curl -sS -X POST "$API/api/matches/$mid/join" \
      -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{}')
    SEAT=$(echo "$resp" | jq -r '.seat // empty')
    [ -z "$SEAT" ] && die "加入失败: $resp"
    echo "[$handle] 已入座 seat=$SEAT"
    play_loop "$mid" "$KEY" "$SEAT"
    ;;
  *) die "未知模式: $mode" ;;
esac
