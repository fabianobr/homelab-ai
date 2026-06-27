#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK_FILE="${ROOT}/infra/media-pipeline/components.lock"

if [[ ! -f "${LOCK_FILE}" ]]; then
  echo "[MISSING] lock file: ${LOCK_FILE}" >&2
  exit 1
fi

# Recuse conteúdo executável antes de carregar o lock file versionado.
if grep -Ev '^(#[[:print:]]*|[[:space:]]*$|[A-Z0-9_]+=[A-Za-z0-9._:/@+-]+)$' "${LOCK_FILE}" | grep -q .; then
  echo "[MISSING] invalid content in ${LOCK_FILE}" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "${LOCK_FILE}"

COMFYUI_SOURCE_DIR="${COMFYUI_SOURCE_DIR:-${HOMELAB_RUNTIME_DIR:-${ROOT}/infra/runtime}/comfyui}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[MISSING] $1; install it and run this command again" >&2
    exit 1
  }
}

clone_at_commit() {
  local name="$1" repository="$2" commit="$3" destination="$4"
  local current=""
  local created=false

  if [[ -e "${destination}" && ! -d "${destination}/.git" ]]; then
    echo "[MISSING] ${destination} exists but is not a Git checkout" >&2
    exit 1
  fi
  if [[ ! -d "${destination}/.git" ]]; then
    mkdir -p "$(dirname "${destination}")"
    git clone --filter=blob:none --no-checkout "${repository}" "${destination}"
    created=true
  fi
  current="$(git -C "${destination}" remote get-url origin)"
  if [[ "${current%.git}" != "${repository%.git}" ]]; then
    echo "[MISSING] ${name} origin differs from the public lock file: ${destination}" >&2
    exit 1
  fi
  if [[ "${created}" == false ]]; then
    git -C "${destination}" diff --quiet --ignore-submodules -- || {
      echo "[MISSING] ${name} has local changes; preserve or remove them manually" >&2
      exit 1
    }
    git -C "${destination}" diff --cached --quiet --ignore-submodules -- || {
      echo "[MISSING] ${name} has staged changes; preserve or remove them manually" >&2
      exit 1
    }
  fi
  if ! git -C "${destination}" cat-file -e "${commit}^{commit}" 2>/dev/null; then
    git -C "${destination}" fetch --depth 1 origin "${commit}"
  fi
  git -C "${destination}" checkout --detach --quiet "${commit}"
  echo "[OK] ${name} at ${commit}"
}

require_command git
clone_at_commit "ComfyUI" "${COMFYUI_REPOSITORY}" "${COMFYUI_COMMIT}" "${COMFYUI_SOURCE_DIR}"
clone_at_commit "ComfyUI-Manager" "${COMFYUI_MANAGER_REPOSITORY}" "${COMFYUI_MANAGER_COMMIT}" "${COMFYUI_SOURCE_DIR}/custom_nodes/ComfyUI-Manager"
clone_at_commit "ComfyUI-LTXVideo" "${COMFYUI_LTXVIDEO_REPOSITORY}" "${COMFYUI_LTXVIDEO_COMMIT}" "${COMFYUI_SOURCE_DIR}/custom_nodes/ComfyUI-LTXVideo"

LOCAL_NODE_SOURCE="${ROOT}/infra/docker/comfyui/custom_nodes/ComfyUI-OllamaFlushVRAM"
LOCAL_NODE_DESTINATION="${COMFYUI_SOURCE_DIR}/custom_nodes/ComfyUI-OllamaFlushVRAM"
mkdir -p "${LOCAL_NODE_DESTINATION}"
cp "${LOCAL_NODE_SOURCE}/__init__.py" "${LOCAL_NODE_SOURCE}/README.md" "${LOCAL_NODE_DESTINATION}/"

mkdir -p \
  "${COMFYUI_SOURCE_DIR}/models/checkpoints" \
  "${COMFYUI_SOURCE_DIR}/models/clip" \
  "${COMFYUI_SOURCE_DIR}/models/loras" \
  "${COMFYUI_SOURCE_DIR}/models/text_encoders" \
  "${COMFYUI_SOURCE_DIR}/input" \
  "${COMFYUI_SOURCE_DIR}/output"

echo "[OK] ComfyUI runtime prepared at ${COMFYUI_SOURCE_DIR}"
