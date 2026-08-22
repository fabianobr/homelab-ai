# CarWatch — adaptação para execução semanal

> Este documento é um **delta** sobre `SPEC.md` (o spec original, copiado
> verbatim nesta pasta). Onde este documento não fala de algo, `SPEC.md`
> vale como está. Onde os dois divergem, este documento manda — ele existe
> justamente para registrar as divergências deliberadas e por quê.

## Por que este delta existe

`SPEC.md` foi desenhado como **daemon contínuo**: `docker compose up`
mantém um processo vivo, `APScheduler` dispara `ingest` a cada 30–60min,
`curate` semanalmente e `digest` diariamente. O princípio central do spec
(§1) é que notícia é gatilho e precisa ser pega em minutos/horas — é isso
que justifica não usar APIs de catálogo.

Este projeto roda como **agente semanal** (systemd timer, `Type=oneshot`),
seguindo o padrão já estabelecido em `agents/weekly-cost-benefit/` e
`agents/weekly-sdlc-research/` deste repositório. Isso é uma decisão
consciente, não um esquecimento: **abandona a proposta de valor de
detecção quase-tempo-real** do spec original. CarWatch semanal é um
**digest semanal de lançamentos**, não um alerta de scoop. Se essa troca
deixar de fazer sentido, a mudança para daemon contínuo é o que o spec
original já descreve — não precisa reescrever nada além do scheduling.

## O que muda

### 1. Scheduler → CLI composto único

`APScheduler` e o modo daemon (`carwatch run`) **não são implementados**.
No lugar, um único comando novo:

```
carwatch weekly-run
```

executa, em sequência, síncrona, num só processo:

```
ingest → prefilter → classify → extract → dedupe → curate → discover → publish
```

e sai com o código de saída real (0 sucesso, ≠0 falha) — systemd não deve
mascarar erro, igual aos outros agentes semanais deste repo. Os subcomandos
individuais do spec (`ingest --once`, `classify --limit`, etc.) continuam
existindo para uso manual/debug, mas `weekly-run` é o único invocado pelo
timer.

Tudo o resto do módulo `ingest.py` — corte de backlog em 45 dias,
`ON CONFLICT DO NOTHING` por `url_hash`, atualização de `etag`/`last_modified`
— continua igual. Numa cadência semanal, o corte de 45 dias ainda protege
a primeira execução; execuções seguintes naturalmente só trazem itens da
última semana.

### 2. O que a cadência semanal invalida (fica documentado, não implementado)

- `INGEST_INTERVAL_MIN` (45min, jitter) — não se aplica; removido do `.env.example`.
- `median_lead_minutes` em `source_metrics` (§13) — continua calculável, mas
  perde sentido como métrica de "chegamos primeiro": numa execução semanal,
  ordem de chegada dentro da mesma janela de 7 dias é praticamente ruído.
  Mantido no schema (não custa nada), mas não vira critério de decisão.
- Rate limit de 20 msgs/hora do Telegram (§15) e "excedente no digest das
  08:00" — não se aplica a uma publicação semanal em lote. `publish` envia
  todos os eventos aprovados da semana numa única passada, respeitando
  apenas o rate limit por causa de burst dentro do próprio lote (evitar
  banimento do bot do Telegram, não do throttle do spec original).
- §22 "Definição de pronto": a meta de ≥90% de detecção continua válida,
  mas **medida por semana**, não por evento individual — "detectamos o
  lançamento na janela semanal em que ele aconteceu", não "em minutos".

### 3. Stack mantida do spec original — não trocada pelo padrão do repo

Os outros agentes semanais deste repo usam Ollama local + ledger em
markdown (sem banco). CarWatch **não segue esse padrão** pelos seguintes
motivos, já implícitos no próprio spec:

- **Postgres + pgvector continuam obrigatórios.** O motor de dedupe (§12)
  depende de `pg_trgm` (similaridade fuzzy de nomes) e `hnsw`/cosseno em
  embeddings — infável em markdown com centenas de `raw_items` e
  `launch_events` por mês.
- **Claude Haiku (`claude-haiku-4-5-20251001`) via API Anthropic continua
  o modelo de classify/extract**, não Ollama local. O spec já justifica
  isso com custo estimado (~US$8–15/mês, teto rígido de US$30/mês no §18)
  e com necessidade de multilíngue de qualidade (zh/ja/ko = 40% do
  volume) — algo que os modelos locais atualmente instalados
  (`qwen3:14b`, `qwen2.5-coder:32b`) não foram avaliados para. Isso é a
  **única chamada a uma API paga de LLM entre os agentes deste repo** —
  vale deixar isso explícito no README do agente para não ser confundido
  com um desvio acidental do padrão Ollama-first.
- `docker-compose.yml` deste agente é **isolado** em `agents/carwatch/`,
  não integrado a `infra/docker/docker-compose.yml`. Só o serviço `db`
  fica de pé continuamente (`docker compose up -d db`, com healthcheck);
  o serviço `app` **não roda como daemon** — é invocado sob demanda via
  `docker compose run --rm app carwatch weekly-run` a partir do systemd
  timer, não `docker compose up -d app`.

### 4. Telegram

Bot e canal dedicados ao CarWatch (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
próprios em `agents/carwatch/.env`), **não** o bot Hermes usado pelos
outros agentes deste repo para notificação operacional. Motivo: o stream
de lançamentos é um produto com formato de conteúdo público (§15, HTML
formatado com emoji, pensado para ser lido por terceiros), diferente do
propósito de "alerta interno de execução de job" que o Hermes cobre hoje.
Alertas de falha/custo do próprio agente (crash, teto de US$30/mês
estourado) vão para o **mesmo bot/canal do CarWatch**, marcados com prefixo
de erro — não para o Hermes — para manter toda a operação do agente
observável num único lugar.

### 4b. Curadoria (Fase 3) — sem botão de confirmação no Telegram

O §13 do spec pede um digest semanal de curadoria "com botão de confirmação"
para aposentar fontes. Este agente não tem processo de longa duração para
receber o callback de um botão inline do Telegram (é um job de systemd
timer, sem webhook ouvindo). Por isso: promoção e rebaixamento continuam
automáticos (são reversíveis e de baixo risco, exatamente como o spec já
descreve), mas aposentadoria nunca é automática — fica sinalizada numa
tabela `pending_retirements` e listada em texto no digest; confirmação é
manual via `carwatch curate --confirm-retirement <id>` numa execução
seguinte. "Nada é aposentado sem o OK" continua valendo — o OK só chega por
CLI em vez de por botão. Detalhado no plano de implementação da Fase 3.

### 5. Systemd

Segue o padrão exato de `weekly-cost-benefit`/`weekly-sdlc-research`
(`Type=oneshot`, `Persistent=true`, `RandomizedDelaySec`), mas em horário
próprio — CarWatch não disputa GPU/Ollama com os outros dois (não usa
Ollama), então não precisa ficar na mesma janela de sexta-feira à noite.
Proposta: **sábado 09:00**, para não competir por I/O de rede com nada
mais agendado e dar folga antes do `curate`/`discovery` rodarem sobre uma
semana completa de dados.

`ExecStartPre` garante `docker compose up -d db` e aguarda o healthcheck
antes do `ExecStart` chamar `docker compose run --rm app carwatch weekly-run`.

## O que **não** muda em relação ao `SPEC.md`

- Schema do banco (§5) inteiro, incluindo `source_metrics`,
  `launch_events`, `event_sources`.
- Contrato e comportamento do `fetcher` (§6): robots.txt, UA fixo,
  conditional GET, rate limit por domínio (semáforo 1, 3s + jitter),
  retry via `tenacity`, detecção de bloqueio silencioso, circuit breaker
  (§6, "não implemente lógica de contorno" continua valendo integralmente).
- `probe.py` (§7), `prefilter.py` (§9), `llm/classify.py` (§10),
  `llm/extract.py` (§11), `dedupe.py` (§12) completos, incluindo os
  prompts, os limiares (0.55 trigram / 0.86 cosseno), e a regra de
  progressão de estágio.
- `curate.py` (§13) e `discovery.py` (§14) completos — aliás, a cadência
  semanal do spec original para `curate` já era semanal; aqui ela só
  passa a rodar *dentro* do mesmo processo de `weekly-run` em vez de via
  scheduler separado.
- Armadilhas conhecidas (§21) e testes obrigatórios (§20) — cobertura de
  90% em `fetcher.py`/`dedupe.py`/`prefilter.py`, `respx` mockando toda
  rede, fixtures reais.
- As 3 fases e critérios de aceite (§19) — usadas como está para o plano
  de implementação, só trocando "scheduler daemon" por "`weekly-run`
  síncrono" onde o texto da Fase 1 menciona scheduler.

## Consequência a aceitar conscientemente

Rodando semanalmente, CarWatch deixa de competir com Motor1/Carscoops em
velocidade de furo — ele vira uma curadoria semanal do que essas fontes
já publicaram. Isso é aceitável para o caso de uso de acompanhamento
pessoal, mas é bom que fique escrito aqui: **se o objetivo mudar para
"ser mais rápido que a imprensa", a arquitetura correta é a do
`SPEC.md` original (daemon + APScheduler), não esta.**
