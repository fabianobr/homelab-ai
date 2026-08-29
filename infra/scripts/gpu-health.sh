#!/usr/bin/env bash
# Capture a GPU / CUDA health snapshot as JSON: nvidia-smi VRAM, the ComfyUI
# container's torch + CUDA runtime versions, and whether the NVRTC builtins
# library is present. Used as the first gate in apply-infra-change.sh and as a
# before/after diff when chasing CUDA/NVRTC load failures.
#
#   infra/scripts/gpu-health.sh [> snapshot.json]
#
# Always exits 0 with a JSON document (fields are null when a probe fails), so
# callers can diff two snapshots. Use --strict to exit 1 when any probe fails.
set -euo pipefail

CONTAINER="${COMFY_CONTAINER:-comfyui}"
STRICT=0
[[ "${1:-}" == "--strict" ]] && STRICT=1

fail=0

# --- host GPU via nvidia-smi ---
gpu_json='null'
if command -v nvidia-smi >/dev/null; then
  gpu_json="$(nvidia-smi \
    --query-gpu=name,memory.total,memory.used,memory.free,driver_version \
    --format=csv,noheader,nounits 2>/dev/null | head -n1 | \
    awk -F', *' '{printf "{\"name\":\"%s\",\"mem_total_mib\":%s,\"mem_used_mib\":%s,\"mem_free_mib\":%s,\"driver\":\"%s\"}",$1,$2,$3,$4,$5}')"
  [[ -n "$gpu_json" ]] || { gpu_json='null'; fail=1; }
else
  fail=1
fi

# --- ComfyUI container: torch + CUDA runtime + NVRTC builtins ---
torch_ver='null'; torch_cuda='null'; cap='null'; cuda_avail='null'; nvrtc='null'
if command -v docker >/dev/null && docker inspect "$CONTAINER" >/dev/null 2>&1; then
  probe="$(docker exec -i "$CONTAINER" python - <<'PY' 2>/dev/null || true
import json
o = {}
try:
    import torch
    o["torch"] = torch.__version__
    o["torch_cuda"] = torch.version.cuda
    o["cuda_available"] = bool(torch.cuda.is_available())
    o["device_capability"] = ".".join(map(str, torch.cuda.get_device_capability())) if torch.cuda.is_available() else None
except Exception as e:
    o["torch_error"] = repr(e)
print(json.dumps(o))
PY
)"
  if [[ -n "$probe" ]]; then
    torch_ver="$(jq -r '.torch // "null"' <<<"$probe" 2>/dev/null || echo null)"
    torch_cuda="$(jq -r '.torch_cuda // "null"' <<<"$probe" 2>/dev/null || echo null)"
    cap="$(jq -r '.device_capability // "null"' <<<"$probe" 2>/dev/null || echo null)"
    cuda_avail="$(jq -r '.cuda_available // "null"' <<<"$probe" 2>/dev/null || echo null)"
  else
    fail=1
  fi
  # libnvrtc-builtins ships with the CUDA toolkit / torch wheel; its absence is a
  # classic "no kernel image" / NVRTC compile failure.
  if docker exec "$CONTAINER" sh -c 'ldconfig -p 2>/dev/null | grep -qi "libnvrtc-builtins" || find / -name "libnvrtc-builtins*" -print -quit 2>/dev/null | grep -q .'; then
    nvrtc='true'
  else
    nvrtc='false'; fail=1
  fi
else
  fail=1
fi

quote() { [[ "$1" == "null" || "$1" == "true" || "$1" == "false" ]] && printf '%s' "$1" || printf '"%s"' "$1"; }

cat <<JSON
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "container": "$CONTAINER",
  "gpu": $gpu_json,
  "torch_version": $(quote "$torch_ver"),
  "torch_cuda_runtime": $(quote "$torch_cuda"),
  "cuda_available": $(quote "$cuda_avail"),
  "device_capability": $(quote "$cap"),
  "libnvrtc_builtins_present": $nvrtc,
  "all_probes_ok": $( [[ $fail -eq 0 ]] && echo true || echo false )
}
JSON

if [[ $STRICT -eq 1 && $fail -ne 0 ]]; then exit 1; fi
exit 0
