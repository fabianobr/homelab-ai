# Continue.dev

## Papel

Assistente de código local integrado ao VS Code, usando modelos do LM Studio e Ollama.

## Configuração

Arquivo: `~/.continue/config.yaml`

Modelos disponíveis:
- **LM Studio Qwen 14B** — chat principal (via `http://localhost:1234/v1`)
- **LM Studio Qwen 8B** — tarefas rápidas
- **LM Studio Autodetect** — usa qualquer modelo carregado no LM Studio
- **Ollama Qwen3 14B** — alternativa quando LM Studio não estiver rodando
- **Ollama Qwen3-Coder 30B** — modelos de código

Tab autocomplete: Qwen 14B via LM Studio (debounce 600ms).

## Uso padrão

| Atalho | Ação |
|---|---|
| `Ctrl+L` | Abrir chat lateral |
| `Ctrl+I` | Editar código inline |
| `Tab` | Aceitar autocomplete |
| `@codebase` | Indexar e buscar no projeto |

## Manutenção do projeto

- Scripts em `scripts/` → validar com `shellcheck` antes de commitar
- Alterações no `docker/docker-compose.yml` → rodar `bash scripts/healthcheck.sh`
- Novo serviço adicionado → atualizar `SERVICES.md` e `ROADMAP.md`
- Novo modelo instalado → documentar em `docs/<serviço>.md`
