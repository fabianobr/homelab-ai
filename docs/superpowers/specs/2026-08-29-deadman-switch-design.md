# Dead man's switch para os agentes systemd — Design

**Data:** 2026-08-29
**Status:** desenho aprovado, pendente de plano de implementação
**Substitui:** Tasks 4 e 5 de `docs/superpowers/plans/2026-08-29-carwatch-backup-heartbeat.md`
(heartbeat interno + units systemd — removidos, ver §8)

## Problema

Cinco rotinas rodam por `systemd timer` do usuário. Todas só falam quando têm o que
dizer. O caso não coberto é a rotina que **não roda**: `linger` perdido num upgrade,
timer desabilitado sozinho, máquina desligada por dias, Docker fora no horário. Um
evento que não acontece não gera log nem alerta, e "o agente parou há 3 semanas" fica
indistinguível de "semana tranquila".

Heartbeat interno (outro timer de usuário checando o primeiro) não resolve: os dois
compartilham `linger` e sessão do usuário — caem juntos. Só algo **fora da máquina**
detecta silêncio total do host.

## Decisão

Um Cloudflare Worker (free tier) com **cron trigger**. O `run.sh` do agente faz um
`POST` de saída só depois de um run bem-sucedido; o cron do Worker alerta no Telegram se
o ping não chegou dentro do prazo. Fluxo sempre de dentro para fora — o Worker nunca
conecta no host, não amplia superfície de ataque inbound.

Alternativas descartadas:
- **Serviço terceiro** (healthchecks.io etc.): adiciona outro terceiro além da
  Cloudflare, que já é confiada (túnel). Ethos do repo é self-host.
- **Durable Object com alarm** (deadline exato, sem polling): mais elegante, modelo
  mental mais pesado para um repo sem nada de JS. Cron + KV é depurável com
  `wrangler tail` / `wrangler kv key get`.

## Arquitetura

```
run.sh (host)  --POST /ping/<agente> + Bearer token-->  Worker (Cloudflare)
                                                          |
                                          grava last-ping:<agente> no KV
                                                          |
cron diário (0 12 * * *) --> lê KV --> se stale --> Telegram (bot Hermes)
```

### Componentes

```
infra/cloudflare/deadman-switch/
├── src/index.mjs        # fetch handler (ping) + scheduled handler (cron)
├── src/logic.mjs        # funções puras: isStale(), decideAlert() — sem deps Cloudflare
├── wrangler.toml        # config; SEM segredo, SEM account_id
├── test/logic.test.mjs  # node:test, zero deps
├── package.json         # devDep: wrangler
└── README.md            # deploy, secrets, como forçar alerta, nota de privacidade
```

JS puro (`.mjs`, módulo Worker, `fetch` nativo). Sem build, sem TS, zero deps de runtime.

### Config de agentes (`wrangler.toml [vars]`, versionável)

```toml
[vars]
AGENTS = '{"carwatch":{"interval_hours":168,"grace_hours":24}}'
```

`interval + grace` = prazo. Para o carwatch: 168h + 24h = 192h (8 dias) — cadência
semanal + 1 dia de folga, casa com o limiar de 8 dias do plano de heartbeat original.
Outros agentes entram depois só com uma entrada aqui + uma linha de ping no `run.sh`
deles. **Escopo deste trabalho: só o carwatch.**

### Estado (KV namespace `DEADMAN`)

| Chave | Valor | Escrito por |
|---|---|---|
| `last-ping:<agente>` | timestamp ISO 8601 | fetch handler |
| `alert-state:<agente>` | `"ok"` \| `"alerted"` | scheduled handler / fetch handler |

Uso: ~1 write/semana/agente + ~1 read/dia/agente. Muito abaixo do free tier de KV
(1k writes/dia, 100k reads/dia).

## Fluxo detalhado

### Ping (fetch handler)

`POST /ping/<agente>`:
1. Extrai `<agente>` do path. Não está em `AGENTS` → `404`.
2. `Authorization: Bearer <token>` ausente ou != secret `PING_TOKEN_<AGENTE>` → `401`,
   **não** atualiza nada. Comparação em tempo constante (`crypto.subtle.timingSafeEqual`).
3. Método != `POST` → `405`.
4. Grava `last-ping:<agente> = new Date().toISOString()`.
5. Se `alert-state:<agente> == "alerted"`: manda Telegram `🟢 <agente>: pings
   normalizados` e seta `alert-state = "ok"`.
6. Responde `204`. Sem corpo, sem eco de dado.

### Checagem (scheduled handler, cron `0 12 * * *`)

Para cada agente em `AGENTS`:
1. Lê `last-ping:<agente>` e `alert-state:<agente>`.
2. `stale` = `last-ping` ausente **ou** `agora - last-ping > interval_hours + grace_hours`.
3. `decideAlert(stale, alert_state)`:
   - `stale && state == "ok"` → manda `🔴 <agente>: sem ping há Xd (esperado ≤ Yd)`,
     seta `state = "alerted"`.
   - `stale && state == "alerted"` → re-manda o alerta (cron é diário; mantém visível
     sem inundar). **Decisão do usuário: re-alerta diário, não alerta único.**
   - `!stale` → nada. (A mensagem de recuperação sai no ping, não aqui.)

### Telegram

`POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage` com
`chat_id = TELEGRAM_CHAT_ID`. Reusa o bot **Hermes** — mesmas credenciais que
`agents/carwatch/.env` já usa. Mensagens contêm só nome do agente e dias de silêncio.
Nada sobre o host, nada sobre o que o agente faz.

## Segurança e privacidade

- **Sem exposição inbound.** O Worker nunca conecta no host.
- **Token por agente** (`PING_TOKEN_CARWATCH`, …). Vazamento de um não mantém os outros
  "vivos". Sem token → o cronômetro não reseta, que é o ponto: um scanner não pode
  mascarar uma queda real.
- **Segredos só via `wrangler secret put`** — `PING_TOKEN_CARWATCH`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Ficam no dashboard Cloudflare, nunca no repo.
- **`wrangler.toml` versionado** carrega só: `name`, `AGENTS`, binding do KV (id do
  namespace — não é segredo). **Sem `account_id`** — passado por env
  `CLOUDFLARE_ACCOUNT_ID` no deploy (convenção de sanitização do repo). `gitleaks` no
  pre-commit é a rede de segurança.
- **Dado mínimo no KV:** `agente → timestamp` e `agente → estado`. Nada mais.
- **Preço aceito** (mesmo do túnel): a Cloudflare passa a inferir quando o host está
  ligado, pela cadência dos pings, e vê o IP residencial de origem — que já vê pelo
  `cloudflared`.
- **Blast radius se o Worker cair:** atacante ganha o token do bot Hermes. Idêntico ao
  risco atual (todos os agentes têm esse token no `.env`). Não amplia.
- **Deliberadamente fora (YAGNI):** WAF, rate-limit explícito (DDoS protection +
  free tier cobrem 1 `curl`/semana), Cloudflare Access no endpoint (quebraria o `curl`
  automático — o token faz esse papel).

## Integração no `run.sh` do carwatch

`run.sh` hoje não exporta o `.env` para o próprio shell (só o `docker compose` lê).

1. No topo, depois do `cd`:
   ```bash
   set -a; [ -f .env ] && . ./.env; set +a
   ```
2. Depois do bloco de backup (portanto só se `weekly-run` passou pelo `set -e`):
   ```bash
   if ! ./deadman-ping.sh; then
       echo "carwatch: ping do dead man's switch falhou" >&2
   fi
   ```

`deadman-ping.sh`: `curl -fsS --max-time 10 --retry 2 -X POST` para
`$CARWATCH_DEADMAN_URL` com header `Authorization: Bearer $CARWATCH_DEADMAN_TOKEN`.
`CARWATCH_DEADMAN_URL` vazio → sai 0 sem fazer nada (mesmo padrão de
`CARWATCH_BACKUP_REMOTE`). **Ping falho nunca derruba um run que deu certo** — igual ao
`if ! ./backup.sh`.

Novas variáveis em `agents/carwatch/.env.example`:
```
CARWATCH_DEADMAN_URL=https://carwatch-deadman.fshomelabai.workers.dev/ping/carwatch
CARWATCH_DEADMAN_TOKEN=
```

## Domínio

`carwatch-deadman.fshomelabai.workers.dev`. Subdomínio de conta `fshomelabai`
(confirmado pelo usuário). Endpoint interno — nome não importa. Migrar para route em
zona própria depois é trocar uma linha no `wrangler.toml`.

## Deploy (parâmetros confirmados)

- Account ID: `<account id — fora do repo>` (via env `CLOUDFLARE_ACCOUNT_ID`)
- `wrangler` já autenticado nesta máquina (`wrangler whoami` OK)
- `PING_TOKEN_CARWATCH`: gerado com `openssl rand -hex 32`, gravado em
  `agents/carwatch/.env` (gitignored) **e** `wrangler secret put`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: lidos de `agents/carwatch/.env`,
  registrados com `wrangler secret put`

## Testes

- `test/logic.test.mjs` (`node:test`, sem deps):
  - `isStale(null, ...)` → `true`
  - `isStale(agora - 10d, 192h)` → `true`
  - `isStale(agora - 2d, 192h)` → `false`
  - `decideAlert(true, "ok")` → `{alert:true, newState:"alerted"}`
  - `decideAlert(true, "alerted")` → `{alert:true, newState:"alerted"}`
  - `decideAlert(false, "alerted")` → `{alert:false, newState:"alerted"}` (recuperação
    é no ping)
  - `decideAlert(false, "ok")` → `{alert:false, newState:"ok"}`
- `agents/carwatch/tests/test_deadman_ping_sh.py` (estilo `test_backup_sh.py`): existe,
  executável, contém `--max-time` e `Authorization: Bearer`, **não** contém `/home/`.
- `test_run_sh.py`: nova asserção de que `deadman-ping.sh` é chamado e que a linha
  `weekly-run` continua presente.
- **E2E manual, executado neste trabalho:** `wrangler kv key put` um `last-ping:carwatch`
  antigo → dispara o scheduled handler (`wrangler dev --test-scheduled` +
  `curl .../__scheduled`) → **confirma a mensagem `🔴` no Telegram**. É a comprovação
  que o goal exige. Depois: um `POST /ping/carwatch` real → confirma `🟢` e
  `alert-state` de volta para `ok`.

## Documentação (mesmo commit da implementação)

- `docs/superpowers/plans/2026-08-29-carwatch-backup-heartbeat.md`: reescrever Tasks 4/5
  (heartbeat interno → "ver dead man's switch"), Task 6 (sem timer systemd novo no
  `CLAUDE.md`), Task 7 (`[REQUER HUMANO]` → resolvida, é isto).
- `CLAUDE.md` (raiz): nota do Worker + pasta nova no mapa de diretórios. **Sem** linha
  nova na tabela de rotinas systemd (não é systemd).
- `infra/SERVICES.md`, `infra/README.md`: registrar o Worker.
- `agents/carwatch/README.md`: documentar `deadman-ping.sh` e as duas variáveis.
- `agents/carwatch/TODO.md`: marcar o P0 de heartbeat, apontando para o switch.

## Limitação conhecida

O switch detecta *ausência de ping*, não "rodou mas não produziu stats" — o heartbeat
interno olhava `daily_stats.computed_at`. Como o ping só vem após `weekly-run` sair 0, a
lacuna é estreita. Fechá-la (condicionar o ping a uma checagem de stats) é YAGNI por
ora; fica anotado.

## Escopo explícito

**Neste trabalho:** só o carwatch. Worker genérico (agente no path + mapa `AGENTS`),
mas só uma entrada e só um `run.sh` tocado. Estender aos outros 4 agentes é trabalho
futuro, uma linha de config + uma linha de ping cada.
