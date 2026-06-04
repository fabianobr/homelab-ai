#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo bash scripts/apply-system-config.sh" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Configurando Ollama Snap =="
snap set ollama host=0.0.0.0:11434
systemctl restart snap.ollama.listener.service

echo "== Restringindo Ollama ao host e Docker =="
install -m 0755 /dev/stdin /usr/local/sbin/homelab-ai-ollama-firewall.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

iptables -N HOMELAB_AI_OLLAMA 2>/dev/null || true
iptables -F HOMELAB_AI_OLLAMA
iptables -A HOMELAB_AI_OLLAMA -i lo -p tcp --dport 11434 -j ACCEPT
iptables -A HOMELAB_AI_OLLAMA -i docker0 -p tcp --dport 11434 -j ACCEPT
iptables -A HOMELAB_AI_OLLAMA -i br+ -p tcp --dport 11434 -j ACCEPT
iptables -A HOMELAB_AI_OLLAMA -p tcp --dport 11434 -j DROP

if ! iptables -C INPUT -p tcp --dport 11434 -j HOMELAB_AI_OLLAMA 2>/dev/null; then
  iptables -I INPUT 1 -p tcp --dport 11434 -j HOMELAB_AI_OLLAMA
fi
EOF

install -m 0644 /dev/stdin /etc/systemd/system/homelab-ai-ollama-firewall.service <<'EOF'
[Unit]
Description=Restrict homelab-ai Ollama API to local host and Docker networks
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/homelab-ai-ollama-firewall.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now homelab-ai-ollama-firewall.service

echo "== Configurando Cloudflare Tunnel =="
install -m 0644 "${PROJECT_ROOT}/infra/cloudflare/config.yml" /etc/cloudflared/config.yml
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
systemctl restart cloudflared

echo
echo "Configuracao de sistema aplicada."
echo "Valide com: bash scripts/healthcheck.sh"
