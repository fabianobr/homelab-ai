# CarWatch — TODO / roadmap operacional

Pendências pós-deploy real (timer systemd instalado em 2026-08-28, 1ª execução
autônoma 2026-08-29 09:00). Contexto e histórico ficam em `DESIGN.md` e no
`SPEC.md`; aqui é só a lista de trabalho.

## P0 — antes de confiar no piloto automático

- [x] **Backup do banco.** Resolvido em 2026-08-29. `carwatch-db-1` (volume
      `carwatch_db_data`) vivia só neste host: perder a máquina apagaria o histórico
      de custo (`llm_usage`) e a curadoria (`sources`, `source_metrics`), que o
      pipeline não reconstrói.
      Agora `backup.sh` roda no fim do `run.sh`, grava um `pg_dump -Fc` em
      `$HOME/.local/state/carwatch/backups` e envia para `gdrive:carwatch-backups/`
      via rclone, mantendo 8 cópias de cada lado. Falha de backup avisa mas não
      derruba o run. Restauração conferida com `pg_restore --list`: 10 tabelas,
      incluindo as três insubstituíveis.

- [x] **Heartbeat → dead man's switch externo.** Resolvido em 2026-08-29 com um
      Worker Cloudflare (`infra/cloudflare/deadman-switch/`), não com heartbeat
      interno — um segundo timer de usuário morre junto quando o `linger` cai.
      `run.sh` chama `deadman-ping.sh` no fim de um run bem-sucedido; o cron do
      Worker alerta no Telegram se o ping não chega em 8 dias. Cobre timer
      parado, `linger` perdido e host desligado. Comprovado forçando a ausência
      de ping. Desenho: `docs/superpowers/specs/2026-08-29-deadman-switch-design.md`.

## P1 — produção "de verdade"

- [ ] **Servir o `feed.atom`.** Hoje é gerado em `data/feed.atom` e fica
      parado. Criar rota no túnel Cloudflare + serviço estático (nginx) e então
      setar `ATOM_FEED_URL` real no `.env` (hoje é placeholder — entra só no
      self-link do XML, não quebra o run).

- [ ] **Bot dedicado do Telegram.** Produção usa o bot Hermes (compartilhado).
      Trocar `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` no `.env` quando o bot
      dedicado existir.

- [ ] **Substituto pro Tier 4.** `news.google.com/rss/search` é bloqueado pra
      crawler genérico no `robots.txt` (confirmado contra o robots real, não é
      bug do CarWatch). Avaliar Bing News, GNews API, ou feeds próprios das
      marcas.

## P2 — depois de 2–4 semanas reais

- [ ] **Métricas de validação** (`SPEC.md` §19/§22), só mensuráveis com
      histórico real: taxa de detecção ≥ 90%, duplicata < 5%, custo < US$ 15/mês.

- [ ] **Batch API** (baixa prioridade). O estudo de custo-benefício recomendou
      a Batch API da Anthropic; o código usa a Messages API síncrona
      (`client.messages.create`). Com ~US$ 0,03/run o ganho é irrelevante hoje —
      revisitar só se o volume crescer muito.

## Verificação da 1ª execução autônoma (2026-08-29 09:00)

```bash
journalctl --user -u carwatch.service -n 100 --no-pager        # exit 0?
ls -la agents/carwatch/data/feed.atom                          # dono fabiano?
docker exec carwatch-db-1 psql -U carwatch -d carwatch -c \
  "SELECT * FROM daily_stats ORDER BY day DESC LIMIT 2;"
systemctl --user list-timers carwatch.timer                    # próximo disparo
```

Era o primeiro teste do pipeline completo rodando como uid 1000 — o smoke test
de 28/08 rodou antes do fix `user: "1000:1000"` no `docker-compose.yml`.
