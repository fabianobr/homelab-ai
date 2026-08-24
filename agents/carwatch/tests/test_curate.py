"""tests/test_curate.py"""
from datetime import datetime, timedelta, timezone

from carwatch.curate import (
    apply_transitions,
    confirm_retirement,
    find_stale_brands,
    recompute_source_metrics,
    run_curate,
)


async def _insert_source(db_pool, **overrides) -> int:
    defaults = dict(
        domain="x.com", feed_url=f"https://x.com/{overrides.get('_unique', 1)}",
        kind="rss", tier=1, status="probation", brand_scope=["BYD"],
    )
    defaults.update({k: v for k, v in overrides.items() if k != "_unique"})
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope, probation_since, added_at) "
            "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, %(status)s, %(brand_scope)s, "
            "%(probation_since)s, %(added_at)s) RETURNING id",
            {**defaults, "probation_since": defaults.get("probation_since"), "added_at": defaults.get("added_at", datetime.now(timezone.utc))},
        )
        return (await result.fetchone())[0]


async def test_recompute_source_metrics_computes_yield_pct(db_pool):
    source_id = await _insert_source(db_pool, _unique=1)
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, prefilter_ok) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't', TRUE) RETURNING id",
            (source_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) VALUES (%s, %s, %s, TRUE)",
            (event_id, item_id, source_id),
        )

    await recompute_source_metrics(db_pool)

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT items_30d, events_30d, unique_events_30d, yield_pct FROM source_metrics WHERE source_id = %s",
            (source_id,),
        )
        row = await result.fetchone()
    assert row == (1, 1, 1, 100.0)


async def test_apply_transitions_promotes_high_yield_probation_source(db_pool):
    source_id = await _insert_source(db_pool, _unique=2, status="probation")
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO source_metrics (source_id, items_30d, events_30d, unique_events_30d, yield_pct) "
            "VALUES (%s, 10, 2, 1, 20.0)",
            (source_id,),
        )

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["promoted"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "active"


async def test_apply_transitions_demotes_stale_active_source(db_pool):
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    source_id = await _insert_source(db_pool, _unique=3, status="active", added_at=old_date)
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO source_metrics (source_id, items_30d, events_30d, unique_events_30d, first_seen_30d, yield_pct) "
            "VALUES (%s, 10, 0, 0, 0, 0.0)",
            (source_id,),
        )

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["demoted"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, probation_since FROM sources WHERE id = %s", (source_id,))
        row = await result.fetchone()
    assert row[0] == "probation"
    assert row[1] is not None


async def test_apply_transitions_flags_but_does_not_retire_after_60_days(db_pool):
    old_probation = datetime.now(timezone.utc) - timedelta(days=61)
    source_id = await _insert_source(db_pool, _unique=4, status="probation", probation_since=old_probation)

    transitions = await apply_transitions(db_pool)

    assert source_id in transitions["retirement_candidates"]
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "probation"  # NOT auto-retired
        result = await conn.execute("SELECT count(*) FROM pending_retirements WHERE source_id = %s", (source_id,))
        assert (await result.fetchone())[0] == 1


async def test_confirm_retirement_applies_the_human_decision(db_pool):
    old_probation = datetime.now(timezone.utc) - timedelta(days=61)
    source_id = await _insert_source(db_pool, _unique=5, status="probation", probation_since=old_probation)
    await apply_transitions(db_pool)

    await confirm_retirement(db_pool, source_id)

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM sources WHERE id = %s", (source_id,))
        assert (await result.fetchone())[0] == "retired"
        result = await conn.execute("SELECT count(*) FROM pending_retirements WHERE source_id = %s", (source_id,))
        assert (await result.fetchone())[0] == 0


async def test_find_stale_brands_flags_brand_with_no_recent_events(db_pool):
    await _insert_source(db_pool, _unique=6, brand_scope=["Toyota"])
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence, first_seen_at) "
            "VALUES ('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, now())"
        )

    stale = await find_stale_brands(db_pool)

    assert "Toyota" in stale
    assert "BYD" not in stale
