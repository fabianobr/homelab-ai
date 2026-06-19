# Proposta A — Stack de Coding Agêntico Básico

**Prioridade:** Alta
**Viabilidade no homelab:** 4/5
**Relevancia para o SDLC:** 5/5
**Status:** Em avaliacao

---

## Resumo

Substituir o Claude Code por um agente de coding local que usa Ollama como backend de inferencia. Zero custo de tokens, privacidade total, funciona offline. O gap de qualidade em relacao ao Claude 4.5 Sonnet e de aproximadamente 20-30% para tarefas bem definidas e de 40-60% para tarefas abertas complexas.

---

## Stack

```
Terminal
   |
   v
OpenCode (TUI) ou Aider (CLI)
   |
   v
Ollama (servidor local)
   |
   v
Devstral Small 24B Q4_K_M   <-- para coding (13GB VRAM)
   ou
Qwen 2.5 Coder 14B Q4       <-- alternativa mais leve (8GB VRAM)
```

---

## Modelos Recomendados para 16GB VRAM

| Modelo | Tamanho VRAM | SWE-bench | Uso recomendado | Observacao |
|---|---|---|---|---|
| Devstral Small 24B Q4_K_M | ~13GB | 68% | Coding principal | Apertado — sem margem para outros processos na GPU |
| Qwen 2.5 Coder 14B Q4 | ~8GB | ~55% | Coding alternativo | Confortavel — sobra VRAM para ComfyUI em paralelo |
| Qwen 3.5 14B Q4_K_M | ~8GB | ~50% | Raciocinio geral + coding | Melhor para planning, specs e discovery alem de coding |
| Phi-4 14B Q4_K_M | ~8GB | ~52% | Coding + matematica | Forte em raciocinio logico; menos testado para agentic loops |

**Recomendacao inicial:** comecar com Qwen 2.5 Coder 14B Q4 para ter margem de VRAM; evoluir para Devstral Small 24B quando o ambiente estiver estavel e o uso de ComfyUI simultaneo nao for necessario.

---

## Pros

- Substitui Claude Code para coding do dia a dia sem custo de tokens
- Privacidade total — nenhum dado sai do homelab
- Funciona offline
- Devstral Small 24B tem 68% SWE-bench — melhor modelo open-source de coding nesta faixa de tamanho em junho/2026
- Aider e git-native: faz commits automaticamente com mensagens explicativas, facilitando integracao ao CI/CD
- OpenCode tem TUI similar ao Claude Code — curva de aprendizado minima

## Contras

- Multi-arquivo complexo fica em ~70-80% da qualidade do Claude 4.5 Sonnet
- Devstral Small 24B ocupa 13GB dos 16GB VRAM — sem paralismo de inferencia, sem GPU para ComfyUI simultaneamente
- Sem memoria persistente de longo prazo entre sessoes (workaround: RAG com Qdrant)
- Raciocinio de sistemas grandes (>50 arquivos) tende a falhar ou produzir codigo inconsistente
- Latencia por token maior que API — sessoes interativas ficam mais lentas

---

## Fases do SDLC Cobertas

| Fase | Cobertura | Detalhe |
|---|---|---|
| 06 — Spec to Code | Principal | Converte specs em codigo, arquivo a arquivo |
| Code (iteracao) | Principal | Refactoring, bugfix, adicao de features |
| Review | Secundaria | Pode revisar PRs se alimentado com o diff |
| Testes | Secundaria | Gera testes unitarios a partir de implementacao |
| Commit | Automatica (Aider) | Aider commita automaticamente cada mudanca |

---

## Setup: OpenCode + Ollama

### Pre-requisitos

```bash
# Ollama ja instalado no homelab
# Verificar que o servico esta rodando
curl http://localhost:11434/api/tags
```

### Instalar modelo de coding

```bash
# Devstral Small 24B (apertado — 13GB VRAM)
ollama pull devstral

# Alternativa: Qwen 2.5 Coder 14B (confortavel — 8GB VRAM)
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
```

### Instalar OpenCode

```bash
# Via npm (requer Node.js 18+)
npm install -g opencode-ai

# Verificar instalacao
opencode --version

# Configurar para usar Ollama
mkdir -p ~/.config/opencode
cat > ~/.config/opencode/config.json << 'EOF'
{
  "provider": "ollama",
  "model": "qwen2.5-coder:14b-instruct-q4_K_M",
  "baseUrl": "http://localhost:11434"
}
EOF

# Iniciar no diretorio do projeto
cd /path/to/project
opencode
```

### Configurar OpenCode via variavel de ambiente

```bash
# Alternativa via env vars (adicionar ao .bashrc ou .zshrc)
export OPENCODE_PROVIDER=ollama
export OPENCODE_MODEL=qwen2.5-coder:14b-instruct-q4_K_M
export OPENCODE_BASE_URL=http://localhost:11434
```

---

## Setup: Aider + Ollama

### Instalar Aider

```bash
# Via pip (Python 3.10+)
pip install aider-chat

# Verificar instalacao
aider --version
```

### Usar Aider com Ollama

```bash
# Iniciar sessao com modelo Ollama
cd /path/to/project
aider --model ollama/qwen2.5-coder:14b-instruct-q4_K_M

# Com Devstral Small
aider --model ollama/devstral

# Modo sem confirmacao de commits (cuidado — commita automaticamente)
aider --model ollama/qwen2.5-coder:14b-instruct-q4_K_M --auto-commits

# Passar arquivos especificos para contexto
aider --model ollama/qwen2.5-coder:14b-instruct-q4_K_M src/api/routes.py src/models/user.py
```

### Arquivo de configuracao do Aider

```yaml
# .aider.conf.yml na raiz do projeto
model: ollama/qwen2.5-coder:14b-instruct-q4_K_M
auto-commits: true
dirty-commits: true
git: true
# Limite de contexto para modelos de 14B (janela menor que Claude)
map-tokens: 2048
```

---

## Integracao ao Ciclo SDLC via n8n

O agente de coding e disparado pelo n8n na fase 06-spec-to-code:

```
n8n Workflow: "06 - Spec to Code"
   |
   v
[Webhook: recebe spec formatada]
   |
   v
[Execute Command node]
   comando: aider --model ollama/devstral --message "{{ spec_prompt }}" --yes
   diretorio: /path/to/project
   |
   v
[HTTP Request: Langfuse — log da execucao]
   |
   v
[Git node: verifica commits criados]
   |
   v
[Webhook: dispara workflow 07-cicd]
```

---

## Taxa de Sucesso Esperada por Tipo de Tarefa

| Tipo de Tarefa | Taxa de Sucesso Esperada | Observacao |
|---|---|---|
| Bugfix isolado (1 arquivo) | 85-90% | Alta confiabilidade |
| Feature simples (1-3 arquivos) | 75-85% | Boa confiabilidade |
| Refactoring localizado | 80-90% | Muito bom |
| Geracao de testes unitarios | 70-80% | Bom, exige revisao |
| Feature media (5-10 arquivos) | 60-75% | Exige supervisao |
| Refactoring de arquitetura | 40-60% | Alto risco de inconsistencia |
| Feature complexa (>10 arquivos) | 30-50% | Melhor dividir em subtarefas |

---

## Dicas de Uso

1. **Quebrar tarefas grandes em subtarefas:** em vez de pedir "implementar sistema de autenticacao", pedir "criar modelo User com campos email e password_hash" → "criar endpoint POST /auth/login" → "adicionar middleware de autenticacao JWT"

2. **Fornecer contexto de arquivos relevantes:** tanto OpenCode quanto Aider funcionam melhor quando os arquivos relacionados estao explicitamente no contexto da sessao

3. **Usar CONVENTIONS.md ou ARCHITECTURE.md no projeto:** modelos locais nao tem contexto do projeto — um arquivo de convencoes lido no inicio da sessao melhora significativamente a aderencia ao padrao do codebase

4. **Revisar antes de commitar (se nao usar auto-commits):** especialmente em Devstral Small, verificar se o modelo nao alucinou imports ou funcoes inexistentes

5. **Modelo de fallback:** se a tarefa falhar 2x com o modelo local, considerar escalar para Claude API via LiteLLM (item 23 do backlog)
