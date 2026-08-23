#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infra/docker/docker-compose.yml"
ENV_FILE="$REPO_ROOT/infra/docker/.env"
DRY_RUN=0
SERVICES=()
ALLOWED=" ollama open-webui comfyui n8n litellm searxng "

usage() {
  echo "Uso: $0 [--dry-run] SERVICO [SERVICO...]"
  echo "Serviços: ollama open-webui comfyui n8n litellm searxng"
  echo "Aplica somente versões já pinadas no Compose; não altera manifests."
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) SERVICES+=("$arg") ;;
  esac
done

((${#SERVICES[@]})) || { usage >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "Arquivo ausente: $ENV_FILE" >&2; exit 1; }

for service in "${SERVICES[@]}"; do
  [[ "$ALLOWED" == *" $service "* ]] || { echo "Serviço inválido: $service" >&2; exit 2; }
done

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" config --quiet

NEED_BACKUP=0
for service in "${SERVICES[@]}"; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$service" 2>/dev/null || true)" != "true" ]]; then
    echo "Recusado: $service não estava ativo; o script não ativa serviços parados." >&2
    exit 1
  fi
  if (( DRY_RUN )); then
    echo "[dry-run] aplicar versão pinada e validar health: $service"
  fi
  [[ "$service" == "open-webui" || "$service" == "n8n" ]] && NEED_BACKUP=1
done

(( DRY_RUN )) && exit 0
(( NEED_BACKUP )) && "$REPO_ROOT/infra/scripts/backup.sh"

for service in "${SERVICES[@]}"; do
  container="$service"
  if [[ "$service" == "comfyui" || "$service" == "n8n" ]]; then
    current_image="$(docker inspect -f '{{.Image}}' "$container")"
    rollback="homelab-ai/rollback-$service:$(date +%Y%m%d-%H%M%S)"
    docker tag "$current_image" "$rollback"
    echo "Rollback preservado: $rollback"
    "${compose[@]}" build "$service"
  else
    "${compose[@]}" pull "$service"
  fi

  "${compose[@]}" up -d --no-deps "$service"

  healthy=0
  for _ in {1..30}; do
    state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"
    if [[ "$state" == "healthy" || "$state" == "running" ]]; then healthy=1; break; fi
    [[ "$state" == "unhealthy" || "$state" == "exited" ]] && break
    sleep 2
  done
  (( healthy )) || { echo "Falha no sanity check de $service (estado: $state)." >&2; exit 1; }
  echo "Atualização validada: $service ($state)"
done
