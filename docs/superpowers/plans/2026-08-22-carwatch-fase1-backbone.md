# CarWatch Fase 1 — Espinha Dorsal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CarWatch backbone — fetcher, db, ingest, prefilter, classify, Telegram smoke notification, CLI, docker-compose — able to run `carwatch weekly-run` once end-to-end over 20 seed sources without duplicating items or making HTTP calls outside `fetcher.py`.

**Architecture:** Single Python 3.12 package (`src/carwatch/`) run inside a Docker container (`app` service), talking to a Postgres 16 + pgvector container (`db` service) over `psycopg` async. All outbound HTTP goes through one `fetcher.py` module (robots.txt, conditional GET, per-domain rate limiting, circuit breaker). A `typer` CLI exposes per-stage commands plus one composite `weekly-run` used by the systemd timer.

**Tech Stack:** Python 3.12, uv, PostgreSQL 16 + pgvector + pg_trgm, psycopg v3 async (^3.2), httpx async HTTP/2 (^0.27), tenacity (^9.0), feedparser (^6.0), pydantic-settings (^2.0), structlog JSON (^24.0), anthropic SDK (^0.40, `claude-haiku-4-5-20251001`), typer, pytest + pytest-asyncio + respx, docker compose.

**Spec:** `agents/carwatch/SPEC.md` (original spec) + `agents/carwatch/DESIGN.md` (weekly-execution delta — read both; DESIGN.md wins on conflicts). This plan implements SPEC.md §1–§10, §16–§17, §19 (Fase 1), §21 (relevant items), §22 (partial), adapted per DESIGN.md §1, §3, §5.

## Global Constraints

- Python 3.12 exactly; dependency manager is `uv`, not pip/poetry.
- **No `requests` library anywhere.** Async end-to-end (SPEC.md §21.1).
- **No module outside `src/carwatch/fetcher.py` may call `httpx` directly.** Enforced by a grep-based test (Task 9).
- Never parallelize fetches within the same domain (SPEC.md §21.2) — per-domain semaphore of 1.
- Never retry HTTP 403/404/410 (SPEC.md §21.3, §6).
- Never trust HTTP 200 as "content is real" — must run silent-block detection (SPEC.md §21.4, §6).
- `temperature=0` on every LLM call (SPEC.md §21.9).
- All timestamps stored in the database are UTC; `America/Sao_Paulo` is a presentation-layer concern only (SPEC.md §21.10) — not exercised until Telegram formatting in Fase 2, but no code in this phase may localize a timestamp before writing to Postgres.
- User-Agent is fixed and honest: `CarWatchBot/1.0 (+{BOT_INFO_URL}; {CONTACT_EMAIL})`, configurable via env, **never** rotated or spoofed (SPEC.md §6.2).
- Out of scope entirely (SPEC.md §1): CAPTCHA/WAF bypass, residential proxy rotation, paywall bypass, full-text scraping of paid media, any frontend/dashboard, market pricing/inventory/resale data.
- No custom scraper for a press room without a working feed — falls back to Tier 3/4 coverage (SPEC.md §7, §21.7). Do not write one even if a specific brand seems to need it.
- **Deviation from SPEC.md (see DESIGN.md §1):** no `APScheduler`, no daemon `carwatch run` mode. Scheduling is a single `carwatch weekly-run` command invoked once by an external systemd timer (built in Task 18).
- Deployment note (SPEC.md §16): this runs on the desktop / residential IP first, not a VPS — nothing in this phase should assume a static datacenter IP.

---

### Task 1: Project scaffolding, Dockerfile, docker-compose, migration 001

**Files:**
- Create: `agents/carwatch/pyproject.toml`
- Create: `agents/carwatch/Dockerfile`
- Create: `agents/carwatch/docker-compose.yml`
- Create: `agents/carwatch/.env.example`
- Create: `agents/carwatch/.gitignore`
- Create: `agents/carwatch/migrations/001_init.sql`
- Create: `agents/carwatch/src/carwatch/__init__.py`
- Test: `agents/carwatch/tests/test_scaffolding.py`

**Interfaces:**
- Produces: a `db` service reachable at `postgresql://carwatch:carwatch@localhost:5432/carwatch` when run locally, and at `postgresql://carwatch:carwatch@db:5432/carwatch` from inside the `app` container network. Later tasks read this from `DATABASE_URL`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "carwatch"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "psycopg[binary,pool]>=3.2,<4.0",
    "httpx[http2]>=0.27,<0.28",
    "tenacity>=9.0,<10.0",
    "feedparser>=6.0,<7.0",
    "selectolax>=0.3,<0.4",
    "pydantic-settings>=2.0,<3.0",
    "structlog>=24.0,<25.0",
    "anthropic>=0.40,<0.41",
    "typer>=0.12,<0.13",
    "pyyaml>=6.0,<7.0",
]

[project.scripts]
carwatch = "carwatch.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.24,<0.25",
    "respx>=0.21,<0.22",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/carwatch"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY config/ ./config/

RUN uv pip install --system --no-cache .

ENTRYPOINT ["carwatch"]
CMD ["--help"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

Per DESIGN.md §3/§5: `db` stays up continuously; `app` is invoked on demand via `docker compose run --rm app <cmd>`, never `docker compose up -d app`.

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_USER: carwatch
      POSTGRES_PASSWORD: carwatch
      POSTGRES_DB: carwatch
    volumes:
      - carwatch_db_data:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U carwatch -d carwatch"]
      interval: 5s
      timeout: 5s
      retries: 10

  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://carwatch:carwatch@db:5432/carwatch

volumes:
  carwatch_db_data:
```

Note: host port is `5433` (not `5432`) to avoid colliding with any other local Postgres. `DATABASE_URL` inside the container always points at `db`; a developer running tests from the host uses `postgresql://carwatch:carwatch@localhost:5433/carwatch`.

- [ ] **Step 4: Write `.env.example`**

```
DATABASE_URL=postgresql://carwatch:carwatch@localhost:5433/carwatch
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BOT_INFO_URL=https://example.com/bot
CONTACT_EMAIL=you@example.com
FETCH_MIN_INTERVAL_SEC=3.0
FETCH_GLOBAL_CONCURRENCY=10
LOG_LEVEL=INFO
```

(`INGEST_INTERVAL_MIN` from SPEC.md §16 is intentionally omitted — DESIGN.md §2, not applicable to weekly execution.)

- [ ] **Step 5: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
reports/
*.log
```

- [ ] **Step 6: Write `migrations/001_init.sql`**

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

- [ ] **Step 7: Write `src/carwatch/__init__.py`** (empty file, makes the package importable)

```python
```

- [ ] **Step 8: Write the scaffolding test**

```python
"""tests/test_scaffolding.py"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_config_is_valid():
    result = subprocess.run(
        ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "config"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_pyproject_declares_carwatch_entrypoint():
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert 'carwatch = "carwatch.cli:app"' in content
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd agents/carwatch && python3 -m pytest tests/test_scaffolding.py -v`
Expected: FAIL — `docker-compose.yml`/`pyproject.toml` don't exist yet (if run before Steps 1-6) or `cli.py` doesn't exist yet (import will fail once `carwatch.cli` is referenced — for this task, only the two assertions above apply, so expect FAIL on missing files if tested before Steps 1-3, PASS after).

- [ ] **Step 10: Implement Steps 1-7 above, then run to verify pass**

Run: `cd agents/carwatch && docker compose config && python3 -m pytest tests/test_scaffolding.py -v`
Expected: PASS

- [ ] **Step 11: Bring up the database and confirm it's healthy**

Run: `cd agents/carwatch && docker compose up -d db && docker compose ps`
Expected: `db` shows `healthy` within ~15s.

- [ ] **Step 12: Commit**

```bash
cd agents/carwatch
git add pyproject.toml Dockerfile docker-compose.yml .env.example .gitignore migrations/001_init.sql src/carwatch/__init__.py tests/test_scaffolding.py
git commit -m "chore(carwatch): scaffold project, docker-compose, base migration"
```

---

### Task 2: `settings.py` + JSON logging setup

**Files:**
- Create: `agents/carwatch/src/carwatch/settings.py`
- Create: `agents/carwatch/src/carwatch/logging_setup.py`
- Test: `agents/carwatch/tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings `BaseSettings` subclass) with fields `database_url: str`, `anthropic_api_key: str`, `telegram_bot_token: str`, `telegram_chat_id: str`, `bot_info_url: str`, `contact_email: str`, `fetch_min_interval_sec: float = 3.0`, `fetch_global_concurrency: int = 10`, `log_level: str = "INFO"`. Loaded via `get_settings() -> Settings` (cached with `functools.lru_cache`).
- Produces: `configure_logging(log_level: str) -> structlog.stdlib.BoundLogger` — call once at process start; returns a logger via `structlog.get_logger()`.
- Consumes: nothing (this is the base layer every other module imports).

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_settings.py"""
import os

import pytest

from carwatch.settings import Settings, get_settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("BOT_INFO_URL", "https://example.com/bot")
    monkeypatch.setenv("CONTACT_EMAIL", "you@example.com")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql://u:p@h:5432/d"
    assert settings.fetch_min_interval_sec == 3.0
    assert settings.fetch_global_concurrency == 10


def test_settings_missing_required_field_raises(monkeypatch):
    for key in (
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BOT_INFO_URL",
        "CONTACT_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(Exception):
        get_settings()
```

```python
"""tests/test_logging_setup.py"""
import json
import logging

from carwatch.logging_setup import configure_logging


def test_configure_logging_emits_json(capsys):
    logger = configure_logging("INFO")
    logger.info("fetch.result", domain="example.com", status=200)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "fetch.result"
    assert payload["domain"] == "example.com"
    assert payload["status"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_settings.py tests/test_logging_setup.py -v`
Expected: FAIL — `carwatch.settings` / `carwatch.logging_setup` don't exist.

- [ ] **Step 3: Implement `settings.py`**

```python
"""src/carwatch/settings.py"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    bot_info_url: str
    contact_email: str
    fetch_min_interval_sec: float = 3.0
    fetch_global_concurrency: int = 10
    log_level: str = "INFO"

    @property
    def user_agent(self) -> str:
        return f"CarWatchBot/1.0 (+{self.bot_info_url}; {self.contact_email})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Implement `logging_setup.py`**

```python
"""src/carwatch/logging_setup.py"""
import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> structlog.stdlib.BoundLogger:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_settings.py tests/test_logging_setup.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add src/carwatch/settings.py src/carwatch/logging_setup.py tests/test_settings.py tests/test_logging_setup.py
git commit -m "feat(carwatch): add settings and JSON logging setup"
```

---

### Task 3: `db.py` — async pool + self-tracking migration runner

**Files:**
- Create: `agents/carwatch/src/carwatch/db.py`
- Create: `agents/carwatch/migrations/002_sources.sql`
- Test: `agents/carwatch/tests/test_db.py`
- Test: `agents/carwatch/tests/conftest.py`

**Interfaces:**
- Consumes: `Settings.database_url` from Task 2.
- Produces: `get_pool() -> psycopg_pool.AsyncConnectionPool` (module-level singleton, opened lazily), `async def run_migrations(pool, migrations_dir: Path) -> list[str]` (returns filenames applied this call, empty list if none pending), `async def close_pool() -> None`.
- Produces fixture `db_pool` in `conftest.py`, reused by every later task's DB-touching tests: opens a pool against `DATABASE_URL_TEST` (or `DATABASE_URL` with `_test` suffix), runs migrations, truncates all tables after each test.

**Note on test database:** these tests need a real Postgres. `docker compose up -d db` (Task 1) must be running. `conftest.py` reads `DATABASE_URL_TEST`, defaulting to `postgresql://carwatch:carwatch@localhost:5433/carwatch_test`. Document this in `agents/carwatch/README.md`'s testing section (folded into Task 18).

- [ ] **Step 1: Write `migrations/002_sources.sql`**

Copied verbatim from SPEC.md §5.1–§5.3 (`sources`, `source_metrics`, `raw_items` — everything Fase 1 needs; `launch_events`/`event_sources` are Fase 2, in `003_events.sql`):

```sql
CREATE TYPE source_status AS ENUM
  ('active','probation','retired','broken','blocked','candidate');

CREATE TABLE sources (
  id              BIGSERIAL PRIMARY KEY,
  domain          TEXT NOT NULL,
  feed_url        TEXT UNIQUE NOT NULL,
  kind            TEXT NOT NULL,
  tier            SMALLINT NOT NULL,
  brand_scope     TEXT[] DEFAULT '{}',
  region          TEXT,
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

CREATE TABLE source_metrics (
  source_id            BIGINT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  items_30d            INT DEFAULT 0,
  passed_prefilter_30d INT DEFAULT 0,
  events_30d           INT DEFAULT 0,
  unique_events_30d    INT DEFAULT 0,
  first_seen_30d       INT DEFAULT 0,
  median_lead_minutes  INT,
  yield_pct            NUMERIC(5,2),
  precision_30d        NUMERIC(5,2)
);

CREATE TABLE raw_items (
  id            BIGSERIAL PRIMARY KEY,
  source_id     BIGINT REFERENCES sources(id),
  url           TEXT NOT NULL,
  url_hash      TEXT UNIQUE NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT,
  lang          TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ DEFAULT now(),
  body          TEXT,
  prefilter_ok  BOOLEAN,
  classified    JSONB,
  status        TEXT DEFAULT 'new'
);
CREATE INDEX ON raw_items (status, fetched_at DESC);
CREATE INDEX ON raw_items (source_id, published_at DESC);
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/conftest.py"""
import os
from pathlib import Path

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from carwatch.db import run_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
)


@pytest_asyncio.fixture
async def db_pool():
    pool = AsyncConnectionPool(TEST_DB_URL, min_size=1, max_size=4, open=False)
    await pool.open()
    await run_migrations(pool, REPO_ROOT / "migrations")
    yield pool
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE raw_items, source_metrics, sources RESTART IDENTITY CASCADE"
        )
    await pool.close()
```

```python
"""tests/test_db.py"""
import pytest


async def test_run_migrations_creates_sources_table(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT to_regclass('public.sources')"
        )
        row = await result.fetchone()
        assert row[0] == "sources"


async def test_run_migrations_is_idempotent(db_pool):
    from pathlib import Path

    from carwatch.db import run_migrations

    applied = await run_migrations(db_pool, Path(__file__).resolve().parents[1] / "migrations")
    assert applied == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && docker compose up -d db && python3 -m pytest tests/test_db.py -v`
Expected: FAIL — `carwatch.db` doesn't exist yet, and the `carwatch_test` database doesn't exist yet either.

Create the test database once, manually:

Run: `docker compose exec db psql -U carwatch -d carwatch -c "CREATE DATABASE carwatch_test;"`

- [ ] **Step 4: Implement `db.py`**

```python
"""src/carwatch/db.py"""
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from carwatch.settings import get_settings

_pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(get_settings().database_url, min_size=1, max_size=10, open=False)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


_TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
);
"""


async def run_migrations(pool: AsyncConnectionPool, migrations_dir: Path) -> list[str]:
    if not pool._opened:
        await pool.open()
    async with pool.connection() as conn:
        await conn.execute(_TRACKING_TABLE_SQL)
        result = await conn.execute("SELECT filename FROM schema_migrations")
        applied_already = {row[0] for row in await result.fetchall()}

        applied_now = []
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in applied_already:
                continue
            await conn.execute(path.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
            )
            applied_now.append(path.name)
        return applied_now
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add src/carwatch/db.py migrations/002_sources.sql tests/test_db.py tests/conftest.py
git commit -m "feat(carwatch): add async db pool and migration runner, sources schema"
```

---

### Task 4: `robots.py` — robots.txt cache with 24h TTL

**Files:**
- Create: `agents/carwatch/src/carwatch/robots.py`
- Test: `agents/carwatch/tests/test_robots.py`

**Interfaces:**
- Produces: `async def is_allowed(url: str, user_agent: str, *, fetch_fn) -> tuple[bool, float | None]` — returns `(allowed, crawl_delay_seconds)`. `fetch_fn` is injected (an async callable `(url: str) -> httpx.Response | None`) so this module never imports `httpx` itself directly for the *actual* fetch in tests, and so `fetcher.py` (Task 8) can pass its own low-level HTTP call without creating a circular import (`robots.py` must not import `fetcher.py`).
- Produces: `clear_robots_cache() -> None` (test helper, resets the module-level cache dict).
- Consumes: nothing beyond the injected `fetch_fn`.

**Design note:** `robots.py` cannot depend on `fetcher.fetch()` (that would be circular, since `fetcher.py` calls `is_allowed()` before every fetch). It takes a raw async HTTP callable as a parameter, supplied by `fetcher.py` at call time using a private low-level client already living in `fetcher.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_robots.py"""
import time
from unittest.mock import AsyncMock

import pytest

from carwatch.robots import clear_robots_cache, is_allowed


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_robots_cache()
    yield
    clear_robots_cache()


async def test_allowed_when_no_disallow_matches():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    allowed, delay = await is_allowed(
        "https://example.com/news/article", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is True
    assert delay is None


async def test_disallowed_path_is_blocked():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    allowed, _ = await is_allowed(
        "https://example.com/admin/secret", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is False


async def test_crawl_delay_is_parsed():
    fetch_fn = AsyncMock(
        return_value=FakeResponse(200, "User-agent: *\nCrawl-delay: 10\n")
    )
    _, delay = await is_allowed(
        "https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert delay == 10.0


async def test_missing_robots_txt_allows_everything():
    fetch_fn = AsyncMock(return_value=FakeResponse(404, ""))
    allowed, _ = await is_allowed(
        "https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is True


async def test_robots_txt_is_cached_for_24h():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    await is_allowed("https://example.com/other", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    assert fetch_fn.call_count == 1


async def test_robots_txt_cache_expires_after_ttl(monkeypatch):
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    real_time = time.time
    fake_now = {"t": real_time()}
    monkeypatch.setattr("carwatch.robots.time.time", lambda: fake_now["t"])

    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    fake_now["t"] += 24 * 3600 + 1
    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)

    assert fetch_fn.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_robots.py -v`
Expected: FAIL — `carwatch.robots` doesn't exist.

- [ ] **Step 3: Implement `robots.py`**

```python
"""src/carwatch/robots.py"""
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

_CACHE_TTL_SECONDS = 24 * 3600
_cache: dict[str, tuple[float, RobotFileParser, float | None]] = {}


def clear_robots_cache() -> None:
    _cache.clear()


async def is_allowed(url: str, user_agent: str, *, fetch_fn) -> tuple[bool, float | None]:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = f"{origin}/robots.txt"

    cached = _cache.get(origin)
    if cached is not None and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        _, parser, crawl_delay = cached
        return parser.can_fetch(user_agent, url), crawl_delay

    parser = RobotFileParser()
    response = await fetch_fn(robots_url)
    if response is None or response.status_code >= 400:
        parser.parse([])
        crawl_delay = None
    else:
        parser.parse(response.text.splitlines())
        crawl_delay = parser.crawl_delay(user_agent)
        if crawl_delay is not None:
            crawl_delay = float(crawl_delay)

    _cache[origin] = (time.time(), parser, crawl_delay)
    return parser.can_fetch(user_agent, url), crawl_delay
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_robots.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/robots.py tests/test_robots.py
git commit -m "feat(carwatch): add robots.txt cache with 24h TTL and crawl-delay parsing"
```

---

### Task 5: `ratelimit.py` — per-domain interval + global concurrency

**Files:**
- Create: `agents/carwatch/src/carwatch/ratelimit.py`
- Test: `agents/carwatch/tests/test_ratelimit.py`

**Interfaces:**
- Produces: class `RateLimiter(min_interval_sec: float, global_concurrency: int, jitter_pct: float = 0.30)` with `async def acquire(self, domain: str) -> None` (blocks until this domain's semaphore-of-1 and the global concurrency semaphore both allow proceeding, and at least `min_interval_sec * (1 ± jitter_pct)` has elapsed since the last request to that same domain) and `def release(self, domain: str) -> None`. Designed for use as `async with limiter.domain(domain):`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_ratelimit.py"""
import asyncio
import time

from carwatch.ratelimit import RateLimiter


async def test_same_domain_requests_are_spaced_by_min_interval():
    limiter = RateLimiter(min_interval_sec=0.2, global_concurrency=10, jitter_pct=0.0)

    start = time.monotonic()
    async with limiter.domain("example.com"):
        pass
    async with limiter.domain("example.com"):
        pass
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2


async def test_different_domains_do_not_wait_on_each_other():
    limiter = RateLimiter(min_interval_sec=1.0, global_concurrency=10, jitter_pct=0.0)

    start = time.monotonic()
    async with limiter.domain("a.com"):
        pass
    async with limiter.domain("b.com"):
        pass
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


async def test_same_domain_concurrency_is_serialized():
    limiter = RateLimiter(min_interval_sec=0.0, global_concurrency=10, jitter_pct=0.0)
    order = []

    async def worker(name):
        async with limiter.domain("example.com"):
            order.append(f"{name}-start")
            await asyncio.sleep(0.05)
            order.append(f"{name}-end")

    await asyncio.gather(worker("a"), worker("b"))

    assert order == ["a-start", "a-end", "b-start", "b-end"] or order == [
        "b-start",
        "b-end",
        "a-start",
        "a-end",
    ]


async def test_global_concurrency_is_capped():
    limiter = RateLimiter(min_interval_sec=0.0, global_concurrency=2, jitter_pct=0.0)
    active = 0
    max_active = 0

    async def worker(domain):
        nonlocal active, max_active
        async with limiter.domain(domain):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(*(worker(f"d{i}.com") for i in range(5)))

    assert max_active <= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_ratelimit.py -v`
Expected: FAIL — `carwatch.ratelimit` doesn't exist.

- [ ] **Step 3: Implement `ratelimit.py`**

```python
"""src/carwatch/ratelimit.py"""
import asyncio
import contextlib
import random
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, min_interval_sec: float, global_concurrency: int, jitter_pct: float = 0.30):
        self._min_interval_sec = min_interval_sec
        self._jitter_pct = jitter_pct
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request_at: dict[str, float] = {}

    @contextlib.asynccontextmanager
    async def domain(self, domain: str):
        async with self._global_sem:
            async with self._domain_locks[domain]:
                await self._wait_for_interval(domain)
                try:
                    yield
                finally:
                    self._last_request_at[domain] = time.monotonic()

    async def _wait_for_interval(self, domain: str) -> None:
        last = self._last_request_at.get(domain)
        if last is None:
            return
        jitter = 1.0 + random.uniform(-self._jitter_pct, self._jitter_pct)
        required = self._min_interval_sec * jitter
        elapsed = time.monotonic() - last
        remaining = required - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_ratelimit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/ratelimit.py tests/test_ratelimit.py
git commit -m "feat(carwatch): add per-domain rate limiter with global concurrency cap"
```

---

### Task 6: `breaker.py` — circuit breaker persisted on `sources`

**Files:**
- Create: `agents/carwatch/src/carwatch/breaker.py`
- Create: `agents/carwatch/migrations/003_source_incidents.sql`
- Test: `agents/carwatch/tests/test_breaker.py`

**Note on migration numbering:** SPEC.md §4 sketches `001_init.sql` / `002_sources.sql` / `003_events.sql`. This plan adds `003_source_incidents.sql` (not in the original sketch) because the "2 pausas em 7 dias → probation" and "bloqueio após retomada → blocked" rules in SPEC.md §6 need a history of past pause/block events, which no column on `sources` alone can answer — `blocked_until` only tells you the *current* state. Fase 2's `launch_events`/`event_sources` migration is renumbered to `004_events.sql` accordingly (tracked in the Fase 2 plan).

**Interfaces:**
- Consumes: `psycopg_pool.AsyncConnectionPool` from Task 3.
- Produces: `async def record_fetch_result(pool, source_id: int, *, status: int, blocked: bool, now: datetime | None = None) -> str` — applies one fetch outcome to a source's breaker state, returns the resulting `sources.status` value as a string. `now` is injectable for testing.
- Produces: `async def check_stale_sources(pool, *, max_days: int = 21, now: datetime | None = None) -> list[int]` — returns `source_id`s with no `last_item_at` in the last `max_days` days (dead-feed alert candidates; Fase 1 just returns the list, Fase 3's `curate.py` is what actually sends the alert).

**Migration `migrations/003_source_incidents.sql`:**

```sql
CREATE TABLE source_incidents (
  id          BIGSERIAL PRIMARY KEY,
  source_id   BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,          -- 'pause' | 'block'
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON source_incidents (source_id, occurred_at DESC);
```

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_breaker.py"""
from datetime import datetime, timedelta, timezone

from carwatch.breaker import check_stale_sources, record_fetch_result


async def _insert_source(db_pool, **overrides):
    defaults = dict(
        domain="example.com",
        feed_url=f"https://example.com/rss?{overrides.get('_unique', 1)}",
        kind="rss",
        tier=1,
        status="active",
    )
    defaults.update({k: v for k, v in overrides.items() if k != "_unique"})
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, %(status)s) RETURNING id",
            defaults,
        )
        row = await result.fetchone()
        return row[0]


async def test_three_consecutive_failures_marks_broken(db_pool):
    source_id = await _insert_source(db_pool, _unique=1)

    for _ in range(3):
        status = await record_fetch_result(db_pool, source_id, status=503, blocked=False)

    assert status == "broken"


async def test_success_resets_consecutive_failures(db_pool):
    source_id = await _insert_source(db_pool, _unique=2)

    await record_fetch_result(db_pool, source_id, status=503, blocked=False)
    await record_fetch_result(db_pool, source_id, status=503, blocked=False)
    await record_fetch_result(db_pool, source_id, status=200, blocked=False)
    status = await record_fetch_result(db_pool, source_id, status=503, blocked=False)

    assert status == "active"  # only 1 consecutive failure after the reset, not broken


async def test_second_pause_within_7_days_moves_to_probation(db_pool):
    source_id = await _insert_source(db_pool, _unique=3)
    now = datetime.now(timezone.utc)

    await record_fetch_result(db_pool, source_id, status=429, blocked=True, now=now)
    async with db_pool.connection() as conn:
        await conn.execute(
            "UPDATE sources SET blocked_until = NULL WHERE id = %s", (source_id,)
        )
    status = await record_fetch_result(
        db_pool, source_id, status=429, blocked=True, now=now + timedelta(days=2)
    )

    assert status == "probation"


async def test_block_after_resuming_from_probation_is_permanent(db_pool):
    source_id = await _insert_source(db_pool, _unique=4, status="probation")
    now = datetime.now(timezone.utc)

    status = await record_fetch_result(db_pool, source_id, status=403, blocked=True, now=now)

    assert status == "blocked"


async def test_check_stale_sources_flags_sources_without_recent_items(db_pool):
    now = datetime.now(timezone.utc)
    stale_id = await _insert_source(db_pool, _unique=5)
    fresh_id = await _insert_source(db_pool, _unique=6)
    async with db_pool.connection() as conn:
        await conn.execute(
            "UPDATE sources SET last_item_at = %s WHERE id = %s",
            (now - timedelta(days=30), stale_id),
        )
        await conn.execute(
            "UPDATE sources SET last_item_at = %s WHERE id = %s",
            (now - timedelta(days=1), fresh_id),
        )

    stale = await check_stale_sources(db_pool, max_days=21, now=now)

    assert stale_id in stale
    assert fresh_id not in stale
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_breaker.py -v`
Expected: FAIL — `carwatch.breaker` doesn't exist, `source_incidents` table doesn't exist.

- [ ] **Step 3: Implement `breaker.py`**

```python
"""src/carwatch/breaker.py"""
from datetime import datetime, timedelta, timezone


async def record_fetch_result(
    pool, source_id: int, *, status: int, blocked: bool, now: datetime | None = None
) -> str:
    now = now or datetime.now(timezone.utc)
    is_failure = status >= 500 or status == 0
    is_pause_signal = blocked or status in (403, 429)

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, consecutive_failures FROM sources WHERE id = %s FOR UPDATE",
            (source_id,),
        )
        row = await result.fetchone()
        current_status, consecutive_failures = row[0], row[1]

        if is_pause_signal:
            await conn.execute(
                "INSERT INTO source_incidents (source_id, kind, occurred_at) VALUES (%s, %s, %s)",
                (source_id, "block" if current_status == "probation" else "pause", now),
            )
            if current_status == "probation":
                new_status = "blocked"
                await conn.execute(
                    "UPDATE sources SET status = %s, blocked_until = NULL WHERE id = %s",
                    (new_status, source_id),
                )
                return new_status

            recent_pauses = await conn.execute(
                "SELECT count(*) FROM source_incidents "
                "WHERE source_id = %s AND kind = 'pause' AND occurred_at > %s",
                (source_id, now - timedelta(days=7)),
            )
            pause_count = (await recent_pauses.fetchone())[0]

            new_status = "probation" if pause_count >= 2 else current_status
            blocked_until = now + timedelta(hours=24)
            await conn.execute(
                "UPDATE sources SET status = %s, blocked_until = %s, consecutive_failures = 0 "
                "WHERE id = %s",
                (new_status, blocked_until, source_id),
            )
            return new_status

        if is_failure:
            consecutive_failures += 1
            new_status = "broken" if consecutive_failures >= 3 else current_status
            await conn.execute(
                "UPDATE sources SET status = %s, consecutive_failures = %s WHERE id = %s",
                (new_status, consecutive_failures, source_id),
            )
            return new_status

        # success
        await conn.execute(
            "UPDATE sources SET consecutive_failures = 0, last_ok_at = %s WHERE id = %s",
            (now, source_id),
        )
        return current_status


async def check_stale_sources(pool, *, max_days: int = 21, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_days)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM sources "
            "WHERE status IN ('active', 'probation') "
            "AND (last_item_at IS NULL OR last_item_at < %s)",
            (cutoff,),
        )
        return [row[0] for row in await result.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_breaker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/breaker.py migrations/003_source_incidents.sql tests/test_breaker.py
git commit -m "feat(carwatch): add circuit breaker state machine over sources"
```

---

### Task 7: `fetcher.py` — the single HTTP egress point (critical path)

**Files:**
- Create: `agents/carwatch/src/carwatch/fetcher.py`
- Test: `agents/carwatch/tests/test_fetcher.py`

**Interfaces:**
- Consumes: `robots.is_allowed` (Task 4), `RateLimiter` (Task 5), `breaker.record_fetch_result` (Task 6), `get_pool` (Task 3), `get_settings` (Task 2).
- Produces: `@dataclass FetchResult(status: int, body: str | None, etag: str | None, last_modified: str | None, not_modified: bool, blocked: bool, reason: str | None)` and `async def fetch(url: str, *, kind: Literal["feed", "page"] = "page", source_id: int | None = None, timeout: float = 20.0) -> FetchResult`. Every later task that needs an HTTP resource (`ingest.py`, `probe.py`, Fase 2's `extract.py`) calls this and only this.
- Produces: `async def close_client() -> None` (closes the module-level `httpx.AsyncClient`; call at process shutdown / test teardown).

**Blocked-content markers (SPEC.md §6.8), copied verbatim:**
`"Just a moment"`, `"Attention Required"`, `"cf-browser-verification"`, `"DataDome"`, `"px-captcha"`, `"Access Denied"`, `"unusual traffic"`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_fetcher.py"""
import httpx
import pytest
import respx

from carwatch import fetcher
from carwatch.robots import clear_robots_cache


@pytest.fixture(autouse=True)
def _reset():
    clear_robots_cache()
    yield
    clear_robots_cache()


@pytest.fixture(autouse=True)
async def _close_client_after():
    yield
    await fetcher.close_client()


def _allow_robots(mock_router, host="example.com"):
    mock_router.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )


@respx.mock
async def test_fresh_fetch_returns_body_and_caches_headers():
    _allow_robots(respx)
    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(
            200,
            text="<rss>ok content long enough to not look blocked " + "x" * 500 + "</rss>",
            headers={"ETag": '"abc123"', "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT"},
        )
    )

    result = await fetcher.fetch("https://example.com/feed.xml", kind="feed")

    assert result.status == 200
    assert result.not_modified is False
    assert result.blocked is False
    assert result.etag == '"abc123"'
    assert "ok content" in result.body


@respx.mock
async def test_conditional_get_returns_not_modified_on_304(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, etag, last_modified) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'active', "
            "'\"abc123\"', 'Wed, 01 Jan 2026 00:00:00 GMT') RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/feed.xml").mock(return_value=httpx.Response(304))

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.status == 304
    assert result.not_modified is True
    assert result.body is None
    sent_headers = route.calls.last.request.headers
    assert sent_headers["If-None-Match"] == '"abc123"'


@respx.mock
async def test_short_body_is_flagged_as_blocked():
    _allow_robots(respx)
    respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text="short"))

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert result.blocked is True


@respx.mock
async def test_challenge_phrase_is_flagged_as_blocked():
    _allow_robots(respx)
    body = "Just a moment..." + "x" * 600
    respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=body))

    result = await fetcher.fetch("https://example.com/page")

    assert result.blocked is True


@respx.mock
async def test_403_is_never_retried():
    _allow_robots(respx)
    route = respx.get("https://example.com/page").mock(return_value=httpx.Response(403))

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 403
    assert route.call_count == 1


@respx.mock
async def test_503_is_retried_up_to_3_times_then_gives_up():
    _allow_robots(respx)
    route = respx.get("https://example.com/page").mock(return_value=httpx.Response(503))

    result = await fetcher.fetch("https://example.com/page", timeout=5.0)

    assert result.status == 503
    assert route.call_count == 3


@respx.mock
async def test_429_honors_retry_after_header():
    _allow_robots(respx)
    route = respx.get("https://example.com/page")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, text="fine content that is long enough " + "x" * 500),
    ]

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert route.call_count == 2


@respx.mock
async def test_robots_disallow_short_circuits_without_fetching():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    )
    route = respx.get("https://example.com/private/page")

    result = await fetcher.fetch("https://example.com/private/page")

    assert result.status == 0
    assert result.reason == "robots"
    assert route.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_fetcher.py -v`
Expected: FAIL — `carwatch.fetcher` doesn't exist.

- [ ] **Step 3: Implement `fetcher.py`**

```python
"""src/carwatch/fetcher.py"""
import random
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx

from carwatch import breaker, robots
from carwatch.db import get_pool
from carwatch.ratelimit import RateLimiter
from carwatch.settings import get_settings

_BLOCK_MARKERS = (
    "Just a moment",
    "Attention Required",
    "cf-browser-verification",
    "DataDome",
    "px-captcha",
    "Access Denied",
    "unusual traffic",
)

_client: httpx.AsyncClient | None = None
_limiter: RateLimiter | None = None


@dataclass
class FetchResult:
    status: int
    body: str | None
    etag: str | None
    last_modified: str | None
    not_modified: bool
    blocked: bool
    reason: str | None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
    return _client


def _get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = RateLimiter(
            min_interval_sec=settings.fetch_min_interval_sec,
            global_concurrency=settings.fetch_global_concurrency,
        )
    return _limiter


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _raw_get(url: str, headers: dict | None = None, timeout: float = 20.0):
    client = _get_client()
    return await client.get(url, headers=headers or {}, timeout=timeout)


def _is_blocked(status: int, body: str) -> bool:
    if status != 200:
        return False
    if len(body) < 500:
        return True
    return any(marker in body for marker in _BLOCK_MARKERS)


def _is_retryable(status: int, exc: Exception | None) -> bool:
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
    return status >= 500 or status == 429


async def fetch(
    url: str,
    *,
    kind: Literal["feed", "page"] = "page",
    source_id: int | None = None,
    timeout: float = 20.0,
) -> FetchResult:
    settings = get_settings()
    parts = urlsplit(url)
    domain = parts.netloc

    allowed, crawl_delay = await robots.is_allowed(
        url, settings.user_agent, fetch_fn=lambda robots_url: _raw_get(robots_url, timeout=10.0)
    )
    if not allowed:
        return FetchResult(0, None, None, None, False, False, "robots")

    conditional_headers: dict[str, str] = {}
    if source_id is not None:
        pool = get_pool()
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT etag, last_modified FROM sources WHERE id = %s", (source_id,)
            )
            row = await result.fetchone()
            if row:
                etag, last_modified = row
                if etag:
                    conditional_headers["If-None-Match"] = etag
                if last_modified:
                    conditional_headers["If-Modified-Since"] = last_modified

    limiter = _get_limiter()
    async with limiter.domain(domain):
        if crawl_delay:
            limiter._min_interval_sec = max(limiter._min_interval_sec, crawl_delay)

        response = None
        exc: Exception | None = None
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            attempts += 1
            exc = None
            try:
                response = await _raw_get(url, headers=conditional_headers, timeout=timeout)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                exc = e
                response = None

            if exc is None and response.status_code in (403, 404, 410):
                break
            if exc is None and not _is_retryable(response.status_code, None):
                break
            if attempts >= max_attempts:
                break

            wait_seconds = 2.0 ** attempts
            if response is not None and response.status_code in (429, 503):
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    wait_seconds = float(retry_after)
            wait_seconds *= 1.0 + random.uniform(-0.2, 0.2)
            import asyncio

            await asyncio.sleep(max(wait_seconds, 0.0))

        if exc is not None:
            if source_id is not None:
                await breaker.record_fetch_result(get_pool(), source_id, status=0, blocked=False)
            return FetchResult(0, None, None, None, False, False, str(exc))

        status = response.status_code

        if status == 304:
            if source_id is not None:
                await breaker.record_fetch_result(get_pool(), source_id, status=304, blocked=False)
            return FetchResult(304, None, None, None, True, False, None)

        body = response.text
        blocked = _is_blocked(status, body)
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")

        if source_id is not None:
            await breaker.record_fetch_result(
                get_pool(), source_id, status=status, blocked=blocked
            )
            if status == 200 and not blocked and (etag or last_modified):
                pool = get_pool()
                async with pool.connection() as conn:
                    await conn.execute(
                        "UPDATE sources SET etag = %s, last_modified = %s WHERE id = %s",
                        (etag, last_modified, source_id),
                    )

        return FetchResult(
            status=status,
            body=body if not blocked else None,
            etag=etag,
            last_modified=last_modified,
            not_modified=False,
            blocked=blocked,
            reason=None,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && docker compose up -d db && python3 -m pytest tests/test_fetcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/fetcher.py tests/test_fetcher.py
git commit -m "feat(carwatch): add fetcher — the single HTTP egress point"
```

---

### Task 8: Enforce "no HTTP outside `fetcher.py`" (SPEC.md §3 inviolable rule)

**Files:**
- Create: `agents/carwatch/tests/test_no_direct_http.py`

**Interfaces:**
- Consumes: nothing — this is a static-analysis test over the source tree.

- [ ] **Step 1: Write the test**

```python
"""tests/test_no_direct_http.py"""
import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "carwatch"
# fetcher.py is the sole egress point for anonymous web crawling (SPEC.md §3/§6).
# publishers/telegram.py is a deliberate, documented exception (see Task 15): it POSTs
# to the authenticated Telegram Bot API, not anonymous content crawling — fetcher's
# robots.txt checks, conditional-GET, and silent-block heuristics (short body < 500
# chars, which a small Telegram JSON ack would trip) don't apply and would misfire.
ALLOWED_FILES = {"fetcher.py", "telegram.py"}
FORBIDDEN_ATTRS = {"get", "post", "put", "delete", "patch", "request", "stream"}
FORBIDDEN_MODULES = {"httpx", "requests", "urllib.request"}


def _iter_python_files():
    for path in SRC_ROOT.rglob("*.py"):
        if path.name not in ALLOWED_FILES:
            yield path


def _imports_forbidden_module(tree: ast.AST) -> set[str]:
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
            for alias in node.names:
                aliases.add(alias.asname or alias.name)
    return aliases


def test_no_module_outside_fetcher_imports_http_libraries():
    offenders = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        aliases = _imports_forbidden_module(tree)
        if aliases:
            offenders.append((str(path.relative_to(SRC_ROOT)), sorted(aliases)))

    assert offenders == [], f"HTTP libraries imported outside the allowed files {ALLOWED_FILES}: {offenders}"


def test_no_module_outside_fetcher_calls_http_methods_on_a_client_named_client():
    offenders = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_ATTRS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"httpx", "client", "session", "requests"}
            ):
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")

    assert offenders == [], f"Direct HTTP calls found outside the allowed files: {offenders}"
```

- [ ] **Step 2: Run test to verify it passes against the current tree**

Run: `cd agents/carwatch && python3 -m pytest tests/test_no_direct_http.py -v`
Expected: PASS (Tasks 1–7 never import `httpx`/`requests` outside `fetcher.py`; `robots.py` takes an injected `fetch_fn` specifically to keep this test green).

This test has no separate "implementation" step — it's a guardrail against *future* regressions. It passing right now is the proof it's wired correctly. Confirm it would fail on a violation by temporarily adding `import httpx` to `src/carwatch/db.py`, re-running, seeing FAIL, then reverting:

Run: `cd agents/carwatch && echo "import httpx" >> src/carwatch/db.py && python3 -m pytest tests/test_no_direct_http.py -v; git checkout src/carwatch/db.py`
Expected: FAIL on the added line, then the file is reverted by `git checkout`.

- [ ] **Step 3: Commit**

```bash
cd agents/carwatch
git add tests/test_no_direct_http.py
git commit -m "test(carwatch): enforce single HTTP egress point via static analysis"
```

---

### Task 9: `models.py` — pydantic config schemas + `LaunchStage` enum

**Files:**
- Create: `agents/carwatch/src/carwatch/models.py`
- Test: `agents/carwatch/tests/test_models.py`
- Test fixtures: `agents/carwatch/tests/fixtures/brands_sample.yaml`, `agents/carwatch/tests/fixtures/keywords_sample.yaml`

**Interfaces:**
- Produces: `class LaunchStage(str, Enum)` with members `spy, teaser, world_premiere, specs_release, pricing, on_sale, market_launch, concept` (matches SPEC.md §5.4's `launch_stage` DB enum exactly — Task 9 of the Fase 2 plan's `dedupe.py` and Fase 3's `curate.py` both import this same enum, so its member names must never drift from these eight).
- Produces: `class BrandEntry(BaseModel)` — `name: str`, `aliases: list[str] = []`, `press_domain: str | None = None`.
- Produces: `class BrandsConfig(BaseModel)` — `brands: list[BrandEntry]`.
- Produces: `class KeywordsConfig(BaseModel)` — `positive: dict[str, list[str]]`, `negative_strong: list[str]`.
- Produces: `class ClassifyItem(BaseModel)` — `i: int`, `is_launch: bool`, `stage: LaunchStage | None`, `brand: str | None`, `model: str | None`, `confidence: float`.
- Produces: `def load_brands_config(path: Path) -> BrandsConfig`, `def load_keywords_config(path: Path) -> KeywordsConfig`.
- Consumes: nothing.

- [ ] **Step 1: Write the test fixtures**

```yaml
# tests/fixtures/brands_sample.yaml
brands:
  - name: "Volkswagen"
    aliases: ["VW"]
    press_domain: "www.volkswagen-media-services.com"
  - name: "BYD"
    aliases: ["比亚迪"]
  - name: "Chevrolet"
    aliases: ["Chevy"]
```

```yaml
# tests/fixtures/keywords_sample.yaml
positive:
  en: [unveil, reveal, debut]
  pt: [lançamento, revela]
negative_strong:
  - recall
  - earnings
```

- [ ] **Step 2: Write the failing tests**

```python
"""tests/test_models.py"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from carwatch.models import (
    ClassifyItem,
    LaunchStage,
    load_brands_config,
    load_keywords_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_brands_config_parses_aliases_and_optional_press_domain():
    cfg = load_brands_config(FIXTURES / "brands_sample.yaml")

    assert len(cfg.brands) == 3
    vw = next(b for b in cfg.brands if b.name == "Volkswagen")
    assert vw.aliases == ["VW"]
    byd = next(b for b in cfg.brands if b.name == "BYD")
    assert byd.press_domain is None


def test_load_keywords_config_parses_positive_and_negative():
    cfg = load_keywords_config(FIXTURES / "keywords_sample.yaml")

    assert "unveil" in cfg.positive["en"]
    assert "lançamento" in cfg.positive["pt"]
    assert "recall" in cfg.negative_strong


def test_launch_stage_matches_db_enum_members():
    expected = {
        "spy",
        "teaser",
        "world_premiere",
        "specs_release",
        "pricing",
        "on_sale",
        "market_launch",
        "concept",
    }
    assert {member.value for member in LaunchStage} == expected


def test_classify_item_rejects_unknown_stage():
    with pytest.raises(ValidationError):
        ClassifyItem(i=0, is_launch=True, stage="not-a-real-stage", brand="X", model="Y", confidence=0.9)


def test_classify_item_accepts_valid_stage():
    item = ClassifyItem(
        i=0, is_launch=True, stage="world_premiere", brand="BYD", model="Seal 06", confidence=0.92
    )
    assert item.stage is LaunchStage.world_premiere
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_models.py -v`
Expected: FAIL — `carwatch.models` doesn't exist.

- [ ] **Step 4: Implement `models.py`**

```python
"""src/carwatch/models.py"""
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel


class LaunchStage(str, Enum):
    spy = "spy"
    teaser = "teaser"
    world_premiere = "world_premiere"
    specs_release = "specs_release"
    pricing = "pricing"
    on_sale = "on_sale"
    market_launch = "market_launch"
    concept = "concept"


class BrandEntry(BaseModel):
    name: str
    aliases: list[str] = []
    press_domain: str | None = None


class BrandsConfig(BaseModel):
    brands: list[BrandEntry]


class KeywordsConfig(BaseModel):
    positive: dict[str, list[str]]
    negative_strong: list[str]


class ClassifyItem(BaseModel):
    i: int
    is_launch: bool
    stage: LaunchStage | None = None
    brand: str | None = None
    model: str | None = None
    confidence: float


def load_brands_config(path: Path) -> BrandsConfig:
    return BrandsConfig.model_validate(yaml.safe_load(path.read_text()))


def load_keywords_config(path: Path) -> KeywordsConfig:
    return KeywordsConfig.model_validate(yaml.safe_load(path.read_text()))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add src/carwatch/models.py tests/test_models.py tests/fixtures/brands_sample.yaml tests/fixtures/keywords_sample.yaml
git commit -m "feat(carwatch): add pydantic config schemas and LaunchStage enum"
```

---

### Task 10: `prefilter.py` — lexical filter (no LLM)

**Files:**
- Create: `agents/carwatch/src/carwatch/prefilter.py`
- Test: `agents/carwatch/tests/test_prefilter.py`

**Interfaces:**
- Consumes: `BrandsConfig`, `KeywordsConfig` from Task 9; `AsyncConnectionPool` from Task 3.
- Produces: `def passes_prefilter(title: str, summary: str | None, brands: BrandsConfig, keywords: KeywordsConfig) -> tuple[bool, str | None]` — returns `(passes, matched_brand_or_None)`.
- Produces: `async def run_prefilter(pool, brands: BrandsConfig, keywords: KeywordsConfig, logger) -> dict` — processes every `raw_items` row with `status='new'`, sets `prefilter_ok` on all of them, sets `status='filtered'` on the ones that fail, leaves `status='new'` on the ones that pass (Task 12's `classify.py` picks those up next), logs one `prefilter.batch` structlog event (`in`, `out`, `pass_rate`), and returns `{"in": int, "out": int, "pass_rate": float}`.

**Matching rule (SPEC.md §9):** passes if **(A)** title+summary contains a known brand name or alias, **(B)** contains ≥1 positive term from *any* language list (language is not reliably known at this stage, so all `positive.*` lists are checked, not just one), **AND (C)** contains no `negative_strong` term. All matching is case-insensitive substring matching (CJK terms are case-invariant, so `.lower()` is a no-op for them and harmless).

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_prefilter.py"""
from carwatch.models import BrandsConfig, KeywordsConfig
from carwatch.prefilter import passes_prefilter, run_prefilter

BRANDS = BrandsConfig.model_validate(
    {
        "brands": [
            {"name": "Volkswagen", "aliases": ["VW"]},
            {"name": "BYD", "aliases": ["比亚迪"]},
        ]
    }
)
KEYWORDS = KeywordsConfig.model_validate(
    {
        "positive": {
            "en": ["unveils", "world premiere"],
            "pt": ["lançamento", "revela"],
            "zh": ["首发", "上市"],
        },
        "negative_strong": ["recall", "quarterly results"],
    }
)


def test_passes_with_brand_and_positive_term_in_english():
    passes, brand = passes_prefilter("VW unveils new Golf", None, BRANDS, KEYWORDS)
    assert passes is True
    assert brand == "Volkswagen"


def test_passes_with_brand_and_positive_term_in_portuguese():
    passes, brand = passes_prefilter("Volkswagen revela novo modelo", None, BRANDS, KEYWORDS)
    assert passes is True


def test_passes_with_chinese_brand_and_term():
    passes, brand = passes_prefilter("比亚迪海豹06首发", None, BRANDS, KEYWORDS)
    assert passes is True
    assert brand == "BYD"


def test_fails_without_known_brand():
    passes, brand = passes_prefilter("Some startup unveils new gadget", None, BRANDS, KEYWORDS)
    assert passes is False
    assert brand is None


def test_fails_without_positive_term():
    passes, brand = passes_prefilter("Volkswagen reports quarterly deliveries", None, BRANDS, KEYWORDS)
    assert passes is False


def test_fails_on_negative_strong_term_even_with_positive_term():
    passes, _ = passes_prefilter(
        "VW unveils recall for 50000 vehicles", None, BRANDS, KEYWORDS
    )
    assert passes is False


def test_checks_summary_as_well_as_title():
    passes, _ = passes_prefilter("VW news", "the brand unveils a new Golf today", BRANDS, KEYWORDS)
    assert passes is True


async def test_run_prefilter_updates_rows_and_returns_counts(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, summary, status) VALUES "
            "(%s, 'https://example.com/a', 'hash-a', 'VW unveils new Golf', NULL, 'new'), "
            "(%s, 'https://example.com/b', 'hash-b', 'Random unrelated news', NULL, 'new')",
            (source_id, source_id),
        )

    stats = await run_prefilter(db_pool, BRANDS, KEYWORDS, logger=None)

    assert stats == {"in": 2, "out": 1, "pass_rate": 50.0}
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT title, prefilter_ok, status FROM raw_items ORDER BY id"
        )
        rows = await result.fetchall()
    assert rows[0][1] is True and rows[0][2] == "new"
    assert rows[1][1] is False and rows[1][2] == "filtered"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_prefilter.py -v`
Expected: FAIL — `carwatch.prefilter` doesn't exist.

- [ ] **Step 3: Implement `prefilter.py`**

```python
"""src/carwatch/prefilter.py"""
from carwatch.models import BrandsConfig, KeywordsConfig


def _find_matching_brand(text_lower: str, brands: BrandsConfig) -> str | None:
    for brand in brands.brands:
        candidates = [brand.name, *brand.aliases]
        if any(candidate.lower() in text_lower for candidate in candidates):
            return brand.name
    return None


def _matches_any(text_lower: str, terms: list[str]) -> bool:
    return any(term.lower() in text_lower for term in terms)


def passes_prefilter(
    title: str, summary: str | None, brands: BrandsConfig, keywords: KeywordsConfig
) -> tuple[bool, str | None]:
    text_lower = f"{title} {summary or ''}".lower()

    brand = _find_matching_brand(text_lower, brands)
    if brand is None:
        return False, None

    all_positive_terms = [term for terms in keywords.positive.values() for term in terms]
    if not _matches_any(text_lower, all_positive_terms):
        return False, brand

    if _matches_any(text_lower, keywords.negative_strong):
        return False, brand

    return True, brand


async def run_prefilter(pool, brands: BrandsConfig, keywords: KeywordsConfig, logger) -> dict:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, title, summary FROM raw_items WHERE status = 'new'"
        )
        rows = await result.fetchall()

        passed = 0
        for row_id, title, summary in rows:
            ok, _brand = passes_prefilter(title, summary, brands, keywords)
            if ok:
                passed += 1
                await conn.execute(
                    "UPDATE raw_items SET prefilter_ok = TRUE WHERE id = %s", (row_id,)
                )
            else:
                await conn.execute(
                    "UPDATE raw_items SET prefilter_ok = FALSE, status = 'filtered' WHERE id = %s",
                    (row_id,),
                )

    total = len(rows)
    pass_rate = round((passed / total * 100), 2) if total else 0.0
    stats = {"in": total, "out": passed, "pass_rate": pass_rate}
    if logger is not None:
        logger.info("prefilter.batch", **stats)
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_prefilter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/prefilter.py tests/test_prefilter.py
git commit -m "feat(carwatch): add lexical prefilter (brand + positive - negative terms)"
```

---

### Task 11: `ingest.py` — feed polling, URL normalization, dedupe-on-insert

**Files:**
- Create: `agents/carwatch/src/carwatch/ingest.py`
- Test: `agents/carwatch/tests/test_ingest.py`

**Interfaces:**
- Consumes: `fetcher.fetch` (Task 7), `AsyncConnectionPool` (Task 3).
- Produces: `def normalize_url(url: str) -> str` (SPEC.md §5.3: lowercase host, strip fragment, strip `utm_*`/`fbclid`/`gclid`/`ref`/`source` query params, strip trailing slash).
- Produces: `async def ingest_source(pool, source_id: int, feed_url: str, logger) -> dict` — fetches one source's feed, parses it, inserts new `raw_items`, returns `{"items_new": int, "not_modified": bool}`.
- Produces: `async def run_ingest(pool, logger) -> dict` — selects all eligible sources (`status IN ('active','probation')` and `blocked_until IS NULL OR blocked_until < now()`), calls `ingest_source` on each, logs one `ingest.cycle` structlog event (`sources_checked`, `items_new`, `ms`), returns the aggregate dict.

**Important:** `feedparser.parse()` must be called on the **already-fetched body string** (`fetch_result.body`), never on a URL — passing a URL would make `feedparser` perform its own HTTP request, violating the single-egress-point rule enforced by Task 8's test. XML/RSS content never starts with `http`, so `feedparser` will never mistake it for a URL to fetch.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_ingest.py"""
from datetime import datetime, timedelta, timezone

import httpx
import respx

from carwatch.ingest import ingest_source, normalize_url, run_ingest


def test_normalize_url_strips_tracking_params_and_fragment_and_trailing_slash():
    url = "HTTPS://Example.com/News/Article/?utm_source=x&fbclid=y&id=1#section"
    assert normalize_url(url) == "https://example.com/News/Article?id=1"


def test_normalize_url_lowercases_host_only():
    assert normalize_url("https://EXAMPLE.com/Path/") == "https://example.com/Path"


def _rss(items: list[tuple[str, str, datetime]]) -> str:
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{pub.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for title, link, pub in items
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{entries}</channel></rss>"


async def _insert_source(db_pool, feed_url: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', %s, 'rss', 1, 'active') RETURNING id",
            (feed_url,),
        )
        return (await result.fetchone())[0]


@respx.mock
async def test_ingest_source_inserts_recent_item_and_skips_old_one(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=5)
    old = now - timedelta(days=100)
    body = _rss(
        [
            ("Recent launch", "https://example.com/recent", recent),
            ("Old launch", "https://example.com/old", old),
        ]
    )
    respx.get("https://example.com/feed.xml").mock(return_value=httpx.Response(200, text=body))
    source_id = await _insert_source(db_pool, "https://example.com/feed.xml")

    stats = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)

    assert stats["items_new"] == 1
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT title FROM raw_items")
        rows = await result.fetchall()
    assert rows == [("Recent launch",)]


@respx.mock
async def test_ingest_source_is_idempotent_on_second_run(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    body = _rss([("Same item", "https://example.com/same", now - timedelta(days=1))])
    route = respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text=body)
    )
    source_id = await _insert_source(db_pool, "https://example.com/feed.xml")

    first = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)
    second = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)

    assert first["items_new"] == 1
    assert second["items_new"] == 0
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM raw_items")
        count = (await result.fetchone())[0]
    assert count == 1


@respx.mock
async def test_run_ingest_only_selects_active_and_probation_sources(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    body = _rss([("Item", "https://example.com/x", now)])
    respx.get("https://example.com/active-feed").mock(return_value=httpx.Response(200, text=body))

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) VALUES "
            "('example.com', 'https://example.com/active-feed', 'rss', 1, 'active'), "
            "('example.com', 'https://example.com/retired-feed', 'rss', 1, 'retired')"
        )

    stats = await run_ingest(db_pool, logger=None)

    assert stats["sources_checked"] == 1
    assert stats["items_new"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_ingest.py -v`
Expected: FAIL — `carwatch.ingest` doesn't exist.

- [ ] **Step 3: Implement `ingest.py`**

```python
"""src/carwatch/ingest.py"""
import hashlib
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from carwatch import fetcher

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {"fbclid", "gclid", "ref", "source"}
_BACKLOG_CUTOFF_DAYS = 45


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAM_NAMES and not key.startswith(_TRACKING_PARAM_PREFIXES)
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query_pairs), ""))


def _url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


async def ingest_source(pool, source_id: int, feed_url: str, logger) -> dict:
    result = await fetcher.fetch(feed_url, kind="feed", source_id=source_id)

    if result.not_modified or result.blocked or result.body is None:
        return {"items_new": 0, "not_modified": result.not_modified}

    parsed = feedparser.parse(result.body)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_BACKLOG_CUTOFF_DAYS)

    items_new = 0
    async with pool.connection() as conn:
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            published_at = None
            if entry.get("published_parsed"):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published_at is not None and published_at < cutoff:
                continue

            normalized = normalize_url(link)
            url_hash = _url_hash(normalized)
            summary = entry.get("summary")

            row = await conn.execute(
                "INSERT INTO raw_items "
                "(source_id, url, url_hash, title, summary, published_at, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'new') "
                "ON CONFLICT (url_hash) DO NOTHING RETURNING id",
                (source_id, normalized, url_hash, title, summary, published_at),
            )
            if await row.fetchone() is not None:
                items_new += 1

        if items_new > 0:
            await conn.execute(
                "UPDATE sources SET last_item_at = now() WHERE id = %s", (source_id,)
            )

    return {"items_new": items_new, "not_modified": False}


async def run_ingest(pool, logger) -> dict:
    start = time.monotonic()
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, feed_url FROM sources "
            "WHERE status IN ('active', 'probation') "
            "AND (blocked_until IS NULL OR blocked_until < now())"
        )
        eligible = await result.fetchall()

    items_new_total = 0
    for source_id, feed_url in eligible:
        stats = await ingest_source(pool, source_id, feed_url, logger)
        items_new_total += stats["items_new"]

    elapsed_ms = int((time.monotonic() - start) * 1000)
    result = {
        "sources_checked": len(eligible),
        "items_new": items_new_total,
        "ms": elapsed_ms,
    }
    if logger is not None:
        logger.info("ingest.cycle", **result)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/ingest.py tests/test_ingest.py
git commit -m "feat(carwatch): add feed ingest with URL normalization and dedupe-on-insert"
```

---

### Task 12: `llm/client.py` + `llm/classify.py` — Claude Haiku classification

**Files:**
- Create: `agents/carwatch/src/carwatch/llm/__init__.py`
- Create: `agents/carwatch/src/carwatch/llm/client.py`
- Create: `agents/carwatch/src/carwatch/llm/classify.py`
- Test: `agents/carwatch/tests/test_classify.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 2), `AsyncConnectionPool` (Task 3), `ClassifyItem`/`LaunchStage` (Task 9).
- Produces: `def get_anthropic_client() -> anthropic.AsyncAnthropic` (module-level singleton).
- Produces: `async def call_classify(system_prompt: str, user_content: str) -> str` — one raw Claude Haiku call, returns response text.
- Produces: `def build_classify_prompt() -> str` — the system prompt, copied verbatim from SPEC.md §10.
- Produces: `def parse_classify_response(raw_text: str, batch_size: int) -> list[ClassifyItem] | None` — returns `None` on any parse/validation failure (bad JSON, wrong length, indices out of order) instead of raising, so callers can degrade gracefully.
- Produces: `async def run_classify(pool, logger, limit: int = 100) -> dict` — selects up to `limit` rows from `raw_items` where `status='new' AND prefilter_ok=TRUE`, batches them 20 at a time, calls `call_classify`, writes `classified` JSONB + `status='rejected'` (if `is_launch` is false or `confidence < 0.6`) back to each row; approved rows keep `status='new'` with `classified` populated (Fase 2's `extract.py` is what advances them to `'extracted'`). Returns `{"in": int, "approved": int, "rejected": int, "parse_errors": int}`.

**Known tuning risk to flag in the README (not to silently fix):** SPEC.md §10 sets `max_tokens=300` for a batch of up to 20 classified items — at ~25-30 tokens per compact JSON object that leaves little headroom, and Claude may truncate the array on a full batch. Keep the literal spec value; if `parse_classify_response` starts returning `None` frequently in production, that is the first thing to check (raise `max_tokens` or shrink the batch), not a plan defect.

> **SUPERSEDED by the Fase 1 final review (2026-08-22).** This instruction to "keep the literal spec value" was wrong, and the risk was not merely a tuning risk: `max_tokens=300` with `BATCH_SIZE=20` is arithmetically impossible, not just tight. A full 20-item response needs ~600-800 output tokens, so *every* full batch truncated mid-JSON, `parse_classify_response` returned `None`, and `run_classify` dropped the whole batch — leaving those rows at `status='new' AND prefilter_ok=TRUE`, so the next weekly run re-attempted and **re-billed** them alongside the new ones, an unbounded backlog. Corrected to `max_tokens=1200` and `BATCH_SIZE=8`, plus split-and-retry: a batch that fails to parse is halved and each half retried independently, so a future budget mismatch costs at most the failing half. Documented in `agents/carwatch/DESIGN.md` §6. Batching below therefore reads "8 at a time", not 20.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_classify.py"""
import json
from unittest.mock import AsyncMock, patch

from carwatch.llm.classify import parse_classify_response, run_classify
from carwatch.models import LaunchStage


def test_parse_classify_response_accepts_well_formed_array():
    raw = json.dumps(
        [
            {"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92},
            {"i": 1, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.1},
        ]
    )
    items = parse_classify_response(raw, batch_size=2)

    assert items is not None
    assert items[0].stage is LaunchStage.world_premiere
    assert items[1].is_launch is False


def test_parse_classify_response_strips_markdown_fences():
    raw = "```json\n" + json.dumps([{"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.0}]) + "\n```"
    items = parse_classify_response(raw, batch_size=1)
    assert items is not None
    assert len(items) == 1


def test_parse_classify_response_rejects_wrong_length():
    raw = json.dumps([{"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.0}])
    assert parse_classify_response(raw, batch_size=2) is None


def test_parse_classify_response_rejects_invalid_json():
    assert parse_classify_response("not json at all", batch_size=1) is None


async def test_run_classify_marks_low_confidence_as_rejected(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, prefilter_ok) "
            "VALUES (%s, 'https://example.com/a', 'hash-a', 'BYD Seal 06 world premiere', 'new', TRUE)",
            (source_id,),
        )

    fake_response = json.dumps(
        [{"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.4}]
    )
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=fake_response)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats == {"in": 1, "approved": 0, "rejected": 1, "parse_errors": 0}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, classified FROM raw_items")
        row = await result.fetchone()
    assert row[0] == "rejected"
    assert row[1]["confidence"] == 0.4


async def test_run_classify_keeps_approved_items_as_new_with_classified_payload(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, prefilter_ok) "
            "VALUES (%s, 'https://example.com/a', 'hash-a', 'BYD Seal 06 world premiere', 'new', TRUE)",
            (source_id,),
        )

    fake_response = json.dumps(
        [{"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92}]
    )
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=fake_response)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats["approved"] == 1
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items")
        row = await result.fetchone()
    assert row[0] == "new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_classify.py -v`
Expected: FAIL — `carwatch.llm` package doesn't exist.

- [ ] **Step 3: Implement `llm/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Implement `llm/client.py`**

```python
"""src/carwatch/llm/client.py"""
from anthropic import AsyncAnthropic

from carwatch.settings import get_settings

_client: AsyncAnthropic | None = None

MODEL = "claude-haiku-4-5-20251001"


def get_anthropic_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


async def call_classify(system_prompt: str, user_content: str) -> str:
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
```

- [ ] **Step 5: Implement `llm/classify.py`**

```python
"""src/carwatch/llm/classify.py"""
import json
import re

from pydantic import ValidationError

from carwatch.llm.client import call_classify
from carwatch.models import ClassifyItem

SYSTEM_PROMPT = """\
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
"""

BATCH_SIZE = 20
APPROVAL_CONFIDENCE_THRESHOLD = 0.6


def build_classify_prompt() -> str:
    return SYSTEM_PROMPT


def _format_batch_for_prompt(rows: list[tuple]) -> str:
    lines = []
    for i, (_id, title, summary) in enumerate(rows):
        lines.append(f'{{"i":{i},"title":{json.dumps(title)},"summary":{json.dumps(summary or "")}}}')
    return "[\n" + ",\n".join(lines) + "\n]"


def parse_classify_response(raw_text: str, batch_size: int) -> list[ClassifyItem] | None:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        raw_items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_items, list) or len(raw_items) != batch_size:
        return None

    try:
        items = [ClassifyItem.model_validate(item) for item in raw_items]
    except ValidationError:
        return None

    if [item.i for item in items] != list(range(batch_size)):
        return None
    return items


async def run_classify(pool, logger, limit: int = 100) -> dict:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, title, summary FROM raw_items "
            "WHERE status = 'new' AND prefilter_ok = TRUE LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()

    approved = rejected = parse_errors = 0
    system_prompt = build_classify_prompt()

    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch = rows[batch_start : batch_start + BATCH_SIZE]
        user_content = _format_batch_for_prompt(batch)
        raw_response = await call_classify(system_prompt, user_content)
        items = parse_classify_response(raw_response, batch_size=len(batch))

        if items is None:
            parse_errors += len(batch)
            if logger is not None:
                logger.warning("llm.call", op="classify", status="parse_error", batch_size=len(batch))
            continue

        async with pool.connection() as conn:
            for (row_id, _title, _summary), item in zip(batch, items):
                is_approved = item.is_launch and item.confidence >= APPROVAL_CONFIDENCE_THRESHOLD
                new_status = "new" if is_approved else "rejected"
                await conn.execute(
                    "UPDATE raw_items SET classified = %s, status = %s WHERE id = %s",
                    (item.model_dump_json(), new_status, row_id),
                )
                if is_approved:
                    approved += 1
                else:
                    rejected += 1

    return {
        "in": len(rows),
        "approved": approved,
        "rejected": rejected,
        "parse_errors": parse_errors,
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_classify.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add src/carwatch/llm tests/test_classify.py
git commit -m "feat(carwatch): add Claude Haiku classify stage with batched prompt"
```

---

### Task 13: `probe.py` — initial feed discovery

**Files:**
- Create: `agents/carwatch/src/carwatch/probe.py`
- Test: `agents/carwatch/tests/test_probe.py`

**Interfaces:**
- Consumes: `fetcher.fetch` (Task 7), `BrandsConfig`/`BrandEntry` (Task 9), `AsyncConnectionPool` (Task 3).
- Produces: `async def probe_brand(brand: BrandEntry) -> tuple[str | None, str]` — returns `(feed_url_or_None, reason)`; `reason` is `"ok"` on success or a short gap reason otherwise (`"no_press_domain"`, `"no_feed_found"`).
- Produces: `async def run_probe(pool, brands: BrandsConfig, out_csv: Path, gaps_csv: Path, logger) -> dict` — probes every brand, `INSERT ... ON CONFLICT (feed_url) DO NOTHING` into `sources` with `tier=1, status='probation', brand_scope=[brand.name]` on success, writes one row per brand to `out_csv`, writes failures to `gaps_csv`. Returns `{"probed": int, "found": int, "gaps": int}`.
- Produces: `def validate_feed_content(body: str | None) -> bool` — **exported (not private)** specifically so Task 14's fixed-source seeding can reuse the exact same ≥5-entries/<90-days validation rule instead of duplicating it.

**Candidate paths, in order (SPEC.md §7), tried against `https://{press_domain}`:** `/rss`, `/feed`, `/feed.rss`, `/rss.xml`, `/feeds/news.xml`, `/en/rss`, `/news/rss`, `/press-releases/rss`. If none validate, look for `<link rel="alternate" type="application/rss+xml">` on the homepage; if that fails too, try `/sitemap.xml` then `/news-sitemap.xml`. **Validation (SPEC.md §7.5):** feed parses without a fatal error, has ≥5 entries, and the newest entry is <90 days old.

> **SUPERSEDED by the Fase 1 final review (2026-08-22).** The sitemap step was **removed** from the chain — it is now *candidate paths → link-rel* only. `feedparser.parse()` extracts zero entries from a `<urlset>` sitemap document (verified empirically), so the ≥5-entries validation above could never pass for a sitemap response: the strategy was dead code costing two extra HTTP requests per brand. Re-adding it requires a real sitemap XML parser plus its own validator. Documented in `agents/carwatch/DESIGN.md` §6.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_probe.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import respx

from carwatch.models import BrandEntry
from carwatch.probe import probe_brand, run_probe
from carwatch.models import BrandsConfig


def _valid_rss(n_entries: int = 5, newest_days_ago: int = 1) -> str:
    now = datetime.now(timezone.utc)
    items = []
    for i in range(n_entries):
        days_ago = newest_days_ago + i
        pub = (now - timedelta(days=days_ago)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>Item {i}</title><link>https://x.com/{i}</link><pubDate>{pub}</pubDate></item>")
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{''.join(items)}</channel></rss>"


def _allow_robots(host: str):
    respx.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )


@respx.mock
async def test_probe_brand_succeeds_on_first_candidate_path():
    _allow_robots("press.example.com")
    respx.get("https://press.example.com/rss").mock(
        return_value=httpx.Response(200, text=_valid_rss())
    )

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url == "https://press.example.com/rss"
    assert reason == "ok"


@respx.mock
async def test_probe_brand_falls_back_to_link_rel_discovery():
    _allow_robots("press.example.com")
    for path in ["/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml", "/en/rss", "/news/rss", "/press-releases/rss"]:
        respx.get(f"https://press.example.com{path}").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><link rel="alternate" type="application/rss+xml" '
            'href="https://press.example.com/discovered.xml"></head></html>',
        )
    )
    respx.get("https://press.example.com/discovered.xml").mock(
        return_value=httpx.Response(200, text=_valid_rss())
    )

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url == "https://press.example.com/discovered.xml"


@respx.mock
async def test_probe_brand_rejects_feed_with_too_few_entries():
    _allow_robots("press.example.com")
    for path in ["/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml", "/en/rss", "/news/rss", "/press-releases/rss"]:
        respx.get(f"https://press.example.com{path}").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/news-sitemap.xml").mock(return_value=httpx.Response(404))

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url is None
    assert reason == "no_feed_found"


async def test_probe_brand_without_press_domain_is_a_gap():
    feed_url, reason = await probe_brand(BrandEntry(name="Acme", press_domain=None))
    assert feed_url is None
    assert reason == "no_press_domain"


@respx.mock
async def test_run_probe_inserts_sources_and_writes_csvs(db_pool, tmp_path):
    _allow_robots("press.example.com")
    respx.get("https://press.example.com/rss").mock(return_value=httpx.Response(200, text=_valid_rss()))

    brands = BrandsConfig.model_validate(
        {
            "brands": [
                {"name": "Acme", "press_domain": "press.example.com"},
                {"name": "NoDomainBrand", "press_domain": None},
            ]
        }
    )
    out_csv = tmp_path / "sources.csv"
    gaps_csv = tmp_path / "gaps.csv"

    stats = await run_probe(db_pool, brands, out_csv, gaps_csv, logger=None)

    assert stats == {"probed": 2, "found": 1, "gaps": 1}
    assert out_csv.exists()
    assert "no_press_domain" in gaps_csv.read_text()
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT feed_url, status, tier FROM sources")
        row = await result.fetchone()
    assert row == ("https://press.example.com/rss", "probation", 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_probe.py -v`
Expected: FAIL — `carwatch.probe` doesn't exist.

- [ ] **Step 3: Implement `probe.py`**

```python
"""src/carwatch/probe.py"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
from selectolax.parser import HTMLParser

from carwatch import fetcher
from carwatch.models import BrandEntry, BrandsConfig

CANDIDATE_PATHS = (
    "/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml",
    "/en/rss", "/news/rss", "/press-releases/rss",
)
MAX_FEED_AGE_DAYS = 90
MIN_FEED_ENTRIES = 5


def validate_feed_content(body: str | None) -> bool:
    if not body:
        return False
    parsed = feedparser.parse(body)
    if len(parsed.entries) < MIN_FEED_ENTRIES:
        return False
    newest = None
    for entry in parsed.entries:
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if newest is None or published > newest:
                newest = published
    if newest is None:
        return False
    return datetime.now(timezone.utc) - newest < timedelta(days=MAX_FEED_AGE_DAYS)


async def _try_candidate_paths(press_domain: str) -> str | None:
    for path in CANDIDATE_PATHS:
        url = f"https://{press_domain}{path}"
        result = await fetcher.fetch(url, kind="feed")
        if result.status == 200 and not result.blocked and validate_feed_content(result.body):
            return url
    return None


async def _try_link_rel_discovery(press_domain: str) -> str | None:
    home_url = f"https://{press_domain}/"
    result = await fetcher.fetch(home_url, kind="page")
    if result.status != 200 or result.blocked or not result.body:
        return None
    tree = HTMLParser(result.body)
    node = tree.css_first('link[rel="alternate"][type="application/rss+xml"]')
    if node is None or not node.attributes.get("href"):
        return None
    candidate_url = urljoin(home_url, node.attributes["href"])
    result = await fetcher.fetch(candidate_url, kind="feed")
    if result.status == 200 and not result.blocked and validate_feed_content(result.body):
        return candidate_url
    return None


async def _try_sitemaps(press_domain: str) -> str | None:
    for path in ("/sitemap.xml", "/news-sitemap.xml"):
        url = f"https://{press_domain}{path}"
        result = await fetcher.fetch(url, kind="feed")
        if result.status == 200 and not result.blocked and validate_feed_content(result.body):
            return url
    return None


async def probe_brand(brand: BrandEntry) -> tuple[str | None, str]:
    if not brand.press_domain:
        return None, "no_press_domain"

    for strategy in (_try_candidate_paths, _try_link_rel_discovery, _try_sitemaps):
        feed_url = await strategy(brand.press_domain)
        if feed_url:
            return feed_url, "ok"

    return None, "no_feed_found"


async def run_probe(pool, brands: BrandsConfig, out_csv: Path, gaps_csv: Path, logger) -> dict:
    found = 0
    gaps = 0
    out_rows = []
    gap_rows = []

    for brand in brands.brands:
        feed_url, reason = await probe_brand(brand)
        out_rows.append({"brand": brand.name, "feed_url": feed_url or "", "reason": reason})

        if feed_url:
            found += 1
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope) "
                    "VALUES (%s, %s, 'rss', 1, 'probation', %s) "
                    "ON CONFLICT (feed_url) DO NOTHING",
                    (brand.press_domain, feed_url, [brand.name]),
                )
        else:
            gaps += 1
            gap_rows.append({"brand": brand.name, "reason": reason})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["brand", "feed_url", "reason"])
        writer.writeheader()
        writer.writerows(out_rows)

    gaps_csv.parent.mkdir(parents=True, exist_ok=True)
    with gaps_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["brand", "reason"])
        writer.writeheader()
        writer.writerows(gap_rows)

    stats = {"probed": len(brands.brands), "found": found, "gaps": gaps}
    if logger is not None:
        logger.info("probe.run", **stats)
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_probe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/probe.py tests/test_probe.py
git commit -m "feat(carwatch): add feed discovery probe (candidate paths, link-rel, sitemap)"
```

---

### Task 14: Seed config (`brands.yaml`, `keywords.yaml`, `settings.yaml`) + Tier 2–4 fixed-source seeding

**Files:**
- Create: `agents/carwatch/config/brands.yaml`
- Create: `agents/carwatch/config/keywords.yaml`
- Create: `agents/carwatch/config/settings.yaml`
- Create: `agents/carwatch/src/carwatch/discovery_seed.py`
- Test: `agents/carwatch/tests/test_discovery_seed.py`

**Interfaces:**
- Consumes: `validate_feed_content` (Task 13), `fetcher.fetch` (Task 7), `BrandsConfig` (Task 9).
- Produces: `def build_google_news_sources(brands: BrandsConfig, extra_locales: dict[str, list[str]]) -> list[dict]` — pure function, one dict per brand (and per extra locale) with keys `domain, feed_url, kind, tier, region, lang`.
- Produces: `def load_fixed_sources(settings_path: Path) -> list[dict]` — reads Tier 2/3 fixed URLs from `settings.yaml`, same dict shape.
- Produces: `async def seed_fixed_sources(pool, fixed_sources: list[dict], logger) -> dict` — validates each candidate via `fetcher.fetch` + `validate_feed_content`, inserts the valid ones into `sources` with `status='probation'`. Returns `{"attempted": int, "seeded": int}`.

**`config/brands.yaml` — 20 seed brands (SPEC.md Fase 1 acceptance: "`carwatch probe` roda sobre 20 marcas").** Press domains are best-effort from public knowledge; `carwatch probe` is what actually confirms them at runtime (SPEC.md §7: "Valide todas as URLs de feed em runtime"). Two brands are seeded with `press_domain: null` on purpose — a plausible-but-unverified guess would fail probe validation anyway and add nothing; leaving them `null` is the honest state, correctly logged as a gap and covered by the Tier 4 Google News fallback instead:

```yaml
brands:
  - name: "Toyota"
    aliases: []
    press_domain: "global.toyota"
  - name: "Volkswagen"
    aliases: ["VW"]
    press_domain: "www.volkswagen-media-services.com"
  - name: "BMW"
    aliases: []
    press_domain: "www.press.bmwgroup.com"
  - name: "Mercedes-Benz"
    aliases: ["Mercedes", "Daimler"]
    press_domain: "media.mercedes-benz.com"
  - name: "Audi"
    aliases: []
    press_domain: "www.audi-mediacenter.com"
  - name: "Porsche"
    aliases: []
    press_domain: "newsroom.porsche.com"
  - name: "Ford"
    aliases: []
    press_domain: "media.ford.com"
  - name: "General Motors"
    aliases: ["GM", "Chevrolet", "Chevy", "GMC", "Cadillac", "Buick"]
    press_domain: "media.gm.com"
  - name: "Stellantis"
    aliases: ["Jeep", "Ram", "Dodge", "Chrysler", "Peugeot", "Citroen", "Fiat"]
    press_domain: "media.stellantis.com"
  - name: "Honda"
    aliases: []
    press_domain: "hondanews.com"
  - name: "Nissan"
    aliases: []
    press_domain: "global.nissannews.com"
  - name: "Hyundai"
    aliases: []
    press_domain: "www.hyundainews.com"
  - name: "Kia"
    aliases: []
    press_domain: "www.kiamedia.com"
  - name: "BYD"
    aliases: ["比亚迪"]
    press_domain: null
  - name: "Volvo Cars"
    aliases: ["Volvo"]
    press_domain: "www.media.volvocars.com"
  - name: "Renault"
    aliases: []
    press_domain: "media.renaultgroup.com"
  - name: "Tesla"
    aliases: []
    press_domain: null
  - name: "Subaru"
    aliases: []
    press_domain: "media.subaru.com"
  - name: "Mazda"
    aliases: []
    press_domain: "newsroom.mazda.com"
  - name: "Jaguar Land Rover"
    aliases: ["Jaguar", "Land Rover", "JLR"]
    press_domain: "media.jaguarlandrover.com"
```

**`config/keywords.yaml`** — copied verbatim from SPEC.md §9:

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
  - recall
  - quarterly results
  - earnings
  - dividend
  - layoffs
  - plant closure
  - lawsuit
  - appoints
  - appointment
  - obituary
  - sponsorship
  - esports
  - stock
  - shares
  - merger talks
  - union
  - strike
  - dealer award
  - sales figures
  - monthly sales
  - market share
```

**`config/settings.yaml`** — Tier 2/3 fixed sources (SPEC.md §7 "Fontes fixas"). RSS URLs are best-effort public knowledge, validated at seed time by `seed_fixed_sources` exactly like probe-discovered feeds:

```yaml
fixed_sources:
  tier2:
    - name: "BusinessWire Automotive"
      feed_url: "https://www.businesswire.com/portal/site/home/news/industries/?vnsId=31319"
      region: "GLOBAL"
      lang: "en"
    - name: "PR Newswire Auto"
      feed_url: "https://www.prnewswire.com/rss/automotive-transportation-latest-news/automotive-transportation-latest-news-list.rss"
      region: "GLOBAL"
      lang: "en"
  tier3:
    - name: "Motor1"
      feed_url: "https://www.motor1.com/rss/articles/all/"
      region: "GLOBAL"
      lang: "en"
    - name: "Carscoops"
      feed_url: "https://www.carscoops.com/feed/"
      region: "GLOBAL"
      lang: "en"
    - name: "CarNewsChina"
      feed_url: "https://www.carnewschina.com/feed/"
      region: "CN"
      lang: "en"
    - name: "Autocar UK"
      feed_url: "https://www.autocar.co.uk/rss"
      region: "GB"
      lang: "en"
    - name: "Auto Express"
      feed_url: "https://www.autoexpress.co.uk/feed/all"
      region: "GB"
      lang: "en"
    - name: "Paultan"
      feed_url: "https://paultan.org/feed/"
      region: "MY"
      lang: "en"
    - name: "Indian Autos Blog"
      feed_url: "https://indianautosblog.com/feed"
      region: "IN"
      lang: "en"
    - name: "Quatro Rodas"
      feed_url: "https://quatrorodas.abril.com.br/feed/"
      region: "BR"
      lang: "pt"
    - name: "Response.jp"
      feed_url: "https://response.jp/rss/index.rdf"
      region: "JP"
      lang: "ja"

tier4_google_news:
  base_url: "https://news.google.com/rss/search"
  query_template: '"{brand}" (unveil OR reveal OR debut OR launch)'
  default_locale: {hl: "en", gl: "US", ceid: "US:en"}
  extra_locales:
    zh: [{hl: "zh-CN", gl: "CN", ceid: "CN:zh-Hans"}]
    in: [{hl: "en-IN", gl: "IN", ceid: "IN:en"}]
```

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_discovery_seed.py"""
from pathlib import Path

import httpx
import respx

from carwatch.discovery_seed import (
    build_google_news_sources,
    load_fixed_sources,
    seed_fixed_sources,
)
from carwatch.models import BrandsConfig

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_build_google_news_sources_one_entry_per_brand_by_default():
    brands = BrandsConfig.model_validate({"brands": [{"name": "Toyota"}, {"name": "BYD"}]})
    sources = build_google_news_sources(brands, extra_locales={})

    assert len(sources) == 2
    toyota = next(s for s in sources if s["domain"] == "news.google.com")
    assert "Toyota" in toyota["feed_url"]
    assert toyota["tier"] == 4


def test_load_fixed_sources_reads_tier2_and_tier3_from_settings_yaml():
    sources = load_fixed_sources(CONFIG_DIR / "settings.yaml")

    assert any(s["tier"] == 2 for s in sources)
    assert any(s["tier"] == 3 for s in sources)
    motor1 = next(s for s in sources if "motor1.com" in s["feed_url"])
    assert motor1["tier"] == 3


@respx.mock
async def test_seed_fixed_sources_only_inserts_validated_feeds(db_pool):
    respx.get("https://good.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://bad.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    good_feed = "<?xml version='1.0'?><rss><channel>" + "".join(
        f"<item><title>i{i}</title><link>https://x/{i}</link>"
        "<pubDate>Wed, 01 Jan 2026 00:00:00 +0000</pubDate></item>"
        for i in range(5)
    ) + "</channel></rss>"
    respx.get("https://good.example.com/feed").mock(return_value=httpx.Response(200, text=good_feed))
    respx.get("https://bad.example.com/feed").mock(return_value=httpx.Response(404))

    candidates = [
        {"domain": "good.example.com", "feed_url": "https://good.example.com/feed", "kind": "rss", "tier": 3, "region": "GLOBAL", "lang": "en"},
        {"domain": "bad.example.com", "feed_url": "https://bad.example.com/feed", "kind": "rss", "tier": 3, "region": "GLOBAL", "lang": "en"},
    ]

    stats = await seed_fixed_sources(db_pool, candidates, logger=None)

    assert stats == {"attempted": 2, "seeded": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT feed_url FROM sources")
        rows = await result.fetchall()
    assert rows == [("https://good.example.com/feed",)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_discovery_seed.py -v`
Expected: FAIL — `carwatch.discovery_seed` doesn't exist, config files don't exist yet.

- [ ] **Step 3: Implement `discovery_seed.py`**

```python
"""src/carwatch/discovery_seed.py"""
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

from carwatch import fetcher
from carwatch.models import BrandsConfig
from carwatch.probe import validate_feed_content


def build_google_news_sources(brands: BrandsConfig, extra_locales: dict) -> list[dict]:
    sources = []
    for brand in brands.brands:
        query = f'"{brand.name}" (unveil OR reveal OR debut OR launch)'
        params = urlencode({"q": query, "hl": "en", "gl": "US", "ceid": "US:en"}, quote_via=quote)
        sources.append(
            {
                "domain": "news.google.com",
                "feed_url": f"https://news.google.com/rss/search?{params}",
                "kind": "gnews",
                "tier": 4,
                "region": "GLOBAL",
                "lang": "en",
            }
        )
    return sources


def load_fixed_sources(settings_path: Path) -> list[dict]:
    data = yaml.safe_load(settings_path.read_text())
    fixed = data.get("fixed_sources", {})
    sources = []
    for tier_key, tier_num in (("tier2", 2), ("tier3", 3)):
        for entry in fixed.get(tier_key, []):
            sources.append(
                {
                    "domain": entry["feed_url"].split("/")[2],
                    "feed_url": entry["feed_url"],
                    "kind": "rss",
                    "tier": tier_num,
                    "region": entry.get("region", "GLOBAL"),
                    "lang": entry.get("lang", "en"),
                }
            )
    return sources


async def seed_fixed_sources(pool, fixed_sources: list[dict], logger) -> dict:
    seeded = 0
    for candidate in fixed_sources:
        result = await fetcher.fetch(candidate["feed_url"], kind="feed")
        if result.status != 200 or result.blocked or not validate_feed_content(result.body):
            if logger is not None:
                logger.warning("discovery_seed.rejected", feed_url=candidate["feed_url"])
            continue

        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status, region, lang) "
                "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, 'probation', %(region)s, %(lang)s) "
                "ON CONFLICT (feed_url) DO NOTHING",
                candidate,
            )
        seeded += 1

    return {"attempted": len(fixed_sources), "seeded": seeded}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_discovery_seed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add config/brands.yaml config/keywords.yaml config/settings.yaml src/carwatch/discovery_seed.py tests/test_discovery_seed.py
git commit -m "feat(carwatch): seed 20 brands + Tier 2-4 fixed sources"
```

---

### Task 15: `publishers/telegram.py` — Fase 1 smoke notification

**Files:**
- Create: `agents/carwatch/src/carwatch/publishers/__init__.py`
- Create: `agents/carwatch/src/carwatch/publishers/telegram.py`
- Test: `agents/carwatch/tests/test_telegram.py`

**Scope note:** SPEC.md §15's rich per-event message (brand/model/powertrain/price/highlights, HTML formatting) needs `launch_events`, which doesn't exist until Fase 2. Fase 1's acceptance criterion is just "Mensagem chega no Telegram" — this task sends a **plain-text summary of classify results** (what got approved this run), confirming the Telegram plumbing (bot token, chat id, HTTP call) works end to end. Fase 2's plan replaces `format_smoke_summary` with the full formatter from SPEC.md §15, reusing `send_telegram_message` unchanged.

**Why this file is exempt from the single-HTTP-egress rule:** see the comment added to Task 8's `test_no_direct_http.py` — this is an authenticated push to the Telegram Bot API, not anonymous content crawling.

**Interfaces:**
- Consumes: `AsyncConnectionPool` (Task 3).
- Produces: `async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool` — returns `False` (never raises) on any HTTP error, so a Telegram outage never crashes `weekly-run`.
- Produces: `def format_smoke_summary(items: list[dict]) -> str`.
- Produces: `async def get_approved_items_for_notification(pool) -> list[dict]` — rows from `raw_items` where `status='new' AND classified->>'is_launch' = 'true'`, shaped as `{"title": str, "url": str, "brand": str | None, "model": str | None, "stage": str | None, "confidence": float}`.
- Produces: `async def run_publish_smoke(pool, bot_token: str, chat_id: str, logger) -> dict` — ties the three functions above together, returns `{"sent": bool, "item_count": int}`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_telegram.py"""
import json

import httpx
import respx

from carwatch.publishers.telegram import (
    format_smoke_summary,
    get_approved_items_for_notification,
    run_publish_smoke,
    send_telegram_message,
)


def test_format_smoke_summary_lists_each_approved_item():
    items = [
        {"title": "BYD reveals Seal 06", "url": "https://x/1", "brand": "BYD", "model": "Seal 06", "stage": "world_premiere", "confidence": 0.92},
    ]
    text = format_smoke_summary(items)
    assert "BYD" in text
    assert "Seal 06" in text
    assert "https://x/1" in text


def test_format_smoke_summary_handles_empty_list():
    text = format_smoke_summary([])
    assert "Nenhum" in text


@respx.mock
async def test_send_telegram_message_returns_true_on_success():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    ok = await send_telegram_message("token123", "chat1", "hello")
    assert ok is True


@respx.mock
async def test_send_telegram_message_returns_false_on_http_error():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    ok = await send_telegram_message("token123", "chat1", "hello")
    assert ok is False


async def test_get_approved_items_excludes_rejected_and_unclassified(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        rejected = json.dumps({"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.1})
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) VALUES "
            "(%s, 'https://x/1', 'h1', 'Approved item', 'new', %s), "
            "(%s, 'https://x/2', 'h2', 'Rejected item', 'rejected', %s), "
            "(%s, 'https://x/3', 'h3', 'Unclassified item', 'new', NULL)",
            (source_id, approved, source_id, rejected, source_id),
        )

    items = await get_approved_items_for_notification(db_pool)

    assert len(items) == 1
    assert items[0]["brand"] == "BYD"


@respx.mock
async def test_run_publish_smoke_sends_and_reports_count(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x/1', 'h1', 'Approved item', 'new', %s)",
            (source_id, approved),
        )

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)

    assert stats == {"sent": True, "item_count": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_telegram.py -v`
Expected: FAIL — `carwatch.publishers` package doesn't exist.

- [ ] **Step 3: Implement `publishers/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Implement `publishers/telegram.py`**

```python
"""src/carwatch/publishers/telegram.py"""
import json

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def format_smoke_summary(items: list[dict]) -> str:
    if not items:
        return "CarWatch — execução semanal\n\nNenhum lançamento novo detectado nesta execução."

    lines = [f"CarWatch — execução semanal", "", f"{len(items)} item(ns) classificado(s) como lançamento:", ""]
    for i, item in enumerate(items, 1):
        brand = item.get("brand") or "?"
        model = item.get("model") or "?"
        stage = item.get("stage") or "?"
        confidence = item.get("confidence", 0.0)
        lines.append(f"{i}. {brand} {model} ({stage}) — confiança {confidence:.2f}")
        lines.append(f"   {item['url']}")
    return "\n".join(lines)


async def get_approved_items_for_notification(pool) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT title, url, classified FROM raw_items "
            "WHERE status = 'new' AND classified IS NOT NULL "
            "AND classified->>'is_launch' = 'true'"
        )
        rows = await result.fetchall()

    items = []
    for title, url, classified in rows:
        data = classified if isinstance(classified, dict) else json.loads(classified)
        items.append(
            {
                "title": title,
                "url": url,
                "brand": data.get("brand"),
                "model": data.get("model"),
                "stage": data.get("stage"),
                "confidence": data.get("confidence", 0.0),
            }
        )
    return items


async def run_publish_smoke(pool, bot_token: str, chat_id: str, logger) -> dict:
    items = await get_approved_items_for_notification(pool)
    text = format_smoke_summary(items)
    sent = await send_telegram_message(bot_token, chat_id, text)
    if logger is not None:
        logger.info("publish.sent", channel="telegram", item_count=len(items), sent=sent)
    return {"sent": sent, "item_count": len(items)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_telegram.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd agents/carwatch
git add src/carwatch/publishers tests/test_telegram.py
git commit -m "feat(carwatch): add Telegram smoke notification for classify results"
```

---

### Task 16: `cli.py` — typer commands + `weekly-run` composite

**Files:**
- Create: `agents/carwatch/src/carwatch/cli.py`
- Test: `agents/carwatch/tests/test_cli.py`

**Interfaces:**
- Consumes: every module produced in Tasks 3, 9–15.
- Produces: the `carwatch` console script (`app: typer.Typer`) declared in `pyproject.toml` (Task 1). Commands: `db migrate`, `probe`, `seed-sources`, `ingest --once`, `classify --limit N`, `publish --dry-run`, `stats`, and the composite `weekly-run` (per DESIGN.md §1 — replaces SPEC.md's daemon `carwatch run`; `extract`/`curate`/`discover`/`review` are added to this file in the Fase 2 and Fase 3 plans, and folded into `weekly-run` there). `seed-sources` is new relative to SPEC.md §17's CLI table — it's what actually calls Task 14's `seed_fixed_sources`/`build_google_news_sources` (SPEC.md §7's Tier 2-4 "fontes fixas"), which otherwise have no caller anywhere in this plan.
- `classify` internally runs `prefilter.run_prefilter` before `llm.classify.run_classify` — SPEC.md §17's CLI table has no separate `prefilter` subcommand, so this plan folds it into `classify` (prefilter is near-instant lexical work; there is no operational reason to trigger it separately).
- `weekly-run` exits non-zero if the Telegram send failed, so systemd never masks a broken run (matches the failure-signaling convention in `agents/weekly-cost-benefit/`).

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_cli.py"""
import os

from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()


def test_help_lists_all_fase1_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("db", "probe", "seed-sources", "ingest", "classify", "publish", "stats", "weekly-run"):
        assert command in result.output


def test_db_migrate_applies_migrations(monkeypatch, db_pool):
    from carwatch.settings import get_settings

    get_settings.cache_clear()
    result = runner.invoke(app, ["db", "migrate"])

    assert result.exit_code == 0
    assert "migration" in result.output.lower()


def test_stats_reports_counts_by_status(db_pool):
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "sources" in result.output
    assert "raw_items" in result.output
```

**Test environment note:** these tests run against the real test database via env vars already set in `conftest.py`/CI (`DATABASE_URL` pointed at `carwatch_test`, dummy values for `ANTHROPIC_API_KEY`/`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`BOT_INFO_URL`/`CONTACT_EMAIL` so `Settings()` construction doesn't fail). Add this block to `conftest.py`:

```python
# tests/conftest.py — append
@pytest.fixture(autouse=True, scope="session")
def _cli_test_env():
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat-id")
    os.environ.setdefault("BOT_INFO_URL", "https://example.com/bot")
    os.environ.setdefault("CONTACT_EMAIL", "test@example.com")
```

(`import os` at the top of `conftest.py`, alongside the existing imports from Task 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `carwatch.cli` doesn't exist.

- [ ] **Step 3: Implement `cli.py`**

```python
"""src/carwatch/cli.py"""
import asyncio
from pathlib import Path

import typer

from carwatch.db import close_pool, get_pool, run_migrations
from carwatch.discovery_seed import build_google_news_sources, load_fixed_sources, seed_fixed_sources
from carwatch.ingest import run_ingest
from carwatch.llm.classify import run_classify
from carwatch.logging_setup import configure_logging
from carwatch.models import load_brands_config, load_keywords_config
from carwatch.prefilter import run_prefilter
from carwatch.probe import run_probe
from carwatch.publishers.telegram import get_approved_items_for_notification, run_publish_smoke
from carwatch.settings import get_settings

app = typer.Typer()
db_app = typer.Typer()
app.add_typer(db_app, name="db")

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # agents/carwatch/
CONFIG_DIR = PACKAGE_ROOT / "config"
MIGRATIONS_DIR = PACKAGE_ROOT / "migrations"


def _logger():
    return configure_logging(get_settings().log_level)


@db_app.command("migrate")
def db_migrate():
    async def _run():
        applied = await run_migrations(get_pool(), MIGRATIONS_DIR)
        await close_pool()
        return applied

    applied = asyncio.run(_run())
    typer.echo(f"Applied {len(applied)} migration(s): {applied}")


@app.command()
def probe(
    brands: Path = typer.Option(CONFIG_DIR / "brands.yaml", "--brands"),
    out: Path = typer.Option(Path("sources.csv"), "--out"),
    gaps: Path = typer.Option(Path("gaps.csv"), "--gaps"),
):
    async def _run():
        logger = _logger()
        brands_config = load_brands_config(brands)
        stats = await run_probe(get_pool(), brands_config, out, gaps, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command(name="seed-sources")
def seed_sources():
    """One-time/on-demand registration of Tier 2-4 fixed sources (SPEC.md §7's
    "Fontes fixas") — not part of `weekly-run`, same as `probe`: SPEC.md §3's
    architecture diagram lists source discovery as something that "roda sob
    demanda", not on the ingest/curate cadence."""

    async def _run():
        logger = _logger()
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
        fixed_sources = load_fixed_sources(CONFIG_DIR / "settings.yaml")
        google_news_sources = build_google_news_sources(brands_config, extra_locales={})
        stats = await seed_fixed_sources(get_pool(), fixed_sources + google_news_sources, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def ingest(once: bool = typer.Option(False, "--once")):
    async def _run():
        logger = _logger()
        stats = await run_ingest(get_pool(), logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def classify(limit: int = typer.Option(100, "--limit")):
    async def _run():
        logger = _logger()
        pool = get_pool()
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
        keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")
        prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
        classify_stats = await run_classify(pool, logger, limit=limit)
        await close_pool()
        return {"prefilter": prefilter_stats, "classify": classify_stats}

    typer.echo(asyncio.run(_run()))


@app.command()
def publish(dry_run: bool = typer.Option(False, "--dry-run")):
    async def _run():
        logger = _logger()
        pool = get_pool()
        if dry_run:
            items = await get_approved_items_for_notification(pool)
            await close_pool()
            return {"would_send": len(items)}
        settings = get_settings()
        stats = await run_publish_smoke(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
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
        await close_pool()
        return {"sources": sources_by_status, "raw_items": items_by_status}

    typer.echo(asyncio.run(_run()))


@app.command(name="weekly-run")
def weekly_run():
    """Single composite pass: ingest -> prefilter -> classify -> publish.

    DESIGN.md §1: replaces SPEC.md's APScheduler daemon (`carwatch run`) with one
    synchronous run per systemd timer trigger. Exits non-zero if the Telegram send
    failed, so systemd doesn't mask a broken run.
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
        publish_stats = await run_publish_smoke(
            pool, settings.telegram_bot_token, settings.telegram_chat_id, logger
        )
        await close_pool()
        return {
            "ingest": ingest_stats,
            "prefilter": prefilter_stats,
            "classify": classify_stats,
            "publish": publish_stats,
        }

    result = asyncio.run(_run())
    typer.echo(result)
    if not result["publish"]["sent"]:
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/carwatch && python3 -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd agents/carwatch
git add src/carwatch/cli.py tests/test_cli.py tests/conftest.py
git commit -m "feat(carwatch): add typer CLI with weekly-run composite command"
```

---

### Task 17: `run.sh`, systemd unit + timer, README

**Files:**
- Create: `agents/carwatch/run.sh`
- Create: `agents/carwatch/systemd/carwatch.service`
- Create: `agents/carwatch/systemd/carwatch.timer`
- Create: `agents/carwatch/README.md`
- Test: `agents/carwatch/tests/test_run_sh.py`

**Interfaces:**
- Consumes: `docker-compose.yml` (Task 1), the `carwatch` entrypoint (Task 1's `Dockerfile`, `ENTRYPOINT ["carwatch"]`).
- Produces: `run.sh` — the single script systemd invokes.

**Important Docker Compose gotcha to get right:** `Dockerfile`'s `ENTRYPOINT ["carwatch"]` means `docker compose run --rm app weekly-run` executes `carwatch weekly-run` — do **not** write `docker compose run --rm app carwatch weekly-run` in `run.sh` (that would execute `carwatch carwatch weekly-run`, which fails — `carwatch` is not a registered subcommand of itself).

- [ ] **Step 1: Write `run.sh`**

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
```

- [ ] **Step 2: Write the test for `run.sh`**

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
```

- [ ] **Step 3: Make it executable and run the test**

Run: `cd agents/carwatch && chmod +x run.sh && python3 -m pytest tests/test_run_sh.py -v`
Expected: PASS

- [ ] **Step 4: Write `systemd/carwatch.service`**

Following the exact pattern of `agents/weekly-cost-benefit/systemd/weekly-cost-benefit.service`, adapted for Docker instead of a Python venv:

```ini
[Unit]
Description=CarWatch weekly run (lançamentos automotivos)

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 30
ExecStart=%h/homelab-ai/agents/carwatch/run.sh
WorkingDirectory=%h/homelab-ai/agents/carwatch
TimeoutStartSec=20min
```

- [ ] **Step 5: Write `systemd/carwatch.timer`**

Per DESIGN.md §5: Saturday morning — CarWatch doesn't use Ollama/GPU, so it doesn't need to dodge the Friday-evening slot shared by `weekly-sdlc-research` (19:00) and `weekly-cost-benefit` (20:00).

```ini
[Unit]
Description=Dispara o carwatch toda sábado 09:00 (com catch-up)

[Timer]
OnCalendar=Sat 09:00
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
```

- [ ] **Step 6: Write `README.md`**

```markdown
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
```

> **SUPERSEDED by the Fase 1 final review (2026-08-22):** the first bullet of
> that README block no longer matches the code — `max_tokens=1200` /
> `BATCH_SIZE=8` with split-and-retry. See the note under Task 12 and
> `agents/carwatch/DESIGN.md` §6; the shipped `README.md` has the corrected text.

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add run.sh systemd/carwatch.service systemd/carwatch.timer README.md tests/test_run_sh.py
git commit -m "chore(carwatch): add run.sh, systemd timer, and README"
```

---

### Task 18: End-to-end `weekly-run` test + Fase 1 acceptance checklist

**Files:**
- Create: `agents/carwatch/tests/test_e2e_fase1.py`

**Interfaces:**
- Consumes: `app` (Task 16's CLI), everything else transitively.

- [ ] **Step 1: Write the end-to-end test**

```python
"""tests/test_e2e_fase1.py"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import respx
from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()


def _feed(items: list[tuple[str, str, int]]) -> str:
    now = datetime.now(timezone.utc)
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{(now - timedelta(days=days_ago)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for title, link, days_ago in items
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{entries}</channel></rss>"


@respx.mock
async def test_weekly_run_end_to_end_ingests_classifies_and_publishes(db_pool):
    respx.get("https://press.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    body = _feed(
        [
            ("BYD unveils Seal 06 world premiere", "https://press.example.com/byd-seal-06", 1),
            ("Random unrelated corporate news", "https://press.example.com/boring", 1),
        ]
    )
    feed_route = respx.get("https://press.example.com/feed.xml").mock(
        return_value=httpx.Response(200, text=body, headers={"ETag": '"v1"'})
    )
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope) "
            "VALUES ('press.example.com', 'https://press.example.com/feed.xml', 'rss', 1, 'active', %s)",
            (["BYD"],),
        )

    async def fake_classify(system_prompt, user_content):
        payload = json.loads(user_content)
        results = []
        for item in payload:
            is_byd = "BYD" in item["title"]
            results.append(
                {
                    "i": item["i"],
                    "is_launch": is_byd,
                    "stage": "world_premiere" if is_byd else None,
                    "brand": "BYD" if is_byd else None,
                    "model": "Seal 06" if is_byd else None,
                    "confidence": 0.92 if is_byd else 0.05,
                }
            )
        return json.dumps(results)

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_classify)):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output

    async with db_pool.connection() as conn:
        rows = await (await conn.execute("SELECT title, status FROM raw_items ORDER BY id")).fetchall()
    statuses = {title: status for title, status in rows}
    assert statuses["BYD unveils Seal 06 world premiere"] == "new"  # approved, classified populated
    assert statuses["Random unrelated corporate news"] == "filtered"  # no positive keyword term

    telegram_calls = [c for c in respx.calls if "sendMessage" in str(c.request.url)]
    assert len(telegram_calls) == 1
    assert b"BYD" in telegram_calls[0].request.content

    # Second run: same feed, unchanged -> conditional GET must short-circuit via 304.
    feed_route.side_effect = None
    respx.get("https://press.example.com/feed.xml").mock(return_value=httpx.Response(304))

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_classify)):
        second_result = runner.invoke(app, ["weekly-run"])

    assert second_result.exit_code == 0, second_result.output
    async with db_pool.connection() as conn:
        count = (await (await conn.execute("SELECT count(*) FROM raw_items")).fetchone())[0]
    assert count == 2  # no duplicates inserted on the second run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/carwatch && python3 -m pytest tests/test_e2e_fase1.py -v`
Expected: FAIL at first (before Tasks 1–17 exist), then PASS once the full stack from this plan is in place — this test is the integration seam, not new production code, so there is no separate "implementation" step.

- [ ] **Step 3: Run the full test suite and confirm everything is green**

Run: `cd agents/carwatch && python3 -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 4: Run coverage on the three modules SPEC.md §20 requires at ≥90%**

Run: `cd agents/carwatch && python3 -m pytest --cov=carwatch.fetcher --cov=carwatch.prefilter --cov-report=term-missing tests/test_fetcher.py tests/test_prefilter.py`
Expected: both modules ≥90% covered. (`dedupe.py` doesn't exist until Fase 2 — its 90% target is checked there.) If either is short, add the missing test case(s) for the uncovered branch before moving on — do not lower the bar.

- [ ] **Step 5: Manual verification against SPEC.md §19 Fase 1 acceptance criteria**

Run for real, against the live internet (not mocked) — this is the one step in Fase 1 that can't be fully automated, since it validates real press-room domains:

```bash
cd agents/carwatch
docker compose up -d db
docker compose run --rm app db migrate
docker compose run --rm app probe --brands config/brands.yaml
docker compose run --rm app seed-sources
```

Check `sources.csv` and `gaps.csv`: SPEC.md §7 expects a 55–65% hit rate on `probe` alone; combined with the Tier 2–4 fixed sources registered by `seed-sources` (Task 14), total coverage of the 20 seed brands should be well above that. Confirm at least one feed source ended up `status='probation'` in the `sources` table from each of `probe` and `seed-sources`.

- [ ] **Step 6: Confirm every SPEC.md §19 Fase 1 bullet has a home**

| SPEC.md §19 Fase 1 criterion | Verified by |
|---|---|
| `docker compose up` sobe e migra sem intervenção | Task 1 Step 11, Task 16 `db migrate` |
| `carwatch probe` roda sobre 20 marcas | Task 14 (20 brands), Task 13 tests, Step 5 above |
| `carwatch ingest --once` popula `raw_items` sem duplicatas | Task 11 tests, this task's e2e test |
| Segundo `ingest` consecutivo gera ≥80% de respostas 304 | This task's e2e test (single source, 100% 304 on unchanged feed) |
| Prefilter aprova entre 8% e 20% | Task 10 (logic + `prefilter.batch` log event); **operational metric, monitored live in production, not something one small fixture proves in the abstract** — flag in the first real run's logs if it's outside range |
| Mensagem chega no Telegram | Task 15 tests, this task's e2e test |
| Teste garante que nenhum módulo fora de `fetcher.py` faz HTTP | Task 8 |
| Teste de bloqueio silencioso (`"Just a moment"` → `blocked=True`) | Task 7 |

- [ ] **Step 7: Commit**

```bash
cd agents/carwatch
git add tests/test_e2e_fase1.py
git commit -m "test(carwatch): add Fase 1 end-to-end weekly-run test"
```

---

## Self-Review

**Spec coverage:** SPEC.md §1 (non-scope respected — no CAPTCHA bypass, no proxy rotation, no frontend, no market data anywhere in this plan), §2 (stack versions pinned in Task 1's `pyproject.toml`), §3 (single fetcher egress — Task 7 + Task 8, with the documented Telegram exception), §4 (file layout matches, `models.py`/`probe.py`/`fetcher.py`/`ratelimit.py`/`breaker.py`/`robots.py` all present), §5.1–§5.3 (schema — Task 3), §6 (fetcher contract, robots, conditional GET, rate limit, retry, blocked detection — Tasks 4/5/7), breaker (Task 6), §7 (probe — Task 13, 20 brands — Task 14), §8 (ingest — Task 11), §9 (prefilter — Task 10), §10 (classify — Task 12), §16 (`.env.example`, docker-compose — Task 1), §17 (CLI surface, minus the dropped daemon mode per DESIGN.md — Task 16), §19 Fase 1 acceptance (Task 18), §20 (respx-only HTTP mocking throughout, real DB for state — noted in README), §21 (armadilhas — no `requests`, no intra-domain parallelism, no 403 retry, blocked-content validation, `temperature=0`, UTC storage — all in Global Constraints and enforced in Task 7/12 code). §5.4 (`launch_events`/`event_sources`), §11 (`extract.py`), §12 (`dedupe.py`), §13 (`curate.py`), §14 (`discovery.py`) are Fase 2/3 scope, out of this plan by design.

**Placeholder scan:** no "TBD"/"TODO" strings; every step has real code or a real shell command with expected output.

**Type consistency:** `FetchResult` fields (Task 7) match every caller's usage in Tasks 11/13/14. `LaunchStage` (Task 9) member names match SPEC.md §5.4's `launch_stage` DB enum exactly — checked because Fase 2's `dedupe.py`/`launch_events` inserts depend on this not drifting. `ClassifyItem` (Task 9) fields match `parse_classify_response`'s usage (Task 12) and the JSON shape in the SPEC.md §10 system prompt. `raw_items.status` values used across tasks (`'new'`, `'filtered'`, `'rejected'`) match the column's documented (non-enum, free `TEXT`) values in Task 3's migration — no task introduces an undocumented status string.

