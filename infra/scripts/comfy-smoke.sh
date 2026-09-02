#!/usr/bin/env bash
# Submit a minimal known-good workflow to the ComfyUI HTTP API and wait for it to
# finish. Proves the container is up, CUDA kernels run, and no OOM occurs.
#
#   infra/scripts/comfy-smoke.sh
#
# Exit 0  = render completed and produced an output.
# Exit 1  = ComfyUI reported an execution error.
# Exit 2  = usage / tooling / unreachable API.
# Exit 3  = timed out waiting for completion.
# Exit 137 = the ComfyUI container was OOM-killed during the render.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
WORKFLOW="${COMFY_SMOKE_WORKFLOW:-$PROJECT_ROOT/infra/docker/comfyui/smoke-workflow.json}"
CKPT_OVERRIDE="${COMFY_SMOKE_CKPT:-}"
TIMEOUT_SECONDS="${COMFY_SMOKE_TIMEOUT:-180}"
POLL_SECONDS="${COMFY_SMOKE_POLL:-3}"
CONTAINER="${COMFY_CONTAINER:-comfyui}"

for bin in curl jq python3; do command -v "$bin" >/dev/null || { echo "need $bin" >&2; exit 2; }; done
[[ -r "$WORKFLOW" ]] || { echo "workflow not readable: $WORKFLOW" >&2; exit 2; }

container_oom_killed() {
  command -v docker >/dev/null || return 1
  [[ "$(docker inspect "$CONTAINER" --format '{{.State.OOMKilled}}' 2>/dev/null)" == "true" ]] && return 0
  [[ "$(docker inspect "$CONTAINER" --format '{{.State.ExitCode}}' 2>/dev/null)" == "137" ]]
}

echo "== comfy-smoke: $COMFY_URL  workflow=$(basename "$WORKFLOW")"

if ! curl -fsS --max-time 10 "$COMFY_URL/system_stats" >/dev/null; then
  echo "[FAIL] ComfyUI API unreachable at $COMFY_URL" >&2
  container_oom_killed && exit 137
  exit 2
fi

graph="$(cat "$WORKFLOW")"
if [[ -n "$CKPT_OVERRIDE" ]]; then
  graph="$(jq --arg c "$CKPT_OVERRIDE" '.["1"].inputs.ckpt_name = $c' <<<"$graph")"
fi
# Drop the human-readable comment key before submission.
graph="$(jq 'del(._comment)' <<<"$graph")"

client_id="comfy-smoke-$$"
resp="$(curl -fsS --max-time 30 -X POST "$COMFY_URL/prompt" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --argjson p "$graph" --arg cid "$client_id" '{prompt:$p, client_id:$cid}')")" || {
    echo "[FAIL] /prompt submission rejected" >&2
    echo "$resp" >&2
    exit 1
  }
prompt_id="$(jq -r '.prompt_id // empty' <<<"$resp")"
[[ -n "$prompt_id" ]] || { echo "[FAIL] no prompt_id in response: $resp" >&2; exit 1; }
echo "   queued prompt_id=$prompt_id"

deadline=$(( SECONDS + TIMEOUT_SECONDS ))
while (( SECONDS < deadline )); do
  sleep "$POLL_SECONDS"

  if ! curl -fsS --max-time 10 "$COMFY_URL/system_stats" >/dev/null; then
    echo "[FAIL] ComfyUI stopped responding mid-render" >&2
    container_oom_killed && { echo "   -> container OOM-killed (exit 137)" >&2; exit 137; }
    exit 1
  fi

  hist="$(curl -fsS --max-time 15 "$COMFY_URL/history/$prompt_id" || echo '{}')"
  [[ "$(jq -r --arg id "$prompt_id" 'has($id)' <<<"$hist")" == "true" ]] || continue

  status="$(jq -r --arg id "$prompt_id" '.[$id].status.status_str // "unknown"' <<<"$hist")"
  completed="$(jq -r --arg id "$prompt_id" '.[$id].status.completed // false' <<<"$hist")"

  if [[ "$status" == "error" ]]; then
    echo "[FAIL] ComfyUI execution error:" >&2
    jq -r --arg id "$prompt_id" '.[$id].status.messages[]? | @json' <<<"$hist" >&2
    exit 1
  fi
  if [[ "$completed" == "true" || "$status" == "success" ]]; then
    outputs="$(jq -r --arg id "$prompt_id" '[.[$id].outputs[]?.images[]?.filename] | length' <<<"$hist")"
    if (( outputs > 0 )); then
      echo "[OK] smoke render completed ($outputs output image(s))"
      exit 0
    fi
    echo "[FAIL] completed but produced no output image" >&2
    exit 1
  fi
done

echo "[FAIL] timed out after ${TIMEOUT_SECONDS}s waiting for prompt_id=$prompt_id" >&2
container_oom_killed && exit 137
exit 3
