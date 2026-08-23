"""tests/test_migrations_events.py"""


async def test_launch_events_and_event_sources_tables_exist(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT to_regclass('public.launch_events')")
        assert (await result.fetchone())[0] == "launch_events"
        result = await conn.execute("SELECT to_regclass('public.event_sources')")
        assert (await result.fetchone())[0] == "event_sources"


async def test_launch_stage_enum_has_all_eight_values(db_pool):
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT unnest(enum_range(NULL::launch_stage))::text"
        )
        values = {row[0] for row in await result.fetchall()}
    assert values == {
        "spy", "teaser", "world_premiere", "specs_release",
        "pricing", "on_sale", "market_launch", "concept",
    }
