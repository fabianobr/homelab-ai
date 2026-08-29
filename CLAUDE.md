# homelab-ai — Instruções para Agentes

## O que é este repositório

Lab pessoal para medir o alcance real de LLMs no ciclo de desenvolvimento de software — o que funciona,
o que não funciona, com números. Inclui a infraestrutura que roda os modelos (GPU local + Cloudflare),
a pesquisa de SDLC agêntico, os produtos gerados por essa pesquisa e as rotinas autônomas que rodam
sozinhas em produção neste host.

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

- **Telegram:** os agentes compartilham o bot **Hermes** (alerta interno de execução de job).
  O **CarWatch é a exceção** — usa bot dedicado, com credenciais próprias em `agents/carwatch/.env`.
  Não misturar os dois. Helper compartilhado: `agents/lib/telegram_notify.py`.
- **Os semanais escrevem no repo:** `weekly-sdlc-research` faz append em
  `research/sdlc-agentico/backlog.md`; `weekly-cost-benefit` em `research/sdlc-agentico/cost-benefit.md`.
  Relatórios por execução vão para `<agente>/reports/YYYY-MM-DD-*.md`.
- **Segredos e relatórios operacionais nunca são versionados** — `.env` é gitignored;
  cada agente tem `.env.example`.
- **O `weekly-disk-guardian` nunca apaga nada sozinho.** O timer chama só
  `diagnose --notify` e para em `Proposal`; `apply` exige manifesto revisado e aprovado.

## Convenções

- **Este arquivo faz parte da mudança.** Criou ou alterou subprojeto, agente, serviço,
  porta, profile do Compose ou convenção operacional? Atualize o `CLAUDE.md` **no mesmo
  commit** — mapa de trilhas, tabela de rotinas, árvore de diretórios, tabela de
  profiles/portas. Confira contra a realidade, não contra a memória: `docker-compose.yml`
  para profiles e portas, `systemctl --user list-timers` para o estado dos agentes.
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

O Compose usa profiles. **Sem `--profile`, só `ollama` e `open-webui` sobem** — o resto
não é falha, é profile desligado.

| Serviço | Profile | Porta (loopback) |
|---|---|---|
| `ollama` | default + `media-pipeline` | 11434 |
| `open-webui` | default | 3000 |
| `comfyui` | `media-pipeline` | 8188 |
| `n8n` | `optional` | 5678 |
| `litellm` | `optional` | 4000 |
| `searxng` | `optional` | 8080 |

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml --profile optional up -d
```

`searxng` e `n8n` são dependências dos agentes semanais — se um agente semanal "não acha
o buscador" ou "não acha o webhook", conferir o profile antes de investigar o agente.

## Portas nunca expostas diretamente na internet

- Ollama `11434`
- LM Studio `1234`
- SearXNG `8080`
- n8n `5678`
- LiteLLM `4000`
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
├── infra/                   ← trilha 1: homelab que roda os modelos
│   ├── docker/              ← docker-compose.yml, comfyui/, n8n/, searxng/, litellm-config.yaml
│   ├── scripts/             ← healthcheck, apply-system-config, update, check-public-ready
│   ├── cloudflare/          ← config do Tunnel e Access
│   ├── media-pipeline/      ← contrato público (contract.yaml) do repo media-meme-pipeline
│   ├── ARCHITECTURE.md      ← C4 L1/L2 do homelab
│   ├── SERVICES.md          ← tabela de serviços e portas
│   └── ROADMAP.md           ← fases concluídas e próximas
├── research/
│   └── sdlc-agentico/       ← trilha 2: pesquisa de SDLC agêntico
│       ├── backlog.md       ← ~35 ferramentas avaliadas + pesquisas semanais datadas
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
└── docs/                    ← docs de serviços (comfyui, n8n, lm-studio, ltx-video, etc.)
    └── superpowers/plans/   ← planos de implementação versionados (n8n PoC, fases do CarWatch)
```
