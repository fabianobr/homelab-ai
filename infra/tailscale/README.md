# Tailscale

## Objetivo

Acesso privado remoto ao servidor `homelab`.

## Instalar

```bash
sudo install -d -m 0755 /usr/share/keyrings
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/resolute.noarmor.gpg | \
  sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/resolute.tailscale-keyring.list | \
  sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
sudo apt-get update
sudo apt-get install -y tailscale
```

## Conectar

```bash
sudo tailscale up
```

## Testar

```bash
tailscale status
```

Depois acesse:

```text
http://IP_TAILSCALE:3000
```

Neste homelab, o Tailscale deve ser o acesso remoto privado padrão. O Cloudflare fica reservado ao domínio autenticado `ai.example.com`.

## Recomendação

Use Tailscale como acesso padrão no dia a dia.

Use Cloudflare apenas quando quiser acessar por domínio ou compartilhar acesso controlado.
