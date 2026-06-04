#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo bash scripts/apply-system-config.sh" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Configurando Ollama Snap =="
snap set ollama host=0.0.0.0:11434
systemctl restart snap.ollama.listener.service

echo "== Configurando Cloudflare Tunnel =="
install -m 0644 "${PROJECT_ROOT}/infra/cloudflare/config.yml" /etc/cloudflared/config.yml
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
systemctl restart cloudflared

echo
echo "Configuracao de sistema aplicada."
echo "Valide com: bash scripts/healthcheck.sh"
