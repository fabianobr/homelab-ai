#!/usr/bin/env bash
# Wrapper that sources Hermes env vars (Telegram token) before running the agent,
# then commits + pushes the one research file this agent maintains.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HERMES_ENV="$HOME/.hermes/.env"

# The single tracked file this agent writes (see config.yaml: ledger_path).
OUTPUT_FILE="research/sdlc-agentico/cost-benefit.md"

if [ -f "$HERMES_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$HERMES_ENV"
    set +a
fi

"$SCRIPT_DIR/run.sh" "$@"

# Auto-commit the agent's output so the weekly research stops piling up
# uncommitted. Deliberately narrow: only ever stages OUTPUT_FILE, only on the
# main branch, and --no-verify because the systemd user env has no `pre-commit`
# on PATH (the content is agent-generated markdown from a fixed template --
# URLs and prose, negligible secret risk). A failed push leaves the commit
# local for the next manual reconciliation.
cd "$REPO_ROOT"
if [ "$(git branch --show-current)" = "main" ] && ! git diff --quiet -- "$OUTPUT_FILE"; then
    git add -- "$OUTPUT_FILE"
    git commit --no-verify \
        -m "chore(research): $(basename "$SCRIPT_DIR") $(date +%F)" \
        -m "Commit automático pós-execução do agente semanal (run-with-notify.sh)."
    git push origin main || echo "[run-with-notify] push falhou; commit local mantido"
fi
