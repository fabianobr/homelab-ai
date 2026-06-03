# Tailscale

## Objetivo

Acesso privado remoto ao servidor `homelab`.

## Instalar

```bash
curl -fsSL https://tailscale.com/install.sh | sh
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

## Recomendação

Use Tailscale como acesso padrão no dia a dia.

Use Cloudflare apenas quando quiser acessar por domínio ou compartilhar acesso controlado.
