"""tests/test_migrations_curation.py"""


async def test_curation_tables_and_column_exist(db_pool):
    async with db_pool.connection() as conn:
        for table in ("pending_retirements", "llm_usage", "daily_stats"):
            result = await conn.execute(f"SELECT to_regclass('public.{table}')")
            assert (await result.fetchone())[0] == table
        result = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sources' AND column_name = 'probation_since'"
        )
        assert (await result.fetchone()) is not None
