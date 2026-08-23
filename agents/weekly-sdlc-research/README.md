# Weekly SDLC Research Agent

Agente de pesquisa semanal automatizado que busca novidades sobre ferramentas
LLM agênticas para desenvolvimento de software local, avalia a viabilidade
para o hardware do homelab e atualiza o backlog em `research/sdlc-agentico/backlog.md`.

## O que faz

1. Executa queries de busca pré-configuradas via SearXNG local (fallback: DuckDuckGo)
2. Lê o backlog existente para extrair itens já conhecidos
3. Envia os resultados ao Ollama local (`qwen3:14b`) para análise e filtragem
4. Gera um relatório semanal em `reports/YYYY-MM-DD-weekly-research.md`
5. Adiciona os novos itens encontrados ao backlog em `research/sdlc-agentico/backlog.md`
6. Registra tudo em `research.log`

## Dependências

- **Ollama** rodando em `http://localhost:11434` com pelo menos um modelo instalado
  - Preferencial: `qwen3:14b` (cabe integralmente na GPU de 16 GB)
  - Fallbacks, em ordem: `qwen3:8b`, `llama3.2:latest`
- **Python 3.11+**
- **SearXNG** em `http://localhost:8080` (opcional — usa DuckDuckGo se indisponível)

## Como rodar manualmente

```bash
cd ~/homelab-ai
./agents/weekly-sdlc-research/run.sh
```

O script cria um virtualenv em `.venv/` na primeira execução e instala as dependências.

## Onde ficam os relatórios

```
agents/weekly-sdlc-research/reports/YYYY-MM-DD-weekly-research.md
```

Um arquivo por execução, com data no nome.

## Como o backlog é atualizado

O agente lê `research/sdlc-agentico/backlog.md`, extrai todos os nomes de ferramentas
já presentes, e adiciona apenas itens **novos** sob a seção
`## Novos itens pendentes de avaliacao`, agrupados por data de pesquisa.

A operação é **idempotente**: rodar duas vezes no mesmo dia não duplica entradas.

## Configuração

Edite `agents/weekly-sdlc-research/config.yaml` para:
- Adicionar/remover queries de busca
- Alterar o modelo Ollama primário e os fallbacks
- Adicionar itens ao `known_discarded` (nunca serão incluídos no backlog)
- Ajustar a URL do SearXNG

### Opções do Ollama

- `ollama_model`: modelo primário. O nome e a tag precisam corresponder exatamente
  a um modelo instalado; o agente nunca substitui por outra variante ou pelo
  primeiro modelo retornado pelo Ollama.
- `ollama_fallback_models`: fallbacks ordenados. O agente tenta o próximo apenas
  quando a requisição expira ou a resposta não passa na validação do schema.
- `ollama_max_attempts`: limite total de modelos tentados por execução (padrão: 2).
- `ollama_timeout_seconds`: timeout individual de cada tentativa (padrão: 240 s).
- `ollama_options.num_ctx`: contexto por requisição (8192), evitando herdar o
  contexto global de 65K e o custo de memória correspondente.
- `ollama_options.num_predict`: limite de tokens gerados (1536).
- `ollama_options.temperature`: temperatura da análise (0.2).

As chamadas usam `think: false` e JSON Schema nativo do Ollama. A resposta ainda é
validada deterministicamente antes de atualizar o backlog. São exigidos todos os
campos, tipos, enum de categoria, notas inteiras entre 1 e 5 e uma URL que exista
nos resultados coletados. A deduplicação normaliza números de headings, tags e
qualificadores para não reinserir variantes de um item já conhecido.

Se todas as tentativas falharem, o relatório de erro é escrito e enviado uma única
vez ao Telegram, mas o processo termina com código diferente de zero. Assim o
`systemd` não registra falsamente a execução como bem-sucedida.
O mesmo vale quando todas as queries retornam zero resultados, pois isso pode
indicar indisponibilidade simultânea dos backends de busca.

## Agendamento (systemd do usuário)

Executa toda sexta-feira às 19h, com catch-up após a máquina voltar a ligar
(`Persistent=true`) e atraso aleatório de até 2 minutos:

```bash
systemctl --user status weekly-sdlc-research.timer
systemctl --user list-timers --all
```

Para executar manualmente a mesma unidade:

```bash
systemctl --user start weekly-sdlc-research.service
journalctl --user -u weekly-sdlc-research.service -n 100 --no-pager
```

## Logs

```bash
tail -f agents/weekly-sdlc-research/research.log
```

## Testes unitários

Os testes usam mocks para HTTP, Ollama, relatório e Telegram; não executam buscas,
não escrevem no backlog real e não enviam notificações:

```bash
python3 -m unittest discover -s agents/weekly-sdlc-research/tests -v
```
