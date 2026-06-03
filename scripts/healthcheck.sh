#!/usr/bin/env bash
set -euo pipefail

echo "== homelab-ai healthcheck =="

check_url() {
  local name="$1"
  local url="$2"

  if curl -fsS --max-time 5 "$url" >/dev/null; then
    echo "[OK] $name -> $url"
  else
    echo "[FAIL] $name -> $url"
  fi
}

echo
echo "Docker:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || true

echo
echo "URLs:"
check_url "Open WebUI" "http://localhost:3000"
check_url "LM Studio models" "http://localhost:1234/v1/models"
check_url "ComfyUI" "http://localhost:8188"
check_url "n8n" "http://localhost:5678"

echo
echo "GPU:"
nvidia-smi || true

echo
echo "Tailscale:"
tailscale status || true
