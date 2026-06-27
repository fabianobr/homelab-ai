# homelab-ai — Instruções para Agentes

## O que é este repositório

Lab pessoal para medir o alcance real de LLMs no ciclo de desenvolvimento de software — o que funciona,
o que não funciona, com números. Inclui a infraestrutura que roda os modelos (GPU local + Cloudflare),
a pesquisa de SDLC agêntico, e os produtos gerados por essa pesquisa.

## Mapa das 3 trilhas

| Trilha | Pasta | O que é |
|---|---|---|
| **Infra** | `infra/` | Docker Compose, scripts, Cloudflare, arquitetura do homelab |
| **Pesquisa** | `research/sdlc-agentico/` | Backlog de ferramentas, fases do SDLC, propostas avaliadas |
| **Produtos** | `products/` | Artefatos rodáveis gerados pela pesquisa |

Produto flagship: `products/sdlc-hibrido/` — pipeline que mistura Ollama local com Claude API.
Prova de conceito rodável: `products/marketplace/` — "Mercado Loop", primeiro app não-toy gerado pelo pipeline.

## Convenções

- **Commits em português (PT-BR)** — padrão do histórico; manter consistência.
- **Conventional commits:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`.
- **Nunca commitar:** `.env`, chaves de API, tokens, IPs internos, segredos de qualquer tipo.
- **Antes de qualquer commit:** rodar `pre-commit run --all-files` (gitleaks detecta segredos).
  O repo é **público** no GitHub — qualquer segredo vaza permanentemente.

## Segurança do repo público

```bash
# Instalar o hook uma vez:
pip install pre-commit && pre-commit install

# Rodar manualmente antes de commitar:
pre-commit run --all-files
```

O hook usa [gitleaks](https://github.com/gitleaks/gitleaks). Ver `.pre-commit-config.yaml` e
`infra/scripts/check-public-ready.sh` para checagem completa.

## Portas nunca expostas diretamente na internet

- Ollama `11434`
- LM Studio `1234`
- n8n `5678`
- LiteLLM `4000`
- Docker socket

Usar Cloudflare Access para os hostnames publicados. Ver `infra/README.md` para detalhes.

## Onde cada coisa vive

```
homelab-ai/
├── CLAUDE.md / AGENTS.md   ← você está aqui; instruções para agentes
├── INVENTORY.yaml           ← hardware e serviços inventariados
├── SECURITY.md              ← política de segurança do repo
├── STANDARDS.md             ← padrões de código e convenções
├── infra/                   ← trilha 1: homelab que roda os modelos
│   ├── docker/              ← docker-compose.yml, ComfyUI, LiteLLM
│   ├── scripts/             ← healthcheck, apply-system-config, bootstrap
│   ├── cloudflare/          ← config do Tunnel e Access
│   ├── ARCHITECTURE.md      ← C4 L1/L2 do homelab
│   ├── SERVICES.md          ← tabela de serviços e portas
│   └── ROADMAP.md           ← fases concluídas e próximas
├── research/
│   └── sdlc-agentico/       ← trilha 2: pesquisa de SDLC agêntico
│       ├── backlog.md       ← 27+ ferramentas avaliadas
│       ├── proposals/       ← propostas A–F com viabilidade
│       └── sdlc-phases/     ← prompt e ferramentas por fase
├── products/
│   ├── sdlc-hibrido/        ← trilha 3a: o pipeline flagship
│   └── marketplace/         ← trilha 3b: primeiro app gerado pelo pipeline
├── agents/                  ← configs de ferramentas (claude-code.md, codex.md)
│   └── weekly-sdlc-research/← job semanal de pesquisa via n8n
└── docs/                    ← docs de serviços (comfyui, n8n, lm-studio, etc.)
```
