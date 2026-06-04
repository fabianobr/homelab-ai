#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo bash scripts/bootstrap-host.sh" >&2
  exit 1
fi

PROJECT_USER="${PROJECT_USER:-fabiano}"

echo "== Atualizando pacotes base =="
apt-get update
apt-get install -y \
  curl \
  ca-certificates \
  fuse

if ! apt-cache policy tailscale | grep -q 'Candidate:'; then
  echo "== Configurando repositorio oficial do Tailscale =="
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/resolute.noarmor.gpg \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  chmod 0644 /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/resolute.tailscale-keyring.list \
    -o /etc/apt/sources.list.d/tailscale.list
  chmod 0644 /etc/apt/sources.list.d/tailscale.list
  apt-get update
fi

apt-get install -y \
  docker-compose-v2 \
  nvidia-container-toolkit \
  tailscale

if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
  echo "== Instalando driver NVIDIA recomendado =="
  apt-get install -y nvidia-driver-580
else
  echo "== Driver NVIDIA ja funcional; mantendo versao instalada =="
fi

echo "== Configurando Docker para NVIDIA =="
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo "== Garantindo acesso do usuario ao Docker =="
usermod -aG docker "${PROJECT_USER}"

echo "== Habilitando servicos =="
systemctl enable --now docker
systemctl enable --now tailscaled
systemctl enable --now cloudflared || true

echo
echo "Bootstrap concluido."
echo "Reinicie o host antes de validar GPU, FUSE e grupos:"
echo "  sudo reboot"
