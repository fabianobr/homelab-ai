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

### 6. Correções da revisão final da Fase 1 (divergências do SPEC.md)

Estas quatro divergências **não** eram planejadas: foram encontradas na
revisão final da Fase 1, com reprodução empírica, e corrigidas por sobrepor
a instrução original de "manter o valor literal do spec".

- **`llm/classify.py`: `max_tokens=300` + `BATCH_SIZE=20` (§10) →
  `max_tokens=1200` + `BATCH_SIZE=8`.** A combinação do spec é
  aritmeticamente impossível: um objeto de classificação custa ~30–40 tokens
  de saída, então um lote cheio de 20 itens precisa de ~600–800 e sempre
  truncava no meio do JSON. `parse_classify_response` devolvia `None`, o
  lote inteiro era descartado, e as linhas ficavam em
  `status='new' AND prefilter_ok=TRUE` — ou seja, a execução da semana
  seguinte re-tentava (e re-cobrava) os mesmos itens mais os novos, num
  backlog sem limite. Além dos novos valores, um lote que falha o parse
  agora é **dividido ao meio e re-tentado**, o que limita o estrago de
  qualquer desalinhamento futuro de orçamento de tokens à metade que falhou.
- **`probe.py`: o fallback de sitemap (§7) saiu da cadeia de descoberta.**
  A cadeia agora é apenas *candidate paths → `<link rel="alternate">`*.
  `feedparser.parse()` extrai **zero** entradas de um documento `<urlset>`
  (verificado empiricamente), então o `>= 5 entries` de
  `validate_feed_content` jamais passaria para uma resposta de sitemap: era
  código morto que custava 2 requisições HTTP a mais por marca. Reativar
  exige um parser de sitemap XML de verdade e um validador próprio, não
  apenas religar a função antiga.
- **`config/keywords.yaml`: os termos `stock` e `shares` (§9) viraram
  frases financeiras** (`stock price`, `stock plunges`, `shares fall`, …).
  Com `prefilter.py` casando por fronteira de palavra, a palavra solta ainda
  vetava anúncios legítimos — "now in stock nationwide" contém `stock`
  inteiro. As frases capturam a intenção real do spec (notícia de mercado
  financeiro) sem o falso positivo.
- **`prefilter.py` casa por fronteira de palavra**, não por substring.
  Substring fazia o alias `GM` casar dentro de "segment" e `Ram` dentro de
  "program"/"framework". Termos com caracteres não-ASCII (zh/ja) continuam
  em substring: `\b` do Python pressupõe palavras delimitadas por espaço,
  que CJK não tem.
- **`breaker.py`: o gatilho de pausa é "qualquer sinal isolado de
  403/429/blocked", não a taxa de "> 20% em janela de 1h" que o §6 do
  spec descreve.** Calcular a taxa literal exigiria uma tabela nova
  logando toda tentativa de fetch (não só os sinais de pausa que
  `source_incidents` já registra hoje) — uma migração de schema que esta
  branch está deliberadamente evitando agora: a Fase 2 (PR #8), aberta em
  cima desta branch, já reserva o número de migração `004`, e adicionar
  uma migração aqui arriscaria colisão de numeração quando as duas forem
  combinadas. O comportamento atual é mais conservador que o spec (pausa
  mais cedo, não mais tarde), não uma lacuna de conformidade que deixe o
  domínio ser martelado — fica registrado aqui como divergência honesta,
  a implementar quando a tabela de log de fetches existir.

Correções da mesma revisão que **não** divergem do spec (são o spec sendo
finalmente implementado): o circuit breaker agora é **lido** antes de cada
fetch (não só gravado), a heurística de corpo curto <500 chars só vale para
`kind="page"` (um feed pequeno e válido não é bloqueio silencioso), e os
eventos `fetch.result`/`breaker.trip`/`llm.call` do §18 passaram a ser
emitidos de fato.

## O que **não** muda em relação ao `SPEC.md`

- Schema do banco (§5) inteiro, incluindo `source_metrics`,
  `launch_events`, `event_sources`.
- Contrato e comportamento do `fetcher` (§6): robots.txt, UA fixo,
  conditional GET, rate limit por domínio (semáforo 1, 3s + jitter),
  retry com backoff exponencial + jitter, detecção de bloqueio silencioso,
  circuit breaker (§6, "não implemente lógica de contorno" continua valendo
  integralmente). O retry é um laço próprio dentro de `fetcher.fetch()`, não
  `tenacity`: o backoff precisa enxergar o `Retry-After` da resposta e
  interagir com o breaker, o que ficaria mais obscuro embrulhado no
  decorator. `tenacity` continua nas dependências para as fases seguintes.
- `probe.py` (§7), `prefilter.py` (§9), `llm/classify.py` (§10),
  `llm/extract.py` (§11), `dedupe.py` (§12) completos, incluindo os
  prompts, os limiares (0.55 trigram / 0.86 cosseno), e a regra de
  progressão de estágio — com as exceções registradas na seção 6 abaixo.
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
