#!/usr/bin/env bash
# Importa e ativa todos os workflows SDLC PoC no n8n.
# Usa publish:workflow (substituição do deprecated update:workflow --active=true).
#
# Uso: ./import-workflows.sh
set -euo pipefail

WORKFLOWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../workflows" && pwd)"

import_workflow() {
  local file="$1"
  local workflow_id="$2"

  [ -f "$file" ] || { echo "  Pulando $file (não encontrado)"; return; }

  local filename
  filename=$(basename "$file")
  echo "  Importando $filename..."
  docker cp "$file" "n8n:/tmp/$filename"
  docker exec n8n n8n import:workflow --input="/tmp/$filename"
  docker exec n8n n8n publish:workflow --id="$workflow_id"
}

echo "=== Importando workflows SDLC PoC ==="
import_workflow "$WORKFLOWS_DIR/01-chat-discovery-to-spec.json" "sdlc-poc-wf01"
import_workflow "$WORKFLOWS_DIR/02-spec-to-code.json"           "sdlc-poc-wf02"
import_workflow "$WORKFLOWS_DIR/03-spec-to-file.json"           "sdlc-poc-wf03"
import_workflow "$WORKFLOWS_DIR/04-fix-from-tests.json"         "sdlc-poc-wf04"

echo ""
echo "=== Reiniciando n8n ==="
docker restart n8n
sleep 5
echo ""
echo "=== Workflows ativos ==="
docker logs n8n --tail 10 2>&1 | grep -i "activated workflow" || echo "(nenhuma linha de ativação ainda — aguarde alguns segundos)"
echo ""
echo "Endpoints disponíveis:"
echo "  POST http://localhost:5678/webhook/sdlc-poc-chat          (WF1 — Discovery)"
echo "  POST http://localhost:5678/webhook/sdlc-poc-spec-to-code  (WF2 — One-shot)"
echo "  POST http://localhost:5678/webhook/sdlc-poc-spec-to-file  (WF3 — Por arquivo)"
echo "  POST http://localhost:5678/webhook/sdlc-poc-fix           (WF4 — Auto-fix)"
