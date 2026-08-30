# homelab-ai — Instruções para Agentes

## O que é este repositório

Lab pessoal para medir o alcance real de LLMs no ciclo de desenvolvimento de software — o que funciona,
o que não funciona, com números. Inclui a infraestrutura que roda os modelos (GPU local + Cloudflare),
a pesquisa de SDLC agêntico, os produtos gerados por essa pesquisa e as rotinas autônomas que rodam
sozinhas em produção neste host.

## Infra Environment Constraints

No início de cada sessão, rodar `scripts/state.sh` antes de me perguntar qualquer coisa
— ele imprime um retrato de uma tela: git (branch/status/últimos 5 commits), PRs abertos,
`docker ps` com health, timers systemd do usuário e uso de disco.

Ler antes de qualquer trabalho de ops nesta máquina:

- **Sem TTY: `sudo` falha.** Se um passo precisa de root, pare e entregue o comando exato
  para o usuário rodar — não fique tentando de novo.
- **Arquivos dentro de containers são de root.** Editar via `docker exec`, não pelo host.
- **Automação de browser não alcança serviços em `127.0.0.1`** (ComfyUI `:8188`, etc.).
  Usar inspeção via CLI/filesystem/API.
- **Unidades systemd de usuário podem esbarrar no classificador de permissão.** Propor o
  comando para o usuário em vez de repetir tentativas em loop.

## Mapa das 4 trilhas

| Trilha | Pasta | O que é |
|---|---|---|
| **Infra** | `infra/` | Docker Compose, scripts, Cloudflare, arquitetura do homelab |
| **Pesquisa** | `research/sdlc-agentico/` | Backlog de ferramentas, fases do SDLC, propostas avaliadas |
| **Produtos** | `products/` | Artefatos rodáveis gerados pela pesquisa |
| **Agentes** | `agents/` | Rotinas autônomas em produção (systemd timers do usuário) |

Produto flagship: `products/sdlc-hibrido/` — pipeline que mistura Ollama local com Claude API.
Prova de conceito rodável: `products/marketplace/` — "Mercado Loop", primeiro app não-toy gerado pelo pipeline.
Agente flagship: `agents/carwatch/` — pipeline semanal de lançamentos automotivos, em produção desde 2026-08-28.

## Rotinas autônomas (`agents/`)

Todas agendadas por **systemd timer do usuário** (`systemctl --user`), não cron — o timer tem
catch-up se a máquina estiver desligada no horário. Cada agente traz seu `systemd/` e um `run.sh`.

| Agente | Quando | Motor | Estado |
|---|---|---|---|
| `carwatch/` | Sáb 09:00 | Claude Haiku + Postgres | 🟢 timer ativo |
| `youtube-etl/` | Sex 18:00 | n8n + Ollama (`llama3.2`) | 🟢 timer ativo |
| `weekly-sdlc-research/` | Sex 19:00 | SearXNG + Ollama (`qwen3:14b`) | 🟢 timer ativo |
| `weekly-cost-benefit/` | Sex 20:00 | SearXNG + Ollama | 🟢 timer ativo |
| `weekly-disk-guardian/` | Seg 10:00 | coletores locais | 🟢 timer ativo |
| `media-pipeline/` | — | — | 📤 código migrado para repo próprio; a pasta é só um ponteiro |

Convenções dos agentes:

- **Telegram:** hoje **todos** os que notificam usam o bot **Hermes** (alerta interno de
  execução de job), com credenciais lidas de `$HOME/.hermes/.env` — fora do repo.
  Helper compartilhado: `agents/lib/telegram_notify.py`.
  O `weekly-disk-guardian` é o único que não manda nada: `telegram: false` no
  `config.yaml`, notifica por `notify-send` no desktop.
  O `DESIGN.md` do CarWatch prevê um **bot dedicado**, mas isso ainda não existe em
  produção — o `agents/carwatch/TODO.md` mantém a troca como pendência aberta. Ao mexer
  nisso, o `TODO.md` é a fonte do que está no ar; o `DESIGN.md` é a intenção.
- **Os semanais escrevem no repo:** `weekly-sdlc-research` faz append em
  `research/sdlc-agentico/backlog.md`; `weekly-cost-benefit` em `research/sdlc-agentico/cost-benefit.md`.
- **Onde cada agente deixa a saída** varia — não presuma `reports/`:
  `weekly-sdlc-research`, `weekly-cost-benefit` e `youtube-etl` gravam
  `<agente>/reports/YYYY-MM-DD-*.md`; `carwatch` gera `data/feed.atom` e publica no
  Telegram; `weekly-disk-guardian` grava só em state XDG privado (`runs/<run_id>/`).
- **O `carwatch` faz backup do banco a cada run.** `backup.sh` roda depois do
  `weekly-run`, grava um dump `pg_dump -Fc` em `$HOME/.local/state/carwatch/backups`
  (fora do repo — o dump tem dados e o repo é público) e envia para o remote rclone
  `gdrive:carwatch-backups/`, mantendo 8 cópias de cada lado. Falha de backup avisa em
  stderr mas **não** derruba o run. Ajustável por `CARWATCH_BACKUP_DIR`,
  `CARWATCH_BACKUP_REMOTE` (vazio desliga o envio) e `CARWATCH_BACKUP_KEEP`.
- **O `carwatch` pinga um dead man's switch externo no fim de um run bem-sucedido.**
  `deadman-ping.sh` (chamado pelo `run.sh` depois do backup, não-fatal) faz um `POST`
  autenticado para o Worker Cloudflare `carwatch-deadman`
  (`infra/cloudflare/deadman-switch/`), que alerta no Telegram se o ping não chega em
  8 dias — cobre timer parado, `linger` perdido, host desligado, que um heartbeat
  interno não pega. `CARWATCH_DEADMAN_URL` vazio desliga o ping. **Não é systemd** — o
  Worker tem cron próprio na Cloudflare.
- **Segredos e relatórios operacionais nunca são versionados** — `.env` é gitignored.
  Só o `agents/carwatch/` tem `.env.example`; os demais não têm nenhum, porque tiram
  credencial do `$HOME/.hermes/.env`.
- **O `weekly-disk-guardian` nunca apaga nada sozinho.** O timer chama só
  `diagnose --notify` e para em `Proposal`; `apply` exige manifesto revisado e aprovado.

## Convenções

- **Este arquivo faz parte da mudança.** Criou ou alterou subprojeto, agente, serviço,
  porta, profile do Compose ou convenção operacional? Atualize o `CLAUDE.md` **no mesmo
  commit** — mapa de trilhas, tabela de rotinas, árvore de diretórios, tabela de
  profiles/portas. Confira contra a realidade, não contra a memória — o doc de design de
  um agente diz a intenção, não o que está no ar: `docker compose config --services` para
  profiles, `docker ps` para portas, `systemctl --user list-timers` para o estado dos
  agentes. Se a mudança tocar serviços ou portas, `infra/SERVICES.md` e `README.md`
  descrevem a mesma coisa e precisam ficar de acordo.
  Este é o primeiro arquivo que qualquer agente lê; quando ele mente, o erro se propaga
  para todo o trabalho seguinte.
- **Commits em português (PT-BR)** — padrão do histórico; manter consistência.
- **Conventional commits:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`.
- **Nunca commitar:** `.env`, chaves de API, tokens, IPs internos, segredos de qualquer tipo.
- **Antes de qualquer commit:** rodar `pre-commit run --all-files` (gitleaks detecta segredos).
  O repo é **público** no GitHub — qualquer segredo vaza permanentemente.
- **Caminhos em arquivos versionados são sanitizados de propósito.** `INVENTORY.yaml` usa
  `/opt/homelab-ai` e `/srv/...`; o host real usa outros caminhos. Hardware pode aparecer,
  o caminho absoluto do `$HOME` não. Não "corrigir" isso.

## Segurança do repo público

```bash
# Instalar o hook uma vez:
pip install pre-commit && pre-commit install

# Rodar manualmente antes de commitar:
pre-commit run --all-files
```

O hook usa [gitleaks](https://github.com/gitleaks/gitleaks) e roda também no CI
(`.github/workflows/gitleaks.yml`, em todo push e PR). Ver `.pre-commit-config.yaml` e
`infra/scripts/check-public-ready.sh` para checagem completa.

## Subir a stack — profiles importam

**Todos os seis serviços estão atrás de profile. Sem `--profile`, nada sobe** — não é
falha, é profile desligado. Confirme com
`docker compose --env-file homelab.env -f infra/docker/docker-compose.yml config --services`:
sem profile a saída é vazia.

| Serviço | Profile | Porta (loopback) |
|---|---|---|
| `open-webui` | `interactive` | 3000 |
| `ollama` | `media-pipeline` | 11434 |
| `comfyui` | `media-pipeline` | 8188 |
| `n8n` | `optional` | 5678 |
| `litellm` | `optional` | 4000 |
| `searxng` | `optional` | 8080 |

O env-file é `homelab.env` na raiz (gitignored) — **não** `.env`. Ele define
`HOMELAB_ROOT`, `COMFYUI_SOURCE_DIR` e `SEARXNG_SECRET`, que o compose lê como
`${VAR:?}`; sem ele o comando falha duro.

```bash
# a stack inteira, como roda hoje neste host:
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile interactive --profile media-pipeline --profile optional up -d
```

**O `comfyui` é sob demanda — não deixe ligado por padrão.** Ocioso ele segura
~20 GiB de RAM e a VRAM do modelo residente, e nenhum timer depende dele. Suba
só quando for gerar (`docker start comfyui`); o timer de usuário
`comfyui-idle-stop.timer` (ver `infra/systemd/`) o desliga sozinho após ~1h sem
atividade. Se `docker compose up` da stack inteira o trouxe junto pelo profile
`media-pipeline`, pare-o com `docker stop comfyui`.

**`--profile interactive` sozinho não funciona:** `open-webui` tem
`depends_on: ollama`, e `ollama` está em `media-pipeline` — o compose recusa o projeto
com *"depends on undefined service"*. Os dois profiles andam juntos.

`--profile optional` sobe `n8n`, `litellm` e `searxng` **sem `ollama`**. Como os agentes
semanais precisam dos dois, esse profile sozinho não basta para rodá-los. Se um agente
semanal "não acha o buscador" ou "não acha o webhook", conferir os profiles no ar antes
de investigar o agente.

O **CarWatch não faz parte desta stack**: tem compose próprio em
`agents/carwatch/docker-compose.yml`, onde só o `db` fica de pé e o `app` roda sob
demanda via `docker compose run --rm`.

## Portas nunca expostas diretamente na internet

- Ollama `11434`
- SearXNG `8080`
- n8n `5678`
- LiteLLM `4000`
- Postgres do CarWatch `5433` (compose próprio do agente)
- Docker socket

Todas ficam em `127.0.0.1` no Compose. Usar Cloudflare Access para os hostnames publicados.
Ver `infra/README.md` para detalhes.

## Onde cada coisa vive

```
homelab-ai/
├── CLAUDE.md / AGENTS.md   ← você está aqui; instruções para agentes
├── INVENTORY.yaml           ← hardware e serviços inventariados (caminhos sanitizados)
├── SECURITY.md              ← política de segurança do repo
├── STANDARDS.md             ← padrões de código e convenções
├── scripts/                 ← utilitários de sessão (state.sh: retrato do host)
├── infra/                   ← trilha 1: homelab que roda os modelos
│   ├── docker/              ← docker-compose.yml, comfyui/, n8n/, searxng/, litellm-config.yaml
│   ├── scripts/             ← healthcheck, apply-system-config, update, check-public-ready, comfyui-idle-stop
│   ├── systemd/             ← unidades de usuário de infra (comfyui-idle-stop.timer)
│   ├── cloudflare/          ← config do Tunnel e Access + deadman-switch/ (Worker)
│   ├── media-pipeline/      ← contrato público (contract.yaml) do repo media-meme-pipeline
│   ├── ARCHITECTURE.md      ← C4 L1/L2 do homelab
│   ├── SERVICES.md          ← tabela de serviços e portas
│   └── ROADMAP.md           ← fases concluídas e próximas
├── research/
│   └── sdlc-agentico/       ← trilha 2: pesquisa de SDLC agêntico
│       ├── backlog.md       ← 27 ferramentas na tabela principal + itens datados pendentes
│       ├── cost-benefit.md  ← saída do agente weekly-cost-benefit
│       ├── proposals/       ← propostas A–F com viabilidade
│       ├── sdlc-phases/     ← 9 fases: prompt e ferramentas por fase
│       └── fluxo-agentico-local.md, sdlc-hibrido-overview.md, feedback.md, input/
├── products/
│   ├── sdlc-hibrido/        ← trilha 3a: o pipeline flagship (workflows n8n + prompts)
│   └── marketplace/         ← trilha 3b: Mercado Loop, app gerado pelo pipeline (PWA + FastAPI)
├── agents/                  ← trilha 4: rotinas autônomas + configs de ferramentas
│   ├── carwatch/            ← lançamentos automotivos; Claude Haiku + Postgres, em produção
│   ├── weekly-sdlc-research/← pesquisa semanal → backlog.md
│   ├── weekly-cost-benefit/ ← custo-benefício semanal → cost-benefit.md
│   ├── youtube-etl/         ← ETL n8n: YouTube automotivo → Ollama → relatório/Telegram
│   ├── weekly-disk-guardian/← diagnóstico de disco (Scout→Proposal→Approval→Apply→Proof)
│   ├── media-pipeline/      ← ponteiro: código vive em fabianobr/media-meme-pipeline
│   ├── lib/                 ← helpers compartilhados (telegram_notify.py)
│   └── claude-code.md, codex.md, continue-dev.md  ← configs por ferramenta
└── docs/                    ← docs de serviços (comfyui, n8n, ltx-video, etc.)
    └── superpowers/plans/   ← planos de implementação versionados (n8n PoC, fases do CarWatch)
```
