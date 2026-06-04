#!/usr/bin/env bash
set -euo pipefail

echo "== homelab-ai healthcheck =="

check_url() {
  local name="$1"
  local url="$2"
  local label="${3:-FAIL}"

  if curl -fsS --max-time 5 "$url" >/dev/null; then
    echo "[OK] $name -> $url"
  else
    echo "[$label] $name -> $url"
  fi
}

echo
echo "Docker:"
if command -v docker >/dev/null 2>&1; then
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || true
else
  echo "[FAIL] docker command not found"
fi

if docker compose version >/dev/null 2>&1; then
  echo "[OK] docker compose"
else
  echo "[FAIL] docker compose not available"
fi

echo
echo "URLs:"
check_url "Open WebUI" "http://localhost:3000"
check_url "LM Studio models" "http://localhost:1234/v1/models"
check_url "ComfyUI" "http://localhost:8188"
check_url "n8n" "http://localhost:5678" "SKIP optional"

echo
echo "Cloudflare:"
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate || true
else
  echo "[FAIL] cloudflared command not found"
fi

echo
echo "GPU:"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi || true
else
  echo "[FAIL] nvidia-smi command not found"
fi

echo
echo "Tailscale:"
if command -v tailscale >/dev/null 2>&1; then
  tailscale status || true
else
  echo "[FAIL] tailscale command not found"
fi
