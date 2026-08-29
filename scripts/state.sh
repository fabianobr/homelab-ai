#!/usr/bin/env bash
# One-screen infra snapshot. Run at session start before doing ops work.
set -uo pipefail

sep() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

sep "git"
git rev-parse --abbrev-ref HEAD 2>/dev/null
git status -s
echo "--- last 5 commits"
git log --oneline -5

sep "open PRs"
if command -v gh >/dev/null 2>&1; then
  gh pr list --state open 2>/dev/null || echo "(gh falhou)"
else
  echo "(gh não instalado)"
fi

sep "docker ps"
if command -v docker >/dev/null 2>&1; then
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "(docker falhou)"
else
  echo "(docker não instalado)"
fi

sep "systemd user timers"
systemctl --user list-timers --all --no-pager 2>/dev/null || echo "(sem systemd user)"

sep "disk usage"
df -h /
