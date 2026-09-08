#!/usr/bin/env bash
# Smoke test do profile `harness` (DeepSeek Harness + dsh-files).
#
# Prova o caminho REALMENTE publicado — `127.0.0.1:3081` no host — e não o
# servidor interno do DSH. Essa distinção é o motivo do script existir: o
# healthcheck antigo do container sondava `127.0.0.1:3080` de dentro do próprio
# container, ficava verde com a porta publicada morta, e o `docker ps` mentia.
#
#   infra/scripts/dsh-smoke.sh                 # só as asserções (não destrutivo)
#   infra/scripts/dsh-smoke.sh --reboot-cycle  # reproduz recriação + reboot e depois assere
#
# `--reboot-cycle` reproduz o modo de falha real observado em produção:
#   1. recria SÓ o `deepseek-harness` (foi o que um PR de bind mount fez);
#   2. para e sobe de novo os containers do profile, sem recriar — é o que o
#      Docker faz sozinho depois de um reboot do host (`restart: unless-stopped`).
# Um sidecar preso ao network namespace do container antigo morre no passo 2 com
# `No such container: <ID antigo>` e a porta publicada fica sem ninguém escutando.
#
# Exit 0 = tudo verde.
# Exit 1 = alguma asserção falhou.
# Exit 2 = uso / ferramenta ausente / env-file ausente.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="${DSH_COMPOSE_FILE:-infra/docker/docker-compose.yml}"
ENV_FILE="${HOMELAB_ENV_FILE:-$PROJECT_ROOT/homelab.env}"
PROFILE="${DSH_PROFILE:-harness}"
DSH_URL="${DSH_URL:-http://127.0.0.1:3081}"
FILES_URL="${DSH_FILES_URL:-http://127.0.0.1:3082}"
WAIT_SECONDS="${DSH_SMOKE_WAIT:-90}"

REBOOT_CYCLE=0
case "${1:-}" in
  "") ;;
  --reboot-cycle) REBOOT_CYCLE=1 ;;
  *) echo "usage: $0 [--reboot-cycle]" >&2; exit 2 ;;
esac

for bin in docker curl; do
  command -v "$bin" >/dev/null || { echo "need $bin" >&2; exit 2; }
done
[[ -f "$ENV_FILE" ]] || { echo "env file not found: $ENV_FILE" >&2; exit 2; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile "$PROFILE" "$@"; }

mapfile -t services < <(dc config --services)
(( ${#services[@]} )) || { echo "nenhum serviço no profile $PROFILE" >&2; exit 2; }

fails=0
ok()   { echo "[OK]   $*"; }
fail() { echo "[FAIL] $*" >&2; fails=$((fails + 1)); }

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" || echo 000; }

# Espera a porta publicada responder 200. Não usa o health do container de
# propósito: o objetivo é justamente não confiar nele.
wait_for_dsh() {
  local deadline=$(( SECONDS + WAIT_SECONDS ))
  while (( SECONDS < deadline )); do
    [[ "$(http_code "$DSH_URL/")" == "200" ]] && return 0
    sleep 3
  done
  return 1
}

# --- ciclo de reprodução (opcional) -----------------------------------------
if (( REBOOT_CYCLE )); then
  echo "== dsh-smoke --reboot-cycle: serviços = ${services[*]}"

  echo "-- 1/2 recriando SÓ o deepseek-harness (gatilho original)"
  dc up -d --force-recreate --no-deps deepseek-harness
  wait_for_dsh || echo "   (aviso: não voltou a 200 já depois da recriação)"

  echo "-- 2/2 simulando reboot: stop + start, sem recriar"
  dc stop "${services[@]}"
  dc start "${services[@]}" || echo "   (start reportou erro — segue para as asserções)"
  wait_for_dsh || true
  echo
fi

# --- asserções ---------------------------------------------------------------
echo "== dsh-smoke: $DSH_URL / $FILES_URL"

code="$(http_code "$DSH_URL/")"
if [[ "$code" == "200" ]]; then
  ok "DSH web na porta publicada ($DSH_URL/ = 200)"
else
  fail "DSH web na porta publicada ($DSH_URL/ = $code)"
fi

body="$(curl -s --max-time 10 "$DSH_URL/" || true)"
if [[ "$body" == *"@deepseek-ai/dsh"* ]]; then
  ok "corpo servido é o DSH web (contém @deepseek-ai/dsh)"
else
  fail "corpo servido não parece o DSH web"
fi

code="$(http_code "$FILES_URL/")"
if [[ "$code" == "302" ]]; then
  ok "dsh-files redireciona ($FILES_URL/ = 302)"
else
  fail "dsh-files ($FILES_URL/ = $code, esperado 302)"
fi

code="$(http_code "$FILES_URL/files/")"
if [[ "$code" == "200" ]]; then
  ok "dsh-files serve a listagem ($FILES_URL/files/ = 200)"
else
  fail "dsh-files ($FILES_URL/files/ = $code, esperado 200)"
fi

# Todo container do profile precisa estar `running` — `restarting` é falha.
mapfile -t containers < <(dc ps -a --format '{{.Name}}' "${services[@]}" 2>/dev/null || true)
for name in "${containers[@]}"; do
  [[ -n "$name" ]] || continue
  state="$(docker inspect "$name" --format '{{.State.Status}}' 2>/dev/null || echo missing)"
  if [[ "$state" == "running" ]]; then
    ok "container $name: running"
  else
    exit_code="$(docker inspect "$name" --format '{{.State.ExitCode}}' 2>/dev/null || echo '?')"
    err="$(docker inspect "$name" --format '{{.State.Error}}' 2>/dev/null || true)"
    fail "container $name: $state (exit $exit_code) ${err:+- $err}"
  fi
done

# Regressão específica: `network_mode: service:`/`container:` é resolvido para o
# ID do alvo no momento da criação. Se o alvo for recriado, o vínculo aponta
# para um container que não existe mais e o dependente morre no próximo boot.
for name in "${containers[@]}"; do
  [[ -n "$name" ]] || continue
  netmode="$(docker inspect "$name" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
  [[ "$netmode" == container:* ]] || continue
  target="${netmode#container:}"
  target_state="$(docker inspect "$target" --format '{{.State.Status}}' 2>/dev/null || echo missing)"
  if [[ "$target_state" == "running" ]]; then
    fail "$name usa netns de outro container ($netmode) — vínculo por ID, quebra quando o alvo for recriado"
  else
    fail "$name aponta para netns inexistente/parado: $netmode ($target_state)"
  fi
done

echo
if (( fails )); then
  echo "== FAIL: $fails asserção(ões) falharam" >&2
  exit 1
fi
echo "== PASS: profile $PROFILE saudável pelo caminho publicado"
