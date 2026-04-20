#!/usr/bin/env bash
# End-to-end smoke test: two curl-based "agents" play a complete gomoku game.
# Usage:   bash scripts/demo_two_agents.sh [BASE_URL]
# Default: http://127.0.0.1:9001
set -euo pipefail

BASE=${1:-${CLAWMOKU_BASE:-http://127.0.0.1:9001}}

json() { python3 -c "import json,sys;print(json.load(sys.stdin)$1)"; }

echo "→ Creating match on $BASE"
A_RESP=$(curl -s -X POST "$BASE/api/matches" \
  -H 'Content-Type: application/json' \
  -d '{"game":"gomoku","config":{"turn_timeout":30},"player":{"name":"demo-alice","display_name":"Alice"}}')
MATCH_ID=$(echo "$A_RESP" | json "['match_id']")
TOKEN_A=$(echo "$A_RESP" | json "['play_token']")
echo "   match_id=$MATCH_ID  seat=0  token=$TOKEN_A"
echo "   invite: $BASE/match/$MATCH_ID   (or https-front)"

echo "→ Bob joins"
B_RESP=$(curl -s -X POST "$BASE/api/matches/$MATCH_ID/join" \
  -H 'Content-Type: application/json' \
  -d '{"player":{"name":"demo-bob","display_name":"Bob"}}')
TOKEN_B=$(echo "$B_RESP" | json "['play_token']")
echo "   seat=1  token=$TOKEN_B"

place() {
  local seat="$1" token="$2" x="$3" y="$4"
  resp=$(curl -s -X POST "$BASE/api/matches/$MATCH_ID/action" \
    -H 'Content-Type: application/json' \
    -H "X-Play-Token: $token" \
    -d "{\"type\":\"place_stone\",\"x\":$x,\"y\":$y}")
  status=$(echo "$resp" | json "['status']")
  echo "   seat=$seat ($x,$y) → status=$status"
  if [ "$status" = "finished" ]; then
    echo "$resp" | python3 -m json.tool
    exit 0
  fi
}

# Black plays five-in-a-row at y=7; white plays a dead column.
BLACK_MOVES=("3 7" "4 7" "5 7" "6 7" "7 7")
WHITE_MOVES=("0 0" "0 1" "0 2" "0 3")

i=0
for m in "${BLACK_MOVES[@]}"; do
  read -r bx by <<<"$m"
  place 0 "$TOKEN_A" "$bx" "$by"
  if [ $i -lt ${#WHITE_MOVES[@]} ]; then
    read -r wx wy <<<"${WHITE_MOVES[$i]}"
    place 1 "$TOKEN_B" "$wx" "$wy"
  fi
  i=$((i+1))
done

echo "✗ Game did not finish as expected"
exit 1
