#!/usr/bin/env bash
set -euo pipefail

# Acrescenta uma rota por PATH (não por hostname novo) pro serviço dsh-files,
# sob o mesmo hostname já publicado do DeepSeek Harness — assim reusa o mesmo
# app/policy de Cloudflare Access, sem precisar de um segundo.
#
# Pré-requisito: o ingress de DSH_PUBLIC_HOSTNAME já existe (instalado por
# add-dsh-cloudflared-ingress.sh) e está protegido por Access.
#
# A regra de path é inserida ANTES da regra sem path do mesmo hostname — o
# cloudflared casa de cima pra baixo e para na primeira regra que bate, então
# a ordem importa.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo env DSH_PUBLIC_HOSTNAME=dsh.example.com bash infra/scripts/add-dsh-files-path-ingress.sh" >&2
  exit 1
fi

DSH_PUBLIC_HOSTNAME="${DSH_PUBLIC_HOSTNAME:?set DSH_PUBLIC_HOSTNAME (o hostname do DSH web já publicado)}"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
DSH_FILES_PATH="${DSH_FILES_PATH:-files}"
DSH_FILES_ORIGIN_URL="${DSH_FILES_ORIGIN_URL:-http://localhost:3082}"

if [[ ! "${DSH_PUBLIC_HOSTNAME}" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "DSH_PUBLIC_HOSTNAME deve ser um hostname simples, sem espaços ou caracteres YAML." >&2
  exit 1
fi

if [[ ! "${DSH_FILES_PATH}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "DSH_FILES_PATH deve ser um único segmento simples (sem barras)." >&2
  exit 1
fi

if [[ ! "${DSH_FILES_ORIGIN_URL}" =~ ^http://localhost:[0-9]{2,5}$ ]]; then
  echo "DSH_FILES_ORIGIN_URL deve apontar para uma porta local HTTP." >&2
  exit 1
fi

if [[ ! -f "${CLOUDFLARED_CONFIG}" ]]; then
  echo "Config do cloudflared não encontrada em ${CLOUDFLARED_CONFIG}." >&2
  exit 1
fi

if ! grep -Fq "hostname: ${DSH_PUBLIC_HOSTNAME}" "${CLOUDFLARED_CONFIG}"; then
  echo "Nenhum ingress para ${DSH_PUBLIC_HOSTNAME} encontrado; rode add-dsh-cloudflared-ingress.sh primeiro." >&2
  exit 1
fi

path_regex="^/${DSH_FILES_PATH}(\$|/.*)"
if grep -Fq "path: ${path_regex}" "${CLOUDFLARED_CONFIG}"; then
  echo "Rota de path /${DSH_FILES_PATH} para ${DSH_PUBLIC_HOSTNAME} já existe; nenhuma alteração aplicada."
  cloudflared tunnel --config "${CLOUDFLARED_CONFIG}" ingress validate
  exit 0
fi

config_dir="$(dirname "${CLOUDFLARED_CONFIG}")"
candidate="$(mktemp "${config_dir}/config.yml.dshfiles.XXXXXX")"
rollback="$(mktemp "${config_dir}/config.yml.rollback.XXXXXX")"
trap 'rm -f "${candidate}" "${rollback}"' EXIT

awk -v hostname="${DSH_PUBLIC_HOSTNAME}" -v path_regex="${path_regex}" -v origin="${DSH_FILES_ORIGIN_URL}" '
  $0 == "  - hostname: " hostname && !inserted {
    print "  - hostname: " hostname
    print "    path: " path_regex
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
    echo "Linha 'hostname: ${DSH_PUBLIC_HOSTNAME}' não encontrada no formato esperado; configuração não alterada." >&2
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
echo "Rota https://${DSH_PUBLIC_HOSTNAME}/${DSH_FILES_PATH}/ -> ${DSH_FILES_ORIGIN_URL} aplicada e cloudflared reiniciado."
