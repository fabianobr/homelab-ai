---
name: infra-change
description: Use for ANY change to the ComfyUI/Docker stack — Dockerfile, a compose memory/cpu/command/mount value, or a systemd unit. Mandates the self-verifying harness; no fix is "done" without a passing comfy-smoke run.
---

Any edit to `infra/docker/comfyui/Dockerfile`, the `comfyui` service in
`infra/docker/docker-compose.yml` (memory / memswap / cpus / command / devices /
volumes), or a related systemd unit MUST go through the harness below. No
exceptions for "obvious" or "one-line" changes — OOM and CUDA/NVRTC regressions
look obvious in hindsight.

## Procedure

1. **Snapshot before.** Run `infra/scripts/gpu-health.sh > /tmp/gpu-before.json`.
   Read it. Note torch version, `torch_cuda_runtime`, `device_capability` (must
   stay `12.0`), and `libnvrtc_builtins_present`.
2. **Make the edit** in the working tree. One logical change at a time.
3. **Apply + verify:** `infra/scripts/apply-infra-change.sh "<description>" --yes`.
   It tags the running image `known-good-<epoch>`, rebuilds + restarts `comfyui`,
   then runs `gpu-health.sh --strict` and `comfy-smoke.sh`. If **either** fails it
   restores the known-good image, `git checkout`s the infra files, restarts, and
   prints the rolled-back diff.
4. **On PASS:** diff `/tmp/gpu-before.json` against a fresh `gpu-health.sh` run.
   Any unexpected change to torch/CUDA/capability/NVRTC is a regression even if
   the smoke passed — investigate before committing.
5. **On FAIL:** the stack is already rolled back. Read the printed diff and the
   failing script output. Consult `../media-meme-pipeline/docs/runbooks/comfyui.md`
   (exit 137 → memory ceiling; NVRTC/`no kernel image` → CUDA mismatch). Form a
   new hypothesis, go back to step 2.
6. **Commit** only after a PASS, and only the verified change.

## Hard rules

- Never report an infra fix as complete, working, or merged without a
  `comfy-smoke.sh` exit 0 in this session. Paste the smoke output.
- Never edit-and-`docker compose up` by hand to "just test something" — that
  leaves no known-good image to roll back to.
- Never resolve a CUDA/NVRTC error by adding a second torch index or pinning
  `nvidia-*` wheels in `requirements.txt`. Change the base image tag and re-run
  the harness.
- `memswap_limit` stays finite. Unlimited swap has taken down the host session.
- If the GPU is busy (a long ComfyUI render or Ollama holding VRAM), wait or
  stop that workload first — a smoke failure caused by contention is a false
  negative that will trigger a needless rollback.
