#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="${DISK_GUARDIAN_CONFIG:-$SCRIPT_DIR/config.yaml}"
exec "$SCRIPT_DIR/run.sh" --config "$CONFIG_PATH" diagnose --notify
