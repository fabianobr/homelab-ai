# Fase 06 — Spec to Code

## O Que e Esta Fase

Spec to Code e a fase de implementacao: o agente de coding recebe a spec tecnica produzida na fase 05 e converte em codigo de producao, commits no git, e potencialmente testes. Esta e a fase mais critica do ciclo agêntico — onde a qualidade do LLM local tem o maior impacto perceptivel.

O agente de coding nao e o mesmo LLM que fez discovery e specs. O modelo de coding (Devstral Small 24B ou Qwen 2.5 Coder 14B) e carregado especificamente para esta fase, e descarregado ao terminar.

---

## Ferramentas Disponiveis

| Ferramenta | Modo de Uso | Melhor Para |
|---|---|---|
| Aider | CLI, git-native, commita automaticamente | Implementacao guiada, arquivo a arquivo |
| OpenCode | TUI interativa | Sessoes interativas com feedback visual |
| OpenHands | Loop autonomo, retorna PR | Tarefas pequenas e bem definidas sem supervisao |

Para o ciclo automatizado via n8n, **Aider** e a melhor escolha — tem modo `--yes` (sem confirmacao) e commita automaticamente, facilitando integracao via Execute Command node.

Para sessoes interativas onde o desenvolvedor quer acompanhar, **OpenCode** oferece TUI similar ao Claude Code.

Para tarefas muito pequenas sem supervisao, **OpenHands** pode ser acionado como alternativa.

---

## Modelos Recomendados

| Modelo | VRAM | Benchmark | Uso Recomendado |
|---|---|---|---|
| Devstral Small 24B Q4_K_M | ~13GB | 68% SWE-bench | Tarefas de media-alta complexidade |
| Qwen 2.5 Coder 14B Q4 | ~8GB | ~55% SWE-bench | Tarefas simples; quando VRAM e critica |
| Qwen 3.5 14B Q4_K_M | ~8GB | ~50% SWE-bench | Alternativa geral se Coder nao estiver disponivel |

**Recomendacao por tipo de tarefa:**
- Bugfix isolado, CRUD simples: Qwen 2.5 Coder 14B (mais rapido, menos VRAM)
- Feature media, refactoring: Devstral Small 24B (melhor qualidade para codigo multi-arquivo)
- Tasks que exigem raciocinio alem de coding: Qwen 3.5 14B (melhor raciocinio geral)

---

## Fluxo de Implementacao

```
[Spec tecnica recebida]
         |
         v
[Carregar modelo de coding no Ollama]
  ollama pull devstral (se nao disponivel)
         |
         v
[Aider: contexto inicial]
  aider --read 05-spec-tecnica.md --read ARCHITECTURE.md
         |
         v
[Loop: arquivo a arquivo]
  Para cada arquivo na lista da spec:
    1. Aider recebe instrucao especifica para aquele arquivo
    2. Modelo gera implementacao
    3. Aider verifica se o arquivo esta sintaticamente correto
    4. Aider commita com mensagem descritiva
         |
         v
[Verificar: testes passam?]
  pytest tests/ (ou equivalente)
         |
         v
[Se falhou: Aider fix]
  Passar erro para o modelo corrigir
         |
         v
[PR criado ou branch pronta para CI/CD]
```

---

## Comandos de Execucao

### Aider — Modo Automatico (para n8n)

```bash
# Implementar spec completa sem interacao humana
cd /path/to/project && \
aider \
  --model ollama/devstral \
  --read /data/sdlc-state/05-spec-tecnica.md \
  --read ARCHITECTURE.md \
  --message "Implemente todos os arquivos listados em /data/sdlc-state/05-spec-tecnica.md.
             Siga as interfaces definidas exatamente.
             Faca um commit por arquivo.
             Comece pelo arquivo mais basico (sem dependencias dos outros)." \
  --yes \
  --no-stream \
  2>&1 | tee /data/sdlc-logs/06-aider-$(date +%Y%m%d-%H%M%S).log
```

### Aider — Arquivo Especifico

```bash
# Implementar um arquivo especifico da spec
aider \
  --model ollama/devstral \
  src/cache/product_cache.py \
  --message "Implemente a classe ProductCache conforme a interface definida em /data/sdlc-state/05-spec-tecnica.md, secao 'Interfaces de Codigo'. Use Redis como backend. Inclua tratamento de erro para conexao perdida."
```

### Aider — Gerar Testes

```bash
# Gerar testes para implementacao criada
aider \
  --model ollama/qwen2.5-coder:14b-instruct-q4_K_M \
  src/cache/product_cache.py \
  tests/test_product_cache.py \
  --message "Escreva testes unitarios para ProductCache em tests/test_product_cache.py.
             Use pytest e pytest-mock. Cubra: get() com cache hit, get() com cache miss,
             set() com sucesso, set() com Redis indisponivel (deve falhar gracefully),
             invalidate() com sucesso."
```

### OpenHands — Tarefa Autonoma

```bash
# Via API do OpenHands (para integracao n8n)
curl -X POST http://localhost:3000/api/conversations \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Implemente a classe ProductCache em src/cache/product_cache.py conforme a spec em /workspace/05-spec-tecnica.md. A classe deve usar Redis como backend. Inclua testes unitarios em tests/test_product_cache.py. Faca um commit ao finalizar.",
    "repository": "/workspace/homelab-ai"
  }'
```

---

## Integracao com Git e CI/CD

O Aider commita automaticamente cada mudanca. Para organizar os commits do ciclo SDLC:

```bash
# Criar branch antes de iniciar a fase
git checkout -b "sdlc/ciclo-$(date +%Y-W%V)/feature-cache-redis"

# Aider trabalha nesta branch
aider --model ollama/devstral [args...]

# Ao finalizar, verificar commits criados
git log --oneline -10

# Criar PR (dispara CI/CD)
gh pr create \
  --title "feat: adicionar cache Redis para produtos (SDLC ciclo 2026-W25)" \
  --body "Implementacao gerada pelo ciclo SDLC agêntico. Ver docs/sdlc-state/05-prd.md para detalhes."
```

---

## Taxa de Sucesso Esperada por Complexidade

| Complexidade | Criterio | Taxa (Devstral 24B) | Taxa (Qwen Coder 14B) |
|---|---|---|---|
| Trivial | 1 arquivo, < 50 linhas, sem dependencias | 90-95% | 85-90% |
| Simples | 1-3 arquivos, dependencias internas | 80-90% | 70-80% |
| Media | 3-7 arquivos, integracao com libs externas | 65-80% | 55-70% |
| Alta | 7-15 arquivos, logica de negocio complexa | 45-65% | 35-55% |
| Muito alta | >15 arquivos, arquitetura distribuida | 25-45% | 20-35% |

**Estrategia para tarefas de alta complexidade:** dividir em subtarefas de complexidade "simples" ou "media". O Aider pode executar multiplas subtarefas sequencialmente em uma sessao.

---

## Quando Usar Fallback para API

Se a tarefa falhar 2 vezes com modelo local:

```bash
# Via LiteLLM proxy com fallback para Claude API
aider \
  --openai-api-base http://litellm:4000 \
  --model claude-sonnet-4-5 \
  --message "{{ spec }}"
```

Ou diretamente via variavel de ambiente:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
aider \
  --model claude-sonnet-4-5 \
  --message "{{ spec }}"
```

O fallback para API e o "plano B" — usa tokens pagos apenas quando o modelo local falhou. Estima-se que 85-90% das tarefas sejam resolvidas pelo modelo local, reduzindo custo de API em proporcao equivalente.

---

## Integracao no n8n

```
Workflow: "06 - Spec to Code"

[Webhook: recebe path da spec tecnica]
     |
     v
[Execute Command: criar branch git]
  git checkout -b "sdlc/ciclo-{{ data }}/{{ feature_slug }}"
     |
     v
[Execute Command: Aider implementar spec]
  aider --model ollama/devstral --read {{ spec_path }} --message "{{ instrucao }}" --yes
  timeout: 30 minutos
     |
     v
[IF: exitcode == 0?]
  |-- Sim: continua
  |-- Nao: tentar com Qwen Coder 14B
       |-- Ainda falhou: notificar humano + aguardar intervencao
     |
     v
[Execute Command: rodar testes]
  pytest tests/ --tb=short 2>&1
     |
     v
[IF: testes passaram?]
  |-- Sim: continua
  |-- Nao: Aider fix com stack trace
     |
     v
[Execute Command: criar PR]
  gh pr create --title "..." --body "..."
     |
     v
[HTTP: Langfuse — log resultado]
     |
     v
[Disparar Fase 07 — CI/CD]
```
