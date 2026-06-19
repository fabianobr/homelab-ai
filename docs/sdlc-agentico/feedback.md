# Feedback — O Que Foi Testado e Não Funcionou

Este arquivo registra experiencias negativas com ferramentas avaliadas para o ciclo SDLC agêntico. O objetivo e evitar revisitar o mesmo caminho sem uma razao tecnica nova que justifique reavaliacao.

**Regra:** se uma ferramenta esta aqui com status "nao retomar", ela nao deve aparecer como sugestao viavel em nenhum contexto de planejamento futuro, a menos que haja uma mudanca de versao major com evidencias concretas de melhoria.

---

## Registro de Ferramentas Descartadas

### Cline

| Campo | Detalhe |
|---|---|
| Data do teste | Antes de junho/2026 |
| Versao testada | Desconhecida |
| Resultado | Experiencia ruim (avaliacao do usuario) |
| Status | **NAO RETOMAR** |

**Razao do descarte:** O usuario testou e teve experiencia ruim. Sem mais detalhes tecnicos registrados — a experiencia subjetiva foi suficiente para descartar. Cline e uma extensao de IDE (VSCode) que age como agente de coding; a experiencia nao correspondeu ao esperado em termos de qualidade de output ou usabilidade.

**O que nao fazer:** nao sugerir Cline como alternativa ao Claude Code ou como agente de coding viavel para este homelab.

---

### Continue.dev

| Campo | Detalhe |
|---|---|
| Data do teste | Antes de junho/2026 |
| Versao testada | Desconhecida |
| Resultado | Experiencia ruim (avaliacao do usuario) |
| Status | **NAO RETOMAR** |

**Razao do descarte:** O usuario testou e teve experiencia ruim. Continue.dev e uma extensao de IDE (VSCode/JetBrains) para code completion e assistencia de coding com modelos locais via Ollama. A experiencia nao foi satisfatoria — possivelmente por qualidade de completions, latencia, ou integracao com o fluxo de trabalho.

**O que nao fazer:** nao sugerir Continue.dev como solucao de code completion ou IDE integration para este homelab.

---

## Formato para Novos Registros

Ao testar uma ferramenta e obter resultado negativo, adicionar uma entrada neste arquivo com o seguinte formato:

```markdown
### [Nome da Ferramenta]

| Campo | Detalhe |
|---|---|
| Data do teste | YYYY-MM-DD |
| Versao testada | X.Y.Z ou "desconhecida" |
| Resultado | Breve descricao do que foi testado e o resultado |
| Status | NAO RETOMAR / REAVALIAR EM [data] / DESCARTADO COM CONDICAO |

**Razao do descarte:** Descricao tecnica do motivo. Inclua:
- O que especificamente nao funcionou
- Contexto do teste (hardware, modelo usado, tipo de tarefa)
- Se houve um workaround tentado e por que nao foi suficiente

**Condicao de reavaliar (se aplicavel):** Ex: "Reavaliar se versao 2.0 for lancada com suporte nativo a Ollama API-compatible."
```

---

## Condicoes para Reavaliar um Item Descartado

Um item descartado pode ser reavaliado se:

1. Nova versao major lancada com changelog que resolve especificamente o problema que gerou o descarte
2. Novo modelo de LLM local disponivel que muda o baseline de qualidade esperado (ex: modelo de 14B com 90%+ SWE-bench)
3. Mudanca no hardware do homelab (ex: upgrade para GPU com 32GB VRAM muda viabilidade de modelos maiores)
4. Evidencia externa de que o problema foi corrigido: relatos de outros usuarios em condicoes similares (1 GPU, Ollama local, sem API externa)

---

## Historico de Decisoes Relacionadas

- **jun/2026:** Decisao de focar em OpenCode e Aider como substitutos de Claude Code, em vez de extensoes de IDE (Cline, Continue.dev). Razao: agentes de terminal tem melhor controle de execucao, integracao com git, e nao dependem de IDE especifica.
- **jun/2026:** Stack base definida como Ollama + n8n (ja instalados), com avaliacao em andamento de agentes terminais e modelos de coding.
