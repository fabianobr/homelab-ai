# homelab-ai — Agent Instructions

As instruções canônicas para agentes estão em [`CLAUDE.md`](CLAUDE.md).

Este arquivo existe para compatibilidade com ferramentas que leem `AGENTS.md`
(opencode, codex, etc.). Siga o conteúdo de `CLAUDE.md`.

## Nota crítica de segurança

Este repo é **público** no GitHub. Antes de qualquer commit:

```bash
pre-commit run --all-files
```

Nunca inclua `.env`, tokens, chaves de API ou IPs internos em commits.
