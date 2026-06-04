# Cloudflare Tunnel e Access

## Objetivo

Publicar Open WebUI, ComfyUI e n8n via domínio sem abrir portas no roteador.

Exemplo:

```text
https://chat.ai.example.com
https://media.ai.example.com
https://flow.ai.example.com
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
cloudflared tunnel route dns homelab-ai chat.ai.example.com
cloudflared tunnel route dns homelab-ai media.ai.example.com
cloudflared tunnel route dns homelab-ai flow.ai.example.com
```

Rodar túnel apontando para Open WebUI:

```bash
cloudflared tunnel --url http://localhost:3000 run homelab-ai
```

## Configuração deste host

O tunnel system-wide deve apontar Open WebUI e ComfyUI:

```yaml
ingress:
  - hostname: chat.ai.example.com
    service: http://localhost:3000
  - hostname: media.ai.example.com
    service: http://localhost:8188
  - hostname: flow.ai.example.com
    service: http://localhost:5678
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

- Ollama
- LM Studio
- n8n
- Docker
- SSH

ComfyUI e publicado apenas pelo tunnel e deve ficar protegido por Cloudflare Access.
