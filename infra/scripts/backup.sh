#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_ROOT="${HOMELAB_BACKUP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/homelab-ai/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"
ARCHIVER_IMAGE="alpine:3.22.5@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
OUTPUT_UID="$(id -u)"
OUTPUT_GID="$(id -g)"
DRY_RUN=0
OWNERS=(open-webui n8n)
MOUNT_DESTINATIONS=(/app/backend/data /home/node/.n8n)
ARCHIVE_NAMES=(open-webui n8n)

usage() {
  echo "Uso: $0 [--dry-run] [--repo-only]"
  echo "Destino: HOMELAB_BACKUP_DIR (default: $BACKUP_ROOT)"
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --repo-only) OWNERS=(); MOUNT_DESTINATIONS=(); ARCHIVE_NAMES=() ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argumento inválido: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

umask 077

if (( DRY_RUN )); then
  echo "[dry-run] destino: $DEST"
  echo "[dry-run] snapshot Git rastreado: homelab-ai-tracked.tgz"
  for index in "${!OWNERS[@]}"; do
    echo "[dry-run] volume de ${OWNERS[$index]}:${MOUNT_DESTINATIONS[$index]} -> ${ARCHIVE_NAMES[$index]}.tgz"
  done
  exit 0
fi

command -v git >/dev/null
command -v sha256sum >/dev/null
if ((${#OWNERS[@]})); then command -v docker >/dev/null; fi

mkdir -p "$DEST"
chmod 700 "$BACKUP_ROOT" "$DEST"

# git archive nunca inclui .env, segredos ignorados ou o próprio backup.
git -C "$REPO_ROOT" archive --format=tar.gz --output="$DEST/homelab-ai-tracked.tgz" HEAD

active_container=""
restart_active() {
  if [[ -n "$active_container" ]]; then
    docker start "$active_container" >/dev/null
    active_container=""
  fi
}
trap restart_active EXIT INT TERM

for index in "${!OWNERS[@]}"; do
  owner="${OWNERS[$index]}"
  mount_destination="${MOUNT_DESTINATIONS[$index]}"
  archive_name="${ARCHIVE_NAMES[$index]}"
  volume="$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$mount_destination\"}}{{.Name}}{{end}}{{end}}" "$owner")"
  [[ -n "$volume" ]] || { echo "Volume de $owner:$mount_destination não encontrado." >&2; exit 1; }
  docker volume inspect "$volume" >/dev/null

  if [[ "$(docker inspect -f '{{.State.Running}}' "$owner" 2>/dev/null || true)" == "true" ]]; then
    active_container="$owner"
    docker stop --timeout 30 "$owner" >/dev/null
  fi

  docker run --rm \
    --mount "type=volume,src=$volume,dst=/source,readonly" \
    --mount "type=bind,src=$DEST,dst=/backup" \
    --env "ARCHIVE_NAME=$archive_name.tgz" \
    --env "OUTPUT_UID=$OUTPUT_UID" \
    --env "OUTPUT_GID=$OUTPUT_GID" \
    "$ARCHIVER_IMAGE" sh -eu -c \
      'tar -czf "/backup/$ARCHIVE_NAME" -C /source .; chmod 600 "/backup/$ARCHIVE_NAME"; chown "$OUTPUT_UID:$OUTPUT_GID" "/backup/$ARCHIVE_NAME"'
  restart_active
done

(cd "$DEST" && sha256sum ./*.tgz > SHA256SUMS)
chmod 600 "$DEST"/*
echo "Backup confidencial criado em: $DEST"
