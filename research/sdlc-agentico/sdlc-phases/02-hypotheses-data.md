# Fase 02 — Hipóteses + Coleta de Dados/Métricas

## O Que e Esta Fase

Hipoteses sao afirmacoes testáveis derivadas do discovery. Nesta fase, o LLM local recebe as hipoteses brutas da fase anterior e as refina em hipoteses com criterios de validacao mensuráveis, define quais dados sao necessarios para validar cada uma, e executa (ou agenda) a coleta desses dados.

A coleta de dados e executada pelo n8n (chamadas a APIs, leitura de logs, consultas a bancos de dados) e entregue ao LLM para analise preliminar.

---

## Input Esperado

| Input | Fonte | Formato |
|---|---|---|
| Hipoteses brutas | Output da fase 01 | Markdown |
| Metricas de deploy anteriores | Langfuse, logs de CI/CD | JSON |
| Logs de erro recentes | Docker logs, arquivos de log | Texto |
| Dados de uso (se disponivel) | API de produto, banco de dados | JSON |
| KPIs definidos previamente | sdlc-phases/08-monitoring-kpis.md | Markdown |

---

## Output Esperado

```markdown
## Hipoteses Refinadas — Ciclo [data]

### Hipotese 1: [titulo]
- Afirmacao: Se [acao], entao [resultado]
- Metrica de validacao: [metrica especifica + threshold de confirmacao]
- Dados necessarios: [lista de dados a coletar]
- Criterio de sucesso: [valor numerico ou comportamento observavel]
- Criterio de falha: [quando declarar a hipotese refutada]
- Prazo de validacao: [X dias/semanas]
- Dados coletados:
  - [Dado 1]: [valor atual]
  - [Dado 2]: [valor atual]
- Analise preliminar: [o que os dados sugerem antes da implementacao]

### Hipotese 2: [titulo]
[mesmo formato]

### Priorizacao
| Hipotese | Impacto esperado | Facilidade de testar | Score |
|---|---|---|---|
| [H1] | Alto | Media | 4/5 |
| [H2] | Medio | Alta | 3.5/5 |
```

---

## Como um LLM Local Formula Hipoteses Testáveis

Um modelo de 14B tem capacidade razoavel de formular hipoteses, mas precisa de constraints explicitios no prompt para produzir hipoteses mensuráveis (em vez de hipoteses vagas).

### System Prompt para Refinamento de Hipoteses

```
Voce e um Data Scientist e Product Analyst trabalhando em ciclo SDLC agêntico.

Receba hipoteses brutas e refine-as em hipoteses testáveis com os seguintes criterios:
1. A hipotese deve ser falsificavel — deve ser possivel refuta-la com dados
2. A metrica de validacao deve ser numerica ou comportamental e mensuravel
3. O prazo de validacao deve ser realista (dias a semanas, nao meses)
4. O criterio de sucesso deve ser especifico — ex: "latencia cai > 20%" nao "latencia melhora"

Para cada hipotese, produza:
- Afirmacao refinada no formato: "Se [acao especifica], entao [resultado mensuravel] em [prazo]"
- Metrica principal: [o que medir]
- Valor atual (baseline): [dado coletado ou "nao disponivel"]
- Threshold de confirmacao: [valor minimo para confirmar]
- Threshold de refutacao: [valor que indica falha da hipotese]

Priorize hipoteses por: impacto esperado x facilidade de medir x risco de estar errado.
```

---

## Integracao com Fontes de Dados

### 1. Logs de Docker via n8n

```json
{
  "name": "Coletar Logs de Erro",
  "type": "n8n-nodes-base.executeCommand",
  "parameters": {
    "command": "docker logs --since 24h --tail 500 homelab-api 2>&1 | grep -E 'ERROR|WARN' | head -100"
  }
}
```

### 2. Metricas do Langfuse via API

```json
{
  "name": "Buscar Metricas Langfuse",
  "type": "n8n-nodes-base.httpRequest",
  "parameters": {
    "method": "GET",
    "url": "http://langfuse:3001/api/public/metrics/daily",
    "headers": {
      "Authorization": "Basic {{ base64(LANGFUSE_PUBLIC_KEY + ':' + LANGFUSE_SECRET_KEY) }}"
    }
  }
}
```

### 3. Status de CI/CD via GitHub API

```json
{
  "name": "Buscar Resultados CI Recentes",
  "type": "n8n-nodes-base.httpRequest",
  "parameters": {
    "method": "GET",
    "url": "https://api.github.com/repos/{{ owner }}/{{ repo }}/actions/runs?per_page=10",
    "headers": {
      "Authorization": "Bearer {{ GITHUB_TOKEN }}"
    }
  }
}
```

### 4. Metricas do Servidor (uptime, memoria, CPU)

```bash
# Execute Command node no n8n
# Retorna metricas do host para analise de performance
free -m && df -h && uptime && nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.free --format=csv,noheader
```

---

## Como Automatizar a Coleta via n8n

```
Workflow: "02 - Hipoteses e Coleta de Dados"

[Webhook: recebe output da fase 01]
     |
     v
[Paralelo — coletar dados de multiplas fontes]
  |-- [Execute Command: docker logs + grep errors]
  |-- [HTTP: Langfuse API metricas]
  |-- [HTTP: GitHub Actions status]
  |-- [Execute Command: metricas do servidor]
     |
     v
[Merge: consolidar todos os dados coletados]
     |
     v
[Set: montar contexto para LLM]
  - hipoteses brutas da fase 01
  - dados coletados de todas as fontes
     |
     v
[HTTP: Ollama API]
  model: qwen3.5:14b
  system_prompt: (refinamento de hipoteses)
  prompt: {{ hipoteses + dados }}
     |
     v
[Write File: /data/sdlc-state/02-hipoteses.md]
     |
     v
[HTTP: Langfuse — log da execucao]
     |
     v
[Webhook: dispara fase 03 se UX relevante, ou 04 se tecnica pura]
```

---

## Formato de Saida para a Proxima Fase

O output desta fase alimenta a fase seguinte (03-UX ou 04-Arquitetura, dependendo da natureza das hipoteses):

```json
{
  "ciclo": "2026-W25",
  "hipoteses_priorizadas": [
    {
      "id": "H1",
      "titulo": "Cache Redis reduz latencia da API em > 30%",
      "afirmacao": "Se adicionarmos cache Redis para respostas de endpoints GET de produtos, entao a latencia p95 cairá de 800ms para < 500ms em 5 dias apos o deploy",
      "metrica": "latencia_p95_get_produtos",
      "baseline": "800ms",
      "threshold_sucesso": "< 560ms (queda > 30%)",
      "threshold_falha": "> 700ms (queda < 12.5%)",
      "prazo": "5 dias",
      "impacto": "Alto",
      "facilidade": "Alta"
    }
  ],
  "dados_coletados": {
    "erros_ultimas_24h": 42,
    "latencia_p95_atual": "820ms",
    "taxa_sucesso_ci": "87%",
    "vram_disponivel": "3.2GB"
  },
  "recomendacao_proxima_fase": "04-arquitetura — hipotese tecnica, sem necessidade de fase UX"
}
```

---

## Criterios de Qualidade

- [ ] Todas as hipoteses da fase 01 foram refinadas com metrica e threshold
- [ ] Dados foram coletados de pelo menos 2 fontes diferentes
- [ ] Priorizacao esta documentada com justificativa
- [ ] Output esta em formato estruturado (JSON ou markdown com secoes claras) para consumo da proxima fase
- [ ] Nenhuma hipotese e subjetiva — todas tem metrica objetiva de validacao
