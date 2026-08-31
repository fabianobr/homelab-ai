# Serviços

## Estado desejado

| Serviço | Obrigatório | Inicialização | Porta | Observação |
|---|---|---|---:|---|
| Ollama | Sim | Docker Compose | 11434 | Backend único de modelos |
| Open WebUI | Sim | Docker Compose | 3000 | Interface principal |
| ComfyUI | Sim | Docker Compose | 8188 | Interface de imagem via Access |
| Cloudflare Tunnel | Sim | systemd | - | Exposição segura |
| LTX Video | Opcional | Docker | variável | Vídeo |
| n8n | Opcional | Docker Compose profile `optional` | 5678 | Automações |
| carwatch-deadman | Sim | Cloudflare Worker (`wrangler deploy`) | - | Dead man's switch dos agentes; cron diário + `POST /ping/<agente>`. Código em `infra/cloudflare/deadman-switch/` |
| DeepSeek Harness | Opcional | Docker Compose profile `harness` | 3081 | Agente de código, via Access |

## Ordem de instalação

1. Ollama (Docker)
2. Open WebUI (Docker)
3. ComfyUI (Docker)
4. Cloudflare Tunnel + Access
5. LTX Video
6. n8n
7. MCPs e ferramentas

## Modelos iniciais recomendados

- Qwen3 14B Q4_K_M
- Gemma 3 12B
- DeepSeek R1 Distill 14B
- Modelo leve auxiliar para tarefas rápidas

## Publicação atual

Serviços publicados via Cloudflare Access:

```text
https://media.example.com -> http://localhost:8188  (ComfyUI)
https://flow.example.com  -> http://localhost:5678  (n8n)
https://dsh.example.com   -> http://localhost:3081 (DeepSeek Harness)
```

E-mail permitido no Access:

```text
user@example.com
```

Open WebUI permanece local em `http://localhost:3000`. Ollama é acessado pelo Open WebUI via rede interna do Docker Compose:

```text
http://ollama:11434        (chat/completions)
http://ollama:11434/v1     (endpoint OpenAI-compatible)
```

O DeepSeek Harness acessa o Ollama pela mesma rede Compose e só publica `127.0.0.1:3081` para o Tunnel. O estado e os workspaces são isolados; ver [`docker/deepseek-harness/README.md`](docker/deepseek-harness/README.md).

## Paths de modelos (bind mounts)

Modelos ficam fora do Docker (muito volume de storage):

| Serviço | Path local | Path no container |
|---|---|---|
| Ollama | `/srv/homelab-ai/ollama` | `/root/.ollama` |
| ComfyUI | `/srv/homelab-ai/comfyui` | `/comfyui` |

## Colibrì / DeepSeek V4 — fora do Compose

| Serviço | Onde roda | Porta | Como sobe |
|---|---|---|---|
| `coli serve` (DeepSeek V4 Flash, 284B) | **host**, não em container | 5000, na bridge do Docker | `infra/scripts/colibri-serve.sh start` |

Único **serviço de inferência** fora do `docker-compose.yml` — o CarWatch tem compose próprio
e o MoneyPrinterTurbo é outro projeto. O engine é compilado no host com
CUDA/DeepGEMM para `sm_120`. **Sob demanda** — segura ~16–21 GB de RAM. Consumido pelo
LiteLLM como `sdlc-review-local`. Detalhes e armadilhas em `docs/colibri.md`.

Não escuta em `127.0.0.1` (o LiteLLM está em container e não alcançaria), e sim em
`172.17.0.1` — o gateway da bridge padrão, que é para onde `host.docker.internal` aponta em
**qualquer** rede. Isso o torna alcançável por todos os containers, por isso `COLI_API_KEY` é
obrigatória.

Validado ponta a ponta em 2026-08-30: `POST /v1/chat/completions` no LiteLLM com
`model: sdlc-review-local` respondeu 48 tokens em 47 s. Note que isso implica ~2,1 tok/s,
acima do 1,37 tok/s medido em execução avulsa — o servidor mantém os pesos densos residentes
e não paga o carregamento a cada requisição.
