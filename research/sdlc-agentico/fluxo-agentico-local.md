# Fluxo Agêntico Local — SDLC com 100% LLM Local

> Última atualização: 2026-06-20  
> Hardware: RTX 5060 Ti 16 GB VRAM  
> Inferência: Ollama (sem chamadas externas em runtime)

---

## 1. Visão Geral do Pipeline (com TDD Invertido e Auto-Fix)

```mermaid
flowchart TD
    DEV([👤 Desenvolvedor])

    subgraph INPUT["Entrada"]
        TXT[chat-discovery.txt\ndescriçao livre do produto]
    end

    subgraph N8N["n8n 2.23.3 — Orquestrador"]
        direction TB
        WF1["WF1 — PM Agent\n/webhook/sdlc-poc-chat\n─────────────────\nqwen3-coder:30b\nPapel: Product Manager IA\n4 estágios: Discovery → Spec"]

        subgraph TDD["Modo TDD Invertido (generate-tdd.sh)"]
            WF5["WF5 — QA Agent\n/webhook/sdlc-poc-spec-to-tests\nqwen2.5-coder:32b\nGera test_main.py PRIMEIRO\n(não vê código algum)"]
            WF3A["WF3 [1/3] — Developer Agent\nArquivo: models.py\nContexto: test_main.py ✓"]
            WF3B["WF3 [2/3] — Developer Agent\nArquivo: routes.py\nContexto: test + models ✓"]
            WF3C["WF3 [3/3] — Developer Agent\nArquivo: main.py\nContexto: test + models + routes ✓"]
        end

        WF4["WF4 — Fix Agent\n/webhook/sdlc-poc-fix\nqwen2.5-coder:32b\nRecebe pytest failures + spec\nCorrige 1 arquivo por iteração"]
    end

    subgraph OLLAMA["Ollama — Inferência 100% Local"]
        M1["qwen3-coder:30b\nDiscovery + Spec"]
        M2["qwen2.5-coder:32b\nCode + Fix"]
    end

    PYTEST{"pytest\n✓ ou ✗"}

    DEV --> TXT --> WF1
    WF1 <-->|chat/api| M1
    WF1 --> SPEC[spec.md]

    SPEC --> WF5
    WF5 <-->|api| M2
    WF5 --> TEST[test_main.py]
    TEST --> WF3A
    WF3A <-->|api + contexto| M2
    WF3A --> MDL[models.py]
    MDL --> WF3B
    WF3B <-->|api + contexto| M2
    WF3B --> RTS[routes.py]
    RTS --> WF3C
    WF3C <-->|api + contexto| M2
    WF3C --> MN[main.py]

    TEST & MDL & RTS & MN --> PYTEST

    PYTEST -->|falhou| WF4
    WF4 <-->|api| M2
    WF4 -->|arquivo corrigido| PYTEST
    PYTEST -->|passou| OK(["✅ 4/4 passed\n0 chamadas externas"])

    style OLLAMA fill:#1a1a2e,color:#e0e0ff,stroke:#4444aa
    style N8N fill:#1e3a1e,color:#e0ffe0,stroke:#44aa44
    style TDD fill:#1a2a1a,color:#ccffcc,stroke:#44aa44,stroke-dasharray:4
    style OK fill:#0a2a0a,color:#aaffaa,stroke:#44ff44
```

---

## 2. Sequência Detalhada — TDD Invertido

```mermaid
sequenceDiagram
    participant Dev as 👤 Script
    participant WF5 as QA Agent (WF5)
    participant WF3 as Developer Agent (WF3)
    participant WF4 as Fix Agent (WF4)
    participant Ollama as Ollama Local
    participant PT as pytest

    Note over Dev,PT: Fase 1 — QA Agent gera testes da spec (sem ver código)
    Dev->>WF5: POST {spec}
    WF5->>Ollama: qwen2.5-coder:32b<br/>QA engineer persona — spec only
    Ollama-->>WF5: test_main.py (fixture reset + 1 test por AC)
    WF5-->>Dev: {filename:"test_main.py", content, lines:56}

    Note over Dev,PT: Fase 2 — Developer Agent gera implementação (vê testes primeiro)
    Dev->>WF3: POST {spec, filename:"models.py", context:[test_main.py]}
    WF3->>Ollama: qwen2.5-coder:32b — TDD mode detectado
    Ollama-->>Dev: models.py (campos compatíveis com os testes)

    Dev->>WF3: POST {spec, filename:"routes.py", context:[test_main.py, models.py]}
    WF3->>Ollama: qwen2.5-coder:32b
    Ollama-->>Dev: routes.py

    Dev->>WF3: POST {spec, filename:"main.py", context:[test_main.py, models.py, routes.py]}
    WF3->>Ollama: qwen2.5-coder:32b — 14s
    Ollama-->>Dev: main.py

    Note over Dev,PT: Fase 3 — pytest + auto-fix loop (max 3 tentativas)
    Dev->>PT: pytest test_main.py -v
    PT-->>Dev: 2 failed (KeyError: seller_net, shipping_cost)

    Dev->>WF4: POST {spec, pytest_output, files:[todos os .py]}
    Note over WF4: Regra 4: KeyError = FastAPI response_model stripping<br/>→ adicionar Optional field em models.py
    WF4->>Ollama: qwen2.5-coder:32b — 85s
    Ollama-->>WF4: models.py corrigido (+ seller_net + shipping_cost Optional)
    WF4-->>Dev: {filename:"models.py", content}

    Dev->>PT: pytest test_main.py -v
    PT-->>Dev: 4/4 passed ✓
```

---

## 3. Cobertura dos Critérios de Aceite (TDD Mode)

```mermaid
flowchart LR
    subgraph SPEC["Spec gerada pelo PM Agent"]
        AC1["AC-01\nSeller cria anúncio\n→ vê métricas no dashboard"]
        AC2["AC-02\nBuyer fidelizado compra > $21\n→ frete grátis automático"]
        AC3["AC-03\nSeller usa Ads\n→ taxa 8% aplicada"]
        AC4["AC-04\nDevolução solicitada ≤ 7 dias\n→ aprovada sem critério"]
    end

    subgraph TESTES_TDD["Testes gerados pelo QA Agent (WF5) — spec only"]
        T1["test_ac_01 ✓\ndashboard retorna ad_metrics"]
        T2["test_ac_02 ✓\nfrete=0 p/ loyalty + compra>$21"]
        T3["test_ac_03 ✓\nseller_net = '92.00' (8% fee)"]
        T4["test_ac_04 ✓\nreturn status = 'completed'"]
    end

    AC1 --> T1
    AC2 --> T2
    AC3 --> T3
    AC4 --> T4

    style TESTES_TDD fill:#1a2a3a,color:#ccddff,stroke:#4466aa
```

---

## 4. Construção vs Runtime

```mermaid
flowchart TD
    subgraph BUILD["🔧 Construção da Infraestrutura\n(one-time, não runtime)"]
        CC["Claude Code\n(Anthropic Sonnet 4.6)\n\nUsado para:\n• Criar os JSON dos workflows n8n\n• Escrever os scripts bash\n• Depurar bugs (timeout, exit code, __builtins__)\n• Aplicar fixes pós-geração\n• Escrever este documento"]
    end

    subgraph RUNTIME["⚡ Runtime do Pipeline\n(100% local, repetível sem internet)"]
        direction LR
        N8N2["n8n 2.23.3\n(orquestrador)"]
        OL["Ollama\n(inferência)"]
        Q3["qwen3-coder:30b\nPM Agent (WF1)"]
        Q2["qwen2.5-coder:32b\nQA Agent (WF5)\nDeveloper Agent (WF3)\nFix Agent (WF4)"]
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

## 5. Métricas Comparativas

### Fluxo Code-First (geração anterior — generate-files.sh)

| Métrica | Valor |
|---|---|
| Tempo total discovery → pytest | ~15 min |
| Arquivos gerados | 4 |
| Linhas de código | 407 |
| Testes | 9 |
| Passando as-generated | 7/9 |
| Fixes manuais | **2** (autouse fixture + valor de cálculo) |
| Chamadas externas | **0** |

### Fluxo TDD Invertido (generate-tdd.sh — sessão atual)

| Métrica | Valor |
|---|---|
| Tempo total spec → pytest verde | ~7min geração + ~8min fixes |
| QA Agent (WF5) — test_main.py | 190s |
| Developer Agent (WF3) — 3 arquivos | 54s + 180s + 14s |
| Fix Agent (WF4) — 1 iteração | 85s |
| Passando as-generated | 1/4 |
| Passando pós auto-fix | **4/4** |
| Fixes manuais | **0** (só fixture corrigida no prompt do WF5) |
| Chamadas externas | **0** |

### O que o TDD Invertido eliminou

- **Divergência de nomes** — Code Agent vê os testes primeiro, usa os mesmos nomes de campo
- **Circularidade** — testes são escritos por agente diferente (QA), não pelo mesmo que gera código
- **Fixes manuais** — WF4 resolveu o `response_model stripping` automaticamente

---

## 6. Limitações Identificadas

```mermaid
mindmap
  root((Limitações))
    Latência
      QA Agent test_main.py 190s
      Developer Agent 3 arquivos ~250s
      Fix Agent por iteração ~85-200s
      Total TDD ~15 min
    Bugs descobertos (agora corrigidos)
      fixture limpava __builtins__ causando hang
      fix-loop exit code capturava || true sempre 0
      WF3 ignorava tipos dos testes em modo TDD
    Escopo de geração
      Testes simples 1 assert por AC
      Não gera testes de erro 404 422
      Specs complexas podem truncar
    Qualidade
      Fix Agent corrige 1 arquivo por iteração
      Pode precisar de mais de 3 tentativas
      KeyError de response_model requer regra explícita
    Cobertura parcial
      Business rules simples bem cobertas
      Fluxos async e tempo difíceis de testar
      Integração entre módulos não coberta
```

---

## 7. Próximos Passos

| Item | Status | Prioridade |
|---|---|---|
| WF4 — Auto-fix loop | ✅ Implementado | — |
| WF5 — TDD Invertido | ✅ Implementado | — |
| `qwen2.5-coder:7b` — modelo rápido para iteração | Backlog | Alta |
| Langfuse — observabilidade de tokens/latência | Backlog | Média |
| WF6 — UX Wireframe (HTML/Tailwind por AC) | Backlog | Média |
| Contexto entre módulos (Seller + Fintech) | Backlog | Baixa |

---

## 8. Comando para Re-executar

```bash
# Fluxo completo Code-First (com auto-fix loop):
cd products/sdlc-hibrido/tests
./run-pipeline.sh research/sdlc-agentico/input/chat-discovery.txt /tmp/output-$(date +%Y%m%d)

# Fluxo TDD Invertido (testes antes do código):
./generate-tdd.sh /tmp/marketplace-spec.md /tmp/tdd-output-$(date +%Y%m%d)

# Só re-importar e ativar todos os workflows:
./import-workflows.sh
```

**Pré-requisitos:** n8n em `http://localhost:5678`, Ollama em `http://localhost:11434`, modelos `qwen3-coder:30b` e `qwen2.5-coder:32b` disponíveis.
