# Relatório de Viabilidade — n8n SDLC PoC

**Data:** 2026-06-19
**Duração total e2e:** 265s (13s chat + 252s code gen)

## Arquitetura Real (difere do plano original)

O plano original assumia que Code nodes poderiam chamar o Ollama via `fetch()`. Isso estava errado — o sandbox JS do n8n 2.23.3 bloqueia todo acesso de rede a partir de Code nodes. A arquitetura real usa HTTP Request nodes para as chamadas LLM:

- **Workflow 1** (`POST /webhook/sdlc-poc-chat`): Webhook → Code(prepara messages) → HTTP Request(Ollama `qwen3-coder:30b`) → Code(processa resposta) → Respond
- **Workflow 2** (`POST /webhook/sdlc-poc-spec-to-code`): Webhook → Code(prepara body) → HTTP Request(Ollama `qwen2.5-coder:32b`) → Code(parse files) → Respond

## Resultados por Fase

### Fase 1: Discovery (Chat)

- **Endpoint:** `POST /webhook/sdlc-poc-chat`
- **Payload:** `{"chatInput": "...", "messages": []}`
- **Modelo:** `qwen3-coder:30b` (Ollama local)
- **Tempo medido:** 13s (e2e test), 11s (Task 3) — consistentemente <15s
- **Output:** 765 chars — resposta conversacional com perguntas de clarificação e estrutura de discovery
- **Qualidade subjetiva:** 3/5 — O modelo faz perguntas de discovery relevantes (contexto de uso, escala, integrações, stack tecnológica), mas produz conteúdo conversacional, não um documento PRD com hipóteses formais. Para gerar um spec completo com requisitos RF-NN é necessária uma conversa multi-turn com o prompt "gerar spec".
- **Problemas identificados:**
  - Workflow 1 em modo chat gera discovery conversacional, não PRD estruturado
  - Não produz hipóteses testáveis em formato `## Hypotheses` automaticamente
  - Para spec completa com RF-NN é necessário sequência multi-turn (discovery → "gerar spec")

### Fase 2: Spec to Code

- **Endpoint:** `POST /webhook/sdlc-poc-spec-to-code`
- **Payload:** `{"spec": "..."}`
- **Modelo:** `qwen2.5-coder:32b` (Ollama local)
- **Tempo medido:** 252s (~4 min 12s) — dentro do limite de 300s
- **Arquivos gerados:** 4 (`models.py`, `routes.py`, `main.py`, `test_main.py`)
- **Qualidade subjetiva:** 4/5 — FastAPI + Pydantic corretos, CRUD completo, HTTPException para 404, pytest assíncrono com httpx. Pequenos bugs de compatibilidade de versão.
- **Problemas identificados:**
  - `pydantic.v2` não é um caminho de importação válido (correto: `pydantic`) — bug do LLM
  - `AsyncClient(app=app, ...)` removido no httpx 0.28+ (requer `ASGITransport`) — bug do LLM
  - `todo_store` global compartilhado entre testes — isolamento de estado não implementado

## Resultados dos Testes Gerados

### Execução com código exatamente como gerado (sem modificação manual)

```
ERROR test_main.py - ModuleNotFoundError: No module named 'pydantic.v2'
```

0/7 testes executam — falha na coleta por import inválido.

### Execução com 2 correções de compatibilidade de versão

Correções aplicadas:
1. `from pydantic.v2 import` → `from pydantic import`
2. `AsyncClient(app=app, ...)` → `AsyncClient(transport=ASGITransport(app=app), ...)`

```
test_main.py::test_create_todo      PASSED
test_main.py::test_read_todos       FAILED  (state leak: vê 3 itens em vez de 2)
test_main.py::test_read_todo        PASSED
test_main.py::test_read_todo_not_found  PASSED
test_main.py::test_update_todo      PASSED
test_main.py::test_delete_todo      PASSED
test_main.py::test_delete_todo_not_found  PASSED

6 passed, 1 failed
```

A falha em `test_read_todos` é um bug de design de teste (estado global não resetado entre testes), não um bug funcional da aplicação.

## Veredicto de Viabilidade

| Critério | Meta | Resultado | Aprovado? |
|---|---|---|---|
| Discovery com estrutura útil | Resposta não-vazia com conteúdo relevante | 765 chars, perguntas de clarificação e guia de discovery | SIM |
| Spec com requisitos RF- | ≥5 RF- items | Workflow 1 gera discovery conversacional; spec RF-NN requer multi-turn. Não produzido automaticamente. | NÃO¹ |
| Código gerado | ≥3 arquivos | 4 arquivos (models.py, routes.py, main.py, test_main.py) | SIM |
| Testes do código passam | ≥1 teste sem modificação manual | 0/7 com código exatamente como gerado (import inválido). 6/7 com 2 correções de compatibilidade de versão. | PARCIAL² |
| Tempo e2e | <300s | 265s total (13s + 252s) | SIM |

**Critérios aprovados: 3/5 (+ 1 parcial)**

¹ O critério de spec RF-NN não foi atingido no fluxo single-shot. O Workflow 1 é um chat assistant que faz discovery conversacional; para gerar um PRD com RF-NN é necessário um segundo turno com prompt "gerar spec". Isso é uma gap de design do PoC, não uma limitação do LLM.

² Os testes falham sem modificação manual por bugs de compatibilidade de versão gerados pelo LLM (`pydantic.v2` e `httpx.AsyncClient(app=...)`). Com 2 correções triviais de import, 6/7 testes passam. A lógica da aplicação está correta.

## Análise por Dimensão

### O que funcionou bem
- **Integração n8n + Ollama local:** Estável, sem problemas de conectividade
- **Qualidade do código FastAPI gerado:** Estrutura correta, CRUD completo, validação Pydantic, HTTPException, testes asyncio
- **Tempo de resposta do chat:** 11-13s é aceitável para discovery interativo
- **Volume de código gerado:** 4 arquivos, ~230 linhas, produção-like

### O que precisa melhorar
- **Prompts do Workflow 1:** Precisam produzir PRD estruturado com RF-NN, não apenas discovery conversacional
- **Compatibilidade de versão no code gen:** O LLM usa APIs desatualizadas (`pydantic.v2`, `AsyncClient(app=...)`) — o system prompt precisa especificar versões (pydantic>=2.0, httpx>=0.23)
- **Isolamento de estado nos testes gerados:** `todo_store` global não é resetado entre testes — prompt precisa instruir `@pytest.fixture(autouse=True)` para reset
- **Tempo do code gen:** 252s (~4min) é aceitável mas no limite — modelos menores (7B-14B) podem ser testados para tarefas mais simples

## Limitação Técnica Descoberta: Sandbox do n8n

O n8n 2.23.3 usa um JS task runner em sandbox que bloqueia todo acesso de rede a partir de Code nodes. Isso significa:
- **Impossível:** `fetch()`, `axios`, `http.request()` etc. em Code nodes
- **Workaround:** Usar HTTP Request nodes para todas as chamadas externas (Ollama, APIs)
- **Impacto:** Aumenta complexidade dos workflows (mais nodes), mas não bloqueia a solução

## Próximos Passos

- [ ] **Se prosseguir:** Revisar prompt do Workflow 1 para gerar PRD com RF-NN em resposta a "gerar spec"
- [ ] **Se prosseguir:** Adicionar versões explícitas ao system prompt do code gen (pydantic, httpx, pytest-asyncio)
- [ ] **Se prosseguir:** Adicionar Langfuse para rastrear tokens e qualidade por fase
- [ ] **Se prosseguir:** Testar modelos menores (qwen2.5-coder:7b) para reduzir tempo de code gen
- [ ] **Se reprovar:** O gap principal é a spec RF-NN — considerar workflow dedicado de spec generation (não chat)
- [ ] **Publicar workflows** como templates n8n no repositório
