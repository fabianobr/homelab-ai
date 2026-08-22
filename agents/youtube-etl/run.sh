#!/usr/bin/env bash
# Valida as dependências efetivas do container e aguarda o workflow n8n
# terminar. Assim, o exit code do systemd representa o resultado do ETL, não
# apenas a aceitação inicial do webhook.
set -euo pipefail

readonly N8N_CONTAINER="${N8N_CONTAINER:-n8n}"
readonly WEBHOOK_URL="${YOUTUBE_ETL_WEBHOOK_URL:-http://localhost:5678/webhook/youtube-etl-run}"
readonly WORKFLOW_TIMEOUT_SECONDS="${YOUTUBE_ETL_TIMEOUT_SECONDS:-14400}"
readonly PREFLIGHT_ONLY="${YOUTUBE_ETL_PREFLIGHT_ONLY:-false}"

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

fail() {
  echo "youtube-etl: $*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl não encontrado no host"
command -v docker >/dev/null 2>&1 || fail "docker não encontrado no host"

if [ "$(docker inspect --format '{{.State.Running}}' "$N8N_CONTAINER" 2>/dev/null || true)" != "true" ]; then
  fail "container $N8N_CONTAINER não está em execução"
fi

# O teste ocorre dentro do container para detectar exatamente o incidente em
# que o .env/Compose estava correto, mas o container antigo conservava valores
# vazios. Nenhum valor de credencial é impresso.
docker exec "$N8N_CONTAINER" sh -eu -c '
  missing=""
  [ -n "${YOUTUBE_API_KEY:-}" ] || missing="$missing YOUTUBE_API_KEY"
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || missing="$missing TELEGRAM_BOT_TOKEN"
  [ -n "${TELEGRAM_CHAT_ID:-}" ] || missing="$missing TELEGRAM_CHAT_ID"
  [ -z "$missing" ] || {
    echo "credenciais ausentes no ambiente efetivo do container:$missing" >&2
    exit 20
  }

  command -v yt-dlp >/dev/null 2>&1 || {
    echo "yt-dlp não encontrado no container" >&2
    exit 21
  }
  [ -w /data/youtube-etl/reports ] || {
    echo "/data/youtube-etl/reports não existe ou não é gravável" >&2
    exit 22
  }
  wget -q --spider http://127.0.0.1:5678/healthz || wget -q --spider http://127.0.0.1:5678/ || {
    echo "serviço HTTP do n8n não respondeu" >&2
    exit 23
  }
  tags="$(wget -qO- http://ollama:11434/api/tags)" || {
    echo "API do Ollama não respondeu a partir do n8n" >&2
    exit 24
  }
  printf "%s" "$tags" | grep -Eq "llama3[.]2(:[^\"]*)?\"" || {
    echo "modelo llama3.2 não está instalado no Ollama" >&2
    exit 25
  }
'

if [ "$PREFLIGHT_ONLY" = "true" ]; then
  echo "youtube-etl: preflight concluído (webhook não disparado)"
  exit 0
fi

echo "youtube-etl: preflight concluído; aguardando o workflow terminar"

set +e
HTTP_CODE=$(curl \
  --silent \
  --show-error \
  --output "$RESPONSE_FILE" \
  --write-out '%{http_code}' \
  --request POST \
  --connect-timeout 10 \
  --max-time "$WORKFLOW_TIMEOUT_SECONDS" \
  "$WEBHOOK_URL")
CURL_STATUS=$?
set -e

if [ "$CURL_STATUS" -ne 0 ]; then
  fail "falha de transporte ou timeout aguardando o workflow (curl exit $CURL_STATUS)"
fi

if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
  # Não imprime o corpo: mensagens internas do n8n podem conter URLs com
  # credenciais. O diagnóstico detalhado permanece na aba Executions/logs.
  fail "workflow terminou com HTTP $HTTP_CODE (consulte Executions no n8n)"
fi

echo "youtube-etl: workflow concluído com sucesso (HTTP $HTTP_CODE)"
