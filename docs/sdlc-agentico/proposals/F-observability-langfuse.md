# Proposta F — Observabilidade com Langfuse

**Prioridade:** Media
**Viabilidade no homelab:** 4/5
**Relevancia para o SDLC:** 4/5
**Status:** Em avaliacao

---

## Resumo

Langfuse e uma plataforma de observabilidade para LLMs, self-hostable via Docker. Rastreia cada chamada ao modelo, decisao dos agentes, latencia, tokens consumidos e outputs. No contexto do SDLC agêntico, o Langfuse fecha o loop: os dados de monitoramento das fases anteriores alimentam a fase de deteccao de oportunidades (09-feedback-loop), que dispara novos ciclos de discovery.

---

## Como o Langfuse Fecha o Loop do SDLC

```
+--------------------+
|  08-MONITORING     |
|  KPIs + OBS        |
|                    |
|  Langfuse coleta:  |
|  - taxa de sucesso |
|  - latencia/fase   |
|  - tokens usados   |
|  - outputs ruins   |
+--------+-----------+
         |
         v
+--------------------+
|  09-FEEDBACK LOOP  |
|                    |
|  LLM analisa dados |
|  do Langfuse e     |
|  identifica:       |
|  - bugs recorrentes|
|  - oportunidades   |
|  - fases lentas    |
+--------+-----------+
         |
         v
+--------------------+
|  01-DISCOVERY      |
|                    |
|  Novo ciclo inicia |
|  com contexto de   |
|  oportunidades     |
|  detectadas        |
+--------------------+
```

Sem observabilidade, o ciclo e cego: nao ha dados objetivos para saber quais fases falham mais, quais modelos sao mais eficientes, ou quais tipos de tarefa tem maior taxa de retrabalho.

---

## Pros

- Rastreia cada decisao dos agentes com contexto completo (input, output, latencia, modelo)
- Self-hostable via Docker — dados ficam no homelab, sem dependencia de SaaS
- Integra com LangChain, LangGraph, OpenAI SDK, e HTTP direto
- Dashboard web com graficos de latencia, custo de tokens, taxa de sucesso
- Permite definir "evals" para medir qualidade dos outputs ao longo do tempo
- Gratuito para self-hosting (plano open-source)

## Contras

- Overhead de configuracao inicial: banco de dados PostgreSQL + ClickHouse necessarios para producao
- Sem integracao nativa com Ollama puro — precisa do wrapper (via LangChain, OpenAI SDK, ou HTTP manual)
- Dashboard e funcional mas menos polido que solucoes SaaS
- Manutencao de banco de dados: backups do PostgreSQL e ClickHouse sao responsabilidade do usuario

---

## Fases do SDLC Cobertas

| Fase | Como o Langfuse Ajuda |
|---|---|
| Todas as fases | Rastreia chamadas LLM em cada fase — input, output, latencia, modelo usado |
| 08-Monitoring | Fonte primaria de dados de KPIs do ciclo agêntico |
| 09-Feedback Loop | Dados do Langfuse alimentam o LLM que detecta oportunidades |
| 06-Spec to Code | Rastreia taxa de sucesso por tipo de tarefa e modelo usado |

---

## Docker Compose para Langfuse no Homelab

Adicionar ao `docker-compose.yml` existente:

```yaml
version: "3.8"

services:
  # ... seus servicos existentes (Ollama, n8n, Open WebUI, ComfyUI) ...

  langfuse-server:
    image: langfuse/langfuse:2
    container_name: langfuse
    restart: unless-stopped
    depends_on:
      langfuse-db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://langfuse:langfuse_password@langfuse-db:5432/langfuse
      - NEXTAUTH_SECRET=seu_segredo_aqui_mude_isso  # gerar com: openssl rand -hex 32
      - SALT=seu_salt_aqui_mude_isso                 # gerar com: openssl rand -hex 32
      - NEXTAUTH_URL=http://localhost:3001
      - TELEMETRY_ENABLED=false
      - LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES=true
      # Desabilitar criacao de conta publica — ambiente pessoal
      - AUTH_DISABLE_SIGNUP=false
    ports:
      - "3001:3000"
    networks:
      - homelab-network

  langfuse-db:
    image: postgres:15-alpine
    container_name: langfuse-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: langfuse_password
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - homelab-network

volumes:
  langfuse_db_data:

networks:
  homelab-network:
    external: true
```

```bash
# Subir Langfuse
docker compose up -d langfuse-server langfuse-db

# Verificar logs
docker logs -f langfuse

# Acessar em http://localhost:3001
# Criar conta admin na primeira visita
```

---

## Como Integrar com n8n (HTTP direto)

O n8n envia eventos ao Langfuse via HTTP Request node. Nao precisa de SDK — a API REST do Langfuse e suficiente.

### Gerar API Key no Langfuse

1. Acessar `http://localhost:3001`
2. Ir em Settings > API Keys
3. Criar chave com nome "n8n-integration"
4. Salvar `LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY`

### Node HTTP Request no n8n

```json
{
  "name": "Log no Langfuse",
  "type": "n8n-nodes-base.httpRequest",
  "parameters": {
    "method": "POST",
    "url": "http://langfuse:3001/api/public/ingestion",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpBasicAuth",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "batch": [
        {
          "type": "trace-create",
          "body": {
            "id": "{{ $execution.id }}",
            "name": "{{ $json.fase }}",
            "input": "{{ $json.input }}",
            "output": "{{ $json.output }}",
            "metadata": {
              "modelo": "{{ $json.modelo }}",
              "fase_sdlc": "{{ $json.fase }}",
              "duracao_ms": "{{ $json.duracao_ms }}"
            },
            "tags": ["sdlc-agêntico", "homelab"],
            "timestamp": "{{ $now }}"
          }
        }
      ]
    }
  }
}
```

---

## Como Integrar com Ollama (via Wrapper Python)

Para projetos Python que chamam Ollama diretamente, usar o decorator do Langfuse:

```python
# pip install langfuse langchain-community

import os
from langfuse import Langfuse
from langfuse.decorators import observe
from langchain_community.llms import Ollama

os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
os.environ["LANGFUSE_HOST"] = "http://localhost:3001"

langfuse = Langfuse()
llm = Ollama(model="qwen3.5:14b", base_url="http://localhost:11434")

@observe(name="discovery-fase")
def executar_discovery(contexto: str) -> str:
    """Cada chamada e automaticamente rastreada pelo Langfuse."""
    prompt = f"PM: Analise este contexto e liste requisitos:\n{contexto}"
    resposta = llm.invoke(prompt)
    return resposta

# Uso
resultado = executar_discovery("Contexto do projeto...")
# O Langfuse ja registrou: input, output, latencia, modelo
```

---

## KPIs Rastreados pelo Langfuse no Ciclo SDLC

| KPI | Como Medir via Langfuse | Meta Inicial |
|---|---|---|
| Taxa de sucesso por fase | % de traces sem erro por fase_sdlc tag | > 80% |
| Latencia media por fase | p50/p95 de duracao por fase | Discovery < 30s, Coding < 5min |
| Tokens por ciclo completo | Total de tokens em traces de 1 ciclo | Monitorar baseline |
| Taxa de retrabalho | # de execucoes da mesma fase no mesmo ciclo | < 2x por fase |
| Qualidade do output | Score manual (1-5) registrado como feedback | > 3.5/5 media |
| Fases mais lentas | Comparar latencia media entre fases | Identificar gargalos |

---

## Configurar Evals no Langfuse

O Langfuse permite definir "evals" — metricas automaticas de qualidade aplicadas aos outputs:

```python
from langfuse import Langfuse

langfuse = Langfuse()

# Registrar score de qualidade apos revisao humana de um output
langfuse.score(
    trace_id="id-do-trace",
    name="qualidade_spec",
    value=4.0,  # escala 1-5
    comment="Spec clara e completa, sem ambiguidades"
)

# Ou via n8n: HTTP POST para http://langfuse:3001/api/public/scores
```

Com dados suficientes, e possivel identificar automaticamente quais tipos de tarefa, modelos e prompts produzem outputs de maior qualidade — fechando o loop de melhoria continua do ciclo agêntico.
