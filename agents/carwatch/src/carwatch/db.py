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
