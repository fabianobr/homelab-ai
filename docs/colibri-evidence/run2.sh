#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a; . /home/fabiano/homelab-ai/homelab.env; set +a

for _ in $(seq 1 120); do
  curl -s -o /dev/null -m 2 http://172.17.0.1:5000/v1/models -H "Authorization: Bearer $COLI_API_KEY" && break
  sleep 1
done

echo "request_start=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" > timeline2.txt

curl -s -w '\n---METRICS---\nhttp_code=%{http_code}\ntime_total=%{time_total}\n' \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @request2.json \
  -o response2_raw.txt

echo "request_end=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >> timeline2.txt
echo DONE_MARKER
