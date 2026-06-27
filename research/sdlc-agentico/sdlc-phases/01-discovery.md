# Fase 01 — Discovery

## O Que e Esta Fase

Discovery e a fase de entendimento do problema. Antes de qualquer codigo ou especificacao, o ciclo agêntico precisa de contexto: o que esta acontecendo, quais problemas existem, quais oportunidades foram identificadas, e qual e o estado atual do sistema.

No contexto agêntico local, o Discovery nao e uma reuniao humana — e uma execucao automatizada que coleta contexto de multiplas fontes (logs, metricas, documentos existentes, resultados do ciclo anterior) e usa um LLM local para sintetizar esse contexto em insights acionaveis.

---

## Input Esperado

| Input | Fonte | Formato |
|---|---|---|
| Contexto do projeto | ARCHITECTURE.md, ROADMAP.md | Markdown |
| Problemas relatados | Issues do git, logs de erro | Texto livre |
| Metricas do ciclo anterior | Langfuse, logs de deploy | JSON/texto |
| Oportunidades detectadas | Output da fase 09 (feedback loop) | Markdown estruturado |
| Pesquisa externa (opcional) | SearXNG — novidades relevantes | JSON com trechos |

---

## Output Esperado

```markdown
## Discovery — Ciclo [data]

### Contexto Atual
[Resumo do estado do projeto em 3-5 paragrafos]

### Problemas Identificados
1. [Problema] — Evidencia: [fonte] — Impacto: Alto/Medio/Baixo
2. [Problema] — Evidencia: [fonte] — Impacto: Alto/Medio/Baixo

### Oportunidades
1. [Oportunidade] — Potencial: [descricao] — Origem: [fonte]
2. [Oportunidade] — Potencial: [descricao] — Origem: [fonte]

### Hipoteses Iniciais
1. Se [acao], entao [resultado], porque [raciocinio]
2. Se [acao], entao [resultado], porque [raciocinio]

### Recomendacao de Proxima Fase
[O que deve ser priorizaado na fase de hipoteses e qual e o escopo sugerido]
```

---

## Ferramentas LLM Recomendadas

| Ferramenta | Uso | Motivo |
|---|---|---|
| Qwen 3.5 14B (Ollama) | Sintese de contexto e geracao de insights | Melhor raciocinio geral, confortavel em VRAM |
| SearXNG | Pesquisa web complementar | Traz dados externos sem depender de API |
| n8n | Orquestracao do workflow de discovery | Ja instalado, visual, versionavel |

O modelo de coding (Devstral Small) nao e adequado para Discovery — e especializado em codigo, nao em raciocinio de produto/negocio.

---

## System Prompt para o Modelo de Discovery

```
Voce e um Product Manager e Analista de Negocio experiente, atuando como agente autonomo de discovery.

Sua tarefa e analisar o contexto fornecido e produzir um relatorio de discovery estruturado que inclua:
1. Resumo do estado atual do projeto
2. Problemas identificados com evidencias e nivel de impacto
3. Oportunidades de melhoria ou novos recursos
4. Hipoteses iniciais no formato: "Se [acao], entao [resultado mensuravel], porque [raciocinio]"
5. Recomendacao clara de qual hipotese deve ser priorizada no proximo ciclo

Seja objetivo e baseie-se apenas no contexto fornecido. Nao invente dados ou cite fontes que nao foram fornecidas.
Produza output em markdown estruturado com secoes claras.
Se o contexto for insuficiente para alguma secao, indique explicitamente "dados insuficientes" em vez de especular.
```

---

## Integracao com SearXNG

Para enriquecer o discovery com dados externos (novidades tecnicas, benchmarks, etc.):

```bash
# Chamar SearXNG via n8n HTTP Request node
POST http://searxng:8080/search
{
  "q": "{{ topico_pesquisa }}",
  "format": "json",
  "categories": "general",
  "language": "pt"
}

# Exemplo de topicos de pesquisa para discovery de ferramentas agenticas:
# "agente LLM coding local 2026"
# "Ollama benchmark modelos 14B junho 2026"
# "OpenCode vs Aider comparacao"
```

O n8n recebe os resultados do SearXNG, extrai os trechos relevantes (campos `content` e `title` de cada resultado), e os passa como contexto adicional ao LLM no prompt de discovery.

---

## Como o Agente Propoe Hipoteses Automaticamente

O LLM nao gera hipoteses "do nada" — ele as deriva do contexto fornecido. Para garantir hipoteses uteis:

1. **Alimentar com dados do ciclo anterior:** output do Langfuse (quais fases falharam, quais tarefas foram refeitas) e um excelente gerador de hipoteses
2. **Incluir issues abertas do git:** `git log --oneline | head -20` + `gh issue list --state open` passados como contexto
3. **Incluir metricas de deploy:** tempo de build, taxa de erro em producao, alertas recentes

Prompt adicional para geracao de hipoteses:

```
Com base nos dados de desempenho do ciclo anterior abaixo, formule 3 hipoteses testáveis
para o proximo ciclo. Priorize hipoteses que, se confirmadas, teriam o maior impacto positivo.

Dados do ciclo anterior:
{{ dados_langfuse }}

Formato esperado para cada hipotese:
- Hipotese: Se [acao especifica], entao [resultado mensuravel em X dias/semanas]
- Metrica de validacao: [como medir se a hipotese foi confirmada]
- Risco: [o que pode dar errado se esta hipotese estiver errada]
```

---

## Integracao com n8n (Workflow Trigger)

```
Trigger: Manual, agendado (toda segunda-feira 09h) ou webhook da fase 09

[Node 1: Coletar Contexto]
  - Ler ARCHITECTURE.md via Execute Command (cat)
  - Ler output da fase 09 de /data/sdlc-state/09-feedback.md
  - Buscar issues abertas: gh issue list --state open --json title,body

[Node 2: Pesquisa SearXNG (opcional)]
  - HTTP Request para SearXNG com topicos definidos
  - Extrair top 5 resultados por topico

[Node 3: Montar Prompt]
  - Set node: concatenar todos os inputs em um prompt estruturado

[Node 4: Chamar Ollama]
  - HTTP Request POST http://ollama:11434/api/generate
  - Model: qwen3.5:14b
  - System prompt: (ver acima)
  - Prompt: {{ contexto_montado }}

[Node 5: Salvar Output]
  - Write File: /data/sdlc-state/01-discovery.md
  - Timestamp no nome do arquivo

[Node 6: Log no Langfuse]
  - HTTP POST para Langfuse com trace da execucao

[Node 7: Disparar Fase 02]
  - HTTP Webhook POST http://n8n:5678/webhook/02-hipoteses
  - Body: {{ discovery_output }}
```

---

## Criterios de Qualidade do Output

Um output de discovery de qualidade deve ter:

- [ ] Pelo menos 3 problemas identificados com evidencias citadas
- [ ] Pelo menos 2 oportunidades com potencial descrito
- [ ] Pelo menos 2 hipoteses no formato correto (Se... entao... porque...)
- [ ] Recomendacao clara de priorizacao para a proxima fase
- [ ] Nenhuma informacao inventada — apenas o que esta no contexto fornecido
- [ ] Sem referencias a ferramentas descartadas (Cline, Continue.dev)
