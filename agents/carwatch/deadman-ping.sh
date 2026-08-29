#!/usr/bin/env bash
# Ping do dead man's switch: avisa o Worker na Cloudflare que este run terminou bem.
# O Worker (infra/cloudflare/deadman-switch/) alerta no Telegram se este ping parar
# de chegar -- timer que não dispara mais, linger perdido num upgrade, máquina
# desligada por dias. Um heartbeat interno não pega nada disso porque morre junto.
#
# Chamado pelo run.sh DEPOIS do weekly-run e do backup, e de forma não-fatal:
# um ping que falha não pode derrubar um run que deu certo.
#
# Ambiente (vem do .env, carregado pelo run.sh):
#   CARWATCH_DEADMAN_URL    endpoint /ping/carwatch do Worker; vazio desliga o ping
#   CARWATCH_DEADMAN_TOKEN  Bearer token (secret PING_TOKEN_CARWATCH no Worker)
set -euo pipefail

URL="${CARWATCH_DEADMAN_URL:-}"
TOKEN="${CARWATCH_DEADMAN_TOKEN:-}"

if [ -z "$URL" ]; then
    echo "deadman-ping.sh: CARWATCH_DEADMAN_URL vazio, ping desligado"
    exit 0
fi

if [ -z "$TOKEN" ]; then
    echo "deadman-ping.sh: CARWATCH_DEADMAN_TOKEN vazio com URL setada -- o Worker rejeitaria (401)" >&2
    exit 1
fi

# `|| true`: sem token de `-f`, um erro de conexão/timeout faz o curl sair !=0 e o
# `set -e` mataria o script AQUI, na atribuição, pulando o diagnóstico abaixo.
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --retry 2 --retry-delay 2 \
    -X POST -H "Authorization: Bearer $TOKEN" "$URL" || true)"
code="${code:-000}"

if [ "$code" = "204" ]; then
    echo "deadman-ping.sh: ping ok"
    exit 0
fi

echo "deadman-ping.sh: ping falhou, HTTP $code" >&2
exit 1
