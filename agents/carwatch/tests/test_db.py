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
