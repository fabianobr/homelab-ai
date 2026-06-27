#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

fail=0

check_absent() {
  local label="$1"
  local pattern="$2"

  if rg -n -i --hidden \
    --glob '!.git/**' \
    --glob '!.tools/**' \
    --glob '!homelab.env' \
    --glob '!.public-denylist.local' \
    --glob '!PUBLIC_REPO_SECURITY_REVIEW.md' \
    --glob '!infra/scripts/check-public-ready.sh' \
    "${pattern}" .; then
    echo "[FAIL] ${label}"
    fail=1
  else
    echo "[OK] ${label}"
  fi
}

echo "== Public repo readiness checks =="

check_absent "host-specific home paths are absent" '/home/[a-z0-9_-]+/(AI|homelab-ai)'
check_absent "real Cloudflare credential UUID paths are absent" '/etc/cloudflared/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json'
check_absent "private key material is absent" 'BEGIN [A-Z ]+PRIVATE KEY'
check_absent "likely token values are absent" '(bearer[[:space:]]+[a-z0-9._-]{20,}|(api[_-]?key|client[_-]?secret|auth[_-]?token)[[:space:]]*[:=][[:space:]]*["'\'']?[a-z0-9._-]{20,})'

if [[ -f .public-denylist.local ]]; then
  while IFS= read -r pattern; do
    [[ -z "${pattern}" || "${pattern}" =~ ^[[:space:]]*# ]] && continue
    check_absent "local denylist pattern is absent: ${pattern}" "${pattern}"
  done < .public-denylist.local
else
  echo "[OK] optional .public-denylist.local is absent"
fi

if [[ -f infra/cloudflare/config.yml ]]; then
  echo "[FAIL] real Cloudflare config path is versionable; use infra/cloudflare/config.example.yml"
  fail=1
else
  echo "[OK] real Cloudflare config path is absent"
fi

if [[ -f infra/cloudflare/config.example.yml ]]; then
  echo "[OK] Cloudflare example config exists"
else
  echo "[FAIL] Cloudflare example config missing"
  fail=1
fi

if [[ -f .env.example ]]; then
  echo "[OK] .env.example exists"
else
  echo "[FAIL] .env.example missing"
  fail=1
fi

if docker compose --env-file .env.media-pipeline.example \
  -f infra/docker/docker-compose.yml \
  --profile optional --profile interactive --profile media-pipeline config >/tmp/homelab-ai-compose-config.yml; then
  echo "[OK] docker compose config renders"
else
  echo "[FAIL] docker compose config failed"
  fail=1
fi

if rg -n 'image: ollama/ollama:(latest|main|main-stable)(@|$)' infra/docker/docker-compose.yml; then
  echo "[FAIL] mutable container image tag is present in the media-pipeline profile"
  fail=1
else
  echo "[OK] mutable container image tags are absent from the media-pipeline profile"
fi

for port in 11434 3000 8188 5678; do
  if rg -n -U "host_ip: 127\\.0\\.0\\.1\\n\\s+target: [0-9]+\\n\\s+published: \"${port}\"" /tmp/homelab-ai-compose-config.yml >/dev/null; then
    echo "[OK] published port ${port} is bound to 127.0.0.1"
  else
    echo "[FAIL] published port ${port} is not bound to 127.0.0.1"
    fail=1
  fi
done

GITLEAKS_BIN="${GITLEAKS_BIN:-}"
if [[ -z "${GITLEAKS_BIN}" ]]; then
  if command -v gitleaks >/dev/null 2>&1; then
    GITLEAKS_BIN="$(command -v gitleaks)"
  elif [[ -x .tools/gitleaks-pkg/usr/bin/gitleaks ]]; then
    GITLEAKS_BIN=".tools/gitleaks-pkg/usr/bin/gitleaks"
  fi
fi

if [[ -n "${GITLEAKS_BIN}" ]]; then
  if "${GITLEAKS_BIN}" detect --no-git --source . --redact >/tmp/homelab-ai-gitleaks-worktree.log; then
    echo "[OK] gitleaks worktree scan found no leaks"
  else
    cat /tmp/homelab-ai-gitleaks-worktree.log
    echo "[FAIL] gitleaks worktree scan found leaks"
    fail=1
  fi

  if "${GITLEAKS_BIN}" detect --source . --redact >/tmp/homelab-ai-gitleaks-history.log; then
    echo "[OK] gitleaks history scan found no leaks"
  else
    cat /tmp/homelab-ai-gitleaks-history.log
    echo "[FAIL] gitleaks history scan found leaks"
    fail=1
  fi
else
  echo "[SKIP] gitleaks not found"
fi

exit "${fail}"
