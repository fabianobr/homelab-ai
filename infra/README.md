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

Resultado esperado: Open WebUI, Ollama, ComfyUI, Docker Compose, as rotas Cloudflare ativas e GPU com `[OK]`.

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
https://media.example.com  → ComfyUI
https://flow.example.com   → n8n
https://dsh.example.com    → DeepSeek Harness
```

Open WebUI permanece local em `http://localhost:3000`. Ollama é um backend interno e nunca deve ter hostname público. O DeepSeek Harness usa `127.0.0.1:3081` como origin do Tunnel e exige uma aplicação Cloudflare Access própria; ver [`docker/deepseek-harness/README.md`](docker/deepseek-harness/README.md).

## Dead man's switch dos agentes

`infra/cloudflare/deadman-switch/` é um Cloudflare Worker que detecta quando um agente
`systemd` do repo para de rodar — timer que não dispara mais, `linger` perdido, host
desligado. O `run.sh` do agente faz um `POST /ping/<agente>` autenticado só depois de um
run bem-sucedido; o cron diário do Worker alerta no Telegram se o ping não chega no
prazo (carwatch: 8 dias). Deploy, secrets e comprovação no
[`README.md`](cloudflare/deadman-switch/README.md) da pasta.

## Regra de ouro de portas

Nunca expor diretamente na internet:
- Ollama `11434`
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
| [`groq-fast-public.md`](docker/groq-fast-public.md) | Rota Groq opt-in, guardrail e fallback local |

Docs de cada serviço em [`../docs/`](../docs/).
