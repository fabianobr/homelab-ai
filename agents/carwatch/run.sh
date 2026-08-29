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

# O backup roda depois do weekly-run, para capturar os dados da semana. Falha de
# backup não pode derrubar um run que deu certo -- `set -e` mataria o script aqui,
# e o resultado seria um run bem-sucedido reportado como falha.
if ! ./backup.sh; then
    echo "carwatch: backup falhou apos weekly-run" >&2
fi
