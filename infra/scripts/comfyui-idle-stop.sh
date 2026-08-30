#!/usr/bin/env bash
# Para o container do ComfyUI quando ele está ocioso.
#
# ComfyUI é sob demanda: sobe com `docker start comfyui`, e este script
# (chamado por comfyui-idle-stop.timer a cada 20 min) o desliga depois de
# ~1h sem atividade, para não segurar ~20 GiB de RAM + VRAM à toa.
#
# Ocioso = container no ar há mais de IDLE_WINDOW, sem job na fila e sem
# "got prompt" / "Prompt executed" nos logs da última hora. Se a API não
# responde mas o container está velho e os logs estão parados, tratamos
# como travado e desligamos também (é justamente o caso que segura RAM).
# Sem arquivo de estado.

set -euo pipefail

CONTAINER="${COMFYUI_CONTAINER:-comfyui}"
PORT="${COMFYUI_PORT:-8188}"
IDLE_WINDOW="${COMFYUI_IDLE_WINDOW:-65m}"
IDLE_SECONDS="${COMFYUI_IDLE_SECONDS:-3900}"  # IDLE_WINDOW em segundos

log() { echo "comfyui-idle-stop: $*"; }

# Container não está rodando -> nada a fazer.
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  log "container '$CONTAINER' não está rodando; nada a fazer"
  exit 0
fi

# Subiu há pouco -> pode estar carregando modelo / API ainda de pé.
started_at="$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER")"
uptime_s=$(( $(date +%s) - $(date -d "$started_at" +%s) ))
if [ "$uptime_s" -lt "$IDLE_SECONDS" ]; then
  log "no ar há ${uptime_s}s (< ${IDLE_SECONDS}s); cedo demais para desligar"
  exit 0
fi

# Fila com job rodando ou pendente -> ocupado.
queue="$(curl -sf --max-time 5 "http://127.0.0.1:${PORT}/queue" || echo '')"
if [ -n "$queue" ]; then
  if ! echo "$queue" | grep -q '"queue_running": *\[\]' \
     || ! echo "$queue" | grep -q '"queue_pending": *\[\]'; then
    log "fila não vazia; ocupado"
    exit 0
  fi
else
  log "sem resposta de /queue; container pode estar travado, checando logs"
fi

# Atividade recente nos logs -> ocioso ainda não (cobre render longo, cuja
# entrada 'got prompt' fica dentro da janela mesmo sem a de conclusão).
if docker logs "$CONTAINER" --since "$IDLE_WINDOW" 2>&1 \
     | grep -qE 'got prompt|Prompt executed'; then
  log "atividade nos últimos $IDLE_WINDOW; ainda não ocioso"
  exit 0
fi

log "ocioso há mais de $IDLE_WINDOW e fila vazia; parando '$CONTAINER'"
docker stop "$CONTAINER"
