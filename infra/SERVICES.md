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
| dsh-files | Opcional | Docker Compose profile `harness` | 3082 | Preview HTTP read-only dos arquivos gerados pelo DSH (`DSH_STORAGES_DIR`); publicado por path sob o hostname do DSH web, mesmo Access |

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
https://dsh.example.com         -> http://localhost:3081 (DeepSeek Harness)
https://dsh.example.com/files/  -> http://localhost:3082 (dsh-files, preview read-only; rota por path, mesmo hostname/Access)
https://api.example.com   -> http://localhost:8000  (QuickTools API — serviço de outro repo, ver seção abaixo)
```

A última rota é a exceção da lista: o serviço do outro lado **não é deste repositório**, mas
ocupa uma entrada do ingress do `cloudflared` deste host. Se esse hostname está atrás de Access
ou aberto ao público é decisão do repo do QuickTools; não foi verificado aqui.

E-mail permitido no Access:

```text
user@example.com
```

Open WebUI permanece local em `http://localhost:3000`. Ollama é acessado pelo Open WebUI via rede interna do Docker Compose:

```text
http://ollama:11434        (chat/completions)
http://ollama:11434/v1     (endpoint OpenAI-compatible)
```

O DeepSeek Harness acessa o Ollama pela mesma rede Compose e só publica `127.0.0.1:3081` para o Tunnel. O estado fica no volume `deepseek-harness-state`; os workspaces (`DSH_WORKSPACE_DIR`) e os projetos gerados no chat (`DSH_STORAGES_DIR` → `/dsh-home/storages`) são bind mounts em `infra/runtime/`, acessíveis no host. O serviço `dsh-files` (mesmo profile `harness`, porta 3082) serve esse diretório por HTTP somente-leitura para visualizar/baixar os arquivos — necessário porque o `/api/host.openPath` do DSH web é bloqueado fora de loopback. É publicado por **path** (`/files/`) sob o mesmo hostname do DSH web, não por um hostname/app de Access novo. Ver [`docker/deepseek-harness/README.md`](docker/deepseek-harness/README.md).

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
e o MoneyPrinterTurbo é outro projeto (ver [Containers de outros repos neste
host](#containers-de-outros-repos-neste-host)). O engine é compilado no host com
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

## Containers de outros repos neste host

Além da stack e do CarWatch, dois projetos de **outros repositórios** rodam neste host com
compose próprio. Não têm profile aqui e não sobem nem descem com
`docker compose -f infra/docker/docker-compose.yml`; aparecem nesta página porque ocupam
porta e RAM da máquina — e, no caso do QuickTools, uma rota do Tunnel.

| Container | Porta (host, loopback) | Projeto Compose | Onde vive | Relação com esta stack |
|---|---|---|---|---|
| `quicktools-api` | 8000 | `quicktools` | `~/code/quicktools/quicktools` | Nenhuma (rede `quicktools_default`); publicado pelo Tunnel |
| `quicktools-daily-report` | — | `quicktools` | idem | Nenhuma; worker sem porta publicada |
| `moneyprinterturbo-webui` | 8501 | `moneyprinterturbo` | `~/AI/MoneyPrinterTurbo` | Anexado também à rede `docker_default` |
| `moneyprinterturbo-api` | 8081 → 8080 | `moneyprinterturbo` | idem | Idem; usa o Ollama da stack |

**QuickTools** (`github.com/fabianobr/quicktools`): micro-ferramentas de vídeo/áudio. O
free tier roda no navegador; as tools de IA batem no `quicktools-api` (FastAPI). O
`quicktools-daily-report` é um worker que envia um resumo diário de acessos no Telegram, com
credenciais do `.env` daquele repo — não é um agente de `agents/` e não lê o
`$HOME/.hermes/.env` que os agentes daqui usam. Isolado na rede `quicktools_default`: não
alcança o Ollama nem os demais serviços daqui.

**MoneyPrinterTurbo** (upstream `harry0703/MoneyPrinterTurbo`, MIT, clonado fora do repo como
o ComfyUI e o Colibrì): geração de vídeo curto, WebUI Streamlit + API FastAPI. Os dois
containers estão anexados também à rede `docker_default`, a do compose deste repo, e o log da
API mostra `llm provider: ollama` — o `config.toml` do MPT (fora deste repo) é quem define a
URL exata. Consequência operacional: derrubar o Ollama quebra a geração de roteiro do MPT.

Armadilha do MPT: os containers no ar foram criados com um `docker-compose.override.yml` que
não existe mais na pasta. O `docker-compose.yml` restante publica `127.0.0.1:8080:8080`, que
colide com o SearXNG, e não anexa a `docker_default` — um `up -d` a partir dos arquivos
presentes hoje não reproduz o que está rodando.
