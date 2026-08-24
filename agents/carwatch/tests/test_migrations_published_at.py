"""tests/test_migrations_published_at.py"""


async def test_launch_events_has_published_at_column(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'launch_events' AND column_name = 'published_at'"
        )
        assert (await result.fetchone()) is not None
