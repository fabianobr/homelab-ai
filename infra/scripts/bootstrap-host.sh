#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo bash scripts/bootstrap-host.sh" >&2
  exit 1
fi

PROJECT_USER="${PROJECT_USER:-fabiano}"

if ! id -u "${PROJECT_USER}" >/dev/null 2>&1; then
  echo "Usuario '${PROJECT_USER}' nao existe. Execute com PROJECT_USER=<usuario> sudo -E bash scripts/bootstrap-host.sh." >&2
  exit 1
fi

echo "== Atualizando pacotes base =="
apt-get update
apt-get install -y \
  curl \
  ca-certificates \
  fuse

apt-get install -y \
  docker.io \
  docker-compose-v2 \
  nvidia-container-toolkit

if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
  echo "== Instalando driver NVIDIA recomendado =="
  apt-get install -y nvidia-driver-580
else
  echo "== Driver NVIDIA ja funcional; mantendo versao instalada =="
fi

echo "== Configurando Docker para NVIDIA =="
if ! nvidia-ctk runtime configure --runtime=docker; then
  echo "Falha ao configurar runtime NVIDIA no Docker. Verifique o driver NVIDIA; o host pode precisar de reboot apos a instalacao." >&2
  exit 1
fi
systemctl restart docker
systemctl enable --now docker

if ! docker info >/dev/null 2>&1; then
  echo "Docker foi instalado, mas o daemon nao esta respondendo. Verifique systemctl status docker." >&2
  exit 1
fi

docker volume create open-webui >/dev/null

echo "== Garantindo acesso do usuario ao Docker =="
usermod -aG docker "${PROJECT_USER}"

echo "== Habilitando servicos =="
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared nao encontrado. Instale e configure o Cloudflare Tunnel antes de publicar o Open WebUI." >&2
  exit 1
fi

if ! systemctl enable --now cloudflared; then
  echo "Falha ao habilitar cloudflared. Verifique /etc/cloudflared/config.yml e systemctl status cloudflared." >&2
  exit 1
fi

echo
echo "Bootstrap concluido."
echo "Reinicie o host antes de validar GPU, FUSE e grupos:"
echo "  sudo reboot"
