#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infra/docker/docker-compose.yml"
ENV_FILE="$REPO_ROOT/infra/docker/.env"
LOCK_FILE="$REPO_ROOT/infra/media-pipeline/components.lock"
ARCHIVER_IMAGE="alpine:3.22.5@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
DRY_RUN=0
SERVICES=()
ALLOWED=" ollama open-webui comfyui n8n litellm searxng "
HEALTH_ATTEMPTS="${HOMELAB_UPDATE_HEALTH_ATTEMPTS:-30}"
HEALTH_DELAY="${HOMELAB_UPDATE_HEALTH_DELAY:-2}"
BACKUP_DEST=""
COMFY_STATE_CAPTURED=0
COMFY_CONTAINER_STOPPED=0
COMFY_SOURCE_DIR=""
COMFY_PATHS=()
COMFY_PREVIOUS_COMMITS=()
COMFY_PREVIOUSLY_PRESENT=()
declare -A STATEFUL_VOLUMES=()

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

MANIFESTS=(
  infra/docker/docker-compose.yml
  infra/docker/comfyui/Dockerfile
  infra/docker/n8n/Dockerfile
  infra/media-pipeline/components.lock
  infra/scripts/backup.sh
  infra/scripts/prepare-media-pipeline.sh
  infra/scripts/update.sh
)
if ! git -C "$REPO_ROOT" diff --quiet -- "${MANIFESTS[@]}" \
  || ! git -C "$REPO_ROOT" diff --cached --quiet -- "${MANIFESTS[@]}"; then
  echo "Recusado: manifests operacionais possuem mudanças não commitadas." >&2
  echo "Commit ou preserve essas mudanças antes de aplicar uma atualização." >&2
  exit 1
fi

command -v docker >/dev/null
command -v flock >/dev/null
command -v git >/dev/null
command -v jq >/dev/null

mkdir -p "$REPO_ROOT/infra/runtime"
exec 8>"$REPO_ROOT/infra/runtime/update.lock"
flock -n 8 || { echo "Outra atualização já está em execução." >&2; exit 1; }

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" config --quiet

stateful_mount() {
  case "$1" in
    open-webui) echo /app/backend/data ;;
    n8n) echo /home/node/.n8n ;;
    *) return 1 ;;
  esac
}

wait_for_health() {
  local container="$1" state="missing"
  for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
    state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || echo missing)"
    if [[ "$state" == "healthy" || "$state" == "running" ]]; then
      echo "$state"
      return 0
    fi
    [[ "$state" == "unhealthy" || "$state" == "exited" || "$state" == "dead" ]] && break
    sleep "$HEALTH_DELAY"
  done
  echo "$state"
  return 1
}

capture_comfy_state() {
  COMFY_SOURCE_DIR="$("${compose[@]}" --profile media-pipeline config --format json | jq -er '.services.comfyui.build.context')"
  COMFY_PATHS=(
    "$COMFY_SOURCE_DIR"
    "$COMFY_SOURCE_DIR/custom_nodes/ComfyUI-Manager"
    "$COMFY_SOURCE_DIR/custom_nodes/ComfyUI-LTXVideo"
    "$COMFY_SOURCE_DIR/custom_nodes/comfyui-ollama"
  )
  COMFY_PREVIOUS_COMMITS=()
  COMFY_PREVIOUSLY_PRESENT=()
  for path in "${COMFY_PATHS[@]}"; do
    if [[ -d "$path/.git" ]]; then
      COMFY_PREVIOUSLY_PRESENT+=(1)
      COMFY_PREVIOUS_COMMITS+=("$(git -C "$path" rev-parse HEAD)")
    else
      COMFY_PREVIOUSLY_PRESENT+=(0)
      COMFY_PREVIOUS_COMMITS+=("")
    fi
  done
  [[ "${COMFY_PREVIOUSLY_PRESENT[0]}" == 1 ]] || {
    echo "Checkout principal do ComfyUI ausente: $COMFY_SOURCE_DIR" >&2
    return 1
  }
  COMFY_STATE_CAPTURED=1
}

restore_comfy_state() {
  (( COMFY_STATE_CAPTURED )) || return 0
  local index path preserved
  for ((index=${#COMFY_PATHS[@]}-1; index>=0; index--)); do
    path="${COMFY_PATHS[$index]}"
    if [[ "${COMFY_PREVIOUSLY_PRESENT[$index]}" == 1 ]]; then
      git -C "$path" checkout --detach --quiet "${COMFY_PREVIOUS_COMMITS[$index]}"
    elif [[ -e "$path" ]]; then
      preserved="$path.failed-update-$(date +%Y%m%d-%H%M%S)-$$"
      mv "$path" "$preserved"
      echo "Checkout criado na tentativa foi preservado em: $preserved" >&2
    fi
  done
  COMFY_STATE_CAPTURED=0
}

emergency_cleanup() {
  local exit_code=$?
  if (( exit_code != 0 && COMFY_STATE_CAPTURED )); then
    echo "Interrupção detectada; restaurando fontes anteriores do ComfyUI." >&2
    restore_comfy_state || echo "CRÍTICO: restauração emergencial das fontes falhou." >&2
  fi
  if (( exit_code != 0 && COMFY_CONTAINER_STOPPED )); then
    docker start comfyui >/dev/null 2>&1 || echo "CRÍTICO: não foi possível reiniciar o container anterior do ComfyUI." >&2
  fi
  exit "$exit_code"
}
trap emergency_cleanup EXIT

verify_comfy_lock() {
  if grep -Ev '^(#[[:print:]]*|[[:space:]]*$|[A-Z0-9_]+=[A-Za-z0-9._:/@+-]+)$' "$LOCK_FILE" | grep -q .; then
    echo "Lock inválido: $LOCK_FILE" >&2
    return 1
  fi
  # shellcheck disable=SC1090
  source "$LOCK_FILE"
  [[ "$(git -C "$COMFY_SOURCE_DIR" rev-parse HEAD)" == "$COMFYUI_COMMIT" ]]
  [[ "$(git -C "$COMFY_SOURCE_DIR/custom_nodes/ComfyUI-Manager" rev-parse HEAD)" == "$COMFYUI_MANAGER_COMMIT" ]]
  [[ "$(git -C "$COMFY_SOURCE_DIR/custom_nodes/ComfyUI-LTXVideo" rev-parse HEAD)" == "$COMFYUI_LTXVIDEO_COMMIT" ]]
  [[ "$(git -C "$COMFY_SOURCE_DIR/custom_nodes/comfyui-ollama" rev-parse HEAD)" == "$COMFYUI_OLLAMA_COMMIT" ]]
}

restore_volume() {
  local service="$1" archive volume
  archive="$BACKUP_DEST/$service.tgz"
  volume="${STATEFUL_VOLUMES[$service]}"
  [[ -f "$archive" ]] || { echo "Snapshot ausente para $service: $archive" >&2; return 1; }
  (cd "$BACKUP_DEST" && sha256sum -c --quiet SHA256SUMS)
  docker run --rm \
    --mount "type=volume,src=$volume,dst=/target" \
    --mount "type=bind,src=$BACKUP_DEST,dst=/backup,readonly" \
    --env "ARCHIVE_NAME=$service.tgz" \
    "$ARCHIVER_IMAGE" sh -eu -c \
      'find /target -depth -mindepth 1 -exec rm -rf -- {} \;; tar -xzf "/backup/$ARCHIVE_NAME" -C /target'
}

rollback_service() {
  local service="$1" rollback_image="$2" override state
  echo "Falha ao atualizar $service; iniciando rollback para $rollback_image." >&2
  docker stop --timeout 30 "$service" >/dev/null 2>&1 || true

  if [[ "$service" == "open-webui" || "$service" == "n8n" ]]; then
    restore_volume "$service"
  fi
  [[ "$service" == "comfyui" ]] && restore_comfy_state

  override="$(mktemp "$REPO_ROOT/infra/runtime/rollback-$service.XXXXXX.yml")"
  chmod 600 "$override"
  printf 'services:\n  %s:\n    image: %s\n' "$service" "$rollback_image" > "$override"
  if ! "${compose[@]}" -f "$override" up -d --no-deps --no-build --force-recreate "$service"; then
    rm -f "$override"
    echo "CRÍTICO: não foi possível recriar $service com $rollback_image." >&2
    return 1
  fi
  rm -f "$override"
  if ! state="$(wait_for_health "$service")"; then
    echo "CRÍTICO: rollback de $service não ficou saudável (estado: $state)." >&2
    return 1
  fi
  [[ "$service" == "comfyui" ]] && COMFY_CONTAINER_STOPPED=0
  echo "Rollback concluído: $service ($state, imagem $rollback_image)." >&2
}

STATEFUL_SERVICES=()
for service in "${SERVICES[@]}"; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$service" 2>/dev/null || true)" != "true" ]]; then
    echo "Recusado: $service não estava ativo; o script não ativa serviços parados." >&2
    exit 1
  fi
  if mount_destination="$(stateful_mount "$service" 2>/dev/null)"; then
    volume="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$mount_destination\"}}{{.Name}}{{end}}{{end}}" "$service")"
    [[ -n "$volume" ]] || { echo "Volume stateful de $service não encontrado." >&2; exit 1; }
    STATEFUL_VOLUMES[$service]="$volume"
    STATEFUL_SERVICES+=("$service")
  fi
  (( DRY_RUN )) && echo "[dry-run] aplicar versão pinada, validar health e reverter em falha: $service"
done

(( DRY_RUN )) && exit 0

if ((${#STATEFUL_SERVICES[@]})); then
  backup_output="$("$REPO_ROOT/infra/scripts/backup.sh" "${STATEFUL_SERVICES[@]}")"
  echo "$backup_output"
  BACKUP_DEST="$(printf '%s\n' "$backup_output" | sed -n 's/^BACKUP_DEST=//p' | tail -1)"
  [[ -d "$BACKUP_DEST" ]] || { echo "Destino do backup não pôde ser determinado." >&2; exit 1; }
fi

for service in "${SERVICES[@]}"; do
  container="$service"
  current_image="$(docker inspect -f '{{.Image}}' "$container")"
  rollback_image="homelab-ai/rollback-$service:$(date +%Y%m%d-%H%M%S)-$$"
  docker tag "$current_image" "$rollback_image"
  echo "Checkpoint de imagem: $rollback_image"

  if [[ "$service" == "comfyui" ]]; then
    capture_comfy_state
    docker stop --timeout 30 "$service" >/dev/null
    COMFY_CONTAINER_STOPPED=1
    if ! COMFYUI_SOURCE_DIR="$COMFY_SOURCE_DIR" "$REPO_ROOT/infra/scripts/prepare-media-pipeline.sh" \
      || ! verify_comfy_lock \
      || ! "${compose[@]}" build "$service"; then
      restore_comfy_state
      docker start "$service" >/dev/null
      COMFY_CONTAINER_STOPPED=0
      state="$(wait_for_health "$service" || true)"
      echo "Falha antes do deploy de $service; estado anterior restaurado ($state)." >&2
      exit 1
    fi
  elif [[ "$service" == "n8n" ]]; then
    if ! "${compose[@]}" build "$service"; then
      echo "Build de $service falhou; container anterior permaneceu ativo." >&2
      exit 1
    fi
  elif ! "${compose[@]}" pull "$service"; then
    echo "Pull de $service falhou; container anterior permaneceu ativo." >&2
    exit 1
  fi

  [[ "$service" == "comfyui" ]] && COMFY_CONTAINER_STOPPED=0
  if ! "${compose[@]}" up -d --no-deps "$service"; then
    rollback_service "$service" "$rollback_image"
    exit 1
  fi

  if ! state="$(wait_for_health "$service")"; then
    echo "Sanity check falhou para $service (estado: $state)." >&2
    rollback_service "$service" "$rollback_image"
    exit 1
  fi
  if [[ "$service" == "comfyui" ]]; then
    COMFY_STATE_CAPTURED=0
    COMFY_CONTAINER_STOPPED=0
  fi
  echo "Atualização validada: $service ($state; rollback: $rollback_image)"
done
