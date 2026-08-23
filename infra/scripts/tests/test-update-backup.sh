#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP_ROOT="$(mktemp -d /tmp/homelab-operations-tests.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT

pass() { echo "PASS — $1"; }
fail() { echo "FAIL — $1" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail "esperava encontrar: $2"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "não esperava encontrar: $2"; }

MOCK_BIN="$TMP_ROOT/bin"
mkdir -p "$MOCK_BIN"
cat > "$MOCK_BIN/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${MOCK_DOCKER_LOG:?}"
case "${1:-}" in
  info|tag|stop|start|run) exit 0 ;;
  inspect)
    all="$*"
    target="${*: -1}"
    if [[ "$all" == *".State.Running"* ]]; then
      echo true
    elif [[ "$all" == *".Destination"* ]]; then
      echo "mock-$target-volume"
    elif [[ "$all" == *".Image"* ]]; then
      echo sha256:previous-image
    elif [[ "$all" == *".State.Health"* ]]; then
      count=0
      [[ -f "${MOCK_HEALTH_COUNT:?}" ]] && count="$(<"$MOCK_HEALTH_COUNT")"
      count=$((count + 1))
      echo "$count" > "$MOCK_HEALTH_COUNT"
      if [[ "$count" == 1 && "${MOCK_FIRST_HEALTH:-healthy}" != healthy ]]; then
        echo "${MOCK_FIRST_HEALTH}"
      else
        echo healthy
      fi
    elif [[ "$target" == n8n && "${MOCK_MISSING_N8N:-0}" == 1 ]]; then
      exit 1
    fi
    ;;
  volume) exit 0 ;;
  compose)
    if [[ "$*" == *"--format json"* ]]; then
      printf '{"services":{"comfyui":{"build":{"context":"%s"}}}}\n' "${MOCK_COMFY_SOURCE:-/tmp/comfyui}"
    fi
    exit 0
    ;;
esac
MOCK
chmod +x "$MOCK_BIN/docker"

export MOCK_DOCKER_LOG="$TMP_ROOT/docker.log"
export MOCK_HEALTH_COUNT="$TMP_ROOT/health-count"
: > "$MOCK_DOCKER_LOG"

output="$(PATH="$MOCK_BIN:$PATH" MOCK_MISSING_N8N=1 "$ROOT/infra/scripts/backup.sh" --dry-run open-webui)"
assert_contains "$output" 'volume de open-webui:/app/backend/data'
assert_not_contains "$output" 'n8n'
pass "backup explícito não exige o serviço opcional n8n"

output="$(PATH="$MOCK_BIN:$PATH" MOCK_MISSING_N8N=1 "$ROOT/infra/scripts/backup.sh" --dry-run)"
assert_contains "$output" 'volume de open-webui:/app/backend/data'
assert_not_contains "$output" 'volume de n8n:'
pass "backup automático ignora serviço opcional ausente"

new_fixture() {
  local fixture="$1"
  mkdir -p \
    "$fixture/infra/scripts" \
    "$fixture/infra/docker/comfyui" \
    "$fixture/infra/docker/n8n" \
    "$fixture/infra/media-pipeline" \
    "$fixture/infra/runtime"
  cp "$ROOT/infra/scripts/update.sh" "$fixture/infra/scripts/update.sh"
  printf 'services: {}\n' > "$fixture/infra/docker/docker-compose.yml"
  printf 'FROM scratch\n' > "$fixture/infra/docker/comfyui/Dockerfile"
  printf 'FROM scratch\n' > "$fixture/infra/docker/n8n/Dockerfile"
  : > "$fixture/infra/docker/.env"
  : > "$fixture/infra/media-pipeline/components.lock"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$fixture/infra/scripts/prepare-media-pipeline.sh"
  chmod +x "$fixture/infra/scripts/"*.sh
  git -C "$fixture" init -q
  git -C "$fixture" config user.name tests
  git -C "$fixture" config user.email tests@example.invalid
}

FIXTURE="$TMP_ROOT/stateful"
new_fixture "$FIXTURE"
cat > "$FIXTURE/infra/scripts/backup.sh" <<'BACKUP'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" > "${MOCK_BACKUP_ARGS:?}"
dest="${MOCK_BACKUP_DEST:?}"
mkdir -p "$dest"
printf snapshot > "$dest/open-webui.tgz"
(cd "$dest" && sha256sum open-webui.tgz > SHA256SUMS)
echo "BACKUP_DEST=$dest"
BACKUP
chmod +x "$FIXTURE/infra/scripts/backup.sh"
git -C "$FIXTURE" add .
git -C "$FIXTURE" commit -qm fixture

printf '# dirty\n' >> "$FIXTURE/infra/docker/docker-compose.yml"
set +e
dirty_output="$(PATH="$MOCK_BIN:$PATH" "$FIXTURE/infra/scripts/update.sh" --dry-run open-webui 2>&1)"
dirty_rc=$?
set -e
[[ "$dirty_rc" == 1 ]] || fail "manifest sujo deveria ser recusado"
assert_contains "$dirty_output" 'manifests operacionais possuem mudanças não commitadas'
git -C "$FIXTURE" checkout -q -- infra/docker/docker-compose.yml
pass "updater recusa manifests divergentes de HEAD"

export MOCK_BACKUP_ARGS="$TMP_ROOT/backup-args"
export MOCK_BACKUP_DEST="$TMP_ROOT/stateful-backup"
export MOCK_FIRST_HEALTH=unhealthy
rm -f "$MOCK_HEALTH_COUNT"
: > "$MOCK_DOCKER_LOG"
set +e
rollback_output="$(PATH="$MOCK_BIN:$PATH" "$FIXTURE/infra/scripts/update.sh" open-webui 2>&1)"
rollback_rc=$?
set -e
[[ "$rollback_rc" == 1 ]] || fail "update com health falho deve retornar erro após rollback"
[[ "$(<"$MOCK_BACKUP_ARGS")" == open-webui ]] || fail "backup recebeu serviços indevidos"
assert_contains "$rollback_output" 'Rollback concluído: open-webui'
assert_contains "$(<"$MOCK_DOCKER_LOG")" 'tag sha256:previous-image homelab-ai/rollback-open-webui:'
assert_contains "$(<"$MOCK_DOCKER_LOG")" 'run --rm --mount type=volume,src=mock-open-webui-volume,dst=/target'
pass "health failure restaura checkpoint pareado de imagem e volume"

FIXTURE="$TMP_ROOT/comfy"
new_fixture "$FIXTURE"
COMFY_SOURCE="$FIXTURE/runtime/comfyui"
paths=(
  "$COMFY_SOURCE"
  "$COMFY_SOURCE/custom_nodes/ComfyUI-Manager"
  "$COMFY_SOURCE/custom_nodes/ComfyUI-LTXVideo"
  "$COMFY_SOURCE/custom_nodes/comfyui-ollama"
)
old_commits=()
new_commits=()
for path in "${paths[@]}"; do
  mkdir -p "$path"
  git -C "$path" init -q
  git -C "$path" config user.name tests
  git -C "$path" config user.email tests@example.invalid
  printf old > "$path/version"
  git -C "$path" add version
  git -C "$path" commit -qm old
  old_commits+=("$(git -C "$path" rev-parse HEAD)")
  printf new > "$path/version"
  git -C "$path" commit -qam new
  new_commits+=("$(git -C "$path" rev-parse HEAD)")
  git -C "$path" checkout -q --detach "${old_commits[-1]}"
done
cat > "$FIXTURE/infra/media-pipeline/components.lock" <<LOCK
COMFYUI_REPOSITORY=https://example.invalid/ComfyUI.git
COMFYUI_COMMIT=${new_commits[0]}
COMFYUI_MANAGER_REPOSITORY=https://example.invalid/Manager.git
COMFYUI_MANAGER_COMMIT=${new_commits[1]}
COMFYUI_LTXVIDEO_REPOSITORY=https://example.invalid/LTX.git
COMFYUI_LTXVIDEO_COMMIT=${new_commits[2]}
COMFYUI_OLLAMA_REPOSITORY=https://example.invalid/Ollama.git
COMFYUI_OLLAMA_COMMIT=${new_commits[3]}
LOCK
cat > "$FIXTURE/infra/scripts/prepare-media-pipeline.sh" <<'PREPARE'
#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$root/infra/media-pipeline/components.lock"
git -C "$COMFYUI_SOURCE_DIR" checkout -q --detach "$COMFYUI_COMMIT"
git -C "$COMFYUI_SOURCE_DIR/custom_nodes/ComfyUI-Manager" checkout -q --detach "$COMFYUI_MANAGER_COMMIT"
git -C "$COMFYUI_SOURCE_DIR/custom_nodes/ComfyUI-LTXVideo" checkout -q --detach "$COMFYUI_LTXVIDEO_COMMIT"
git -C "$COMFYUI_SOURCE_DIR/custom_nodes/comfyui-ollama" checkout -q --detach "$COMFYUI_OLLAMA_COMMIT"
echo prepared >> "${MOCK_PREPARE_LOG:?}"
PREPARE
printf '#!/usr/bin/env bash\nexit 0\n' > "$FIXTURE/infra/scripts/backup.sh"
chmod +x "$FIXTURE/infra/scripts/"*.sh
git -C "$FIXTURE" add infra
git -C "$FIXTURE" commit -qm fixture

export MOCK_COMFY_SOURCE="$COMFY_SOURCE"
export MOCK_PREPARE_LOG="$TMP_ROOT/prepare.log"
export MOCK_FIRST_HEALTH=unhealthy
rm -f "$MOCK_HEALTH_COUNT" "$MOCK_PREPARE_LOG"
: > "$MOCK_DOCKER_LOG"
set +e
comfy_output="$(PATH="$MOCK_BIN:$PATH" "$FIXTURE/infra/scripts/update.sh" comfyui 2>&1)"
comfy_rc=$?
set -e
[[ "$comfy_rc" == 1 ]] || fail "ComfyUI deveria retornar erro após health falho e rollback"
[[ -s "$MOCK_PREPARE_LOG" ]] || fail "prepare-media-pipeline não foi executado"
for index in "${!paths[@]}"; do
  [[ "$(git -C "${paths[$index]}" rev-parse HEAD)" == "${old_commits[$index]}" ]] \
    || fail "checkout ComfyUI $index não retornou ao commit anterior"
done
assert_contains "$comfy_output" 'Rollback concluído: comfyui'
pass "ComfyUI aplica lock e restaura os quatro commits em falha"

echo "Todos os testes operacionais passaram."
