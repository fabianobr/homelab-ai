#!/usr/bin/env bash
# ATENÇÃO: este script rodou DUAS vezes na sessão original com request3.json
# (max_tokens=2000) — a 1ª vez com o timeout do LiteLLM recém-bumped pra 4800s
# e o container reiniciado; a 2ª vez sem reiniciar o container. Como as duas
# escrevem em timeline3.txt/response3_raw.txt, a 1ª rodada foi sobrescrita
# pela 2ª e seu timestamp de início é irrecuperável — só sobrou o teto
# observado na conversa. Ver docs/colibri-evidence/kill-timestamps.md.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . /home/fabiano/homelab-ai/homelab.env; set +a

for _ in $(seq 1 120); do
  curl -s -o /dev/null -m 2 http://172.17.0.1:5000/v1/models -H "Authorization: Bearer $COLI_API_KEY" && break
  sleep 1
done

echo "request_start=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" > timeline3.txt

curl -s -w '\n---METRICS---\nhttp_code=%{http_code}\ntime_total=%{time_total}\n' \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @request3.json \
  -o response3_raw.txt

echo "request_end=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >> timeline3.txt
echo DONE_MARKER
