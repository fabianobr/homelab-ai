# Backlog de Pesquisa — SDLC Agêntico

Este arquivo registra todas as ferramentas, modelos e tecnologias pesquisadas para o ciclo SDLC agêntico local. Atualizado semanalmente pelo agente `weekly-sdlc-research`, via systemd timer.

---

## Tabela de Itens Pesquisados

| # | Nome/Ferramenta | Tipo | Viabilidade | Relevancia | Status |
|---|---|---|---|---|---|
| 1 | OpenCode | Agente de Coding (TUI) | 4/5 | 5/5 | Em avaliacao |
| 2 | Aider | Agente de Coding (CLI) | 5/5 | 5/5 | Em avaliacao |
| 3 | OpenHands (ex-OpenDevin) | Agente Autonomo | 3/5 | 4/5 | Em avaliacao |
| 4 | Goose (Block/Square) | Agente CLI | 3/5 | 4/5 | Pendente |
| 5 | AgenticSeek | Pesquisa + Execucao | 3/5 | 4/5 | Pendente |
| 6 | LangGraph + Ollama | Orquestracao Multi-Agente | 3/5 | 4/5 | Pendente |
| 7 | CrewAI + Ollama | Multi-Agente com Roles | 3/5 | 4/5 | Em avaliacao |
| 8 | AutoGen (Microsoft) | Multi-Agente Pesquisa | 2/5 | 3/5 | Pendente |
| 9 | Smolagents (HuggingFace) | Agente Leve | 4/5 | 3/5 | Pendente |
| 10 | n8n + Ollama | Orquestracao Visual | 5/5 | 5/5 | Implementado |
| 11 | Devstral Small 24B Q4_K_M | Modelo LLM | 3/5 | 5/5 | Em avaliacao |
| 12 | Qwen 3.5 14B Q4_K_M | Modelo LLM | 5/5 | 5/5 | Em avaliacao |
| 13 | Phi-4 14B Q4_K_M | Modelo LLM | 5/5 | 4/5 | Pendente |
| 14 | Qwen 2.5 Coder 14B Q4 | Modelo LLM (coding) | 5/5 | 5/5 | Pendente |
| 15 | Gemma 4 14B Q5 | Modelo LLM | 4/5 | 3/5 | Pendente |
| 16 | n8n como orquestrador SDLC | Infraestrutura | 5/5 | 5/5 | Em avaliacao |
| 17 | LiteLLM Proxy | Roteamento de Modelos | 3/5 | 4/5 | Pendente |
| 18 | AgentOps | Observabilidade | 3/5 | 3/5 | Pendente |
| 19 | Langfuse | Observabilidade LLM | 4/5 | 4/5 | Em avaliacao |
| 20 | Tabby | Code Completion Self-hosted | 3/5 | 3/5 | Pendente |
| 21 | vLLM | Servidor de Inferencia | 3/5 | 3/5 | Pendente |
| 22 | LiteLLM (proxy routing) | Proxy Multi-modelo | 3/5 | 4/5 | Pendente |
| 23 | Fallback hibrido local + API | Arquitetura | 4/5 | 4/5 | Pendente |
| 24 | SearXNG + Pipeline | Pesquisa no Discovery | 4/5 | 4/5 | Pendente |
| 25 | Qdrant + RAG | Contexto de Codebase | 4/5 | 4/5 | Pendente |
| 26 | Workflow 3 — Spec to UX Wireframe | Fase SDLC | 4/5 | 5/5 | Pendente |
| 27 | Workflow 4 — TDD Invertido (Spec → Testes → Código) | Fase SDLC | 5/5 | 5/5 | Pendente |

**Legenda de Status:** Pendente / Em avaliacao / Descartado / Implementado

**Legenda de Viabilidade:** 1=impraticavel no homelab atual, 5=plug-and-play

**Legenda de Relevancia:** 1=marginal para o ciclo SDLC, 5=cobre fase critica

---

## Detalhes por Item

### 1. OpenCode
- Stars: ~162k (GitHub)
- Descricao: substituto do Claude Code, terminal-native, TUI, suporta 75+ providers incluindo Ollama
- Por que avaliar: interface similar ao Claude Code, zero config com Ollama local
- Risco: projeto novo, pode ter instabilidades; base de stars e comunidade grande mas historico curto

### 2. Aider
- Stars: ~44k (GitHub)
- Licenca: Apache-2.0
- Descricao: agente de coding via terminal, git-native, faz commits com mensagens explicativas automaticamente
- Por que avaliar: maduro, estavel, boa integracao com git, facil de integrar no CI
- Risco: sem TUI interativa como Claude Code; exige bem mais prompt engineering

### 3. OpenHands (ex-OpenDevin)
- Stars: ~74k (GitHub)
- Descricao: sandbox Docker, recebe uma tarefa e retorna PRs prontos, loop autonomo completo
- Por que avaliar: o mais autonomo da lista — da tarefa, recebe PR
- Risco: taxa de sucesso cai para 40-60% com modelos locais de 14B em tarefas abertas

### 4. Goose (Block/Square)
- Descricao: agente CLI desenvolvido pela Block/Square, trabalha com repositorios, edita arquivos, executa tarefas autonomas
- Por que avaliar: origem corporativa, mais robusto para ambientes reais
- Status: pendente de avaliacao — poucos relatos de uso com Ollama local

### 5. AgenticSeek
- Descricao: combina pesquisa web + execucao de codigo + memoria Redis + SearXNG
- Por que avaliar: unico item que integra pesquisa nativa ao agente; util para fase de Discovery
- Risco: complexidade de setup; depende de SearXNG e Redis rodando

### 6. LangGraph + Ollama
- Descricao: framework de grafo de estado para multi-agentes; melhor para producao, permite auditoria e rollback de estados
- Por que avaliar: mais robusto que CrewAI para producao; permite modelar o ciclo SDLC como grafo
- Risco: curva de aprendizado alta; overkill para homelab de uma pessoa

### 7. CrewAI + Ollama
- Descricao: framework multi-agente com roles definidos (PM, Architect, Dev, Reviewer)
- Por que avaliar: mais simples que LangGraph; roles mapeiam bem para fases do SDLC
- Risco: execucao serial em 1 GPU; modelos de 14B nem sempre aderem ao output estruturado esperado

### 8. AutoGen (Microsoft)
- Descricao: framework para conversas multi-agente, forte em pesquisa e experimentos
- Por que avaliar: suporte oficial da Microsoft, integracao com Ollama via adaptador
- Risco: mais voltado a pesquisa que producao; pouco adequado para ciclo continuo de desenvolvimento

### 9. Smolagents (HuggingFace)
- Descricao: o LLM escreve codigo Python para completar tarefas; abordagem "code as action"
- Por que avaliar: muito leve, baixo overhead, robusto para tarefas autonomas simples
- Risco: seguranca (executa codigo gerado pelo LLM diretamente); requer sandbox

### 10. n8n + Ollama
- Status: JA IMPLEMENTADO no homelab
- Integracao nativa via HTTP node ou node dedicado Ollama
- Base para Proposta B

### 11. Devstral Small 24B Q4_K_M
- Tamanho em disco/VRAM: ~13GB quantizado
- Benchmark: 68% SWE-bench (melhor modelo de coding open-source nesta faixa de tamanho)
- Risco: ocupa 13GB dos 16GB VRAM — apertado, sem margem para paralelismo; swap para RAM em contextos longos

### 12. Qwen 3.5 14B Q4_K_M
- Tamanho em VRAM: ~8GB
- Uso: raciocinio geral, planning, specs, discovery
- Vantagem: sobra 8GB de VRAM — pode rodar ComfyUI em contextos menores simultaneamente

### 13. Phi-4 14B Q4_K_M
- Tamanho em VRAM: ~8GB
- Uso: forte especificamente em coding e matematica
- Candidato para fase spec-to-code se Devstral Small for apertado demais

### 14. Qwen 2.5 Coder 14B Q4
- Uso: especializado em codigo, melhor que Qwen 3.5 14B para tarefas puras de coding
- Candidato como modelo principal para fase 06-spec-to-code

### 15. Gemma 4 14B Q5
- Tamanho em VRAM: ~12GB com Q5
- Origem: Google DeepMind
- Uso: raciocinio geral — menos vantagens especificas para SDLC vs Qwen 3.5 14B

### 16-17. n8n como orquestrador + LiteLLM Proxy
- Ver proposals/B e proposals/C para detalhes

### 18. AgentOps
- Descricao: plataforma de observabilidade para agentes LLM, self-hostable
- Risco: documentacao de self-hosting menos madura que Langfuse; comunidade menor

### 19. Langfuse
- Ver proposals/F para detalhes
- Candidato preferido para observabilidade vs AgentOps

### 20. Tabby
- Descricao: servidor self-hosted de code completion para equipes e ambientes air-gap
- Uso potencial: completar o ambiente de desenvolvimento sem depender de Copilot/Codeium
- Avaliacao: baixa prioridade — substituido funcionalmente por OpenCode/Aider para o homelab

### 21. vLLM
- Descricao: servidor de inferencia mais rapido que Ollama para workloads agênticos (batching, throughput)
- Risco: compatibilidade com RTX 5060 Ti ainda em avaliacao; Ollama ja suficiente para 1 usuario
- Potencial: trocar Ollama por vLLM se latencia virar gargalo

### 22. LiteLLM (routing)
- Descricao: proxy que expoe interface OpenAI-compatible e roteia para multiplos backends (Ollama, Anthropic API, etc.)
- Uso: modelo de fallback hibrido (item 23)

### 23. Fallback hibrido local + API
- Descricao: 90% das chamadas vao para Ollama local; casos complexos escalam para Claude API
- Estimativa de economia: 90% dos tokens em relacao a uso 100% de API
- Implementacao: via LiteLLM com regra de roteamento por comprimento de contexto ou tipo de tarefa

### 24. SearXNG + Pipeline
- Descricao: motor de busca self-hosted; integrado ao pipeline de discovery para pesquisa orientada a dados
- Integracao sugerida: n8n chama SearXNG API, passa resultados ao LLM para sintese

### 26. Workflow 3 — Spec to UX Wireframe
- **Tipo:** Fase SDLC (novo workflow n8n)
- **Relevancia:** 5/5 — fecha o gap entre PRD e implementação visual
- **Viabilidade:** 4/5 — mesmo padrão dos Workflows 1 e 2 (Code node + HTTP Request + Ollama)
- **Descricao:** Workflow n8n que recebe o PRD do Workflow 1 e gera componentes de UI navegáveis antes da fase de código. LLM produz HTML/Tailwind ou React/TSX com layout de telas, navegação entre páginas, e dados mockados. Usuário valida o fluxo visual antes de commitar a implementação.
- **Abordagem recomendada:** Prompt no estilo "você é um frontend designer sênior — dado este PRD, produza as telas principais como HTML+Tailwind standalone, uma tela por arquivo, separadas por ---FILE---". Mesmo parser do Workflow 2.
- **Alternativas avaliadas:** Bolt.new self-hosted (pendente maturidade offline), Lovable (cloud-only), v0 (cloud-only).
- **Pré-requisito:** Task 7 validada — confirmar que o fluxo Discovery → Spec → Code está estável antes de adicionar fase de UX.

### 27. Workflow 4 — TDD Invertido (Spec → Testes → Código)

- **Tipo:** Fase SDLC (novo workflow n8n)
- **Relevância:** 5/5 — resolve o problema de circularidade do WF3 (mesmo LLM gera código e testes)
- **Viabilidade:** 5/5 — mesmo padrão do WF3, apenas inverte a ordem e usa agentes separados

**Problema que resolve:**

No WF3 atual, o mesmo modelo (`qwen2.5-coder:32b`) gera `routes.py` e depois `test_main.py`.
Se o código estiver errado, os testes tendem a refletir o mesmo erro — circularidade.
Exemplo real desta sessão: `revenue_cents: 800` (errado) gerado tanto no código quanto no teste.

**Como funciona o TDD invertido:**

```
spec.md
  │
  ├─→ [WF4a — Test Agent]  ← lê só a spec, nunca vê o código
  │     qwen3-coder:30b (modelo de reasoning, não coding)
  │     Papel: QA Engineer sênior
  │     Output: test_main.py com asserções baseadas nos AC da spec
  │     (ex: "AC-03 diz taxa 8% → assert revenue == amount * 0.92")
  │
  └─→ [WF4b — Code Agent]  ← lê spec + test_main.py gerado
        qwen2.5-coder:32b
        Papel: Developer que implementa para passar os testes
        Output: models.py + routes.py + main.py
              ↓
           pytest → prova que Code Agent satisfaz Test Agent
                    sem que um soubesse o que o outro faria
```

**Por que usar modelos diferentes (opcional mas recomendado):**
- `qwen3-coder:30b` no Test Agent: melhor em reasoning e interpretação de critérios
- `qwen2.5-coder:32b` no Code Agent: melhor em geração de código funcional
- Mesmo usando o mesmo modelo, a separação de contexto já elimina a circularidade

**Implementação no n8n:**

```
WF4a: Webhook → PrepareTestPrompt → CallOllama(30b) → ParseTests → Respond
WF4b: Webhook → PrepareCodePrompt(spec + tests) → CallOllama(32b) × 3 → Respond

generate-tdd.sh:
  1. Chama WF4a → salva test_main.py
  2. Chama WF4b com spec + test_main.py → salva models.py, routes.py, main.py
  3. pytest test_main.py → resultado
```

**Métrica de sucesso:** testes escritos pelo Test Agent passando no código do Code Agent, sem nenhum fix manual de asserção de valor.

**Diferença para WF3:**
- WF3: `[spec] → [código] → [testes]` — testes validam o código
- WF4: `[spec] → [testes] → [código]` — código é forçado a satisfazer testes independentes

### 25. Qdrant + RAG
- Descricao: banco vetorial self-hosted; permite recuperar contexto de codebase longa sem estourar janela de contexto
- Uso: fase 06-spec-to-code com codebases grandes; fase 01-discovery com historico de decisoes

---

## Como Adicionar Novas Ideias

O agente `weekly-sdlc-research` executa via systemd toda sexta-feira às 19h e pode
popular automaticamente novos itens neste arquivo. Para adicionar manualmente:

1. Atribuir o proximo numero sequencial
2. Preencher: Nome, Tipo, Viabilidade (1-5), Relevancia (1-5), Status inicial = Pendente
3. Adicionar secao de detalhes abaixo da tabela
4. Commit com mensagem: `docs: add [nome] to sdlc-agentico backlog`

Criterios de Viabilidade para o homelab atual:
- 5: funciona hoje, sem configuracao extra
- 4: funciona com configuracao simples (1-2h de setup)
- 3: funciona mas exige tradeoffs (latencia, VRAM, complexidade)
- 2: funciona com workarounds significativos
- 1: impraticavel nas restricoes atuais (hardware, licenca, etc.)

---

## Itens Descartados

| Ferramenta | Razao do Descarte | Data |
|---|---|---|
| Cline | Testado pelo usuario — experiencia ruim; nao retomar | jun/2026 |
| Continue.dev | Testado pelo usuario — experiencia ruim; nao retomar | jun/2026 |

Detalhes adicionais em [feedback.md](../feedback.md).

---

## Proximas Pesquisas Sugeridas

- **Bolt.new self-hosted (StackBlitz):** editor web com agente integrado — avaliar se tem modo offline
- **Cursor com Ollama backend:** avaliar se a versao paga permite custom API endpoint apontando para Ollama
- **Jan.ai:** cliente desktop para LLMs locais com suporte a plugins de agentes
- **Plandex:** sistema de agente de coding orientado a planos de longo prazo, git-native
- **Letta (ex-MemGPT):** adiciona memoria persistente de longo prazo aos agentes — relevante para fechar o loop do SDLC
- **LocalAI:** alternativa ao Ollama com suporte a mais backends e modelos multimodais

---

## Novos itens pendentes de avaliacao

### Pesquisa de 2026-09-04

### Observer AI
- **Tipo:** orchestrator
- **Relevancia SDLC:** 3/5
- **Viabilidade HW:** 4/5
- **Descricao:** An open-source local automation agent framework that provides infrastructure for agent behavior, useful for managing multiple agents in a development workflow.
- **Fonte:** https://fast.io/resources/top-10-open-source-ai-agents/

### Agent Orchestrator (AO)
- **Tipo:** orchestrator
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 4/5
- **Descricao:** A full-automation system that allows multiple agents to run in isolated worktrees, each with its own PR, supervised from a central interface.
- **Fonte:** https://www.augmentcode.com/tools/open-source-agent-orchestrators


### Pesquisa de 2026-08-28

### Nimbalyst
- **Tipo:** orchestrator
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 5/5
- **Descricao:** Nimbalyst is an open-source agent orchestrator that supports local-first workflows and integrates with LLMs for AI coding tasks.
- **Fonte:** https://www.augmentcode.com/tools/open-source-agent-orchestrators

### Meta 30B Agentic Model
- **Tipo:** model
- **Relevancia SDLC:** 5/5
- **Viabilidade HW:** 5/5
- **Descricao:** Meta's 30B agentic model is optimized for local deployment on consumer GPUs, enabling powerful coding and automation capabilities.
- **Fonte:** https://pinggy.io/blog/best_open_source_self_hosted_llms_for_coding/


### Pesquisa de 2026-08-07

### OpenJarvis
- **Tipo:** coding_agent
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 3/5
- **Descricao:** An open-source framework for building personal AI agents that run on your own hardware, with Ollama integration.
- **Fonte:** https://ollama.com/blog/openjarvis

### Warp
- **Tipo:** orchestrator
- **Relevancia SDLC:** 5/5
- **Viabilidade HW:** 3/5
- **Descricao:** An open platform for building software with agents, supports cloud and local development.
- **Fonte:** https://www.warp.dev/


### Pesquisa de 2026-07-20

### Kimi K2.6
- **Tipo:** model
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 3/5
- **Descricao:** A strong local LLM for coding with a MoE architecture, suitable for agentic tasks.
- **Fonte:** https://www.promptquorum.com/local-llms/best-local-llms-for-coding

### Codestral 22B
- **Tipo:** model
- **Relevancia SDLC:** 3/5
- **Viabilidade HW:** 4/5
- **Descricao:** A dense model for IDE autocomplete, running locally with good performance.
- **Fonte:** https://www.promptquorum.com/local-llms/best-local-llms-for-coding

### DeepSeek V4
- **Tipo:** model
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 3/5
- **Descricao:** A strong performer for agentic coding tasks, especially suitable for self-hosting teams.
- **Fonte:** https://www.mindstudio.ai/blog/best-open-source-llms-agentic-coding-2026

### Dify
- **Tipo:** orchestrator
- **Relevancia SDLC:** 5/5
- **Viabilidade HW:** 4/5
- **Descricao:** A platform combining visual workflow building, RAG pipelines, AI agents, and prompt engineering.
- **Fonte:** https://blog.canadianwebhosting.com/open-source-ai-tools-self-hosting-2026/

### OpenClaw
- **Tipo:** coding_agent
- **Relevancia SDLC:** 4/5
- **Viabilidade HW:** 3/5
- **Descricao:** A self-hosted AI agent that can use local models or cloud APIs, focusing on developer experience.
- **Fonte:** https://getclawdbot.com/blog/self-hosted-ai-agent-complete-guide-2026/

### Gemma 4 26B A4B
- **Tipo:** model
- **Relevancia SDLC:** 3/5
- **Viabilidade HW:** 2/5
- **Descricao:** A strong default for local coding, suitable for more powerful hardware setups.
- **Fonte:** https://huggingface.co/blog/daya-shankar/open-source-llms


### Pesquisa de 2026-06-18

### KodeOps
- **Tipo:** infrastructure
- **Relevancia SDLC:** 5/5
- **Viabilidade HW:** 3/5
- **Descricao:** An open source CLI and TUI tool that automates the software development lifecycle from concept to structured backlog using agentic AI.
- **Fonte:** https://github.com/your-repo/kodeops


_Itens descobertos pela pesquisa semanal automatica. Adicionados toda sexta-feira._
