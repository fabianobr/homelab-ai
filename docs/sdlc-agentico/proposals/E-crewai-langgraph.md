# Proposta E — CrewAI/LangGraph para Pipeline Completo

**Prioridade:** Media
**Viabilidade no homelab:** 2/5
**Relevancia para o SDLC:** 4/5
**Status:** Pendente

---

## Resumo

CrewAI e LangGraph sao frameworks Python para orquestracao de agentes LLM multiplos. CrewAI define "crews" com roles (PM, Architect, Developer, Reviewer) e tasks, orquestrando a interacao entre eles. LangGraph modela o fluxo como um grafo de estado, com suporte a rollback, checkpointing e rastreabilidade. Ambos cobrem o ciclo SDLC de ponta a ponta na teoria — mas na pratica, a execucao serial em 1 GPU, a latencia de modelos locais e a aderencia inconsistente de modelos de 14B a output estruturado tornam a viabilidade baixa para uso continuo.

---

## CrewAI vs LangGraph: Comparacao

| Criterio | CrewAI | LangGraph |
|---|---|---|
| Curva de aprendizado | Baixa (declarativo, roles pre-definidos) | Alta (grafo de estado explicito) |
| Flexibilidade | Media (papeis e tarefas fixas) | Alta (qualquer fluxo modelavel) |
| Auditoria / rollback | Basica | Avancada (checkpointing nativo) |
| Producao | Media | Alta |
| Suporte a Ollama | Via LiteLLM ou OpenAI-compat | Via LangChain Ollama |
| Overhead de setup | Medio | Alto |
| Adequacao para 1 GPU | Media (serial mas simples) | Media (serial com mais controle) |
| Melhor para | Prototipagem de pipeline multi-agente | Pipeline de producao com rastreabilidade |

**Recomendacao:** para o homelab com 1 GPU e 1 usuario, o n8n (Proposta B) substitui ambos com menos complexidade. CrewAI/LangGraph fazem sentido se o ciclo precisar de auditoria profunda ou se o usuario ja tem experiencia com Python frameworks de agentes.

---

## Pros

- Cobre o ciclo completo de ponta a ponta com um unico framework
- LangGraph tem auditoria e rollback de estados — essencial para producao
- CrewAI e simples de configurar para prototipo rapido
- Roles mapeiam bem para as fases do SDLC (PM, Architect, Dev, Reviewer)
- Extensivel em Python puro — sem dependencia de interface visual

## Contras

- Com 1 GPU, execucao e estritamente serial — nao ha beneficio de "multi-agente" real
- Latencia alta por fase: cada role chama o LLM sequencialmente, podendo levar horas para um ciclo completo
- Complexidade de setup significativa vs n8n
- Modelos de 14B nem sempre aderem ao formato de output esperado por cada role — requer retry logic
- Sem interface visual para monitoramento (diferente do n8n)
- Manutencao: codigo Python mais fragil para manter em longo prazo que workflows n8n

---

## Limitacao Central: Serial em 1 GPU

Com Ollama e 1 GPU de 16GB VRAM, a execucao e necessariamente serial:

```
Tarefa recebida
    |
    v
[PM Role chama LLM]  <- espera resposta (30s-2min)
    |
    v
[Architect Role chama LLM]  <- espera resposta (30s-2min)
    |
    v
[Developer Role chama LLM]  <- espera resposta (2-10min para codigo)
    |
    v
[Reviewer Role chama LLM]  <- espera resposta (1-3min)
    |
    v
Resultado final
```

Em vez de "4 agentes trabalhando em paralelo" (o pitch do CrewAI), temos "4 chamadas LLM sequenciais com diferentes prompts". O beneficio real e o isolamento de responsabilidade por prompt — o que o n8n com system prompts especializados (Proposta C) ja resolve.

---

## Workaround: CPU Offload para Fases Nao-Interativas

Para fases que nao precisam de resposta imediata (discovery noturno, geracao de specs em background), e possivel usar modelos maiores com CPU offload:

```bash
# Ollama com offload parcial para CPU (usa RAM alem da VRAM)
# Com 32GB RAM disponivel, pode rodar modelos de ate ~30B com offload

OLLAMA_NUM_GPU_LAYERS=20 ollama run llama3.3:70b  # exemplo extremo
```

Para LangGraph/CrewAI em modo batch (nao-interativo):
- Fase de Discovery pode rodar de madrugada com modelo maior (ex: Qwen 3.5 32B com offload)
- Fase de Coding (interativa) continua com modelo de 14B na GPU

Isso nao muda a latencia por chamada, mas permite usar modelos mais capazes para as fases que nao precisam de resposta instantanea.

---

## Quando Faz Sentido Usar

**Usar CrewAI/LangGraph quando:**

1. O usuario ja e proficiente em Python e quer controle total sobre o fluxo
2. O ciclo de SDLC precisa de auditoria detalhada de cada decisao dos agentes (LangGraph tem checkpointing nativo)
3. Existe necessidade de retry logic complexo (ex: "se o Architect Role falhar 3x, escalar para modelo maior")
4. O projeto precisa de integracao com o ecossistema LangChain (ferramentas, retrievers, memoria)
5. O ciclo e executado em modo batch (nao-interativo), onde latencia nao e critica

**Nao usar quando:**

1. O objetivo e velocidade de setup — n8n e muito mais rapido para chegar ao primeiro workflow funcional
2. O ciclo precisa de interface visual para monitoramento e ajuste
3. Nao ha familiaridade com Python e gerenciamento de dependencias (venv, pip, etc.)
4. O ciclo e interativo e latencia importa — CrewAI/LangGraph adicionam overhead vs chamadas diretas ao Ollama

---

## Exemplo Minimo: CrewAI com Ollama

```python
# pip install crewai crewai-tools langchain-community

import os
from crewai import Agent, Task, Crew, Process
from langchain_community.llms import Ollama

# Configurar modelo Ollama
llm = Ollama(
    model="qwen3.5:14b",
    base_url="http://localhost:11434",
    temperature=0.3,
)

# Definir roles
pm = Agent(
    role="Product Manager",
    goal="Analisar o contexto e identificar os requisitos mais importantes",
    backstory="Voce é um PM experiente que transforma contexto de negocio em requisitos claros",
    llm=llm,
    verbose=True
)

architect = Agent(
    role="Software Architect",
    goal="Propor arquitetura adequada para os requisitos identificados",
    backstory="Voce é um arquiteto senior que avalia tradeoffs e documenta decisoes em ADRs",
    llm=llm,
    verbose=True
)

developer = Agent(
    role="Senior Developer",
    goal="Implementar a solucao conforme arquitetura definida",
    backstory="Voce é um dev senior que escreve codigo limpo, testável e bem documentado",
    llm=llm,
    verbose=True
)

# Definir tarefas
discovery_task = Task(
    description="Analise o contexto: {contexto}. Produza lista de requisitos priorizados.",
    agent=pm,
    expected_output="Lista de requisitos em markdown com prioridade Alta/Media/Baixa"
)

architecture_task = Task(
    description="Com base nos requisitos, proponha arquitetura. Documente em ADR.",
    agent=architect,
    expected_output="ADR em markdown com contexto, decisao e consequencias"
)

implementation_task = Task(
    description="Implemente a solucao conforme arquitetura. Gere codigo completo.",
    agent=developer,
    expected_output="Codigo Python completo com testes unitarios"
)

# Executar crew
crew = Crew(
    agents=[pm, architect, developer],
    tasks=[discovery_task, architecture_task, implementation_task],
    process=Process.sequential,
    verbose=True
)

resultado = crew.kickoff(inputs={"contexto": "Adicionar sistema de cache para reducao de latencia da API"})
print(resultado)
```

---

## Exemplo Minimo: LangGraph com Ollama

```python
# pip install langgraph langchain-community

from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_community.llms import Ollama

llm = Ollama(model="qwen3.5:14b", base_url="http://localhost:11434")

class SDLCState(TypedDict):
    contexto: str
    requisitos: str
    arquitetura: str
    codigo: str
    revisao: str
    fase_atual: str

def discovery(state: SDLCState) -> SDLCState:
    prompt = f"PM: Analise este contexto e liste requisitos priorizados:\n{state['contexto']}"
    state["requisitos"] = llm.invoke(prompt)
    state["fase_atual"] = "architecture"
    return state

def architecture(state: SDLCState) -> SDLCState:
    prompt = f"Architect: Com estes requisitos, proponha arquitetura em ADR:\n{state['requisitos']}"
    state["arquitetura"] = llm.invoke(prompt)
    state["fase_atual"] = "coding"
    return state

def coding(state: SDLCState) -> SDLCState:
    prompt = f"Developer: Implemente conforme arquitetura:\n{state['arquitetura']}"
    state["codigo"] = llm.invoke(prompt)
    state["fase_atual"] = "review"
    return state

def review(state: SDLCState) -> SDLCState:
    prompt = f"Reviewer: Revise este codigo e aponte problemas:\n{state['codigo']}"
    state["revisao"] = llm.invoke(prompt)
    state["fase_atual"] = "done"
    return state

def should_continue(state: SDLCState) -> str:
    return state["fase_atual"]

# Construir grafo
workflow = StateGraph(SDLCState)
workflow.add_node("discovery", discovery)
workflow.add_node("architecture", architecture)
workflow.add_node("coding", coding)
workflow.add_node("review", review)

workflow.set_entry_point("discovery")
workflow.add_conditional_edges("discovery", should_continue, {"architecture": "architecture"})
workflow.add_conditional_edges("architecture", should_continue, {"coding": "coding"})
workflow.add_conditional_edges("coding", should_continue, {"review": "review"})
workflow.add_conditional_edges("review", should_continue, {"done": END})

app = workflow.compile()

# Executar
result = app.invoke({"contexto": "Adicionar cache Redis para reducao de latencia", "fase_atual": "discovery"})
print(result["revisao"])
```
