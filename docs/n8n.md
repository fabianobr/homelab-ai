# n8n

## Papel

Automações.

## Porta

```text
5678
```

## Exemplos

- Resumo diário
- Webhooks internos
- Monitoramento de preços
- Integração com Telegram
- Integração com Gmail/Calendar

## Segurança

Não expor n8n diretamente sem Cloudflare Access e autenticação.

Preferir:

```text
Cloudflare Access
+
usuário/senha forte
+
MFA
```

## Inicialização

O n8n é opcional nesta fase e fica atrás do profile `optional` no Docker Compose:

```bash
cd docker
docker compose --profile optional up -d n8n
```
