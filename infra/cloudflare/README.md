# Cloudflare Tunnel e Access

## Objetivo

Publicar ComfyUI, n8n e DeepSeek Harness via domínio sem abrir portas no roteador.

Exemplo:

```text
https://media.example.com
https://flow.example.com
https://dsh.example.com
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
cloudflared tunnel route dns homelab-ai media.example.com
cloudflared tunnel route dns homelab-ai flow.example.com
```

Rodar túnel apontando para Open WebUI:

```bash
cloudflared tunnel --url http://localhost:3000 run homelab-ai
```

## Configuração deste host

O tunnel system-wide deve apontar ComfyUI, n8n e DeepSeek Harness:

```yaml
ingress:
  - hostname: media.example.com
    service: http://localhost:8188
  - hostname: flow.example.com
    service: http://localhost:5678
  - hostname: dsh.example.com
    service: http://localhost:3081
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
- n8n
- Docker
- SSH

ComfyUI e DeepSeek Harness são publicados apenas pelo Tunnel e devem ficar protegidos por aplicações Cloudflare Access próprias. Crie a aplicação Access antes de adicionar a rota do Harness; ele executa comandos e não tem autenticação remota própria.
