# Padrões Operacionais

## Princípios

- Simplicidade antes de sofisticação
- Docker Compose antes de Kubernetes
- Uma interface principal: Open WebUI
- Tailscale para acesso privado
- Cloudflare Access para exposição pública
- Documentar toda alteração relevante

## Não usar por padrão

- Kubernetes
- Portainer exposto na internet
- Banco externo desnecessário
- Múltiplos reverse proxies sem necessidade
- Scripts mágicos sem documentação

## Convenções

### Diretórios

```text
/srv/homelab-ai
/srv/homelab-ai/data
/srv/homelab-ai/models
/srv/homelab-ai/backups
```

### Commits

Formato sugerido:

```text
feat: adiciona open webui
fix: corrige healthcheck do lm studio
docs: atualiza segurança cloudflare
chore: atualiza docker compose
```

## Critério de pronto

Uma mudança só está pronta quando:

1. Serviço sobe sem erro
2. Healthcheck passa
3. Documentação foi atualizada
4. Segurança foi revisada
5. Backup foi considerado
