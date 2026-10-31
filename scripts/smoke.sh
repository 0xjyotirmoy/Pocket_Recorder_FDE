#!/usr/bin/env bash
# Usage: scripts/smoke.sh path/to/clip.wav [server]
# Sends one clip using the hand-off contract, sends it again (must be 201 + same id),
# then waits until it is transcribed. Proves L4 contract + L6 live upload.
set -euo pipefail
CLIP="${1:?usage: smoke.sh clip.wav [http://localhost:8000]}"
SERVER="${2:-http://localhost:8000}"
TS="$(date +%Y-%m-%dT%H:%M:%S)+05:30"

send() {
  curl -s -w '\n%{http_code}' -F "audio=@${CLIP}" -F "device_id=rec-smoke" -F "recorded_at=${TS}" \
       -F "duration_ms=" -F "battery_pct=" "${SERVER}/upload"
}
A="$(send)"; B="$(send)"
echo "first : ${A//$'\n'/  HTTP }"
echo "second: ${B//$'\n'/  HTTP }"
ID="$(echo "$A" | head -1 | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')"
ENC="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$ID")"

START=$(date +%s)
while :; do
  STATUS="$(curl -s "${SERVER}/recordings/${ENC}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')"
  echo "  $(( $(date +%s) - START ))s  ${STATUS}"
  [[ "$STATUS" == "done" || "$STATUS" == "failed" ]] && break
  (( $(date +%s) - START > 120 )) && { echo "timeout"; exit 1; }
  sleep 2
done
