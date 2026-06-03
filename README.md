# homelab-ai

Laboratório pessoal de IA local para rodar chat, agentes, RAG, geração de imagem, vídeo e automações em um desktop Ubuntu com GPU NVIDIA.

## Objetivo

Transformar o desktop `homelab` em um servidor pessoal de IA acessível remotamente com segurança.

Stack principal:

- LM Studio
- Open WebUI
- Tailscale
- Cloudflare Tunnel + Cloudflare Access
- ComfyUI
- LTX Video
- n8n

## Estrutura

```text
homelab-ai/
├── README.md
├── ARCHITECTURE.md
├── INVENTORY.yaml
├── SERVICES.md
├── SECURITY.md
├── STANDARDS.md
├── ROADMAP.md
├── docker/
│   └── docker-compose.yml
├── infra/
│   ├── cloudflare/
│   └── tailscale/
├── scripts/
├── agents/
└── docs/
```

## Subir serviços Docker

```bash
cd docker
docker compose up -d
```

## Validar ambiente

```bash
bash ../scripts/healthcheck.sh
```

## Regra de ouro

Nunca exponha diretamente na internet:

- LM Studio `1234`
- ComfyUI `8188`
- n8n `5678`
- Docker socket

Use Tailscale ou Cloudflare Access.
