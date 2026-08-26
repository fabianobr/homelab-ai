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


async def test_get_open_pool_opens_a_closed_pool():
    from carwatch.db import close_pool, get_open_pool, get_pool

    await close_pool()
    assert get_pool()._opened is False  # get_pool() alone never opens it

    pool = await get_open_pool()

    assert pool._opened is True
    assert pool is get_pool()

    await close_pool()
