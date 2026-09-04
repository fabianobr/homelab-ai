#!/usr/bin/env bash
# Rodada 7: repetir o teste de max_tokens alto (4000, vs 200/900 das rodadas
# anteriores) mas disparado FORA de qualquer task gerenciada pelo Claude Code
# — as rodadas 3-6 morreram sistematicamente em segundos quando lançadas como
# tarefa em background da sessão de chat (ver README.md, seção "Rodadas que
# NÃO completaram"). Rode este script diretamente num terminal seu:
#
#   nohup docs/colibri-evidence/run7.sh > /dev/null 2>&1 &
#   disown
#
# ou simplesmente num terminal que você deixa aberto. NÃO peça para o Claude
# Code rodar isto em background — é exatamente o mecanismo suspeito.
#
# Tudo vai para um único log (log7.txt); a resposta crua e as métricas também
# ficam em arquivos separados, no padrão das rodadas anteriores. Quando
# terminar (ou você desistir de esperar), me aponte para log7.txt.
set -uo pipefail
cd "$(dirname "$0")"

LOCK="run7.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "run7.sh: já há uma execução em andamento (lock $LOCK existe). Abortando para não duplicar a requisição." >&2
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

LOG="log7.txt"
: > "$LOG"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)] $*" | tee -a "$LOG"; }

log "=== rodada 7: max_tokens=4000, execução fora do Claude Code ==="

log "RAM disponível: $(awk '/MemAvailable/{printf "%d GiB", $2/1048576}' /proc/meminfo)"
log "VRAM livre: $(nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>&1)"

SERVE=../../infra/scripts/colibri-serve.sh
STARTED_BY_US=0

log "checando colibri-serve..."
if "$SERVE" status >>"$LOG" 2>&1; then
  log "já estava rodando — não vou parar no final."
else
  log "parado; iniciando (isto carrega o modelo, ~40-60s antes do bind)..."
  if "$SERVE" start >>"$LOG" 2>&1; then
    STARTED_BY_US=1
    log "start ok."
  else
    log "FALHA no start — abortando rodada. Ver log acima (RAM insuficiente é a causa mais provável)."
    exit 1
  fi
fi

set -a; . ../../homelab.env; set +a

log "esperando o endpoint direto aceitar conexão..."
ok=0
for _ in $(seq 1 120); do
  if curl -s -o /dev/null -m 2 http://172.17.0.1:5000/v1/models -H "Authorization: Bearer $COLI_API_KEY"; then
    ok=1
    break
  fi
  sleep 1
done
[ "$ok" = 1 ] || log "AVISO: endpoint direto não respondeu em 120s; tentando mesmo assim pelo LiteLLM."

log "request_start (via LiteLLM, timeout local generoso: 3000s)"
echo "request_start=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" > timeline7.txt

curl -s -m 3000 -w '\n---METRICS---\nhttp_code=%{http_code}\ntime_total=%{time_total}\n' \
  -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @request7.json \
  -o response7_raw.txt \
  2>>"$LOG"
CURL_EXIT=$?

echo "request_end=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >> timeline7.txt
log "curl saiu com código $CURL_EXIT (0 = completou, 28 = timeout de 3000s estourado)"

# time_total do curl -w vai para stdout, não para -o: capturamos de novo,
# isolado, para não repetir o erro registrado no README (métrica perdida).
tail -c 200 response7_raw.txt | grep -q METRICS && \
  grep -A2 METRICS response7_raw.txt > metrics7.txt 2>/dev/null

log "resposta salva em response7_raw.txt ($(wc -c < response7_raw.txt 2>/dev/null || echo '?') bytes)"

if [ "$STARTED_BY_US" = 1 ]; then
  log "fomos nós que subimos o serviço — deixando no ar para inspeção manual."
  log "para derrubar depois: infra/scripts/colibri-serve.sh stop"
fi

log "=== rodada 7 concluída ==="
