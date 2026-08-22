# SPEC — CarWatch: pipeline global de lançamentos automotivos

> Documento de implementação. Destinado a um agente de coding autônomo.
> Leia inteiro antes de escrever código. Não invente escopo além do descrito.
> Entregue por fase. Não avance de fase sem os critérios de aceite verdes.

---

## 1. Objetivo

Detectar lançamentos de veículos no mundo todo a partir de fontes públicas, extrair dados estruturados (marca, modelo, specs, preço, mercado, data) e publicar como stream consumível (Telegram + feed Atom + Postgres).

### Princípio central

Notícia é o **gatilho** de lançamento. APIs de catálogo de veículos são **enriquecimento posterior** — elas atrasam semanas ou meses e não servem para descoberta. Não inverta isso.

### Não-escopo (explícito)

- ❌ Bypass de CAPTCHA, Cloudflare Turnstile, DataDome, PerimeterX
- ❌ Rotação de proxy residencial para contornar bloqueio deliberado
- ❌ Contorno de paywall
- ❌ Scraping de conteúdo integral de mídia paga (só título + snippet + URL)
- ❌ Frontend/dashboard web (fase futura, fora deste spec)
- ❌ Preço de mercado, inventário, revenda

Domínio que bloqueia é marcado `status=blocked` e substituído por fonte alternativa. Sempre existe alternativa: press release aparece em 5+ lugares em minutos.

---

## 2. Stack (decidida — não substituir)

| Camada | Escolha | Versão |
|---|---|---|
| Linguagem | Python | 3.12 |
| Gerenciador | `uv` | latest |
| DB | PostgreSQL + `pgvector` | 16 |
| Driver | `psycopg` (v3, async) | ^3.2 |
| HTTP | `httpx` (async, HTTP/2) | ^0.27 |
| Retry | `tenacity` | ^9.0 |
| Feeds | `feedparser` | ^6.0 |
| HTML parse | `selectolax` | ^0.3 |
| Scheduler | `APScheduler` (AsyncIOScheduler) | ^3.10 |
| Embeddings | `sentence-transformers` | ^3.0 |
| LLM | Anthropic API (`anthropic`) | ^0.40 |
| Config | `pydantic-settings` + YAML | ^2.0 |
| Logs | `structlog` (JSON) | ^24.0 |
| Testes | `pytest` + `pytest-asyncio` + `respx` | — |
| Deploy | `docker compose` | — |

**Modelo de embedding:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dims). Multilíngue é obrigatório — 40% do volume é zh/ja/ko.

**Modelo LLM:** `claude-haiku-4-5-20251001` para classificação e extração. Não use modelo maior sem evidência de que Haiku falha; o custo estimado é ~US$8/mês.

---

## 3. Arquitetura

```
┌─────────────┐
│ source_probe│  (CLI, roda sob demanda)
│  descoberta │──────► sources (tabela)
└─────────────┘
                          │
┌─────────────────────────▼──────────────────────────┐
│                    scheduler                        │
│  ingest(30-60min) · curate(semanal) · digest(diário)│
└─────────────────────────┬──────────────────────────┘
                          │
   ┌──────────────────────▼───────────────────────┐
   │  fetcher  (ÚNICO ponto de saída HTTP)        │
   │  robots · ETag/304 · rate limit · breaker    │
   └──────────────────────┬───────────────────────┘
                          │
        ingest ──► raw_items (dedupe por hash)
                          │
        prefilter (regex/keyword) ──► descarta ~85%
                          │
        classify (LLM, título+snippet) ──► is_launch? stage?
                          │
        fetch_full ──► extract (LLM, artigo) ──► JSON
                          │
        dedupe (chave + embedding, janela 14d)
                          │
        ┌─────────────────┴─────────────────┐
    launch_events                      publishers
                                    (telegram, atom)
```

**Regra inviolável:** nenhum módulo faz `httpx.get()` direto. Tudo passa por `carwatch.fetcher.fetch()`. Um teste deve garantir isso (grep por chamadas HTTP fora do módulo).

---

## 4. Estrutura do repositório

```
carwatch/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── migrations/
│   ├── 001_init.sql
│   ├── 002_sources.sql
│   └── 003_events.sql
├── config/
│   ├── brands.yaml          # ~90 marcas/grupos
│   ├── keywords.yaml        # prefilter: positivos e negativos
│   └── settings.yaml
├── src/carwatch/
│   ├── __init__.py
│   ├── settings.py
│   ├── db.py                # pool psycopg, helpers
│   ├── fetcher.py           # ÚNICO ponto de saída HTTP
│   ├── ratelimit.py
│   ├── breaker.py
│   ├── robots.py
│   ├── models.py            # pydantic
│   ├── probe.py             # descoberta de feeds
│   ├── ingest.py
│   ├── prefilter.py
│   ├── llm/
│   │   ├── client.py
│   │   ├── classify.py
│   │   └── extract.py
│   ├── dedupe.py
│   ├── curate.py            # métricas + promote/demote/retire
│   ├── discovery.py         # descoberta contínua de fontes
│   ├── publishers/
│   │   ├── telegram.py
│   │   └── atom.py
│   ├── scheduler.py
│   └── cli.py               # entrypoint typer
└── tests/
```

---

## 5. Schema do banco

`migrations/001_init.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 5.1 `sources`

```sql
CREATE TYPE source_status AS ENUM
  ('active','probation','retired','broken','blocked','candidate');

CREATE TABLE sources (
  id              BIGSERIAL PRIMARY KEY,
  domain          TEXT NOT NULL,
  feed_url        TEXT UNIQUE NOT NULL,
  kind            TEXT NOT NULL,        -- rss|atom|sitemap|jsonld|newswire|gnews
  tier            SMALLINT NOT NULL,    -- 1..4
  brand_scope     TEXT[] DEFAULT '{}',  -- vazio = generalista
  region          TEXT,                 -- ISO-3166-1 alpha-2 ou 'GLOBAL'
  lang            TEXT DEFAULT 'en',
  status          source_status NOT NULL DEFAULT 'candidate',
  etag            TEXT,
  last_modified   TEXT,
  added_at        TIMESTAMPTZ DEFAULT now(),
  last_ok_at      TIMESTAMPTZ,
  last_item_at    TIMESTAMPTZ,
  consecutive_failures  INT DEFAULT 0,
  blocked_until   TIMESTAMPTZ,
  notes           TEXT
);
CREATE INDEX ON sources (status, tier);
CREATE INDEX ON sources (domain);
```

### 5.2 `source_metrics` (rolling 30d, recalculada semanalmente)

```sql
CREATE TABLE source_metrics (
  source_id            BIGINT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  items_30d            INT DEFAULT 0,
  passed_prefilter_30d INT DEFAULT 0,
  events_30d           INT DEFAULT 0,
  unique_events_30d    INT DEFAULT 0,   -- eventos onde foi a ÚNICA fonte
  first_seen_30d       INT DEFAULT 0,   -- eventos onde chegou primeiro
  median_lead_minutes  INT,             -- negativo = chega depois da mediana
  yield_pct            NUMERIC(5,2),    -- events/items
  precision_30d        NUMERIC(5,2)     -- amostragem manual, pode ser NULL
);
```

### 5.3 `raw_items`

```sql
CREATE TABLE raw_items (
  id            BIGSERIAL PRIMARY KEY,
  source_id     BIGINT REFERENCES sources(id),
  url           TEXT NOT NULL,
  url_hash      TEXT UNIQUE NOT NULL,   -- sha256 da url normalizada
  title         TEXT NOT NULL,
  summary       TEXT,
  lang          TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ DEFAULT now(),
  body          TEXT,                   -- só preenchido se passar classify
  prefilter_ok  BOOLEAN,
  classified    JSONB,                  -- output do classify
  status        TEXT DEFAULT 'new'      -- new|filtered|rejected|extracted|error
);
CREATE INDEX ON raw_items (status, fetched_at DESC);
CREATE INDEX ON raw_items (source_id, published_at DESC);
```

**Normalização de URL antes do hash:** lowercase host, remove fragmento, remove params de tracking (`utm_*`, `fbclid`, `gclid`, `ref`, `source`), remove trailing slash.

### 5.4 `launch_events`

```sql
CREATE TYPE launch_stage AS ENUM
  ('spy','teaser','world_premiere','specs_release',
   'pricing','on_sale','market_launch','concept');

CREATE TABLE launch_events (
  id              BIGSERIAL PRIMARY KEY,
  dedupe_key      TEXT NOT NULL,        -- brand|model_slug|market|stage
  brand           TEXT NOT NULL,
  brand_group     TEXT,
  model           TEXT NOT NULL,
  model_slug      TEXT NOT NULL,
  generation      TEXT,
  body_type       TEXT,
  stage           launch_stage NOT NULL,
  is_new_generation BOOLEAN,            -- false = facelift/restyling
  markets         TEXT[] DEFAULT '{}',
  global_debut    BOOLEAN DEFAULT false,
  event_date      DATE,
  sales_start     TEXT,                 -- texto livre: "2026-Q4", "2027-03"
  powertrain      JSONB,
  price           JSONB,
  highlights      TEXT[],
  embedding       vector(384),
  confidence      NUMERIC(3,2),
  first_seen_at   TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),
  published       BOOLEAN DEFAULT false,
  review_status   TEXT DEFAULT 'pending' -- pending|confirmed|rejected
);
CREATE INDEX ON launch_events (dedupe_key, first_seen_at DESC);
CREATE INDEX ON launch_events USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON launch_events USING gin (model gin_trgm_ops);

CREATE TABLE event_sources (
  event_id   BIGINT REFERENCES launch_events(id) ON DELETE CASCADE,
  item_id    BIGINT REFERENCES raw_items(id),
  source_id  BIGINT REFERENCES sources(id),
  is_primary BOOLEAN DEFAULT false,
  seen_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (event_id, item_id)
);
```

**Schema JSONB `powertrain`:**
```json
{"type":"bev|phev|hev|ice|fcev","power_hp":212,"torque_nm":300,
 "battery_kwh":10.08,"range_km":120,"range_cycle":"WLTP|CLTC|EPA",
 "drivetrain":"fwd|rwd|awd","zero_to_100_s":7.5}
```

**Schema JSONB `price`:**
```json
{"amount":109800,"currency":"CNY","status":"official|estimated|starting_from"}
```

Todo campo é opcional exceto `type`. Use `null`, nunca invente.

---

## 6. Módulo `fetcher` (crítico)

### Contrato

```python
async def fetch(
    url: str,
    *,
    kind: Literal["feed", "page"] = "page",
    source_id: int | None = None,
    timeout: float = 20.0,
) -> FetchResult: ...

@dataclass
class FetchResult:
    status: int                  # 0 = não executado (breaker aberto / robots)
    body: str | None
    etag: str | None
    last_modified: str | None
    not_modified: bool           # True se 304
    blocked: bool                # 403/429 persistente ou WAF silencioso
    reason: str | None
```

### Comportamento obrigatório

1. **robots.txt** — cache de 24h por domínio. Se `Disallow` para o path, retorna `status=0, reason="robots"`. Respeitar `Crawl-delay`.
2. **User-Agent honesto e fixo:**
   ```
   CarWatchBot/1.0 (+{BOT_INFO_URL}; {CONTACT_EMAIL})
   ```
   Configurável via env. **Nunca** rotacionar UA nem imitar navegador.
3. **Conditional GET** — envia `If-None-Match` / `If-Modified-Since` a partir de `sources.etag` / `sources.last_modified`. Ao receber 304, retorna imediatamente sem parse. Persiste os novos valores no 200.
4. **Rate limit por domínio** — semáforo de concorrência 1 e intervalo mínimo de 3s (configurável, default 3.0, com jitter ±30%). Concorrência global entre domínios: 10.
5. **Sessão persistente** — um `httpx.AsyncClient` global, `http2=True`, `follow_redirects=True`.
6. **Retry** (`tenacity`): 3 tentativas, backoff exponencial base 2s, jitter. Retenta apenas em `5xx`, timeout, `ConnectError`. Em `429`/`503` com header `Retry-After`, honra o valor exato.
7. **Nunca retenta 403/404/410.**
8. **Detecção de bloqueio silencioso** — WAF frequentemente devolve `200` com página vazia. Marca `blocked=True` se `status==200` E:
   - `len(body) < 500`, OU
   - corpo contém qualquer um de: `"Just a moment"`, `"Attention Required"`, `"cf-browser-verification"`, `"DataDome"`, `"px-captcha"`, `"Access Denied"`, `"unusual traffic"`

### Circuit breaker (`breaker.py`)

Estado por domínio, persistido em `sources`:

| Condição | Ação |
|---|---|
| taxa de 403/429/blocked > 20% em janela de 1h | `blocked_until = now + 24h`, alerta |
| 2 pausas em 7 dias | `status='probation'`, aciona fallback |
| bloqueio após retomada | `status='blocked'`, **para de tentar permanentemente** |
| 3 falhas HTTP consecutivas | `status='broken'`, tenta redescoberta de feed 1x |
| 21 dias sem item novo | alerta de fonte morta |

**Não implemente lógica de contorno.** `blocked` é terminal. O fallback é cobrir a marca via Tier 3/4, não insistir no domínio.

---

## 7. `probe.py` — descoberta inicial de fontes

CLI: `carwatch probe --brands config/brands.yaml --out sources.csv`

Para cada marca em `brands.yaml`:

1. Resolve o domínio do press room. Ordem: campo `press_domain` do YAML (preferido, preencher manualmente onde souber) → senão, pula e registra como gap.
2. Tenta os caminhos, nesta ordem, parando no primeiro sucesso:
   ```
   /rss  /feed  /feed.rss  /rss.xml  /feeds/news.xml
   /en/rss  /news/rss  /press-releases/rss
   ```
3. Se nenhum: busca `<link rel="alternate" type="application/rss+xml">` no HTML da home do press room.
4. Se nenhum: tenta `/sitemap.xml` e `/news-sitemap.xml`.
5. **Validação de feed** — só aceita se: parseia sem erro fatal, tem ≥5 entries, e a entry mais recente tem menos de 90 dias.
6. Grava em `sources` com `tier=1`, `status='probation'`, `brand_scope=[marca]`.
7. Marca sem feed válido → registra em `gaps.csv` com motivo.

**Expectativa realista:** 55–65% de hit rate. Não escreva scraper customizado para os que falharem — eles são cobertos pelos Tiers 3/4. Isso é decisão de projeto, não limitação.

### Fontes fixas (seed manual, `config/settings.yaml`)

- **Tier 2 (newswire):** BusinessWire automotive, GlobeNewswire tag automakers, PR Newswire auto
- **Tier 3 (mídia):** Motor1, Carscoops, CarNewsChina, Autocar UK, Auto Express, Paultan (MY), Indian Autos Blog, Quatro Rodas, Motor1 Brasil, Autohome (zh), Response.jp (ja)
- **Tier 4 (rede de segurança):** Google News RSS por marca —
  `https://news.google.com/rss/search?q=%22{brand}%22+(unveil+OR+reveal+OR+debut+OR+launch)&hl=en&gl=US&ceid=US:en`
  Gerar uma entrada por marca do top-40. Para marcas CN/IN, gerar também com `hl=zh-CN` / `hl=en-IN`.

⚠️ **Valide todas as URLs de feed em runtime.** Não assuma que as listadas acima existem exatamente nesses caminhos — o probe deve confirmar antes de gravar `status='active'`.

---

## 8. `ingest.py`

Por ciclo (default 45min, jitter ±10min):

1. Seleciona `sources` com `status IN ('active','probation')` e `blocked_until IS NULL OR blocked_until < now()`.
2. `fetch(feed_url, kind="feed", source_id=...)`.
3. Se `not_modified` → registra `last_ok_at`, encerra.
4. Parseia com `feedparser`. Para cada entry: normaliza URL, calcula `url_hash`, `INSERT ... ON CONFLICT (url_hash) DO NOTHING`.
5. Atualiza `sources.last_item_at`, `etag`, `last_modified`, zera `consecutive_failures`.

Ignora entries com `published_at` > 45 dias no passado (backlog inicial do feed).

---

## 9. `prefilter.py` — filtro barato

Objetivo: descartar ~85% antes de gastar token. Puramente lexical, sem LLM.

Passa se: **(A) contém marca conhecida** E **(B) contém ≥1 termo positivo** E **(C) não contém termo negativo forte**.

`config/keywords.yaml`:

```yaml
positive:
  en: [unveil, unveils, reveal, reveals, debut, debuts, world premiere,
       all-new, new generation, launches, launched, introduces, introducing,
       goes on sale, pricing announced, revealed, teaser, teased, facelift,
       refreshed, order books, deliveries begin]
  pt: [lançamento, lança, apresenta, revela, estreia, nova geração,
       chega ao mercado, pré-venda, preços anunciados]
  zh: [首发, 上市, 亮相, 全新, 官图, 预售, 发布]
  ja: [新型, 発表, 発売, 世界初公開]
negative_strong:
  - recall, quarterly results, earnings, dividend, layoffs, plant closure,
    lawsuit, appoints, appointment, obituary, sponsorship, esports,
    stock, shares, merger talks, union, strike, dealer award,
    sales figures, monthly sales, market share
```

`brands.yaml` deve incluir aliases (`VW`/`Volkswagen`, `BYD`/`比亚迪`, `Chevy`/`Chevrolet`).

Aplica sobre `title + summary`. Marca `prefilter_ok`, seta `status='filtered'` nos reprovados.

**Meta:** taxa de aprovação entre 8% e 20%. Se ficar fora, os keywords precisam de ajuste — logue a taxa a cada ciclo.

---

## 10. `llm/classify.py`

Input: apenas `title` + `summary` (economia de token). Modelo: `claude-haiku-4-5-20251001`, `max_tokens=300`, `temperature=0`.

Processa em lote de 20 itens por chamada para amortizar o system prompt. Use prompt caching no bloco de instruções.

### System prompt

```
Você classifica notícias automotivas. Para cada item, decida se anuncia
um LANÇAMENTO DE VEÍCULO (modelo novo, nova geração, facelift, versão
nova, estreia mundial, início de vendas ou anúncio de preço).

NÃO é lançamento: resultados financeiros, recall, nomeações executivas,
números de venda, fábricas, parcerias, patrocínio, testes de longa duração,
comparativos, opinião, listas.

Estágios possíveis:
  spy            - flagra de protótipo camuflado
  teaser         - imagem/vídeo parcial oficial pré-estreia
  concept        - conceito, não previsto para produção
  world_premiere - primeira apresentação pública oficial do veículo
  specs_release  - divulgação de ficha técnica completa
  pricing        - anúncio oficial de preço
  on_sale        - abertura de pedidos/pré-venda
  market_launch  - chegada a um mercado onde já existia em outro

Responda APENAS com um array JSON, um objeto por item de entrada,
na mesma ordem. Sem markdown, sem preâmbulo.

[{"i":0,"is_launch":true,"stage":"world_premiere","brand":"BYD",
  "model":"Seal 06 DM-i","confidence":0.92}, ...]

is_launch=false → os demais campos podem ser null.
confidence é sua certeza de 0 a 1.
Se o título estiver em outro idioma, traduza mentalmente. brand e model
sempre em alfabeto latino.
```

Aprova para extração se `is_launch && confidence >= 0.6`. Reprovados → `status='rejected'`.

---

## 11. `llm/extract.py`

Só para itens aprovados no classify. Passos:

1. `fetch(url, kind="page")` do artigo completo.
2. Extrai texto com `selectolax`: prioriza `<article>`, `<main>`, senão maior bloco de `<p>`. Se houver `<script type="application/ld+json">` com `@type: NewsArticle`, use `articleBody` — é mais limpo.
3. **Trunca em 6000 tokens.** Custo triplica sem ganho acima disso.
4. Se `blocked` ou texto < 400 chars → extrai só de `title + summary`, marca `confidence` máxima de 0.5.
5. Chamada LLM com tool use / structured output forçando o schema.

### System prompt

```
Extraia dados estruturados de lançamento de veículo do artigo fornecido.

REGRAS:
- Use null para qualquer campo não afirmado explicitamente no texto.
- NUNCA infira, estime ou complete com conhecimento externo.
- Converta unidades para o padrão do schema (hp, Nm, kWh, km).
- Se o artigo citar múltiplas versões, registre a de entrada e liste as
  demais em highlights.
- is_new_generation: true APENAS se o texto indicar plataforma nova ou
  geração nova. Facelift, restyling, "atualizado", "renovado" => false.
  Na dúvida => false.
- markets: códigos ISO-3166-1 alpha-2. Global/mundial => listar os
  mercados citados; se nenhum, usar [].
- event_date: data do anúncio (formato ISO). Não confundir com data de venda.
- Artigo em qualquer idioma; saída sempre em inglês, exceto highlights
  que devem sair em português do Brasil.
- highlights: 3 a 5 itens, ≤120 caracteres cada, factuais.
- confidence: 0-1, refletindo quão completo e inequívoco é o artigo.
```

Output validado com pydantic. Falha de validação → 1 retry com o erro no prompt → senão `status='error'`.

---

## 12. `dedupe.py`

Um reveal gera 200+ artigos em 6h. Este módulo é o que separa produto de spam.

### Etapa 1 — chave determinística

```python
dedupe_key = f"{slug(brand)}|{slug(model)}|{sorted(markets) or 'GLOBAL'}|{stage}"
```

`slug()`: lowercase, remove acentos, remove pontuação, colapsa espaços em `-`.

Match exato em janela de **14 dias** → é o mesmo evento.

### Etapa 2 — fuzzy (pega variação de nomenclatura)

Se não houve match exato, busca candidatos com mesmo `brand` + mesmo `stage` + janela 14d, e compara:

- `similarity(model_a, model_b)` via `pg_trgm` ≥ **0.55**, **E**
- cosseno do embedding ≥ **0.86**

Embedding é gerado sobre: `f"{brand} {model} {generation or ''} {' '.join(highlights)}"`.

Ambas as condições devem passar. Só embedding produz falso positivo entre modelos irmãos (ex.: Seal 05 vs Seal 06).

### Etapa 3 — merge

Ao detectar duplicata:
- Mantém o evento existente.
- Adiciona linha em `event_sources`.
- **Enriquece campos nulos** com os valores da nova fonte.
- Se a nova fonte é `tier=1` e a original não era, sobrescreve campos conflitantes e marca `is_primary=true`.
- Atualiza `updated_at`. **Não republica** salvo se `stage` mudou.

### Etapa 4 — progressão de estágio

Se chega um evento com mesma `brand|model` mas `stage` mais avançado, cria **novo** `launch_event` e vincula ao anterior. A ordem de avanço é: `spy < teaser < concept < world_premiere < specs_release < pricing < on_sale < market_launch`.

---

## 13. `curate.py` — job semanal

### Recalcula `source_metrics`

- `yield_pct = events_30d / NULLIF(items_30d,0) * 100`
- `unique_events_30d`: eventos com exatamente 1 linha em `event_sources` apontando para essa fonte
- `first_seen_30d`: eventos onde essa fonte tem o menor `seen_at`
- `median_lead_minutes`: mediana de `(mediana de seen_at do evento) - (seen_at dessa fonte)`. Positivo = chega antes.

### Regras de transição

```
promote:  probation AND yield_pct > 5 AND unique_events_30d > 0   -> active
demote:   active AND unique_events_30d = 0 AND first_seen_30d = 0
          AND age > 30d                                          -> probation
retire:   probation por 60 dias contínuos                        -> retired
```

**Unicidade e lead time mandam, não yield.** Uma fonte que republica o que a Motor1 deu 4h antes tem yield alto e valor zero.

Cutoff de retirement é 60d (não 30d) porque imprensa de salão publica em rajadas sazonais.

### Digest semanal de curadoria

Envia ao Telegram: fontes promovidas, rebaixadas, aposentadas, quebradas, e candidatas novas — com botão de confirmação. Nada é aposentado sem o OK.

### Alerta de cobertura

Marca do top-40 sem nenhum evento em **90 dias** → alerta. Isso pega feed que quebrou em silêncio, que nenhuma métrica de fonte detecta.

---

## 14. `discovery.py` — descoberta contínua

Roda semanalmente. Três heurísticas:

1. **Reverse-lookup do scoop** — para cada evento, o domínio com menor `seen_at` que não está em `sources` vira `candidate`.
2. **Outbound links** — em artigos Tier 3, extrai links externos cujo domínio contenha `media.`, `press.`, `newsroom.`, `.presse`, ou `global.*/newsroom`. Candidato a Tier 1.
3. **Eventos capturados só pelo Tier 4** (Google News) — sinal de buraco de cobertura. Rastreia o domínio de origem.

Candidatos entram como `status='candidate'`, passam pelo probe de validação de feed, e vão para `probation` se válidos. Sem isso o sistema congela na lista do dia 1 e perde toda marca chinesa nova.

---

## 15. Publishers

### `telegram.py`

Envia eventos com `published=false AND confidence >= 0.7`, ordenados por `first_seen_at`.

Formato (HTML parse mode):

```
🚗 <b>{brand} {model}</b>
{emoji_stage} {stage_label} · {markets}

{highlights como bullets}

⚡ {powertrain resumido}
💰 {price formatado}
📅 Vendas: {sales_start}

<a href="{primary_url}">Fonte</a> · {n} fontes
```

Rate limit: máximo 20 msgs/hora. Excedente entra no digest diário das 08:00 (timezone `America/Sao_Paulo`).

### `atom.py`

Gera `/feed.atom` estático com os últimos 100 eventos. Escreve em arquivo, servido por nginx ou qualquer static host. Sem framework web.

---

## 16. Configuração

`.env.example`:

```
DATABASE_URL=postgresql://carwatch:carwatch@localhost:5432/carwatch
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BOT_INFO_URL=https://example.com/bot
CONTACT_EMAIL=you@example.com
FETCH_MIN_INTERVAL_SEC=3.0
FETCH_GLOBAL_CONCURRENCY=10
INGEST_INTERVAL_MIN=45
LOG_LEVEL=INFO
```

`docker-compose.yml`: dois serviços — `db` (`pgvector/pgvector:pg16`, volume nomeado) e `app`. Healthcheck no db; app depende dele.

**Nota de deploy:** rode primeiro no desktop (IP residencial). Ranges de datacenter são pré-classificados como bot por vários WAFs. Migre para VPS só depois de medir a taxa de 403.

---

## 17. CLI (`typer`)

```
carwatch db migrate
carwatch probe --brands config/brands.yaml
carwatch ingest --once
carwatch classify --limit 100
carwatch extract --limit 50
carwatch curate
carwatch discover
carwatch publish --dry-run
carwatch run                    # scheduler, modo daemon
carwatch review --limit 15      # amostragem manual de precisão
carwatch stats                  # saúde do pipeline
```

`review` mostra evento + link e pede `[c]onfirmar / [r]ejeitar / [s]kip`, gravando em `review_status`. **20 minutos por semana disso é o único trabalho manual que não dá para eliminar** nos primeiros 2 meses — sem ground truth, `precision_30d` é teatro.

---

## 18. Observabilidade

`structlog` em JSON para stdout. Eventos obrigatórios:

| Evento | Campos |
|---|---|
| `fetch.result` | domain, status, ms, not_modified, blocked |
| `ingest.cycle` | sources_checked, items_new, ms |
| `prefilter.batch` | in, out, pass_rate |
| `llm.call` | op, model, tokens_in, tokens_out, usd |
| `dedupe.match` | method (exact\|fuzzy), similarity |
| `breaker.trip` | domain, reason |
| `publish.sent` | event_id, channel |

Tabela `daily_stats` com agregação diária. `carwatch stats` lê dela.

**Alerta obrigatório:** custo LLM acumulado do mês > US$30 → notifica e pausa extração. Proteção contra loop de retry.

---

## 19. Fases e critérios de aceite

### Fase 1 — Espinha dorsal (meta: ~6h de agente)

Entrega: `fetcher`, `db`, `ingest`, `prefilter`, `classify`, `telegram`, CLI, docker-compose. 20 fontes seed.

✅ Aceite:
- `docker compose up` sobe e migra sem intervenção
- `carwatch probe` roda sobre 20 marcas e grava sources válidas
- `carwatch ingest --once` popula `raw_items` sem duplicatas
- Segundo `ingest` consecutivo gera ≥80% de respostas 304
- Prefilter aprova entre 8% e 20%
- Mensagem chega no Telegram
- Teste garante que nenhum módulo fora de `fetcher.py` faz HTTP
- Teste de bloqueio silencioso: mock de 200 com `"Just a moment"` → `blocked=True`

### Fase 2 — Estrutura e qualidade (meta: ~12h)

Entrega: `extract`, `dedupe`, `launch_events`, `atom`, `review`.

✅ Aceite:
- 30 artigos reais extraídos com schema válido
- Fixture com 8 artigos sobre o mesmo lançamento → colapsa em 1 evento
- Fixture com 2 modelos irmãos (ex.: Seal 05 e Seal 06) → **não** colapsa
- Progressão de estágio cria evento novo, não sobrescreve
- Feed Atom valida no W3C validator

### Fase 3 — Autonomia (meta: ~10h)

Entrega: `curate`, `discovery`, `daily_stats`, alertas, digest.

✅ Aceite:
- `curate` transiciona status corretamente sobre dados sintéticos
- `discovery` identifica ≥3 candidatos válidos em 30d de dados reais
- Alerta de marca silenciosa dispara em teste
- Alerta de custo dispara ao ultrapassar o teto

---

## 20. Testes obrigatórios

- `respx` para mockar todo HTTP. **Zero rede real em testes.**
- Fixtures de feed reais salvos em `tests/fixtures/feeds/*.xml`
- Fixtures de artigo em `tests/fixtures/articles/*.html` (incluir 1 em chinês, 1 em japonês, 1 em português)
- LLM mockado por padrão; testes de integração real atrás da marca `@pytest.mark.live`
- Cobertura mínima em `fetcher.py`, `dedupe.py`, `prefilter.py`: **90%**

---

## 21. Armadilhas conhecidas (leia antes de codar)

1. **Não use `requests`.** Async do início ao fim.
2. **Não paralelize dentro do mesmo domínio.** Burst é o gatilho de bloqueio, não volume total.
3. **Não retente 403.** Insistir após o primeiro 403 transforma bloqueio de rota em bloqueio de ASN.
4. **Não confie em status 200.** Valide conteúdo.
5. **Não deixe o LLM inventar specs.** Prompt já força `null`; valide que campos numéricos ausentes no texto não aparecem no output durante os testes.
6. **`is_new_generation` é onde o LLM mais erra.** Facelift vira "lançamento" com facilidade. Por isso o campo é separado e o default na dúvida é `false`.
7. **Não escreva scraper para press room sem RSS.** Decisão de projeto: cai no fallback.
8. **Não implemente enrichment por API de catálogo nesta versão.** Fora de escopo — as APIs atrasam meses e não agregam na detecção.
9. **`temperature=0` em toda chamada LLM.**
10. **Timezone**: tudo em UTC no banco, `America/Sao_Paulo` só na apresentação.

---

## 22. Definição de pronto

O sistema está pronto quando, após 14 dias rodando:

- Detecta ≥90% dos lançamentos das 40 marcas principais (validado contra Motor1/Autocar manualmente)
- Taxa de duplicata no Telegram < 5%
- Custo LLM < US$15/mês
- Nenhum domínio em `status='blocked'` por culpa do fetcher
- Intervenção manual ≤ 30 min/semana
