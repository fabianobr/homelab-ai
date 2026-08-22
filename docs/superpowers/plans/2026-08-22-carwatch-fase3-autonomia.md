# CarWatch Fase 3 — Autonomia — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `curate` (source metrics + promote/demote/retire), `discover` (continuous source discovery), `daily_stats`, the LLM cost cap, and the weekly curation digest — so CarWatch stops being frozen at its Fase 1 seed list and starts adapting which sources it trusts.

**Architecture:** Unchanged. `curate` and `discover` join the end of `weekly-run`, after `publish` — this matches SPEC.md §13/§14's own weekly cadence, which was already weekly in the original daemon design (DESIGN.md's delta doesn't change anything here).

**Tech Stack:** No new libraries.

**Spec:** `agents/carwatch/SPEC.md` §13, §14, §18, §19 (Fase 3), §22 + `agents/carwatch/DESIGN.md`. **Depends on** the Fase 1 and Fase 2 plans being fully implemented first.

**Pricing used for the cost cap (looked up live via the `claude-api` skill, not guessed):** Claude Haiku 4.5 is $1.00 / MTok input, $5.00 / MTok output as of this plan's writing. SPEC.md pins the dated snapshot `claude-haiku-4-5-20251001`; dated snapshots normally share their base model's pricing, but **confirm this against Anthropic's current pricing page before trusting the $30/month cap in production** — this plan makes the pricing a config value specifically so a wrong number is a one-line fix, not a code change.

## Global Constraints

- All Fase 1/2 Global Constraints still apply.
- **"Nada é aposentado sem o OK" (SPEC.md §13) is honored as a genuine deviation, explained here, not silently dropped:** this agent has no long-running process to receive a Telegram inline-button callback (it's a systemd-timer batch job with no webhook listener). Retirement is therefore **never automatic**: `curate` only flags 60-day-stale-probation sources into a `pending_retirements` table and lists them in the digest; an operator confirms with `carwatch curate --confirm-retirement <id>` in a later run. Promote/demote are lower-risk and reversible, so those stay automatic exactly as SPEC.md §13 specifies.
- `median_lead_minutes` (SPEC.md §13) is **not computed** in this plan — DESIGN.md §2 already establishes it's meaningless on a weekly cadence ("ordem de chegada dentro da mesma janela de 7 dias é praticamente ruído"). The column stays in the schema (Fase 1) and stays `NULL`.
- Cost cap check happens **before** `run_extract` inside `weekly-run` (SPEC.md §18: "notifica e pausa **extração**" — specifically extraction, the most expensive stage since it sends full article text, not classification).

---

### Task 1: Migration `005_curation.sql` — `daily_stats`, `llm_usage`, `pending_retirements`, `probation_since`

**Files:**
- Create: `agents/carwatch/migrations/005_curation.sql`
- Test: `agents/carwatch/tests/test_migrations_curation.py`

**Interfaces:**
- Produces: `daily_stats` (one row per day, aggregated), `llm_usage` (one row per LLM call, feeds the cost cap and `daily_stats`), `pending_retirements` (source ids awaiting manual confirmation), and `sources.probation_since` (new column — when a source most recently entered `'probation'`, needed because `added_at` only reflects *original* insertion, not re-entry into probation after a demotion).

- [ ] **Step 1: Write `migrations/005_curation.sql`**

```sql
ALTER TABLE sources ADD COLUMN probation_since TIMESTAMPTZ;
UPDATE sources SET probation_since = added_at WHERE status = 'probation' AND probation_since IS NULL;

CREATE TABLE pending_retirements (
  source_id  BIGINT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  flagged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
  id          BIGSERIAL PRIMARY KEY,
  called_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  op          TEXT NOT NULL,          -- 'classify' | 'extract'
  model       TEXT NOT NULL,
  tokens_in   INT NOT NULL,
  tokens_out  INT NOT NULL,
  cost_usd    NUMERIC(10,4) NOT NULL
);
CREATE INDEX ON llm_usage (called_at);

CREATE TABLE daily_stats (
  day                DATE PRIMARY KEY,
  items_ingested     INT DEFAULT 0,
  items_classified   INT DEFAULT 0,
  items_approved     INT DEFAULT 0,
  items_extracted    INT DEFAULT 0,
  events_created     INT DEFAULT 0,
  events_published   INT DEFAULT 0,
  llm_calls          INT DEFAULT 0,
  llm_tokens_in      INT DEFAULT 0,
  llm_tokens_out     INT DEFAULT 0,
  llm_cost_usd       NUMERIC(10,4) DEFAULT 0,
  sources_active     INT DEFAULT 0,
  sources_blocked    INT DEFAULT 0,
  computed_at        TIMESTAMPTZ DEFAULT now()
);
```

**Deviation from SPEC.md, noted explicitly:** SPEC.md §18 says only "Tabela `daily_stats` com agregação diária" without a schema — this plan designs one from the observability events SPEC.md §18 already requires (`fetch.result`, `ingest.cycle`, `prefilter.batch`, `llm.call`, `dedupe.match`, `breaker.trip`, `publish.sent`), so `carwatch stats` has real columns to read.

- [ ] **Step 2: Write the test**

```python
"""tests/test_migrations_curation.py"""
async def test_curation_tables_and_column_exist(db_pool):
    async with db_pool.connection() as conn:
        for table in ("pending_retirements", "llm_usage", "daily_stats"):
            result = await conn.execute(f"SELECT to_regclass('public.{table}')")
            assert (await result.fetchone())[0] == table
        result = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sources' AND column_name = 'probation_since'"
        )
        assert (await result.fetchone()) is not None
```

- [ ] **Step 3: Update `conftest.py`'s truncate list**

```python
# tests/conftest.py — extend the TRUNCATE line inside db_pool once more:
        await conn.execute(
            "TRUNCATE raw_items, source_metrics, sources, launch_events, event_sources, "
            "source_incidents, pending_retirements, llm_usage, daily_stats "
            "RESTART IDENTITY CASCADE"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_migrations_curation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add migrations/005_curation.sql tests/test_migrations_curation.py tests/conftest.py
git commit -m "feat(carwatch): add daily_stats, llm_usage, pending_retirements schema"
```

---

### Task 2: `cost.py` — LLM usage tracking + monthly cost cap

**Files:**
- Create: `agents/carwatch/src/carwatch/cost.py`
- Modify: `agents/carwatch/config/settings.yaml` — add `llm_pricing`.
- Modify: `agents/carwatch/src/carwatch/llm/client.py` — `call_classify`/`call_extract` return `(text, usage)` instead of just `text`.
- Modify: `agents/carwatch/src/carwatch/llm/classify.py` and `agents/carwatch/src/carwatch/llm/extract.py` — record usage after every call; `run_extract` refuses to run when cost-capped.
- Test: `agents/carwatch/tests/test_cost.py`

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3).
- Produces: `def compute_cost_usd(tokens_in: int, tokens_out: int, *, input_usd_per_million: float, output_usd_per_million: float) -> float`.
- Produces: `def load_llm_pricing(settings_path: Path, model: str) -> tuple[float, float]` — `(input_usd_per_million, output_usd_per_million)`.
- Produces: `async def record_llm_usage(pool, op: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None`.
- Produces: `async def month_to_date_cost_usd(pool, now: datetime | None = None) -> float`.
- Produces: `MONTHLY_COST_CAP_USD = 30.0` (SPEC.md §18, exact value).
- Produces: `async def is_extraction_cost_capped(pool, now: datetime | None = None) -> bool`.

- [ ] **Step 1: Add pricing to `config/settings.yaml`**

```yaml
# append to config/settings.yaml
llm_pricing:
  "claude-haiku-4-5-20251001":
    # Looked up 2026-08-22 via Anthropic's current pricing for claude-haiku-4-5 (undated).
    # Dated snapshots normally share base-model pricing — reconfirm before trusting the cap.
    input_usd_per_million: 1.00
    output_usd_per_million: 5.00
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_cost.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from carwatch.cost import (
    MONTHLY_COST_CAP_USD,
    compute_cost_usd,
    is_extraction_cost_capped,
    load_llm_pricing,
    month_to_date_cost_usd,
    record_llm_usage,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_compute_cost_usd_matches_haiku_pricing():
    cost = compute_cost_usd(1_000_000, 1_000_000, input_usd_per_million=1.0, output_usd_per_million=5.0)
    assert cost == 6.0


def test_load_llm_pricing_reads_settings_yaml():
    input_price, output_price = load_llm_pricing(CONFIG_DIR / "settings.yaml", "claude-haiku-4-5-20251001")
    assert input_price == 1.00
    assert output_price == 5.00


async def test_month_to_date_cost_sums_only_current_month(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "classify", "claude-haiku-4-5-20251001", 1000, 500, 0.0035)
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO llm_usage (called_at, op, model, tokens_in, tokens_out, cost_usd) "
            "VALUES (%s, 'extract', 'claude-haiku-4-5-20251001', 1000, 500, 5.0)",
            (now - timedelta(days=40),),  # previous month — must be excluded
        )

    total = await month_to_date_cost_usd(db_pool, now=now)

    assert abs(total - 0.0035) < 1e-6


async def test_is_extraction_cost_capped_true_above_30_usd(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1_000_000, 6_000_000, 31.0)

    assert await is_extraction_cost_capped(db_pool, now=now) is True


async def test_is_extraction_cost_capped_false_below_30_usd(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1000, 500, 5.0)

    assert await is_extraction_cost_capped(db_pool, now=now) is False


def test_monthly_cost_cap_matches_spec_value():
    assert MONTHLY_COST_CAP_USD == 30.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cost.py -v`
Expected: FAIL — `carwatch.cost` doesn't exist.

- [ ] **Step 4: Implement `cost.py`**

```python
"""src/carwatch/cost.py"""
from datetime import datetime, timezone
from pathlib import Path

import yaml

MONTHLY_COST_CAP_USD = 30.0


def compute_cost_usd(
    tokens_in: int, tokens_out: int, *, input_usd_per_million: float, output_usd_per_million: float
) -> float:
    return round(
        tokens_in / 1_000_000 * input_usd_per_million
        + tokens_out / 1_000_000 * output_usd_per_million,
        6,
    )


def load_llm_pricing(settings_path: Path, model: str) -> tuple[float, float]:
    data = yaml.safe_load(settings_path.read_text())
    pricing = data["llm_pricing"][model]
    return pricing["input_usd_per_million"], pricing["output_usd_per_million"]


async def record_llm_usage(pool, op: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO llm_usage (op, model, tokens_in, tokens_out, cost_usd) VALUES (%s, %s, %s, %s, %s)",
            (op, model, tokens_in, tokens_out, cost_usd),
        )


async def month_to_date_cost_usd(pool, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT COALESCE(sum(cost_usd), 0) FROM llm_usage WHERE called_at >= %s",
            (month_start,),
        )
        return float((await result.fetchone())[0])


async def is_extraction_cost_capped(pool, now: datetime | None = None) -> bool:
    return await month_to_date_cost_usd(pool, now) > MONTHLY_COST_CAP_USD
```

- [ ] **Step 5: Update `llm/client.py` to return usage alongside text**

```python
# src/carwatch/llm/client.py — replace call_classify and call_extract bodies
async def call_classify(system_prompt: str, user_content: str) -> tuple[str, dict]:
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    usage = {"tokens_in": response.usage.input_tokens, "tokens_out": response.usage.output_tokens}
    return text, usage


async def call_extract(system_prompt: str, article_text: str) -> tuple[str, dict]:
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": article_text}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    usage = {"tokens_in": response.usage.input_tokens, "tokens_out": response.usage.output_tokens}
    return text, usage
```

- [ ] **Step 6: Update `llm/classify.py`'s `run_classify` to record usage**

```python
# src/carwatch/llm/classify.py — inside the batch loop in run_classify, replace:
#     raw_response = await call_classify(system_prompt, user_content)
# with:
        raw_response, usage = await call_classify(system_prompt, user_content)
        input_price, output_price = load_llm_pricing(CONFIG_DIR / "settings.yaml", MODEL)
        cost = compute_cost_usd(
            usage["tokens_in"], usage["tokens_out"],
            input_usd_per_million=input_price, output_usd_per_million=output_price,
        )
        await record_llm_usage(pool, "classify", MODEL, usage["tokens_in"], usage["tokens_out"], cost)
```

Add the needed imports at the top of `llm/classify.py`:

```python
from pathlib import Path

from carwatch.cost import compute_cost_usd, load_llm_pricing, record_llm_usage
from carwatch.llm.client import MODEL

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"  # src/carwatch/llm/ -> agents/carwatch/config
```

- [ ] **Step 7: Update `llm/extract.py`'s `extract_one_item` to record usage and check the cost cap in `run_extract`**

```python
# src/carwatch/llm/extract.py — replace the two `await call_extract(...)` call sites inside
# extract_one_item with:
        raw_response, usage = await call_extract(truncated)
        await _record_extract_usage(pool, usage)
        extracted = parse_extract_response(raw_response)
# ...and for the retry:
        raw_response, usage = await call_extract(retry_text)
        await _record_extract_usage(pool, usage)
        extracted = parse_extract_response(raw_response)
```

```python
# src/carwatch/llm/extract.py — add near the top (after the existing imports)
from pathlib import Path

from carwatch.cost import compute_cost_usd, is_extraction_cost_capped, load_llm_pricing, record_llm_usage
from carwatch.llm.client import MODEL

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


async def _record_extract_usage(pool, usage: dict) -> None:
    input_price, output_price = load_llm_pricing(CONFIG_DIR / "settings.yaml", MODEL)
    cost = compute_cost_usd(
        usage["tokens_in"], usage["tokens_out"],
        input_usd_per_million=input_price, output_usd_per_million=output_price,
    )
    await record_llm_usage(pool, "extract", MODEL, usage["tokens_in"], usage["tokens_out"], cost)
```

```python
# src/carwatch/llm/extract.py — run_extract gains a cost-cap guard as its first check
async def run_extract(pool, logger, limit: int = 50) -> dict:
    if await is_extraction_cost_capped(pool):
        if logger is not None:
            logger.warning("extract.cost_capped", cap_usd=30.0)
        return {"in": 0, "extracted": 0, "error": 0, "cost_capped": True}

    # ... existing body unchanged below this point
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cost.py tests/test_classify.py tests/test_extract.py -v`
Expected: PASS (Fase 2's `test_classify.py`/`test_extract.py` mocks of `call_classify`/`call_extract` need their `return_value`/`side_effect` updated from a bare string to a `(text, usage)` tuple — e.g. `AsyncMock(return_value=(fake_response, {"tokens_in": 100, "tokens_out": 50}))` — go back and fix those two test files' mocks now.)

- [ ] **Step 9: Commit**

```bash
cd agents/carwatch
git add config/settings.yaml src/carwatch/cost.py src/carwatch/llm tests/test_cost.py tests/test_classify.py tests/test_extract.py
git commit -m "feat(carwatch): add LLM cost tracking and the \$30/month extraction cap"
```

---

### Task 3: `curate.py` — source metrics, promote/demote, retirement flagging, coverage alert

**Files:**
- Create: `agents/carwatch/src/carwatch/curate.py`
- Modify: `agents/carwatch/src/carwatch/probe.py` — set `probation_since = now()` on insert.
- Modify: `agents/carwatch/src/carwatch/discovery_seed.py` — same, on insert.
- Test: `agents/carwatch/tests/test_curate.py`

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3), `send_telegram_message` (Fase 1/2 Task 15/6).
- Produces: `async def recompute_source_metrics(pool, now: datetime | None = None) -> int` — upserts `source_metrics` for every source over a rolling 30-day window (`items_30d, passed_prefilter_30d, events_30d, unique_events_30d, first_seen_30d, yield_pct, precision_30d`; `median_lead_minutes` stays `NULL` — see Global Constraints). Returns the number of sources processed.
- Produces: `async def apply_transitions(pool, now: datetime | None = None) -> dict` — SPEC.md §13 promote/demote rules, applied automatically; retirement only **flagged** into `pending_retirements`, never applied automatically. Returns `{"promoted": [ids], "demoted": [ids], "retirement_candidates": [ids]}`.
- Produces: `async def find_stale_brands(pool, now: datetime | None = None) -> list[str]` — brands present in any `sources.brand_scope` with zero `launch_events` in the last 90 days.
- Produces: `async def confirm_retirement(pool, source_id: int) -> None` — the human-in-the-loop step SPEC.md §13 requires; sets `status='retired'`, clears the `pending_retirements` row.
- Produces: `async def send_curation_digest(pool, bot_token: str, chat_id: str, transitions: dict, stale_brands: list[str], logger) -> bool`.
- Produces: `async def run_curate(pool, bot_token: str, chat_id: str, logger, now: datetime | None = None) -> dict`.

- [ ] **Step 1: Update `probe.py`'s insert to set `probation_since`**

```python
# src/carwatch/probe.py — inside run_probe, change the INSERT to:
                await conn.execute(
                    "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope, probation_since) "
                    "VALUES (%s, %s, 'rss', 1, 'probation', %s, now()) "
                    "ON CONFLICT (feed_url) DO NOTHING",
                    (brand.press_domain, feed_url, [brand.name]),
                )
```

- [ ] **Step 2: Update `discovery_seed.py`'s insert similarly**

```python
# src/carwatch/discovery_seed.py — inside seed_fixed_sources, change the INSERT to:
            await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status, region, lang, probation_since) "
                "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, 'probation', %(region)s, %(lang)s, now()) "
                "ON CONFLICT (feed_url) DO NOTHING",
                candidate,
            )
```

- [ ] **Step 3: Write the failing tests**

```python
"""tests/test_curate.py"""
from datetime import datetime, timedelta, timezone

from carwatch.curate import (
    apply_transitions,
    confirm_retirement,
    find_stale_brands,
    recompute_source_metrics,
    run_curate,
)


async def _insert_source(db_pool, **overrides) -> int:
    defaults = dict(
        domain="x.com", feed_url=f"https://x.com/{overrides.get('_unique', 1)}",
        kind="rss", tier=1, status="probation", brand_scope=["BYD"],
    )
    defaults.update({k: v for k, v in overrides.items() if k != "_unique"})
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope, probation_since, added_at) "
            "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, %(status)s, %(brand_scope)s, "
            "%(probation_since)s, %(added_at)s) RETURNING id",
            {**defaults, "probation_since": defaults.get("probation_since"), "added_at": defaults.get("added_at", datetime.now(timezone.utc))},
        )
        return (await result.fetchone())[0]


async def test_recompute_source_metrics_computes_yield_pct(db_pool):
    source_id = await _insert_source(db_pool, _unique=1)
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, prefilter_ok) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't', TRUE) RETURNING id",
            (source_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) VALUES (%s, %s, %s, TRUE)",
            (event_id, item_id, source_id),
        )

    await recompute_source_metrics(db_pool)

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT items_30d, events_30d, unique_events_30d, yield_pct FROM source_metrics WHERE source_id = %s",
            (source_id,),
        )
        row = await result.fetchone()
    assert row == (1, 1, 1, 100.0)


async def test_apply_transitions_promotes_high_yield_probation_source(db_pool):
    source_id = await _insert_source(db_pool, _unique=2, status="probation")
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO source_metrics (source_id, items_30d, events_30d, unique_events_30d, yield_pct) "
            "VALUES (%s, 10, 2, 1, 20.0)",
            (source_id,),
        )

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["promoted"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "active"


async def test_apply_transitions_demotes_stale_active_source(db_pool):
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    source_id = await _insert_source(db_pool, _unique=3, status="active", added_at=old_date)
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO source_metrics (source_id, items_30d, events_30d, unique_events_30d, first_seen_30d, yield_pct) "
            "VALUES (%s, 10, 0, 0, 0, 0.0)",
            (source_id,),
        )

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["demoted"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, probation_since FROM sources WHERE id = %s", (source_id,))
        row = await result.fetchone()
    assert row[0] == "probation"
    assert row[1] is not None


async def test_apply_transitions_flags_but_does_not_retire_after_60_days(db_pool):
    old_probation = datetime.now(timezone.utc) - timedelta(days=61)
    source_id = await _insert_source(db_pool, _unique=4, status="probation", probation_since=old_probation)

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["retirement_candidates"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "probation"  # NOT auto-retired
        result = await conn.execute("SELECT count(*) FROM pending_retirements WHERE source_id = %s", (source_id,))
        assert (await result.fetchone())[0] == 1


async def test_confirm_retirement_applies_the_human_decision(db_pool):
    old_probation = datetime.now(timezone.utc) - timedelta(days=61)
    source_id = await _insert_source(db_pool, _unique=5, status="probation", probation_since=old_probation)
    await apply_transitions(db_pool)

    await confirm_retirement(db_pool, source_id)

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "retired"
        result = await conn.execute("SELECT count(*) FROM pending_retirements WHERE source_id = %s", (source_id,))
        assert (await result.fetchone())[0] == 0


async def test_find_stale_brands_flags_brand_with_no_recent_events(db_pool):
    await _insert_source(db_pool, _unique=6, brand_scope=["Toyota"])
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence, first_seen_at) "
            "VALUES ('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, now())"
        )

    stale = await find_stale_brands(db_pool)

    assert "Toyota" in stale
    assert "BYD" not in stale
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_curate.py -v`
Expected: FAIL — `carwatch.curate` doesn't exist.

- [ ] **Step 5: Implement `curate.py`**

```python
"""src/carwatch/curate.py"""
from datetime import datetime, timedelta, timezone

from carwatch.publishers.telegram import send_telegram_message

PROMOTE_YIELD_THRESHOLD = 5.0
DEMOTE_MIN_AGE_DAYS = 30
RETIRE_PROBATION_DAYS = 60
STALE_BRAND_DAYS = 90


async def recompute_source_metrics(pool, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)

    async with pool.connection() as conn:
        result = await conn.execute("SELECT id FROM sources")
        source_ids = [r[0] for r in await result.fetchall()]

        for source_id in source_ids:
            items_result = await conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE prefilter_ok = TRUE) "
                "FROM raw_items WHERE source_id = %s AND fetched_at >= %s",
                (source_id, window_start),
            )
            items_30d, passed_30d = await items_result.fetchone()

            events_result = await conn.execute(
                "SELECT count(DISTINCT event_id) FROM event_sources "
                "WHERE source_id = %s AND seen_at >= %s",
                (source_id, window_start),
            )
            events_30d = (await events_result.fetchone())[0]

            unique_result = await conn.execute(
                "SELECT count(*) FROM ("
                "  SELECT event_id FROM event_sources WHERE seen_at >= %s "
                "  GROUP BY event_id HAVING count(*) = 1 AND bool_or(source_id = %s)"
                ") sub",
                (window_start, source_id),
            )
            unique_events_30d = (await unique_result.fetchone())[0]

            first_seen_result = await conn.execute(
                "SELECT count(*) FROM event_sources es WHERE es.source_id = %s AND es.seen_at >= %s "
                "AND es.seen_at = (SELECT min(seen_at) FROM event_sources es2 WHERE es2.event_id = es.event_id)",
                (source_id, window_start),
            )
            first_seen_30d = (await first_seen_result.fetchone())[0]

            precision_result = await conn.execute(
                "SELECT count(*) FILTER (WHERE le.review_status = 'confirmed')::float "
                "  / NULLIF(count(*) FILTER (WHERE le.review_status IN ('confirmed','rejected')), 0) * 100 "
                "FROM event_sources es JOIN launch_events le ON le.id = es.event_id "
                "WHERE es.source_id = %s AND es.seen_at >= %s",
                (source_id, window_start),
            )
            precision_30d = (await precision_result.fetchone())[0]

            yield_pct = round(events_30d / items_30d * 100, 2) if items_30d else None

            await conn.execute(
                "INSERT INTO source_metrics "
                "(source_id, items_30d, passed_prefilter_30d, events_30d, unique_events_30d, "
                " first_seen_30d, yield_pct, precision_30d, computed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "items_30d = EXCLUDED.items_30d, passed_prefilter_30d = EXCLUDED.passed_prefilter_30d, "
                "events_30d = EXCLUDED.events_30d, unique_events_30d = EXCLUDED.unique_events_30d, "
                "first_seen_30d = EXCLUDED.first_seen_30d, yield_pct = EXCLUDED.yield_pct, "
                "precision_30d = EXCLUDED.precision_30d, computed_at = now()",
                (source_id, items_30d, passed_30d, events_30d, unique_events_30d,
                 first_seen_30d, yield_pct, precision_30d),
            )

    return len(source_ids)


async def apply_transitions(pool, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)

    async with pool.connection() as conn:
        promoted = await conn.execute(
            "UPDATE sources SET status = 'active', probation_since = NULL "
            "FROM source_metrics sm WHERE sources.id = sm.source_id "
            "AND sources.status = 'probation' "
            "AND sm.yield_pct > %s AND sm.unique_events_30d > 0 "
            "RETURNING sources.id",
            (PROMOTE_YIELD_THRESHOLD,),
        )
        promoted_ids = [r[0] for r in await promoted.fetchall()]

        demoted = await conn.execute(
            "UPDATE sources SET status = 'probation', probation_since = %s "
            "FROM source_metrics sm WHERE sources.id = sm.source_id "
            "AND sources.status = 'active' "
            "AND sm.unique_events_30d = 0 AND sm.first_seen_30d = 0 "
            "AND sources.added_at < %s "
            "RETURNING sources.id",
            (now, now - timedelta(days=DEMOTE_MIN_AGE_DAYS)),
        )
        demoted_ids = [r[0] for r in await demoted.fetchall()]

        retire_cutoff = now - timedelta(days=RETIRE_PROBATION_DAYS)
        candidates = await conn.execute(
            "SELECT id FROM sources WHERE status = 'probation' "
            "AND probation_since IS NOT NULL AND probation_since < %s "
            "AND id NOT IN (SELECT source_id FROM pending_retirements)",
            (retire_cutoff,),
        )
        retirement_candidate_ids = [r[0] for r in await candidates.fetchall()]
        for source_id in retirement_candidate_ids:
            await conn.execute(
                "INSERT INTO pending_retirements (source_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (source_id,),
            )

    return {
        "promoted": promoted_ids,
        "demoted": demoted_ids,
        "retirement_candidates": retirement_candidate_ids,
    }


async def find_stale_brands(pool, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STALE_BRAND_DAYS)
    async with pool.connection() as conn:
        all_brands_result = await conn.execute("SELECT DISTINCT unnest(brand_scope) FROM sources")
        all_brands = {r[0] for r in await all_brands_result.fetchall()}
        recent_result = await conn.execute(
            "SELECT DISTINCT brand FROM launch_events WHERE first_seen_at >= %s", (cutoff,)
        )
        recent_brands = {r[0] for r in await recent_result.fetchall()}
    return sorted(b for b in all_brands if b not in recent_brands)


async def confirm_retirement(pool, source_id: int) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE sources SET status = 'retired' WHERE id = %s", (source_id,))
        await conn.execute("DELETE FROM pending_retirements WHERE source_id = %s", (source_id,))


async def send_curation_digest(
    pool, bot_token: str, chat_id: str, transitions: dict, stale_brands: list[str], logger
) -> bool:
    lines = ["📊 CarWatch — Curadoria semanal", ""]
    lines.append(f"Promovidas: {len(transitions['promoted'])}")
    lines.append(f"Rebaixadas: {len(transitions['demoted'])}")
    lines.append(
        f"Candidatas a aposentadoria (aguardando confirmação manual): "
        f"{len(transitions['retirement_candidates'])}"
    )
    if transitions["retirement_candidates"]:
        ids = ", ".join(str(i) for i in transitions["retirement_candidates"])
        lines.append(f"  IDs: {ids}")
        lines.append("  Confirme com: carwatch curate --confirm-retirement <id>")
    if stale_brands:
        lines.append("")
        lines.append(f"⚠️ Marcas sem lançamento em {STALE_BRAND_DAYS} dias: " + ", ".join(stale_brands))

    ok = await send_telegram_message(bot_token, chat_id, "\n".join(lines))
    if logger is not None:
        logger.info(
            "curate.digest", ok=ok,
            promoted=len(transitions["promoted"]), demoted=len(transitions["demoted"]),
            retirement_candidates=len(transitions["retirement_candidates"]), stale_brands=len(stale_brands),
        )
    return ok


async def run_curate(pool, bot_token: str, chat_id: str, logger, now: datetime | None = None) -> dict:
    await recompute_source_metrics(pool, now)
    transitions = await apply_transitions(pool, now)
    stale_brands = await find_stale_brands(pool, now)
    digest_sent = await send_curation_digest(pool, bot_token, chat_id, transitions, stale_brands, logger)
    return {"transitions": transitions, "stale_brands": stale_brands, "digest_sent": digest_sent}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_curate.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add src/carwatch/curate.py src/carwatch/probe.py src/carwatch/discovery_seed.py tests/test_curate.py
git commit -m "feat(carwatch): add curate — source metrics, promote/demote, retirement flagging"
```

---

### Task 4: `discovery.py` — continuous source discovery (SPEC.md §14's three heuristics)

**Files:**
- Modify: `agents/carwatch/src/carwatch/probe.py` — extract `discover_feed_for_domain` so `discovery.py` can reuse the candidate-path/link-rel/sitemap chain without duplicating it.
- Create: `agents/carwatch/src/carwatch/discovery.py`
- Test: `agents/carwatch/tests/test_discovery.py`

**Interpretation note (this plan's own reading of SPEC.md §14, stated explicitly because the text is genuinely ambiguous):** heuristics 1 ("reverse-lookup do scoop") and 3 ("eventos capturados só pelo Tier 4... rastreia o domínio de origem") both reduce to the same mechanical check — find the real publisher domain behind an event whose earliest source was Tier 4 (Google News) — so this plan implements them as one function, `find_scoop_domain_candidates`. Heuristic 2 (outbound press-room-like links from Tier 3 articles) is implemented separately as `find_outbound_link_candidates`, exactly as SPEC.md describes it.

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3), `probe.discover_feed_for_domain` (this task, Step 1).
- Produces: `async def discover_feed_for_domain(domain: str) -> str | None` (moved from `probe.py`'s inline logic in `probe_brand`).
- Produces: `async def find_scoop_domain_candidates(pool) -> list[str]` — real publisher domains behind Tier-4-only-sourced events, not already in `sources`.
- Produces: `async def find_outbound_link_candidates(pool) -> list[str]` — hostnames from `<a href>` links in Tier 3 article bodies matching `media.`/`press.`/`newsroom.`/`.presse`, not already in `sources`.
- Produces: `async def register_and_validate_candidates(pool, domains: list[str], tier: int, logger) -> dict` — runs `discover_feed_for_domain` on each; only domains that validate get inserted into `sources` as `status='probation'` (SPEC.md §14: "passam pelo probe de validação de feed, e vão para probation se válidos" — this plan skips the intermediate literal `status='candidate'` row since a domain that fails validation is simply not registered at all, which is behaviorally identical and one fewer moving part).
- Produces: `async def run_discovery(pool, logger) -> dict`.

- [ ] **Step 1: Refactor `probe.py` to extract `discover_feed_for_domain`**

```python
# src/carwatch/probe.py — replace probe_brand's body and add discover_feed_for_domain above it
async def discover_feed_for_domain(domain: str) -> str | None:
    for strategy in (_try_candidate_paths, _try_link_rel_discovery, _try_sitemaps):
        feed_url = await strategy(domain)
        if feed_url:
            return feed_url
    return None


async def probe_brand(brand: BrandEntry) -> tuple[str | None, str]:
    if not brand.press_domain:
        return None, "no_press_domain"
    feed_url = await discover_feed_for_domain(brand.press_domain)
    return (feed_url, "ok") if feed_url else (None, "no_feed_found")
```

Run the existing Fase 1 probe tests to confirm the refactor didn't change behavior: `cd agents/carwatch && python3 -m pytest tests/test_probe.py -v` — expect PASS, unchanged.

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_discovery.py"""
from unittest.mock import AsyncMock, patch

from carwatch.discovery import (
    find_outbound_link_candidates,
    find_scoop_domain_candidates,
    register_and_validate_candidates,
    run_discovery,
)


async def _insert_source(db_pool, domain: str, tier: int, feed_url: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES (%s, %s, 'rss', %s, 'active') RETURNING id",
            (domain, feed_url, tier),
        )
        return (await result.fetchone())[0]


async def test_find_scoop_domain_candidates_finds_real_domain_behind_tier4_event(db_pool):
    tier4_id = await _insert_source(db_pool, "news.google.com", 4, "https://news.google.com/feed1")
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://newmedia.example.com/article', 'h1', 't') RETURNING id",
            (tier4_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'X', 'Y', 'y', 'teaser', ARRAY['h'], 0.7) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id) VALUES (%s, %s, %s)",
            (event_id, item_id, tier4_id),
        )

    candidates = await find_scoop_domain_candidates(db_pool)

    assert candidates == ["newmedia.example.com"]


async def test_find_outbound_link_candidates_matches_press_patterns(db_pool):
    tier3_id = await _insert_source(db_pool, "carscoops.com", 3, "https://carscoops.com/feed")
    body = (
        '<html><body><article>'
        '<a href="https://media.acme-motors.com/press-release">official</a>'
        '<a href="https://twitter.com/acme">social</a>'
        '</article></body></html>'
    )
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, body) "
            "VALUES (%s, 'https://carscoops.com/a', 'h1', 't', %s)",
            (tier3_id, body),
        )

    candidates = await find_outbound_link_candidates(db_pool)

    assert candidates == ["media.acme-motors.com"]


async def test_register_and_validate_candidates_only_keeps_domains_with_a_valid_feed(db_pool):
    with patch(
        "carwatch.discovery.discover_feed_for_domain",
        new=AsyncMock(side_effect=lambda d: "https://good.com/rss" if d == "good.com" else None),
    ):
        stats = await register_and_validate_candidates(db_pool, ["good.com", "bad.com"], tier=1, logger=None)

    assert stats == {"attempted": 2, "registered": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT domain, status FROM sources")
        rows = await result.fetchall()
    assert rows == [("good.com", "probation")]


async def test_run_discovery_orchestrates_both_heuristics(db_pool):
    with patch(
        "carwatch.discovery.find_scoop_domain_candidates", new=AsyncMock(return_value=["a.com"])
    ), patch(
        "carwatch.discovery.find_outbound_link_candidates", new=AsyncMock(return_value=["media.b.com"])
    ), patch(
        "carwatch.discovery.discover_feed_for_domain", new=AsyncMock(return_value="https://x/rss")
    ):
        stats = await run_discovery(db_pool, logger=None)

    assert stats["total_registered"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_discovery.py -v`
Expected: FAIL — `carwatch.discovery` doesn't exist.

- [ ] **Step 4: Implement `discovery.py`**

```python
"""src/carwatch/discovery.py"""
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from carwatch.probe import discover_feed_for_domain

OUTBOUND_LINK_PATTERNS = ("media.", "press.", "newsroom.", ".presse")


async def find_scoop_domain_candidates(pool) -> list[str]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT DISTINCT ri.url FROM event_sources es "
            "JOIN raw_items ri ON ri.id = es.item_id "
            "JOIN sources s ON s.id = es.source_id "
            "WHERE s.tier = 4 "
            "AND es.seen_at = (SELECT min(seen_at) FROM event_sources es2 WHERE es2.event_id = es.event_id)"
        )
        urls = [r[0] for r in await result.fetchall()]
        existing_result = await conn.execute("SELECT DISTINCT domain FROM sources")
        existing_domains = {r[0] for r in await existing_result.fetchall()}

    candidates = set()
    for url in urls:
        domain = urlsplit(url).netloc.lower()
        if domain and domain != "news.google.com" and domain not in existing_domains:
            candidates.add(domain)
    return sorted(candidates)


async def find_outbound_link_candidates(pool) -> list[str]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT ri.body FROM raw_items ri JOIN sources s ON s.id = ri.source_id "
            "WHERE s.tier = 3 AND ri.body IS NOT NULL"
        )
        bodies = [r[0] for r in await result.fetchall()]
        existing_result = await conn.execute("SELECT DISTINCT domain FROM sources")
        existing_domains = {r[0] for r in await existing_result.fetchall()}

    candidates = set()
    for body in bodies:
        tree = HTMLParser(body)
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            if not href.startswith("http"):
                continue
            hostname = urlsplit(href).netloc.lower()
            if not hostname or hostname in existing_domains:
                continue
            if any(hostname.startswith(p) or f".{p}" in hostname for p in OUTBOUND_LINK_PATTERNS):
                candidates.add(hostname)
    return sorted(candidates)


async def register_and_validate_candidates(pool, domains: list[str], tier: int, logger) -> dict:
    registered = 0
    for domain in domains:
        feed_url = await discover_feed_for_domain(domain)
        if not feed_url:
            if logger is not None:
                logger.info("discovery.candidate_rejected", domain=domain)
            continue
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status, probation_since) "
                "VALUES (%s, %s, 'rss', %s, 'probation', now()) ON CONFLICT (feed_url) DO NOTHING",
                (domain, feed_url, tier),
            )
        registered += 1
    return {"attempted": len(domains), "registered": registered}


async def run_discovery(pool, logger) -> dict:
    scoop_domains = await find_scoop_domain_candidates(pool)
    outbound_domains = await find_outbound_link_candidates(pool)

    scoop_stats = await register_and_validate_candidates(pool, scoop_domains, tier=3, logger=logger)
    outbound_stats = await register_and_validate_candidates(pool, outbound_domains, tier=1, logger=logger)

    stats = {
        "scoop_candidates": scoop_stats,
        "outbound_candidates": outbound_stats,
        "total_registered": scoop_stats["registered"] + outbound_stats["registered"],
    }
    if logger is not None:
        logger.info("discovery.run", **stats)
    return stats
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_discovery.py tests/test_probe.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add src/carwatch/discovery.py src/carwatch/probe.py tests/test_discovery.py
git commit -m "feat(carwatch): add continuous source discovery (scoop reverse-lookup + outbound links)"
```

---

### Task 5: `daily_stats.py` + wire `curate`/`discover`/`--confirm-retirement`/cost cap into `cli.py`

**Files:**
- Create: `agents/carwatch/src/carwatch/daily_stats.py`
- Modify: `agents/carwatch/src/carwatch/cli.py`
- Test: `agents/carwatch/tests/test_daily_stats.py`
- Test: `agents/carwatch/tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3), `run_curate` (Task 3), `run_discovery` (Task 4), `month_to_date_cost_usd` (Task 2).
- Produces: `async def aggregate_daily_stats(pool, day: date | None = None) -> dict` — upserts one `daily_stats` row for `day` (default today, UTC). **Approximation, stated plainly:** `raw_items`/`launch_events` have no per-stage timestamp columns (`classified_at`, `extracted_at`, `published_at`) — only `fetched_at`, `first_seen_at`, `updated_at`. Since this pipeline runs the whole `weekly-run` in one sitting, bucketing by those existing timestamps is accurate in practice; `llm_calls`/`llm_tokens_*`/`llm_cost_usd` are exact (`llm_usage.called_at` is a real per-call timestamp). `sources_active`/`sources_blocked` are a snapshot at aggregation time, not day-scoped.
- Produces: new `cli.py` commands: `curate`, `discover`, and `--confirm-retirement <id>` on the existing `curate` command (`carwatch curate --confirm-retirement 42` applies one retirement instead of running the full metrics/transitions pass).
- Produces: updated `stats` command reading `daily_stats` (last 7 rows) and `month_to_date_cost_usd`, in addition to the Fase 1 source/raw_items counts.
- Produces: `weekly-run` extended to call `run_curate` and `run_discovery` after `publish`, and `aggregate_daily_stats` last.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_daily_stats.py"""
from datetime import date, datetime, timezone

from carwatch.cost import record_llm_usage
from carwatch.daily_stats import aggregate_daily_stats


async def test_aggregate_daily_stats_counts_todays_activity(db_pool):
    today = datetime.now(timezone.utc)
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, fetched_at) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't', 'extracted', %s)",
            (source_id, today),
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published, first_seen_at) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, TRUE, %s)",
            (today,),
        )
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1000, 500, 0.0035)

    stats = await aggregate_daily_stats(db_pool, day=today.date())

    assert stats["items_ingested"] == 1
    assert stats["items_extracted"] == 1
    assert stats["events_created"] == 1
    assert stats["llm_calls"] == 1
    assert abs(stats["llm_cost_usd"] - 0.0035) < 1e-6

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT items_ingested FROM daily_stats WHERE day = %s", (today.date(),))
        assert (await result.fetchone())[0] == 1
```

```python
# tests/test_cli.py — append
def test_help_lists_fase3_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("curate", "discover"):
        assert command in result.output


def test_curate_confirm_retirement_flag(db_pool):
    result = runner.invoke(app, ["curate", "--confirm-retirement", "1"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_daily_stats.py -v`
Expected: FAIL — `carwatch.daily_stats` doesn't exist.

- [ ] **Step 3: Implement `daily_stats.py`**

```python
"""src/carwatch/daily_stats.py"""
from datetime import date, datetime, timedelta, timezone


async def aggregate_daily_stats(pool, day: date | None = None) -> dict:
    day = day or datetime.now(timezone.utc).date()
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT count(*), "
            "count(*) FILTER (WHERE classified->>'is_launch' = 'true'), "
            "count(*) FILTER (WHERE status = 'extracted') "
            "FROM raw_items WHERE fetched_at >= %s AND fetched_at < %s",
            (day_start, day_end),
        )
        items_ingested, items_approved, items_extracted = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*) FILTER (WHERE first_seen_at >= %s AND first_seen_at < %s), "
            "count(*) FILTER (WHERE published = TRUE AND updated_at >= %s AND updated_at < %s) "
            "FROM launch_events",
            (day_start, day_end, day_start, day_end),
        )
        events_created, events_published = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), "
            "COALESCE(sum(cost_usd), 0) FROM llm_usage WHERE called_at >= %s AND called_at < %s",
            (day_start, day_end),
        )
        llm_calls, llm_tokens_in, llm_tokens_out, llm_cost_usd = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*) FILTER (WHERE status = 'active'), "
            "count(*) FILTER (WHERE status = 'blocked') FROM sources"
        )
        sources_active, sources_blocked = await result.fetchone()

        stats = {
            "items_ingested": items_ingested,
            "items_approved": items_approved,
            "items_extracted": items_extracted,
            "events_created": events_created,
            "events_published": events_published,
            "llm_calls": llm_calls,
            "llm_tokens_in": llm_tokens_in,
            "llm_tokens_out": llm_tokens_out,
            "llm_cost_usd": float(llm_cost_usd),
            "sources_active": sources_active,
            "sources_blocked": sources_blocked,
        }

        await conn.execute(
            "INSERT INTO daily_stats (day, items_ingested, items_approved, items_extracted, "
            "events_created, events_published, llm_calls, llm_tokens_in, llm_tokens_out, "
            "llm_cost_usd, sources_active, sources_blocked, computed_at) "
            "VALUES (%(day)s, %(items_ingested)s, %(items_approved)s, %(items_extracted)s, "
            "%(events_created)s, %(events_published)s, %(llm_calls)s, %(llm_tokens_in)s, "
            "%(llm_tokens_out)s, %(llm_cost_usd)s, %(sources_active)s, %(sources_blocked)s, now()) "
            "ON CONFLICT (day) DO UPDATE SET "
            "items_ingested = EXCLUDED.items_ingested, items_approved = EXCLUDED.items_approved, "
            "items_extracted = EXCLUDED.items_extracted, events_created = EXCLUDED.events_created, "
            "events_published = EXCLUDED.events_published, llm_calls = EXCLUDED.llm_calls, "
            "llm_tokens_in = EXCLUDED.llm_tokens_in, llm_tokens_out = EXCLUDED.llm_tokens_out, "
            "llm_cost_usd = EXCLUDED.llm_cost_usd, sources_active = EXCLUDED.sources_active, "
            "sources_blocked = EXCLUDED.sources_blocked, computed_at = now()",
            {**stats, "day": day},
        )

    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_daily_stats.py -v`
Expected: PASS

- [ ] **Step 5: Update `cli.py`**

```python
# src/carwatch/cli.py — add imports
from carwatch.curate import confirm_retirement, run_curate
from carwatch.daily_stats import aggregate_daily_stats
from carwatch.discovery import run_discovery
from carwatch.cost import month_to_date_cost_usd


@app.command()
def curate(confirm_retirement_id: int = typer.Option(None, "--confirm-retirement")):
    async def _run():
        pool = get_pool()
        if confirm_retirement_id is not None:
            await confirm_retirement(pool, confirm_retirement_id)
            await close_pool()
            return {"confirmed_retirement": confirm_retirement_id}
        logger = _logger()
        settings = get_settings()
        result = await run_curate(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
        await close_pool()
        return result

    typer.echo(asyncio.run(_run()))


@app.command()
def discover():
    async def _run():
        logger = _logger()
        stats = await run_discovery(get_pool(), logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def stats():
    async def _run():
        pool = get_pool()
        async with pool.connection() as conn:
            result = await conn.execute("SELECT status, count(*) FROM sources GROUP BY status")
            sources_by_status = dict(await result.fetchall())
            result = await conn.execute("SELECT status, count(*) FROM raw_items GROUP BY status")
            items_by_status = dict(await result.fetchall())
            result = await conn.execute(
                "SELECT day, items_ingested, events_created, llm_cost_usd "
                "FROM daily_stats ORDER BY day DESC LIMIT 7"
            )
            recent_days = await result.fetchall()
        month_cost = await month_to_date_cost_usd(pool)
        await close_pool()
        return {
            "sources": sources_by_status,
            "raw_items": items_by_status,
            "recent_days": recent_days,
            "month_to_date_cost_usd": month_cost,
        }

    typer.echo(asyncio.run(_run()))


@app.command(name="weekly-run")
def weekly_run():
    """ingest -> prefilter -> classify -> extract -> publish -> curate -> discover -> daily_stats."""

    async def _run():
        logger = _logger()
        pool = get_pool()
        settings = get_settings()
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
        keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")

        await run_migrations(pool, MIGRATIONS_DIR)
        ingest_stats = await run_ingest(pool, logger)
        prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
        classify_stats = await run_classify(pool, logger, limit=200)
        extract_stats = await run_extract(pool, logger, limit=100)
        publish_stats = await publish_pending_events(
            pool, settings.telegram_bot_token, settings.telegram_chat_id, logger
        )
        await write_atom_feed(pool, Path(settings.atom_feed_path), settings.atom_feed_url)
        curate_stats = await run_curate(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
        discover_stats = await run_discovery(pool, logger)
        daily_stats = await aggregate_daily_stats(pool)

        await close_pool()
        return {
            "ingest": ingest_stats, "prefilter": prefilter_stats, "classify": classify_stats,
            "extract": extract_stats, "publish": publish_stats, "curate": curate_stats,
            "discover": discover_stats, "daily_stats": daily_stats,
        }

    result = asyncio.run(_run())
    typer.echo(result)
    if result["publish"]["pending"] > 0 and result["publish"]["sent"] == 0:
        raise typer.Exit(code=1)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cli.py tests/test_daily_stats.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add src/carwatch/daily_stats.py src/carwatch/cli.py tests/test_daily_stats.py tests/test_cli.py
git commit -m "feat(carwatch): add daily_stats aggregation, wire curate/discover into weekly-run"
```

---

### Task 6: Fase 3 end-to-end test + acceptance checklist + "definição de pronto" tracking

**Files:**
- Create: `agents/carwatch/tests/test_e2e_fase3.py`

**Interfaces:**
- Consumes: the full `weekly-run` CLI command.

- [ ] **Step 1: Write the end-to-end test**

```python
"""tests/test_e2e_fase3.py"""
from unittest.mock import AsyncMock, patch

import httpx
import respx
from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()


@respx.mock
async def test_weekly_run_completes_through_curate_discover_and_daily_stats(db_pool):
    respx.get("https://x.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://x.com/feed.xml").mock(return_value=httpx.Response(200, text=(
        "<?xml version='1.0'?><rss><channel></channel></rss>"  # empty feed: no items this run
    )))
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed.xml', 'rss', 1, 'active')"
        )

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=("[]", {"tokens_in": 0, "tokens_out": 0}))):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output
    async with db_pool.connection() as conn:
        result_row = await (await conn.execute("SELECT count(*) FROM daily_stats")).fetchone()
    assert result_row[0] == 1  # aggregate_daily_stats ran and wrote today's row
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd agents/carwatch && python3 -m pytest tests/test_e2e_fase3.py -v`
Expected: PASS once Tasks 1–5 are in place.

- [ ] **Step 3: Run the full test suite one more time**

Run: `cd agents/carwatch && python3 -m pytest -v`
Expected: all PASS — this is the complete three-phase test suite.

- [ ] **Step 4: Confirm every SPEC.md §19 Fase 3 bullet has a home**

| SPEC.md §19 Fase 3 criterion | Verified by |
|---|---|
| `curate` transiciona status corretamente sobre dados sintéticos | Fase 3 Task 3 (`test_apply_transitions_*`) |
| `discovery` identifica ≥3 candidatos válidos em 30d de dados reais | Manual, live check — run `carwatch discover` weekly for a month against the real deployment and count registrations; not automatable without 30 days of real ingest history |
| Alerta de marca silenciosa dispara em teste | Fase 3 Task 3 (`test_find_stale_brands_flags_brand_with_no_recent_events`) |
| Alerta de custo dispara ao ultrapassar o teto | Fase 3 Task 2 (`test_is_extraction_cost_capped_true_above_30_usd`) |

- [ ] **Step 5: Track SPEC.md §22 "Definição de pronto" — a 14-day operational milestone, not a test**

These five criteria can only be evaluated after CarWatch has run for two consecutive weekly cycles in production; write them into `agents/carwatch/README.md`'s existing "Riscos operacionais conhecidos" section (added in Fase 1 Task 17) as a standing checklist an operator revisits after week 2:

```markdown
## Definição de pronto (SPEC.md §22) — revisar após 2 execuções semanais

- [ ] Detecta ≥90% dos lançamentos das 40 marcas principais (checar manualmente contra Motor1/Autocar)
- [ ] Taxa de duplicata no Telegram < 5%
- [ ] Custo LLM < US$15/mês (`carwatch stats` → `month_to_date_cost_usd`)
- [ ] Nenhum domínio em `status='blocked'` por culpa do fetcher (não por bloqueio real do site)
- [ ] Intervenção manual ≤ 30 min/semana (tempo gasto em `carwatch review` + confirmar aposentadorias)
```

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add tests/test_e2e_fase3.py README.md
git commit -m "test(carwatch): add Fase 3 end-to-end test and operational readiness checklist"
```

---

## Self-Review

**Spec coverage:** SPEC.md §13 (curate — Task 3, with the documented retirement-confirmation deviation), §14 (discovery — Task 4, with the documented heuristic 1+3 consolidation), §18 (observability + cost cap — Tasks 1/2/5, with pricing looked up live rather than guessed), §19 Fase 3 acceptance (Task 6), §22 "definição de pronto" (Task 6, tracked as an operational checklist rather than an automated test, since it's inherently a 14-day-of-production measurement).

**Placeholder scan:** no "TBD"/"TODO"; every step has real code or a real command with an expected result. The one genuinely non-automatable item (discovery's "≥3 candidates in 30 real days") is labeled as a manual/live check, not left vague.

**Type consistency:** `pending_retirements`/`llm_usage`/`daily_stats` column names used across Tasks 2/3/5 all trace to Task 1's migration. `apply_transitions`'s return dict shape (`{"promoted": [...], "demoted": [...], "retirement_candidates": [...]}`) matches exactly what `send_curation_digest` (Task 3) and the `run_curate` composite (Task 3) consume — no task assumes a different key name. `run_extract`'s new `cost_capped` key (Task 2) doesn't break Fase 2's `weekly-run` failure-exit check (`result["publish"]["sent"] == 0`), since it's a different dict entirely.
