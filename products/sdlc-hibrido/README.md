# SDLC Híbrido — Pipeline de Desenvolvimento com LLMs

Pipeline que transforma uma descrição em linguagem natural em código testado, combinando
**Ollama local (GPU)** para inferência barata e **Claude Sonnet (cloud)** para tarefas de alta
ambiguidade — tudo coordenado por n8n e opencode.

## O resultado em números

| Métrica | Resultado |
|---|---|
| Custo por feature (pipeline híbrido) | **$0.04 – $0.07** |
| Custo equivalente tudo-Claude Sonnet | $0.50 – $2.00 |
| Custo tudo-local (mais fixes manuais) | $0 + tempo |
| Tempo e2e (discovery → código testado) | ~265s (~4 min) |
| Taxa de aprovação no PoC (junho/2026) | 3/5 critérios + 1 parcial |

Ver [`VIABILITY-REPORT.md`](VIABILITY-REPORT.md) para o relatório completo com falhas e correções.

## Como funciona

```
Operador descreve o produto
        │
        ▼
WF1 — Discovery (Claude Sonnet via LiteLLM)
  PM Agent: conversa estruturada em 4 estágios
  Output: spec.md com critérios de aceite
        │
        ▼
WF5 — TDD Invertido: Test Agent (Ollama qwen3-coder:30b)
  Lê APENAS a spec — nunca vê código
  Output: test_main.py com 1 teste por critério
        │
        ▼
WF3 — Code Gen em 3 passes (Ollama qwen2.5-coder:32b)
  models.py → routes.py → main.py
  Contexto: spec + testes (nunca o oposto)
        │
        ▼
pytest → resultado + relatório de custo
```

**Insight central — TDD Invertido:** gerar testes a partir da spec (sem ver código) e código a
partir dos testes (sem escrever testes) elimina a circularidade onde o mesmo modelo gera erros
correlacionados nos dois artefatos.

## Roteamento por ambiguidade

| Ambiguidade | Tarefa | Modelo |
|---|---|---|
| Alta | Interpretar descrição vaga, estruturar PRD, avaliar qualidade | Claude Sonnet (cloud) |
| Baixa | Gerar código a partir de spec estruturada, escrever testes de ACs explícitos | Ollama local (grátis) |

## Como usar

```bash
# Via opencode (modo interativo):
opencode run --command sdlc-hybrid "descrição do produto"

# Via scripts bash (modo batch):
cd products/sdlc-hibrido/tests
./sdlc-hybrid-interactive.sh "descrição do produto"
```

## Primeiro produto gerado

[`../marketplace/`](../marketplace/) — **Mercado Loop**, um marketplace PWA + FastAPI gerado
pelo pipeline a partir de uma spec real. É a prova de que o pipeline constrói além de TODO CRUDs.

## Estrutura

```
sdlc-hibrido/
├── VIABILITY-REPORT.md     ← resultados do PoC com métricas honestas
├── opencode-config/        ← configuração do opencode p/ este projeto
├── prompts/                ← system prompts de cada fase
├── tests/                  ← scripts de e2e (generate-*.sh, run-pipeline.sh)
│   └── generated-code/     ← saída do último run
└── workflows/              ← exports n8n (WF1–WF5)
```

## Stack

- **Orquestrador:** n8n 2.23.3 (Docker `:5678`)
- **Entry point:** opencode (comando `/sdlc-hybrid`)
- **Gateway de modelos:** LiteLLM (Docker `:4000`) — roteamento por alias, fallback, cost tracking
- **Inferência local:** Ollama (RTX 5060 Ti 16GB VRAM)
- **Inferência cloud:** Anthropic Claude Sonnet (via LiteLLM)

Ver [`../../research/sdlc-agentico/`](../../research/sdlc-agentico/) para a pesquisa que embasou
este pipeline: backlog de 27 ferramentas avaliadas, propostas A–F, fases do SDLC documentadas.
