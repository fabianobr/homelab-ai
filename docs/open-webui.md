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

## Conectar com LM Studio

Provider OpenAI-compatible:

```text
http://host.docker.internal:1234/v1
```

API key:

```text
lm-studio
```

## Uso

- Chat
- Histórico
- Upload de arquivos
- RAG
- Ferramentas
- Integrações
