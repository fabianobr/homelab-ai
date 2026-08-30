#!/usr/bin/env bash
# Para o container do ComfyUI quando ele está ocioso.
#
# ComfyUI é sob demanda: sobe com `docker start comfyui`, e este script
# (chamado por comfyui-idle-stop.timer a cada 20 min) o desliga depois de
# ~1h sem atividade, para não segurar ~20 GiB de RAM + VRAM à toa.
#
# Ocioso = container no ar, fila vazia e nenhum "got prompt" / "Prompt
# executed" nos logs da última hora. Sem arquivo de estado.

set -euo pipefail

CONTAINER="${COMFYUI_CONTAINER:-comfyui}"
PORT="${COMFYUI_PORT:-8188}"
IDLE_WINDOW="${COMFYUI_IDLE_WINDOW:-65m}"

log() { echo "comfyui-idle-stop: $*"; }

# Container não está rodando -> nada a fazer.
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  log "container '$CONTAINER' não está rodando; nada a fazer"
  exit 0
fi

# Fila com job rodando ou pendente -> ocupado.
queue="$(curl -sf --max-time 5 "http://127.0.0.1:${PORT}/queue" || echo '')"
if [ -z "$queue" ]; then
  log "sem resposta de /queue; assumindo ocupado, não desliga"
  exit 0
fi
if ! echo "$queue" | grep -q '"queue_running": \[\]' \
   || ! echo "$queue" | grep -q '"queue_pending": \[\]'; then
  log "fila não vazia; ocupado"
  exit 0
fi

# Atividade recente nos logs -> ocioso ainda não.
if docker logs "$CONTAINER" --since "$IDLE_WINDOW" 2>&1 \
     | grep -qE 'got prompt|Prompt executed'; then
  log "atividade nos últimos $IDLE_WINDOW; ainda não ocioso"
  exit 0
fi

log "ocioso há mais de $IDLE_WINDOW e fila vazia; parando '$CONTAINER'"
docker stop "$CONTAINER"
