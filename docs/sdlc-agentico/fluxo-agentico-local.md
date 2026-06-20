# Fluxo Agêntico Local — SDLC com 100% LLM Local

> Sessão de validação: 2026-06-20  
> Hardware: RTX 5060 Ti 16 GB VRAM  
> Inferência: Ollama (sem chamadas externas em runtime)

---

## 1. Visão Geral do Pipeline

```mermaid
flowchart TD
    DEV([👤 Desenvolvedor])

    subgraph INPUT["Entrada"]
        TXT[chat-discovery.txt\ndescriçao livre do produto]
    end

    subgraph N8N["n8n — Orquestrador"]
        direction TB
        WF1["WF1 — PM Agent\n/webhook/sdlc-poc-chat\n─────────────────\nqwen3-coder:30b\nPapel: Product Manager IA\n4 estágios: Discovery → Hipóteses\n→ Métricas → Spec"]
        WF3A["WF3 [1/4] — Developer Agent\nArquivo: models.py\nContexto: nenhum"]
        WF3B["WF3 [2/4] — Developer Agent\nArquivo: routes.py\nContexto: models.py ✓"]
        WF3C["WF3 [3/4] — Developer Agent\nArquivo: main.py\nContexto: models.py + routes.py ✓"]
        WF3D["WF3 [4/4] — Developer Agent\nArquivo: test_main.py\nContexto: 3 arquivos anteriores ✓"]
    end

    subgraph OLLAMA["Ollama — Inferência 100% Local"]
        M1["qwen3-coder:30b\nDiscovery + Spec"]
        M2["qwen2.5-coder:32b\nCode Generation"]
    end

    subgraph OUTPUT["Output Gerado"]
        SPEC["spec.md\n41 linhas\nRF × 8 + AC × 4"]
        MDL["models.py — 37 linhas\nPydantic v2 models"]
        RTS["routes.py — 110 linhas\nFastAPI endpoints\nbusiness logic"]
        MN["main.py — 6 linhas\napp init"]
        TST["test_main.py — 254 linhas\n9 testes async"]
    end

    PYTEST{"pytest\n9/9 ✓\n0.16s"}

    DEV --> TXT --> WF1
    WF1 <-->|chat/api| M1
    WF1 --> SPEC
    SPEC --> WF3A
    WF3A <-->|api| M2
    WF3A --> MDL
    MDL --> WF3B
    WF3B <-->|api + contexto| M2
    WF3B --> RTS
    RTS --> WF3C
    WF3C <-->|api + contexto| M2
    WF3C --> MN
    MN --> WF3D
    WF3D <-->|api + contexto| M2
    WF3D --> TST
    MDL & RTS & MN & TST --> PYTEST

    style OLLAMA fill:#1a1a2e,color:#e0e0ff,stroke:#4444aa
    style N8N fill:#1e3a1e,color:#e0ffe0,stroke:#44aa44
    style PYTEST fill:#1a3a1a,color:#aaffaa,stroke:#44ff44
```

---

## 2. O Que Cada Agente Fez

```mermaid
sequenceDiagram
    participant Dev as 👤 Desenvolvedor
    participant WF1 as PM Agent (WF1)
    participant WF3 as Developer Agent (WF3)
    participant Ollama as Ollama Local

    Dev->>WF1: POST /sdlc-poc-chat<br/>{chatInput: "me ajude com ecommerce..."}
    WF1->>Ollama: qwen3-coder:30b<br/>estágio DISCOVERY
    Ollama-->>WF1: resposta conversacional
    WF1-->>Dev: hipóteses + perguntas

    Dev->>WF1: POST /sdlc-poc-chat<br/>{chatInput: "gerar spec"}
    WF1->>Ollama: qwen3-coder:30b<br/>estágio SPEC
    Ollama-->>WF1: ---SPEC-START--- ... ---SPEC-END---
    WF1-->>Dev: spec estruturada (RF, NF, AC)

    Note over Dev,WF3: generate-files.sh extrai spec e chama WF3 × 4

    Dev->>WF3: {spec, filename:"models.py", context:[]}
    WF3->>Ollama: qwen2.5-coder:32b — 114s
    Ollama-->>WF3: Pydantic v2 models
    WF3-->>Dev: models.py (37 linhas)

    Dev->>WF3: {spec, filename:"routes.py", context:[models.py]}
    WF3->>Ollama: qwen2.5-coder:32b — 226s
    Ollama-->>WF3: FastAPI router + business logic
    WF3-->>Dev: routes.py (110 linhas)

    Dev->>WF3: {spec, filename:"main.py", context:[models.py, routes.py]}
    WF3->>Ollama: qwen2.5-coder:32b — 12s
    Ollama-->>Dev: main.py (6 linhas)

    Dev->>WF3: {spec, filename:"test_main.py", context:[models.py, routes.py, main.py]}
    WF3->>Ollama: qwen2.5-coder:32b — 467s
    Ollama-->>Dev: test_main.py (254 linhas)

    Note over Dev: pytest test_main.py -v → 9/9 ✓
```

---

## 3. Cobertura dos Critérios de Aceite

```mermaid
flowchart LR
    subgraph SPEC["Spec gerada pelo PM Agent"]
        AC1["AC-01\nSeller cria anúncio\n→ vê métricas no dashboard"]
        AC2["AC-02\nBuyer fidelizado compra > $21\n→ frete grátis automático"]
        AC3["AC-03\nSeller usa Ads\n→ taxa 8% aplicada"]
        AC4["AC-04\nDevolução solicitada ≤ 7 dias\n→ aprovada sem critério"]
    end

    subgraph TESTES["Testes gerados pelo Developer Agent"]
        T1["test_create_and_get_product ✓"]
        T2["test_create_and_get_advertisement ✓"]
        T3["test_create_and_get_seller_metrics ✓"]
        T4["test_create_and_get_buyer ✓"]
        T5["test_create_and_get_purchase ✓"]
        T6["test_create_and_get_refund ✓"]
        T7["test_paid_advertisement_commission ✓"]
        T8["test_refund_within_7_days ✓"]
        T9["test_fidelity_member_free_shipping ✓"]
    end

    AC1 --> T1 & T2 & T3
    AC2 --> T4 & T9
    AC3 --> T7
    AC4 --> T6 & T8
    T5 -.->|cobertura extra\nfluxo de compra| AC1
```

---

## 4. O Que Foi Usado Onde

```mermaid
flowchart TD
    subgraph BUILD["🔧 Construção da Infraestrutura\n(one-time, não runtime)"]
        CC["Claude Code\n(Anthropic Sonnet 4.6)\n\nUsado para:\n• Criar os JSON dos workflows n8n\n• Escrever generate-files.sh\n• Depurar bugs (timeout 600ms→600s)\n• Aplicar fixes pós-geração\n• Escrever este documento"]
    end

    subgraph RUNTIME["⚡ Runtime do Pipeline\n(100% local, repetível sem internet)"]
        direction LR
        N8N2["n8n 2.23.3\n(orquestrador)"]
        OL["Ollama\n(inferência)"]
        Q3["qwen3-coder:30b\nPM Agent"]
        Q2["qwen2.5-coder:32b\nDeveloper Agent"]
        PY["Python / pytest\n(validação)"]
        N8N2 --> OL
        OL --> Q3 & Q2
        Q3 & Q2 --> PY
    end

    BUILD -.->|"criou os workflows\nque rodam aqui"| RUNTIME

    style BUILD fill:#2d1515,color:#ffcccc,stroke:#aa4444
    style RUNTIME fill:#0d2d0d,color:#ccffcc,stroke:#44aa44
```

---

## 5. Métricas da Sessão

| Métrica | Valor |
|---|---|
| Tempo total discovery → pytest | ~15 min |
| Tokens processados localmente | ~150k (estimado) |
| Chamadas para APIs externas (runtime) | **0** |
| Arquivos gerados | 4 |
| Linhas de código geradas | 407 |
| Testes gerados | 9 |
| Testes passando as-generated | 7/9 |
| Testes passando pós-fix mínimo | **9/9** |
| Fixes manuais aplicados | 2 (autouse fixture + valor de cálculo) |

### Fixes que o contexto progressivo eliminou
Na geração anterior (sem contexto), eram necessários 4 fixes:
- `platform_fee_usd` → `platform_fee` (divergência de nome)
- `seller_net_usd` → `seller_net` (divergência de nome)
- Endpoint `/ledger` ausente
- Lógica de freeze com off-by-one

Com contexto progressivo, nenhum desses ocorreu. As **254 linhas** de `test_main.py` usaram exatamente os mesmos nomes de campo que `routes.py`.

---

## 6. Limitações Identificadas

```mermaid
mindmap
  root((Limitações))
    Latência
      models.py: 114s
      routes.py: 226s
      test_main.py: 467s
      Total: ~15 min por módulo
    Escopo de geração
      One-shot funciona para specs simples
      Specs complexas precisam de WF3 por arquivo
      Módulos grandes ainda truncam
    Qualidade
      Cálculo de valor errado no teste
      State leak entre testes não foi gerado
      Requer 2 fixes manuais mínimos
    Cobertura parcial
      Business rules simples bem cobertas
      Fluxos assíncronos e tempo difíceis de testar
      Integração entre módulos não coberta
```

---

## 7. Próximos Passos Naturais

1. **Contexto entre módulos** — gerar Seller Central com context de Fintech Core (wallet compartilhado)
2. **Modelo mais rápido** — testar `qwen2.5-coder:7b` para iteração (~15-30s/arquivo vs 2-8min)
3. **WF4 — UX Wireframe** — mesmo padrão, output HTML/Tailwind por tela
4. **Langfuse** — observabilidade: ver tokens, latência, qualidade por chamada
5. **Auto-fix loop** — WF4: rodar pytest → erros → prompt de fix → re-gerar arquivo com bug
