#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="${LOCAL_ENV:-/etc/homelab-ai/homelab.env}"
if [[ -f "${LOCAL_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${LOCAL_ENV}"
elif [[ -f "${PROJECT_ROOT}/homelab.env" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/homelab.env"
fi

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
check_url "Ollama models" "http://localhost:11434/api/tags"
check_url "LM Studio models" "http://localhost:1234/v1/models" "SKIP optional"
check_url "ComfyUI" "http://localhost:8188"
check_url "n8n" "http://localhost:5678" "SKIP optional"

echo
echo "Ollama exposure:"
if systemctl is-active --quiet homelab-ai-ollama-firewall.service; then
  echo "[OK] Ollama firewall service active"
else
  echo "[FAIL] Ollama firewall service inactive"
  record_fail
fi

echo
echo "Container backends:"
if docker inspect open-webui >/dev/null 2>&1; then
  if docker exec open-webui python -c "import urllib.request; urllib.request.urlopen('http://ollama:11434/api/tags', timeout=5).read()" >/dev/null; then
    echo "[OK] Open WebUI -> Ollama"
  else
    echo "[FAIL] Open WebUI -> Ollama"
    record_fail
  fi

  echo "[SKIP optional] Open WebUI -> LM Studio"
else
  echo "[FAIL] open-webui container not found"
  record_fail
fi

echo
echo "Cloudflare:"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
OPEN_WEBUI_HOSTNAME="${OPEN_WEBUI_HOSTNAME:-ai.example.com}"
COMFYUI_HOSTNAME="${COMFYUI_HOSTNAME:-media.example.com}"
N8N_HOSTNAME="${N8N_HOSTNAME:-flow.example.com}"
if command -v cloudflared >/dev/null 2>&1; then
  if cloudflared tunnel --config "${CLOUDFLARED_CONFIG}" ingress validate; then
    echo "[OK] cloudflared ingress config"
  else
    echo "[FAIL] cloudflared ingress config invalid"
    record_fail
  fi

  if grep -q "hostname: ${OPEN_WEBUI_HOSTNAME}" "${CLOUDFLARED_CONFIG}" \
    && grep -q "hostname: ${COMFYUI_HOSTNAME}" "${CLOUDFLARED_CONFIG}" \
    && grep -q "hostname: ${N8N_HOSTNAME}" "${CLOUDFLARED_CONFIG}"; then
    echo "[OK] cloudflared required hostnames"
  else
    echo "[FAIL] cloudflared required hostnames missing"
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
