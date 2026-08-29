# Continue.dev

## Papel

Assistente de código local integrado ao VS Code, usando modelos do Ollama.

## Configuração

Arquivo: `~/.continue/config.yaml`

Modelos disponíveis:
- **Ollama Qwen3 14B** — chat principal
- **Ollama Qwen3 8B** — tarefas rápidas
- **Ollama Qwen3-Coder 30B** — modelos de código

Tab autocomplete: modelo de código via Ollama (debounce 600ms).

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
