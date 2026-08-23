"""tests/conftest.py"""
import os
from pathlib import Path

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from carwatch.db import configure_connection, run_migrations
from carwatch.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
)


@pytest.fixture(autouse=True)
def _database_url_matches_test_db(monkeypatch):
    """Force carwatch.db.get_pool()/get_open_pool() to resolve to the same
    database as the db_pool fixture below.

    .env's DATABASE_URL points at the dev `carwatch` database, which has no
    migrated schema. Without this, any production code that calls
    get_pool()/get_open_pool() directly (fetcher.fetch() with a source_id,
    and later ingest.py/probe.py/discovery_seed.py/cli.py) would silently
    talk to a different, empty database than the one the db_pool fixture
    just set up and inserted rows into.
    """
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fast_rate_limiter(monkeypatch):
    """Override the rate limiter to have zero delay in tests, avoiding real
    3-second intervals during test sequences that make multiple same-domain
    fetch() calls.
    """
    from carwatch.ratelimit import RateLimiter
    from carwatch import fetcher

    fast_limiter = RateLimiter(min_interval_sec=0.0, global_concurrency=50, jitter_pct=0.0)
    monkeypatch.setattr(fetcher, "_limiter", fast_limiter)
    yield


@pytest_asyncio.fixture
async def db_pool():
    pool = AsyncConnectionPool(
        TEST_DB_URL, min_size=1, max_size=4, open=False, configure=configure_connection
    )
    await pool.open()
    await run_migrations(pool, REPO_ROOT / "migrations")
    yield pool
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE raw_items, source_metrics, sources, launch_events, "
            "event_sources, source_incidents RESTART IDENTITY CASCADE"
        )
    await pool.close()


@pytest.fixture(autouse=True, scope="session")
def _cli_test_env():
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat-id")
    os.environ.setdefault("BOT_INFO_URL", "https://example.com/bot")
    os.environ.setdefault("CONTACT_EMAIL", "test@example.com")
