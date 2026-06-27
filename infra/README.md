# Infraestrutura — homelab-ai

Tudo que mantém o homelab de IA rodando: Docker Compose, scripts de sistema,
Cloudflare Tunnel/Access e configuração de GPU.

## Subir os serviços

```bash
cd infra/docker
docker compose up -d open-webui
```

O `n8n` é opcional e só deve ser iniciado explicitamente:

```bash
cd infra/docker
docker compose --profile optional up -d n8n
```

## Healthcheck geral

```bash
bash infra/scripts/healthcheck.sh
```

Resultado esperado: Open WebUI, LM Studio, ComfyUI, Docker Compose, Cloudflare e GPU com `[OK]`.

## Aplicar configuração de sistema

Algumas mudanças ficam fora do repositório e exigem root:

```bash
sudo bash infra/scripts/apply-system-config.sh
```

Esse script configura o bind do Ollama Snap, restringe a porta `11434` ao host/redes Docker,
instala o ingress do Cloudflare Tunnel e reinicia os serviços afetados.

## Acesso remoto

O acesso remoto público passa pelo Cloudflare Access:

```text
https://ai.example.com     → Open WebUI
https://media.example.com  → ComfyUI
https://flow.example.com   → n8n
```

Ollama e LM Studio são backends internos — nunca devem ter hostnames públicos.

## Regra de ouro de portas

Nunca expor diretamente na internet:
- Ollama `11434`
- LM Studio `1234`
- n8n `5678`
- LiteLLM `4000`
- Docker socket

## Documentação de serviços

| Arquivo | O que cobre |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | C4 L1/L2 do sistema |
| [`SERVICES.md`](SERVICES.md) | Tabela de portas e exposição |
| [`ROADMAP.md`](ROADMAP.md) | Fases concluídas e próximas |
| [`ROLLBACK-gpu-cdi.md`](docker/ROLLBACK-gpu-cdi.md) | Troubleshooting GPU CDI |

Docs de cada serviço em [`../docs/`](../docs/).
