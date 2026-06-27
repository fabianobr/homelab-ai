# SDLC Híbrido — Decisão de Flagship e Definition of Done v1

> Registrado em: 2026-06-27  
> Status: **DECIDIDO**

---

## A decisão

**O SDLC Híbrido é o flagship do homelab-ai.**

Dos três candidatos avaliados, este é o único com (a) insight original verificável,
(b) métricas já coletadas em PoC real e (c) alinhamento direto com o objetivo declarado
do projeto: medir e divulgar o alcance real de LLMs no ciclo de desenvolvimento de software.

---

## SWOT dos candidatos

### Candidato 1 — SDLC Híbrido ← ESCOLHIDO

| | |
|---|---|
| **Forças** | PoC com métricas reais ($0.04–0.07/feature, 265s e2e, 3/5 critérios); insight original (TDD Invertido elimina circularidade); roteamento por ambiguidade é tese vendável; `/sdlc-hybrid` no opencode já funciona |
| **Fraquezas** | Ainda não gera código limpo sem fixes manuais; depende de n8n + scripts bash frágeis; único caso de uso testado é FastAPI CRUD (toy) |
| **Oportunidades** | Tema atual (custo de LLM no SDLC); poucos projetos publicam números honestos local+cloud; vira série de posts + template reutilizável |
| **Ameaças** | Frontier models barateando podem corroer a tese "local economiza"; ferramentas concorrentes (KodeOps, Plandex) crescendo |

### Candidato 2 — Gerador de memes

| | |
|---|---|
| **Forças** | Produto com usuário final; usa stack de imagem/vídeo já montada; output visual tem apelo de divulgação |
| **Fraquezas** | Desmembrado para repo separado (status atual desconhecido aqui); mercado saturado e comoditizado |
| **Oportunidades** | Nicho + distribuição Telegram pode achar audiência pequena mas específica |
| **Ameaças** | Concorrência gratuita e infinita; baixíssima defensabilidade; custo de manter usuários reais |

**Decisão:** arquivado como caso de portfolio ("explorei produto de nicho, desmembrei para repo próprio"). Não é flagship.

### Candidato 3 — Homelab como showcase

| | |
|---|---|
| **Forças** | Já está sólido (CDI GPU, Cloudflare Access, gitleaks); baixo esforço para "terminar" |
| **Fraquezas** | Categoria saturada ("my homelab" repos); não é produto; valor decai com facilidade de setup crescente |
| **Oportunidades** | Boa referência de setup seguro de IA local; útil como suporte narrativo |
| **Ameaças** | Difícil destacar-se; zero diferenciação além do cuidado com segurança |

**Decisão:** é a *fundação* da história (onde os modelos rodam), não o protagonista. O `infra/` serve o flagship; não compete com ele.

---

## O que "shippar" significa — Definition of Done v1

Um observador externo roda **um comando**, descreve uma feature em linguagem natural, e recebe
**código que passa no pytest sem nenhuma edição manual**, com relatório de custo.

### Critérios mensuráveis

| Régua atual (PoC jun/2026) | Régua v1 |
|---|---|
| 6/7 testes passam *com* 2 fixes manuais | 100% testes passam *sem* fix manual em ≥1 caso real não-toy |
| Spec RF-NN só via multi-turn manual | Spec estruturada gerada deterministicamente a partir de descrição |
| Bugs de versão (`pydantic.v2`, `httpx`) | System prompt fixa versões; código compila de primeira |
| Scripts bash soltos + n8n | Um entry point (`/sdlc-hybrid` ou `make feature`) e2e |
| Único caso testado: TODO CRUD | ≥3 casos de exemplo versionados como regression suite |
| Sem observabilidade de custo | Langfuse rastreando custo/tokens por fase |

### Caminho de maior impacto para fechar o gap (derivado do VIABILITY-REPORT.md)

1. **Loop de auto-fix** — `fix-loop.sh` já existe em `tests/`; fechar o ciclo pytest→erro→Ollama corrige→re-roda
2. **Pinning de versões no system prompt** — pydantic≥2, httpx≥0.23, pytest-asyncio; elimina toda a classe de bugs do PoC
3. **WF4 TDD Invertido** — Test Agent lê só a spec, Code Agent lê spec+testes; contextos separados eliminam circularidade
4. **3 casos de regressão** — além do TODO CRUD; prova que generaliza (ex.: validação com regra de negócio, auth mock, parser)
5. **Langfuse** — transforma estimativa de custo em medição

A ordem 1→2→3 dá o maior salto com menor esforço (todos têm scaffolding existente).

---

## O que NÃO está no escopo de v1

- Interface gráfica ou SaaS
- Suporte a múltiplos usuários ou multi-tenancy
- Casos de uso além de APIs backend (ex.: frontend, mobile)
- Integração com CI/CD externo real
- RAG sobre codebase existente

Essas extensões existem no backlog de pesquisa (`research/sdlc-agentico/backlog.md`) e
são candidatos para v2 depois que v1 for validada.

---

## Relação com os outros artefatos

- **Prova de conceito**: [`VIABILITY-REPORT.md`](VIABILITY-REPORT.md) — métricas do PoC
- **Primeiro app gerado**: [`../marketplace/`](../marketplace/) — Mercado Loop (gerado em 2026-06-20)
- **Pesquisa que embasou**: [`../../research/sdlc-agentico/`](../../research/sdlc-agentico/)
- **Próximo goal**: reorganizar backlog de pesquisa em radar/roadmap/decisions (Goal 3)
- **Execução**: elevar a régua do pipeline para a DoD acima (Goal 4)
