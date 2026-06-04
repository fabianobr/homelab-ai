# Cloudflare Tunnel e Access

## Objetivo

Publicar o Open WebUI via domínio sem abrir portas no roteador.

Exemplo:

```text
https://ai.example.com
```

## Instalação básica

```bash
sudo apt install cloudflared
```

Login:

```bash
cloudflared tunnel login
```

Criar túnel:

```bash
cloudflared tunnel create homelab-ai
```

Criar rota DNS:

```bash
cloudflared tunnel route dns homelab-ai ia.seudominio.com
```

Rodar túnel apontando para Open WebUI:

```bash
cloudflared tunnel --url http://localhost:3000 run homelab-ai
```

## Configuração deste host

O tunnel system-wide deve apontar somente o Open WebUI:

```yaml
ingress:
  - hostname: ai.example.com
    service: http://localhost:3000
  - service: http_status:404
```

## Segurança obrigatória

Configure Cloudflare Access antes de usar publicamente.

Política recomendada:

- Permitir apenas seu e-mail
- E-mail permitido neste homelab: `user@example.com`
- Exigir MFA
- Bloquear países desnecessários
- Ativar rate limiting
- Ativar WAF

## Não publicar diretamente

Não publique:

- LM Studio
- ComfyUI
- n8n
- Docker
- SSH
