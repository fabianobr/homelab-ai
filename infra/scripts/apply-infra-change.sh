#!/usr/bin/env bash
# Self-verifying wrapper for a ComfyUI infra change (Dockerfile / compose memory
# limit / command / mount).
#
# Contract: make your edit in the working tree FIRST, then run this with a short
# description. It will:
#   1. tag the running comfyui image as  known-good-<epoch>
#   2. show the infra diff being applied
#   3. rebuild + restart the comfyui service from the current tree
#   4. run gpu-health.sh --strict, then comfy-smoke.sh
#   5. if EITHER fails: restore the known-good image tag, `git checkout` the
#      infra files, restart, print the diff that was rolled back, exit 1
#
#   infra/scripts/apply-infra-change.sh "raise comfyui memory limit to 30g" [--yes]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="infra/docker/docker-compose.yml"
ENV_FILE="${HOMELAB_ENV_FILE:-$PROJECT_ROOT/homelab.env}"
PROFILE="${COMFY_PROFILE:-media-pipeline}"
CONTAINER="${COMFY_CONTAINER:-comfyui}"
SERVICE="comfyui"
# Paths whose changes this harness is responsible for verifying / rolling back.
INFRA_PATHS=("$COMPOSE_FILE" "infra/docker/comfyui")

[[ $# -ge 1 ]] || { echo "usage: $0 \"<description>\" [--yes]" >&2; exit 2; }
DESCRIPTION="$1"; shift
ASSUME_YES=0
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=1

for bin in docker git jq; do command -v "$bin" >/dev/null || { echo "need $bin" >&2; exit 2; }; done
[[ -f "$ENV_FILE" ]] || { echo "env file not found: $ENV_FILE" >&2; exit 2; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile "$PROFILE" "$@"; }

echo "== apply-infra-change: $DESCRIPTION"

# --- 0. the change under test -------------------------------------------------
diff_text="$(git diff -- "${INFRA_PATHS[@]}" || true)"
if [[ -z "$diff_text" ]]; then
  echo "no uncommitted changes under: ${INFRA_PATHS[*]}" >&2
  echo "make your infra edit first, then re-run." >&2
  exit 2
fi
echo "-- change under test --"
git --no-pager diff --stat -- "${INFRA_PATHS[@]}"
echo

if [[ $ASSUME_YES -ne 1 ]]; then
  read -r -p "rebuild + restart '$SERVICE' and verify? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted."; exit 2; }
fi

# --- 1. snapshot the known-good image ---------------------------------------
KNOWN_GOOD="known-good-$(date +%s)"
current_image="$(docker inspect "$CONTAINER" --format '{{.Config.Image}}' 2>/dev/null || true)"
if [[ -z "$current_image" ]]; then
  echo "container '$CONTAINER' is not running; cannot snapshot a known-good image." >&2
  echo "start it first: dc up -d $SERVICE" >&2
  exit 2
fi
docker tag "$current_image" "$KNOWN_GOOD"
echo "-- tagged known-good image: $KNOWN_GOOD  (from $current_image)"

restore() {
  echo
  echo "!! verification FAILED -- rolling back"
  git checkout -- "${INFRA_PATHS[@]}" || true
  docker tag "$KNOWN_GOOD" "$current_image" || true
  dc up -d "$SERVICE" || true
  # wait for it to come back
  for _ in $(seq 1 20); do
    curl -fsS --max-time 5 "http://127.0.0.1:8188/system_stats" >/dev/null 2>&1 && break
    sleep 3
  done
  echo
  echo "-- rolled back the following change --"
  echo "$diff_text"
  echo
  echo "known-good image kept as: $KNOWN_GOOD"
  exit 1
}

# --- 2. rebuild + restart ---------------------------------------------------
echo "-- building $SERVICE"
dc build "$SERVICE" || restore
echo "-- restarting $SERVICE"
dc up -d "$SERVICE" || restore

echo "-- waiting for API"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "http://127.0.0.1:8188/system_stats" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
[[ $ok -eq 1 ]] || restore

# --- 3. verify ------------------------------------------------------------
echo "-- gpu-health"
"$PROJECT_ROOT/infra/scripts/gpu-health.sh" --strict || restore
echo "-- comfy-smoke"
smoke_rc=0
"$PROJECT_ROOT/infra/scripts/comfy-smoke.sh" || smoke_rc=$?
if [[ $smoke_rc -ne 0 ]]; then
  echo "comfy-smoke exit $smoke_rc$( [[ $smoke_rc -eq 137 ]] && echo '  (OOM-killed)' )"
  restore
fi

echo
echo "== PASS: '$DESCRIPTION' verified (gpu-health + comfy-smoke green)"
echo "   known-good snapshot: $KNOWN_GOOD  (delete with: docker rmi $KNOWN_GOOD)"
echo "   commit the change when ready."
