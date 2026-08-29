# deadman-switch — dead man's switch dos agentes

Cloudflare Worker que detecta quando um agente `systemd` do repo **para de rodar**.
Um timer que deixa de disparar não gera evento nenhum — `OnFailure=` não pega, e um
heartbeat interno morre junto com o `linger`. Só algo fora da máquina resolve.

## Como funciona

```
run.sh (host)  --POST /ping/<agente> + Bearer token-->  Worker
                                                          └─ grava last-ping:<agente> no KV
cron diário 12:00 UTC  ──lê o KV──  se passou do prazo  ──>  Telegram (bot Hermes)
```

- O `run.sh` do agente pinga **só depois de um run bem-sucedido** (padrão não-fatal:
  ping que falha não derruba o run).
- O cron alerta se `agora - last-ping > interval_hours + grace_hours`.
- carwatch: 168h + 24h = alerta após **8 dias** sem ping.
- Enquanto stale, re-alerta 1×/dia. Quando o ping volta, o Worker manda `🟢` e limpa o
  estado.

## Endpoints

| Rota | Método | Auth | Efeito |
|---|---|---|---|
| `/ping/<agente>` | POST | `Authorization: Bearer <PING_TOKEN_<AGENTE>>` | registra ping; `204` |
| `/__check` | POST | Bearer de qualquer `PING_TOKEN_*` | roda a checagem sob demanda (mesmo efeito do cron); devolve JSON do que fez |
| `/` `/health` | GET | — | `200 carwatch-deadman ok` |

Sem token válido → `401` e **não** registra nada (um scanner não pode manter o switch
"vivo" e mascarar uma queda real).

## Config

Prazo por agente em `wrangler.toml` `[vars] AGENTS` (JSON, versionável, sem segredo):

```toml
AGENTS = '{"carwatch":{"interval_hours":168,"grace_hours":24}}'
```

Adicionar outro agente = mais uma entrada aqui + `wrangler secret put PING_TOKEN_<NOME>`
+ uma linha de ping no `run.sh` dele.

## Deploy

Pré-requisitos: `wrangler` autenticado (`wrangler login`), subdomínio `*.workers.dev`
definido na conta.

```bash
cd infra/cloudflare/deadman-switch
npm install
export CLOUDFLARE_ACCOUNT_ID=<account id>   # não fica no repo

# 1. KV namespace (uma vez) — cole o id retornado em wrangler.toml
npx wrangler kv namespace create DEADMAN

# 2. Secrets (uma vez)
openssl rand -hex 32 | npx wrangler secret put PING_TOKEN_CARWATCH
npx wrangler secret put TELEGRAM_BOT_TOKEN   # bot Hermes
npx wrangler secret put TELEGRAM_CHAT_ID

# 3. Deploy
npx wrangler deploy
```

O mesmo `PING_TOKEN_CARWATCH` vai em `agents/carwatch/.env` (gitignored) como
`CARWATCH_DEADMAN_TOKEN`.

## Testes

```bash
npm test          # node:test, funções puras de logic.mjs — sem rede
```

## Comprovar o alerta (sem esperar 8 dias)

```bash
export CLOUDFLARE_ACCOUNT_ID=<account id>
NS=<kv namespace id>   # de `wrangler kv namespace list`
U=https://carwatch-deadman.<subdominio>.workers.dev

# força um último ping de 10 dias atrás
npx wrangler kv key put --namespace-id $NS "last-ping:carwatch" \
  "$(date -u -d '10 days ago' +%Y-%m-%dT%H:%M:%SZ)" --remote
npx wrangler kv key put --namespace-id $NS "alert-state:carwatch" "ok" --remote

# dispara a checagem (mesmo efeito do cron)
curl -s -X POST -H "Authorization: Bearer $CARWATCH_DEADMAN_TOKEN" $U/__check
```

Espere `🔴 carwatch: sem ping há 10.0d …` no Telegram e `"alerted":true` no JSON.
Depois um `POST /ping/carwatch` com o token real traz o `🟢` e zera `alert-state`
(pode levar até ~60s pela consistência eventual do KV).

## Privacidade

O Worker nunca conecta no host — o fluxo é sempre de saída. Guarda no KV só
`agente → timestamp` e `agente → estado`. As mensagens têm só nome do agente e dias de
silêncio. A Cloudflare passa a inferir quando o host está ligado pela cadência dos pings
e vê o IP de origem — o mesmo que o túnel `cloudflared` já expõe.
