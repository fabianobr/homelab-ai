# CarWatch — Backup do banco e Heartbeat — Implementation Plan

> **For agentic workers:** este plano foi escrito para ser executado por um modelo barato
> (Claude Haiku ou qwen3-max). Cada passo traz caminho de arquivo, conteúdo exato e
> comando de verificação com critério objetivo. **Não improvise:** se um passo não fizer
> sentido, pare e reporte em vez de inventar. Passos marcados `[REQUER HUMANO]` não podem
> ser executados por modelo nenhum — pare e pergunte.

**Goal:** fechar as duas pendências P0 de `agents/carwatch/TODO.md` — o banco não tem
backup, e nada avisa se o timer parar de disparar.

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
- **`CLAUDE.md` faz parte da mudança.** Este trabalho cria um timer novo e uma porta de
  saída nova; a tabela de rotinas do `CLAUDE.md` precisa refletir isso no mesmo commit.
- **Teste junto.** O projeto tem 5.311 linhas de teste para 3.477 de código. Siga o
  padrão dos vizinhos (`tests/test_daily_stats.py`, `tests/test_run_sh.py`).
- **Não quebre o run semanal.** Nenhuma das duas features pode fazer o `weekly-run`
  falhar. Backup que falha avisa e segue; heartbeat roda em unit separada.

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
5. **O heartbeat é uma unit systemd separada, diária.** Não pode viver dentro do
   `weekly-run`: um processo não detecta a própria ausência.
6. **`OnFailure=` não é usado.** Ele dispara quando um run falha; o caso a detectar é o
   timer que **nunca disparou**, que não gera evento nenhum.

---

## O que este plano NÃO resolve (leia antes de achar que está coberto)

O heartcheck é um timer de usuário verificando outro timer de usuário. Eles compartilham
o mesmo domínio de falha: **se o `linger` do usuário for perdido num upgrade, os dois
param juntos e ninguém avisa** — que é justamente um dos cenários que o `TODO.md` cita.

O heartbeat cobre: banco fora do ar, run falhando em silêncio, `carwatch.timer`
desabilitado sozinho, Docker fora no horário, pipeline rodando mas sem produzir stats.

O heartbeat **não** cobre: máquina desligada por dias, `linger` perdido, conta do usuário
sem sessão. Só um serviço externo (dead man's switch) cobre silêncio total do host.
Ver Task 7.

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

### Task 4: Subcomando `heartbeat` no CLI

**Files:**
- Criar: `agents/carwatch/src/carwatch/heartbeat.py`
- Modificar: `agents/carwatch/src/carwatch/cli.py`
- Teste: `agents/carwatch/tests/test_heartbeat.py`

**Interfaces disponíveis** (já existem, use-as, não reescreva):
- `carwatch.db.get_open_pool()` / `carwatch.db.close_pool(pool)`
- `carwatch.settings.get_settings()` → tem `telegram_bot_token` e `telegram_chat_id`
- `carwatch.publishers.telegram.send_telegram_message(bot_token, chat_id, text) -> bool`
- `carwatch.logging_setup.configure_logging(level)`
- Tabela `daily_stats`, coluna `computed_at TIMESTAMPTZ DEFAULT now()`
  (`migrations/005_curation.sql`)

**Em `heartbeat.py`,** uma função assíncrona
`check_heartbeat(pool, max_age_days: int = 8) -> dict` que:

1. Roda `SELECT max(computed_at) AS last FROM daily_stats`.
2. Calcula a idade em dias do valor retornado.
3. Retorna `{"last": <datetime|None>, "age_days": <float|None>, "stale": <bool>}`.
   `stale` é `True` quando `last` é `NULL` (nunca rodou) **ou** quando a idade passa de
   `max_age_days`.

O limiar padrão é 8 dias — cadência semanal mais um dia de folga, para não alarmar por
um run que atrasou algumas horas.

**Em `cli.py`,** um comando Typer novo, seguindo o padrão de `@app.command(name="...")`
que o arquivo já usa:

```python
@app.command(name="heartbeat")
def heartbeat(max_age_days: int = 8):
```

Comportamento: abre o pool, chama `check_heartbeat`, fecha o pool. Se `stale` for
verdadeiro, manda uma mensagem de Telegram dizendo há quantos dias não há execução
bem-sucedida (ou que nunca houve) e loga em nível `error`. Se não for, apenas loga em
nível `info`.

**Sai sempre com código 0**, inclusive quando detecta silêncio. O alerta é a mensagem de
Telegram; fazer a unit falhar só acrescenta ruído no journal sem informar mais ninguém.

**Verificação:**
```bash
cd ~/homelab-ai/agents/carwatch
docker compose run --rm app heartbeat
```
Critério de aceite: sai com código 0 e loga uma linha de heartbeat. Como o run de
2026-08-29 gravou `daily_stats`, o esperado é **não** disparar alerta.

**Teste** (`tests/test_heartbeat.py`), seguindo `tests/test_daily_stats.py`:
- `stale` é `True` quando a query devolve `NULL`.
- `stale` é `True` para um `computed_at` de 10 dias atrás.
- `stale` é `False` para um `computed_at` de 2 dias atrás.
- `age_days` é `None` quando não há linha nenhuma.

---

### Task 5: Units systemd do heartbeat

**Files:**
- Criar: `agents/carwatch/systemd/carwatch-heartbeat.service`
- Criar: `agents/carwatch/systemd/carwatch-heartbeat.timer`

Copie o estilo de `agents/carwatch/systemd/carwatch.service` e `carwatch.timer` — leia os
dois antes de escrever, e mantenha as mesmas convenções de `WorkingDirectory`, usuário e
ambiente que eles já usam.

Diferenças em relação ao par existente:
- O `.service` roda `docker compose run --rm app heartbeat`, não `run.sh`.
- O `.timer` usa `OnCalendar=daily` e `Persistent=true`.
- Acrescente `RandomizedDelaySec=15m` para não competir com o run semanal.

**Instalação e verificação:**
```bash
systemctl --user daemon-reload
systemctl --user enable --now carwatch-heartbeat.timer
systemctl --user list-timers carwatch-heartbeat.timer
systemctl --user start carwatch-heartbeat.service
systemctl --user status carwatch-heartbeat.service --no-pager
```
Critério de aceite: o timer aparece em `list-timers` com próximo disparo em até 24h, e o
start manual do service termina em `Result=success`.

---

### Task 6: Documentação, no mesmo commit

**Files:**
- Modificar: `CLAUDE.md` (raiz)
- Modificar: `agents/carwatch/README.md`
- Modificar: `agents/carwatch/TODO.md`

1. **`CLAUDE.md`** — a convenção do repo exige atualizar este arquivo junto. Acrescente
   `carwatch-heartbeat` à tabela de rotinas autônomas (diário) e registre que o CarWatch
   passou a gerar dumps fora do repo. **Confira contra a realidade** com
   `systemctl --user list-timers`, não contra este plano.
2. **`README.md` do CarWatch** — documente `backup.sh`, a variável
   `CARWATCH_BACKUP_DIR`, a retenção de 8 arquivos, o comando de restauração
   (`pg_restore`) e o subcomando `heartbeat`.
3. **`TODO.md`** — marque os dois P0. Se o Task 2 não tiver sido respondido, **não**
   marque o backup como concluído: registre que está feito localmente e pendente de
   destino replicado.

---

### Task 7: [REQUER HUMANO] Decidir sobre dead man's switch externo

Leia de novo a seção "O que este plano NÃO resolve". O heartbeat do Task 4 não detecta
host desligado nem `linger` perdido, porque ele mesmo depende dos dois.

A cobertura completa exige algo **fora desta máquina** que espere um sinal e reclame
quando ele não chega — um ping de sucesso para um serviço externo no fim do `run.sh`.

Isso é uma decisão de arquitetura com implicações de privacidade: significa que um
terceiro passa a saber quando este host está de pé. Dado o cuidado que o repo tem com
exposição, **não implemente por conta própria.** Pergunte, e registre a resposta no
`TODO.md`.

**Alternativa que não acrescenta terceiro:** o Drive já recebe um `.dump` por semana.
A idade do arquivo mais recente em `gdrive:carwatch-backups/` é, por si só, um sinal de
vida — e é observável de qualquer lugar, inclusive de outra máquina. Não fecha o ciclo
sozinho (alguém ou algo precisa olhar), mas transforma "o host está vivo?" numa pergunta
respondível de fora sem contratar serviço nenhum.

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
- `systemctl --user list-timers` mostra `carwatch.timer` **e**
  `carwatch-heartbeat.timer`.
- Nenhum caminho começando com `/home/` em arquivo versionado:
  `git grep -n "/home/" -- . ':!*.lock'` não retorna nada novo.

## Commit sugerido

Dois commits, um por pendência, cada um com sua documentação junto:

```
feat(carwatch): dump semanal do banco com retenção de 8 cópias
feat(carwatch): heartbeat diário avisa quando o run semanal silencia
```

Não abra PR sem antes verificar `git status`: em 2026-08-29 havia trabalho de outra
sessão não commitado neste repositório (`deepseek-harness`). Commite **apenas** os
arquivos deste plano, nominalmente — nunca `git add -A`.
