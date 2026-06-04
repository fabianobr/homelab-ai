# Open WebUI

## Papel

Interface principal do laboratório.

## Porta

```text
3000
```

## Subir via Docker

```bash
cd docker
docker compose up -d open-webui
```

Enquanto o plugin `docker compose` nao estiver instalado no host, o container pode ser mantido pelo Docker direto:

```bash
docker run -d --name open-webui --restart unless-stopped \
  -p 127.0.0.1:3000:8080 \
  -v open-webui:/app/backend/data \
  -e "WEBUI_NAME=Home Lab AI" \
  -e ENABLE_SIGNUP=false \
  -e WEBUI_AUTH_TRUSTED_EMAIL_HEADER=Cf-Access-Authenticated-User-Email \
  -e ENABLE_OPENAI_API=True \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:1234/v1 \
  -e OPENAI_API_KEY=lm-studio \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

## Conectar com Ollama

Backend Ollama:

```text
http://host.docker.internal:11434
```

Ollama precisa escutar em `0.0.0.0:11434` no host para ser acessivel a partir do container Docker. No Snap, aplique:

```bash
sudo snap set ollama host=0.0.0.0:11434
sudo systemctl restart snap.ollama.listener.service
```

Nao publique essa porta no Cloudflare nem no roteador.

## Conectar com LM Studio

Provider OpenAI-compatible:

```text
http://host.docker.internal:1234/v1
```

API key:

```text
lm-studio
```

## Publicação

O container publica apenas em loopback para Cloudflare:

```text
127.0.0.1:3000
```

O acesso remoto público deve passar pelo Cloudflare Access:

```text
https://chat.ai.example.com
```

## Uso

- Chat
- Histórico
- Upload de arquivos
- RAG
- Ferramentas
- Integrações

## Estado atual

Open WebUI esta rodando em container Docker com volume persistente `open-webui`.

O container acessa o LM Studio em:

```text
http://host.docker.internal:1234/v1
```

O container acessa o Ollama em:

```text
http://host.docker.internal:11434
```

Antes do primeiro chat, carregue no LM Studio um modelo de conversa. No momento da validacao inicial, o endpoint `/v1/models` listava apenas um modelo de embedding.
