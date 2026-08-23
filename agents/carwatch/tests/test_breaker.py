"""tests/test_breaker.py"""
from datetime import datetime, timedelta, timezone

from carwatch.breaker import check_stale_sources, is_source_paused, record_fetch_result


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


async def test_three_consecutive_404s_marks_broken_without_resetting_as_success(db_pool):
    """404/410 are the fetcher's "permanently gone" signals (never retried,
    see fetcher.py's 403/404/410 handling), but is_failure used to only
    catch >=500/0 — a dead feed that starts 404ing fell through to the
    success branch, resetting consecutive_failures/last_ok_at as if it were
    healthy, and never tripped 'broken' (which triggers feed rediscovery)."""
    source_id = await _insert_source(db_pool, _unique=7)

    for _ in range(3):
        status = await record_fetch_result(db_pool, source_id, status=404, blocked=False)

    assert status == "broken"

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT consecutive_failures, last_ok_at FROM sources WHERE id = %s",
            (source_id,),
        )
        consecutive_failures, last_ok_at = await result.fetchone()
    assert consecutive_failures == 3
    assert last_ok_at is None


async def test_pause_on_one_source_pauses_sibling_on_same_domain(db_pool):
    """sources.domain lets discovery_seed.build_google_news_sources() create
    several rows sharing one domain (news.google.com, one per brand). If
    that domain starts blocking broadly, a pause tripped on any one row must
    stop fetches against its siblings too, or the untripped siblings keep
    hammering an already-hostile domain."""
    domain = "shared.example.com"
    tripped_id = await _insert_source(
        db_pool, _unique=8, domain=domain, feed_url=f"https://{domain}/a"
    )
    sibling_id = await _insert_source(
        db_pool, _unique=9, domain=domain, feed_url=f"https://{domain}/b"
    )
    now = datetime.now(timezone.utc)

    await record_fetch_result(db_pool, tripped_id, status=429, blocked=True, now=now)

    assert await is_source_paused(db_pool, sibling_id, now=now) is True

    # record_fetch_result must still only have written the tripped row —
    # the sibling's own row is untouched.
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, blocked_until FROM sources WHERE id = %s", (sibling_id,)
        )
        status, blocked_until = await result.fetchone()
    assert status == "active"
    assert blocked_until is None


async def test_sources_on_different_domains_do_not_pause_each_other(db_pool):
    id_a = await _insert_source(
        db_pool, _unique=10, domain="a.example.com", feed_url="https://a.example.com/rss"
    )
    id_b = await _insert_source(
        db_pool, _unique=11, domain="b.example.com", feed_url="https://b.example.com/rss"
    )
    now = datetime.now(timezone.utc)

    await record_fetch_result(db_pool, id_a, status=429, blocked=True, now=now)

    assert await is_source_paused(db_pool, id_b, now=now) is False


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
