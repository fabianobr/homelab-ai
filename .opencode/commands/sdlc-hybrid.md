---
description: Pipeline SDLC híbrido completo. Discovery via Claude Sonnet → TDD → codegen Ollama local. Uso: /sdlc-hybrid <descrição do produto>
model: anthropic/claude-sonnet-4-6
---

Você é o orquestrador do pipeline SDLC híbrido local. Seu trabalho é executar cada fase do pipeline usando suas ferramentas bash e reportar o progresso.

## Objetivo

Construir um sistema FastAPI para: **$1**

## Roteamento de modelos neste pipeline

| Fase | Modelo | Via |
|---|---|---|
| Discovery → spec | Claude Sonnet | WF1 → LiteLLM |
| Test gen | qwen2.5-coder:32b | WF5 → Ollama |
| Code gen | qwen3-coder:30b | WF3 → Ollama |
| Auto-fix | qwen3:14b + fallback Claude | WF4 → LiteLLM |

## Pré-verificação (antes de começar)

Execute e confirme que os serviços estão no ar:

```bash
curl -sf http://localhost:5678/healthz > /dev/null && echo "n8n: ok" || echo "n8n: OFFLINE"
curl -sf http://localhost:4000/health > /dev/null && echo "litellm: ok" || echo "litellm: OFFLINE"
curl -sf http://localhost:11434/api/tags > /dev/null && echo "ollama: ok" || echo "ollama: OFFLINE"
```

Se algum serviço estiver offline, pare e avise o usuário antes de continuar.

## Passo 1 — Discovery: gerar spec (Claude Sonnet via WF1 → LiteLLM)

Use Python para montar o payload JSON com segurança (evita problemas de escaping com aspas):

```bash
python3 - << 'PYEOF'
import json, subprocess, sys

ideia = "$1"

payload = {
    "chatInput": (
        f"Minha ideia: {ideia}\n\n"
        "Com base nessa ideia, gere a spec completa AGORA (pule direto para 'gerar spec'). "
        "Inclua: background (1 parágrafo), 5-8 requisitos funcionais (RF-0X), "
        "critérios de aceite em Given/When/Then para cada RF, e itens fora de escopo."
    ),
    "messages": []
}

result = subprocess.run(
    ["curl", "-s", "-X", "POST",
     "http://localhost:5678/webhook/sdlc-poc-chat",
     "-H", "Content-Type: application/json",
     "--max-time", "120",
     "--data", json.dumps(payload)],
    capture_output=True, text=True, timeout=130
)

if result.returncode != 0:
    print(f"ERRO curl: {result.stderr}", file=sys.stderr)
    sys.exit(1)

data = json.loads(result.stdout)
output = data.get("output", "")
print(output)
PYEOF
```

**Extraia o bloco entre `---SPEC-START---` e `---SPEC-END---` da resposta acima.**
Salve em `/tmp/sdlc-spec-$(date +%Y%m%d%H%M).md` usando um heredoc Python para preservar o conteúdo exato.

Se a resposta não contiver `---SPEC-START---`, avise e peça ao usuário para refinar a descrição.

## Passo 2 — TDD Invertido: testes antes do código (WF5 → Ollama)

Execute o pipeline TDD completo apontando para o spec salvo no passo anterior:

```bash
cd /home/fabiano/homelab-ai/agents/sdlc-poc/tests
./generate-tdd.sh /tmp/sdlc-spec-TIMESTAMP.md /tmp/sdlc-output-TIMESTAMP
```

(substitua TIMESTAMP pelo valor real do arquivo salvo no passo 1)

Este script:
- Chama WF5 para gerar `test_main.py` (QA Agent, vê só a spec)
- Chama WF3 3x para gerar `models.py`, `routes.py`, `main.py` (com testes como contexto)
- Roda pytest e chama WF4 (fix loop, até 3 tentativas) se houver falhas
- Pode levar 8-15 minutos (qwen3-coder:30b é lento mas preciso)

Mostre o output em tempo real se possível.

## Passo 3 — Relatório final

Após a conclusão, mostre:

```
## Resultado do Pipeline SDLC Híbrido

### Spec
- Arquivo: /tmp/sdlc-spec-TIMESTAMP.md
- Requisitos gerados: N

### Código gerado
- models.py: X linhas
- routes.py: Y linhas
- main.py: Z linhas
- test_main.py: W linhas

### Pytest
- Resultado: N/N passed (ou X failed)
- Fixes automáticos: N iteração(ões) do WF4

### Performance
- Discovery (Claude): ~Xs
- Test gen (Ollama): ~Xs
- Code gen (Ollama): ~Xs
- Fix loop (Ollama): ~Xs
- Total: ~Xmin

### Custo estimado
- Discovery: ~$0.02 (Claude Sonnet via LiteLLM)
- Codegen: $0.00 (Ollama local)
- Total: ~$0.02-0.07/feature
```
