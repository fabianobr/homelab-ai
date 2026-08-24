"""tests/test_discovery.py"""
from unittest.mock import AsyncMock, patch

from carwatch.discovery import (
    find_outbound_link_candidates,
    find_scoop_domain_candidates,
    register_and_validate_candidates,
    run_discovery,
)


async def _insert_source(db_pool, domain: str, tier: int, feed_url: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES (%s, %s, 'rss', %s, 'active') RETURNING id",
            (domain, feed_url, tier),
        )
        return (await result.fetchone())[0]


async def test_find_scoop_domain_candidates_finds_real_domain_behind_tier4_event(db_pool):
    tier4_id = await _insert_source(db_pool, "news.google.com", 4, "https://news.google.com/feed1")
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://newmedia.example.com/article', 'h1', 't') RETURNING id",
            (tier4_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'X', 'Y', 'y', 'teaser', ARRAY['h'], 0.7) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id) VALUES (%s, %s, %s)",
            (event_id, item_id, tier4_id),
        )

    candidates = await find_scoop_domain_candidates(db_pool)

    assert candidates == ["newmedia.example.com"]


async def test_find_outbound_link_candidates_matches_press_patterns(db_pool):
    tier3_id = await _insert_source(db_pool, "carscoops.com", 3, "https://carscoops.com/feed")
    body = (
        '<html><body><article>'
        '<a href="https://media.acme-motors.com/press-release">official</a>'
        '<a href="https://twitter.com/acme">social</a>'
        '</article></body></html>'
    )
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, body) "
            "VALUES (%s, 'https://carscoops.com/a', 'h1', 't', %s)",
            (tier3_id, body),
        )

    candidates = await find_outbound_link_candidates(db_pool)

    assert candidates == ["media.acme-motors.com"]


async def test_register_and_validate_candidates_only_keeps_domains_with_a_valid_feed(db_pool):
    with patch(
        "carwatch.discovery.discover_feed_for_domain",
        new=AsyncMock(side_effect=lambda d: "https://good.com/rss" if d == "good.com" else None),
    ):
        stats = await register_and_validate_candidates(db_pool, ["good.com", "bad.com"], tier=1, logger=None)

    assert stats == {"attempted": 2, "registered": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT domain, status FROM sources")
        rows = await result.fetchall()
    assert rows == [("good.com", "probation")]


async def test_run_discovery_orchestrates_both_heuristics(db_pool):
    with patch(
        "carwatch.discovery.find_scoop_domain_candidates", new=AsyncMock(return_value=["a.com"])
    ), patch(
        "carwatch.discovery.find_outbound_link_candidates", new=AsyncMock(return_value=["media.b.com"])
    ), patch(
        "carwatch.discovery.discover_feed_for_domain", new=AsyncMock(return_value="https://x/rss")
    ):
        stats = await run_discovery(db_pool, logger=None)

    assert stats["total_registered"] == 2
