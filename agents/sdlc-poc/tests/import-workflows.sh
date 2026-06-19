#!/usr/bin/env bash
set -euo pipefail

N8N_URL="http://localhost:5678"
WORKFLOWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../workflows" && pwd)"

import_workflow() {
  local file="$1"
  local name
  name=$(python3 -c "import json,sys; print(json.load(open('$file'))['name'])")
  echo "Importing: $name"
  local resp
  resp=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "@$file" \
    "$N8N_URL/api/v1/workflows")
  local id
  id=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id', 'ERROR: ' + str(d.get('message','unknown'))))")
  echo "  -> Workflow ID: $id"
  echo "$id"
}

echo "=== Importing SDLC PoC workflows ==="
ID1=$(import_workflow "$WORKFLOWS_DIR/01-chat-discovery-to-spec.json")
ID2=$(import_workflow "$WORKFLOWS_DIR/02-spec-to-code.json")

echo ""
echo "=== Done ==="
echo "Workflow 1 (Chat) ID: $ID1"
echo "Workflow 2 (Code)  ID: $ID2"
echo ""
echo "Ative o Workflow 1 no n8n UI e acesse o chat em:"
echo "  http://localhost:5678/webhook/sdlc-poc-chat"
