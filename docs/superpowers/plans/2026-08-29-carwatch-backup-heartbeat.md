# CarWatch — Backup do Banco e Heartbeat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as duas pendências P0 de `agents/carwatch/TODO.md` — nenhum backup do banco e nenhum aviso se o timer semanal parar de disparar — com um `pg_dump` semanal automático e uma checagem de heartbeat independente que alerta no Telegram quando a última execução bem-sucedida está velha demais.

**Architecture:** Dois scripts bash novos e independentes um do outro, ambos rodando fora do container Docker (direto no host, via `run.sh` e via um segundo timer systemd):
`scripts/backup_db.sh` faz `docker compose exec -T db pg_dump -Fc` e grava com rotação de N cópias; `scripts/heartbeat_check.sh` lê a idade de um arquivo-marcador de sucesso (`data/last_weekly_run_ok`, escrito por `run.sh`) e dispara um alerta via `curl` direto na API do Telegram se estiver velho — **sem depender de Docker nem do Postgres estarem de pé**, porque o próprio cenário que ele precisa detectar ("o timer nunca disparou") pode coincidir com "o Docker também não subiu". O heartbeat roda num **timer systemd `--user` separado** (`carwatch-heartbeat.timer`, diário), não dentro do `carwatch.timer` semanal — é essa independência de trigger que cobre o caso que `OnFailure=` não cobre (TODO.md é explícito sobre isso: o caso a detectar é o timer que nunca disparou, não o run que falhou).

**Tech Stack:** Bash puro (sem Python, sem dependências novas) + `curl` (já presente em qualquer host Linux) + `docker compose exec` para o `pg_dump`. Testes em `pytest` (já é a stack de testes do projeto), rodando os scripts de verdade via `subprocess`, com um binário `docker`/`curl` fake no `PATH` — sem precisar de Postgres real nem de rede.

**Spec:** `agents/carwatch/TODO.md`, seção "P0 — antes de confiar no piloto automático" (as duas primeiras entradas: "Backup do banco" e "Heartbeat"). Não há SPEC.md/DESIGN.md cobrindo isso — são pendências pós-deploy, o TODO.md é a única fonte.

## Global Constraints

- Commits em português, Conventional Commits (`feat`, `fix`, `docs`, `chore`, `refactor`, `test`) — padrão do histórico deste repo.
- `pre-commit run --all-files` (gitleaks) **antes de todo commit** — o repo é público no GitHub. Se `pre-commit` não estiver no PATH, está em `~/.venvs/tools/bin` (exportar antes: `export PATH="$HOME/.venvs/tools/bin:$PATH"`).
- Nenhum segredo, token, ou caminho absoluto de `$HOME` **literal** pode entrar em arquivo versionado. Referenciar `$HOME` como variável de shell dentro de um script é permitido (não é um caminho literal gravado no arquivo) — é exatamente o padrão que `agents/weekly-cost-benefit/run-with-notify.sh` já usa para achar `$HOME/.hermes/.env`.
- Mudou agente, timer systemd, ou convenção operacional? `CLAUDE.md` (raiz do repo) é atualizado **no mesmo commit** que introduz a mudança visível em produção — não num commit separado depois.
- Qualquer mudança em `agents/carwatch/run.sh` exige atualizar `agents/carwatch/tests/test_run_sh.py` na mesma mudança (já existe e testa o conteúdo do arquivo).
- Testes ficam ao lado do código que testam, seguindo o padrão dos vizinhos deste repo (`tests/test_run_sh.py` ao lado de `run.sh`).
- Os testes deste plano **não** precisam de Postgres real (diferente da suíte Python principal do projeto, que precisa — ver `README.md` do agente): são scripts bash testados via `subprocess` com `docker`/`curl` falsos no `PATH`. Não é necessário `docker compose up -d db` nem criar `carwatch_test` para os passos deste plano — só é necessário no smoke test manual opcional (marcado como tal em cada tarefa).

---

## File Structure

```
agents/carwatch/
├── scripts/                          ← NOVO diretório
│   ├── backup_db.sh                  ← NOVO — pg_dump + rotação
│   └── heartbeat_check.sh            ← NOVO — checa idade do último sucesso, alerta Telegram
├── systemd/
│   ├── carwatch-heartbeat.service    ← NOVO
│   └── carwatch-heartbeat.timer      ← NOVO
├── tests/
│   ├── test_backup_db_sh.py          ← NOVO
│   ├── test_heartbeat_check_sh.py    ← NOVO
│   └── test_run_sh.py                ← MODIFICADO (novas asserções)
├── run.sh                            ← MODIFICADO (2 linhas novas)
├── .env.example                      ← MODIFICADO (nova var CARWATCH_BACKUP_DIR)
├── README.md                         ← MODIFICADO (seções "Backup do banco" e "Heartbeat")
└── TODO.md                           ← MODIFICADO (marca progresso das 2 pendências P0)

CLAUDE.md (raiz do repo)              ← MODIFICADO (tabela de rotinas + nota sobre Telegram)
```

`data/last_weekly_run_ok` (o arquivo-marcador que `heartbeat_check.sh` lê) **não** é versionado — `agents/carwatch/.gitignore` já ignora `data/` inteiro. `backups/carwatch/*.dump` (destino default do `backup_db.sh`) também não é versionado — o `.gitignore` da raiz do repo já ignora `backups/*` (confirmado com `git check-ignore -v backups/carwatch/qualquer-arquivo.dump`).

---

### Task 1: `scripts/backup_db.sh` — pg_dump semanal com rotação

**Files:**
- Create: `agents/carwatch/scripts/backup_db.sh`
- Test: `agents/carwatch/tests/test_backup_db_sh.py`
- Modify: `agents/carwatch/.env.example`
- Modify: `agents/carwatch/README.md`

**Interfaces:**
- Produces: um script executável, chamado sem argumentos, que lê `CARWATCH_BACKUP_DIR` do ambiente (ou de `.env`, se presente) e grava `<CARWATCH_BACKUP_DIR>/carwatch-<timestamp>.dump` via `docker compose exec -T db pg_dump`. Sai com código 0 em sucesso, 1 se o `db` não estiver `healthy` ou se o `pg_dump` falhar. Mantém só os 8 dumps mais recentes em `CARWATCH_BACKUP_DIR`.
- Consumes (Task 3): nada ainda — este script não depende de nenhuma outra tarefa deste plano. É chamado por `run.sh` na Task 3.

- [ ] **Step 1: Escrever o teste (vai falhar — o script ainda não existe)**

Crie `agents/carwatch/tests/test_backup_db_sh.py` com exatamente este conteúdo:

```python
"""tests/test_backup_db_sh.py"""
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "backup_db.sh"

FAKE_DOCKER_HEALTHY = """#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then
    echo "healthy"
    exit 0
fi
if [ "$1" = "compose" ] && [ "$2" = "exec" ]; then
    echo "-- fake pg_dump payload $RANDOM --"
    exit 0
fi
exit 1
"""

FAKE_DOCKER_UNHEALTHY = """#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then
    echo "starting"
    exit 0
fi
exit 1
"""


def _make_fake_docker(bin_dir, script_body):
    bin_dir.mkdir(exist_ok=True)
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(script_body)
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IXUSR)


def _run(tmp_path, docker_body, backup_dir=None, extra_env=None):
    bin_dir = tmp_path / "fakebin"
    _make_fake_docker(bin_dir, docker_body)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if backup_dir is not None:
        env["CARWATCH_BACKUP_DIR"] = str(backup_dir)
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10
    )
    return result


def test_backup_db_is_executable():
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR


def test_healthy_db_produces_dump_file(tmp_path):
    backup_dir = tmp_path / "out"
    result = _run(tmp_path, FAKE_DOCKER_HEALTHY, backup_dir=backup_dir)
    assert result.returncode == 0
    dumps = list(backup_dir.glob("carwatch-*.dump"))
    assert len(dumps) == 1
    assert dumps[0].read_text().startswith("-- fake pg_dump payload")


def test_unhealthy_db_aborts_without_creating_dump(tmp_path):
    backup_dir = tmp_path / "out"
    result = _run(tmp_path, FAKE_DOCKER_UNHEALTHY, backup_dir=backup_dir)
    assert result.returncode == 1
    assert not backup_dir.exists() or not list(backup_dir.glob("carwatch-*.dump"))


def test_rotation_keeps_only_the_8_most_recent_dumps(tmp_path):
    import time

    backup_dir = tmp_path / "out"
    backup_dir.mkdir()
    for i in range(10):
        f = backup_dir / f"carwatch-2026010{i:01d}T000000Z.dump"
        f.write_text("old")
        os.utime(f, (time.time() - (10 - i) * 3600, time.time() - (10 - i) * 3600))

    result = _run(tmp_path, FAKE_DOCKER_HEALTHY, backup_dir=backup_dir)
    assert result.returncode == 0
    remaining = list(backup_dir.glob("carwatch-*.dump"))
    assert len(remaining) == 8
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd agents/carwatch && python3 -m pytest tests/test_backup_db_sh.py -v`
Expected: FAIL — `scripts/backup_db.sh` não existe (erro tipo `FileNotFoundError` ou `No such file or directory`).

- [ ] **Step 3: Criar o script**

Crie o diretório e o arquivo `agents/carwatch/scripts/backup_db.sh` com exatamente este conteúdo:

```bash
#!/usr/bin/env bash
# agents/carwatch/scripts/backup_db.sh
#
# pg_dump semanal do banco carwatch. Chamado por run.sh logo após o
# weekly-run (TODO.md P0 "Backup do banco"). Formato -Fc (custom,
# comprimido) -- restaura com:
#   docker compose exec -T db pg_restore -U carwatch -d carwatch \
#     --clean --if-exists < caminho/do/arquivo.dump
#
# Destino configurável via CARWATCH_BACKUP_DIR (lido de .env se presente).
# Default: backups/carwatch/ na raiz do repo -- local-only, já gitignored
# (raiz do repo: "backups/*" no .gitignore). Ver README.md "Backup do
# banco" para o que falta pra isso valer como backup de verdade
# (replicação para fora deste host) -- esse passo exige decisão humana e
# NÃO está resolvido só por este script existir.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARWATCH_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$CARWATCH_DIR/../.." && pwd)"
cd "$CARWATCH_DIR"

if [ -f "$CARWATCH_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$CARWATCH_DIR/.env"
    set +a
fi

BACKUP_DIR="${CARWATCH_BACKUP_DIR:-$REPO_ROOT/backups/carwatch}"
KEEP=8
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="$BACKUP_DIR/carwatch-${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

if ! docker compose ps db --format '{{.Health}}' 2>/dev/null | grep -q healthy; then
    echo "[backup_db] db não está healthy -- abortando backup (não sobrescreve nada)." >&2
    exit 1
fi

docker compose exec -T db pg_dump -U carwatch -d carwatch -Fc > "${DUMP_FILE}.tmp"
mv "${DUMP_FILE}.tmp" "$DUMP_FILE"
echo "[backup_db] Dump salvo em $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))."

# Rotação: mantém só os $KEEP dumps mais recentes.
mapfile -t OLD_DUMPS < <(ls -1t "$BACKUP_DIR"/carwatch-*.dump 2>/dev/null | tail -n "+$((KEEP + 1))")
for f in "${OLD_DUMPS[@]:-}"; do
    if [ -n "$f" ]; then
        rm -f "$f"
        echo "[backup_db] Removido backup antigo: $f"
    fi
done
```

- [ ] **Step 4: Tornar o script executável**

Run: `chmod +x agents/carwatch/scripts/backup_db.sh`

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd agents/carwatch && python3 -m pytest tests/test_backup_db_sh.py -v`
Expected: `4 passed` (todas as 4 funções de teste em verde).

- [ ] **Step 6: Adicionar `CARWATCH_BACKUP_DIR` ao `.env.example`**

Em `agents/carwatch/.env.example`, no final do arquivo (depois da linha `ATOM_FEED_URL=https://example.com/feed.atom`), adicione:

```
# Diretório onde scripts/backup_db.sh grava os dumps pg_dump. Lido pelo
# script direto do .env (roda no host via run.sh, fora do container -- não
# passa por pydantic-settings). Se ausente, default é backups/carwatch/ na
# raiz do repo (local-only -- ver README.md "Backup do banco").
CARWATCH_BACKUP_DIR=
```

- [ ] **Step 7: Adicionar a seção "Backup do banco" ao `README.md`**

Em `agents/carwatch/README.md`, logo depois do parágrafo que termina em "...e ajuste `ATOM_FEED_URL` no `.env` pra URL pública real." (fim da seção "## Servindo o feed Atom") e antes de "## Riscos operacionais conhecidos", insira:

```markdown
## Backup do banco

`carwatch_db_data` é o único volume Docker deste agente e vive só neste
host. `raw_items`/`launch_events` o pipeline reconstrói com o tempo;
`llm_usage` (histórico de custo), `sources` e `source_metrics` (curadoria
acumulada) **não** — perder o volume é perder esse histórico de vez
(TODO.md).

`run.sh` chama `scripts/backup_db.sh` a cada execução semanal, logo após o
`weekly-run`: um `pg_dump -Fc` (formato custom, comprimido) do banco
`carwatch`, gravado em `$CARWATCH_BACKUP_DIR` (lido de `.env`; default
`backups/carwatch/` na raiz do repo — local-only, já gitignored). Mantém
só os 8 dumps mais recentes.

**Isso, sozinho, não é um backup de verdade** — só protege contra apagar
uma tabela por engano, não contra perder esta máquina, a menos que
`CARWATCH_BACKUP_DIR` aponte para um caminho que já é replicado pra fora
deste host (NAS, `rclone`, disco externo, etc.). Configure isso em `.env`
antes de contar com este mecanismo para esse cenário — ver TODO.md.

Restaurar um dump:

```bash
cd ~/homelab-ai/agents/carwatch
docker compose up -d db
docker compose exec -T db pg_restore -U carwatch -d carwatch --clean --if-exists \
  < backups/carwatch/carwatch-<timestamp>.dump
```
```

- [ ] **Step 8: Commit**

```bash
cd agents/carwatch
export PATH="$HOME/.venvs/tools/bin:$PATH"
cd /home/fabiano/homelab-ai && pre-commit run --all-files
cd agents/carwatch
git add scripts/backup_db.sh tests/test_backup_db_sh.py .env.example README.md
git commit -m "$(cat <<'EOF'
feat(carwatch): adiciona pg_dump semanal do banco (scripts/backup_db.sh)

TODO.md P0 "Backup do banco": llm_usage, sources e source_metrics não são
reconstruídos pelo pipeline -- perder o volume carwatch_db_data era
perder esse histórico de vez. Ainda falta apontar CARWATCH_BACKUP_DIR
para um destino replicado para fora deste host (ver README.md).
EOF
)"
```

---

### Task 2: `scripts/heartbeat_check.sh` — detecta a última execução bem-sucedida velha demais

**Files:**
- Create: `agents/carwatch/scripts/heartbeat_check.sh`
- Test: `agents/carwatch/tests/test_heartbeat_check_sh.py`

**Interfaces:**
- Produces: um script executável, chamado sem argumentos a partir de `agents/carwatch/`, que lê `data/last_weekly_run_ok` (arquivo com um timestamp Unix em segundos, uma linha). Se o arquivo não existe, ou se `now - timestamp > 8 dias`, envia uma mensagem de alerta para o Telegram (credenciais de `$HOME/.hermes/.env`, bot Hermes) e sai com código 1. Caso contrário, sai com código 0 sem enviar nada.
- Consumes: `data/last_weekly_run_ok` — escrito pela Task 3 (`run.sh`). Este script não depende de nenhuma outra tarefa para ser testado (os testes criam o arquivo diretamente); só depende da Task 3 para ter dado real em produção.

- [ ] **Step 1: Escrever o teste (vai falhar — o script ainda não existe)**

Crie `agents/carwatch/tests/test_heartbeat_check_sh.py` com exatamente este conteúdo:

```python
"""tests/test_heartbeat_check_sh.py"""
import os
import stat
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "heartbeat_check.sh"


def _fake_home_with_curl_stub(tmp_path):
    """Fake $HOME com .hermes/.env (credenciais Telegram falsas) e um
    `curl` stub no PATH que só loga a chamada em curl_calls.log em vez de
    bater na API real do Telegram.
    """
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    (home / ".hermes" / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=test-chat\n"
    )
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl_calls.log"
    curl_stub = bin_dir / "curl"
    curl_stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{curl_log}"\necho -n "200"\n')
    curl_stub.chmod(curl_stub.stat().st_mode | stat.S_IXUSR)
    return home, bin_dir, curl_log


def _run(tmp_path, heartbeat_file_content=None):
    home, bin_dir, curl_log = _fake_home_with_curl_stub(tmp_path)
    carwatch_dir = tmp_path / "carwatch"
    data_dir = carwatch_dir / "data"
    data_dir.mkdir(parents=True)
    if heartbeat_file_content is not None:
        (data_dir / "last_weekly_run_ok").write_text(heartbeat_file_content)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    # O script faz `cd "$(dirname "${BASH_SOURCE[0]}")/.."`, resolvendo
    # relativo a onde o *arquivo* do script está -- por isso ele é copiado
    # para dentro da árvore fake, não chamado direto do REPO_ROOT real.
    script_copy = carwatch_dir / "scripts" / "heartbeat_check.sh"
    script_copy.parent.mkdir(parents=True, exist_ok=True)
    script_copy.write_bytes(SCRIPT.read_bytes())
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        ["bash", str(script_copy)], env=env, capture_output=True, text=True, timeout=10
    )
    return result, curl_log


def test_heartbeat_check_is_executable():
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR


def test_fresh_heartbeat_file_exits_zero_and_does_not_alert(tmp_path):
    result, curl_log = _run(tmp_path, heartbeat_file_content=str(int(time.time())))
    assert result.returncode == 0
    assert not curl_log.exists()


def test_missing_heartbeat_file_exits_nonzero_and_alerts(tmp_path):
    result, curl_log = _run(tmp_path, heartbeat_file_content=None)
    assert result.returncode == 1
    assert curl_log.exists()
    assert "sendMessage" in curl_log.read_text()


def test_stale_heartbeat_file_exits_nonzero_and_alerts(tmp_path):
    ten_days_ago = int(time.time()) - 10 * 86400
    result, curl_log = _run(tmp_path, heartbeat_file_content=str(ten_days_ago))
    assert result.returncode == 1
    assert curl_log.exists()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd agents/carwatch && python3 -m pytest tests/test_heartbeat_check_sh.py -v`
Expected: FAIL — `scripts/heartbeat_check.sh` não existe.

- [ ] **Step 3: Criar o script**

Crie `agents/carwatch/scripts/heartbeat_check.sh` com exatamente este conteúdo:

```bash
#!/usr/bin/env bash
# agents/carwatch/scripts/heartbeat_check.sh
#
# TODO.md P0 "Heartbeat": nada avisava se carwatch.timer parasse de
# disparar (linger perdido, timer desabilitado, Docker fora do ar no
# horário). OnFailure= no .service não resolve -- só dispara quando o RUN
# falha, não quando o timer nunca chega a rodar. Este script roda a
# partir de um SEGUNDO timer systemd independente (carwatch-heartbeat.timer,
# ver systemd/), e deliberadamente não depende de Docker nem do Postgres
# estarem de pé -- só lê um arquivo local (data/last_weekly_run_ok,
# escrito por run.sh só quando o weekly-run termina com sucesso) e manda
# Telegram via curl direto, sem passar pelo container `app` nem pelo
# helper Python agents/lib/telegram_notify.py (que exigiria um venv no
# host só para isso).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

HEARTBEAT_FILE="data/last_weekly_run_ok"
THRESHOLD_DAYS=8
THRESHOLD_SECONDS=$((THRESHOLD_DAYS * 86400))
NOW="$(date -u +%s)"

STALE=false
REASON=""

if [ ! -f "$HEARTBEAT_FILE" ]; then
    STALE=true
    REASON="nunca completou uma execução semanal com sucesso (arquivo $HEARTBEAT_FILE ausente)"
else
    LAST="$(cat "$HEARTBEAT_FILE")"
    AGE=$((NOW - LAST))
    if [ "$AGE" -gt "$THRESHOLD_SECONDS" ]; then
        STALE=true
        AGE_DAYS=$((AGE / 86400))
        REASON="última execução semanal bem-sucedida foi há ${AGE_DAYS} dia(s) (limite: ${THRESHOLD_DAYS})"
    fi
fi

if [ "$STALE" = "false" ]; then
    echo "[heartbeat_check] OK: última execução bem-sucedida dentro do limite de ${THRESHOLD_DAYS} dias."
    exit 0
fi

echo "[heartbeat_check] ALERTA: $REASON"

HERMES_ENV="$HOME/.hermes/.env"
if [ -f "$HERMES_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$HERMES_ENV"
    set +a
fi

RAW_TELEGRAM_ALLOWED_USERS="${TELEGRAM_ALLOWED_USERS:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-${RAW_TELEGRAM_ALLOWED_USERS%%,*}}"

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "$CHAT_ID" ]; then
    echo "[heartbeat_check] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes -- alerta não enviado, só logado." >&2
    exit 1
fi

MESSAGE="⚠️ CarWatch heartbeat: $REASON"
curl -sS --max-time 10 -o /dev/null -w "%{http_code}" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" > /dev/null || true

exit 1
```

- [ ] **Step 4: Tornar o script executável**

Run: `chmod +x agents/carwatch/scripts/heartbeat_check.sh`

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd agents/carwatch && python3 -m pytest tests/test_heartbeat_check_sh.py -v`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
cd /home/fabiano/homelab-ai && pre-commit run --all-files
cd agents/carwatch
git add scripts/heartbeat_check.sh tests/test_heartbeat_check_sh.py
git commit -m "$(cat <<'EOF'
feat(carwatch): adiciona checagem de heartbeat (scripts/heartbeat_check.sh)

TODO.md P0 "Heartbeat": alerta no Telegram (bot Hermes) quando faz mais
de 8 dias desde a última execução semanal bem-sucedida, ou quando nunca
houve uma. Não depende de Docker/Postgres de pé -- só lê
data/last_weekly_run_ok (ainda não escrito por ninguém; isso vem na
próxima tarefa) e chama a API do Telegram direto via curl.
EOF
)"
```

---

### Task 3: Ligar os dois scripts ao `run.sh` semanal

**Files:**
- Modify: `agents/carwatch/run.sh`
- Modify: `agents/carwatch/tests/test_run_sh.py`

**Interfaces:**
- Consumes: `scripts/backup_db.sh` (Task 1) e escreve `data/last_weekly_run_ok` (consumido por `scripts/heartbeat_check.sh`, Task 2).
- Produces: `run.sh` agora só grava `data/last_weekly_run_ok` e só chama `backup_db.sh` quando `docker compose run --rm app weekly-run` sai com código 0 (herdado de `set -euo pipefail`: se o weekly-run falhar, o script para ali e as duas linhas novas não rodam nessa semana).

- [ ] **Step 1: Atualizar o teste (vai falhar contra o `run.sh` atual)**

Substitua o conteúdo de `agents/carwatch/tests/test_run_sh.py` por exatamente:

```python
"""tests/test_run_sh.py"""
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_run_sh_is_executable_and_does_not_pass_redundant_carwatch_arg():
    run_sh = REPO_ROOT / "run.sh"
    content = run_sh.read_text()

    assert "docker compose run --rm app carwatch weekly-run" not in content
    assert "docker compose run --rm app weekly-run" in content
    mode = run_sh.stat().st_mode
    assert mode & stat.S_IXUSR


def test_run_sh_writes_heartbeat_marker_after_weekly_run():
    """TODO.md P0 'Heartbeat': scripts/heartbeat_check.sh só funciona se
    run.sh marcar toda execução bem-sucedida do weekly-run. A linha
    precisa vir DEPOIS de `docker compose run --rm app weekly-run` no
    arquivo -- com `set -euo pipefail`, se o weekly-run falhar, essa linha
    nunca roda nessa semana.
    """
    run_sh = REPO_ROOT / "run.sh"
    content = run_sh.read_text()
    lines = content.splitlines()

    weekly_run_idx = next(i for i, line in enumerate(lines) if "weekly-run" in line and "docker compose run" in line)
    heartbeat_idx = next(i for i, line in enumerate(lines) if "data/last_weekly_run_ok" in line)

    assert "date -u +%s > data/last_weekly_run_ok" in content
    assert heartbeat_idx > weekly_run_idx


def test_run_sh_calls_backup_db_after_weekly_run():
    """TODO.md P0 'Backup do banco': o pg_dump semanal roda depois do
    weekly-run, chamado via `bash scripts/backup_db.sh` (não `./scripts/...`,
    para não depender do bit executável sobreviver a um clone/checkout).
    """
    run_sh = REPO_ROOT / "run.sh"
    content = run_sh.read_text()
    lines = content.splitlines()

    weekly_run_idx = next(i for i, line in enumerate(lines) if "weekly-run" in line and "docker compose run" in line)
    backup_idx = next(i for i, line in enumerate(lines) if "backup_db.sh" in line)

    assert "bash scripts/backup_db.sh" in content
    assert backup_idx > weekly_run_idx
```

- [ ] **Step 2: Rodar o teste e confirmar que falham as duas novas**

Run: `cd agents/carwatch && python3 -m pytest tests/test_run_sh.py -v`
Expected: `test_run_sh_is_executable_and_does_not_pass_redundant_carwatch_arg` PASSA; `test_run_sh_writes_heartbeat_marker_after_weekly_run` e `test_run_sh_calls_backup_db_after_weekly_run` FALHAM (`StopIteration`, porque nenhuma linha contém `data/last_weekly_run_ok` nem `backup_db.sh` ainda).

- [ ] **Step 3: Editar `run.sh`**

Substitua todo o conteúdo de `agents/carwatch/run.sh` por exatamente:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose up -d db
for i in $(seq 1 15); do
    status="$(docker compose ps db --format '{{.Health}}')"
    if [ "$status" = "healthy" ]; then
        break
    fi
    sleep 2
done

docker compose run --rm app weekly-run
date -u +%s > data/last_weekly_run_ok
bash scripts/backup_db.sh
```

- [ ] **Step 4: Confirmar que o bit executável de `run.sh` não mudou**

Run: `ls -l agents/carwatch/run.sh`
Expected: começa com `-rwx` (se não, `chmod +x agents/carwatch/run.sh`).

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd agents/carwatch && python3 -m pytest tests/test_run_sh.py -v`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
cd /home/fabiano/homelab-ai && pre-commit run --all-files
cd agents/carwatch
git add run.sh tests/test_run_sh.py
git commit -m "$(cat <<'EOF'
feat(carwatch): liga backup e marcador de heartbeat ao run.sh semanal

Depois de um weekly-run bem-sucedido, run.sh agora grava
data/last_weekly_run_ok (lido por scripts/heartbeat_check.sh) e roda o
pg_dump (scripts/backup_db.sh). set -euo pipefail garante que nenhum dos
dois roda numa semana em que o weekly-run falhou.
EOF
)"
```

---

### Task 4: Timer systemd do heartbeat + documentação

**Files:**
- Create: `agents/carwatch/systemd/carwatch-heartbeat.service`
- Create: `agents/carwatch/systemd/carwatch-heartbeat.timer`
- Modify: `agents/carwatch/README.md`
- Modify: `CLAUDE.md` (raiz do repo)

**Interfaces:**
- Consumes: `agents/carwatch/scripts/heartbeat_check.sh` (Task 2), já executável e testado.
- Produces: um timer systemd `--user` instalável do mesmo jeito que `carwatch.timer` (README já documenta o padrão), mas com seu próprio ciclo diário, independente do timer semanal.

- [ ] **Step 1: Criar `systemd/carwatch-heartbeat.service`**

Crie `agents/carwatch/systemd/carwatch-heartbeat.service` com exatamente:

```ini
[Unit]
Description=CarWatch heartbeat (detecta timer que não disparou)

[Service]
Type=oneshot
ExecStart=%h/homelab-ai/agents/carwatch/scripts/heartbeat_check.sh
WorkingDirectory=%h/homelab-ai/agents/carwatch
TimeoutStartSec=2min
```

- [ ] **Step 2: Criar `systemd/carwatch-heartbeat.timer`**

Crie `agents/carwatch/systemd/carwatch-heartbeat.timer` com exatamente:

```ini
[Unit]
Description=Roda o heartbeat check do carwatch todo dia às 12:00 (com catch-up)

[Timer]
OnCalendar=*-*-* 12:00:00
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Validar a sintaxe dos dois arquivos**

Run: `systemd-analyze --user verify agents/carwatch/systemd/carwatch-heartbeat.service agents/carwatch/systemd/carwatch-heartbeat.timer 2>&1 || true`
Expected: nenhuma linha de erro sobre sintaxe inválida nos dois arquivos criados (avisos sobre o `%h` não resolvido nesse contexto de verificação isolada são esperados e não são o que este passo checa — o que importa é ausência de erro de parsing das seções `[Unit]`/`[Service]`/`[Timer]`/`[Install]`). Se o comando `systemd-analyze` não existir neste host, pule este passo (não é bloqueante).

- [ ] **Step 4: Atualizar a seção "Agendamento (systemd timer)" do `README.md`**

Em `agents/carwatch/README.md`, o bloco atual é:

```markdown
## Agendamento (systemd timer)

Executa todo **sábado às 09:00**:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/carwatch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now carwatch.timer

# Verificar:
systemctl --user list-timers carwatch.timer
```

`Persistent=true` garante catch-up se a máquina estava desligada no
horário agendado.
```

Substitua por exatamente (mantém tudo acima igual, acrescenta a subseção de heartbeat no final):

```markdown
## Agendamento (systemd timer)

Executa todo **sábado às 09:00**:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/carwatch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now carwatch.timer

# Verificar:
systemctl --user list-timers carwatch.timer
```

`Persistent=true` garante catch-up se a máquina estava desligada no
horário agendado.

### Heartbeat (detecta o timer que nunca disparou)

`carwatch.timer` só avisa quando encontra lançamento — silêncio é
indistinguível de "semana tranquila" e de "o timer parou de disparar"
(`linger` perdido, timer desabilitado, Docker fora do ar no horário).
`OnFailure=` no `.service` não resolve isso: só dispara quando o *run*
falha, não quando o timer nunca chega a rodar.

`carwatch-heartbeat.timer` é um **segundo timer independente**, que roda
todo dia às 12:00 e checa a idade de `data/last_weekly_run_ok` (escrito
por `run.sh` só quando o `weekly-run` termina com sucesso). Se fizer mais
de 8 dias desde o último sucesso — ou o arquivo nunca existiu — manda um
alerta pro Telegram (bot Hermes, mesmas credenciais dos outros agentes
deste repo) e sai com código 1 (fica visível também em `systemctl --user
status carwatch-heartbeat.service`).

```bash
mkdir -p ~/.config/systemd/user
cp systemd/carwatch-heartbeat.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now carwatch-heartbeat.timer

# Verificar:
systemctl --user list-timers carwatch-heartbeat.timer
```

**Limite conhecido:** se a máquina perder inteiramente o `loginctl
enable-linger` do usuário, *nenhum* timer `systemctl --user` (incluindo
este) volta a disparar sozinho — hoje não há, neste repo, um mecanismo
externo a este host que cubra esse caso específico. Ver `TODO.md`.
```

- [ ] **Step 5: Instalar e ativar o timer de verdade neste host**

Run:
```bash
mkdir -p ~/.config/systemd/user
cp /home/fabiano/homelab-ai/agents/carwatch/systemd/carwatch-heartbeat.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now carwatch-heartbeat.timer
systemctl --user list-timers carwatch-heartbeat.timer
```
Expected: a última linha do `list-timers` mostra `carwatch-heartbeat.timer` com um horário de próximo disparo (`NEXT`) preenchido, não vazio.

- [ ] **Step 6: Rodar o heartbeat check manualmente uma vez, pra ver o comportamento real**

Neste momento `data/last_weekly_run_ok` provavelmente não existe ainda (só é escrito na Task 3, pela primeira vez que `run.sh` rodar depois deste plano ser aplicado) — então este passo deve, de propósito, disparar um alerta real de teste no Telegram.

Run: `cd /home/fabiano/homelab-ai/agents/carwatch && ./scripts/heartbeat_check.sh; echo "exit=$?"`
Expected: imprime `[heartbeat_check] ALERTA: ...` e `exit=1`; chega uma mensagem `⚠️ CarWatch heartbeat: ...` no chat do Telegram configurado em `$HOME/.hermes/.env`. Isso é o comportamento correto e esperado neste ponto do plano — confirma que o alerta de verdade funciona antes de depender dele silenciosamente por 8 dias.

- [ ] **Step 7: Atualizar a tabela de rotinas em `CLAUDE.md` (raiz do repo)**

Em `CLAUDE.md`, a linha atual da tabela "Rotinas autônomas" é:

```
| `carwatch/` | Sáb 09:00 | Claude Haiku + Postgres | 🟢 timer ativo |
```

Substitua por estas duas linhas:

```
| `carwatch/` (weekly-run) | Sáb 09:00 | Claude Haiku + Postgres | 🟢 timer ativo |
| `carwatch/` (heartbeat) | diário 12:00 | bash + curl (Telegram) | 🟢 timer ativo |
```

- [ ] **Step 8: Atualizar a nota sobre Telegram em `CLAUDE.md`**

Em `CLAUDE.md`, dentro de "Convenções dos agentes", o bloco atual é:

```
- **Telegram:** hoje **todos** os que notificam usam o bot **Hermes** (alerta interno de
  execução de job), com credenciais lidas de `$HOME/.hermes/.env` — fora do repo.
  Helper compartilhado: `agents/lib/telegram_notify.py`.
  O `weekly-disk-guardian` é o único que não manda nada: `telegram: false` no
  `config.yaml`, notifica por `notify-send` no desktop.
```

Substitua por:

```
- **Telegram:** hoje **todos** os que notificam usam o bot **Hermes** (alerta interno de
  execução de job), com credenciais lidas de `$HOME/.hermes/.env` — fora do repo.
  Helper compartilhado: `agents/lib/telegram_notify.py` — exceto
  `carwatch/scripts/heartbeat_check.sh`, que roda fora do container `app`
  (não tem o venv Python do agente disponível) e chama a API do Telegram
  direto via `curl`, lendo as mesmas credenciais do Hermes.
  O `weekly-disk-guardian` é o único que não manda nada: `telegram: false` no
  `config.yaml`, notifica por `notify-send` no desktop.
```

- [ ] **Step 9: Commit**

```bash
cd /home/fabiano/homelab-ai && pre-commit run --all-files
git add agents/carwatch/systemd/carwatch-heartbeat.service \
        agents/carwatch/systemd/carwatch-heartbeat.timer \
        agents/carwatch/README.md \
        CLAUDE.md
git commit -m "$(cat <<'EOF'
feat(carwatch): adiciona timer systemd de heartbeat diário

Segundo timer --user independente de carwatch.timer (TODO.md P0
"Heartbeat"): OnFailure= no .service não detecta o timer que nunca
disparou, só o run que falhou. CLAUDE.md atualizado no mesmo commit
(nova linha na tabela de rotinas + nota sobre o heartbeat não usar o
helper Python de Telegram compartilhado).
EOF
)"
```

---

### Task 5: Atualizar `TODO.md` com o progresso real

**Files:**
- Modify: `agents/carwatch/TODO.md`

**Interfaces:**
- Consumes: nada de código — só reflete o estado real depois das Tasks 1–4.

- [ ] **Step 1: Editar o bloco P0 do `TODO.md`**

O bloco atual (seção "## P0 — antes de confiar no piloto automático") é:

```markdown
## P0 — antes de confiar no piloto automático

- [ ] **Backup do banco.** `carwatch-db-1` (volume `carwatch_db_data`) vive só
      neste host, sem backup. Perder a máquina = perder histórico de custo
      (`llm_usage`), curadoria (`sources`, `source_metrics`) e eventos.
      `raw_items`/`launch_events` o pipeline reconstrói com o tempo; o resto não.
      Sugestão: `pg_dump` semanal (etapa em `run.sh` depois do `weekly-run`, ou
      cron próprio) pra um caminho que já entra no backup do host. Guardar as
      últimas N cópias.

- [ ] **Heartbeat.** Nada avisa se o timer parar de disparar — `linger`
      perdido num upgrade, timer desabilitado, `docker` fora do ar no horário.
      O silêncio é indistinguível de "semana tranquila". Sugestão: checagem
      "última run bem-sucedida < 8 dias" (via `daily_stats.computed_at` ou o
      exit do serviço) que manda um alerta no Telegram quando estoura; ou
      transformar o digest de curadoria semanal em sinal de vida obrigatório.
```

Substitua por exatamente:

```markdown
## P0 — antes de confiar no piloto automático

- [ ] **Backup do banco.** Implementado: `run.sh` chama `scripts/backup_db.sh`
      (pg_dump -Fc, mantém 8 cópias) a cada `weekly-run` bem-sucedido — ver
      README.md "Backup do banco". **Ainda falta**: `CARWATCH_BACKUP_DIR`
      hoje aponta pro default local (`backups/carwatch/` na raiz do repo),
      que não é replicado pra fora deste host — perder a máquina ainda é
      perder o histórico. Falta confirmar/configurar um destino de verdade
      (ver plano `docs/superpowers/plans/2026-08-29-carwatch-backup-heartbeat.md`,
      Task 6) antes de marcar isto como concluído.

- [x] **Heartbeat.** `carwatch-heartbeat.timer` (segundo timer `--user`,
      diário às 12:00, independente de `carwatch.timer`) roda
      `scripts/heartbeat_check.sh`, que alerta no Telegram quando a última
      execução semanal bem-sucedida (`data/last_weekly_run_ok`, escrito por
      `run.sh`) tem mais de 8 dias, ou nunca existiu. Ver README.md
      "Heartbeat". Limite conhecido: não cobre perda total de
      `loginctl enable-linger` do usuário (nenhum timer `--user`, incluindo
      este, dispara sozinho nesse caso) — não há hoje mecanismo externo a
      este host para esse cenário específico; ficar de olho se isso vale a
      pena resolver depois de rodar um tempo.
```

- [ ] **Step 2: Commit**

```bash
cd /home/fabiano/homelab-ai && pre-commit run --all-files
git add agents/carwatch/TODO.md
git commit -m "$(cat <<'EOF'
docs(carwatch): atualiza TODO.md com o progresso das pendências P0

Heartbeat fechado de ponta a ponta. Backup do banco tem o mecanismo
pronto, mas o destino ainda não é replicado para fora deste host --
fica marcado como pendente até essa confirmação (Task 6 do plano).
EOF
)"
```

---

### Task 6: `[REQUER HUMANO]` — confirmar o destino replicado do backup

Esta tarefa **não pode ser executada mecanicamente** — é uma decisão de infraestrutura pessoal que só o dono do host tem os dados para tomar, e é o motivo pelo qual o item "Backup do banco" ficou com `- [ ]` (não `- [x]`) na Task 5 acima.

**Contexto verificado neste plano:** `backups/` na raiz do repo existe, está listado em `.gitignore` (`backups/*`, então nada dentro dele nunca vai pro Git de qualquer forma — isso não é o problema) e hoje contém só um tarball avulso de 3 de junho de 2026 (`homelab-ai-20260603-235053.tar.gz`). Não há, em nenhum lugar deste repositório, evidência de que esse diretório — ou qualquer outro caminho deste host — seja replicado para fora dele (nenhuma menção a `rsync`, `restic`, `rclone`, `borg`, backup em nuvem, ou NAS foi encontrada em `infra/`, `docs/`, ou nos scripts existentes). O default proposto e já implementado nas Tasks 1–5 (`backups/carwatch/` na raiz do repo) é **local-only** e serve só como salvaguarda contra apagar uma tabela por engano — não contra perder a máquina, que é o objetivo original do item no `TODO.md`.

- [ ] **[REQUER HUMANO] Decidir o destino real do backup.** Perguntas que só o dono do host pode responder:
  1. Existe algum caminho já montado/sincronizado para fora desta máquina (NAS, disco externo com sincronização automática, pasta de um serviço de nuvem, outro host na rede) que `CARWATCH_BACKUP_DIR` deveria apontar diretamente?
  2. Se não existe, vale configurar um agora (ex.: `rclone` para um bucket S3/B2/R2, ou um `restic`/`borg` apontando pra fora) — e nesse caso, isso é uma tarefa maior que este plano não cobre (setup de credenciais de um provedor externo, custo recorrente, etc.) e deveria virar seu próprio item no `TODO.md`?
  3. Ou é aceitável, por ora, que `backups/carwatch/` fique como está (proteção só contra erro operacional local, não contra perda do host) e o item continue `[ ]` no `TODO.md` até uma decisão futura?

- [ ] **Depois da decisão, se um destino diferente do default foi escolhido:** adicionar `CARWATCH_BACKUP_DIR=<caminho-escolhido>` em `agents/carwatch/.env` (não `.env.example` — esse arquivo é local e gitignored) e rodar manualmente:

```bash
cd /home/fabiano/homelab-ai/agents/carwatch
docker compose up -d db
bash scripts/backup_db.sh
ls -la "$CARWATCH_BACKUP_DIR"
```
Expected: um arquivo `carwatch-<timestamp>.dump` aparece no caminho escolhido, com tamanho maior que zero.

- [ ] **Só então, marcar o item como concluído.** Em `agents/carwatch/TODO.md`, trocar `- [ ] **Backup do banco.**` (Task 5, Step 1) por `- [x] **Backup do banco.**`, ajustando o texto "Ainda falta" para refletir o destino real escolhido, e commitar:

```bash
cd /home/fabiano/homelab-ai
export PATH="$HOME/.venvs/tools/bin:$PATH"
pre-commit run --all-files
git add agents/carwatch/TODO.md
git commit -m "$(cat <<'EOF'
docs(carwatch): confirma destino replicado do backup do banco

CARWATCH_BACKUP_DIR configurado (ver .env, gitignored) para um caminho
replicado para fora deste host. TODO.md P0 "Backup do banco" fechado.
EOF
)"
```

---

## Verificação final (rodar depois de todas as tasks 1–5, antes da Task 6)

```bash
cd agents/carwatch
python3 -m pytest tests/test_backup_db_sh.py tests/test_heartbeat_check_sh.py tests/test_run_sh.py -v
```
Expected: `11 passed` (4 + 4 + 3).

```bash
systemctl --user list-timers carwatch.timer carwatch-heartbeat.timer
```
Expected: as duas linhas aparecem, cada uma com um horário em `NEXT` preenchido.

```bash
grep -n "carwatch" /home/fabiano/homelab-ai/CLAUDE.md | grep -i "heartbeat\|weekly-run"
```
Expected: as duas linhas novas da tabela de rotinas aparecem.
