#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# O ping do dead man's switch (fim do arquivo) lê CARWATCH_DEADMAN_* do .env.
# O docker compose lê o .env sozinho; este shell não -- daí o source explícito.
set -a
[ -f .env ] && . ./.env
set +a

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

# Ping do dead man's switch: só chega aqui se o weekly-run passou pelo `set -e`.
# Ping que falha (Worker fora, rede, token errado) não pode derrubar um run que
# deu certo -- mesma proteção não-fatal do backup acima.
if ! ./deadman-ping.sh; then
    echo "carwatch: ping do dead man's switch falhou apos weekly-run" >&2
fi
