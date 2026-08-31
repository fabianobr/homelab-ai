#!/usr/bin/env bash
# colibri-serve — sobe/derruba o DeepSeek V4 (Colibrì) como backend do LiteLLM.
#
# NÃO está no docker-compose de propósito: o engine é compilado no host com
# CUDA/DeepGEMM para sm_120, e containerizar exigiria refazer esse build com
# passthrough de GPU. Ver docs/colibri.md, seção "Servindo pelo LiteLLM".
#
# É SOB DEMANDA. Segura ~16-21 GB de RAM enquanto vive; numa máquina de 29 GB
# isso não convive com ComfyUI nem com trabalho pesado. Suba, use, derrube.
#
#   colibri-serve.sh start | stop | status | logs
#
# Segredo: COLI_API_KEY vem do homelab.env na raiz do repo (gitignored), a mesma
# fonte que o LiteLLM usa — um segredo, um lugar.
set -euo pipefail

MODEL="${COLI_MODEL:-$HOME/AI/models/colibri/deepseek_v4}"
ENGINE_DIR="${COLI_DIR:-$HOME/AI/colibri}/c"
PORT="${COLI_PORT:-5000}"
MODEL_ID="${COLI_MODEL_ID:-deepseek-v4}"
NET="${COLI_DOCKER_NET:-bridge}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/colibri"
PIDFILE="$STATE/serve.pid"
LOGFILE="$STATE/serve.log"
ENVFILE="${COLI_ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/homelab.env}"
MIN_FREE_GB="${COLI_MIN_FREE_GB:-20}"

mkdir -p "$STATE"

die() { echo "colibri-serve: $*" >&2; exit 1; }

# O endereço que `host.docker.internal` resolve dentro dos containers. O Docker
# mapeia `host-gateway` SEMPRE para o gateway da bridge PADRÃO (docker0,
# 172.17.0.1) — não para o gateway da rede do container (docker_default,
# 172.18.0.1). Bindar no gateway "da rede do LiteLLM" parece certo e dá
# `Connection refused`. Resolvido em runtime porque o subnet pode mudar.
resolve_gateway() {
  docker network inspect "$NET" \
    --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null \
    | grep -E '^[0-9.]+$' || true
}

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
start)
  running && die "já está rodando (pid $(cat "$PIDFILE"))"
  [ -d "$MODEL" ] || die "modelo não encontrado: $MODEL"
  [ -x "$ENGINE_DIR/coli" ] || [ -f "$ENGINE_DIR/coli" ] || die "launcher não encontrado em $ENGINE_DIR"

  # shellcheck disable=SC1090
  [ -f "$ENVFILE" ] && . "$ENVFILE"
  [ -n "${COLI_API_KEY:-}" ] || die "COLI_API_KEY vazio. Defina em $ENVFILE — sem chave o
  endpoint fica aberto a TODOS os containers da bridge, não só ao LiteLLM."
  # O LiteLLM precisa do MESMO valor; ele o recebe via environment no compose.

  GW="$(resolve_gateway)"
  [ -n "$GW" ] || die "não achei o gateway da rede '$NET'. A stack está de pé?
  Confira com: docker network ls"

  free_gb=$(awk '/MemAvailable/{printf "%d", $2/1048576}' /proc/meminfo)
  [ "$free_gb" -ge "$MIN_FREE_GB" ] || die "só ${free_gb} GB de RAM disponível (mínimo
  ${MIN_FREE_GB}). Pare o ComfyUI (docker stop comfyui) ou feche o desktop."

  echo "colibri-serve: subindo em ${GW}:${PORT} (modelo $MODEL_ID)"
  cd "$ENGINE_DIR"
  COLI_MODEL="$MODEL" DSV4_CUDA=1 COLI_CUDA_MOE_BATCH=1 COLI_CUDA_ATTN_BATCH=1 \
  nohup python3 ./coli serve \
      --host "$GW" --port "$PORT" \
      --gpu 0 --ctx "${COLI_CTX:-32768}" \
      --model-id "$MODEL_ID" \
      --api-key "$COLI_API_KEY" \
      --allowed-host "host.docker.internal" \
      --max-queue "${COLI_MAX_QUEUE:-4}" \
      --queue-timeout "${COLI_QUEUE_TIMEOUT:-2400}" \
      >"$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  echo "colibri-serve: pid $(cat "$PIDFILE") · log em $LOGFILE"
  echo "colibri-serve: carrega ~6,3 GB de pesos densos antes de aceitar requisição."
  ;;
stop)
  running || { rm -f "$PIDFILE"; die "não está rodando"; }
  pid="$(cat "$PIDFILE")"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
  pkill -f "$ENGINE_DIR/deepseek_v4" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "colibri-serve: parado"
  ;;
status)
  if running; then
    echo "colibri-serve: rodando (pid $(cat "$PIDFILE"))"
    GW="$(resolve_gateway)"; echo "  endpoint: http://${GW:-?}:${PORT}/v1"
    ps -o rss= -p "$(cat "$PIDFILE")" 2>/dev/null | awk '{printf "  RSS do launcher: %.1f GB\n",$1/1048576}'
    pgrep -f "$ENGINE_DIR/deepseek_v4" >/dev/null && \
      ps -o rss= -p "$(pgrep -f "$ENGINE_DIR/deepseek_v4"|head -1)" | awk '{printf "  RSS do engine:   %.1f GB\n",$1/1048576}'
  else
    echo "colibri-serve: parado"
  fi
  ;;
logs) tail -n "${2:-40}" "$LOGFILE" 2>/dev/null || echo "sem log ainda" ;;
*) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
