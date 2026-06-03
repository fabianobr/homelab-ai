# Cloudflare Tunnel e Access

## Objetivo

Publicar o Open WebUI via domínio sem abrir portas no roteador.

Exemplo:

```text
https://ia.seudominio.com
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

## Segurança obrigatória

Configure Cloudflare Access antes de usar publicamente.

Política recomendada:

- Permitir apenas seu e-mail
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
