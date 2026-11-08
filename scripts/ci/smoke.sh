#!/usr/bin/env bash
# Smoke test THROUGH THE INGRESS: the UI page loads, an answerable question is answered
# with a citation, and the must-abstain question is declined. Prints status and body of
# every request so a failure says what failed.
set -uo pipefail
BASE=${BASE:-http://localhost}
HOST=${HOST:-rahbar.local}
code=000
for _ in $(seq 1 45); do
  code=$(curl -s -o /tmp/ui.html -w '%{http_code}' -H "Host: $HOST" "$BASE/")
  [ "$code" = 200 ] && break
  sleep 2
done
echo "GET / -> $code"; head -c 300 /tmp/ui.html; echo
[ "$code" = 200 ] && grep -qi rahbar /tmp/ui.html || { echo "UI not served through the Ingress"; exit 1; }

ask() {
  local out code
  out=$(mktemp)
  for _ in $(seq 1 30); do   # 503 = no Ready api endpoint yet: wait, do not fail at once
    code=$(curl -s -o "$out" -w '%{http_code}' -m 120 -H "Host: $HOST" -H 'Content-Type: application/json' \
      -X POST "$BASE/api/ask" -d "{\"question\": \"$1\"}")
    echo "POST /api/ask ($1) -> $code" >&2
    [ "$code" = 503 ] || break
    sleep 2
  done
  cat "$out"
  [ "$code" = 200 ]
}
ok=$(ask "When is a student placed on academic warning?") || { echo "$ok"; exit 1; }
echo "$ok"
echo "$ok" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["answered_from_context"] and r["citations"], r' || exit 1
no=$(ask "How do I apply for a hostel room?") || { echo "$no"; exit 1; }
echo "$no"
echo "$no" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert not r["answered_from_context"], r' || exit 1
echo "smoke test passed"
