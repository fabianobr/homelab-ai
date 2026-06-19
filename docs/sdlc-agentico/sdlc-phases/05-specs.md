# Fase 05 — Especificações

## O Que e Esta Fase

Specs sao o contrato entre o que foi decidido (discovery, hipoteses, arquitetura) e o que sera implementado (spec-to-code). Esta fase produz dois documentos principais:

1. **PRD (Product Requirements Document):** o que o produto/feature deve fazer, do ponto de vista de negocio e usuario
2. **Spec Tecnica:** como implementar — schemas de dados, contratos de API, interfaces de codigo, dependencias

Um LLM local de 14B produz specs de qualidade alta quando o contexto de entrada (ADRs, user stories, contexto do projeto) e bem estruturado. A spec resultante serve como input direto para o agente de coding na fase 06.

---

## Input Esperado

| Input | Fonte | Formato |
|---|---|---|
| ADRs aprovados | docs/adr/ | Markdown |
| User stories + criterios de aceitacao | Output fase 03 | Markdown |
| Hipoteses priorizadas | Output fase 02 | JSON/Markdown |
| Convencoes do projeto | ARCHITECTURE.md, STANDARDS.md | Markdown |
| Schemas existentes (se relevante) | Schema de banco, OpenAPI existente | YAML/SQL |

---

## Output Esperado

### PRD (Product Requirements Document)

```markdown
# PRD: [Nome da Feature/Melhoria]

**Versao:** 1.0
**Data:** YYYY-MM-DD
**Status:** Draft / Aprovado
**Ciclo SDLC:** [numero do ciclo]

## Contexto e Motivacao

[Por que esta feature/melhoria existe? Qual problema resolve?
Qual hipotese esta validando? Referencia ao item do backlog ou ADR.]

## Objetivos

- [Objetivo 1 mensuravel]
- [Objetivo 2 mensuravel]

## Nao esta no escopo

- [O que explicitamente NAO sera feito neste ciclo]
- [Features relacionadas que ficam para futuro]

## Requisitos Funcionais

### RF-01: [Nome]
**Como:** [persona]
**Quero:** [acao]
**Para:** [beneficio]
**Criterios de aceitacao:**
- CA1: [criterio especifico]
- CA2: [criterio especifico]

[Repetir para cada requisito funcional]

## Requisitos Nao-Funcionais

| Requisito | Valor | Metodo de medicao |
|---|---|---|
| Latencia p95 | < 200ms | Load test com k6 |
| Disponibilidade | 99.5% | Uptime monitor |
| Seguranca | Sem dados sensiveis em log | Audit de logs |

## Metricas de Sucesso

[Como saberemos que esta feature foi bem-sucedida em producao?]
- KPI 1: [metrica atual → meta em X dias]
- KPI 2: [metrica atual → meta em X dias]

## Dependencias e Riscos

| Item | Tipo | Mitigacao |
|---|---|---|
| Redis disponivel | Dependencia tecnica | Ja rodando no homelab |
| Latencia de 14B LLM | Risco de performance | Benchmark antes de deploy |
```

### Spec Tecnica

```markdown
# Spec Tecnica: [Nome]

## Schema de Dados

```sql
-- Adicionar campo de cache key
ALTER TABLE products ADD COLUMN cache_key VARCHAR(64) UNIQUE;
CREATE INDEX idx_products_cache_key ON products(cache_key);
```

## Contratos de API

```yaml
# openapi: 3.0.0
paths:
  /api/v1/products/{id}:
    get:
      summary: Buscar produto por ID
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        '200':
          description: Produto encontrado
          headers:
            X-Cache:
              description: HIT ou MISS
              schema:
                type: string
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Product'
        '404':
          description: Produto nao encontrado
```

## Interfaces de Codigo

```python
# src/cache/product_cache.py

class ProductCache:
    def get(self, product_id: int) -> dict | None:
        """Busca produto no cache. Retorna None se nao encontrado."""
        ...

    def set(self, product_id: int, data: dict, ttl: int = 300) -> None:
        """Armazena produto no cache com TTL em segundos."""
        ...

    def invalidate(self, product_id: int) -> None:
        """Remove produto do cache (ex: apos update)."""
        ...
```

## Arquivos a Criar/Modificar

| Arquivo | Acao | Descricao |
|---|---|---|
| src/cache/product_cache.py | Criar | Implementacao do cache de produtos |
| src/api/routes/products.py | Modificar | Integrar cache no endpoint GET /products/{id} |
| tests/test_product_cache.py | Criar | Testes unitarios do cache |
| docker-compose.yml | Verificar | Redis ja deve estar configurado |
```

---

## System Prompt para PM/Spec LLM

```
Voce e um Product Manager e Tech Lead experiente, especializado em escrever
especificacoes tecnicas claras e acionaveis para desenvolvimento agêntico.

Ao receber o contexto de uma feature ou melhoria, produza DOIS documentos:

DOCUMENTO 1 - PRD (Product Requirements Document):
- Contexto e motivacao (por que existe)
- Objetivos mensuráveis
- O que NAO esta no escopo (importante para agilidade)
- Requisitos funcionais com criterios de aceitacao (User Stories formais)
- Requisitos nao-funcionais (latencia, seguranca, disponibilidade)
- Metricas de sucesso em producao

DOCUMENTO 2 - Spec Tecnica:
- Schema de dados (SQL ou equivalente)
- Contratos de API (OpenAPI/YAML ou formato alternativo)
- Interfaces de codigo (assinaturas de funcoes/classes com docstrings)
- Lista de arquivos a criar e modificar (com descricao do que cada um faz)
- Sequencia de implementacao recomendada

Seja especifico: escreva especificacoes que um agente de coding possa implementar
sem perguntas adicionais. Se houver ambiguidade, resolva-a com uma decisao explicita
e documente o raciocinio.

Nao inclua implementacao de codigo — apenas interfaces e contratos.
```

---

## Como Usar o Output desta Fase como Input para Spec-to-Code

O agente de coding (Aider ou OpenCode) recebe a spec tecnica como contexto. O formato ideal e:

```bash
# Passando spec para o Aider
aider \
  --model ollama/devstral \
  --read docs/sdlc-state/05-spec-tecnica.md \
  --read ARCHITECTURE.md \
  --message "Implemente a spec em docs/sdlc-state/05-spec-tecnica.md. 
             Comece pelo arquivo src/cache/product_cache.py conforme as interfaces definidas.
             Faca um commit por arquivo criado/modificado."
```

A spec tecnica funciona como "manual de instrucoes" para o agente — quanto mais detalhada, maior a taxa de sucesso da implementacao.

---

## Integracao no n8n

```
Workflow: "05 - Specs"

[Webhook: recebe ADRs + user stories]
     |
     v
[HTTP: Ollama — Gerar PRD]
  system: (PM/Spec prompt)
  prompt: "Gere o PRD para a feature: {{ feature_contexto }}"
     |
     v
[HTTP: Ollama — Gerar Spec Tecnica]
  prompt: "Com base no PRD acima e nos ADRs {{ adrs }}, gere a spec tecnica"
     |
     v
[Write File: /data/sdlc-state/05-prd.md]
[Write File: /data/sdlc-state/05-spec-tecnica.md]
     |
     v
[Wait for Webhook: aprovacao humana (opcional)]
  timeout: 12h — se nao aprovado, continua automaticamente
     |
     v
[Disparar Fase 06]
  body: { spec_tecnica_path: "/data/sdlc-state/05-spec-tecnica.md" }
```

---

## Criterios de Qualidade das Specs

### PRD
- [ ] Contexto e motivacao estao claros — alguem novo ao projeto entenderia por que
- [ ] Objetivos sao mensuráveis (nao "melhorar experiencia" mas "reduzir latencia p95 em 30%")
- [ ] "Nao esta no escopo" e explicitio
- [ ] Cada requisito funcional tem pelo menos 2 criterios de aceitacao
- [ ] Metricas de sucesso em producao estao definidas

### Spec Tecnica
- [ ] Schema de dados e completo e valido (SQL sintaticamente correto)
- [ ] Contratos de API tem todos os campos, tipos e codigos de resposta
- [ ] Interfaces de codigo tem assinaturas completas e docstrings
- [ ] Lista de arquivos a modificar e exaustiva — nenhum arquivo "esquecido"
- [ ] Sequencia de implementacao respeita dependencias entre arquivos
