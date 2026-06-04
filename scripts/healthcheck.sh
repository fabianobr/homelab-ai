#!/usr/bin/env bash
set -euo pipefail

echo "== homelab-ai healthcheck =="

FAIL_COUNT=0

record_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

check_url() {
  local name="$1"
  local url="$2"
  local label="${3:-FAIL}"

  if curl -fsS --max-time 5 "$url" >/dev/null; then
    echo "[OK] $name -> $url"
  else
    echo "[$label] $name -> $url"
    if [[ "$label" == "FAIL" ]]; then
      record_fail
    fi
  fi
}

echo
echo "Docker:"
if command -v docker >/dev/null 2>&1; then
  if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"; then
    :
  else
    echo "[FAIL] docker daemon may be down"
    record_fail
  fi

  if docker compose version >/dev/null 2>&1; then
    echo "[OK] docker compose"
  else
    echo "[FAIL] docker compose not available"
    record_fail
  fi
else
  echo "[FAIL] docker command not found"
  record_fail
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
  if cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate; then
    echo "[OK] cloudflared ingress config"
  else
    echo "[FAIL] cloudflared ingress config invalid"
    record_fail
  fi
else
  echo "[FAIL] cloudflared command not found"
  record_fail
fi

echo
echo "GPU:"
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi; then
    echo "[OK] nvidia-smi"
  else
    echo "[FAIL] nvidia-smi command failed; check NVIDIA driver and reboot if it was just installed"
    record_fail
  fi
else
  echo "[FAIL] nvidia-smi command not found"
  record_fail
fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo
  echo "Healthcheck failed with ${FAIL_COUNT} mandatory failure(s)."
  exit 1
fi

echo
echo "Healthcheck passed."
