# Proposta D — OpenHands para Autonomia Completa

**Prioridade:** Media
**Viabilidade no homelab:** 3/5
**Relevancia para o SDLC:** 4/5
**Status:** Em avaliacao

---

## Resumo

OpenHands (antigo OpenDevin, 74k stars) e o agente mais autonomo da lista: recebe uma tarefa em linguagem natural e retorna um PR pronto, com loop de execucao completo em sandbox Docker. Contudo, a taxa de sucesso com modelos locais de 14B cai significativamente para tarefas abertas — o OpenHands foi projetado pensando em modelos frontier (Claude 4.5 Sonnet, GPT-4o). Para tarefas bem especificadas e de escopo pequeno, e uma opcao valida no homelab.

---

## Como Funciona

```
Usuario fornece tarefa em linguagem natural
           |
           v
+---------------------------+
|       OpenHands           |
|  [Planner LLM]            |
|  -> decompoe a tarefa     |
|  -> cria plano de acao    |
+---------------------------+
           |
           v
+---------------------------+
|    Sandbox Docker         |
|  [Executor]               |
|  -> executa comandos      |
|  -> le e escreve arquivos |
|  -> roda testes           |
|  -> verifica resultado    |
+---------------------------+
           |
           v
+---------------------------+
|  [Verificador LLM]        |
|  -> avalia se a tarefa    |
|     foi concluida         |
|  -> se nao: itera         |
|  -> se sim: cria PR       |
+---------------------------+
           |
           v
     PR criado no git
```

O loop de execucao e autonomo: o modelo planeja, executa, verifica o resultado e itera ate concluir ou esgotar tentativas. Isso e radicalmente diferente dos agentes assistivos (Aider, OpenCode) onde o humano conduz a sessao.

---

## Pros

- O mais proximo de "dar uma tarefa e receber um PR pronto"
- Loop autonomo completo — sem interacao humana durante a execucao
- Sandbox Docker: execucao segura, sem risco de danificar o host
- Suporte a multiplos backends de LLM (incluindo Ollama)
- Retorna PR com diff revisavel — o humano ainda aprova antes do merge

## Contras

- Taxa de sucesso com modelos locais de 14B: ~40-60% em tarefas complexas
- Melhor com modelos frontier (Claude 4.5 Sonnet atinge ~80-90%)
- Tarefas abertas (ex: "melhore a performance do sistema") tendem a falhar ou gerar mudancas incoerentes
- Consome mais VRAM por sessao que Aider (o loop de planejamento usa contexto longo)
- Latencia alta: uma tarefa simples pode levar 10-30 minutos com modelos locais
- Dificil de debugar quando falha — o loop autonomo nao e transparente

---

## Taxa de Sucesso Esperada por Tipo de Tarefa

| Tipo de Tarefa | Taxa de Sucesso (modelo local 14B) | Taxa de Sucesso (Claude 4.5 Sonnet) |
|---|---|---|
| Bugfix isolado com erro claro | 70-80% | 90-95% |
| Adicionar campo em formulario existente | 65-75% | 85-90% |
| Implementar endpoint REST bem especificado | 55-70% | 80-90% |
| Escrever testes para funcao existente | 60-75% | 85-90% |
| Refactoring de funcao (pre/pos definidos) | 55-65% | 75-85% |
| Feature media (5-10 arquivos, spec clara) | 35-50% | 65-80% |
| Feature aberta (sem spec detalhada) | 20-35% | 50-65% |
| Refactoring de arquitetura | 15-25% | 40-60% |

**Conclusao pratica:** OpenHands com modelos locais e viavel para tarefas pequenas e bem definidas. Para tarefas medias e grandes, ou usar Aider com supervisao humana, ou aceitar a taxa de falha e revisar o PR cuidadosamente.

---

## Casos de Uso Ideais

- Bugfix com stack trace claro e arquivo identificado
- Adicionar validacao a campo existente
- Gerar CRUD a partir de schema de banco de dados
- Traduzir funcao de uma linguagem para outra
- Gerar testes unitarios para uma funcao especifica
- Documentar uma API (gerar docstrings a partir de codigo existente)

## Casos a Evitar

- "Refatore o sistema de autenticacao"
- "Melhore a performance geral"
- "Adicione suporte a multi-tenancy"
- Qualquer tarefa que exija modificar mais de 10 arquivos em coordenacao
- Tarefas que exigem decisoes de produto/negocio durante a execucao

---

## Como Instalar: OpenHands com Docker

```bash
# Pre-requisito: Docker instalado e rodando
# Pre-requisito: Ollama rodando na mesma maquina

# Criar diretorio de dados
mkdir -p ~/openhands-data

# Executar OpenHands
docker run -d \
  --name openhands \
  --network homelab-network \
  -p 3000:3000 \
  -v ~/openhands-data:/opt/workspace_base \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE=docker.all-hands.dev/all-hands-ai/runtime:0.47-nikolaik \
  -e LOG_ALL_EVENTS=true \
  docker.all-hands.dev/all-hands-ai/openhands:0.47

# Verificar que subiu
docker logs -f openhands
```

Acessar em: `http://localhost:3000`

**Nota sobre versoes:** verificar a tag mais recente em `docker.all-hands.dev/all-hands-ai/openhands` — a versao 0.47 era a estavel em junho/2026.

---

## Como Configurar para Usar Ollama Local

Apos abrir `http://localhost:3000`, ir em Settings (icone de engrenagem):

```
Provider: Custom OpenAI-compatible
Base URL: http://ollama:11434/v1
API Key: (qualquer string — Ollama nao requer autenticacao)
Model: qwen3.5:14b ou devstral
```

Se o OpenHands nao esta na mesma Docker network que o Ollama, usar o IP do host:

```
Base URL: http://172.17.0.1:11434/v1  # IP padrao do Docker host
```

### Configuracao via variavel de ambiente (alternativa)

```bash
docker run -d \
  --name openhands \
  --network homelab-network \
  -p 3000:3000 \
  -v ~/openhands-data:/opt/workspace_base \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e LLM_API_KEY=ollama \
  -e LLM_BASE_URL=http://ollama:11434/v1 \
  -e LLM_MODEL=openai/qwen3.5:14b \
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE=docker.all-hands.dev/all-hands-ai/runtime:0.47-nikolaik \
  docker.all-hands.dev/all-hands-ai/openhands:0.47
```

---

## Integracao no Ciclo SDLC via n8n

O OpenHands pode ser acionado pelo n8n na fase 06 para tarefas de escopo menor:

```
n8n: "06 - Spec to Code (OpenHands)"
  |
  v
[Webhook: recebe spec + tipo_tarefa]
  |
  v
[IF: tipo_tarefa == "bugfix" OR "feature_pequena"]
  |
  v
[HTTP Request: OpenHands API]
  POST http://openhands:3000/api/conversations
  {
    "task": "{{ spec_formatada }}",
    "repository": "{{ repo_path }}"
  }
  |
  v
[Wait: poll status ate completar ou timeout 30min]
  |
  v
[HTTP Request: Langfuse — log resultado]
  |
  v
[IF: success] -> [Disparar CI/CD]
[IF: failure] -> [Notificar humano para intervencao]
```

---

## Dicas de Uso com Modelos Locais

1. **Seja especifico na tarefa:** quanto mais detalhada a descricao, maior a taxa de sucesso. Em vez de "adicionar autenticacao", escrever "adicionar middleware JWT em `src/middleware/auth.py` que valida o header `Authorization: Bearer <token>` usando a secret em `config.SECRET_KEY`"

2. **Definir claramente o criterio de sucesso:** o modelo precisa saber quando a tarefa foi concluida. Incluir criterio mensuravel: "a tarefa e concluida quando `pytest tests/test_auth.py` passar com 100%"

3. **Limitar o escopo:** tarefas que tocam muitos arquivos tendem a falhar. Dividir em subtarefas de 1-3 arquivos cada

4. **Revisar o PR gerado:** mesmo com taxa de sucesso de 70%, sempre revisar o diff antes de mergear — o modelo pode ter tomado atalhos ou ignorado convencoes do projeto

5. **Ter um timeout:** se o loop nao concluir em 30 minutos com modelos locais, provavelmente falhou em silencio. Cancelar e tentar com Aider supervisionado.
