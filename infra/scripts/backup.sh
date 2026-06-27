#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="$(dirname "$0")/../backups"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

echo "== Backup simples do projeto =="

tar -czf "$BACKUP_DIR/homelab-ai-$STAMP.tar.gz"   --exclude="./backups"   -C "$(dirname "$0")/.." .

echo "Backup criado em: $BACKUP_DIR/homelab-ai-$STAMP.tar.gz"
