#!/usr/bin/env bash
# Importa e publica o workflow YouTube ETL no n8n.
# Usa publish:workflow (substituição do deprecated update:workflow --active=true).
#
# Uso: ./import-workflow.sh
set -euo pipefail

WORKFLOWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/workflows" && pwd)"
FILE="$WORKFLOWS_DIR/01-youtube-etl.json"
WORKFLOW_ID="youtube-etl-wf01"

[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE"; exit 1; }

echo "=== Importando $(basename "$FILE") ==="
docker cp "$FILE" "n8n:/tmp/01-youtube-etl.json"
docker exec n8n n8n import:workflow --input="/tmp/01-youtube-etl.json"
docker exec n8n n8n publish:workflow --id="$WORKFLOW_ID"

echo ""
echo "=== Reiniciando n8n ==="
docker restart n8n
sleep 5

echo ""
echo "=== Workflows ativos ==="
docker logs n8n --tail 10 2>&1 | grep -i "activated workflow" || echo "(nenhuma linha de ativação ainda — aguarde alguns segundos)"

echo ""
echo "Agendamento: toda segunda-feira às 08:00 (TZ do container) via Schedule Trigger."
echo "Antes do primeiro run: preencha os channelIds no nó 'Config Canais' (UI do n8n)"
echo "e as variáveis YOUTUBE_API_KEY / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
echo "no .env do compose (ver README.md)."
