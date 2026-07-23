#!/usr/bin/env bash
# Dispara o workflow via webhook do n8n. O n8n cuida do resto (Ollama,
# relatório, Telegram) de forma assíncrona — este script só confirma que o
# disparo foi aceito, não espera a execução terminar.
set -euo pipefail

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

HTTP_CODE=$(curl -s -o "$RESPONSE_FILE" -w '%{http_code}' -X POST http://localhost:5678/webhook/youtube-etl-run)

if [ "$HTTP_CODE" != "200" ]; then
  echo "Falha ao disparar o webhook do youtube-etl (HTTP $HTTP_CODE):" >&2
  cat "$RESPONSE_FILE" >&2
  exit 1
fi

echo "Webhook do youtube-etl disparado com sucesso (HTTP 200): $(cat "$RESPONSE_FILE")"
