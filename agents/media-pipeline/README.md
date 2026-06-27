# Media Meme Pipeline

Pipeline de geração e distribuição de memes via IA — um experimento de produto de nicho
que prova o uso do homelab para geração de mídia em lote.

## O que foi construído

Pipeline automatizado que usa **ComfyUI** (geração de imagem com Stable Diffusion, GPU local)
e **LTX Video** (text-to-video e image-to-video) para criar memes e conteúdo visual, com
distribuição automática via **Telegram** (bot Hermes). O n8n orquestra os workflows: recebe
o tema, chama ComfyUI via API, pós-processa e envia pelo Telegram.

## Por que foi desmembrado

Decisão de arquitetura: o homelab-ai é a **infraestrutura** que roda os modelos (ComfyUI,
Ollama, n8n). O pipeline de mídia é um **produto** com ciclo de vida próprio — workflows,
prompts, saídas de mídia e automações não devem misturar com infra. Separar em repo próprio
permite publicar, versionar e iterar o produto independentemente.

## Onde o código vive agora

```text
https://github.com/fabianobr/media-meme-pipeline
```

Este `homelab-ai` continua sendo o host: ComfyUI em `infra/docker/`, Ollama, n8n.
O pipeline consome esses serviços via API local.

Não coloque outputs de mídia, `.env`, tokens ou artefatos gerados neste repo.

O contrato consumido pelo pipeline está em
`infra/media-pipeline/contract.yaml`. Releases do pipeline devem fixar uma tag
exata do `homelab-ai`; `main` não é uma dependência suportada.
