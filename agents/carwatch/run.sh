#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose up -d db
for i in $(seq 1 15); do
    status="$(docker compose ps db --format '{{.Health}}')"
    if [ "$status" = "healthy" ]; then
        break
    fi
    sleep 2
done

docker compose run --rm app weekly-run
