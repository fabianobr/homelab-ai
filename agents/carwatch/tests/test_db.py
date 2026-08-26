"""tests/test_db.py"""
import os

from psycopg_pool import AsyncConnectionPool


async def test_run_migrations_bootstraps_a_database_with_no_extensions():
    """A genuinely fresh database has no `schema_migrations` table and no
    `vector` extension until 001_init.sql creates it. configure_connection's
    vector-type registration must not prevent the pool from ever getting a
    working connection to run that migration in the first place.
    """
    from pathlib import Path

    from carwatch.db import configure_connection, run_migrations

    admin_db_url = os.environ.get(
        "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
    )
    fresh_db_name = "carwatch_test_bootstrap"
    fresh_db_url = admin_db_url.rsplit("/", 1)[0] + f"/{fresh_db_name}"

    async def _drop_fresh_db():
        admin_pool = AsyncConnectionPool(admin_db_url, min_size=1, max_size=1, open=False)
        await admin_pool.open()
        async with admin_pool.connection() as conn:
            await conn.set_autocommit(True)
            await conn.execute(f"DROP DATABASE IF EXISTS {fresh_db_name} WITH (FORCE)")
        await admin_pool.close()

    await _drop_fresh_db()  # in case a previous crashed run left it behind
    admin_pool = AsyncConnectionPool(admin_db_url, min_size=1, max_size=1, open=False)
    await admin_pool.open()
    async with admin_pool.connection() as conn:
        await conn.set_autocommit(True)
        await conn.execute(f"CREATE DATABASE {fresh_db_name}")
    await admin_pool.close()

    fresh_pool = AsyncConnectionPool(
        fresh_db_url, min_size=1, max_size=4, open=False, configure=configure_connection
    )
    await fresh_pool.open()
    try:
        applied = await run_migrations(fresh_pool, Path(__file__).resolve().parents[1] / "migrations")
        assert "001_init.sql" in applied

        async with fresh_pool.connection() as conn:
            result = await conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            row = await result.fetchone()
            assert row is not None
    finally:
        await fresh_pool.close()
        await _drop_fresh_db()


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
