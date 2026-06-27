#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECTED_TAG=""
EXPECTED_CONTRACT="1"
ALLOW_UNSUPPORTED=false
UNSUPPORTED=false

usage() {
  echo "Usage: $0 --expected-tag vMAJOR.MINOR.PATCH [--expected-contract N] [--allow-unsupported]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-tag) EXPECTED_TAG="${2:-}"; shift 2 ;;
    --expected-contract) EXPECTED_CONTRACT="${2:-}"; shift 2 ;;
    --allow-unsupported) ALLOW_UNSUPPORTED=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "${EXPECTED_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "[MISSING] --expected-tag must be an exact SemVer tag, for example v1.0.0" >&2
  exit 2
fi

actual_contract="$(awk '$1 == "contract_version:" {print $2; exit}' "${ROOT}/infra/media-pipeline/contract.yaml")"
actual_tag="$(git -C "${ROOT}" describe --tags --exact-match HEAD 2>/dev/null || true)"
dirty="$(git -C "${ROOT}" status --porcelain --untracked-files=normal)"

fail() {
  if [[ "${ALLOW_UNSUPPORTED}" == true ]]; then
    echo "[OPTIONAL] $1 (--allow-unsupported enabled)" >&2
    UNSUPPORTED=true
  else
    echo "[MISSING] $1" >&2
    exit 1
  fi
}

[[ "${actual_contract}" == "${EXPECTED_CONTRACT}" ]] || fail "contract ${actual_contract:-absent}; expected ${EXPECTED_CONTRACT}"
[[ "${actual_tag}" == "${EXPECTED_TAG}" ]] || fail "homelab checkout is ${actual_tag:-not at an exact tag}; expected ${EXPECTED_TAG}"
[[ -z "${dirty}" ]] || fail "homelab worktree has local changes; use a clean checkout of ${EXPECTED_TAG}"

if [[ "${UNSUPPORTED}" == true ]]; then
  echo "[OPTIONAL] unsupported homelab accepted for development"
else
  echo "[OK] homelab ${EXPECTED_TAG}, contract ${EXPECTED_CONTRACT}, clean worktree"
fi
