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
