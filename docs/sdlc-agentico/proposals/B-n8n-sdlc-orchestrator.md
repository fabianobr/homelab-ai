# Proposta B — n8n como Orquestrador do SDLC

**Prioridade:** Alta
**Viabilidade no homelab:** 5/5
**Relevancia para o SDLC:** 5/5
**Status:** Em avaliacao

---

## Resumo

Usar o n8n (ja instalado no homelab) como orquestrador central do ciclo SDLC agêntico. Cada fase do ciclo se torna um workflow n8n independente e reutilizavel. O n8n chama o Ollama via HTTP para processar cada fase, dispara agentes de coding como subprocessos, e alimenta o Langfuse com eventos de observabilidade.

---

## Por Que n8n Como Orquestrador

O n8n ja esta rodando no homelab e tem suporte nativo a Ollama via node dedicado (ou HTTP Request node apontando para `http://ollama:11434`). A abordagem de "cada fase = um workflow" tem vantagens claras:

- **Versionamento:** workflows n8n podem ser exportados como JSON e commitados no repositorio
- **Observabilidade visual:** o historico de execucoes do n8n registra cada passo automaticamente
- **Composabilidade:** um workflow pode chamar outro (sub-workflows), permitindo reuso
- **Sem dependencia de framework:** nao precisa instalar LangGraph, CrewAI, etc. — o n8n e a cola
- **Human-in-the-loop nativo:** o n8n tem nodes de "Wait for approval" que pausam o fluxo ate aprovacao humana via webhook

---

## Arquitetura de Orquestracao

```
+---------------------------------------------------------------+
|                          n8n                                  |
|                                                               |
|  [Workflow: 01-Discovery]                                     |
|     Trigger: manual ou webhook                                |
|     -> HTTP: Ollama (sintese de contexto)                     |
|     -> HTTP: SearXNG (pesquisa web)                           |
|     -> Output: contexto formatado para fase 02               |
|                                                               |
|  [Workflow: 02-Hipoteses]                                     |
|     Trigger: webhook recebe output da fase 01                 |
|     -> HTTP: Ollama (gera hipoteses testáveis)               |
|     -> Output: lista de hipoteses + metricas alvo             |
|                                                               |
|  [Workflow: 05-Specs]                                         |
|     Trigger: webhook com output de arquitetura                |
|     -> HTTP: Ollama (gera PRD + spec tecnica)                 |
|     -> Output: spec formatada para fase 06                    |
|                                                               |
|  [Workflow: 06-Spec-to-Code]                                  |
|     Trigger: webhook recebe spec                              |
|     -> Execute Command: aider --message "{{ spec }}"          |
|     -> Git: verifica commits criados                          |
|     -> HTTP: Langfuse (log de execucao)                       |
|     -> Webhook: dispara workflow 07                           |
|                                                               |
|  [Workflow: 07-CI-CD]                                         |
|     Trigger: webhook ou push no git                           |
|     -> HTTP: GitHub Actions API (dispara pipeline)            |
|     -> Wait for Webhook (aguarda resultado do CI)             |
|     -> HTTP: Langfuse (resultado do deploy)                   |
+---------------------------------------------------------------+
           |                    |                    |
           v                    v                    v
      +--------+          +----------+          +----------+
      | Ollama |          |  Agente  |          | Langfuse |
      | (LLMs) |          | (Aider/  |          | (Obs.)   |
      +--------+          |  OHands) |          +----------+
                          +----------+
```

---

## Pros

- n8n ja esta instalado no homelab — zero overhead de infra
- Suporte nativo a Ollama (node dedicado ou HTTP Request)
- Visual: cada fase do SDLC e visivel e auditavel no dashboard
- Cada workflow e exportavel como JSON e versionavel no git
- Nao e um agente autonomo — e uma orquestracao de etapas controladas (mais seguro)
- Human-in-the-loop facil: node "Wait for Webhook" pausa entre fases para aprovacao
- Pode disparar agentes de coding (Aider, OpenHands) como Execute Command nodes
- Historico de execucoes serve como log natural do ciclo SDLC

## Contras

- Nao e um agente autonomo: cada transicao de fase exige modelagem explicitia no workflow
- Sem memoria nativa de longo prazo entre execucoes de fases diferentes (workaround: passar contexto acumulado via payload de webhook, ou usar arquivo JSON em disco)
- Exige modelar bem cada workflow — a qualidade do ciclo depende da qualidade dos prompts e da modelagem
- Erro em um workflow pode quebrar a cadeia sem rollback automatico

---

## Fases do SDLC Cobertas

| Fase | Como o n8n Cobre |
|---|---|
| 01 — Discovery | Workflow que busca contexto, chama Ollama, sintetiza |
| 02 — Hipoteses | Workflow que recebe contexto e gera hipoteses testáveis |
| 03 — UX Design | Workflow que gera user stories e wireframes em texto |
| 04 — Arquitetura | Workflow que gera ADRs e diagramas mermaid via Ollama |
| 05 — Specs | Workflow que gera PRD e spec tecnica |
| 06 — Spec to Code | Workflow que chama Aider ou OpenHands como subprocesso |
| 07 — CI/CD | Workflow que dispara e monitora GitHub Actions |
| 08 — Monitoring | Workflow que coleta metricas e chama Langfuse |
| 09 — Feedback Loop | Workflow que analisa metricas e dispara novo Discovery |

O n8n cobre todas as fases — seja executando diretamente (via HTTP Request ao Ollama) ou delegando (via Execute Command para agentes de coding).

---

## Exemplo: Workflow de Discovery (fase 01)

```json
{
  "name": "01 - SDLC Discovery",
  "nodes": [
    {
      "name": "Trigger Manual",
      "type": "n8n-nodes-base.manualTrigger",
      "parameters": {}
    },
    {
      "name": "Input: Contexto do Projeto",
      "type": "n8n-nodes-base.set",
      "parameters": {
        "values": {
          "projeto": "homelab-ai",
          "foco": "{{ $json.foco }}",
          "historico": "{{ $json.historico_resumido }}"
        }
      }
    },
    {
      "name": "Ollama: Sintese de Discovery",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://ollama:11434/api/generate",
        "body": {
          "model": "qwen3.5:14b",
          "prompt": "Voce é um Product Manager agêntico. Dado o contexto do projeto {{ $json.projeto }} e o foco atual {{ $json.foco }}, sintetize os principais problemas a resolver, oportunidades identificadas e hipoteses iniciais. Seja conciso e estruturado.",
          "stream": false
        }
      }
    },
    {
      "name": "Formatar Output",
      "type": "n8n-nodes-base.set",
      "parameters": {
        "values": {
          "discovery_output": "{{ $json.response }}",
          "fase": "01-discovery",
          "timestamp": "{{ $now }}"
        }
      }
    },
    {
      "name": "Disparar Fase 02",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://n8n:5678/webhook/02-hipoteses",
        "body": "{{ $json }}"
      }
    }
  ]
}
```

---

## Exemplo: Workflow de Spec-to-Code (fase 06)

```json
{
  "name": "06 - Spec to Code",
  "nodes": [
    {
      "name": "Webhook: Recebe Spec",
      "type": "n8n-nodes-base.webhook",
      "parameters": {
        "path": "06-spec-to-code",
        "method": "POST"
      }
    },
    {
      "name": "Formatar Prompt Aider",
      "type": "n8n-nodes-base.set",
      "parameters": {
        "values": {
          "aider_message": "Implemente a seguinte spec: {{ $json.spec_tecnica }}. Siga as convencoes do arquivo ARCHITECTURE.md. Faca commits atomicos por arquivo alterado."
        }
      }
    },
    {
      "name": "Executar Aider",
      "type": "n8n-nodes-base.executeCommand",
      "parameters": {
        "command": "cd /path/to/project && aider --model ollama/devstral --message \"{{ $json.aider_message }}\" --yes --no-stream 2>&1"
      }
    },
    {
      "name": "Verificar Commits",
      "type": "n8n-nodes-base.executeCommand",
      "parameters": {
        "command": "cd /path/to/project && git log --oneline -5"
      }
    },
    {
      "name": "Log no Langfuse",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://langfuse:3000/api/public/traces",
        "headers": {
          "Authorization": "Bearer {{ $env.LANGFUSE_API_KEY }}"
        },
        "body": {
          "name": "spec-to-code",
          "input": "{{ $json.spec_tecnica }}",
          "output": "{{ $json.commits_criados }}",
          "metadata": {
            "modelo": "devstral",
            "fase": "06-spec-to-code"
          }
        }
      }
    },
    {
      "name": "Disparar CI/CD",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://n8n:5678/webhook/07-cicd",
        "body": "{{ $json }}"
      }
    }
  ]
}
```

---

## Configuracao da Integracao com Ollama via HTTP Node

```
URL: http://ollama:11434/api/generate
Metodo: POST
Content-Type: application/json

Body:
{
  "model": "qwen3.5:14b",
  "prompt": "{{ seu_prompt }}",
  "system": "{{ system_prompt_da_fase }}",
  "stream": false,
  "options": {
    "temperature": 0.3,
    "num_ctx": 8192
  }
}

Extrair da resposta: $.response
```

Se o Ollama estiver no mesmo Docker network (`homelab-network`), usar `http://ollama:11434`. Se estiver em host separado, usar `http://IP_DO_HOST:11434`.

---

## Escalabilidade: Sub-Workflows Reutilizaveis

Cada fase pode ser decomposta em sub-workflows reutilizaveis. Por exemplo:

- `sub-ollama-call`: encapsula a chamada ao Ollama com retry e error handling
- `sub-langfuse-log`: log padrao para o Langfuse com metadata de fase
- `sub-git-status`: verifica status do repositorio apos acao do agente

Esses sub-workflows sao chamados pelos workflows de fase via o node "Execute Workflow" do n8n, garantindo que logica de retry e log seja consistente em todo o ciclo.

---

## Estrategia de Memoria entre Fases

O n8n nao tem memoria nativa entre execucoes de workflows diferentes. Estrategias para contornar:

1. **Payload acumulado via webhook:** cada fase passa para a proxima um JSON que acumula os outputs de todas as fases anteriores. Simples mas pode crescer muito.

2. **Arquivo de estado em disco:** n8n escreve e le um arquivo JSON em `/data/sdlc-state/current-cycle.json`. Cada fase atualiza o arquivo com seu output.

3. **Qdrant + RAG (futuro):** armazenar embeddings dos outputs de cada fase no Qdrant. O n8n recupera contexto relevante antes de chamar o Ollama em cada nova fase.

Para comecar, a estrategia 2 (arquivo de estado em disco) e a mais simples e suficiente.
