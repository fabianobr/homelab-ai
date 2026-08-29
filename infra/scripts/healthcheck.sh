#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_ENV="${LOCAL_ENV:-/etc/homelab-ai/homelab.env}"
if [[ -f "${PROJECT_ROOT}/homelab.env" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/homelab.env"
elif [[ -f "${LOCAL_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${LOCAL_ENV}"
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
check_url "ComfyUI" "http://localhost:8188"
check_url "n8n" "http://localhost:5678" "SKIP optional"
if docker inspect deepseek-harness >/dev/null 2>&1; then
  check_url "DeepSeek Harness" "http://localhost:3081"
else
  echo "[SKIP optional] DeepSeek Harness container not found"
fi

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
else
  echo "[FAIL] open-webui container not found"
  record_fail
fi

echo
echo "Cloudflare:"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
COMFYUI_HOSTNAME="${COMFYUI_HOSTNAME:-media.example.com}"
N8N_HOSTNAME="${N8N_HOSTNAME:-flow.example.com}"
DSH_PUBLIC_HOSTNAME="${DSH_PUBLIC_HOSTNAME:-}"
DSH_CLOUDFLARE_ENABLED="${DSH_CLOUDFLARE_ENABLED:-false}"
if command -v cloudflared >/dev/null 2>&1; then
  if cloudflared tunnel --config "${CLOUDFLARED_CONFIG}" ingress validate; then
    echo "[OK] cloudflared ingress config"
  else
    echo "[FAIL] cloudflared ingress config invalid"
    record_fail
  fi

  missing_hostnames=()
  for hostname in "${COMFYUI_HOSTNAME}" "${N8N_HOSTNAME}"; do
    if ! grep -Fq -- "hostname: ${hostname}" "${CLOUDFLARED_CONFIG}"; then
      missing_hostnames+=("${hostname}")
    fi
  done

  if [[ ${#missing_hostnames[@]} -eq 0 ]]; then
    echo "[OK] cloudflared required hostnames (ComfyUI, n8n)"
  else
    echo "[FAIL] cloudflared required hostnames missing: ${missing_hostnames[*]}"
    record_fail
  fi

  echo "[SKIP disabled] Open WebUI Cloudflare hostname"

  if [[ "${DSH_CLOUDFLARE_ENABLED}" == "true" ]]; then
    if [[ -z "${DSH_PUBLIC_HOSTNAME}" ]]; then
      echo "[FAIL] DSH_CLOUDFLARE_ENABLED=true but DSH_PUBLIC_HOSTNAME is unset"
      record_fail
    elif grep -q "hostname: ${DSH_PUBLIC_HOSTNAME}" "${CLOUDFLARED_CONFIG}"; then
      echo "[OK] cloudflared DeepSeek Harness hostname"
    else
      echo "[FAIL] cloudflared DeepSeek Harness hostname missing"
      record_fail
    fi
  else
    echo "[SKIP pending Cloudflare] DeepSeek Harness hostname"
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
