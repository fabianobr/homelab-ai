# Rota opcional `groq-fast-public`

Esta rota do LiteLLM usa `qwen/qwen3.6-27b` no Groq com
`reasoning_effort=none`. Se o provedor falhar, o LiteLLM tenta
`qwen3.5:latest` local (9,7B, Q4_K_M). Nenhum workflow existente seleciona a
rota automaticamente.

## Segurança e opt-in

A chave fica apenas no `.env` local, que é ignorado pelo Git:

```dotenv
GROQ_API_KEY=<defina-localmente>
```

Uma requisição precisa escolher o alias e declarar explicitamente que os dados
são públicos:

```json
{
  "model": "groq-fast-public",
  "metadata": {"data_classification": "public"},
  "messages": [{"role": "user", "content": "Resuma estas notas públicas."}]
}
```

O guardrail roda antes do provedor e bloqueia por padrão:

- requisições sem `metadata.data_classification=public`;
- tokens, chaves privadas, credenciais atribuídas e endereços de rede privada;
- mensagens multimodais ou estruturas que o filtro textual não consegue inspecionar.

O filtro não registra nem redige o prompt: ele rejeita a requisição. A
classificação explícita continua sendo obrigatória porque expressões regulares
não conseguem provar que texto arbitrário é público.

## Evidência local da escolha

O benchmark de 2026-08-23 em
`/tmp/homelab-ai-groq-bench-20260823/results.reasoning-none.json` executou duas
tarefas com `qwen/qwen3.6-27b` e `reasoning_effort=none`: 2 respostas bem-sucedidas,
11/11 casos determinísticos aprovados, zero retries, 981 tokens de conclusão e
3,288 segundos totais. O arquivo permanece fora do repositório porque é evidência
de execução, não configuração operacional.

## Validação sem Groq

```bash
pytest -q infra/docker/tests/test_groq_fast_public.py
docker compose -f infra/docker/docker-compose.yml config --quiet
```

Os testes usam somente configuração e mocks; não fazem chamadas externas.
