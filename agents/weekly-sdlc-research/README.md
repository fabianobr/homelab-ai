# Weekly SDLC Research Agent

Agente de pesquisa semanal automatizado que busca novidades sobre ferramentas
LLM agênticas para desenvolvimento de software local, avalia a viabilidade
para o hardware do homelab e atualiza o backlog em `docs/sdlc-agentico/backlog.md`.

## O que faz

1. Executa queries de busca pré-configuradas via SearXNG local (fallback: DuckDuckGo)
2. Lê o backlog existente para extrair itens já conhecidos
3. Envia os resultados ao Ollama local (`qwen2.5-coder:14b`) para análise e filtragem
4. Gera um relatório semanal em `reports/YYYY-MM-DD-weekly-research.md`
5. Adiciona os novos itens encontrados ao backlog em `docs/sdlc-agentico/backlog.md`
6. Registra tudo em `research.log`

## Dependências

- **Ollama** rodando em `http://localhost:11434` com pelo menos um modelo instalado
  - Preferencial: `qwen2.5-coder:14b`
  - Fallback: `llama3.2:latest`
- **Python 3.11+**
- **SearXNG** em `http://localhost:8080` (opcional — usa DuckDuckGo se indisponível)

## Como rodar manualmente

```bash
cd /home/fabiano/homelab-ai
./agents/weekly-sdlc-research/run.sh
```

O script cria um virtualenv em `.venv/` na primeira execução e instala as dependências.

## Onde ficam os relatórios

```
agents/weekly-sdlc-research/reports/YYYY-MM-DD-weekly-research.md
```

Um arquivo por execução, com data no nome.

## Como o backlog é atualizado

O agente lê `docs/sdlc-agentico/backlog.md`, extrai todos os nomes de ferramentas
já presentes, e adiciona apenas itens **novos** sob a seção
`## Novos itens pendentes de avaliacao`, agrupados por data de pesquisa.

A operação é **idempotente**: rodar duas vezes no mesmo dia não duplica entradas.

## Configuração

Edite `agents/weekly-sdlc-research/config.yaml` para:
- Adicionar/remover queries de busca
- Alterar o modelo Ollama
- Adicionar itens ao `known_discarded` (nunca serão incluídos no backlog)
- Ajustar a URL do SearXNG

## Agendamento (cron)

Executa toda segunda-feira às 9h:

```cron
0 9 * * 1 cd /home/fabiano/homelab-ai && ./agents/weekly-sdlc-research/run.sh >> /tmp/weekly-research.log 2>&1
```

Para verificar o cron instalado:
```bash
crontab -l
```

## Logs

```bash
tail -f agents/weekly-sdlc-research/research.log
```
