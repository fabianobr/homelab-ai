#!/usr/bin/env bash
set -euo pipefail

echo "== Atualizando homelab-ai =="

cd "$(dirname "$0")/../docker"

docker compose pull open-webui
docker compose up -d open-webui

echo "== Atualização concluída =="
