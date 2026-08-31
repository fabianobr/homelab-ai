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

ENVFILE="${COLI_ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/homelab.env}"
# Lido ANTES dos defaults: senão só COLI_API_KEY teria efeito e as demais
# COLI_* do arquivo seriam silenciosamente ignoradas.
# shellcheck disable=SC1090
[ -f "$ENVFILE" ] && . "$ENVFILE"

MODEL="${COLI_MODEL:-$HOME/AI/models/colibri/deepseek_v4}"
ENGINE_DIR="${COLI_DIR:-$HOME/AI/colibri}/c"
PORT="${COLI_PORT:-5000}"
MODEL_ID="${COLI_MODEL_ID:-deepseek-v4}"
NET="${COLI_DOCKER_NET:-bridge}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/colibri"
PIDFILE="$STATE/serve.pid"
LOGFILE="$STATE/serve.log"
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
    | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | head -1 || true
}

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

# O engine é processo FILHO do launcher e é quem segura a RAM. Casar por
# caminho exato: `pkill -f deepseek_v4` mataria um editor ou grep que apenas
# mencione o arquivo.
engine_pids() { pgrep -x deepseek_v4 2>/dev/null || true; }

case "${1:-}" in
start)
  running && die "já está rodando (pid $(cat "$PIDFILE"))"
  [ -d "$MODEL" ] || die "modelo não encontrado: $MODEL"
  [ -f "$ENGINE_DIR/coli" ] || die "launcher não encontrado em $ENGINE_DIR"

  [ -n "${COLI_API_KEY:-}" ] || die "COLI_API_KEY vazio. Defina em $ENVFILE — sem chave o
  endpoint fica aberto a TODOS os containers da bridge, não só ao LiteLLM."
  # O LiteLLM precisa do MESMO valor; ele o recebe via environment no compose.

  GW="$(resolve_gateway)"
  [ -n "$GW" ] || die "não achei o gateway da rede '$NET'. A stack está de pé?
  Confira com: docker network ls"

  free_gb=$(awk '/MemAvailable/{printf "%d", $2/1048576}' /proc/meminfo)   # GiB, truncado
  [ "$free_gb" -ge "$MIN_FREE_GB" ] || die "só ${free_gb} GiB de RAM disponível (mínimo
  ${MIN_FREE_GB}). Pare o ComfyUI (docker stop comfyui) ou feche o desktop.
  Ajuste o piso com COLI_MIN_FREE_GB no ambiente ou no homelab.env."

  echo "colibri-serve: subindo em ${GW}:${PORT} (modelo $MODEL_ID)"
  cd "$ENGINE_DIR"
  # COLI_API_KEY vai pelo AMBIENTE, nunca como --api-key: /proc/<pid>/cmdline é
  # legível por qualquer processo local e o segredo apareceria em `ps`. O
  # launcher já usa a variável como default (coli: --api-key default=os.environ).
  COLI_MODEL="$MODEL" COLI_API_KEY="$COLI_API_KEY" \
  DSV4_CUDA=1 COLI_CUDA_ATTN_BATCH=1 \
  nohup python3 ./coli serve \
      --host "$GW" --port "$PORT" \
      --gpu 0 --ctx "${COLI_CTX:-32768}" \
      --model-id "$MODEL_ID" \
      --allowed-host "host.docker.internal" \
      --max-queue "${COLI_MAX_QUEUE:-4}" \
      --queue-timeout "${COLI_QUEUE_TIMEOUT:-2400}" \
      >"$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  echo "colibri-serve: pid $(cat "$PIDFILE") · log em $LOGFILE"
  echo "colibri-serve: carrega ~6,3 GB de pesos densos antes de aceitar requisição."
  ;;
stop)
  # O engine é morto SEMPRE, mesmo com o launcher já morto ou o pidfile obsoleto:
  # é ele que segura os ~12 GB, e se o launcher cair sozinho (OOM, por exemplo)
  # esta é a única forma de recuperar a RAM.
  if running; then
    pid="$(cat "$PIDFILE")"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
  fi
  eng="$(engine_pids)"
  if [ -n "$eng" ]; then
    echo "$eng" | xargs -r kill -TERM 2>/dev/null || true
    sleep 2
    engine_pids | xargs -r kill -KILL 2>/dev/null || true
    echo "colibri-serve: engine encerrado (RAM liberada)"
  fi
  rm -f "$PIDFILE"
  echo "colibri-serve: parado"
  ;;
status)
  # Exit 0 = no ar, 1 = parado. Um wrapper ou healthcheck depende disso.
  eng="$(engine_pids)"
  if running; then
    echo "colibri-serve: rodando (pid $(cat "$PIDFILE"))"
    GW="$(resolve_gateway)"; echo "  endpoint: http://${GW:-?}:${PORT}/v1"
    if [ -n "$eng" ]; then
      ps -o rss= -p "$(echo "$eng" | head -1)" 2>/dev/null |
        awk '{printf "  RAM do engine: %.1f GiB\n",$1/1048576}'
    else
      echo "  ATENÇÃO: launcher vivo mas engine ausente — rode stop e suba de novo."
    fi
    exit 0
  elif [ -n "$eng" ]; then
    # Launcher morto e engine órfão: o caso que mais engana, porque `ps` do
    # pidfile não mostra nada e a RAM continua ocupada.
    echo "colibri-serve: ÓRFÃO — launcher morto, engine ainda segurando RAM (pid $eng)"
    echo "  rode: $0 stop"
    exit 1
  else
    echo "colibri-serve: parado"
    exit 1
  fi
  ;;
logs) tail -n "${2:-40}" "$LOGFILE" 2>/dev/null || echo "sem log ainda" ;;
*) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
