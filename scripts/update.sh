#!/usr/bin/env bash
set -euo pipefail

echo "== Atualizando homelab-ai =="

cd "$(dirname "$0")/../docker"

docker compose pull
docker compose up -d

echo "== Atualização concluída =="
