# CarWatch — Backup do banco e Dead man's switch — Implementation Plan

> **For agentic workers:** este plano foi escrito para ser executado por um modelo barato
> (Claude Haiku ou qwen3-max). Cada passo traz caminho de arquivo, conteúdo exato e
> comando de verificação com critério objetivo. **Não improvise:** se um passo não fizer
> sentido, pare e reporte em vez de inventar. Passos marcados `[REQUER HUMANO]` não podem
> ser executados por modelo nenhum — pare e pergunte.

**Goal:** fechar as duas pendências P0 de `agents/carwatch/TODO.md` — o banco não tem
backup, e nada avisa se o timer parar de disparar.

> A pendência de heartbeat foi fechada por um **dead man's switch externo** (Worker
> Cloudflare), não pelo heartbeat interno que este plano previa. Tasks 4, 5 e 7
> reescritas; ver `docs/superpowers/specs/2026-08-29-deadman-switch-design.md`.

**Contexto:** o CarWatch entrou em produção em 2026-08-28 e o primeiro run autônomo
rodou em 2026-08-29 09:00:54 com `Result=success`. As duas lacunas abaixo são o que
separa "está rodando" de "dá para confiar sem olhar".

**Tech Stack:** nada novo. `pg_dump` já vem na imagem `pgvector/pgvector:pg16`; Typer,
asyncpg e o publisher de Telegram já existem no projeto.

**Spec:** `agents/carwatch/TODO.md` §P0. Convenções do repo em `CLAUDE.md` da raiz.

---

## Global Constraints

- **O repo é público.** Nenhum dump, log operacional, token ou caminho absoluto de
  `$HOME` pode entrar em arquivo versionado. Rode `pre-commit run --all-files` antes de
  qualquer commit — gitleaks roda também no CI.
- **Commits em português**, conventional commits (`feat`, `fix`, `docs`, `chore`).
- **`CLAUDE.md` faz parte da mudança.** Este trabalho abre uma porta de saída nova (o
  ping) e um subprojeto novo (`infra/cloudflare/deadman-switch/`); o `CLAUDE.md` precisa
  refletir isso no mesmo commit. **Não** há timer systemd novo.
- **Teste junto.** O projeto tem 5.311 linhas de teste para 3.477 de código. Siga o
  padrão dos vizinhos (`tests/test_daily_stats.py`, `tests/test_run_sh.py`).
- **Não quebre o run semanal.** Nenhuma das duas features pode fazer o `weekly-run`
  falhar. Backup que falha avisa e segue; ping que falha avisa e segue.

---

## Decisões já tomadas (não reabrir)

1. **Dump completo, não seletivo.** O `TODO.md` observa que `raw_items`/`launch_events`
   são reconstruíveis. Ainda assim o dump é integral: é mais simples, mais seguro, e o
   banco é pequeno — medido em 2026-08-29, 1,4 MB com as 10 tabelas. Otimizar isso não
   vale a complexidade.
2. **Formato `-Fc` (custom, comprimido).** Restaura com `pg_restore`, permite restauração
   seletiva de tabela, e já vem comprimido.
3. **Dump depois do `weekly-run`, não antes** — para capturar os dados da semana.
4. **Retenção: 8 arquivos** (~2 meses de execuções semanais).
5. **A detecção de silêncio é um dead man's switch EXTERNO, não um heartbeat interno.**
   Decidido em 2026-08-29 (fecha o Task 7). Um segundo timer de usuário checando o
   primeiro morre junto quando o `linger` cai — mesmo domínio de falha. O switch é um
   Cloudflare Worker (`infra/cloudflare/deadman-switch/`): o `run.sh` pinga só após um
   run bem-sucedido; o cron do Worker alerta no Telegram se o ping não chega em 8 dias.
   Ver Tasks 4 e 5 (reescritas) e `docs/superpowers/specs/2026-08-29-deadman-switch-design.md`.
6. **`OnFailure=` não é usado.** Ele dispara quando um run falha; o caso a detectar é o
   timer que **nunca disparou**, que não gera evento nenhum.

---

## Cobertura da detecção de silêncio (dead man's switch)

O switch externo (Worker Cloudflare) cobre: `carwatch.timer` desabilitado sozinho,
Docker fora no horário, run falhando em silêncio, **e também** máquina desligada por
dias, `linger` perdido num upgrade, conta do usuário sem sessão — porque quem checa
está fora da máquina.

O que ele **não** distingue: "rodou mas não produziu stats". O ping só sai quando o
`weekly-run` retorna 0, então a lacuna é estreita; fechá-la (condicionar o ping a uma
checagem de `daily_stats`) fica anotado como YAGNI. O que ele depende: a própria
Cloudflare no ar e a conta ativa — modo de falha aceito de qualquer dead man's switch.

---

### Task 1: Script de backup

**Files:**
- Criar: `agents/carwatch/backup.sh`
- Teste: `agents/carwatch/tests/test_backup_sh.py`

**Comportamento:**

O script recebe o diretório de destino da variável `CARWATCH_BACKUP_DIR`, com default
`$HOME/.local/state/carwatch/backups`. **O destino nunca pode ser dentro do repositório**
— é um repo público e o dump contém dados.

Passos do script, nesta ordem:

1. `set -euo pipefail` e `cd` para o diretório do script.
2. Resolver `DEST="${CARWATCH_BACKUP_DIR:-$HOME/.local/state/carwatch/backups}"` e
   `mkdir -p "$DEST"`.
3. Dumpar **para um arquivo temporário primeiro**:
   `TMP="$DEST/.carwatch-$(date +%Y%m%d-%H%M%S).dump.partial"`.
   Isso importa: com `set -e` mais redirecionamento, um `pg_dump` que falha ainda deixa
   um arquivo truncado no lugar do bom. Escrever no temporário e só renomear no sucesso
   evita um backup corrompido se passar por válido.
4. `docker compose exec -T db pg_dump -U carwatch -Fc carwatch > "$TMP"`
5. Se o comando anterior falhou **ou** o arquivo tem menos de 1000 bytes: apagar o
   temporário, escrever mensagem em stderr e sair com código 1.
6. Renomear o temporário para `carwatch-YYYYMMDD-HHMMSS.dump`.
7. Rotação: manter os 8 `carwatch-*.dump` mais recentes, apagar o resto.
8. Imprimir na saída padrão o caminho do arquivo criado e o tamanho em bytes.

`chmod +x agents/carwatch/backup.sh`.

**Verificação:**
```bash
cd ~/homelab-ai/agents/carwatch
docker compose up -d db && sleep 5
./backup.sh
```
Critério de aceite: sai com código 0, imprime um caminho, e
`ls -la "${CARWATCH_BACKUP_DIR:-$HOME/.local/state/carwatch/backups}"` mostra um arquivo
`.dump` com mais de 1000 bytes e nenhum `.partial`.

**Para conferir que o dump é restaurável de verdade** (tamanho não prova nada):

```bash
docker cp <arquivo>.dump carwatch-db-1:/tmp/verify.dump
docker compose exec -T db pg_restore --list /tmp/verify.dump | grep "TABLE DATA"
docker compose exec -T db rm -f /tmp/verify.dump
```
Espere ver 10 tabelas, entre elas `llm_usage`, `sources` e `source_metrics` — as três que
o pipeline não reconstrói. **Não** tente `pg_restore --list /dev/stdin < arquivo`: o
formato custom precisa de arquivo seekable e um pipe não é, e o erro que aparece
(`did not find magic string in file header`) parece corrupção do dump quando na verdade
é o método de leitura que está errado.

**Teste** (`tests/test_backup_sh.py`), no estilo de `tests/test_run_sh.py` — asserções
sobre o conteúdo do script, sem subir Docker:
- `backup.sh` existe e tem bit de execução para o dono.
- Contém `pg_dump` e `-Fc`.
- Contém `.partial` (prova que usa arquivo temporário).
- **Não** contém nenhum caminho absoluto começando com `/home/` (evita vazar `$HOME`).

---

### Task 2: Enviar o dump para o Google Drive — RESOLVIDO, destino confirmado

O destino foi decidido e a autenticação já está feita (2026-08-29). **Não é mais um
bloqueio.**

- Ferramenta: `rclone` (já instalado, `v1.60.1`).
- Remote: `gdrive:` — já configurado e autenticado. `rclone about gdrive:` responde.
- Pasta de destino: `gdrive:carwatch-backups/`.
- Cópia local continua existindo em `$HOME/.local/state/carwatch/backups` (restauração
  rápida); o Drive é a cópia que sobrevive à perda da máquina.

> **Por que não o MCP do Google Drive:** aquelas ferramentas existem só dentro de uma
> sessão do Claude, não no host. Um systemd timer rodando sábado 09:00 sem ninguém
> presente não tem como chamá-las. `rclone` roda headless com token OAuth em
> `~/.config/rclone/rclone.conf` (fora do repo — nunca versionar).

**Acrescente ao final do `backup.sh` (Task 1), depois do passo 7 de rotação local:**

8. `rclone copy "$DEST" gdrive:carwatch-backups/ --include "carwatch-*.dump"`
9. Rotação remota: manter as 8 cópias mais recentes em `gdrive:carwatch-backups/`,
   apagar as demais (`rclone lsf` ordenado por nome + `rclone delete`). Os nomes são
   `carwatch-YYYYMMDD-HHMMSS.dump`, então ordem alfabética é ordem cronológica.
10. Falha do `rclone` **não** pode derrubar o script: o dump local já existe e vale.
    Escreva o erro em stderr e siga com código 0.

**Medido em 2026-08-29, use para dimensionar timeouts:** o dump tem 1,4 MB e o upload
levou 56s (~480 KiB/s). Não coloque timeout menor que 5 minutos em volta do `rclone`;
a banda de subida aqui é modesta e o dump cresce com o tempo.

**Verificação:**
```bash
rclone ls gdrive:carwatch-backups/
```
Critério de aceite: lista o `.dump` recém-criado com o mesmo tamanho em bytes do arquivo
local.

### Task 3: Chamar o backup no `run.sh`

**Files:**
- Modificar: `agents/carwatch/run.sh`
- Modificar: `agents/carwatch/tests/test_run_sh.py`

O `run.sh` hoje tem 14 linhas e termina em
`docker compose run --rm app weekly-run`.

Acrescente **depois** dessa linha um bloco que chama `./backup.sh` sem deixar que uma
falha de backup derrube o run. Como o arquivo tem `set -euo pipefail`, o chamado precisa
ser protegido:

```bash
if ! ./backup.sh; then
    echo "carwatch: backup falhou apos weekly-run" >&2
fi
```

Não troque o `set -euo pipefail` por nada mais frouxo.

**Verificação:** `pytest tests/test_run_sh.py -q` passa. O teste existente já exige que
a linha `docker compose run --rm app weekly-run` continue presente e que
`docker compose run --rm app carwatch weekly-run` **não** apareça — não quebre nenhuma
das duas. Acrescente ao teste uma asserção de que `backup.sh` é chamado.

---

### Task 4: Dead man's switch — Worker Cloudflare  ✅ FEITO (2026-08-29)

Substitui o "subcomando `heartbeat` no CLI" que este plano previa. Um heartbeat interno
não detecta a própria ausência quando o `linger` cai; um Worker externo sim.

**Implementado em:**
- `infra/cloudflare/deadman-switch/` — Worker (`src/index.mjs`, `src/logic.mjs`),
  `wrangler.toml`, testes `node:test`, `README.md`.
- Desenho completo: `docs/superpowers/specs/2026-08-29-deadman-switch-design.md`.

**Como funciona:**
- `POST /ping/carwatch` com `Authorization: Bearer <PING_TOKEN_CARWATCH>` grava
  `last-ping:carwatch` no KV.
- Cron `0 12 * * *` compara com agora; se `> 192h` (168h cadência + 24h folga = 8 dias)
  sem ping, manda `🔴` no Telegram (bot Hermes) e re-alerta 1×/dia até voltar.
- Ping de volta → `🟢` e limpa o estado.
- Endpoint público sem token → `401` e **não** reseta o cronômetro (um scanner não pode
  mascarar uma queda real).

**Secrets (via `wrangler secret put`, nunca no repo):** `PING_TOKEN_CARWATCH`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. `account_id` via env `CLOUDFLARE_ACCOUNT_ID`.

**Comprovado em 2026-08-29:** forçado `last-ping` de 14 dias atrás → `/__check` disparou
`🔴` no Telegram e virou `alert-state=alerted`; `deadman-ping.sh` real (com o `.env` de
produção) retornou 204 e trouxe o `🟢`.

---

### Task 5: Integração no `run.sh`  ✅ FEITO (2026-08-29)

Substitui as "units systemd do heartbeat" — não há timer novo, o ping vive no `run.sh`
que já roda.

**Feito em `agents/carwatch/`:**
- `deadman-ping.sh` — `curl -X POST` com Bearer e `--max-time 10 --retry 2`;
  `CARWATCH_DEADMAN_URL` vazio desliga o ping (mesmo padrão de `CARWATCH_BACKUP_REMOTE`).
- `run.sh` — carrega o `.env` no topo (`set -a; . ./.env; set +a` — o ping roda no host,
  fora do container) e chama `if ! ./deadman-ping.sh` **depois** do `weekly-run` e do
  `backup.sh`. Ping que falha escreve em stderr e não derruba o run — mesma proteção
  não-fatal do backup.
- `.env.example` — `CARWATCH_DEADMAN_URL` e `CARWATCH_DEADMAN_TOKEN`.
- Testes: `tests/test_deadman_ping_sh.py` (estilo `test_backup_sh.py`) e novas asserções
  em `tests/test_run_sh.py`. Suíte completa: 283 passed.

---


### Task 6: Documentação, no mesmo commit

**Files:**
- Modificar: `CLAUDE.md` (raiz)
- Modificar: `agents/carwatch/README.md`
- Modificar: `agents/carwatch/TODO.md`

1. **`CLAUDE.md`** — a convenção do repo exige atualizar este arquivo junto. **Não**
   acrescente linha na tabela de rotinas systemd (o switch não é systemd). Acrescente
   `infra/cloudflare/deadman-switch/` à árvore de diretórios e uma nota, na seção do
   CarWatch, de que o `run.sh` pinga o switch no fim. Registre também os dumps fora do
   repo. **Confira contra a realidade** (`systemctl --user list-timers`,
   `wrangler deployments list`), não contra este plano.
2. **`README.md` do CarWatch** — documente `backup.sh`, `CARWATCH_BACKUP_DIR`, a
   retenção de 8 arquivos, o `pg_restore`, e o `deadman-ping.sh` + as variáveis
   `CARWATCH_DEADMAN_URL` / `CARWATCH_DEADMAN_TOKEN`.
3. **`infra/SERVICES.md` e `infra/README.md`** — registrar o Worker `carwatch-deadman`.
4. **`TODO.md`** — marque os dois P0, apontando o de heartbeat para o switch.

---

### Task 7: Dead man's switch externo  ✅ RESOLVIDO (2026-08-29)

A decisão de privacidade foi tomada: o switch externo entra. A Cloudflare já é confiada
(túnel `cloudflared`), o ping não carrega dado do host além do IP de origem — que a
Cloudflare já vê pelo túnel — e o fluxo é sempre de saída, sem abrir nada inbound.

Implementado nas Tasks 4 e 5 (reescritas acima). Desenho e trade-offs completos em
`docs/superpowers/specs/2026-08-29-deadman-switch-design.md`.

---

## Verificação final antes de commitar

```bash
cd ~/homelab-ai/agents/carwatch
pytest -q                                    # toda a suíte, não só os testes novos
cd ~/homelab-ai
export PATH="$HOME/.venvs/tools/bin:$PATH"
pre-commit run --all-files                   # gitleaks; repo público
git status --short                           # nenhum .dump, nenhum .env
```

Critérios de aceite, todos obrigatórios:
- `pytest -q` passa inteiro, sem teste novo pulado.
- gitleaks passa.
- `git status` não mostra nenhum arquivo `.dump`, `.env` ou relatório operacional.
- `systemctl --user list-timers` mostra `carwatch.timer` (o switch **não** adiciona
  timer — é um Worker Cloudflare com cron próprio).
- `infra/cloudflare/deadman-switch/` tem `npm test` verde e a URL do Worker responde
  `200` em `/health`.
- Nenhum caminho começando com `/home/` nem o `account_id` da Cloudflare em arquivo
  versionado: `git grep -n "/home/" -- . ':!*.lock'` não retorna nada novo, e
  `git grep -ni "$CLOUDFLARE_ACCOUNT_ID"` (com a env setada) não retorna nada.

## Commit sugerido

Commits separados por peça, cada um com sua documentação junto:

```
feat(carwatch): dump semanal do banco com retenção de 8 cópias
feat(deadman-switch): Worker Cloudflare que alerta quando um agente para de pingar
feat(carwatch): pinga o dead man's switch no fim de um run bem-sucedido
```

Não abra PR sem antes verificar `git status`: em 2026-08-29 havia trabalho de outra
sessão não commitado neste repositório (`deepseek-harness`). Commite **apenas** os
arquivos deste plano, nominalmente — nunca `git add -A`.
