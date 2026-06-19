#!/usr/bin/env bash
set -euo pipefail

WORKFLOWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../workflows" && pwd)"
CONTAINER_WORKFLOWS_DIR="/tmp/n8n-workflows"

import_workflow() {
  local file="$1"

  # Guard: skip if file doesn't exist
  if [ ! -f "$file" ]; then
    echo "Skipping $file (not yet created)"
    return
  fi

  local name
  name=$(python3 -c "import json,sys; print(json.load(open('$file'))['name'])")
  echo "Importing: $name"

  # Copy workflow file to container
  local filename
  filename=$(basename "$file")
  docker cp "$file" "n8n:$CONTAINER_WORKFLOWS_DIR/$filename"

  # Import workflow using n8n CLI
  docker exec n8n n8n import:workflow --input="$CONTAINER_WORKFLOWS_DIR/$filename"
  echo "  -> Workflow imported successfully"
}

echo "=== Importing SDLC PoC workflows ==="

# Ensure temp directory exists in container
docker exec n8n mkdir -p "$CONTAINER_WORKFLOWS_DIR" 2>/dev/null || true

# Import workflow 1
import_workflow "$WORKFLOWS_DIR/01-chat-discovery-to-spec.json"

# Conditionally import workflow 2
import_workflow "$WORKFLOWS_DIR/02-spec-to-code.json"

echo ""
echo "=== Activating workflows ==="
docker exec n8n n8n update:workflow --active=true

echo ""
echo "=== Restarting n8n ==="
docker restart n8n

echo ""
echo "=== Done ==="
echo "Restart n8n with: docker restart n8n"
echo ""
echo "Ative o Workflow 1 no n8n UI e acesse o chat em:"
echo "  http://localhost:5678/webhook/sdlc-poc-chat"
