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
  -p 100.74.179.70:3000:8080 \
  -v open-webui:/app/backend/data \
  -e "WEBUI_NAME=Fabiano AI" \
  -e ENABLE_SIGNUP=false \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:1234/v1 \
  -e OPENAI_API_KEY=lm-studio \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

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

O container publica em loopback para Cloudflare:

```text
127.0.0.1:3000
```

E no IP Tailscale para acesso privado:

```text
100.74.179.70:3000
```

O acesso remoto público deve passar pelo Cloudflare Access:

```text
https://ai.example.com
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

Antes do primeiro chat, carregue no LM Studio um modelo de conversa. No momento da validacao inicial, o endpoint `/v1/models` listava apenas um modelo de embedding.
