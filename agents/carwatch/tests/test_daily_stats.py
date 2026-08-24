"""tests/test_daily_stats.py"""
from datetime import date, datetime, timedelta, timezone

from carwatch.cost import record_llm_usage
from carwatch.daily_stats import aggregate_daily_stats
from carwatch.publishers.telegram import mark_published


async def test_aggregate_daily_stats_counts_todays_activity(db_pool):
    today = datetime.now(timezone.utc)
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, fetched_at) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't', 'extracted', %s)",
            (source_id, today),
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published, first_seen_at) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, TRUE, %s)",
            (today,),
        )
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1000, 500, 0.0035)

    stats = await aggregate_daily_stats(db_pool, day=today.date())

    assert stats["items_ingested"] == 1
    assert stats["items_extracted"] == 1
    assert stats["events_created"] == 1
    assert stats["llm_calls"] == 1
    assert abs(stats["llm_cost_usd"] - 0.0035) < 1e-6

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT items_ingested FROM daily_stats WHERE day = %s", (today.date(),))
        assert (await result.fetchone())[0] == 1


async def test_aggregate_daily_stats_attributes_published_event_to_the_day_it_was_actually_published(db_pool):
    """Regression test for the events_published bug: it used to count off
    `updated_at`, which mark_published() never set (only bumped by
    dedupe.py's merge logic). This constructs the actual regression scenario
    -- an event FIRST SEEN and last merge-updated 10 days ago, published only
    TODAY -- so first_seen_at/updated_at and published_at genuinely differ.
    Before the fix, this event would never be counted in ANY daily_stats row
    (aggregation only ever looks at *today*, and updated_at points 10 days in
    the past); after the fix it must be counted today, via published_at.
    """
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published, first_seen_at, updated_at) VALUES "
            "('k-old', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, "
            "FALSE, %s, %s) RETURNING id",
            (ten_days_ago, ten_days_ago),
        )
        event_id = (await result.fetchone())[0]

    await mark_published(db_pool, event_id)  # published TODAY

    stats = await aggregate_daily_stats(db_pool, day=datetime.now(timezone.utc).date())

    assert stats["events_published"] == 1
    assert stats["events_created"] == 0  # first_seen_at is 10 days ago, not today
