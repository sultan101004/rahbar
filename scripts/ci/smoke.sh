#!/usr/bin/env bash
# Smoke test THROUGH THE INGRESS: the UI page loads, an answerable question is answered
# with a citation, and the must-abstain question is declined.
set -euo pipefail
BASE=${BASE:-http://localhost}
HOST=${HOST:-rahbar.local}
for _ in $(seq 1 30); do curl -sf -H "Host: $HOST" "$BASE/" >/dev/null && break; sleep 2; done
curl -sf -H "Host: $HOST" "$BASE/" | grep -qi "rahbar"
ask() { curl -sf -H "Host: $HOST" -H 'Content-Type: application/json' -X POST "$BASE/api/ask" -d "{\"question\": \"$1\"}"; }
ok=$(ask "When is a student placed on academic warning?")
echo "$ok"
echo "$ok" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["answered_from_context"] and r["citations"], r'
no=$(ask "How do I apply for a hostel room?")
echo "$no"
echo "$no" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert not r["answered_from_context"], r'
echo "smoke test passed"
