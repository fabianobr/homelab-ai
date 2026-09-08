#!/usr/bin/env bash
# Head-to-head: mesma review (diff.patch) mandada pra sdlc-review-local
# (Colibrì). Disparado detached (nohup+disown) e não pelo mecanismo de
# background task do Claude Code, pela mesma razão do run7.sh: tasks
# gerenciadas pela sessão de chat morreram sistematicamente em segundos
# numa investigação anterior (ver docs/colibri-evidence/README.md).
set -uo pipefail
cd "$(dirname "$0")"

LOG="log_colibri.txt"
: > "$LOG"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)] $*" >> "$LOG"; }

log "=== head-to-head: sdlc-review-local, mesmo diff da review Claude ==="

set -a; . ../../../homelab.env; set +a

log "esperando endpoint direto..."
for _ in $(seq 1 120); do
  curl -s -o /dev/null -m 2 http://172.17.0.1:5000/v1/models -H "Authorization: Bearer $COLI_API_KEY" && break
  sleep 1
done

echo "request_start=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" > timeline_colibri.txt

curl -s -m 3000 -w '\n---METRICS---\nhttp_code=%{http_code}\ntime_total=%{time_total}\n' \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @req_colibri.json \
  -o response_colibri_raw.txt \
  2>>"$LOG"
log "curl saiu com código $?"

echo "request_end=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >> timeline_colibri.txt
log "resposta salva ($(wc -c < response_colibri_raw.txt 2>/dev/null || echo '?') bytes)"
log "=== concluído ==="
