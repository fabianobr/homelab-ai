# Backlog de Pesquisa — SDLC Agêntico

Este arquivo registra todas as ferramentas, modelos e tecnologias pesquisadas para o ciclo SDLC agêntico local. Atualizado semanalmente via job n8n.

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

### 25. Qdrant + RAG
- Descricao: banco vetorial self-hosted; permite recuperar contexto de codebase longa sem estourar janela de contexto
- Uso: fase 06-spec-to-code com codebases grandes; fase 01-discovery com historico de decisoes

---

## Como Adicionar Novas Ideias

O job semanal do n8n executa toda segunda-feira e pode popular automaticamente novos itens neste arquivo. Para adicionar manualmente:

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

_Itens descobertos pela pesquisa semanal automatica. Adicionados toda segunda-feira._

