#!/usr/bin/env bash
# Wrapper that sources Hermes env vars (Telegram token) before running the agent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_ENV="$HOME/.hermes/.env"

if [ -f "$HERMES_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$HERMES_ENV"
    set +a
fi

exec "$SCRIPT_DIR/run.sh" "$@"
