# CarWatch Fase 2 — Estrutura e Qualidade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `extract`, `dedupe`, `launch_events`, the full Telegram formatter, the Atom feed, and the manual `review` command on top of the Fase 1 backbone — turning classified `raw_items` into deduplicated, structured `launch_events` that get published once (not once per duplicate article).

**Architecture:** Unchanged from Fase 1. New pieces slot into the existing `weekly-run` pipeline: `extract` runs after `classify`, and for every successfully extracted item calls into `dedupe.py` synchronously (there is no separate `dedupe` CLI command — SPEC.md §17's CLI table has none; dedupe is part of what `extract` does with each result, matching the SPEC.md §3 architecture diagram's `extract → dedupe` arrow).

**Tech Stack:** Adds `sentence-transformers` (^3.0, `paraphrase-multilingual-MiniLM-L12-v2`, 384 dims) to the Fase 1 stack.

**Spec:** `agents/carwatch/SPEC.md` §5.4, §11, §12, §15 (full formatter), §19 (Fase 2 acceptance), §20 (fixtures) + `agents/carwatch/DESIGN.md`. **Depends on** `docs/superpowers/plans/2026-08-22-carwatch-fase1-backbone.md` being fully implemented and merged first — every Fase 1 module is a direct dependency here.

## Global Constraints

- All Fase 1 Global Constraints still apply (single fetcher egress, no `requests`, no intra-domain parallelism, no 403 retry, `temperature=0`, UTC storage).
- Migration numbering: this phase's schema migration is `004_events.sql`, **not** `003_events.sql` as sketched in SPEC.md §4 — Fase 1 already used `003_source_incidents.sql` for breaker state (see Fase 1 plan, Task 6).
- Article text is truncated to **6000 tokens** before the extract LLM call (SPEC.md §11.3); this plan approximates tokens as `len(text) // 4` (documented approximation, not a real tokenizer — SPEC.md doesn't mandate one).
- `is_new_generation` defaults to `false` whenever the extract model is unsure (SPEC.md §21.6 — this is where the LLM errs most; facelifts must not silently become "new generation").
- Dedupe fuzzy match requires **both** `similarity(model_a, model_b) >= 0.55` (via `pg_trgm`) **and** cosine similarity `>= 0.86` on the embedding — SPEC.md §12 is explicit that either alone produces false positives (sibling models like Seal 05 vs Seal 06).
- Stage progression order (SPEC.md §12 Etapa 4), lowest to highest: `spy < teaser < concept < world_premiere < specs_release < pricing < on_sale < market_launch`.
- Never invent specs: numeric fields absent from the source article must come back `null` from the extract LLM, never a guessed value (SPEC.md §21.5) — this is asserted directly in tests, not just hoped for.
- Highlights are written in `pt-BR` regardless of the article's source language; every other extracted field is in English (SPEC.md §11 system prompt).

---

### Task 1: `migrations/004_events.sql` — `launch_events` + `event_sources`

**Files:**
- Create: `agents/carwatch/migrations/004_events.sql`
- Test: `agents/carwatch/tests/test_migrations_events.py`

**Interfaces:**
- Consumes: `run_migrations` (Fase 1 Task 3).
- Produces: the `launch_events` and `event_sources` tables and the `launch_stage` Postgres enum, consumed by every other task in this plan.

- [ ] **Step 1: Write `migrations/004_events.sql`** (copied verbatim from SPEC.md §5.4)

```sql
CREATE TYPE launch_stage AS ENUM
  ('spy','teaser','world_premiere','specs_release',
   'pricing','on_sale','market_launch','concept');

CREATE TABLE launch_events (
  id              BIGSERIAL PRIMARY KEY,
  dedupe_key      TEXT NOT NULL,
  brand           TEXT NOT NULL,
  brand_group     TEXT,
  model           TEXT NOT NULL,
  model_slug      TEXT NOT NULL,
  generation      TEXT,
  body_type       TEXT,
  stage           launch_stage NOT NULL,
  is_new_generation BOOLEAN,
  markets         TEXT[] DEFAULT '{}',
  global_debut    BOOLEAN DEFAULT false,
  event_date      DATE,
  sales_start     TEXT,
  powertrain      JSONB,
  price           JSONB,
  highlights      TEXT[],
  embedding       vector(384),
  confidence      NUMERIC(3,2),
  first_seen_at   TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),
  published       BOOLEAN DEFAULT false,
  review_status   TEXT DEFAULT 'pending',
  previous_event_id BIGINT REFERENCES launch_events(id)
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

**Deviation from SPEC.md §5.4, noted explicitly:** added `previous_event_id BIGINT REFERENCES launch_events(id)` — SPEC.md §12 Etapa 4 says stage progression "cria **novo** `launch_event` e vincula ao anterior" but the table in §5.4 has no column to hold that link. Without it, "vincula ao anterior" has nowhere to be stored.

- [ ] **Step 2: Write the test**

```python
"""tests/test_migrations_events.py"""
async def test_launch_events_and_event_sources_tables_exist(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT to_regclass('public.launch_events')")
        assert (await result.fetchone())[0] == "launch_events"
        result = await conn.execute("SELECT to_regclass('public.event_sources')")
        assert (await result.fetchone())[0] == "event_sources"


async def test_launch_stage_enum_has_all_eight_values(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT unnest(enum_range(NULL::launch_stage))::text"
        )
        values = {row[0] for row in await result.fetchall()}
    assert values == {
        "spy", "teaser", "world_premiere", "specs_release",
        "pricing", "on_sale", "market_launch", "concept",
    }
```

**Note:** `conftest.py`'s `db_pool` fixture TRUNCATEs `raw_items, source_metrics, sources` after each test (Fase 1 Task 3) — extend that list to include `launch_events, event_sources, source_incidents` now that they exist, or later tests in this phase will leak state across test functions.

- [ ] **Step 3: Update `conftest.py`'s truncate list**

```python
# tests/conftest.py — change the TRUNCATE line inside db_pool to:
        await conn.execute(
            "TRUNCATE raw_items, source_metrics, sources, launch_events, "
            "event_sources, source_incidents RESTART IDENTITY CASCADE"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_migrations_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add migrations/004_events.sql tests/test_migrations_events.py tests/conftest.py
git commit -m "feat(carwatch): add launch_events and event_sources schema"
```

---

### Task 2: `embeddings.py` — multilingual sentence embeddings

**Files:**
- Create: `agents/carwatch/src/carwatch/embeddings.py`
- Test: `agents/carwatch/tests/test_embeddings.py`
- Modify: `agents/carwatch/pyproject.toml` — add `sentence-transformers>=3.0,<4.0` to `dependencies`.

**Interfaces:**
- Produces: `def embed_text(text: str) -> list[float]` — always returns a 384-dimensional vector; loads `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` lazily into a module-level singleton on first call.
- Consumes: nothing.

**Note on test cost:** this downloads a ~470MB model from Hugging Face on first run (cached in `~/.cache/huggingface` afterward). This is the one test module in the whole project that needs real network access to a non-carwatch-controlled host — mark it explicitly so it can be skipped in fully offline environments.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`'s `dependencies` list, adding:

```toml
    "sentence-transformers>=3.0,<4.0",
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_embeddings.py"""
import pytest

from carwatch.embeddings import embed_text

pytestmark = pytest.mark.embeddings  # register in pyproject.toml's pytest markers if not already


def test_embed_text_returns_384_dimensions():
    vector = embed_text("BYD Seal 06 world premiere")
    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)


def test_embed_text_is_deterministic_for_same_input():
    a = embed_text("BYD Seal 06 world premiere")
    b = embed_text("BYD Seal 06 world premiere")
    assert a == b


def test_embed_text_multilingual_inputs_are_close_in_semantic_space():
    import math

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b)

    en = embed_text("BYD Seal 06 world premiere")
    zh = embed_text("比亚迪海豹06首发")
    unrelated = embed_text("quarterly earnings report layoffs")

    assert cosine(en, zh) > cosine(en, unrelated)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_embeddings.py -v`
Expected: FAIL — `carwatch.embeddings` doesn't exist.

- [ ] **Step 4: Implement `embeddings.py`**

```python
"""src/carwatch/embeddings.py"""
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    vector = _get_model().encode(text, normalize_embeddings=False)
    return vector.tolist()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_embeddings.py -v`
Expected: PASS (first run is slow — downloading the model)

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add pyproject.toml src/carwatch/embeddings.py tests/test_embeddings.py
git commit -m "feat(carwatch): add multilingual sentence embeddings for dedupe"
```

---

### Task 3: Extend `models.py` — `Powertrain`, `Price`, `ExtractedEvent`

**Files:**
- Modify: `agents/carwatch/src/carwatch/models.py` (append; do not touch the Fase 1 classes)
- Test: `agents/carwatch/tests/test_models_extract.py`

**Interfaces:**
- Produces: `class Powertrain(BaseModel)` — `type: Literal["bev","phev","hev","ice","fcev"]`, and optional `power_hp`, `torque_nm`, `battery_kwh`, `range_km`, `range_cycle: Literal["WLTP","CLTC","EPA"] | None`, `drivetrain: Literal["fwd","rwd","awd"] | None`, `zero_to_100_s: float | None`.
- Produces: `class Price(BaseModel)` — `amount: float | None`, `currency: str | None`, `status: Literal["official","estimated","starting_from"] | None`.
- Produces: `class ExtractedEvent(BaseModel)` — `brand: str`, `model: str`, `generation: str | None`, `body_type: str | None`, `stage: LaunchStage`, `is_new_generation: bool = False`, `markets: list[str] = []`, `global_debut: bool = False`, `event_date: date | None`, `sales_start: str | None`, `powertrain: Powertrain | None`, `price: Price | None`, `highlights: list[str]`, `confidence: float`. **`is_new_generation` defaults to `False`** (SPEC.md §21.6 — this is a Python-level safety net in addition to the prompt instruction, so a model that omits the field never silently becomes "new generation").
- Consumes: `LaunchStage` (already in `models.py`, Fase 1 Task 9).

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_models_extract.py"""
import pytest
from pydantic import ValidationError

from carwatch.models import ExtractedEvent, Powertrain, Price


def test_powertrain_requires_only_type():
    pt = Powertrain(type="bev")
    assert pt.power_hp is None
    assert pt.range_cycle is None


def test_powertrain_rejects_invalid_type():
    with pytest.raises(ValidationError):
        Powertrain(type="diesel")


def test_price_all_fields_optional():
    price = Price()
    assert price.amount is None


def test_extracted_event_defaults_is_new_generation_to_false():
    event = ExtractedEvent(
        brand="BYD",
        model="Seal 06",
        generation=None,
        body_type="sedan",
        stage="world_premiere",
        markets=["CN"],
        event_date=None,
        sales_start=None,
        powertrain=None,
        price=None,
        highlights=["Estreia mundial do novo sedã elétrico"],
        confidence=0.9,
    )
    assert event.is_new_generation is False


def test_extracted_event_requires_brand_and_model():
    with pytest.raises(ValidationError):
        ExtractedEvent(
            model="Seal 06",
            stage="world_premiere",
            highlights=[],
            confidence=0.9,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_models_extract.py -v`
Expected: FAIL — `Powertrain`/`Price`/`ExtractedEvent` don't exist.

- [ ] **Step 3: Append to `models.py`**

```python
# src/carwatch/models.py — append below the existing Fase 1 classes
from datetime import date
from typing import Literal


class Powertrain(BaseModel):
    type: Literal["bev", "phev", "hev", "ice", "fcev"]
    power_hp: int | None = None
    torque_nm: int | None = None
    battery_kwh: float | None = None
    range_km: int | None = None
    range_cycle: Literal["WLTP", "CLTC", "EPA"] | None = None
    drivetrain: Literal["fwd", "rwd", "awd"] | None = None
    zero_to_100_s: float | None = None


class Price(BaseModel):
    amount: float | None = None
    currency: str | None = None
    status: Literal["official", "estimated", "starting_from"] | None = None


class ExtractedEvent(BaseModel):
    brand: str
    model: str
    generation: str | None = None
    body_type: str | None = None
    stage: LaunchStage
    is_new_generation: bool = False
    markets: list[str] = []
    global_debut: bool = False
    event_date: date | None = None
    sales_start: str | None = None
    powertrain: Powertrain | None = None
    price: Price | None = None
    highlights: list[str] = []
    confidence: float
```

(Move the `from datetime import date` and `from typing import Literal` imports to the top of the file alongside the existing `from enum import Enum` / `from pathlib import Path` — don't leave a second import block mid-file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_models_extract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/models.py tests/test_models_extract.py
git commit -m "feat(carwatch): add Powertrain/Price/ExtractedEvent schemas"
```

---

### Task 4: `dedupe.py` — the two-stage match/merge/progression engine

**Files:**
- Create: `agents/carwatch/src/carwatch/dedupe.py`
- Modify: `agents/carwatch/src/carwatch/db.py` — register the `pgvector` adapter on every pooled connection.
- Modify: `agents/carwatch/pyproject.toml` — add `pgvector>=0.3,<0.4` to `dependencies`.
- Test: `agents/carwatch/tests/test_dedupe.py`

**Interfaces:**
- Consumes: `embed_text` (Task 2), `ExtractedEvent` (Task 3), `AsyncConnectionPool` (Fase 1 Task 3).
- Produces: `def slug(text: str) -> str`.
- Produces: `def compute_dedupe_key(brand: str, model: str, markets: list[str], stage: str) -> str`.
- Produces: `STAGE_ORDER: list[str]` — `["spy", "teaser", "concept", "world_premiere", "specs_release", "pricing", "on_sale", "market_launch"]` (SPEC.md §12 Etapa 4 order — **not** the DB enum's declaration order in SPEC.md §5.4, which lists `concept` last; that's just enum member order and irrelevant to progression comparisons).
- Produces: `async def process_extracted_event(pool, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, source_tier: int) -> int` — the single entrypoint `extract.py` (Task 5) calls per successfully extracted item. Returns the resulting `launch_events.id` (new or matched).

**Matching order inside `process_extracted_event` (this plan's synthesis of SPEC.md §12's four numbered etapas into one decision sequence):**
1. Exact `dedupe_key` match within 14 days → merge (Etapa 3).
2. No exact match → fuzzy match (same brand + stage, `similarity(model) >= 0.55` AND cosine `>= 0.86`, 14-day window) → merge (Etapa 3).
3. No match at either stage-preserving check → look for a prior event with the **same** brand + `model_slug` but an **earlier** stage in `STAGE_ORDER` (no time window — SPEC.md doesn't bound how long a spy-shot-to-market-launch arc can take) → stage progression: create a **new** row with `previous_event_id` set (Etapa 4).
4. Nothing matches at all → create a new standalone event.

**Deviation from SPEC.md, noted explicitly:** `previous_event_id` (added to the schema in Task 1) is what "vincula ao anterior" (§12 Etapa 4) is stored in — SPEC.md's own `launch_events` table in §5.4 has no such column.

- [ ] **Step 1: Add the `pgvector` dependency and register it on the pool**

Edit `pyproject.toml`'s `dependencies`, adding:

```toml
    "pgvector>=0.3,<0.4",
```

Modify `src/carwatch/db.py`'s `get_pool()`:

```python
# src/carwatch/db.py — replace get_pool() with:
from pgvector.psycopg import register_vector_async


async def _configure_connection(conn) -> None:
    await register_vector_async(conn)


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=10,
            open=False,
            configure=_configure_connection,
        )
    return _pool
```

(This lets any later code bind a Python `list[float]` directly to a `vector` column parameter, and lets `db_pool` in `conftest.py` — which builds its own separate `AsyncConnectionPool` for tests — pick this up too: update `conftest.py`'s `db_pool` fixture to pass `configure=_configure_connection` as well, importing it from `carwatch.db`.)

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_dedupe.py"""
from datetime import date

from carwatch.dedupe import STAGE_ORDER, compute_dedupe_key, process_extracted_event, slug
from carwatch.embeddings import embed_text
from carwatch.models import ExtractedEvent


def test_slug_removes_accents_punctuation_and_collapses_spaces():
    assert slug("Seal 06 DM-i!") == "seal-06-dm-i"
    assert slug("Citroën C3") == "citroen-c3"


def test_compute_dedupe_key_sorts_markets_and_defaults_to_global():
    key = compute_dedupe_key("BYD", "Seal 06", ["US", "cn"], "world_premiere")
    assert key == "byd|seal-06|cn,us|world_premiere"
    assert compute_dedupe_key("BYD", "Seal 06", [], "world_premiere") == "byd|seal-06|global|world_premiere"


def test_stage_order_matches_spec_progression_order():
    assert STAGE_ORDER == [
        "spy", "teaser", "concept", "world_premiere",
        "specs_release", "pricing", "on_sale", "market_launch",
    ]


async def _make_extracted(**overrides) -> ExtractedEvent:
    defaults = dict(
        brand="BYD", model="Seal 06", generation=None, body_type="sedan",
        stage="world_premiere", markets=["CN"], event_date=date(2026, 1, 1),
        sales_start=None, powertrain=None, price=None,
        highlights=["Estreia mundial"], confidence=0.9,
    )
    defaults.update(overrides)
    return ExtractedEvent(**defaults)


async def _insert_source_and_item(db_pool, tier: int = 1):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', %s, 'rss', %s, 'active') RETURNING id",
            (f"https://x.com/feed-{tier}-{id(object())}", tier),
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://x.com/a', %s, 'title') RETURNING id",
            (source_id, f"hash-{id(object())}"),
        )
        item_id = (await item.fetchone())[0]
    return source_id, item_id


async def test_first_occurrence_creates_new_standalone_event(db_pool):
    extracted = await _make_extracted()
    source_id, item_id = await _insert_source_and_item(db_pool)

    event_id = await process_extracted_event(
        db_pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT brand, model, stage, previous_event_id FROM launch_events WHERE id = %s",
            (event_id,),
        )
        row = await result.fetchone()
    assert row == ("BYD", "Seal 06", "world_premiere", None)


async def test_exact_duplicate_merges_instead_of_creating_new_row(db_pool):
    first = await _make_extracted()
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    first_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=3
    )

    second = await _make_extracted(price={"amount": 109800, "currency": "CNY", "status": "official"})
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    second_id = await process_extracted_event(
        db_pool, second, source_id=source_id_b, raw_item_id=item_id_b, source_tier=3
    )

    assert second_id == first_id
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1
        result = await conn.execute("SELECT count(*) FROM event_sources WHERE event_id = %s", (first_id,))
        assert (await result.fetchone())[0] == 2
        result = await conn.execute("SELECT price FROM launch_events WHERE id = %s", (first_id,))
        assert (await result.fetchone())[0]["amount"] == 109800  # null field enriched


async def test_sibling_models_do_not_collapse(db_pool):
    seal_05 = await _make_extracted(model="Seal 05")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    id_a = await process_extracted_event(
        db_pool, seal_05, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    seal_06 = await _make_extracted(model="Seal 06")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    id_b = await process_extracted_event(
        db_pool, seal_06, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    assert id_a != id_b


async def test_tier1_source_overwrites_conflicting_fields_from_lower_tier(db_pool):
    first = await _make_extracted(body_type="sedan")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool, tier=3)
    event_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=3
    )

    corrected = await _make_extracted(body_type="hatchback")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool, tier=1)
    await process_extracted_event(
        db_pool, corrected, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT body_type FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] == "hatchback"
        result = await conn.execute(
            "SELECT is_primary FROM event_sources WHERE event_id = %s AND source_id = %s",
            (event_id, source_id_b),
        )
        assert (await result.fetchone())[0] is True


async def test_stage_progression_creates_new_linked_event(db_pool):
    teaser = await _make_extracted(stage="teaser")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    teaser_id = await process_extracted_event(
        db_pool, teaser, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    premiere = await _make_extracted(stage="world_premiere")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    premiere_id = await process_extracted_event(
        db_pool, premiere, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    assert premiere_id != teaser_id
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT previous_event_id FROM launch_events WHERE id = %s", (premiere_id,)
        )
        assert (await result.fetchone())[0] == teaser_id
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_dedupe.py -v`
Expected: FAIL — `carwatch.dedupe` doesn't exist.

- [ ] **Step 4: Implement `dedupe.py`**

```python
"""src/carwatch/dedupe.py"""
import re
import unicodedata

from carwatch.embeddings import embed_text
from carwatch.models import ExtractedEvent

STAGE_ORDER = [
    "spy", "teaser", "concept", "world_premiere",
    "specs_release", "pricing", "on_sale", "market_launch",
]
EXACT_MATCH_WINDOW_DAYS = 14
FUZZY_MATCH_WINDOW_DAYS = 14
TRIGRAM_THRESHOLD = 0.55
COSINE_THRESHOLD = 0.86


def slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    lowered = without_accents.lower()
    cleaned = re.sub(r"[^a-z0-9\s-]", "", lowered)
    return re.sub(r"[\s-]+", "-", cleaned).strip("-")


def compute_dedupe_key(brand: str, model: str, markets: list[str], stage: str) -> str:
    market_part = ",".join(sorted(m.lower() for m in markets)) if markets else "global"
    return f"{slug(brand)}|{slug(model)}|{market_part}|{stage}"


def _embedding_text(extracted: ExtractedEvent) -> str:
    return f"{extracted.brand} {extracted.model} {extracted.generation or ''} {' '.join(extracted.highlights)}"


async def _find_exact_match(pool, dedupe_key: str) -> int | None:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM launch_events WHERE dedupe_key = %s "
            "AND first_seen_at > now() - make_interval(days => %s) "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (dedupe_key, EXACT_MATCH_WINDOW_DAYS),
        )
        row = await result.fetchone()
        return row[0] if row else None


async def _find_fuzzy_match(pool, brand: str, model: str, stage: str, embedding: list[float]) -> int | None:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM launch_events "
            "WHERE brand = %s AND stage = %s "
            "AND first_seen_at > now() - make_interval(days => %s) "
            "AND similarity(model, %s) >= %s "
            "AND 1 - (embedding <=> %s) >= %s "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (brand, stage, FUZZY_MATCH_WINDOW_DAYS, model, TRIGRAM_THRESHOLD, embedding, COSINE_THRESHOLD),
        )
        row = await result.fetchone()
        return row[0] if row else None


async def _find_earlier_stage_event(pool, brand: str, model_slug: str, stage: str) -> int | None:
    incoming_rank = STAGE_ORDER.index(stage)
    earlier_stages = STAGE_ORDER[:incoming_rank]
    if not earlier_stages:
        return None
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM launch_events "
            "WHERE brand = %s AND model_slug = %s AND stage = ANY(%s) "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (brand, model_slug, earlier_stages),
        )
        row = await result.fetchone()
        return row[0] if row else None


async def _insert_event_source(pool, event_id: int, item_id: int, source_id: int, is_primary: bool) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (event_id, item_id, source_id, is_primary),
        )


async def _create_new_event(
    pool, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, previous_event_id: int | None
) -> int:
    embedding = embed_text(_embedding_text(extracted))
    dedupe_key = compute_dedupe_key(extracted.brand, extracted.model, extracted.markets, extracted.stage.value)
    async with pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events "
            "(dedupe_key, brand, model, model_slug, generation, body_type, stage, "
            "is_new_generation, markets, global_debut, event_date, sales_start, "
            "powertrain, price, highlights, embedding, confidence, previous_event_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                dedupe_key, extracted.brand, extracted.model, slug(extracted.model),
                extracted.generation, extracted.body_type, extracted.stage.value,
                extracted.is_new_generation, extracted.markets, extracted.global_debut,
                extracted.event_date, extracted.sales_start,
                extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                extracted.price.model_dump_json() if extracted.price else None,
                extracted.highlights, embedding, extracted.confidence, previous_event_id,
            ),
        )
        event_id = (await result.fetchone())[0]
    await _insert_event_source(pool, event_id, raw_item_id, source_id, is_primary=True)
    return event_id


async def _merge_into_existing(
    pool, event_id: int, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, source_tier: int
) -> None:
    async with pool.connection() as conn:
        had_tier1_source = await conn.execute(
            "SELECT EXISTS (SELECT 1 FROM event_sources es JOIN sources s ON s.id = es.source_id "
            "WHERE es.event_id = %s AND s.tier = 1)",
            (event_id,),
        )
        already_has_tier1 = (await had_tier1_source.fetchone())[0]

        is_primary = source_tier == 1 and not already_has_tier1

        if is_primary:
            await conn.execute(
                "UPDATE launch_events SET body_type = %s, generation = %s, "
                "is_new_generation = %s, event_date = %s, sales_start = %s, "
                "powertrain = %s, price = %s, updated_at = now() WHERE id = %s",
                (
                    extracted.body_type, extracted.generation, extracted.is_new_generation,
                    extracted.event_date, extracted.sales_start,
                    extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                    extracted.price.model_dump_json() if extracted.price else None,
                    event_id,
                ),
            )
        else:
            await conn.execute(
                "UPDATE launch_events SET "
                "body_type = COALESCE(body_type, %s), generation = COALESCE(generation, %s), "
                "event_date = COALESCE(event_date, %s), sales_start = COALESCE(sales_start, %s), "
                "powertrain = COALESCE(powertrain, %s), price = COALESCE(price, %s), "
                "updated_at = now() WHERE id = %s",
                (
                    extracted.body_type, extracted.generation,
                    extracted.event_date, extracted.sales_start,
                    extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                    extracted.price.model_dump_json() if extracted.price else None,
                    event_id,
                ),
            )

    await _insert_event_source(pool, event_id, raw_item_id, source_id, is_primary=is_primary)


async def process_extracted_event(
    pool, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, source_tier: int
) -> int:
    dedupe_key = compute_dedupe_key(extracted.brand, extracted.model, extracted.markets, extracted.stage.value)

    exact_match = await _find_exact_match(pool, dedupe_key)
    if exact_match is not None:
        await _merge_into_existing(
            pool, exact_match, extracted, source_id=source_id, raw_item_id=raw_item_id, source_tier=source_tier
        )
        return exact_match

    embedding = embed_text(_embedding_text(extracted))
    fuzzy_match = await _find_fuzzy_match(pool, extracted.brand, extracted.model, extracted.stage.value, embedding)
    if fuzzy_match is not None:
        await _merge_into_existing(
            pool, fuzzy_match, extracted, source_id=source_id, raw_item_id=raw_item_id, source_tier=source_tier
        )
        return fuzzy_match

    previous_event_id = await _find_earlier_stage_event(
        pool, extracted.brand, slug(extracted.model), extracted.stage.value
    )
    return await _create_new_event(
        pool, extracted, source_id=source_id, raw_item_id=raw_item_id, previous_event_id=previous_event_id
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_dedupe.py -v`
Expected: PASS

- [ ] **Step 6: Run dedupe.py coverage check (SPEC.md §20: ≥90%)**

Run: `cd agents/carwatch && python3 -m pytest --cov=carwatch.dedupe --cov-report=term-missing tests/test_dedupe.py`
Expected: ≥90%. Add cases for any uncovered branch (e.g., the `already_has_tier1` COALESCE path) before moving on.

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add pyproject.toml src/carwatch/db.py src/carwatch/dedupe.py tests/test_dedupe.py tests/conftest.py
git commit -m "feat(carwatch): add two-stage dedupe engine with stage progression"
```

---

### Task 5: `llm/extract.py` — full-article extraction + retry + dedupe hookup

**Files:**
- Create: `agents/carwatch/src/carwatch/llm/extract.py`
- Test: `agents/carwatch/tests/test_extract.py`
- Test fixtures: `agents/carwatch/tests/fixtures/articles/simple_article.html`, `ld_json_article.html`

**Interfaces:**
- Consumes: `fetcher.fetch` (Fase 1 Task 7), `call_extract`-style client helper (new, alongside `llm/client.py`'s existing `call_classify`), `dedupe.process_extracted_event` (Task 4), `ExtractedEvent` (Task 3).
- Produces: `def extract_article_text(html: str) -> str` — ld+json `NewsArticle.articleBody` first (SPEC.md §11.2: "é mais limpo" implies it's preferred when present), else `<article>`, else `<main>`, else all `<p>` text concatenated.
- Produces: `def truncate_for_llm(text: str) -> str` — caps at `6000 * 4` characters (SPEC.md §11.3's 6000-token limit, approximated as 4 chars/token — no real tokenizer is pulled in for this).
- Produces: `async def call_extract(article_text: str) -> str` (added to `llm/client.py`, alongside `call_classify`).
- Produces: `def parse_extract_response(raw_text: str) -> ExtractedEvent | None`.
- Produces: `async def extract_one_item(pool, row: tuple, logger) -> str` — returns `"extracted"` or `"error"`.
- Produces: `async def run_extract(pool, logger, limit: int = 50) -> dict` — selects `raw_items` where `status='new' AND classified->>'is_launch'='true'`, joined to `sources` for `tier`; returns `{"in": int, "extracted": int, "error": int}`.

- [ ] **Step 1: Write the test fixtures**

```html
<!-- tests/fixtures/articles/simple_article.html -->
<html><body>
<article>
<p>BYD unveiled the all-new Seal 06 sedan today at a global event in Shenzhen.</p>
<p>The car is offered exclusively as a battery electric vehicle with 212 hp and a WLTP range of 520 km.</p>
<p>Pricing starts at 109,800 CNY and deliveries begin in the second quarter.</p>
</article>
</body></html>
```

```html
<!-- tests/fixtures/articles/ld_json_article.html -->
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle","articleBody":"BYD unveiled the Seal 06 today. The sedan is electric only and starts at 109800 CNY."}
</script>
</head><body><article><p>Different, messier body text that should be ignored.</p></article></body></html>
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_extract.py"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from carwatch.llm.extract import (
    extract_article_text,
    parse_extract_response,
    run_extract,
    truncate_for_llm,
)

FIXTURES = Path(__file__).parent / "fixtures" / "articles"


def test_extract_article_text_prefers_ld_json_when_present():
    html = (FIXTURES / "ld_json_article.html").read_text()
    text = extract_article_text(html)
    assert "109800 CNY" in text
    assert "messier" not in text


def test_extract_article_text_falls_back_to_article_tag():
    html = (FIXTURES / "simple_article.html").read_text()
    text = extract_article_text(html)
    assert "Shenzhen" in text
    assert "109,800 CNY" in text


def test_truncate_for_llm_caps_at_24000_chars():
    text = "x" * 30000
    assert len(truncate_for_llm(text)) == 24000


def test_parse_extract_response_accepts_well_formed_json():
    raw = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": "2026-Q2",
            "powertrain": {"type": "bev", "power_hp": 212, "range_km": 520, "range_cycle": "WLTP"},
            "price": {"amount": 109800, "currency": "CNY", "status": "official"},
            "highlights": ["Estreia mundial em Shenzhen"], "confidence": 0.9,
        }
    )
    event = parse_extract_response(raw)
    assert event is not None
    assert event.powertrain.power_hp == 212


def test_parse_extract_response_rejects_invalid_json():
    assert parse_extract_response("not json") is None


def test_parse_extract_response_never_invents_missing_numeric_fields():
    raw = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "teaser", "is_new_generation": False, "markets": [],
            "global_debut": False, "event_date": None, "sales_start": None,
            "powertrain": {"type": "bev"}, "price": None,
            "highlights": ["Teaser oficial divulgado"], "confidence": 0.6,
        }
    )
    event = parse_extract_response(raw)
    assert event.powertrain.power_hp is None
    assert event.price is None


async def test_run_extract_marks_success_as_extracted_and_calls_dedupe(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        classified = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.9})
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x.com/article', 'hash-1', 'BYD reveals Seal 06', 'new', %s) RETURNING id",
            (source_id, classified),
        )
        item_id = (await item.fetchone())[0]

    fake_extracted_json = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": None,
            "powertrain": None, "price": None, "highlights": ["Estreia mundial"], "confidence": 0.9,
        }
    )

    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": "x" * 1000, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=AsyncMock(return_value=fake_extracted_json)):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        assert (await result.fetchone())[0] == "extracted"
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1


async def test_run_extract_marks_unparseable_response_as_error_after_one_retry(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        classified = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.9})
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x.com/article', 'hash-1', 'BYD reveals Seal 06', 'new', %s) RETURNING id",
            (source_id, classified),
        )
        item_id = (await item.fetchone())[0]

    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": "x" * 1000, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=AsyncMock(return_value="not json, ever")):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 0, "error": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        assert (await result.fetchone())[0] == "error"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_extract.py -v`
Expected: FAIL — `carwatch.llm.extract` doesn't exist.

- [ ] **Step 4: Add `call_extract` to `llm/client.py`**

```python
# src/carwatch/llm/client.py — append
async def call_extract(system_prompt: str, article_text: str) -> str:
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": article_text}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
```

- [ ] **Step 5: Implement `llm/extract.py`**

```python
"""src/carwatch/llm/extract.py"""
import json
import re

from pydantic import ValidationError
from selectolax.parser import HTMLParser

from carwatch import dedupe, fetcher
from carwatch.llm.client import call_extract as _call_extract_raw
from carwatch.models import ExtractedEvent

MAX_CHARS = 6000 * 4  # approximate 4 chars/token (SPEC.md §11.3 caps at 6000 tokens)
MIN_TEXT_LEN_FOR_FULL_EXTRACT = 400
DEGRADED_CONFIDENCE_CAP = 0.5

SYSTEM_PROMPT = """\
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

Responda APENAS com um objeto JSON com os campos: brand, model, generation,
body_type, stage, is_new_generation, markets, global_debut, event_date,
sales_start, powertrain, price, highlights, confidence. Sem markdown.
"""


async def call_extract(article_text: str) -> str:
    return await _call_extract_raw(SYSTEM_PROMPT, article_text)


def extract_article_text(html: str) -> str:
    tree = HTMLParser(html)

    ld_json_node = tree.css_first('script[type="application/ld+json"]')
    if ld_json_node is not None:
        try:
            data = json.loads(ld_json_node.text())
        except (json.JSONDecodeError, TypeError):
            data = None
        candidates = data if isinstance(data, list) else [data] if data else []
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "NewsArticle":
                body = candidate.get("articleBody")
                if body:
                    return body

    for selector in ("article", "main"):
        node = tree.css_first(selector)
        if node is not None:
            text = node.text(separator=" ", strip=True)
            if len(text) > MIN_TEXT_LEN_FOR_FULL_EXTRACT:
                return text

    paragraphs = tree.css("p")
    return " ".join(p.text(strip=True) for p in paragraphs)


def truncate_for_llm(text: str) -> str:
    return text[:MAX_CHARS]


def parse_extract_response(raw_text: str) -> ExtractedEvent | None:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    try:
        return ExtractedEvent.model_validate(data)
    except ValidationError:
        return None


async def extract_one_item(pool, row: tuple, logger) -> str:
    item_id, url, title, summary, source_id, source_tier = row

    result = await fetcher.fetch(url, kind="page")
    degraded = result.status != 200 or result.blocked or not result.body

    if degraded:
        article_text = f"{title}\n\n{summary or ''}"
    else:
        article_text = extract_article_text(result.body)
        if len(article_text) < MIN_TEXT_LEN_FOR_FULL_EXTRACT:
            degraded = True
            article_text = f"{title}\n\n{summary or ''}"

    truncated = truncate_for_llm(article_text)
    raw_response = await call_extract(truncated)
    extracted = parse_extract_response(raw_response)

    if extracted is None:
        retry_text = truncated + (
            "\n\n[A resposta anterior não pôde ser validada como o JSON esperado. "
            "Responda novamente, apenas com o objeto JSON, sem markdown.]"
        )
        raw_response = await call_extract(retry_text)
        extracted = parse_extract_response(raw_response)

    if extracted is None:
        async with pool.connection() as conn:
            await conn.execute("UPDATE raw_items SET status = 'error' WHERE id = %s", (item_id,))
        if logger is not None:
            logger.warning("llm.call", op="extract", status="parse_error", item_id=item_id)
        return "error"

    if degraded:
        extracted.confidence = min(extracted.confidence, DEGRADED_CONFIDENCE_CAP)

    await dedupe.process_extracted_event(
        pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=source_tier
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE raw_items SET status = 'extracted', body = %s WHERE id = %s",
            (None if degraded else result.body, item_id),
        )
    return "extracted"


async def run_extract(pool, logger, limit: int = 50) -> dict:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT ri.id, ri.url, ri.title, ri.summary, ri.source_id, s.tier "
            "FROM raw_items ri JOIN sources s ON s.id = ri.source_id "
            "WHERE ri.status = 'new' AND ri.classified IS NOT NULL "
            "AND ri.classified->>'is_launch' = 'true' LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()

    extracted_count = error_count = 0
    for row in rows:
        outcome = await extract_one_item(pool, row, logger)
        if outcome == "extracted":
            extracted_count += 1
        else:
            error_count += 1

    stats = {"in": len(rows), "extracted": extracted_count, "error": error_count}
    if logger is not None:
        logger.info("extract.batch", **stats)
    return stats
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_extract.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add src/carwatch/llm/extract.py src/carwatch/llm/client.py tests/test_extract.py tests/fixtures/articles
git commit -m "feat(carwatch): add article extraction with ld+json/article/main fallback chain"
```

---

### Task 6: `publishers/telegram.py` — full per-event formatter (replaces the Fase 1 smoke summary)

**Files:**
- Modify: `agents/carwatch/src/carwatch/publishers/telegram.py` — **remove** `format_smoke_summary`, `get_approved_items_for_notification`, `run_publish_smoke` (Fase 1 Task 15); they're superseded now that `launch_events` exists. Keep `send_telegram_message` unchanged.
- Test: replace `agents/carwatch/tests/test_telegram.py` content accordingly (remove the three superseded tests, add the ones below; keep the `send_telegram_message` tests as-is).

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3).
- Produces: `def format_event_message(event: dict, source_count: int, primary_url: str) -> str` — SPEC.md §15 layout.
- Produces: `async def get_pending_events(pool) -> list[dict]` — `launch_events` where `published=FALSE AND confidence >= 0.7`, ordered by `first_seen_at`, each dict carrying `id, brand, model, stage, markets, highlights, powertrain, price, sales_start, primary_url, source_count` (`primary_url` from the `event_sources` row with `is_primary=TRUE`, falling back to the earliest `seen_at`).
- Produces: `async def mark_published(pool, event_id: int) -> None`.
- Produces: `async def publish_pending_events(pool, bot_token: str, chat_id: str, logger) -> dict` — sends one Telegram message per pending event, marks it `published=TRUE` only on a successful send, sleeps ~1.1s between sends (Telegram's per-chat flood limit — a practical implementation detail, not a SPEC.md-mandated number; SPEC.md §15's "20 msgs/hora, excedente no digest das 08:00" doesn't apply per DESIGN.md §2 — a weekly run sends everything pending in one pass). Returns `{"pending": int, "sent": int}`.

**Emoji/label mapping (not specified verbatim in SPEC.md §15 — this plan's own interpretation, consistent with the format sketch):**

```python
STAGE_EMOJI = {
    "spy": "🕵️", "teaser": "🎬", "concept": "💭", "world_premiere": "🌍",
    "specs_release": "📋", "pricing": "💵", "on_sale": "🛒", "market_launch": "🚀",
}
STAGE_LABEL_PT = {
    "spy": "Flagra", "teaser": "Teaser", "concept": "Conceito",
    "world_premiere": "Estreia mundial", "specs_release": "Ficha técnica divulgada",
    "pricing": "Preço anunciado", "on_sale": "Pré-venda aberta",
    "market_launch": "Chegada ao mercado",
}
```

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_telegram.py — full replacement content"""
import httpx
import respx

from carwatch.publishers.telegram import (
    format_event_message,
    get_pending_events,
    mark_published,
    publish_pending_events,
    send_telegram_message,
)


@respx.mock
async def test_send_telegram_message_returns_true_on_success():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert await send_telegram_message("token123", "chat1", "hello") is True


@respx.mock
async def test_send_telegram_message_returns_false_on_http_error():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(return_value=httpx.Response(500))
    assert await send_telegram_message("token123", "chat1", "hello") is False


def test_format_event_message_includes_brand_model_stage_and_source_link():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "world_premiere",
        "markets": ["CN"], "highlights": ["Estreia mundial em Shenzhen"],
        "powertrain": {"type": "bev", "power_hp": 212, "range_km": 520, "range_cycle": "WLTP"},
        "price": {"amount": 109800, "currency": "CNY", "status": "official"},
        "sales_start": "2026-Q2",
    }
    text = format_event_message(event, source_count=3, primary_url="https://x.com/a")

    assert "BYD Seal 06" in text
    assert "🌍" in text
    assert "Estreia mundial em Shenzhen" in text
    assert "212 cv" in text
    assert "CNY" in text
    assert "3 fonte(s)" in text
    assert 'href="https://x.com/a"' in text


def test_format_event_message_handles_missing_powertrain_and_price():
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": [],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "não informado" in text
    assert "não divulgado" in text


async def test_get_pending_events_excludes_published_and_low_confidence(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't') RETURNING id",
            (source_id,),
        )
        item_id = (await item.fetchone())[0]

        pending = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE) RETURNING id"
        )
        pending_id = (await pending.fetchone())[0]
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'world_premiere', ARRAY['h'], 0.9, TRUE)"
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k3', 'BYD', 'Seal 08', 'seal-08', 'world_premiere', ARRAY['h'], 0.5, FALSE)"
        )
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) VALUES (%s, %s, %s, TRUE)",
            (pending_id, item_id, source_id),
        )

    events = await get_pending_events(db_pool)

    assert len(events) == 1
    assert events[0]["id"] == pending_id
    assert events[0]["primary_url"] == "https://x.com/a"
    assert events[0]["source_count"] == 1


@respx.mock
async def test_publish_pending_events_marks_published_only_on_success(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE) RETURNING id"
        )
        event_id = (await result.fetchone())[0]

    stats = await publish_pending_events(db_pool, "token123", "chat1", logger=None)

    assert stats == {"pending": 1, "sent": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT published FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_telegram.py -v`
Expected: FAIL — new functions don't exist yet.

- [ ] **Step 3: Replace `publishers/telegram.py`**

```python
"""src/carwatch/publishers/telegram.py"""
import asyncio

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"

STAGE_EMOJI = {
    "spy": "🕵️", "teaser": "🎬", "concept": "💭", "world_premiere": "🌍",
    "specs_release": "📋", "pricing": "💵", "on_sale": "🛒", "market_launch": "🚀",
}
STAGE_LABEL_PT = {
    "spy": "Flagra", "teaser": "Teaser", "concept": "Conceito",
    "world_premiere": "Estreia mundial", "specs_release": "Ficha técnica divulgada",
    "pricing": "Preço anunciado", "on_sale": "Pré-venda aberta",
    "market_launch": "Chegada ao mercado",
}
POWERTRAIN_TYPE_LABEL = {
    "bev": "Elétrico", "phev": "Híbrido plug-in", "hev": "Híbrido",
    "ice": "Combustão", "fcev": "Célula de combustível",
}
PRICE_STATUS_LABEL = {"official": "oficial", "estimated": "estimado", "starting_from": "a partir de"}


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def _format_powertrain(powertrain: dict | None) -> str:
    if not powertrain:
        return "não informado"
    parts = [POWERTRAIN_TYPE_LABEL.get(powertrain.get("type"), powertrain.get("type") or "?")]
    if powertrain.get("power_hp"):
        parts.append(f"{powertrain['power_hp']} cv")
    if powertrain.get("range_km"):
        parts.append(f"{powertrain['range_km']} km ({powertrain.get('range_cycle') or '?'})")
    return " · ".join(parts)


def _format_price(price: dict | None) -> str:
    if not price or price.get("amount") is None:
        return "não divulgado"
    status = PRICE_STATUS_LABEL.get(price.get("status"), "")
    currency = price.get("currency") or ""
    return f"{currency} {price['amount']:,.0f} ({status})".strip()


def format_event_message(event: dict, source_count: int, primary_url: str) -> str:
    stage = event["stage"]
    emoji = STAGE_EMOJI.get(stage, "🚗")
    label = STAGE_LABEL_PT.get(stage, stage)
    markets = ", ".join(event.get("markets") or []) or "Global"

    lines = [f"🚗 <b>{event['brand']} {event['model']}</b>", f"{emoji} {label} · {markets}", ""]
    highlights = event.get("highlights") or []
    if highlights:
        lines.append("\n".join(f"• {h}" for h in highlights))
        lines.append("")
    lines.append(f"⚡ {_format_powertrain(event.get('powertrain'))}")
    lines.append(f"💰 {_format_price(event.get('price'))}")
    if event.get("sales_start"):
        lines.append(f"📅 Vendas: {event['sales_start']}")
    lines.append("")
    lines.append(f'<a href="{primary_url}">Fonte</a> · {source_count} fonte(s)')
    return "\n".join(lines)


async def get_pending_events(pool) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, le.markets, le.highlights, "
            "le.powertrain, le.price, le.sales_start, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC, es.seen_at ASC LIMIT 1) AS primary_url, "
            "(SELECT count(*) FROM event_sources es WHERE es.event_id = le.id) AS source_count "
            "FROM launch_events le WHERE le.published = FALSE AND le.confidence >= 0.7 "
            "ORDER BY le.first_seen_at ASC"
        )
        rows = await result.fetchall()

    return [
        {
            "id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "markets": r[4],
            "highlights": r[5], "powertrain": r[6], "price": r[7], "sales_start": r[8],
            "primary_url": r[9], "source_count": r[10],
        }
        for r in rows
    ]


async def mark_published(pool, event_id: int) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE launch_events SET published = TRUE WHERE id = %s", (event_id,))


async def publish_pending_events(pool, bot_token: str, chat_id: str, logger) -> dict:
    events = await get_pending_events(pool)
    sent = 0
    for i, event in enumerate(events):
        text = format_event_message(event, event["source_count"], event["primary_url"] or "")
        ok = await send_telegram_message(bot_token, chat_id, text)
        if ok:
            await mark_published(pool, event["id"])
            sent += 1
        if logger is not None:
            logger.info("publish.sent", event_id=event["id"], channel="telegram", ok=ok)
        if i < len(events) - 1:
            await asyncio.sleep(1.1)
    return {"pending": len(events), "sent": sent}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_telegram.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/publishers/telegram.py tests/test_telegram.py
git commit -m "feat(carwatch): replace smoke Telegram summary with full per-event formatter"
```

---

### Task 7: `publishers/atom.py` — static Atom feed

**Files:**
- Create: `agents/carwatch/src/carwatch/publishers/atom.py`
- Test: `agents/carwatch/tests/test_atom.py`

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3).
- Produces: `async def get_recent_events_for_feed(pool, limit: int = 100) -> list[dict]` — the last `limit` **published** events (`published = TRUE`), ordered by `updated_at DESC`.
- Produces: `def render_atom_feed(events: list[dict], feed_self_url: str) -> str` — pure function, no I/O, returns the Atom 1.0 XML document as a string.
- Produces: `async def write_atom_feed(pool, output_path: Path, feed_self_url: str, limit: int = 100) -> int` — writes the file, returns the number of entries written.

**On "validates no W3C validator" (SPEC.md §19 Fase 2 acceptance):** that's a manual step against the live public feed, not something a hermetic test can call out to (no network access to an external validator from the test suite). This plan's automated test instead parses the output with `xml.etree.ElementTree` and asserts every Atom-required element is present — the practical proxy. The literal W3C check is Step 5 of Task 10 (this phase's end-to-end task), run once against a real deployed feed.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_atom.py"""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from carwatch.publishers.atom import render_atom_feed

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def test_render_atom_feed_produces_well_formed_xml_with_required_elements():
    events = [
        {
            "id": 1, "brand": "BYD", "model": "Seal 06", "stage": "world_premiere",
            "highlights": ["Estreia mundial em Shenzhen"],
            "updated_at": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "primary_url": "https://x.com/a",
        }
    ]
    xml_text = render_atom_feed(events, feed_self_url="https://example.com/feed.atom")

    root = ET.fromstring(xml_text)
    assert root.tag == f"{ATOM_NS}feed"
    assert root.find(f"{ATOM_NS}id") is not None
    assert root.find(f"{ATOM_NS}title") is not None
    assert root.find(f"{ATOM_NS}updated") is not None
    entries = root.findall(f"{ATOM_NS}entry")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.find(f"{ATOM_NS}id").text == "urn:carwatch:event:1"
    assert "BYD Seal 06" in entry.find(f"{ATOM_NS}title").text
    assert entry.find(f"{ATOM_NS}updated").text == "2026-01-15T10:00:00Z"
    assert entry.find(f"{ATOM_NS}link").get("href") == "https://x.com/a"


def test_render_atom_feed_escapes_special_characters_in_titles():
    events = [
        {
            "id": 2, "brand": "M&M Motors", "model": "X<Y>", "stage": "teaser",
            "highlights": [], "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "primary_url": "https://x.com/b",
        }
    ]
    xml_text = render_atom_feed(events, feed_self_url="https://example.com/feed.atom")
    root = ET.fromstring(xml_text)  # raises if not well-formed
    assert "M&M Motors" in root.find(f"{ATOM_NS}entry/{ATOM_NS}title").text


def test_render_atom_feed_handles_zero_events():
    xml_text = render_atom_feed([], feed_self_url="https://example.com/feed.atom")
    root = ET.fromstring(xml_text)
    assert root.findall(f"{ATOM_NS}entry") == []


async def test_write_atom_feed_writes_file_and_returns_count(db_pool, tmp_path):
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, TRUE)"
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'teaser', ARRAY['h'], 0.9, FALSE)"  # unpublished, excluded
        )

    from carwatch.publishers.atom import write_atom_feed

    out_path = tmp_path / "feed.atom"
    count = await write_atom_feed(db_pool, out_path, "https://example.com/feed.atom")

    assert count == 1
    assert out_path.exists()
    assert "Seal 06" in out_path.read_text()
    assert "Seal 07" not in out_path.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_atom.py -v`
Expected: FAIL — `carwatch.publishers.atom` doesn't exist.

- [ ] **Step 3: Implement `publishers/atom.py`**

```python
"""src/carwatch/publishers/atom.py"""
from datetime import timezone
from pathlib import Path
from xml.sax.saxutils import escape

ATOM_NS = "http://www.w3.org/2005/Atom"


async def get_recent_events_for_feed(pool, limit: int = 100) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, le.highlights, le.updated_at, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC, es.seen_at ASC LIMIT 1) AS primary_url "
            "FROM launch_events le WHERE le.published = TRUE "
            "ORDER BY le.updated_at DESC LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()
    return [
        {"id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "highlights": r[4],
         "updated_at": r[5], "primary_url": r[6]}
        for r in rows
    ]


def _rfc3339(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_atom_feed(events: list[dict], feed_self_url: str) -> str:
    from datetime import datetime

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = []
    for event in events:
        summary = " ".join(event.get("highlights") or [])
        link = event.get("primary_url") or feed_self_url
        title = f"{event['brand']} {event['model']} — {event['stage']}"
        entries.append(
            "  <entry>\n"
            f"    <id>urn:carwatch:event:{event['id']}</id>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <updated>{_rfc3339(event['updated_at'])}</updated>\n"
            f"    <link href=\"{escape(link)}\"/>\n"
            f"    <summary>{escape(summary)}</summary>\n"
            "  </entry>\n"
        )

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<feed xmlns="{ATOM_NS}">\n'
        "  <title>CarWatch — Lançamentos Automotivos</title>\n"
        "  <id>urn:carwatch:feed</id>\n"
        f"  <updated>{now}</updated>\n"
        f'  <link rel="self" href="{escape(feed_self_url)}"/>\n'
        + "".join(entries)
        + "</feed>\n"
    )


async def write_atom_feed(pool, output_path: Path, feed_self_url: str, limit: int = 100) -> int:
    events = await get_recent_events_for_feed(pool, limit)
    content = render_atom_feed(events, feed_self_url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return len(events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_atom.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/publishers/atom.py tests/test_atom.py
git commit -m "feat(carwatch): add static Atom feed generator"
```

---

### Task 8: `review.py` — manual precision sampling

**Files:**
- Create: `agents/carwatch/src/carwatch/review.py`
- Test: `agents/carwatch/tests/test_review.py`

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Fase 1 Task 3).
- Produces: `async def get_events_for_review(pool, limit: int = 15) -> list[dict]` — `launch_events` where `review_status='pending'`, newest first.
- Produces: `async def set_review_status(pool, event_id: int, status: str) -> None`.
- Produces: `async def run_review(pool, limit: int, input_fn, print_fn) -> dict` — `input_fn`/`print_fn` are injected (`input_fn: Callable[[str], str]`, `print_fn: Callable[[str], None]`) so this is testable without a real terminal; the CLI command (Task 9) wires `input_fn=input, print_fn=typer.echo`. Returns `{"confirmed": int, "rejected": int, "skipped": int}`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_review.py"""
from carwatch.review import get_events_for_review, run_review, set_review_status


async def _insert_pending_event(db_pool, dedupe_key: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, review_status) VALUES "
            "(%s, 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, 'pending') RETURNING id",
            (dedupe_key,),
        )
        return (await result.fetchone())[0]


async def test_get_events_for_review_only_returns_pending(db_pool):
    pending_id = await _insert_pending_event(db_pool, "k1")
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, review_status) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'teaser', ARRAY['h'], 0.9, 'confirmed')"
        )

    events = await get_events_for_review(db_pool, limit=15)

    assert len(events) == 1
    assert events[0]["id"] == pending_id


async def test_run_review_records_confirm_reject_and_skip(db_pool):
    id_a = await _insert_pending_event(db_pool, "k1")
    id_b = await _insert_pending_event(db_pool, "k2")
    id_c = await _insert_pending_event(db_pool, "k3")

    answers = iter(["c", "r", "s"])
    printed = []
    counts = await run_review(
        db_pool, limit=15, input_fn=lambda _prompt: next(answers), print_fn=printed.append
    )

    assert counts == {"confirmed": 1, "rejected": 1, "skipped": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, review_status FROM launch_events ORDER BY id"
        )
        rows = dict(await result.fetchall())
    assert rows[id_a] == "confirmed"
    assert rows[id_b] == "rejected"
    assert rows[id_c] == "pending"  # skip leaves it untouched
    assert any("BYD" in line for line in printed)


async def test_run_review_reprompts_on_invalid_input(db_pool):
    await _insert_pending_event(db_pool, "k1")
    answers = iter(["x", "c"])
    printed = []

    counts = await run_review(
        db_pool, limit=15, input_fn=lambda _prompt: next(answers), print_fn=printed.append
    )

    assert counts == {"confirmed": 1, "rejected": 0, "skipped": 0}
    assert any("inválida" in line for line in printed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_review.py -v`
Expected: FAIL — `carwatch.review` doesn't exist.

- [ ] **Step 3: Implement `review.py`**

```python
"""src/carwatch/review.py"""
DECISION_MAP = {"c": "confirmed", "r": "rejected"}


async def get_events_for_review(pool, limit: int = 15) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC LIMIT 1) AS primary_url "
            "FROM launch_events le WHERE le.review_status = 'pending' "
            "ORDER BY le.first_seen_at DESC LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()
    return [{"id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "primary_url": r[4]} for r in rows]


async def set_review_status(pool, event_id: int, status: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE launch_events SET review_status = %s WHERE id = %s", (status, event_id))


async def run_review(pool, limit: int, input_fn, print_fn) -> dict:
    events = await get_events_for_review(pool, limit)
    counts = {"confirmed": 0, "rejected": 0, "skipped": 0}

    for event in events:
        print_fn(f"{event['brand']} {event['model']} ({event['stage']}) — {event['primary_url']}")
        while True:
            answer = input_fn("[c]onfirmar / [r]ejeitar / [s]kip: ").strip().lower()
            if answer in DECISION_MAP or answer == "s":
                break
            print_fn("Resposta inválida, use c/r/s.")

        if answer == "s":
            counts["skipped"] += 1
            continue
        await set_review_status(pool, event["id"], DECISION_MAP[answer])
        counts["confirmed" if answer == "c" else "rejected"] += 1

    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/review.py tests/test_review.py
git commit -m "feat(carwatch): add manual review CLI backend for precision sampling"
```

---

### Task 9: Wire `extract`, `review`, full `publish`, and Atom generation into `cli.py`

**Files:**
- Modify: `agents/carwatch/src/carwatch/cli.py`
- Modify: `agents/carwatch/src/carwatch/settings.py` — add `atom_feed_path: str = "feed.atom"` and `atom_feed_url: str`.
- Modify: `agents/carwatch/.env.example` — add `ATOM_FEED_PATH=feed.atom` and `ATOM_FEED_URL=https://example.com/feed.atom`.
- Test: `agents/carwatch/tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `run_extract` (Task 5), `run_review` (Task 8), `publish_pending_events` (Task 6), `write_atom_feed` (Task 7).
- Produces: updated `publish` command (drops `--dry-run`'s old smoke-summary meaning, now dry-runs the real publisher — counts pending events without sending), new `extract --limit` and `review --limit` commands, `weekly-run` extended to run `extract` and the full `publish` + Atom write after `classify`.

- [ ] **Step 1: Write the failing tests (appended to `tests/test_cli.py`)**

```python
def test_help_lists_fase2_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("extract", "review"):
        assert command in result.output


def test_publish_dry_run_counts_pending_events_without_sending(db_pool):
    result = runner.invoke(app, ["publish", "--dry-run"])
    assert result.exit_code == 0
    assert "would_send" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `extract`/`review` commands don't exist yet; `publish --dry-run` still references the removed Fase 1 smoke functions.

- [ ] **Step 3: Update `settings.py`**

```python
# src/carwatch/settings.py — add two fields to the Settings class
    atom_feed_path: str = "feed.atom"
    atom_feed_url: str = "https://example.com/feed.atom"
```

- [ ] **Step 4: Update `.env.example`**

```
# append
ATOM_FEED_PATH=feed.atom
ATOM_FEED_URL=https://example.com/feed.atom
```

- [ ] **Step 5: Update `cli.py`**

```python
# src/carwatch/cli.py — replace the imports block's publishers import and the publish/weekly_run functions,
# and add extract/review commands.

from pathlib import Path as _Path  # already imported as Path above; reuse existing import

from carwatch.llm.extract import run_extract
from carwatch.publishers.atom import write_atom_feed
from carwatch.publishers.telegram import get_pending_events, publish_pending_events
from carwatch.review import run_review


@app.command()
def extract(limit: int = typer.Option(50, "--limit")):
    async def _run():
        logger = _logger()
        stats = await run_extract(get_pool(), logger, limit=limit)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def review(limit: int = typer.Option(15, "--limit")):
    async def _run():
        counts = await run_review(get_pool(), limit, input_fn=input, print_fn=typer.echo)
        await close_pool()
        return counts

    typer.echo(asyncio.run(_run()))


@app.command()
def publish(dry_run: bool = typer.Option(False, "--dry-run")):
    async def _run():
        logger = _logger()
        pool = get_pool()
        if dry_run:
            events = await get_pending_events(pool)
            await close_pool()
            return {"would_send": len(events)}
        settings = get_settings()
        stats = await publish_pending_events(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
        await write_atom_feed(pool, Path(settings.atom_feed_path), settings.atom_feed_url)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command(name="weekly-run")
def weekly_run():
    """ingest -> prefilter -> classify -> extract -> publish (+ atom).

    DESIGN.md §1: replaces SPEC.md's APScheduler daemon. dedupe.py has no
    separate CLI entrypoint — it's invoked per item inside run_extract
    (SPEC.md §3 architecture diagram: extract -> dedupe -> launch_events).
    """

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
        await close_pool()
        return {
            "ingest": ingest_stats,
            "prefilter": prefilter_stats,
            "classify": classify_stats,
            "extract": extract_stats,
            "publish": publish_stats,
        }

    result = asyncio.run(_run())
    typer.echo(result)
    if result["publish"]["pending"] > 0 and result["publish"]["sent"] == 0:
        raise typer.Exit(code=1)
```

**Note the changed failure condition:** Fase 1's `weekly-run` failed if the single smoke message didn't send. Now that `publish` can legitimately have zero pending events in a quiet week, "no pending events" must not look like a failure — only "there were pending events and none of them sent" does.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add src/carwatch/cli.py src/carwatch/settings.py .env.example tests/test_cli.py
git commit -m "feat(carwatch): wire extract, review, full publish, and atom into the CLI"
```

---

### Task 10: Multilingual fixtures + Fase 2 end-to-end acceptance

**Files:**
- Create: `agents/carwatch/tests/fixtures/articles/article_zh.html`, `article_ja.html`, `article_pt.html`
- Create: `agents/carwatch/tests/test_e2e_fase2.py`

**Interfaces:**
- Consumes: everything in this phase.

- [ ] **Step 1: Write the multilingual fixtures (SPEC.md §20: "incluir 1 em chinês, 1 em japonês, 1 em português")**

```html
<!-- tests/fixtures/articles/article_zh.html -->
<html><body><article>
<p>比亚迪今日在深圳举行海豹06全球首发仪式。</p>
<p>新车提供纯电动力，最大功率212马力，WLTP续航520公里。</p>
<p>官方指导价为109,800元人民币，第二季度开始交付。</p>
</article></body></html>
```

```html
<!-- tests/fixtures/articles/article_ja.html -->
<html><body><article>
<p>BYDは本日、深センで新型シール06を世界初公開した。</p>
<p>電気自動車専用で、最高出力212馬力、WLTP航続距離520kmを実現。</p>
<p>価格は109,800人民元から、第2四半期に納車開始予定。</p>
</article></body></html>
```

```html
<!-- tests/fixtures/articles/article_pt.html -->
<html><body><article>
<p>A BYD revelou hoje o novo Seal 06 em um evento mundial em Shenzhen.</p>
<p>O modelo é oferecido exclusivamente como elétrico, com 212 cv e autonomia WLTP de 520 km.</p>
<p>Os preços partem de 109.800 CNY, com entregas a partir do segundo trimestre.</p>
</article></body></html>
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_e2e_fase2.py"""
from pathlib import Path

from carwatch.dedupe import process_extracted_event
from carwatch.llm.extract import extract_article_text
from carwatch.models import ExtractedEvent

FIXTURES = Path(__file__).parent / "fixtures" / "articles"


def test_extract_article_text_handles_chinese_japanese_and_portuguese():
    for filename, expected_fragment in (
        ("article_zh.html", "比亚迪"),
        ("article_ja.html", "BYD"),
        ("article_pt.html", "Shenzhen"),
    ):
        html = (FIXTURES / filename).read_text(encoding="utf-8")
        text = extract_article_text(html)
        assert expected_fragment in text


async def _insert_source_and_item(db_pool, url: str):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', %s, 'rss', 3, 'active') RETURNING id",
            (f"{url}-feed",),
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, %s, %s, 'title') RETURNING id",
            (source_id, url, url),
        )
        item_id = (await item.fetchone())[0]
    return source_id, item_id


async def test_eight_articles_about_same_launch_collapse_into_one_event(db_pool):
    event_id = None
    for i in range(8):
        source_id, item_id = await _insert_source_and_item(db_pool, f"https://x.com/article-{i}")
        extracted = ExtractedEvent(
            brand="BYD", model="Seal 06", generation=None, body_type="sedan",
            stage="world_premiere", markets=["CN"], event_date=None, sales_start=None,
            powertrain=None, price=None, highlights=[f"Cobertura {i}"], confidence=0.9,
        )
        result_id = await process_extracted_event(
            db_pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=3
        )
        if event_id is None:
            event_id = result_id
        assert result_id == event_id  # every one of the 8 collapses onto the first

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1
        result = await conn.execute(
            "SELECT count(*) FROM event_sources WHERE event_id = %s", (event_id,)
        )
        assert (await result.fetchone())[0] == 8
```

- [ ] **Step 3: Run tests to verify they fail, then pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_e2e_fase2.py -v`
Expected: FAIL initially only if run before earlier tasks exist; PASS once Tasks 1–9 are in place.

- [ ] **Step 4: Run the full suite and coverage check**

Run: `cd agents/carwatch && python3 -m pytest -v`
Expected: all PASS.

Run: `cd agents/carwatch && python3 -m pytest --cov=carwatch.dedupe --cov-report=term-missing tests/test_dedupe.py tests/test_e2e_fase2.py`
Expected: `dedupe.py` ≥90% (SPEC.md §20).

- [ ] **Step 5: Manual verification against SPEC.md §19 Fase 2 acceptance criteria**

Run for real, against the live internet, using a handful of real press-room/Motor1/Carscoops URLs already in `sources` from Fase 1's Step 5:

```bash
cd agents/carwatch
docker compose run --rm app ingest --once
docker compose run --rm app classify --limit 50
docker compose run --rm app extract --limit 30
docker compose run --rm app stats
```

Confirm: ≥30 articles reach `status='extracted'` with a valid `ExtractedEvent` behind them (spot-check a few rows' `launch_events` entries by hand); no numeric field appears in `powertrain`/`price` that isn't actually stated in the source article (SPEC.md §21.5 — check this by hand against 3–5 real articles, since this is precisely the failure mode no automated test can catch without a ground-truth-labeled corpus).

For the Atom feed:

```bash
docker compose run --rm app publish
```

Take the resulting `feed.atom` and paste it into https://validator.w3.org/feed/ by hand — the one genuinely manual, non-automatable acceptance item in this phase.

- [ ] **Step 6: Confirm every SPEC.md §19 Fase 2 bullet has a home**

| SPEC.md §19 Fase 2 criterion | Verified by |
|---|---|
| 30 artigos reais extraídos com schema válido | Task 5 (`extract.py`), Step 5 above (manual, live) |
| Fixture com 8 artigos → colapsa em 1 evento | This task, Step 2 |
| Fixture com 2 modelos irmãos → não colapsa | Fase 2 Task 4 (`test_sibling_models_do_not_collapse`) |
| Progressão de estágio cria evento novo | Fase 2 Task 4 (`test_stage_progression_creates_new_linked_event`) |
| Feed Atom valida no W3C validator | Task 7 (structural proxy test), Step 5 above (manual, literal) |

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add tests/test_e2e_fase2.py tests/fixtures/articles
git commit -m "test(carwatch): add Fase 2 end-to-end acceptance tests and multilingual fixtures"
```

---

## Self-Review

**Spec coverage:** SPEC.md §5.4 (schema — Task 1, with the documented `previous_event_id` addition), §11 (extract — Task 5), §12 (dedupe, all four etapas — Task 4), §15 full formatter (Task 6), atom (Task 7), `review` (Task 8), §17 CLI surface additions (Task 9), §19 Fase 2 acceptance (Task 10), §20 multilingual fixtures (Task 10), §21.5/§21.6 (never-invent-numbers, `is_new_generation` default-false — Task 3's Pydantic default + Task 5's system prompt).

**Placeholder scan:** no "TBD"/"TODO"; every step has real code, a real fixture, or a real shell command with an expected result.

**Type consistency:** `ExtractedEvent` (Task 3) fields match `dedupe.process_extracted_event`'s usage (Task 4) and `parse_extract_response`'s validation (Task 5) exactly. `STAGE_ORDER` (Task 4) matches the Global Constraints section's progression order, which is explicitly **not** the DB enum declaration order — checked because it would be an easy, silent bug to use the wrong ordering. `launch_events` column names used across Tasks 4/6/7/8 (`dedupe_key, brand, model, model_slug, stage, highlights, confidence, published, review_status, previous_event_id, powertrain, price, sales_start, markets, updated_at, first_seen_at`) all trace back to Task 1's migration — no task references a column Task 1 didn't create.
