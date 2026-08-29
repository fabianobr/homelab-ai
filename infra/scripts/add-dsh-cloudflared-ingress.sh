#!/usr/bin/env bash
set -euo pipefail

# Acrescenta o ingress do DeepSeek Harness antes do catch-all do Tunnel.
# Execute somente depois de criar a aplicação Cloudflare Access para o hostname.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo env DSH_PUBLIC_HOSTNAME=dsh.example.com bash infra/scripts/add-dsh-cloudflared-ingress.sh" >&2
  exit 1
fi

DSH_PUBLIC_HOSTNAME="${DSH_PUBLIC_HOSTNAME:?set DSH_PUBLIC_HOSTNAME}"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
DSH_ORIGIN_URL="${DSH_ORIGIN_URL:-http://localhost:3081}"

if [[ ! "${DSH_PUBLIC_HOSTNAME}" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "DSH_PUBLIC_HOSTNAME deve ser um hostname simples, sem espaços ou caracteres YAML." >&2
  exit 1
fi

if [[ ! "${DSH_ORIGIN_URL}" =~ ^http://localhost:[0-9]{2,5}$ ]]; then
  echo "DSH_ORIGIN_URL deve apontar para uma porta local HTTP." >&2
  exit 1
fi

if [[ ! -f "${CLOUDFLARED_CONFIG}" ]]; then
  echo "Config do cloudflared não encontrada em ${CLOUDFLARED_CONFIG}." >&2
  exit 1
fi

if grep -Fq "hostname: ${DSH_PUBLIC_HOSTNAME}" "${CLOUDFLARED_CONFIG}"; then
  echo "Ingress de ${DSH_PUBLIC_HOSTNAME} já existe; nenhuma alteração aplicada."
  cloudflared tunnel --config "${CLOUDFLARED_CONFIG}" ingress validate
  exit 0
fi

config_dir="$(dirname "${CLOUDFLARED_CONFIG}")"
candidate="$(mktemp "${config_dir}/config.yml.dsh.XXXXXX")"
rollback="$(mktemp "${config_dir}/config.yml.rollback.XXXXXX")"
trap 'rm -f "${candidate}" "${rollback}"' EXIT

awk -v hostname="${DSH_PUBLIC_HOSTNAME}" -v origin="${DSH_ORIGIN_URL}" '
  $0 == "  - service: http_status:404" && !inserted {
    print "  - hostname: " hostname
    print "    service: " origin
    print ""
    inserted = 1
  }
  { print }
  END {
    if (!inserted) {
      exit 42
    }
  }
' "${CLOUDFLARED_CONFIG}" >"${candidate}" || {
  status=$?
  if [[ "${status}" -eq 42 ]]; then
    echo "Catch-all 'service: http_status:404' não encontrado; configuração não alterada." >&2
  fi
  exit "${status}"
}

cp --preserve=mode,ownership,timestamps "${CLOUDFLARED_CONFIG}" "${rollback}"
install -m 0644 "${candidate}" "${CLOUDFLARED_CONFIG}"

if ! cloudflared tunnel --config "${CLOUDFLARED_CONFIG}" ingress validate; then
  install -m 0644 "${rollback}" "${CLOUDFLARED_CONFIG}"
  echo "Ingress inválido; configuração anterior restaurada." >&2
  exit 1
fi

systemctl restart cloudflared
echo "Ingress ${DSH_PUBLIC_HOSTNAME} -> ${DSH_ORIGIN_URL} aplicado e cloudflared reiniciado."
