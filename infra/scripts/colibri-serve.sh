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
# Quem esta segurando a porta, seja qual for o pidfile. Um launcher iniciado a
# mao (ou de uma sessao anterior) nao aparece em `running`, mas impede o bind e
# faz o LiteLLM falar com um servidor cujo engine ja morreu.
port_pid() {
  { ss -tlnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$"' |
      grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2; } || true
}

# Qualquer socket na porta, nao so LISTEN. O openai_server.py NAO define
# allow_reuse_address, entao um TIME_WAIT deixado por um stop recente faz o
# bind falhar com "Address already in use" mesmo sem processo algum.
# Coluna de endereço LOCAL, não o filtro `sport =` do ss: aquele não casa com
# sockets em TIME-WAIT e a espera terminava na hora, sem esperar nada.
port_busy() {
  ss -tan 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PORT}\$"
}

# NOTA: toda substituicao de comando abaixo precisa de `|| true`. Com
# `set -euo pipefail`, um grep sem resultado derruba o script SEM IMPRIMIR NADA
# — foi o que fez o `start` sair com codigo 1 e zero saida.

# `state=Z` exclui zombies: depois de um stop o engine vira defunct até o init
# recolher, e sem o filtro o `status` reportaria "órfão" para sempre.
engine_pids() {
  { pgrep -x deepseek_v4 2>/dev/null || true; } | while read -r p; do
    [ -n "$p" ] || continue
    [ "$(ps -o stat= -p "$p" 2>/dev/null | cut -c1)" = "Z" ] || echo "$p"
  done
}

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

  # Sem isto o bind falha com "Address already in use" DEPOIS do fork, o pidfile
  # guarda um pid morto e o LiteLLM segue falando com o servidor velho.
  # Checar a PORTA nao basta: o `coli serve` so binda DEPOIS de carregar o
  # modelo (~40-60 s). Uma tentativa anterior ainda carregando deixa a porta
  # livre agora e a rouba depois — e o start novo morre no bind, ja com o
  # pidfile gravado.
  #
  # `-f` casado no CAMINHO ABSOLUTO, nao na substring solta "coli serve --host":
  # essa substring aparece na linha de comando de qualquer grep, ps ou editor
  # que a mencione (reproduzido nesta sessao com um `sh -c` decoy e com o
  # proprio ugrep do harness) — um `-f` solto derrubaria um processo alheio em
  # `stop`, ou bloquearia um `start` legitimo por falso positivo.
  prev="$(pgrep -f "${ENGINE_DIR}/coli serve --host" | head -1 || true)"
  [ -z "$prev" ] || die "já há um 'coli serve' em execução (pid $prev), possivelmente
  ainda carregando o modelo. Rode: $0 stop"

  other="$(port_pid)"
  [ -z "$other" ] || die "a porta $PORT já está em uso (pid $other). Rode: $0 stop"

  # Espera o TIME_WAIT drenar: sem SO_REUSEADDR no servidor, subir logo depois
  # de um stop falha no bind — e falha DEPOIS do fork, deixando um pidfile
  # apontando para um processo morto.
  if port_busy; then
    echo "colibri-serve: porta $PORT em TIME_WAIT, aguardando liberar..."
    for _ in $(seq 1 90); do port_busy || break; sleep 1; done
    port_busy && die "a porta $PORT continua ocupada após 90 s."
  fi

  free_gb=$(awk '/MemAvailable/{printf "%d", $2/1048576}' /proc/meminfo)   # GiB, truncado
  [ "$free_gb" -ge "$MIN_FREE_GB" ] || die "só ${free_gb} GiB de RAM disponível (mínimo
  ${MIN_FREE_GB}). Pare o ComfyUI (docker stop comfyui) ou feche o desktop.
  Ajuste o piso com COLI_MIN_FREE_GB no ambiente ou no homelab.env."

  echo "colibri-serve: subindo em ${GW}:${PORT} (modelo $MODEL_ID)"
  cd "$ENGINE_DIR"
  # COLI_API_KEY vai pelo AMBIENTE, nunca como --api-key: /proc/<pid>/cmdline é
  # legível por qualquer processo local e o segredo apareceria em `ps`. O
  # launcher já usa a variável como default (coli: --api-key default=os.environ).
  #
  # `"$ENGINE_DIR/coli"` em vez de `./coli`: o argv do processo precisa
  # carregar o caminho ABSOLUTO para que `pgrep -f "$ENGINE_DIR/coli serve"`
  # (usado abaixo e em `stop`) ache o processo real. Com caminho relativo o
  # match nunca acontece — verificado: um `./coli serve --host ...` real não
  # é encontrado por um pgrep ancorado no caminho absoluto.
  COLI_MODEL="$MODEL" COLI_API_KEY="$COLI_API_KEY" \
  DSV4_CUDA=1 COLI_CUDA_ATTN_BATCH=1 \
  nohup python3 "$ENGINE_DIR/coli" serve \
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
  # O launcher órfão segura a porta mesmo com o engine morto: sem isto o próximo
  # start falha no bind e o LiteLLM continua falando com um servidor inútil.
  # Tambem um launcher ainda carregando, que nao aparece na porta mas roubaria
  # o bind da proxima tentativa.
  pkill -f "${ENGINE_DIR}/coli serve --host" 2>/dev/null || true
  lp="$(port_pid)"
  if [ -n "$lp" ]; then
    kill -TERM "$lp" 2>/dev/null || true
    sleep 1
    kill -0 "$lp" 2>/dev/null && kill -KILL "$lp" 2>/dev/null || true
    echo "colibri-serve: launcher na porta $PORT encerrado (pid $lp)"
  fi
  rm -f "$PIDFILE"
  # Drena o TIME_WAIT antes de devolver o controle, senao um `start` logo em
  # seguida falha no bind.
  for _ in $(seq 1 90); do port_busy || break; sleep 1; done
  echo "colibri-serve: parado"
  ;;
status)
  # Exit 0 = no ar, 1 = parado. Um wrapper ou healthcheck depende disso.
  eng="$(engine_pids)"; lp="$(port_pid)"
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
  elif [ -n "$lp" ] || [ -n "$eng" ]; then
    # Launcher morto e engine órfão: o caso que mais engana, porque `ps` do
    # pidfile não mostra nada e a RAM continua ocupada.
    echo "colibri-serve: ÓRFÃO — sem pidfile válido, mas há processo vivo"
    [ -n "$lp" ]  && echo "  launcher segurando a porta $PORT: pid $lp"
    [ -n "$eng" ] && echo "  engine segurando RAM: pid $eng"
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
