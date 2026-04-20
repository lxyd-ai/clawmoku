#!/usr/bin/env bash
# MVP 验收脚本：
# 1) 双 agent curl 对弈到胜负
# 2) 多观众 long-poll 同时收到事件
# 3) 超时判负
# 4) /claim 页能看
#
# 用法：先启动 backend on 127.0.0.1:9001，然后运行：
#   bash scripts/mvp_verify.sh
set -euo pipefail
BASE=${1:-http://127.0.0.1:9001}

log() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32mOK\033[0m  %s\n' "$*"; }
bad() { printf '\033[1;31mFAIL\033[0m %s\n' "$*"; exit 1; }

curl -sf "$BASE/healthz" >/dev/null || bad "backend not reachable at $BASE"

# ---------- 1) 双 agent 完整对弈 ----------
log "Case 1: two-agent full game"
A=$(curl -s -X POST "$BASE/api/matches" -H 'Content-Type: application/json' \
     -d '{"game":"gomoku","player":{"name":"mvp-a"}}')
MID=$(echo "$A" | python3 -c "import json,sys;print(json.load(sys.stdin)['match_id'])")
TA=$(echo "$A" | python3 -c "import json,sys;print(json.load(sys.stdin)['play_token'])")
B=$(curl -s -X POST "$BASE/api/matches/$MID/join" -H 'Content-Type: application/json' \
     -d '{"player":{"name":"mvp-b"}}')
TB=$(echo "$B" | python3 -c "import json,sys;print(json.load(sys.stdin)['play_token'])")

place() {
  curl -s -X POST "$BASE/api/matches/$MID/action" -H 'Content-Type: application/json' \
    -H "X-Play-Token: $1" -d "{\"type\":\"place_stone\",\"x\":$2,\"y\":$3}" >/dev/null
}
BM=("3 7" "4 7" "5 7" "6 7" "7 7"); WM=("0 0" "0 1" "0 2" "0 3")
i=0; for m in "${BM[@]}"; do read -r x y <<<"$m"; place "$TA" "$x" "$y"
  if [ $i -lt ${#WM[@]} ]; then read -r wx wy <<<"${WM[$i]}"; place "$TB" "$wx" "$wy"; fi
  i=$((i+1))
done
STATUS=$(curl -s "$BASE/api/matches/$MID" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "finished" ] || bad "expected finished, got $STATUS"
ok "game finished, match_id=$MID"

# ---------- 2) 多观众 long-poll 同时收事件 ----------
log "Case 2: multiple spectators receive same move via long-poll"
A2=$(curl -s -X POST "$BASE/api/matches" -H 'Content-Type: application/json' \
     -d '{"game":"gomoku","player":{"name":"spec-a"}}')
MID2=$(echo "$A2" | python3 -c "import json,sys;print(json.load(sys.stdin)['match_id'])")
TA2=$(echo "$A2" | python3 -c "import json,sys;print(json.load(sys.stdin)['play_token'])")
curl -s -X POST "$BASE/api/matches/$MID2/join" -H 'Content-Type: application/json' \
     -d '{"player":{"name":"spec-b"}}' >/dev/null

# Spectator baseline = current events_total
SINCE=$(curl -s "$BASE/api/matches/$MID2" | python3 -c "import json,sys;print(json.load(sys.stdin)['events_total'])")

# Two concurrent spectators waiting up to 10s
F1=$(mktemp); F2=$(mktemp)
( curl -s "$BASE/api/matches/$MID2/events?since=$SINCE&wait=10" > "$F1" ) &
( curl -s "$BASE/api/matches/$MID2/events?since=$SINCE&wait=10" > "$F2" ) &
sleep 0.5
# Place stone
curl -s -X POST "$BASE/api/matches/$MID2/action" -H 'Content-Type: application/json' \
  -H "X-Play-Token: $TA2" -d '{"type":"place_stone","x":7,"y":7}' >/dev/null
wait
for f in "$F1" "$F2"; do
  TYPES=$(python3 -c "import json;print([e['type'] for e in json.load(open('$f'))['events']])")
  echo "   spectator -> $TYPES"
  python3 -c "import json,sys;d=json.load(open('$f'));sys.exit(0 if any(e['type']=='stone_placed' for e in d['events']) else 1)" \
    || bad "spectator $f did not receive stone_placed"
done
ok "both spectators received stone_placed via long-poll"

# ---------- 3) 超时判负 ----------
log "Case 3: timeout forfeit (turn_timeout=2)"
A3=$(curl -s -X POST "$BASE/api/matches" -H 'Content-Type: application/json' \
     -d '{"game":"gomoku","config":{"turn_timeout":2},"player":{"name":"to-a"}}')
MID3=$(echo "$A3" | python3 -c "import json,sys;print(json.load(sys.stdin)['match_id'])")
curl -s -X POST "$BASE/api/matches/$MID3/join" -H 'Content-Type: application/json' \
     -d '{"player":{"name":"to-b"}}' >/dev/null
sleep 3
RES=$(curl -s "$BASE/api/matches/$MID3" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['status'],d['result']['reason'],d['result']['winner_seat'])")
echo "   $RES"
echo "$RES" | grep -q "finished timeout 1" || bad "expected finished timeout winner=1, got '$RES'"
ok "timeout forfeit works"

# ---------- 4) /claim 页 ----------
log "Case 4: /claim HTML"
CODE=$(curl -s -o /tmp/claim.html -w "%{http_code}" "$BASE/matches/$MID/claim")
[ "$CODE" = "200" ] || bad "/claim returned $CODE"
grep -q "Clawmoku" /tmp/claim.html || bad "/claim missing branding"
grep -q "$MID" /tmp/claim.html || bad "/claim missing match_id"
ok "claim page renders ($MID)"

echo
printf '\033[1;32mAll MVP criteria passed.\033[0m\n'
