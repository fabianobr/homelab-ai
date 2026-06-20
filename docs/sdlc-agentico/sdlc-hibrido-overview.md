# SDLC Híbrido — Visão Geral de Arquitetura

> Última atualização: 2026-06-20  
> Hardware: RTX 5060 Ti 16 GB VRAM · Ubuntu · Ollama + Docker Compose  
> Status: Operacional

---

## 1. O que é o SDLC Híbrido?

Um pipeline de desenvolvimento de software onde **cada fase é executada pelo modelo com melhor custo-benefício** para aquela tarefa específica — não por um único modelo tentando fazer tudo.

O princípio central é **roteamento por ambiguidade**:

| Ambiguidade | Exemplo de tarefa | Modelo ideal |
|---|---|---|
| **Alta** | Interpretar uma descrição vaga, decidir o que construir, avaliar qualidade | Claude Sonnet (cloud) |
| **Baixa** | Gerar código a partir de spec estruturada, escrever testes de ACs explícitos | Ollama local (gratuito) |

Resultado: ~$0.04–0.07 por feature completa (vs $0.50–2.00 tudo-Claude ou $0 com mais fixes manuais tudo-local).

---

## 2. C4 — Nível 1: Contexto do Sistema

```mermaid
C4Context
  title SDLC Híbrido — Contexto (C4 L1)

  Person(op, "Operador", "Você: descreve o produto,\nanalisa resultados, itera")

  System(sdlc, "SDLC Híbrido", "Pipeline que transforma uma\ndescriçao em código testado.\nMix de IA local + cloud.")

  System_Ext(claude, "Anthropic Claude API", "Julgamento, ambiguidade,\nreview de qualidade")
  System_Ext(ollama, "Ollama (GPU local)", "Geração de código e testes.\nGratuito. 100% privado.")

  Rel(op, sdlc, "Descreve feature /sdlc-hybrid\nou via scripts bash")
  Rel(sdlc, claude, "Discovery e Review\n~3 chamadas/feature")
  Rel(sdlc, ollama, "Test gen, Code gen, Fix\n~10-15 chamadas/feature")
  Rel(sdlc, op, "Spec, código, pytest result,\nrelatório de custo")
```

**O que o operador vê:** uma descrição em linguagem natural entra, código FastAPI testado e aprovado pelo pytest sai. O roteamento entre Claude e Ollama é transparente.

---

## 3. C4 — Nível 2: Containers

```mermaid
C4Container
  title SDLC Híbrido — Containers (C4 L2)

  Person(op, "Operador")

  Container_Boundary(local, "Homelab (Docker Compose)") {

    Container(oc, "opencode TUI/CLI", "Node.js binary", "Entry point interativo.\nComando /sdlc-hybrid.\nAgente orquestrador (Claude)")

    Container(n8n, "n8n 2.23.3", "Docker :5678", "Orquestrador de fluxo.\nWF1-WF5: webhooks REST.\nSem acesso à rede nos Code nodes.")

    Container(litellm, "LiteLLM Gateway", "Docker :4000\nghcr.io/berriai/litellm", "Gateway de modelos.\nRoteamento por alias.\nFallback automático.\nTracking de custo.")

    Container(ollama, "Ollama", "Docker :11434\nRTX 5060 Ti 16GB", "Inferência local.\nqwen3-coder:30b (codegen)\nqwen2.5-coder:32b (tests)\nqwen3:14b (fix)")
  }

  System_Ext(claude_api, "Anthropic API", "claude-sonnet-4-6")

  Rel(op, oc, "opencode run\n--command sdlc-hybrid")
  Rel(oc, n8n, "curl POST /webhook/\nsdlc-poc-chat (WF1)")
  Rel(oc, n8n, "bash: generate-tdd.sh\n→ chama WF3/WF5/WF4")

  Rel(n8n, litellm, "HTTP POST /v1/chat/completions\nmodel: sdlc-discovery | sdlc-fix")
  Rel(n8n, ollama, "HTTP POST /api/chat\nmodel: qwen3-coder:30b (WF3/WF5)")

  Rel(litellm, claude_api, "model: anthropic/\nclaude-sonnet-4-6")
  Rel(litellm, ollama, "model: ollama/qwen3:14b\n(sdlc-fix)")
```

### Responsabilidades por container

| Container | Responsabilidade | O que NÃO faz |
|---|---|---|
| **opencode** | Entry point interativo; orquestração bash; relatório | Não gera código diretamente |
| **n8n** | Sequenciamento de fases; system prompts especializados; retry | Não decide qual modelo usar (isso é o LiteLLM) |
| **LiteLLM** | Roteamento por alias; fallback; unified cost tracking | Não orquestra fases |
| **Ollama** | Inferência GPU local pura | Não tem sistema de fallback |

---

## 4. O Ciclo SDLC — Visão de Processo

```mermaid
flowchart TD
    IN([🧑 Operador: descreve o produto])

    subgraph DISCOVERY["Fase 1 — Discovery (Claude Sonnet)"]
        D1["WF1: PM Agent\nconversa estruturada em 4 estágios\nDiscovery → Hipóteses → Métricas → Spec"]
        D2["spec.md\n---SPEC-START/END---"]
    end

    subgraph TDD["Fase 2 — TDD Invertido (Ollama)"]
        T1["WF5: QA Agent\nLê só a spec, gera test_main.py\nSEM ver código algum"]
        T2["test_main.py\n1 teste por Critério de Aceite"]
    end

    subgraph CODEGEN["Fase 3 — Code Gen (Ollama)"]
        C1["WF3 [1/3] models.py\ncontexto: spec + testes"]
        C2["WF3 [2/3] routes.py\ncontexto: spec + testes + models"]
        C3["WF3 [3/3] main.py\ncontexto: spec + testes + models + routes"]
    end

    subgraph VALIDATE["Fase 4 — Validação + Auto-fix"]
        V1{pytest}
        V2["WF4: Fix Agent (Ollama qwen3:14b)\nDiagnóstico + patch cirúrgico"]
        V3{pytest novamente}
        V4["Fallback Claude\n(se 3 tentativas falharem)"]
    end

    OUT(["✅ Código testado\nFastAPI 100% pytest green"])

    IN --> D1 --> D2 --> T1 --> T2
    T2 --> C1 --> C2 --> C3
    C3 --> V1
    V1 -->|✓ passou| OUT
    V1 -->|✗ falhou| V2 --> V3
    V3 -->|✓ passou| OUT
    V3 -->|✗ 3x falhou| V4 --> V3

    style DISCOVERY fill:#2d1515,color:#ffcccc,stroke:#aa4444
    style TDD fill:#1a2a3a,color:#ccddff,stroke:#4466aa
    style CODEGEN fill:#0d2d0d,color:#ccffcc,stroke:#44aa44
    style VALIDATE fill:#2a2a0d,color:#ffffcc,stroke:#aaaa44
```

### Por que TDD Invertido?

O QA Agent gera os testes **sem ver o código** — só a spec. Isso elimina a circularidade onde o mesmo modelo gera o código e os testes, validando suas próprias suposições. Com TDD Invertido, o código é **forçado a satisfazer um contrato escrito por um agente diferente**.

Resultado medido: 0 fixes manuais vs 2 fixes manuais no modo code-first.

---

## 5. Diagrama de Sequência — Caminho Feliz

```mermaid
sequenceDiagram
    actor Op as 🧑 Operador
    participant OC as opencode
    participant WF1 as n8n WF1<br/>(PM Agent)
    participant WF5 as n8n WF5<br/>(QA Agent)
    participant WF3 as n8n WF3<br/>(Developer)
    participant WF4 as n8n WF4<br/>(Fix Agent)
    participant LLM as LiteLLM<br/>:4000
    participant Claude as Anthropic<br/>Claude Sonnet
    participant Ollama as Ollama<br/>GPU Local

    Op->>OC: /sdlc-hybrid "app de tasks"

    Note over OC: Pré-verifica n8n, LiteLLM, Ollama

    OC->>WF1: POST /webhook/sdlc-poc-chat<br/>{chatInput: "Minha ideia: app de tasks\ngerar spec"}
    WF1->>LLM: POST /v1/chat/completions<br/>model: sdlc-discovery
    LLM->>Claude: anthropic/claude-sonnet-4-6<br/>~30s · ~$0.02
    Claude-->>LLM: spec.md com RF-01..RF-06
    LLM-->>WF1: OpenAI response format
    WF1-->>OC: {output: "---SPEC-START---...---SPEC-END---"}

    OC->>OC: extrai spec → /tmp/sdlc-spec-202506201430.md

    Note over OC,Ollama: Fase TDD — bash: ./generate-tdd.sh

    OC->>WF5: POST /webhook/sdlc-poc-spec-to-tests<br/>{spec: "..."}
    WF5->>Ollama: qwen2.5-coder:32b<br/>~190s
    Ollama-->>WF5: test_main.py (4 testes)
    WF5-->>OC: {filename:"test_main.py", content, lines:56}

    loop 3 arquivos: models → routes → main
        OC->>WF3: POST /webhook/sdlc-poc-spec-to-file<br/>{spec, filename, context:[testes + arquivos anteriores]}
        WF3->>Ollama: qwen3-coder:30b<br/>~50-180s por arquivo
        Ollama-->>WF3: arquivo gerado
        WF3-->>OC: {filename, content, lines}
    end

    OC->>OC: pytest test_main.py

    alt pytest falhou
        OC->>WF4: POST /webhook/sdlc-poc-fix<br/>{spec, pytest_output, files:[todos .py]}
        WF4->>LLM: POST /v1/chat/completions<br/>model: sdlc-fix
        LLM->>Ollama: qwen3:14b<br/>~85s
        Ollama-->>LLM: arquivo corrigido
        LLM-->>WF4: patch
        WF4-->>OC: {filename: "models.py", content}
        OC->>OC: pytest novamente → ✅ 4/4 passed
    end

    OC-->>Op: Relatório: spec, arquivos, pytest, tempo, custo ~$0.02
```

---

## 6. Use Cases — Perspectiva do Operador

```mermaid
graph LR
    Op(["🧑 Operador"])

    subgraph UC["Casos de Uso — SDLC Híbrido"]
        UC1["UC1: Gerar feature do zero\n/sdlc-hybrid 'descrição livre'"]
        UC2["UC2: Só Discovery\ncurl WF1 → extrai spec"]
        UC3["UC3: Só codegen\n./generate-tdd.sh spec.md"]
        UC4["UC4: Re-rodar fix loop\n./fix-loop.sh output/ spec.md"]
        UC5["UC5: Review de qualidade\ncurl WF6 (futuro)"]
        UC6["UC6: Comparar híbrido vs local\nrun-pipeline.sh vs run-hybrid.sh"]
    end

    Op --> UC1
    Op --> UC2
    Op --> UC3
    Op --> UC4
    Op --> UC5
    Op --> UC6
```

### Como cada UC é acionado na prática

| Caso de uso | Comando | Quando usar |
|---|---|---|
| **UC1 — Feature completa** | `opencode run --command sdlc-hybrid "descrição"` | Nova feature do zero, ideia vaga |
| **UC2 — Só Discovery** | `curl POST /webhook/sdlc-poc-chat` | Você quer a spec mas vai implementar manualmente |
| **UC3 — Só TDD+Codegen** | `./generate-tdd.sh spec.md /tmp/out` | Spec já existe (outra fonte) |
| **UC4 — Re-fix** | `./fix-loop.sh /tmp/out spec.md 5` | Pytest falhou, quer mais tentativas |
| **UC5 — Review** | (WF6 planejado) | Antes de PR, validação de qualidade |
| **UC6 — Comparação** | Dois terminais | Benchmarking custo/qualidade |

### Experiência típica de uma feature (UC1)

```
$ opencode run --command sdlc-hybrid "sistema de gestão de estoque com alertas de reposição"

[opencode / Claude Sonnet como orquestrador]

▶ Verificando serviços...  n8n ✓  LiteLLM ✓  Ollama ✓

▶ Discovery (Claude Sonnet via WF1)...
  → 28s · spec gerada: 6 RFs, 4 ACs
  → salvo: /tmp/sdlc-spec-202506201430.md

▶ QA Agent: gerando test_main.py (qwen2.5-coder:32b)...
  → 190s · 4 testes, 56 linhas

▶ Developer Agent: models.py...  [54s]
▶ Developer Agent: routes.py...  [180s]
▶ Developer Agent: main.py...    [14s]

▶ pytest... 2 falhas (KeyError: quantidade_alerta)
▶ Fix Agent (qwen3:14b)...       [85s]  → models.py corrigido
▶ pytest... ✅ 4/4 passed

## Relatório Final
Spec:  6 requisitos funcionais
Código: models.py (42L), routes.py (78L), main.py (31L)
Testes: 4/4 passed · 1 fix automático
Tempo: 28s discovery + ~7min codegen + ~2min fix = ~10min total
Custo: ~$0.02 (Discovery Claude) + $0.00 (Ollama) = ~$0.02
```

---

## 7. Como o LiteLLM Joga o Jogo

### O problema sem o LiteLLM

Antes do LiteLLM, cada workflow n8n chamava **diretamente** um backend fixo:

```
WF1 → http://ollama:11434/api/chat  (Ollama API format)
WF3 → http://ollama:11434/api/chat  (modelo hardcoded no jsCode)
WF4 → http://ollama:11434/api/chat  (modelo hardcoded no jsCode)
```

Isso criava três problemas:

1. **Sem roteamento inteligente** — para trocar WF1 de Ollama para Claude, era preciso editar o JSON do workflow, reimportar no n8n e reiniciar. Modelo hardcoded = inflexibilidade.

2. **Sem fallback** — se o modelo local travasse (VRAM cheia, timeout), o workflow simplesmente falhava. Nenhum mecanismo de escalada para modelo cloud.

3. **Sem visibilidade de custo** — zero tracking de tokens. Impossível saber quanto custa cada fase ou comparar modelos.

### A solução com LiteLLM

O LiteLLM é inserido como **camada única de abstração entre o n8n e os modelos**:

```mermaid
flowchart LR
    subgraph ANTES["Antes (direto)"]
        direction TB
        N1["n8n WF1\nmodel: qwen3-coder:30b\nURL: ollama:11434"]
        N2["n8n WF4\nmodel: qwen2.5-coder:32b\nURL: ollama:11434"]
        O1["Ollama"]
        N1 --> O1
        N2 --> O1
    end

    subgraph DEPOIS["Depois (via LiteLLM)"]
        direction TB
        N3["n8n WF1\nmodel: sdlc-discovery\nURL: litellm:4000"]
        N4["n8n WF4\nmodel: sdlc-fix\nURL: litellm:4000"]
        LIT["LiteLLM\n:4000"]
        CL["Claude API"]
        O2["Ollama"]
        N3 --> LIT
        N4 --> LIT
        LIT -->|"sdlc-discovery → anthropic/\nclaude-sonnet-4-6"| CL
        LIT -->|"sdlc-fix → ollama/\nqwen3:14b"| O2
        LIT -.->|"fallback se timeout"| CL
    end
```

### O que o LiteLLM resolve na prática

| Problema | Como o LiteLLM resolve |
|---|---|
| **Modelo hardcoded** | n8n passa `model: "sdlc-discovery"` — um alias. O mapeamento real (para Claude ou Ollama) está no `litellm-config.yaml`. Troca de modelo = editar 1 linha no YAML, sem tocar nos workflows. |
| **Sem fallback** | `fallbacks: [{sdlc-fix: [sdlc-review]}]` — se `qwen3:14b` exceder o timeout ou retornar erro, o LiteLLM automaticamente escala a chamada para Claude. O n8n não sabe da diferença. |
| **Sem visibilidade** | O LiteLLM loga cada chamada com tokens, latência e custo calculado. Com Langfuse (próximo passo do backlog), isso vira um dashboard. |
| **Formato de API diferente** | Ollama nativo usa `/api/chat` com `options.temperature`. Claude usa `/v1/chat/completions` com `temperature` no topo. O LiteLLM expõe **sempre** OpenAI format — os workflows falam um único formato. |

### Mapa de roteamento atual

```yaml
# docker/litellm-config.yaml
sdlc-discovery  →  anthropic/claude-sonnet-4-6   # WF1 (Discovery)
sdlc-review     →  anthropic/claude-sonnet-4-6   # WF6 (Review, futuro)
sdlc-codegen    →  ollama/qwen3-coder:30b         # WF3 (Code gen)
sdlc-test       →  ollama/qwen2.5-coder:32b       # WF5 (Test gen)
sdlc-fix        →  ollama/qwen3:14b               # WF4 (Fix), com fallback Claude
```

### O que o LiteLLM NÃO faz

- **Não orquestra fases** — quem decide "agora gera testes, agora gera código" é o n8n (e o bash wrapper).
- **Não mantém contexto entre chamadas** — cada chamada é stateless. O contexto acumulado (arquivos já gerados) é passado explicitamente pelo n8n no payload.
- **Não resolve problemas de qualidade** — se o modelo local gerar código ruim, o LiteLLM entrega fielmente. A qualidade vem dos system prompts e do TDD Invertido.

---

## 8. Stack Completa em Uma Linha

```
Operador → opencode (Claude orquestra) → n8n (sequencia fases) → LiteLLM (roteia) → Claude (julgamento) | Ollama (geração)
```

Cada componente tem responsabilidade única. Remover qualquer um degrada uma capability específica mas não derruba o sistema inteiro — você pode, por exemplo, chamar os webhooks do n8n diretamente sem o opencode, ou apontar os workflows para Ollama nativo sem o LiteLLM.

---

## 9. Como Subir o Stack Completo

```bash
# Pré-requisito: ANTHROPIC_API_KEY no ambiente (nunca no repo)
export ANTHROPIC_API_KEY="sk-ant-..."

# 1. Subir n8n + LiteLLM (Ollama e Open WebUI já sobem no profile padrão)
cd ~/homelab-ai/docker
docker compose --profile optional up -d n8n litellm

# 2. Importar e ativar os workflows n8n
cd ~/homelab-ai/agents/sdlc-poc/tests
./import-workflows.sh

# 3. Smoke test
curl http://localhost:4000/health          # LiteLLM ok
curl http://localhost:5678/healthz         # n8n ok

# 4. Rodar o pipeline híbrido
opencode run --command sdlc-hybrid "descreva sua feature aqui"
```

**Referências:**
- `docker/litellm-config.yaml` — mapeamento de aliases → modelos
- `agents/sdlc-poc/workflows/` — WF1-5 (JSON do n8n)
- `agents/sdlc-poc/tests/generate-tdd.sh` — pipeline TDD bash
- `.opencode/commands/sdlc-hybrid.md` — skill opencode
- `docs/sdlc-agentico/proposals/C-model-routing.md` — decisão de arquitetura
