# Fase 08 — Monitoring, KPIs e Observabilidade

## O Que e Esta Fase

Monitoring e a fase de coleta continua de dados sobre o sistema em producao e sobre o proprio ciclo agêntico. Dois niveis de observabilidade:

1. **Observabilidade do sistema:** o aplicativo implantado esta saudavel? Latencia, erros, uso de recursos.
2. **Observabilidade do ciclo agêntico:** os LLMs estao tomando boas decisoes? Quais fases falham mais? Qual e o custo (em tempo e tokens) de cada ciclo?

O Langfuse e a ferramenta central para o nivel 2. Para o nivel 1, a combinacao Prometheus + Grafana ou logs do Docker e suficiente para o homelab.

---

## Langfuse: Rastreamento de Decisoes dos Agentes

O Langfuse registra cada chamada LLM do ciclo SDLC com contexto completo. Os dados coletados alimentam a fase 09 (feedback loop).

### O Que o Langfuse Rastreia por Default

```
Por chamada LLM:
  - Fase do SDLC (tag)
  - Modelo usado
  - Tokens de entrada e saida
  - Latencia (tempo de resposta)
  - Input completo (prompt)
  - Output completo (resposta)
  - Metadata custom (ciclo, feature, tipo de tarefa)

Por ciclo completo:
  - Total de tokens consumidos
  - Custo estimado (se usando API paga)
  - Numero de fases executadas
  - Numero de retentativas
  - Resultado final (sucesso/falha)
```

---

## KPIs do Ciclo Agêntico

### KPIs de Eficiencia

| KPI | Formula | Meta Inicial | Como Medir |
|---|---|---|---|
| Taxa de sucesso de ciclos | ciclos concluidos / ciclos iniciados | > 80% | Langfuse — tag final_status |
| Taxa de sucesso por fase | fases ok / fases tentadas | > 85% por fase | Langfuse — tag fase + status |
| Tempo total por ciclo | timestamp_fim - timestamp_inicio | < 4h para features simples | Langfuse — trace duration |
| Tokens por ciclo | sum(tokens em todas as fases) | Monitorar baseline | Langfuse — token_count |
| Taxa de retrabalho | fases executadas > 1x por ciclo | < 15% | Langfuse — contar retentativas |
| Fallbacks para API paga | chamadas API / total de chamadas | < 10% | Langfuse — tag modelo |

### KPIs do Sistema (Producao)

| KPI | Ferramenta | Meta | Alerta em |
|---|---|---|---|
| Uptime dos servicos | Docker healthcheck | > 99.5% | < 99% em 24h |
| Latencia p95 da API | Logs do nginx / app | < 500ms | > 1000ms |
| Taxa de erro HTTP | Logs de acesso | < 1% | > 5% em 15min |
| Uso de VRAM (Ollama) | nvidia-smi | < 90% | > 95% |
| Uso de RAM | free -m | < 80% | > 90% |
| Espaco em disco | df -h | < 80% | > 90% |

---

## Como o LLM Local Analisa Logs e Metricas

O LLM atua como "analista de primeira linha" — recebe um resumo de metricas e identifica anomalias ou tendencias. Nao substitui um sistema de alerta proper (Prometheus/Grafana), mas e util para analise de tendencias e priorizacao.

### System Prompt para Analista LLM

```
Voce e um SRE (Site Reliability Engineer) experiente, analisando metricas de um
sistema em producao rodando no homelab (1 GPU, servicos Docker).

Ao receber metricas e logs, produza:

1. STATUS GERAL: OK / ATENCAO / CRITICO (uma linha)
2. ANOMALIAS DETECTADAS: liste o que destoa do padrao esperado, com dados especificos
3. TENDENCIAS: o que esta piorando gradualmente (pode nao ser problema agora, mas sera)
4. RECOMENDACOES: acoes priorizadas por urgencia (AGORA / ESTA SEMANA / PROXIMO CICLO)

Seja objetivo. Se os dados indicam que tudo esta OK, diga isso claramente.
Nao invente problemas onde nao existem. Baseie-se apenas nos dados fornecidos.
```

### Exemplos de Consultas ao LLM para Analise

```
Prompt para analise de latencia:
"Estas sao as metricas de latencia p95 dos ultimos 7 dias: [dados].
A feature de cache Redis foi deployada ha 3 dias. Houve melhoria significativa?
Calcule a variacao percentual e avalie se a hipotese H1 foi confirmada."

Prompt para analise de erros:
"Estes sao os 50 ultimos erros do servico de API: [logs].
Classifique por tipo, identifique se algum e recorrente, e sugira
qual deve ser investigado primeiro considerando impacto no usuario."
```

---

## Integracao Prometheus + Grafana + n8n + LLM

Para observabilidade de nivel 1 mais robusta, adicionar Prometheus e Grafana ao homelab:

```yaml
# Adicionar ao docker-compose.yml

  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    networks:
      - homelab-network

  grafana:
    image: grafana/grafana:11.0.0
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3002:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    networks:
      - homelab-network

  # Exporter para metricas do host
  node-exporter:
    image: prom/node-exporter:v1.8.1
    container_name: node-exporter
    restart: unless-stopped
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
    networks:
      - homelab-network

volumes:
  prometheus_data:
  grafana_data:
```

```yaml
# monitoring/prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'ollama'
    static_configs:
      - targets: ['ollama:11434']
    metrics_path: '/metrics'
```

---

## Workflow n8n de Coleta de Metricas (Agendado)

```
Trigger: Schedule — a cada hora

[Execute Command: metricas do host]
  free -m | awk 'NR==2{printf "RAM: %s/%s MB (%.0f%%)", $3,$2,$3*100/$2}'
  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.free --format=csv,noheader
  df -h / | awk 'NR==2{print $5}'

[HTTP: Langfuse API — buscar metricas do ultimo ciclo]
  GET /api/public/metrics/daily?fromTimestamp={{ agora_menos_1h }}

[HTTP: Prometheus API — buscar metricas do sistema]
  GET http://prometheus:9090/api/v1/query?query=process_resident_memory_bytes

[Set: consolidar metricas]
  metricas_consolidadas = { host, vram, langfuse, prometheus }

[HTTP: Ollama — analisar anomalias]
  prompt: "Analise estas metricas do homelab: {{ metricas }}. Ha anomalias?"

[IF: STATUS == CRITICO]
  |-- Sim: notificar + criar issue automaticamente
  |-- Nao: salvar em arquivo de estado

[Write File: /data/sdlc-state/08-monitoring-{{ data }}.json]
  metricas + analise do LLM

[HTTP: Langfuse — log desta execucao de monitoramento]
```

---

## Alertas e Notificacoes

Para notificacoes do homelab, o n8n pode usar:

- **Telegram:** via node Telegram do n8n — mensagens simples e rapidas
- **Email:** via node Email (SMTP) — relatorios mais detalhados
- **Webhook para outro sistema:** qualquer servico que aceite HTTP POST

Exemplo de mensagem de alerta:

```
ALERTA HOMELAB [CRITICO]
Status: CRITICO
Detectado: uso de RAM em 94% (limite: 90%)

Contexto:
- Ollama carregou devstral (13GB VRAM) enquanto ComfyUI estava ativo
- Soma de processos excedeu 30GB RAM

Acao sugerida: reiniciar Ollama para liberar VRAM e RAM
Comando: docker restart ollama

[Aprovar rollback automatico] [Ignorar por 1h]
```

---

## Dashboard de KPIs do Ciclo Agêntico no Langfuse

O Langfuse oferece dashboard nativo com:

- Grafico de volume de traces por dia (quantos ciclos ou chamadas LLM)
- Latencia media por modelo e por fase
- Distribuicao de tokens (percentis p50, p95, p99)
- Taxa de erro por tag de fase

Para KPIs customizados, usar a API do Langfuse e construir um dashboard no Grafana ou uma pagina HTML simples servida pelo n8n.
