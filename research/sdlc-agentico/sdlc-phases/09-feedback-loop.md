# Fase 09 — Detecção de Oportunidades e Feedback Loop

## O Que e Esta Fase

O feedback loop e a fase que fecha o ciclo SDLC agêntico. Apos o deploy e o monitoramento, o sistema precisa identificar automaticamente o que corrigir ou melhorar a seguir — e disparar um novo ciclo de discovery com esse contexto.

Sem esta fase, o ciclo SDLC e linear e manual: alguem precisa decidir o que fazer depois. Com ela, o ciclo se torna continuo: os dados de producao alimentam automaticamente a proxima iteracao.

---

## Como o Agente Identifica Oportunidades

O LLM analisa os dados coletados na fase 08 e os compara com os KPIs definidos nas hipoteses da fase 02. Com base nessa analise, classifica as oportunidades em duas categorias:

```
+------------------------------------------+
|          DADOS DE PRODUCAO               |
|  - Langfuse: taxa de sucesso por fase    |
|  - Logs: erros recorrentes               |
|  - Metricas: latencia, uptime            |
|  - KPIs: meta vs realizado               |
+------------------+-----------------------+
                   |
                   v
+------------------------------------------+
|          LLM: CLASSIFICADOR              |
|                                          |
|  BUGFIX URGENTE?                         |
|  Criterio: erro em producao + impacto    |
|  alto + reproducivel                     |
|                                          |
|  BUSINESS IMPROVEMENT?                   |
|  Criterio: oportunidade de melhoria de   |
|  produto identificada em metricas        |
+------------------+-----------------------+
                   |
                   v
         +---------+---------+
         |                   |
         v                   v
+------------------+ +------------------+
| BUGFIX           | | IMPROVEMENT      |
| -> fase 05       | | -> fase 01       |
| (spec de fix)    | | (novo discovery) |
+------------------+ +------------------+
```

---

## Criterios para Disparar Novo Ciclo de Discovery

### Criterios Automaticos (sem intervencao humana)

| Criterio | Threshold | Acao |
|---|---|---|
| Taxa de erro HTTP > 5% por 15 min | CRITICO | Bugfix imediato — pular discovery, ir para spec |
| Latencia p95 > 2x do baseline | ALERTA | Iniciar discovery focado em performance |
| Taxa de sucesso do ciclo agêntico < 60% | ALERTA | Discovery focado em melhoria do ciclo |
| Hipotese do ciclo anterior refutada | INFO | Discovery para reformulacao de hipoteses |
| Todos os KPIs no verde por 7 dias | INFO | Discovery de novas oportunidades (proativo) |

### Criterios Manuais (requerem input humano)

| Criterio | Como Capturar |
|---|---|
| Nova ideia de feature | Issue criada no git com label "sdlc-discovery" |
| Feedback de usuario | Webhook externo ou formulario que dispara o workflow |
| Mudanca de prioridade de negocio | Input manual no n8n via formulario |

---

## Como Priorizar: Bugfix Urgente vs Feature Nova

O LLM usa o seguinte framework de priorizacao:

```
System prompt para priorizacao:

Voce e um Product Manager analisando oportunidades para o proximo ciclo SDLC.
Dadas as seguintes oportunidades detectadas, priorize-as usando o framework ICE:
- I (Impact): impacto esperado no usuario ou sistema (1-10)
- C (Confidence): confianca que esta oportunidade e real e vale o investimento (1-10)
- E (Ease): facilidade de implementar no ciclo agêntico local (1-10)
Score ICE = I x C x E

Regras de override:
- BUGFIX CRITICO (erro em producao afetando funcionalidade principal): sempre prioritario, ICE = 999
- SEGURANCA (vulnerabilidade detectada): sempre prioritario, ICE = 998
- TECH DEBT BLOQUEANTE (impede novos desenvolvimentos): prioridade alta, ICE calculado normalmente mas com I >= 8
```

---

## O Loop Fecha: Saida desta Fase = Input para 01-Discovery

```
Output da fase 09:

{
  "ciclo_anterior": "2026-W25",
  "proxima_acao": "discovery" | "bugfix_spec" | "melhoria_ciclo",
  "oportunidades_priorizadas": [
    {
      "id": "OPP-001",
      "tipo": "business_improvement",
      "titulo": "Latencia de busca de produtos acima do baseline",
      "contexto": "Pos-deploy do cache Redis, a latencia p95 caiu de 820ms para 680ms (meta: <500ms). A hipotese H1 foi parcialmente confirmada. Investigar se o TTL do cache esta muito baixo.",
      "ice_score": 7.2,
      "fase_destino": "01-discovery",
      "dados_relevantes": {
        "latencia_atual": "680ms",
        "meta": "500ms",
        "hipotese_anterior": "H1"
      }
    }
  ],
  "contexto_para_discovery": "O ciclo 2026-W25 implementou cache Redis para produtos. A latencia melhorou 17% mas nao atingiu a meta de 30%. Proxima investigacao deve focar em: 1) TTL do cache, 2) estrategia de invalidacao, 3) compressao de payload. Dados de producao sugerem pico de miss rate as 14h-16h."
}
```

Este JSON e o input direto para a fase 01 do proximo ciclo — o discovery comeca com contexto rico ao inves de comecar do zero.

---

## Diagrama ASCII do Loop Completo

```
+-------------------------------------------------------------------+
|                    CICLO SDLC AGÊNTICO                            |
|                                                                   |
|  +-------------+    +---------------+    +---------------+        |
|  | 01-DISCOVERY|--->| 02-HIPOTESES  |--->| 03-UX DESIGN  |        |
|  | (contexto   |    | + DADOS       |    | (opcional)    |        |
|  |  + opp.     |    |               |    |               |        |
|  +-------------+    +---------------+    +-------+-------+        |
|         ^                                        |                |
|         |                                        v                |
|         |           +---------------+    +-------+-------+        |
|         |           | 05-SPECS      |<---| 04-ARQUITETURA|        |
|         |           | (PRD + Tecnica|    | (ADRs)        |        |
|         |           +-------+-------+    +---------------+        |
|         |                   |                                     |
|         |                   v                                     |
|         |           +-------+-------+                             |
|         |           | 06-SPEC TO    |                             |
|         |           | CODE          |                             |
|         |           | (Aider/       |                             |
|         |           |  OpenHands)   |                             |
|         |           +-------+-------+                             |
|         |                   |                                     |
|         |                   v                                     |
|         |           +-------+-------+    +---------------+        |
|         |           | 07-CI/CD +    |--->| 08-MONITORING |        |
|         |           | DEPLOY        |    | KPIs + OBS    |        |
|         |           +---------------+    +-------+-------+        |
|         |                                        |                |
|         |           +---------------+            |                |
|         +-----------| 09-FEEDBACK   |<-----------+                |
|                     | LOOP          |                             |
|                     | (oportunidades|                             |
|                     |  detectadas)  |                             |
|                     +---------------+                             |
|                                                                   |
|  Duracao estimada de um ciclo completo:                           |
|  - Feature simples: 2-6h (majoritariamente automatizado)          |
|  - Feature media: 6-12h (com pontos de aprovacao humana)          |
|  - Bugfix: 30min-2h                                               |
+-------------------------------------------------------------------+
```

---

## Workflow n8n do Feedback Loop

```
Workflow: "09 - Feedback Loop"

[Trigger: Schedule — todo domingo 18h]
[OU Trigger: Webhook — chamado pela fase 08 em caso de anomalia]
     |
     v
[Execute Command: Coletar dados das ultimas 2 semanas]
  - git log --oneline --since="2 weeks ago"
  - Langfuse API: traces das ultimas 2 semanas
  - Docker logs: erros e warnings
     |
     v
[HTTP: Langfuse API — KPIs do periodo]
  GET /api/public/metrics/daily?fromTimestamp={{ 2_semanas_atras }}
     |
     v
[Set: Consolidar contexto]
  ciclo_anterior, kpis, logs_erros, hipoteses_anteriores, resultados
     |
     v
[HTTP: Ollama — Identificar oportunidades]
  system: (analista LLM prompt)
  prompt: "Com base nos dados do periodo, identifique e priorize oportunidades
           para o proximo ciclo. Use framework ICE. {{ dados_consolidados }}"
     |
     v
[HTTP: Ollama — Classificar: bugfix ou improvement?]
  prompt: "Para cada oportunidade identificada, classifique como:
           BUGFIX_CRITICO, BUGFIX_NORMAL, IMPROVEMENT, TECH_DEBT ou DESCARTE"
     |
     v
[IF: existe BUGFIX_CRITICO?]
  |-- Sim: disparar workflow fase 05 direto (spec de fix urgente)
  |-- Nao: continuar para gerar contexto de discovery
     |
     v
[HTTP: Ollama — Gerar contexto para proximo discovery]
  prompt: "Sintetize as oportunidades priorizadas em um contexto rico
           para iniciar o proximo ciclo de discovery. {{ oportunidades }}"
     |
     v
[Write File: /data/sdlc-state/09-feedback-{{ data }}.md]
[Write File: /data/sdlc-state/next-cycle-context.json]
     |
     v
[HTTP: Langfuse — log do feedback loop]
     |
     v
[IF: auto_start_next_cycle == true]
  |-- Sim: Disparar workflow 01-discovery com next-cycle-context
  |-- Nao: notificar usuario para iniciar proximo ciclo manualmente
```

---

## Condicoes para Iniciar o Proximo Ciclo Automaticamente

Por padrao, o proximo ciclo de discovery **nao e iniciado automaticamente** — o usuario recebe uma notificacao com o contexto gerado e decide quando comecar. Isso garante controle humano sobre o ritmo de desenvolvimento.

Para habilitar inicio automatico, configurar a variavel no n8n:

```
AUTO_START_NEXT_CYCLE = false  # default seguro
```

Mudar para `true` apenas se o ciclo completo for estavel e confiavel o suficiente (taxa de sucesso > 85% por pelo menos 3 ciclos consecutivos).

---

## Formato da Notificacao de Fim de Ciclo

```
Ciclo SDLC 2026-W25 Concluido

Status: Sucesso parcial
Hipotese H1: PARCIALMENTE CONFIRMADA (latencia caiu 17%, meta era 30%)
Duracao total: 8h 23min
Tokens usados: 142.000 (estimativa R$ 0 — apenas Ollama local)

Proximas oportunidades identificadas:
1. [IMPROVEMENT] Otimizar TTL do cache Redis — ICE: 7.2
2. [TECH_DEBT] Refatorar endpoint de busca (latencia base ainda alta) — ICE: 5.8
3. [IMPROVEMENT] Adicionar cache para listagem de categorias — ICE: 5.1

Contexto para proximo ciclo salvo em: /data/sdlc-state/next-cycle-context.json

Iniciar proximo ciclo? [Sim] [Adiar 3 dias] [Revisar antes]
```
