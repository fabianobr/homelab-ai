# SDLC Agêntico Local com LLMs

## Pergunta central

**É possível ter um ambiente 100% agêntico estilo Claude Code com LLMs locais no homelab?**

**Resposta curta:** Sim, para aproximadamente 80% dos casos de uso cotidianos. O gap real está em raciocínio complexo multi-arquivo, tarefas que exigem planejamento de longo horizonte, e coordenação de agentes paralelos — nesses cenários, modelos locais de 14-24B ficam entre 40% e 80% da qualidade de modelos frontier como Claude 4.5 Sonnet. Para tarefas bem definidas (bugfix isolado, geração de boilerplate, refactoring localizado, geração de specs a partir de contexto estruturado), a paridade é alta.

---

## Hardware do Homelab

| Componente | Especificacao |
|---|---|
| GPU | NVIDIA RTX 5060 Ti — 16GB VRAM |
| RAM | 32GB DDR5 |
| SO | Ubuntu 26.04 LTS |
| Armazenamento | NVMe (SSD primario) |

### Servicos em execucao (Docker Compose)

| Servico | Funcao |
|---|---|
| Ollama | Servidor de inferencia local — carrega e serve LLMs |
| Open WebUI | Interface web para chat com modelos Ollama |
| n8n | Orquestrador visual de workflows — ja integrado ao Ollama |
| ComfyUI | Geracao de imagens com Stable Diffusion (GPU RTX 5060 Ti) |

---

## Ciclo SDLC Agêntico Completo

```
+------------------+
|   09-FEEDBACK    |<-----------------------------------------+
|   LOOP           |                                          |
| (Oportunidades)  |                                          |
+--------+---------+                                          |
         |                                                    |
         v                                                    |
+------------------+     +------------------+                 |
|   01-DISCOVERY   +---->|  02-HIPOTESES    |                 |
|                  |     |  + DADOS         |                 |
+------------------+     +--------+---------+                 |
                                  |                           |
                                  v                           |
+------------------+     +------------------+                 |
|   04-ARQUITETURA |<----+  03-UX DESIGN    |                 |
|                  |     |                  |                 |
+--------+---------+     +------------------+                 |
         |                                                    |
         v                                                    |
+------------------+     +------------------+                 |
|   05-SPECS       +---->|  06-SPEC TO CODE |                 |
|   (PRD + Tecnica)|     |  (Agente Coding) |                 |
+------------------+     +--------+---------+                 |
                                  |                           |
                                  v                           |
                         +------------------+                 |
                         |   07-CI/CD +     |                 |
                         |   DEPLOY         |                 |
                         +--------+---------+                 |
                                  |                           |
                                  v                           |
                         +------------------+                 |
                         |   08-MONITORING  +----------------+
                         |   KPIs + OBS     |
                         +------------------+
```

Cada fase tem um arquivo dedicado em `sdlc-phases/` com prompts, ferramentas e integracoes recomendadas.

---

## Stack Arquitetural Recomendado

```
+--------------------------------------------------------+
|                    n8n (Orquestrador)                  |
|  [Workflow: Discovery] [Workflow: Specs] [Workflow: CI] |
+----+-------------------+-------------------+-----------+
     |                   |                   |
     v                   v                   v
+----------+      +------------+      +-------------+
|  Ollama  |      |  Agente de |      |  Langfuse   |
|  (LLMs)  |      |  Coding    |      |  (Observ.)  |
|          |      | (OpenCode/ |      |             |
| Qwen14B  |      |  Aider/    |      | Rastreia    |
| Devstral |      |  OpenHands)|      | decisoes    |
+----------+      +------------+      +-------------+
     |
     v
+----------+
| LiteLLM  |
|  Proxy   |
| (routing)|
+----------+
```

O n8n atua como orquestrador central: dispara fases, chama Ollama via HTTP, aciona agentes de coding como subprocessos, e alimenta o Langfuse com eventos para fechar o loop de observabilidade.

---

## Propostas avaliadas

| ID | Nome | Prioridade | Viabilidade |
|---|---|---|---|
| [A](proposals/A-coding-agent-stack.md) | Stack de Coding Agêntico Basico | Alta | 4/5 |
| [B](proposals/B-n8n-sdlc-orchestrator.md) | n8n como Orquestrador do SDLC | Alta | 5/5 |
| [C](proposals/C-model-routing.md) | Roteamento por Modelos Especialistas | Media | 3/5 |
| [D](proposals/D-openhands-autonomo.md) | OpenHands para Autonomia Completa | Media | 3/5 |
| [E](proposals/E-crewai-langgraph.md) | CrewAI/LangGraph para Pipeline Completo | Media | 2/5 |
| [F](proposals/F-observability-langfuse.md) | Observabilidade com Langfuse | Media | 4/5 |

---

## Fases do SDLC

| Fase | Arquivo | Cobertura por LLMs locais |
|---|---|---|
| 01 — Discovery | [sdlc-phases/01-discovery.md](sdlc-phases/01-discovery.md) | Alta — analise e sintese de contexto |
| 02 — Hipoteses + Dados | [sdlc-phases/02-hypotheses-data.md](sdlc-phases/02-hypotheses-data.md) | Media — formulacao de hipoteses ok, coleta depende de integracoes |
| 03 — UX Design | [sdlc-phases/03-ux-design.md](sdlc-phases/03-ux-design.md) | Media — wireframes em texto, user stories, sem imagens nativas |
| 04 — Arquitetura | [sdlc-phases/04-architecture.md](sdlc-phases/04-architecture.md) | Media-Alta — ADRs e diagramas mermaid, limitado em sistemas grandes |
| 05 — Specs | [sdlc-phases/05-specs.md](sdlc-phases/05-specs.md) | Alta — PRDs e specs tecnicas bem estruturadas |
| 06 — Spec to Code | [sdlc-phases/06-spec-to-code.md](sdlc-phases/06-spec-to-code.md) | Media-Alta — 70-80% paridade com frontier para tarefas bem definidas |
| 07 — CI/CD + Deploy | [sdlc-phases/07-cicd-deploy.md](sdlc-phases/07-cicd-deploy.md) | Media — geracao de YAML, review de pipelines |
| 08 — Monitoring + KPIs | [sdlc-phases/08-monitoring-kpis.md](sdlc-phases/08-monitoring-kpis.md) | Media — analise de logs, deteccao de anomalias simples |
| 09 — Feedback Loop | [sdlc-phases/09-feedback-loop.md](sdlc-phases/09-feedback-loop.md) | Media — priorizacao e sintese de oportunidades |

---

## Backlog e Ferramentas

Ver [backlog.md](backlog.md) para lista completa de 25 ferramentas e tecnologias pesquisadas.

Ver [feedback.md](feedback.md) para registro do que foi testado e descartado.

---

## Status

- Pesquisa iniciada: junho/2026
- Job semanal de pesquisa: ativo (n8n — busca novidades em ferramentas agênticas)
- Proxima acao recomendada: implementar Proposta A (OpenCode ou Aider + Devstral Small) e Proposta B (mapear fases SDLC como workflows n8n)
- Revisao agendada: mensal
