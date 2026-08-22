# CarWatch

Pipeline semanal de detecção de lançamentos automotivos globais a partir de
fontes públicas (feeds de imprensa, mídia especializada, Google News),
classificados via Claude Haiku e publicados no Telegram.

Ver `SPEC.md` (especificação original) e `DESIGN.md` (adaptação para
execução semanal — leia os dois; `DESIGN.md` prevalece em conflitos).

## Dependências

- **Docker + Docker Compose** (roda `db` e `app` como containers)
- **Chave de API Anthropic** (`ANTHROPIC_API_KEY`) — usa `claude-haiku-4-5-20251001`
- **Bot do Telegram dedicado** (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`) —
  não é o bot Hermes usado pelos outros agentes deste repositório
  (DESIGN.md §4)

## Como rodar manualmente

```bash
cd ~/homelab-ai/agents/carwatch
cp .env.example .env   # preencher as chaves
./run.sh
```

## Testes

Precisam de Postgres real (não são mockados — apenas HTTP é mockado via
`respx`, seguindo SPEC.md §20):

```bash
cd ~/homelab-ai/agents/carwatch
docker compose up -d db
docker compose exec db psql -U carwatch -d carwatch -c "CREATE DATABASE carwatch_test;"  # uma vez
python3 -m pytest -q
```

Cobertura mínima exigida (SPEC.md §20): 90% em `fetcher.py`, `dedupe.py`
(Fase 2), `prefilter.py`.

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

## Riscos operacionais conhecidos

- `llm/classify.py` usa `max_tokens=300` por lote de 20 itens (valor exato
  do SPEC.md §10) — pode truncar em lotes cheios; ver nota em
  `llm/classify.py`.
- `config/brands.yaml` traz domínios de press room de melhor esforço;
  `carwatch probe` é quem valida de verdade em runtime.
