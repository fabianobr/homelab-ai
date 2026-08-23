"""src/carwatch/db.py"""
from pathlib import Path

from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from carwatch.settings import get_settings

_pool: AsyncConnectionPool | None = None


async def configure_connection(conn) -> None:
    """Register pgvector's type adapters on a pooled connection.

    Lets Python `list[float]` values bind directly to `vector` columns and
    lets `vector` columns come back as numpy arrays instead of raw text.
    Passed as the pool's `configure=` callback so it runs on every connection
    the pool opens, not just the first one.
    """
    await register_vector_async(conn)


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=10,
            open=False,
            configure=configure_connection,
        )
    return _pool


async def _ensure_open(pool: AsyncConnectionPool) -> AsyncConnectionPool:
    if not pool._opened:
        await pool.open()
    return pool


async def get_open_pool() -> AsyncConnectionPool:
    """Return the module-level pool from get_pool(), opened if necessary.

    get_pool() constructs the pool lazily (open=False); calling .connection()
    on an unopened pool raises PoolClosed. Any caller that wants to use the
    singleton pool (as opposed to a pool it manages itself, e.g. a test
    fixture) should call this instead of get_pool() directly.
    """
    return await _ensure_open(get_pool())


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
    pool = await _ensure_open(pool)
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
