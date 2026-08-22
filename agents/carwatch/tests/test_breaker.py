"""tests/test_breaker.py"""
from datetime import datetime, timedelta, timezone

from carwatch.breaker import check_stale_sources, record_fetch_result


async def _insert_source(db_pool, **overrides):
    defaults = dict(
        domain="example.com",
        feed_url=f"https://example.com/rss?{overrides.get('_unique', 1)}",
        kind="rss",
        tier=1,
        status="active",
    )
    defaults.update({k: v for k, v in overrides.items() if k != "_unique"})
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, %(status)s) RETURNING id",
            defaults,
        )
        row = await result.fetchone()
        return row[0]


async def test_three_consecutive_failures_marks_broken(db_pool):
    source_id = await _insert_source(db_pool, _unique=1)

    for _ in range(3):
        status = await record_fetch_result(db_pool, source_id, status=503, blocked=False)

    assert status == "broken"


async def test_success_resets_consecutive_failures(db_pool):
    source_id = await _insert_source(db_pool, _unique=2)

    await record_fetch_result(db_pool, source_id, status=503, blocked=False)
    await record_fetch_result(db_pool, source_id, status=503, blocked=False)
    await record_fetch_result(db_pool, source_id, status=200, blocked=False)
    status = await record_fetch_result(db_pool, source_id, status=503, blocked=False)

    assert status == "active"  # only 1 consecutive failure after the reset, not broken


async def test_second_pause_within_7_days_moves_to_probation(db_pool):
    source_id = await _insert_source(db_pool, _unique=3)
    now = datetime.now(timezone.utc)

    await record_fetch_result(db_pool, source_id, status=429, blocked=True, now=now)
    async with db_pool.connection() as conn:
        await conn.execute(
            "UPDATE sources SET blocked_until = NULL WHERE id = %s", (source_id,)
        )
    status = await record_fetch_result(
        db_pool, source_id, status=429, blocked=True, now=now + timedelta(days=2)
    )

    assert status == "probation"


async def test_block_after_resuming_from_probation_is_permanent(db_pool):
    source_id = await _insert_source(db_pool, _unique=4, status="probation")
    now = datetime.now(timezone.utc)

    status = await record_fetch_result(db_pool, source_id, status=403, blocked=True, now=now)

    assert status == "blocked"


async def test_check_stale_sources_flags_sources_without_recent_items(db_pool):
    now = datetime.now(timezone.utc)
    stale_id = await _insert_source(db_pool, _unique=5)
    fresh_id = await _insert_source(db_pool, _unique=6)
    async with db_pool.connection() as conn:
        await conn.execute(
            "UPDATE sources SET last_item_at = %s WHERE id = %s",
            (now - timedelta(days=30), stale_id),
        )
        await conn.execute(
            "UPDATE sources SET last_item_at = %s WHERE id = %s",
            (now - timedelta(days=1), fresh_id),
        )

    stale = await check_stale_sources(db_pool, max_days=21, now=now)

    assert stale_id in stale
    assert fresh_id not in stale
